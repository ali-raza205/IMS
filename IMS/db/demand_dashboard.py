"""
Demand dashboard API: demands from request to approval to issue, totalled for dashboard cards and charts.
Everything starts from the demand requests: filters pick demands (by demand date, demanding storage location,
item...) and their lines are followed through approval (allocations) and issue (linked transfers).
Data is limited by role like the other APIs.
"""
from decimal import Decimal

from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .dashboard import date_param, id_list, param
from .demands import awaiting_decision, line_scope, scoped, status_from
from .models import DemandAllocation, DemandLine, InventoryTransaction
from .permissions import sees_all_locations
from .serializers import user_info

ZERO = Decimal('0')
QUANTITY = DecimalField(max_digits=20, decimal_places=2)
RECENT = 10


def line_total(queryset, path):
    """Per demand line: Sum of `queryset` quantities whose `path` is the line (0 when none)."""
    total = queryset.filter(**{path: OuterRef('pk')}).values(path).annotate(total=Sum('quantity')).values('total')
    return Coalesce(Subquery(total, output_field=QUANTITY), Value(ZERO), output_field=QUANTITY)


def demand_filters(params):
    return {
        'date_from': date_param(params, 'date_from'),
        'date_to': date_param(params, 'date_to'),
        'storage_location': id_list(params, 'storage_location'),
        'location': id_list(params, 'location'),
        'referred_to': id_list(params, 'referred_to'),
        'category': id_list(params, 'category'),
        'item': id_list(params, 'item'),
    }


def demand_lines(user, filters):
    """The demand lines (role scoped, filtered) with their approved and issued quantities."""
    lines = scoped(DemandLine.objects.all(), user, line_scope)
    lookups = {
        'date_from': 'demand__demand_date__gte',
        'date_to': 'demand__demand_date__lte',
        'storage_location': 'demand__for_storage_location__in',
        'location': 'demand__for_storage_location__location__in',
        'referred_to': 'referred_to__in',
        'category': 'item__item_category__in',
        'item': 'item__in',
    }
    for name, lookup in lookups.items():
        if filters[name]:
            lines = lines.filter(**{lookup: filters[name]})
    return lines.annotate(
        approved=line_total(DemandAllocation.objects.all(), 'line'),
        issued=line_total(InventoryTransaction.objects.all(), 'demand_allocation__line'),
    )


def add(group, row, demanded=True):
    group['demanded'] += row['quantity'] if demanded else ZERO
    group['approved'] += row['approved']
    group['issued'] += row['issued']


def grouped(rows, key, names):
    """Quantities demanded, approved and issued per `key`, most demanded first."""
    groups = {}
    for row in rows:
        group = groups.setdefault(key(row), {
            **{name: row[source] for name, source in names.items()},
            'lines': 0, 'demanded': ZERO, 'approved': ZERO, 'issued': ZERO,
        })
        group['lines'] += 1
        add(group, row)
    return sorted(groups.values(), key=lambda group: group['demanded'], reverse=True)


def rate(part, whole):
    return round(float(part) / float(whole), 4) if whole else None


