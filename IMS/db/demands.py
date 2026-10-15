"""
Demands API.

1. Any user raises a demand (items with quantities) for a storage location; storage location users for their own.
2. The PDMA Admin (master users) refers each line to a storage location that has the stock, or to NDMA.
3. The line is approved, possibly for less than requested (rationalized) and split over several storage locations
   (allocations), or rejected. The PDMA Admin (DG PDMA) decides every line from PDMA stock, seeing the available
   quantity on each line; it requests NDMA stock by referring a line to NDMA. NDMA is a separate body: it alone
   decides the lines referred to it, from NDMA stock kept in any storage location.
4. Storage locations only issue: the giving storage location issues each allocation, at once or in parts, as internal transfers to the demanding
   storage location, linked to the allocation.
Stock in every storage location belongs to PDMA or NDMA. Issued stock becomes PDMA's (NDMA stock is handed over
when issued).
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .api_views import LogSubmitMixin, id_param
from .models import (
    Demand,
    DemandAllocation,
    DemandLine,
    InventoryTransaction,
    ItemCondition,
    ItemStatus,
    StockBalance,
    StockOwner,
    StorageLocation,
    StorageType,
    TransactionType,
)
from .permissions import (
    LocationScopedFieldsMixin,
    can_decide_demand_line,
    is_district,
    is_ndma,
    is_pdma_admin,
    sees_all_locations,
    user_location_id,
)
from .serializers import InventoryTransactionSerializer, item_option_errors, movement_kind, name_field

ZERO = Decimal('0')


# --- Quantities -----------------------------------------------------------------

def issued_quantity(allocation):
    """Quantity issued so far against an allocation (uses prefetched transactions when there are any)."""
    return sum((txn.quantity for txn in allocation.transactions.all()), ZERO)


def item_key(line):
    return {'item_id': line.item_id, 'sub_cat_id': line.sub_cat_id, 'spec_id': line.spec_id}


def reserved_quantities(line):
    """{(storage location id, owner id): approved but not yet issued quantity} of the line's item for other lines."""
    allocations = (
        DemandAllocation.objects
        .filter(line__item_id=line.item_id, line__sub_cat_id=line.sub_cat_id, line__spec_id=line.spec_id,
                line__status=DemandLine.APPROVED)
        .exclude(line=line)
        .annotate(issued=Coalesce(Sum('transactions__quantity'), ZERO))
    )
    reserved = {}
    for allocation in allocations:
        open_quantity = max(allocation.quantity - allocation.issued, ZERO)
        key = (allocation.from_storage_location_id, allocation.owner_id)
        reserved[key] = reserved.get(key, ZERO) + open_quantity
    return reserved


def availability(line):
    """
    Serviceable, ready to use stock of the line's item per storage location (other than the demanding one) and owner (PDMA, NDMA):
    on hand, reserved for other approved demands and still available, most available first.
    """
    on_hand = (
        StockBalance.objects
        .filter(status_id=ItemStatus.SERVICEABLE, condition_id=ItemCondition.READY_TO_USE, **item_key(line))
        .exclude(storage_location_id=line.demand.for_storage_location_id)
        .values('storage_location_id', 'storage_location__details', 'storage_location__location__location_name',
                'storage_location__type_id', 'owner_id', 'owner__owner_name')
        .annotate(on_hand=Sum('quantity'))
    )
    reserved = reserved_quantities(line)
    rows = []
    for row in on_hand:
        held = reserved.get((row['storage_location_id'], row['owner_id']), ZERO)
        rows.append({
            'storage_location_id': row['storage_location_id'],
            'storage_location_name': row['storage_location__details'],
            'location_name': row['storage_location__location__location_name'],
            'is_district': row['storage_location__type_id'] == StorageType.DISTRICT,
            'owner_id': row['owner_id'],
            'owner_name': row['owner__owner_name'],
            'on_hand': row['on_hand'],
            'reserved': held,
            'available': max(row['on_hand'] - held, ZERO),
        })
    return sorted(rows, key=lambda row: row['available'], reverse=True)


