"""
Dashboard API: purchase order and donation records, totalled and filtered by expiry, item, category and storage location.
Data is limited by role like the other APIs: storage location users only see their own storage location,
master and all areas users see every storage location and can narrow it down with the filters.
"""
import datetime

from django.db.models import Case, CharField, Count, F, FloatField, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, TruncDate, TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Donation, PurchaseOrder
from .permissions import limit_to_location, sees_all_locations
from .serializers import user_info

EXPIRY_STATUSES = ('expired', 'expiring', 'valid', 'no_expiry')
DEFAULT_EXPIRING_DAYS = 30
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

# Per source: the record's own columns behind the shared dashboard columns.
SOURCES = {
    'purchase_order': {
        'model': PurchaseOrder,
        'record_id': F('po_id'),
        'record_no': F('po_number'),
        'record_date': Coalesce('received_date', 'invoice_date', TruncDate('created_at')),
        'party_name': F('supplier__supplier_name'),
        'unit_value': F('unit_price'),
        'batch': Value(None),
    },
    'donation': {
        'model': Donation,
        'record_id': F('donation_id'),
        'record_no': F('donation_no'),
        'record_date': Coalesce('received_date', 'donation_date'),
        'party_name': F('donor__donor_name'),
        'unit_value': F('estimated_unit_value'),
        'batch': F('batch_no'),
    },
}

# Columns of a record row, in the same order for every source so they can be combined.
RECORD_FIELDS = (
    'source', 'record_id', 'record_no', 'record_date', 'party_name',
    'item_id', 'item_name', 'item_code', 'category_id', 'category_name',
    'st_loc_id', 'storage_location_name', 'location_id', 'location_name', 'shed_name',
    'quantity', 'unit_value', 'value', 'batch', 'manufacturing_date', 'expiry_date', 'expiry_status',
)


def id_list(params, name):
    """`?name=3` or `?name=3,7` as a list of ids."""
    raw = params.get(name)
    if not raw:
        return []
    try:
        return [int(value) for value in raw.split(',') if value.strip()]
    except ValueError:
        raise ValidationError({name: 'Use an id or comma-separated ids, e.g. 3 or 3,7.'})


def choice_list(params, name, choices):
    values = [value for value in params.get(name, '').split(',') if value]
    if set(values) - set(choices):
        raise ValidationError({name: f'Use one or more of: {", ".join(choices)}.'})
    return values


def int_param(params, name, default, minimum, maximum):
    try:
        value = int(params.get(name, default))
    except ValueError:
        raise ValidationError({name: 'Use a whole number.'})
    if not minimum <= value <= maximum:
        raise ValidationError({name: f'Use {minimum} to {maximum}.'})
    return value


def date_param(params, name):
    raw = params.get(name)
    if not raw:
        return None
    value = parse_date(raw)
    if value is None:
        raise ValidationError({name: 'Use a date as YYYY-MM-DD.'})
    return value


def dashboard_filters(params):
    """Validated filters from the query string."""
    return {
        'source': choice_list(params, 'source', tuple(SOURCES)),
        'category': id_list(params, 'category'),
        'item': id_list(params, 'item'),
        'storage_location': id_list(params, 'storage_location'),
        'location': id_list(params, 'location'),
        'expiry_status': choice_list(params, 'expiry_status', EXPIRY_STATUSES),
        'expiring_days': int_param(params, 'expiring_days', DEFAULT_EXPIRING_DAYS, 0, 3650),
        'expiry_from': date_param(params, 'expiry_from'),
        'expiry_to': date_param(params, 'expiry_to'),
        'date_from': date_param(params, 'date_from'),
        'date_to': date_param(params, 'date_to'),
    }


def source_records(source, user, filters, today):
    """One source's records (role scoped) with the shared dashboard columns and every filter applied."""
    config = SOURCES[source]
    expiring_until = today + datetime.timedelta(days=filters['expiring_days'])
    queryset = limit_to_location(config['model'].objects.all(), user).annotate(
        source=Value(source, output_field=CharField()),
        record_id=config['record_id'],
        record_no=Cast(config['record_no'], CharField()),
        record_date=config['record_date'],
        party_name=Cast(config['party_name'], CharField()),
        item_name=F('item__item_name'),
        item_code=F('item__item_code'),
        category_id=F('item__item_category'),
        category_name=F('item__item_category__category_name'),
        st_loc_id=F('storage_location'),
        storage_location_name=F('storage_location__details'),
        location_id=F('storage_location__location'),
        location_name=F('storage_location__location__location_name'),
        shed_name=F('sto_shed__shed__shed_name'),
        batch=Cast(config['batch'], CharField()),
        unit_value=Cast(config['unit_value'], FloatField()),
        value=Cast(F('quantity'), FloatField()) * Cast(config['unit_value'], FloatField()),
        expiry_status=Case(
            When(expiry_date__isnull=True, then=Value('no_expiry')),
            When(expiry_date__lt=today, then=Value('expired')),
            When(expiry_date__lte=expiring_until, then=Value('expiring')),
            default=Value('valid'),
            output_field=CharField(),
        ),
    )
    lookups = {
        'category': 'item__item_category__in',
        'item': 'item__in',
        'storage_location': 'storage_location__in',
        'location': 'storage_location__location__in',
        'expiry_status': 'expiry_status__in',
        'expiry_from': 'expiry_date__gte',
        'expiry_to': 'expiry_date__lte',
        'date_from': 'record_date__gte',
        'date_to': 'record_date__lte',
    }
    for name, lookup in lookups.items():
        if filters[name]:
            queryset = queryset.filter(**{lookup: filters[name]})
    return queryset


