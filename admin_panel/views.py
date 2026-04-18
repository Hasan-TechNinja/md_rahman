from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from payment.models import Order, VendorPayout


# Create your views here.
@require_GET
def super_admin_stats_api(request):
    """API for Super Admin Dashboard stats"""
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    vendor_id = request.GET.get('vendor_id')

    # Default to today
    today = timezone.now().date()
    start_date = today
    end_date = today

    if start_date_str:
        try:
            start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Optimized queryset
    queryset = Order.objects.filter(
        status__in=['completed', 'charged']
    ).select_related('service_provider')

    # Apply filters
    queryset = queryset.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )

    if vendor_id:
        queryset = queryset.filter(service_provider_id=vendor_id)

    # Single optimized aggregation
    stats = queryset.aggregate(
        total_revenue=Sum('final_total_cents'),
        total_insurance=Sum('insurance_amount'),
        total_weight=Sum('weight_in_pounds'),
        total_orders=Count('id'),
        total_service_charge=Sum('service_charge_cents'),
    )

    # Platform fee calculation
    vendor_payout_total = VendorPayout.objects.filter(
        order__in=queryset,
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0

    platform_fee_cents = (stats['total_revenue'] or 0) - vendor_payout_total

    # Vendor fee per lb
    vendor_fee_per_lb = 0.00
    if stats['total_weight'] and stats['total_weight'] > 0:
        total_service_cents = stats['total_service_charge'] or 0
        vendor_fee_per_lb = round(total_service_cents / (stats['total_weight'] * 100), 2)

    # Convert to dollars
    revenue_dollars = round((stats['total_revenue'] or 0) / 100, 2)
    platform_fee_dollars = round(platform_fee_cents / 100, 2)
    insurance_dollars = round((stats['total_insurance'] or 0), 2)   # assuming already in dollars

    data = {
        'revenue': revenue_dollars,
        'insurance': insurance_dollars,
        'vendor_fee_per_lb': vendor_fee_per_lb,
        'platform_fee': platform_fee_dollars,
        'total_orders': stats['total_orders'] or 0,
        'total_weight': round(stats['total_weight'] or 0, 2),
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'vendor_id': vendor_id,
    }

    return JsonResponse(data)