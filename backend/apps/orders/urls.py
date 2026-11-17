from django.urls import path

from . import views

urlpatterns = [
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/items/", views.CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<str:product_id>/", views.CartItemView.as_view(), name="cart-item"),
    path("orders/", views.OrderListCreateView.as_view(), name="orders"),
    path("orders/<str:order_id>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:order_id>/pay/", views.OrderPayView.as_view(), name="order-pay"),
    path("orders/<str:order_id>/cancel/", views.OrderCancelView.as_view(), name="order-cancel"),
    path("orders/<str:order_id>/returns/", views.OrderReturnsView.as_view(), name="order-returns"),
    path("staff/orders/", views.StaffOrdersView.as_view(), name="staff-orders"),
    path("staff/orders/<str:order_id>/<str:action>/", views.StaffOrderFulfilView.as_view(), name="staff-order-fulfil"),
    path("staff/returns/", views.StaffReturnsView.as_view(), name="staff-returns"),
    path("staff/returns/<str:return_id>/decision/", views.StaffReturnDecisionView.as_view(), name="staff-return-decision"),
    path("staff/refunds/", views.StaffRefundsView.as_view(), name="staff-refunds"),
    path("staff/refunds/<str:refund_id>/retry/", views.StaffRefundRetryView.as_view(), name="staff-refund-retry"),
    path("staff/delivery/partners/", views.StaffDeliveryPartnersView.as_view(), name="staff-delivery-partners"),
    path("staff/delivery/orders/<str:order_id>/assign/", views.StaffDeliveryAssignView.as_view(), name="staff-delivery-assign"),
    path("staff/delivery/orders/<str:order_id>/<str:action>/", views.StaffDeliveryResolveView.as_view(), name="staff-delivery-resolve"),
    path("rider/deliveries/", views.RiderDeliveriesView.as_view(), name="rider-deliveries"),
    path("rider/deliveries/<str:order_id>/<str:action>/", views.RiderActionView.as_view(), name="rider-action"),
    path("orders/<str:order_id>/delivery/", views.OrderDeliveryView.as_view(), name="order-delivery"),
    path("payments/config/", views.PaymentConfigView.as_view(), name="payment-config"),
    path("payments/webhook/", views.PaymentWebhookView.as_view(), name="payment-webhook"),
    path("orders/<str:order_id>/payment/start/", views.OrderPaymentStartView.as_view(), name="order-payment-start"),
    path("orders/<str:order_id>/payment/verify/", views.OrderPaymentVerifyView.as_view(), name="order-payment-verify"),
]
