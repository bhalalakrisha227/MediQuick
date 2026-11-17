"""
Response security headers. The API returns JSON only, never web pages, so the policy can be very strict.

`apply_headers` is plain Python (testable without Django). `SecurityHeadersMiddleware` is the thin Django wrapper.
These headers protect the API's own responses. The React app is served separately and needs its own headers
(see docs/PHASE12_HARDENING.md, "Frontend hosting").
"""

API_PREFIX = "/api/"

STATIC_HEADERS = {
    # No scripts, styles, frames or anything else may load from an API response, and it cannot be framed.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Resource-Policy": "same-site",
}


def apply_headers(headers, path: str) -> None:
    """`headers` is any mapping with setdefault (Django's response.headers works)."""
    for name, value in STATIC_HEADERS.items():
        headers.setdefault(name, value)
    if path.startswith(API_PREFIX):
        # Orders, prescriptions and tokens must never sit in a browser or proxy cache. Views may set a stricter value first.
        headers.setdefault("Cache-Control", "no-store")
        headers.setdefault("Pragma", "no-cache")


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        apply_headers(response.headers, request.path)
        return response
