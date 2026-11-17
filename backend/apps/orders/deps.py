from functools import lru_cache
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.accounts.repository import AddressRepository, UserRepository
from apps.catalogue.repository import ProductRepository
from apps.inventory.repository import BatchRepository, MovementRepository
from apps.inventory.reservations import ReservationService
from apps.prescriptions.allowance import AllowanceService
from apps.prescriptions.repository import PrescriptionRepository
from common.mongo import get_db

from apps.notifications import deps as notify_deps
from apps.notifications.observers import NotifyingOrders, NotifyingRefunds, NotifyingReturns

from .cart import CartService
from .payments import MockPaymentAdapter, RazorpayAdapter
from .delivery import DeliveryService
from .gateway import GatewayPaymentService
from .lifecycle import LifecycleService
from .refunds import RefundService
from .repository import CartRepository, OrderRepository, PaymentEventRepository, RefundRepository, ReturnRepository
from .services import OrderService, _now


def build_payment_adapter():
    provider = settings.PAYMENT_PROVIDER
    if provider == "mock":
        if not settings.DEBUG:
            # Fail closed: the mock must never be reachable on a non-debug (production-like) server.
            raise ImproperlyConfigured("The mock payment provider only runs when DJANGO_DEBUG=True.")
        return MockPaymentAdapter()
    if provider == "razorpay":
        if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET and settings.RAZORPAY_WEBHOOK_SECRET):
            raise ImproperlyConfigured("PAYMENT_PROVIDER=razorpay needs RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET in .env.")
        if not settings.RAZORPAY_KEY_ID.startswith("rzp_test_") and not settings.PAYMENT_ALLOW_LIVE:
            # This project is not production-ready: live keys are refused unless someone sets PAYMENT_ALLOW_LIVE on purpose.
            raise ImproperlyConfigured("Live Razorpay keys are refused. Use rzp_test_ keys (this build is not production-ready).")
        return RazorpayAdapter(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET, settings.RAZORPAY_WEBHOOK_SECRET)
    raise ImproperlyConfigured(f"PAYMENT_PROVIDER={provider!r} is not available. Use 'mock' or 'razorpay'.")


@lru_cache(maxsize=1)
def get_services() -> SimpleNamespace:
    db = get_db()
    products = ProductRepository(db)
    carts = CartRepository(db)
    reservations = ReservationService(BatchRepository(db), MovementRepository(db))
    allowances = AllowanceService(PrescriptionRepository(db))   # pharmacist-approved prescription allowances
    notifier = notify_deps.get_notifications()
    order_repo, adapter = NotifyingOrders(OrderRepository(db), notifier), build_payment_adapter()
    orders = OrderService(carts, order_repo, products, AddressRepository(db), reservations, adapter, allowances=allowances,
                          pincode_prefixes=settings.DELIVERY_PINCODE_PREFIXES)
    refunds = RefundService(NotifyingRefunds(RefundRepository(db), notifier, order_repo), order_repo, adapter, _now)
    lifecycle = LifecycleService(orders, order_repo, NotifyingReturns(ReturnRepository(db), notifier), refunds, reservations, allowances, _now)
    gateway = GatewayPaymentService(orders, order_repo, adapter, reservations, refunds, PaymentEventRepository(db), allowances, _now)
    delivery = DeliveryService(order_repo, UserRepository(db), refunds, settings.SECRET_KEY, _now)
    return SimpleNamespace(cart=CartService(carts, products, reservations, allowances=allowances),
                           orders=orders, lifecycle=lifecycle, gateway=gateway, delivery=delivery)