class DemandDashboardView(APIView):
    """
    GET /api/dashboard/demands/ returns demands from request to issue, totalled for dashboard cards and charts.
    approval_rate = approved / demanded over decided lines; fulfilment_rate = issued / approved.
    Every filter is optional; id filters take one id or comma-separated ids.
    """

    @swagger_auto_schema(manual_parameters=[
        param('date_from', openapi.TYPE_STRING, 'Demand date on or after (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('date_to', openapi.TYPE_STRING, 'Demand date on or before (YYYY-MM-DD)', format=openapi.FORMAT_DATE),
        param('storage_location', openapi.TYPE_STRING, 'Demanding storage location id(s)'),
        param('location', openapi.TYPE_STRING, 'Area (district) id(s) of the demanding storage location'),
        param('referred_to', openapi.TYPE_STRING, 'Storage location id(s) the lines are referred to'),
        param('category', openapi.TYPE_STRING, 'Category id(s)'),
        param('item', openapi.TYPE_STRING, 'Item id(s)'),
    ])
    def get(self, request):
        filters = demand_filters(request.query_params)
        today = timezone.localdate()
        lines = demand_lines(request.user, filters)
        rows = list(lines.values(
            'line_id', 'status', 'quantity', 'approved', 'issued', 'referred_to_id',
            'item_id', 'item__item_name', 'item__item_category__category_name', 'sub_cat_id', 'sub_cat__sub_cat_name',
            'spec_id', 'spec__spec_name', 'item__unit__unit_name',
            'demand_id', 'demand__demand_no', 'demand__demand_date', 'demand__needed_by', 'demand__purpose',
            'demand__for_storage_location_id', 'demand__for_storage_location__details',
            'demand__for_storage_location__location__location_name',
        ))

        # Demands, with their status from their lines
        demands = {}
        for row in rows:
            demand = demands.setdefault(row['demand_id'], {
                'demand_id': row['demand_id'], 'demand_no': row['demand__demand_no'],
                'demand_date': row['demand__demand_date'], 'needed_by': row['demand__needed_by'],
                'purpose': row['demand__purpose'],
                'storage_location_id': row['demand__for_storage_location_id'],
                'storage_location_name': row['demand__for_storage_location__details'],
                'location_name': row['demand__for_storage_location__location__location_name'],
                'lines': 0, 'statuses': [], 'demanded': ZERO, 'approved': ZERO, 'issued': ZERO,
            })
            demand['lines'] += 1
            demand['statuses'].append(row['status'])
            add(demand, row)
        for demand in demands.values():
            demand['status'] = status_from(demand.pop('statuses'), demand['approved'], demand['issued'])
            demand['overdue'] = bool(demand['needed_by'] and demand['needed_by'] < today
                                     and demand['status'] not in ('completed', 'rejected'))

        decided = [row for row in rows if row['status'] != DemandLine.PENDING]
        approved_lines = [row for row in rows if row['status'] == DemandLine.APPROVED]
        demanded = sum((row['quantity'] for row in rows), ZERO)
        approved = sum((row['approved'] for row in rows), ZERO)
        issued = sum((row['issued'] for row in rows), ZERO)

        # Giving storage locations, from the allocations of these lines
        giving = {}
        allocations = DemandAllocation.objects.filter(line__in=lines.values('pk')).annotate(
            issued=Coalesce(Sum('transactions__quantity'), Value(ZERO), output_field=QUANTITY),
        ).values('from_storage_location_id', 'from_storage_location__details', 'quantity', 'issued', 'line__status')
        for allocation in allocations:
            group = giving.setdefault(allocation['from_storage_location_id'], {
                'storage_location_id': allocation['from_storage_location_id'],
                'storage_location_name': allocation['from_storage_location__details'],
                'allocations': 0, 'approved': ZERO, 'issued': ZERO, 'reserved': ZERO,
            })
            group['allocations'] += 1
            group['approved'] += allocation['quantity']
            group['issued'] += allocation['issued']
            group['reserved'] += max(allocation['quantity'] - allocation['issued'], ZERO)

        months = {}
        for row in rows:
            month = row['demand__demand_date'].replace(day=1)
            group = months.setdefault(month, {'month': month, 'lines': 0, 'demanded': ZERO, 'approved': ZERO, 'issued': ZERO})
            group['lines'] += 1
            add(group, row)

        by_status = {status: 0 for status in ('pending', 'in_process', 'approved', 'partly_issued', 'completed', 'rejected')}
        for demand in demands.values():
            by_status[demand['status']] += 1

        user = user_info(request.user)
        return Response({
            'scope': {
                'role': user['role'],
                'sees_all_locations': sees_all_locations(request.user),
                'storage_location_id': user['storage_location_id'],
                'storage_location_name': user['storage_location_name'],
                'can_approve_demands': user['can_approve_demands'],
            },
            'filters': {**filters, 'today': today},
            'summary': {
                'demands': len(demands),
                'lines': len(rows),
                'awaiting_my_decision': awaiting_decision(lines, request.user).count(),
                'pending_lines': sum(1 for row in rows if row['status'] == DemandLine.PENDING),
                'approved_lines': len(approved_lines),
                'rejected_lines': sum(1 for row in rows if row['status'] == DemandLine.REJECTED),
                'rationalized_lines': sum(1 for row in approved_lines if row['approved'] < row['quantity']),
                'quantity_demanded': demanded,
                'quantity_approved': approved,
                'quantity_issued': issued,
                'quantity_to_issue': approved - issued,
                'approval_rate': rate(approved, sum((row['quantity'] for row in decided), ZERO)),
                'fulfilment_rate': rate(issued, approved),
                'overdue_demands': sum(1 for demand in demands.values() if demand['overdue']),
            },
            'by_status': [{'status': status, 'demands': count} for status, count in by_status.items()],
            'by_demanding_location': grouped(rows, lambda row: row['demand__for_storage_location_id'], {
                'storage_location_id': 'demand__for_storage_location_id',
                'storage_location_name': 'demand__for_storage_location__details',
                'location_name': 'demand__for_storage_location__location__location_name',
            }),
            'by_giving_location': sorted(giving.values(), key=lambda group: group['approved'], reverse=True),
            'by_item': grouped(rows, lambda row: (row['item_id'], row['sub_cat_id'], row['spec_id']), {
                'item_id': 'item_id', 'item_name': 'item__item_name',
                'category_name': 'item__item_category__category_name',
                'sub_cat_id': 'sub_cat_id', 'sub_cat_name': 'sub_cat__sub_cat_name',
                'spec_id': 'spec_id', 'spec_name': 'spec__spec_name', 'unit_name': 'item__unit__unit_name',
            }),
            'by_month': sorted(months.values(), key=lambda group: group['month']),
            'recent': sorted(demands.values(), key=lambda demand: (demand['demand_date'], demand['demand_id']),
                             reverse=True)[:RECENT],
        })