def can_give(line, row):
    """
    Whether stock in availability `row` can be given for `line`: NDMA stock anywhere for a line referred to NDMA;
    the district's own stock for a return asked from a district; otherwise PDMA stock in warehouses.
    """
    if row['is_district'] and is_district(line.demand.for_storage_location):
        return False  # stock does not move from one district to another
    if line.referred_owner_id == StockOwner.NDMA:
        return row['owner_id'] == StockOwner.NDMA
    if row['owner_id'] != StockOwner.PDMA:
        return False
    if is_district(line.referred_to):
        return row['storage_location_id'] == line.referred_to_id
    return not row['is_district']


# --- Serializers ----------------------------------------------------------------

class DemandAllocationSerializer(serializers.ModelSerializer):
    from_storage_location_name = name_field('from_storage_location.details')
    owner_name = name_field('owner.owner_name')
    issued_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = DemandAllocation
        exclude = ['line']

    def get_issued_quantity(self, allocation):
        return issued_quantity(allocation)

    def get_remaining_quantity(self, allocation):
        return allocation.quantity - issued_quantity(allocation)


class DemandLineSerializer(serializers.ModelSerializer):
    """An item of a demand. Only item, sub_cat, spec, quantity and remarks are entered; the rest follows the decision."""
    item_name = name_field('item.item_name')
    sub_cat_name = name_field('sub_cat.sub_cat_name')
    spec_name = name_field('spec.spec_name')
    unit_name = name_field('item.unit.unit_name')
    referred_to_name = name_field('referred_to.details')
    referred_owner_name = name_field('referred_owner.owner_name')
    allocations = DemandAllocationSerializer(many=True, read_only=True)
    approved_quantity = serializers.SerializerMethodField()
    issued_quantity = serializers.SerializerMethodField()
    rationalized = serializers.SerializerMethodField()
    can_decide = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField(
        help_text='Serviceable stock of this item available to give (not promised to other demands), of the owner the '
                  'line is referred to (PDMA or NDMA), over all storage locations but the demanding one.')

    class Meta:
        model = DemandLine
        exclude = ['demand']
        read_only_fields = ['referred_to', 'referred_owner', 'status', 'decision_remarks', 'decided_by', 'decided_at']

    def get_approved_quantity(self, line):
        return sum((allocation.quantity for allocation in line.allocations.all()), ZERO)

    def get_issued_quantity(self, line):
        return sum((issued_quantity(allocation) for allocation in line.allocations.all()), ZERO)

    def get_rationalized(self, line):
        """Approved for less than requested."""
        return line.status == DemandLine.APPROVED and self.get_approved_quantity(line) < line.quantity

    def get_available_quantity(self, line):
        if line.status != DemandLine.PENDING:
            return None
        return sum((row['available'] for row in availability(line) if can_give(line, row)), ZERO)

    def get_can_decide(self, line):
        request = self.context.get('request')
        return request is not None and can_decide_demand_line(request.user, line)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get('quantity') is not None and attrs['quantity'] <= 0:
            raise serializers.ValidationError({'quantity': 'Must be more than 0.'})
        errors = item_option_errors(attrs['item'], attrs.get('sub_cat'), attrs.get('spec'), True)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


DEMAND_STATUSES = ('pending', 'in_process', 'approved', 'partly_issued', 'completed', 'rejected')


def status_from(line_statuses, approved, issued):
    """
    A demand's status from its lines' statuses and the quantities approved and issued:
    pending, in_process, approved, partly_issued, completed or rejected.
    """
    statuses = set(line_statuses)
    if not statuses or statuses == {DemandLine.PENDING}:
        return 'pending'
    if statuses == {DemandLine.REJECTED}:
        return 'rejected'
    if DemandLine.PENDING in statuses:
        return 'in_process'
    if issued == 0:
        return 'approved'
    return 'completed' if issued >= approved else 'partly_issued'


def demand_status(lines):
    """The status of a demand from its (prefetched) lines."""
    allocations = [allocation for line in lines if line.status == DemandLine.APPROVED
                   for allocation in line.allocations.all()]
    return status_from(
        [line.status for line in lines],
        sum((allocation.quantity for allocation in allocations), ZERO),
        sum((issued_quantity(allocation) for allocation in allocations), ZERO),
    )