def filtered_records(user, filters, today):
    """{source: queryset} for the chosen sources (all when no `source` filter is given)."""
    return {source: source_records(source, user, filters, today) for source in filters['source'] or SOURCES}


def totals(querysets, *group_by, **names):
    """Quantity, value and number of records per group over all sources, largest quantity first."""
    merged = {}
    for queryset in querysets:
        rows = queryset.values(*group_by, **names).annotate(
            total_quantity=Sum('quantity'), total_value=Sum('value'), records=Count('pk'),
        ).order_by()
        for row in rows:
            key = tuple(row[name] for name in (*group_by, *names))
            if key not in merged:
                merged[key] = {**row, 'total_quantity': 0, 'total_value': 0, 'records': 0}
            merged[key]['total_quantity'] += row['total_quantity'] or 0
            merged[key]['total_value'] += row['total_value'] or 0
            merged[key]['records'] += row['records']
    return sorted(merged.values(), key=lambda row: row['total_quantity'], reverse=True)


def distinct_count(querysets, field):
    values = set()
    for queryset in querysets:
        values.update(queryset.exclude(**{f'{field}__isnull': True}).values_list(field, flat=True).distinct())
    return len(values)


def records_page(querysets, page, page_size):
    """The records themselves: soonest expiry first, records without expiry last, newest first within that."""
    querysets = [queryset.values(*RECORD_FIELDS) for queryset in querysets]
    combined = querysets[0].union(*querysets[1:], all=True) if len(querysets) > 1 else querysets[0]
    combined = combined.order_by(F('expiry_date').asc(nulls_last=True), F('record_date').desc(nulls_last=True))
    start = (page - 1) * page_size
    return list(combined[start:start + page_size])


def param(name, type_, description, **kwargs):
    return openapi.Parameter(name, openapi.IN_QUERY, type=type_, description=description, **kwargs)


class DashboardView(APIView):
    """
    GET /api/dashboard/ returns purchase order and donation records with totals for dashboard cards and charts.
    Every filter is optional and filters can be combined; id filters take one id or comma-separated ids.
    """

    @swagger_auto_schema(manual_parameters=[
        param('source', openapi.TYPE_STRING, 'purchase_order or donation (default both)'),
        param('category', openapi.TYPE_STRING, 'Category id(s), e.g. 2 or 2,5'),
        param('item', openapi.TYPE_STRING, 'Item id(s)'),
        param('storage_location', openapi.TYPE_STRING,
              'Storage location (warehouse) id(s); location users only get their own'),
        param('location', openapi.TYPE_STRING, 'Area (district) id(s)'),
        param('expiry_status', openapi.TYPE_STRING, 'expired, expiring, valid or no_expiry (comma-separated for several)'),
        param('expiring_days', openapi.TYPE_INTEGER,
              f'Days ahead that count as "expiring" (default {DEFAULT_EXPIRING_DAYS})'),
        param('expiry_from', openapi.TYPE_STRING, 'Expiry date on or after (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('expiry_to', openapi.TYPE_STRING, 'Expiry date on or before (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('date_from', openapi.TYPE_STRING, 'Received/record date on or after (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('date_to', openapi.TYPE_STRING, 'Received/record date on or before (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('page', openapi.TYPE_INTEGER, 'Page of `records` (default 1)'),
        param('page_size', openapi.TYPE_INTEGER, f'Records per page (default {DEFAULT_PAGE_SIZE}, max {MAX_PAGE_SIZE})'),
    ])
    def get(self, request):
        params = request.query_params
        filters = dashboard_filters(params)
        page = int_param(params, 'page', 1, 1, 100000)
        page_size = int_param(params, 'page_size', DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        today = timezone.localdate()
        records = filtered_records(request.user, filters, today)
        querysets = list(records.values())

        by_expiry = {row['expiry_status']: row for row in totals(querysets, 'expiry_status')}
        expiry = [
            by_expiry.get(status, {'expiry_status': status, 'total_quantity': 0, 'total_value': 0, 'records': 0})
            for status in EXPIRY_STATUSES
        ]
        record_count = sum(row['records'] for row in expiry)

        user = user_info(request.user)
        return Response({
            'scope': {
                'role': user['role'],
                'sees_all_locations': sees_all_locations(request.user),
                'storage_location_id': user['storage_location_id'],
                'storage_location_name': user['storage_location_name'],
            },
            'filters': {
                **filters,
                'today': today,
                'expiring_until': today + datetime.timedelta(days=filters['expiring_days']),
            },
            'summary': {
                'records': record_count,
                'total_quantity': sum(row['total_quantity'] for row in expiry),
                'total_value': sum(row['total_value'] for row in expiry),
                'items': distinct_count(querysets, 'item'),
                'categories': distinct_count(querysets, 'category_id'),
                'storage_locations': distinct_count(querysets, 'storage_location'),
                'expired_records': by_expiry.get('expired', {}).get('records', 0),
                'expiring_records': by_expiry.get('expiring', {}).get('records', 0),
            },
            'expiry': expiry,
            'by_source': totals(querysets, 'source'),
            'by_category': totals(querysets, 'category_id', 'category_name'),
            'by_storage_location': totals(querysets, 'st_loc_id', 'storage_location_name', 'location_name'),
            'by_item': totals(querysets, 'item_id', 'item_name', 'item_code', 'category_name'),
            'by_month': sorted(
                totals(querysets, month=TruncMonth('record_date')),
                key=lambda row: (row['month'] is None, row['month'] or datetime.date.min),
            ),
            'records': {
                'count': record_count,
                'page': page,
                'page_size': page_size,
                'results': records_page(querysets, page, page_size),
            },
        })
