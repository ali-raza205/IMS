"""
Dashboard API: inventory transactions, totalled and filtered by type, expiry, item, category and storage location.
Data is limited by role like the other APIs: storage location users only see their own storage location,
master and all areas users see every storage location and can narrow it down with the filters.
"""
import datetime

from django.db.models import Case, CharField, Count, F, FloatField, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InventoryTransaction, TransactionType
from .permissions import limit_to_location, sees_all_locations
from .serializers import user_info

EXPIRY_STATUSES = ('expired', 'expiring', 'valid', 'no_expiry')
DEFAULT_EXPIRING_DAYS = 30
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

DIRECTIONS = tuple(direction for direction, _ in TransactionType.DIRECTION_CHOICES)

# Columns of a record row.
RECORD_FIELDS = (
    'record_id', 'record_no', 'record_date', 'txn_type_id', 'txn_type_name', 'direction', 'party_name',
    'item_id', 'item_name', 'item_code', 'category_id', 'category_name',
    'sub_cat_id', 'sub_cat_name', 'spec_id', 'spec_name', 'status_id', 'status_name',
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
        'txn_type': id_list(params, 'txn_type'),
        'party': id_list(params, 'party'),
        'direction': choice_list(params, 'direction', DIRECTIONS),
        'category': id_list(params, 'category'),
        'item': id_list(params, 'item'),
        'sub_category': id_list(params, 'sub_category'),
        'spec': id_list(params, 'spec'),
        'status': id_list(params, 'status'),
        'storage_location': id_list(params, 'storage_location'),
        'location': id_list(params, 'location'),
        'expiry_status': choice_list(params, 'expiry_status', EXPIRY_STATUSES),
        'expiring_days': int_param(params, 'expiring_days', DEFAULT_EXPIRING_DAYS, 0, 3650),
        'expiry_from': date_param(params, 'expiry_from'),
        'expiry_to': date_param(params, 'expiry_to'),
        'date_from': date_param(params, 'date_from'),
        'date_to': date_param(params, 'date_to'),
    }