class DemandSerializer(LocationScopedFieldsMixin, serializers.ModelSerializer):
    """
    A demand with its lines. Storage location users raise demands for their own storage location (it may be left
    out); master and all areas users choose one. Lines can be changed only while every line is still pending.
    """
    for_storage_location_name = name_field('for_storage_location.details')
    location_name = name_field('for_storage_location.location.location_name')
    lines = DemandLineSerializer(many=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = Demand
        fields = '__all__'
        read_only_fields = ['demand_no', 'created_by', 'created_at']
        extra_kwargs = {'for_storage_location': {'required': False}, 'demand_date': {'required': False}}

    def get_status(self, demand):
        return demand_status(list(demand.lines.all()))

    def to_representation(self, demand):
        data = super().to_representation(demand)
        request = self.context.get('request')
        if request is not None and is_ndma(request.user):  # NDMA sees only the lines referred to it
            data['lines'] = [line for line in data['lines'] if line['referred_owner'] == StockOwner.NDMA]
        return data

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is None:
            if not attrs.get('lines'):
                raise serializers.ValidationError({'lines': 'Add at least one item.'})
            if attrs.get('for_storage_location') is None:
                request = self.context.get('request')
                own = user_location_id(request.user) if request is not None else None
                if own is None or sees_all_locations(request.user):
                    raise serializers.ValidationError({'for_storage_location': 'This field is required.'})
                attrs['for_storage_location'] = StorageLocation.objects.get(pk=own)
            attrs.setdefault('demand_date', timezone.localdate())
        elif 'lines' in attrs and not attrs['lines']:
            raise serializers.ValidationError({'lines': 'Add at least one item.'})
        return attrs

    def create(self, validated_data):
        lines = validated_data.pop('lines')
        demand = super().create(validated_data)
        demand.demand_no = f'DMD-{demand.demand_date:%Y}-{demand.pk:05d}'
        demand.save(update_fields=['demand_no'])
        for line in lines:
            DemandLine.objects.create(demand=demand, **line)
        return demand

    def update(self, instance, validated_data):
        lines = validated_data.pop('lines', None)
        demand = super().update(instance, validated_data)
        if lines is not None:
            demand.lines.all().delete()
            for line in lines:
                DemandLine.objects.create(demand=demand, **line)
        return demand


class AllocationInputSerializer(serializers.Serializer):
    from_storage_location = serializers.PrimaryKeyRelatedField(queryset=StorageLocation.objects.all())
    owner = serializers.PrimaryKeyRelatedField(queryset=StockOwner.objects.all(), required=False,
                                               help_text='Whose stock is given: 1 PDMA (default) or 2 NDMA.')
    quantity = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal('0.01'))


class ApproveSerializer(serializers.Serializer):
    allocations = AllocationInputSerializer(many=True, allow_empty=False)
    decision_remarks = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class IssueSerializer(serializers.Serializer):
    allocation = serializers.IntegerField(required=False, help_text='Needed when the line has several allocations.')
    quantity = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal('0.01'), required=False,
                                        help_text='Default: everything not yet issued.')
    txn_date = serializers.DateField(required=False)
    from_sto_shed = serializers.CharField(required=False, allow_null=True)
    to_sto_shed = serializers.CharField(required=False, allow_null=True)
    remarks = serializers.CharField(required=False, allow_blank=True, allow_null=True)


# --- Views ----------------------------------------------------------------------

def demand_scope(location_id):
    """Demands of, referred to, or allocated from storage location `location_id`."""
    return Q(for_storage_location=location_id) | Q(lines__referred_to=location_id) | \
        Q(lines__allocations__from_storage_location=location_id)


def line_scope(location_id):
    return Q(demand__for_storage_location=location_id) | Q(referred_to=location_id) | \
        Q(allocations__from_storage_location=location_id)


# NDMA sees only the requests referred to it.
NDMA_DEMAND_SCOPES = {
    Demand: Q(lines__referred_owner=StockOwner.NDMA),
    DemandLine: Q(referred_owner=StockOwner.NDMA),
}


