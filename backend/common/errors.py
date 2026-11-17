"""
One JSON error shape for everything, including bugs. An unexpected error returns a generic message and a short
reference id; the details (stack trace) go to the server log only, never to the client.
"""
import logging
import uuid

logger = logging.getLogger(__name__)


def error_body(code: str, message: str, reference: str | None = None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if reference:
        body["error"]["reference"] = reference
    return body


def new_reference() -> str:
    return uuid.uuid4().hex[:10]


def api_exception_handler(exc, context):
    """DRF EXCEPTION_HANDLER: keep DRF's own handling for known errors (401/403/404/405/throttle), but use our shape;
    anything unexpected becomes a generic 500 with a reference id."""
    from rest_framework.response import Response
    from rest_framework.views import exception_handler

    response = exception_handler(exc, context)
    if response is not None:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        status = response.status_code
        code = {400: "bad_request", 401: "not_authenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                415: "unsupported_media_type", 429: "rate_limited"}.get(status, "error")
        message = str(detail) if detail else "The request could not be processed."
        if status == 429:
            message = "Too many requests. Please slow down and try again shortly."
        return Response(error_body(code, message), status=status, headers={k: v for k, v in response.items() if k == "Retry-After"})
    ref = new_reference()
    logger.error("Unhandled error [%s] in %s", ref, getattr(context.get("view"), "__class__", type(None)).__name__, exc_info=exc)
    return Response(error_body("server_error", "Something went wrong on our side. Please try again.", ref), status=500)


def json_404(request, exception=None):
    from django.http import JsonResponse
    return JsonResponse(error_body("not_found", "Not found."), status=404)


def json_500(request):
    from django.http import JsonResponse
    ref = new_reference()
    logger.error("Server error [%s] for %s", ref, request.path)
    return JsonResponse(error_body("server_error", "Something went wrong on our side. Please try again.", ref), status=500)
