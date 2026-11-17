"""
What we tell customers, and when. No Django / MongoDB imports.

Privacy rule: messages never contain medicine names, addresses, prescription details or the delivery handover code.
They carry the order number and a link; the details stay behind the login. Email also goes to an address nobody has
verified yet (there is no email verification), so keeping it minimal limits the harm of a mistyped address.
"""
MAX_EMAIL_ATTEMPTS = 5
BACKOFF_MINUTES = (1, 5, 30, 120)     # wait before attempt 2, 3, 4, 5
LEASE_MINUTES = 10                    # a "sending" email with no result after this is retried
RETENTION_DAYS = 180
PAGE_SIZE = 20

# event -> (title, body, send_email). {n} = order number, {amount} = rupees.
EVENTS = {
    "order_confirmed": ("Order {n} confirmed", "We received your payment and your order {n} is confirmed.", True),
    "order_payment_review": ("Order {n}: we are checking your payment",
                             "We received a payment for order {n} but could not finish the order automatically. Our team will look into it.", True),
    "order_dispatched": ("Order {n} is out for delivery",
                         "Your order {n} is out for delivery. Open the order page to see your handover code and give it to the delivery partner only when you receive the parcel.", True),
    "order_delivered": ("Order {n} delivered", "Your order {n} was marked delivered.", True),
    "order_delivery_failed": ("Order {n}: delivery failed",
                              "We could not deliver order {n} after several attempts. Our team will contact you about a new delivery or a refund.", True),
    "order_cancelled": ("Order {n} cancelled", "Your order {n} was cancelled.", True),
    "refund_succeeded": ("Refund of {amount} issued for order {n}",
                         "A refund of {amount} was issued for order {n}. When it shows in your account depends on your bank or payment method.", True),
    "return_approved": ("Return approved for order {n}", "Your return request for order {n} was approved. A refund follows.", True),
    "return_rejected": ("Return not approved for order {n}", "Your return request for order {n} was not approved. Open the order for details.", True),
    "prescription_approved": ("Prescription approved", "A pharmacist approved your prescription. You can now order the approved medicines.", True),
    "prescription_rejected": ("Prescription not approved", "A pharmacist could not approve your prescription. Open it to see why.", True),
    "prescription_clarification": ("Prescription: the pharmacist needs more information",
                                   "A pharmacist has a question about your prescription. Open it to reply.", True),
}


def rupees(paise: int) -> str:
    return f"Rs {paise // 100}.{paise % 100:02d}"


def render(event: str, n: str = "", amount_paise: int = 0) -> tuple[str, str, bool]:
    title, body, email = EVENTS[event]
    fmt = {"n": n, "amount": rupees(amount_paise)}
    return title.format(**fmt), body.format(**fmt), email