def scoped(queryset, user, scope):
    if sees_all_locations(user):
        return queryset
    if is_ndma(user):
        return queryset.filter(pk__in=queryset.model.objects.filter(NDMA_DEMAND_SCOPES[queryset.model]).values('pk'))
    location_id = user_location_id(user)
    if location_id is None:
        return queryset.none()
    return queryset.filter(pk__in=queryset.model.objects.filter(scope(location_id)).values('pk'))


def awaiting_decision(lines, user):
    """
    Pending lines this user may decide: NDMA those referred to NDMA, a district the returns asked from it, the PDMA
    Admin all others.
    """
    lines = lines.filter(status=DemandLine.PENDING)
    if is_ndma(user):
        return lines.filter(referred_owner=StockOwner.NDMA)
    pdma = lines.filter(referred_owner=StockOwner.PDMA)
    if is_pdma_admin(user):
        return pdma.exclude(referred_to__type_id=StorageType.DISTRICT)
    location_id = user_location_id(user)
    if location_id is None or sees_all_locations(user):
        return lines.none()
    return pdma.filter(referred_to=location_id, referred_to__type_id=StorageType.DISTRICT)


def refer_target(request, demand):
    """
    (storage location or None, owner id) to refer lines to, from {"referred_to": id, "owner": 1|2}.
    Lines referred to NDMA (owner 2) need no storage location: NDMA gives from its stock in any of them.
    """
    if not is_pdma_admin(request.user):
        raise PermissionDenied('Only the PDMA Admin refers demands.')
    owner = id_param_from(request.data, 'owner') or StockOwner.PDMA
    if owner not in (StockOwner.PDMA, StockOwner.NDMA):
        raise serializers.ValidationError({'owner': 'Use 1 (PDMA) or 2 (NDMA).'})
    referred_to = id_param_from(request.data, 'referred_to')
    location = StorageLocation.objects.filter(pk=referred_to).first() if referred_to else None
    if referred_to and location is None:
        raise serializers.ValidationError({'referred_to': 'No such storage location.'})
    if location is None and owner == StockOwner.PDMA:
        raise serializers.ValidationError({'referred_to': 'Choose a storage location, or refer it to NDMA (owner 2).'})
    if location is not None and location.pk == demand.for_storage_location_id:
        raise serializers.ValidationError({'referred_to': 'Refer it to another storage location than the demanding one.'})
    if is_district(location):
        if owner == StockOwner.NDMA:
            raise serializers.ValidationError({'referred_to': 'NDMA stock is requested from NDMA, not from a district.'})
        if is_district(demand.for_storage_location):
            raise serializers.ValidationError({'referred_to': 'Stock does not move from one district to another; '
                                                              'ask the district for a return to a warehouse.'})
    return location, owner


LINE_PREFETCH = ('lines__allocations__transactions', 'lines__item__unit', 'lines__sub_cat', 'lines__spec',
                 'lines__referred_to', 'lines__allocations__from_storage_location')


