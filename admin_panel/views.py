from django.db.models import Count, Sum
from django.http import JsonResponse
# from django.shortcuts import render
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

    # Optimized Order queryset
    queryset = Order.objects.filter(
        status='completed'
    ).select_related('service_provider')

    # Apply filters
    queryset = queryset.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )

    if vendor_id:
        queryset = queryset.filter(service_provider_id=vendor_id)

    # Aggregations from Order
    stats = queryset.aggregate(
        total_insurance=Sum('insurance_amount'),
        total_weight=Sum('weight_in_pounds'),
        total_orders=Count('id'),
        total_service_charge=Sum('service_charge_cents'),   # vendor laundry fee
    )

    # Get related VendorPayouts (this is where platform revenue lives)
    payout_queryset = VendorPayout.objects.filter(
        order__in=queryset
    )

    payout_stats = payout_queryset.aggregate(
        total_platform_fee=Sum('platform_fee'),
        total_vendor_payout=Sum('amount'),
        total_added_stripe_fee=Sum('added_stripe_fee'),
    )

    # === Super Admin Revenue = Platform Fee (what you keep) ===
    platform_revenue_dollars = round(payout_stats['total_platform_fee'] or 0, 2)

    # Vendor fee per lb (laundry service charge)
    vendor_fee_per_lb = 0.00
    if stats['total_weight'] and stats['total_weight'] > 0:
        total_service_cents = stats['total_service_charge'] or 0
        vendor_fee_per_lb = round(total_service_cents / (stats['total_weight'] * 100), 2)

    # Insurance (already in dollars)
    insurance_dollars = round(stats['total_insurance'] or 0, 2)

    data = {
        'revenue': platform_revenue_dollars,           # ← This is now correct (platform revenue)
        'insurance': insurance_dollars,
        'vendor_fee_per_lb': vendor_fee_per_lb,
        'platform_fee': platform_revenue_dollars,      # same as revenue for now
        'total_orders': stats['total_orders'] or 0,
        'total_weight': round(stats['total_weight'] or 0, 2),
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'vendor_id': vendor_id,
    }

    return JsonResponse(data)