def filtered_records(user, filters, today):
    """Transactions (role scoped) with the dashboard columns and every filter applied.
    A transaction counts at its receiving storage location, or its sending one when it has none (dispatch)."""
    expiring_until = today + datetime.timedelta(days=filters['expiring_days'])
    queryset = limit_to_location(InventoryTransaction.objects.all(), user).annotate(
        record_id=F('txn_id'),
        record_no=F('txn_no'),
        record_date=F('txn_date'),
        txn_type_name=F('txn_type__type_name'),
        direction=F('txn_type__direction'),
        party_name=Coalesce('party__party_name', 'issued_to', output_field=CharField()),
        item_name=F('item__item_name'),
        item_code=F('item__item_code'),
        category_id=F('item__item_category'),
        category_name=F('item__item_category__category_name'),
        sub_cat_name=F('sub_cat__sub_cat_name'),
        spec_name=F('spec__spec_name'),
        status_name=F('status__status_name'),
        st_loc_id=Coalesce('to_storage_location', 'from_storage_location'),
        storage_location_name=Coalesce('to_storage_location__details', 'from_storage_location__details'),
        location_id=Coalesce('to_storage_location__location', 'from_storage_location__location'),
        location_name=Coalesce('to_storage_location__location__location_name',
                               'from_storage_location__location__location_name'),
        shed_name=Coalesce('to_sto_shed__shed__shed_name', 'from_sto_shed__shed__shed_name'),
        batch=F('batch_no'),
        unit_value=Cast('unit_price', FloatField()),
        value=Cast(F('quantity'), FloatField()) * Cast('unit_price', FloatField()),
        expiry_status=Case(
            When(expiry_date__isnull=True, then=Value('no_expiry')),
            When(expiry_date__lt=today, then=Value('expired')),
            When(expiry_date__lte=expiring_until, then=Value('expiring')),
            default=Value('valid'),
            output_field=CharField(),
        ),
    )
    lookups = {
        'txn_type': 'txn_type__in',
        'party': 'party__in',
        'direction': 'direction__in',
        'category': 'item__item_category__in',
        'item': 'item__in',
        'sub_category': 'sub_cat__in',
        'spec': 'spec__in',
        'status': 'status__in',
        'storage_location': 'st_loc_id__in',
        'location': 'location_id__in',
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


def totals(queryset, *group_by, **names):
    """Quantity, value and number of records per group, largest quantity first."""
    rows = queryset.values(*group_by, **names).annotate(
        total_quantity=Coalesce(Sum('quantity'), 0, output_field=FloatField()),
        total_value=Coalesce(Sum('value'), 0, output_field=FloatField()),
        records=Count('pk'),
    ).order_by('-total_quantity')
    return list(rows)


def distinct_count(queryset, field):
    return queryset.exclude(**{f'{field}__isnull': True}).values(field).distinct().count()


def records_page(queryset, page, page_size):
    """The records themselves: soonest expiry first, records without expiry last, newest first within that."""
    records = queryset.values(*RECORD_FIELDS).order_by(
        F('expiry_date').asc(nulls_last=True), F('record_date').desc(nulls_last=True), F('record_id').desc(),
    )
    start = (page - 1) * page_size
    return list(records[start:start + page_size])


def param(name, type_, description, **kwargs):
    return openapi.Parameter(name, openapi.IN_QUERY, type=type_, description=description, **kwargs)


class DashboardView(APIView):
    """
    GET /api/dashboard/ returns inventory transactions with totals for dashboard cards and charts.
    Every filter is optional and filters can be combined; id filters take one id or comma-separated ids.
    """

    @swagger_auto_schema(manual_parameters=[
        param('txn_type', openapi.TYPE_STRING, 'Transaction type id(s), e.g. 1 or 1,2 (default all)'),
        param('party', openapi.TYPE_STRING, 'Supplier / donor / NDMA party id(s)'),
        param('direction', openapi.TYPE_STRING, 'in, out or transfer (comma-separated for several; default all)'),
        param('category', openapi.TYPE_STRING, 'Category id(s), e.g. 2 or 2,5'),
        param('item', openapi.TYPE_STRING, 'Item id(s)'),
        param('sub_category', openapi.TYPE_STRING, 'Item sub category id(s)'),
        param('spec', openapi.TYPE_STRING, 'Item spec id(s)'),
        param('status', openapi.TYPE_STRING, 'Status id(s): 1 Serviceable, 2 Non Serviceable'),
        param('storage_location', openapi.TYPE_STRING,
              'Storage location (warehouse) id(s); location users only get their own'),
        param('location', openapi.TYPE_STRING, 'Area (district) id(s)'),
        param('expiry_status', openapi.TYPE_STRING, 'expired, expiring, valid or no_expiry (comma-separated for several)'),
        param('expiring_days', openapi.TYPE_INTEGER,
              f'Days ahead that count as "expiring" (default {DEFAULT_EXPIRING_DAYS})'),
        param('expiry_from', openapi.TYPE_STRING, 'Expiry date on or after (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('expiry_to', openapi.TYPE_STRING, 'Expiry date on or before (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('date_from', openapi.TYPE_STRING, 'Transaction date on or after (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('date_to', openapi.TYPE_STRING, 'Transaction date on or before (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
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

        by_expiry = {row['expiry_status']: row for row in totals(records, 'expiry_status')}
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
                'items': distinct_count(records, 'item'),
                'categories': distinct_count(records, 'category_id'),
                'storage_locations': distinct_count(records, 'st_loc_id'),
                'expired_records': by_expiry.get('expired', {}).get('records', 0),
                'expiring_records': by_expiry.get('expiring', {}).get('records', 0),
            },
            'expiry': expiry,
            'by_type': totals(records, 'txn_type_id', 'txn_type_name', 'direction'),
            'by_status': totals(records, 'status_id', 'status_name'),
            'by_party': totals(records, 'party_id', 'party_name'),
            'by_category': totals(records, 'category_id', 'category_name'),
            'by_storage_location': totals(records, 'st_loc_id', 'storage_location_name', 'location_name'),
            'by_item': totals(records, 'item_id', 'item_name', 'item_code', 'category_name'),
            'by_item_variant': totals(records, 'item_id', 'item_name', 'sub_cat_id', 'sub_cat_name', 'spec_id', 'spec_name'),
            'by_month': sorted(
                totals(records, month=TruncMonth('record_date')),
                key=lambda row: (row['month'] is None, row['month'] or datetime.date.min),
            ),
            'records': {
                'count': record_count,
                'page': page,
                'page_size': page_size,
                'results': records_page(records, page, page_size),
            },
        })