class DemandViewSet(LogSubmitMixin, viewsets.ModelViewSet):
    """
    Demands with their lines. Everyone sees the demands of their storage location and those referred to or
    allocated from it; master and all areas users see all.
    Filters: ?for_storage_location, ?referred_to, ?status (pending, in_process, approved, partly_issued, completed,
    rejected), ?awaiting_my_decision=true (demands with lines the user can approve or reject now).
    POST /api/demands/<id>/refer/ {"referred_to": id, "owner": 1|2, "lines": [ids]} refers lines (all pending ones
    by default) to a storage location (PDMA stock) or to NDMA (owner 2; storage location optional). PDMA Admin only.
    """
    queryset = Demand.objects.select_related('for_storage_location__location').prefetch_related(*LINE_PREFETCH) \
        .order_by('-demand_date', '-demand_id')
    serializer_class = DemandSerializer

    def get_queryset(self):
        queryset = scoped(super().get_queryset(), self.request.user, demand_scope)
        for param, lookup in (('for_storage_location', 'for_storage_location'), ('referred_to', 'lines__referred_to')):
            value = id_param(self.request, param)
            if value is not None:
                queryset = queryset.filter(pk__in=Demand.objects.filter(**{lookup: value}).values('pk'))
        if self.request.query_params.get('awaiting_my_decision') == 'true':
            lines = awaiting_decision(DemandLine.objects.all(), self.request.user)
            queryset = queryset.filter(pk__in=lines.values('demand_id'))
        return queryset

    def list(self, request, *args, **kwargs):
        status = request.query_params.get('status')
        if not status:
            return super().list(request, *args, **kwargs)
        demands = [demand for demand in self.get_queryset() if demand_status(list(demand.lines.all())) == status]
        return Response(self.get_serializer(demands, many=True).data)

    def _check_editable(self, demand):
        user = self.request.user
        if not sees_all_locations(user) and demand.for_storage_location_id != user_location_id(user):
            raise PermissionDenied('Only the demanding storage location can change this demand.')
        if demand.lines.exclude(status=DemandLine.PENDING).exists():
            raise PermissionDenied('This demand can no longer be changed: lines have been approved or rejected.')

    def perform_create(self, serializer):
        user = self.request.user
        demand = serializer.validated_data.get('for_storage_location')
        if demand is not None and not sees_all_locations(user) and demand.pk != user_location_id(user):
            raise PermissionDenied('You can only raise demands for your own storage location.')
        serializer.save(created_by=user.id, created_at=timezone.now())

    def perform_update(self, serializer):
        self._check_editable(serializer.instance)
        location = serializer.validated_data.get('for_storage_location')
        user = self.request.user
        if location is not None and not sees_all_locations(user) and location.pk != user_location_id(user):
            raise PermissionDenied('You can only raise demands for your own storage location.')
        serializer.save()

    def perform_destroy(self, instance):
        self._check_editable(instance)
        instance.delete()

    @action(detail=True, methods=['post'])
    def refer(self, request, pk=None):
        demand = self.get_object()
        location, owner = refer_target(request, demand)
        lines = demand.lines.filter(status=DemandLine.PENDING)
        if request.data.get('lines'):
            lines = lines.filter(pk__in=request.data['lines'])
        count = lines.update(referred_to=location, referred_owner_id=owner)
        demand = self.get_queryset().get(pk=demand.pk)
        return Response({'referred_lines': count, 'demand': self.get_serializer(demand).data})


def id_param_from(data, name):
    try:
        return int(data.get(name))
    except (TypeError, ValueError):
        return None


