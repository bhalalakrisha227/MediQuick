from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import has_role
from apps.accounts.views import body, handle_errors

from . import deps, rules


class AuthedView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]


class CartView(AuthedView):
    @handle_errors
    def get(self, request):
        return Response(deps.get_services().cart.view(request.user.id))

    @handle_errors
    def delete(self, request):
        return Response(deps.get_services().cart.clear(request.user.id))


class CartItemsView(AuthedView):
    @handle_errors
    def post(self, request):
        return Response(deps.get_services().cart.add(request.user.id, body(request)), status=201)


class CartItemView(AuthedView):
    @handle_errors
    def patch(self, request, product_id):
        return Response(deps.get_services().cart.set_quantity(request.user.id, product_id, body(request)))

    @handle_errors
    def delete(self, request, product_id):
        return Response(deps.get_services().cart.remove(request.user.id, product_id))


class OrderListCreateView(AuthedView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "checkout"

    @handle_errors
    def get(self, request):
        q = request.query_params
        page = int(q["page"]) if q.get("page", "").isdigit() and int(q["page"]) >= 1 else 1
        return Response(deps.get_services().orders.list(request.user.id, page))

    @handle_errors
    def post(self, request):
        return Response(deps.get_services().orders.create(request.user.id, body(request)), status=201)


class OrderDetailView(AuthedView):
    @handle_errors
    def get(self, request, order_id):
        return Response(deps.get_services().orders.get(request.user.id, order_id))


class OrderPayView(AuthedView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "checkout"

    @handle_errors
    def post(self, request, order_id):
        return Response(deps.get_services().orders.pay(request.user.id, order_id, body(request)))


class OrderCancelView(AuthedView):
    @handle_errors
    def post(self, request, order_id):
        result = deps.get_services().lifecycle.cancel(request.user.id, order_id)
        return Response({**result["order"], "refund": result["refund"]})


class OrderReturnsView(AuthedView):
    """GET: this order's return requests and refunds. POST: ask to return delivered items."""

    @handle_errors
    def get(self, request, order_id):
        return Response(deps.get_services().lifecycle.customer_returns(request.user.id, order_id))

    @handle_errors
    def post(self, request, order_id):
        return Response(deps.get_services().lifecycle.request_return(request.user.id, order_id, body(request)), status=201)


class StaffOrdersView(AuthedView):
    permission_classes = [has_role(*rules.FULFILMENT_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().lifecycle.staff_orders(request.user.role, request.query_params.get("status")))


class StaffOrderFulfilView(AuthedView):
    permission_classes = [has_role(*rules.FULFILMENT_ROLES)]

    @handle_errors
    def post(self, request, order_id, action):
        return Response(deps.get_services().lifecycle.fulfil(request.user.id, request.user.role, order_id, action))


class StaffReturnsView(AuthedView):
    permission_classes = [has_role(*rules.RETURN_DECISION_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().lifecycle.staff_returns(request.user.role, request.query_params.get("status", "requested")))


class StaffReturnDecisionView(AuthedView):
    permission_classes = [has_role(*rules.RETURN_DECISION_ROLES)]

    @handle_errors
    def post(self, request, return_id):
        return Response(deps.get_services().lifecycle.decide_return(request.user.id, request.user.role, return_id, body(request)))


class StaffRefundsView(AuthedView):
    permission_classes = [has_role(*rules.FULFILMENT_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().lifecycle.failed_refunds(request.user.role))


class StaffRefundRetryView(AuthedView):
    permission_classes = [has_role(*rules.FULFILMENT_ROLES)]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "checkout"

    @handle_errors
    def post(self, request, refund_id):
        return Response(deps.get_services().lifecycle.retry_refund(request.user.role, refund_id))


class PaymentConfigView(AuthedView):
    """Public checkout settings only (never the secret): which provider, and the public key id."""

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().gateway.config())


class OrderPaymentStartView(AuthedView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "checkout"

    @handle_errors
    def post(self, request, order_id):
        return Response(deps.get_services().gateway.start(request.user.id, order_id))


class OrderPaymentVerifyView(AuthedView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "checkout"

    @handle_errors
    def post(self, request, order_id):
        return Response(deps.get_services().gateway.verify(request.user.id, order_id, body(request)))


class PaymentWebhookView(APIView):
    """Called by the payment gateway, not by browsers. Authenticated ONLY by the body signature."""
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = []          # the raw bytes are needed for the signature, so DRF must not parse them
    throttle_classes = []        # the gateway calls from shared addresses and retries on 429; the signature check is the protection

    @handle_errors
    def post(self, request):
        raw = request._request.body
        meta = request._request.META
        return Response(deps.get_services().gateway.handle_webhook(
            raw, meta.get("HTTP_X_RAZORPAY_SIGNATURE"), meta.get("HTTP_X_RAZORPAY_EVENT_ID")))


class StaffDeliveryPartnersView(AuthedView):
    permission_classes = [has_role(*rules.FULFILMENT_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().delivery.partners(request.user.role))


class StaffDeliveryAssignView(AuthedView):
    permission_classes = [has_role(*rules.FULFILMENT_ROLES)]

    @handle_errors
    def post(self, request, order_id):
        return Response(deps.get_services().delivery.assign(request.user.id, request.user.role, order_id, body(request).get("partner_id")))


class StaffDeliveryResolveView(AuthedView):
    permission_classes = [has_role(*rules.FULFILMENT_ROLES)]

    @handle_errors
    def post(self, request, order_id, action):
        return Response(deps.get_services().delivery.resolve_failed(request.user.id, request.user.role, order_id, action))


class RiderDeliveriesView(AuthedView):
    permission_classes = [has_role(rules.DELIVERY_PARTNER_ROLE)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().delivery.my_deliveries(request.user.id))


class RiderActionView(AuthedView):
    permission_classes = [has_role(rules.DELIVERY_PARTNER_ROLE)]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "checkout"

    @handle_errors
    def post(self, request, order_id, action):
        svc = deps.get_services().delivery
        if action == "pickup":
            return Response(svc.pickup(request.user.id, order_id))
        if action == "deliver":
            return Response(svc.complete(request.user.id, order_id, body(request)))
        if action == "fail":
            return Response(svc.fail(request.user.id, order_id, body(request)))
        from apps.accounts.errors import ServiceError
        raise ServiceError("not_found", "Not found.", 404)


class OrderDeliveryView(AuthedView):
    """The customer's view of their delivery, including the handover code once the parcel is picked up."""

    @handle_errors
    def get(self, request, order_id):
        return Response(deps.get_services().delivery.customer_status(request.user.id, order_id))