class DemandLineViewSet(LogSubmitMixin, viewsets.ReadOnlyModelViewSet):
    """
    Demand lines, with the actions on them:
    GET  /api/demand-lines/?awaiting_my_decision=true  lines the user can approve or reject now
    GET  /api/demand-lines/<id>/availability/  stock per storage location to approve from
    POST /api/demand-lines/<id>/refer/    {"referred_to": id, "owner": 1|2}  (PDMA Admin; owner 2 = to NDMA)
    POST /api/demand-lines/<id>/approve/  {"allocations": [{"from_storage_location": id, "owner": 1|2, "quantity": n}],
                                           "decision_remarks": "..."}  (less than requested = rationalized)
    POST /api/demand-lines/<id>/reject/   {"decision_remarks": "..."}
    POST /api/demand-lines/<id>/issue/    {"allocation": id, "quantity": n, "txn_date": "YYYY-MM-DD",
                                           "from_sto_shed": .., "to_sto_shed": .., "remarks": ".."}
    NDMA alone decides the lines referred to NDMA, from NDMA stock in any storage location. The PDMA Admin decides
    every other line from PDMA stock. The giving storage location (or a master / all areas user) issues approved
    quantities.
    """
    queryset = DemandLine.objects.select_related(
        'demand__for_storage_location', 'item__unit', 'sub_cat', 'spec', 'referred_to',
    ).prefetch_related('allocations__transactions', 'allocations__from_storage_location').order_by('-demand_id', 'line_id')
    serializer_class = DemandLineSerializer

    def get_queryset(self):
        queryset = scoped(super().get_queryset(), self.request.user, line_scope)
        params = self.request.query_params
        if params.get('awaiting_my_decision') == 'true':
            queryset = awaiting_decision(queryset, self.request.user)
        if params.get('status'):
            queryset = queryset.filter(status=params['status'])
        for param, lookup in (('demand', 'demand'), ('referred_to', 'referred_to'), ('item', 'item')):
            value = id_param(self.request, param)
            if value is not None:
                queryset = queryset.filter(**{lookup: value})
        return queryset

    def _decidable(self):
        line = self.get_object()
        if not can_decide_demand_line(self.request.user, line):
            if line.referred_owner_id == StockOwner.NDMA:
                raise PermissionDenied('This line is referred to NDMA; only NDMA can accept, reject or rationalize it.')
            raise PermissionDenied('Only the PDMA Admin decides demands; storage locations only issue.')
        return line

    def _line_response(self, line):
        return Response(self.get_serializer(self.get_queryset().get(pk=line.pk)).data)

    @action(detail=True)
    def availability(self, request, pk=None):
        rows = availability(self.get_object())
        if is_ndma(request.user):  # NDMA sees only its own stock
            rows = [row for row in rows if row['owner_id'] == StockOwner.NDMA]
        return Response(rows)

    @action(detail=True, methods=['post'])
    def refer(self, request, pk=None):
        line = self.get_object()
        location, owner = refer_target(request, line.demand)
        if line.status != DemandLine.PENDING:
            raise serializers.ValidationError('Only pending lines can be referred.')
        line.referred_to, line.referred_owner_id = location, owner
        line.save(update_fields=['referred_to', 'referred_owner'])
        return self._line_response(line)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        line = self._decidable()
        data = ApproveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        allocations = data.validated_data['allocations']
        user = request.user

        # {(storage location, owner): quantity}; the stock is of the owner the line is referred to.
        owner_id = line.referred_owner_id
        names = {StockOwner.PDMA: 'PDMA', StockOwner.NDMA: 'NDMA'}
        wanted = {}
        errors = []
        for allocation in allocations:
            owner = allocation.get('owner')
            if owner is not None and owner.pk != owner_id:
                errors.append(f'This line is referred to {names[owner_id]}, so only {names[owner_id]} stock can be '
                              f'given; the PDMA Admin can refer it again to change that.')
            key = (allocation['from_storage_location'].pk, owner_id)
            wanted[key] = wanted.get(key, ZERO) + allocation['quantity']
        if line.demand.for_storage_location_id in {location_id for location_id, _ in wanted}:
            errors.append('Stock can not be approved from the demanding storage location itself.')
        if sum(wanted.values(), ZERO) > line.quantity:
            errors.append(f'Approved quantity is more than the {line.quantity} demanded.')

        existing = {(allocation.from_storage_location_id, allocation.owner_id): allocation
                    for allocation in line.allocations.all()}
        rows = availability(line)
        available = {(row['storage_location_id'], row['owner_id']): row['available'] for row in rows}
        givers = {(row['storage_location_id'], row['owner_id']) for row in rows if can_give(line, row)}
        for key in wanted:
            if key not in givers and key[0] in {row['storage_location_id'] for row in rows}:
                if line.referred_owner_id == StockOwner.NDMA:
                    errors.append(f'Storage location {key[0]}: only NDMA stock is given for this line.')
                elif is_district(line.referred_to):
                    errors.append(f'Storage location {key[0]}: this return is given only by {line.referred_to}.')
                else:
                    errors.append(f'Storage location {key[0]}: the DG PDMA gives from warehouses; district stock is '
                                  f'asked for as a return.')
        for (location_id, owner_id), quantity in wanted.items():
            where = f'{names.get(owner_id, owner_id)} stock at storage location {location_id}'
            allocation = existing.get((location_id, owner_id))
            issued = issued_quantity(allocation) if allocation else ZERO
            if quantity < issued:
                errors.append(f'{issued} of {where} has already been issued.')
            elif quantity - issued > available.get((location_id, owner_id), ZERO):
                errors.append(f'Only {available.get((location_id, owner_id), ZERO)} of {where} is available '
                              f'(stock not promised to other demands).')
        for key, allocation in existing.items():
            if key not in wanted and issued_quantity(allocation) > 0:
                errors.append(f'Storage location {key[0]} has already issued against this line; keep it.')
        if errors:
            raise serializers.ValidationError({'allocations': errors})

        now = timezone.now()
        with transaction.atomic():
            for key, allocation in existing.items():
                if key not in wanted:
                    allocation.delete()
            for (location_id, owner_id), quantity in wanted.items():
                DemandAllocation.objects.update_or_create(
                    line=line, from_storage_location_id=location_id, owner_id=owner_id,
                    defaults={'quantity': quantity, 'approved_by': user.id, 'approved_at': now},
                )
            line.status = DemandLine.APPROVED
            line.decision_remarks = data.validated_data.get('decision_remarks')
            line.decided_by, line.decided_at = user.id, now
            locations = {location_id for location_id, _ in wanted}
            if line.referred_to_id is None and len(locations) == 1:
                line.referred_to_id = next(iter(locations))
            line.save()
        return self._line_response(line)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        line = self._decidable()
        if any(issued_quantity(allocation) > 0 for allocation in line.allocations.all()):
            raise serializers.ValidationError('Stock has already been issued for this line.')
        with transaction.atomic():
            line.allocations.all().delete()
            line.status = DemandLine.REJECTED
            line.decision_remarks = request.data.get('decision_remarks')
            line.decided_by, line.decided_at = request.user.id, timezone.now()
            line.save()
        return self._line_response(line)

    @action(detail=True, methods=['post'])
    def issue(self, request, pk=None):
        line = self.get_object()
        if line.status != DemandLine.APPROVED:
            raise serializers.ValidationError('Only approved lines can be issued.')
        data = IssueSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        allocations = list(line.allocations.all())
        user = request.user
        if not sees_all_locations(user):
            allocations = [allocation for allocation in allocations
                           if allocation.from_storage_location_id == user_location_id(user)]
        if data.validated_data.get('allocation') is not None:
            allocations = [allocation for allocation in allocations if allocation.pk == data.validated_data['allocation']]
        if not allocations:
            raise PermissionDenied('Nothing approved for this line can be issued by you.')
        if len(allocations) > 1:
            raise serializers.ValidationError({'allocation': 'This line is given by several storage locations; choose one.'})
        allocation = allocations[0]
        remaining = allocation.quantity - issued_quantity(allocation)
        quantity = data.validated_data.get('quantity', remaining)
        if remaining <= 0:
            raise serializers.ValidationError('Everything approved here has already been issued.')

        transfer = InventoryTransactionSerializer(data={
            'txn_type': movement_kind(allocation.from_storage_location, line.demand.for_storage_location),
            'txn_date': data.validated_data.get('txn_date') or timezone.localdate(),
            'item': line.item_id, 'sub_cat': line.sub_cat_id, 'spec': line.spec_id,
            'status': ItemStatus.SERVICEABLE, 'condition': ItemCondition.READY_TO_USE, 'quantity': quantity,
            # Issued stock becomes PDMA's; NDMA stock is handed over on the way.
            'owner': StockOwner.PDMA,
            'from_owner': allocation.owner_id if allocation.owner_id != StockOwner.PDMA else None,
            'from_storage_location': allocation.from_storage_location_id,
            'from_sto_shed': data.validated_data.get('from_sto_shed'),
            'to_storage_location': line.demand.for_storage_location_id,
            'to_sto_shed': data.validated_data.get('to_sto_shed'),
            'txn_no': line.demand.demand_no,
            'remarks': data.validated_data.get('remarks') or f'Issued against demand {line.demand.demand_no}',
        }, context={'request': request, 'demand_issue': True})
        transfer.is_valid(raise_exception=True)
        with transaction.atomic():
            txn = transfer.save(demand_allocation=allocation, created_by=user.id, created_at=timezone.now())
        return Response({
            'transaction': InventoryTransactionSerializer(
                InventoryTransaction.objects.get(pk=txn.pk), context={'request': request}).data,
            'line': self.get_serializer(self.get_queryset().get(pk=line.pk)).data,
        }, status=201)
