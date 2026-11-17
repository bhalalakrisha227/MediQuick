from django.conf import settings
from django.http import HttpResponse
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import roles
from apps.accounts.errors import ServiceError
from apps.accounts.permissions import has_role
from apps.accounts.views import body, handle_errors

from . import deps, rules

_ENVELOPE_BYTES = 64 * 1024     # allowance for multipart boundaries and the small text fields


class AuthedView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]


class PrescriptionListCreateView(AuthedView):
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "upload"

    def get_throttles(self):
        # Only uploads are rate limited; listing is not.
        return super().get_throttles() if self.request.method == "POST" else []

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().prescriptions.list(request.user.id))

    @handle_errors
    def post(self, request):
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        if declared > max_bytes + _ENVELOPE_BYTES:
            raise ServiceError("file_too_large", f"The file is larger than {settings.MAX_UPLOAD_SIZE_MB} MB.", 413)
        upload = request.FILES.get("file")
        if upload is None:
            raise ServiceError("validation_error", "Choose a file to upload.", 400, {"file": "A file is required."})
        if upload.size > max_bytes:
            raise ServiceError("file_too_large", f"The file is larger than {settings.MAX_UPLOAD_SIZE_MB} MB.", 413)
        data = upload.read(max_bytes + 1)
        fields = {"consent": request.data.get("consent"), "notes": request.data.get("notes")}
        result = deps.get_services().prescriptions.upload(request.user.id, data, upload.name, fields)
        return Response(result, status=201)


class PrescriptionDetailView(AuthedView):
    @handle_errors
    def get(self, request, prescription_id):
        return Response(deps.get_services().prescriptions.get(request.user.id, prescription_id))

    @handle_errors
    def patch(self, request, prescription_id):
        return Response(deps.get_services().prescriptions.update(request.user.id, prescription_id, body(request)))


class PrescriptionSubmitView(AuthedView):
    @handle_errors
    def post(self, request, prescription_id):
        return Response(deps.get_services().prescriptions.submit(request.user.id, prescription_id))


class PrescriptionWithdrawView(AuthedView):
    @handle_errors
    def post(self, request, prescription_id):
        return Response(deps.get_services().prescriptions.withdraw(request.user.id, prescription_id))


class PrescriptionRetryView(AuthedView):
    @handle_errors
    def post(self, request, prescription_id):
        return Response(deps.get_services().prescriptions.retry_ocr(request.user.id, prescription_id))


class PrescriptionFileView(AuthedView):
    """The original file. Owner, or pharmacy staff once submitted (every staff open is logged). Never cached."""

    @handle_errors
    def get(self, request, prescription_id):
        data, content_type, name = deps.get_services().prescriptions.file_for(request.user.id, request.user.role, prescription_id)
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


class AllowancesView(AuthedView):
    """The customer's approved prescriptions and how many units are still left on each."""

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().allowances.view(request.user.id))


# ----- pharmacist portal (Phase 6). Roles are enforced here AND again inside ReviewService. -----
_VIEW = has_role(roles.PHARMACIST, roles.PHARMACY_MANAGER, roles.ADMIN)
_DECIDE = has_role(roles.PHARMACIST)


def _actor(request):
    u = request.user
    return {"id": u.id, "role": u.role, "name": getattr(u, "full_name", "")}


class StaffView(APIView):
    parser_classes = [JSONParser]


class ReviewQueueView(StaffView):
    permission_classes = [IsAuthenticated, _VIEW]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().review.queue(_actor(request), request.query_params.get("scope", "queue")))


class ReviewDetailView(StaffView):
    permission_classes = [IsAuthenticated, _VIEW]

    @handle_errors
    def get(self, request, prescription_id):
        return Response(deps.get_services().review.detail(_actor(request), prescription_id))


def _action(name, permission, needs_body):
    class _Action(StaffView):
        permission_classes = [IsAuthenticated, permission]

        @handle_errors
        def post(self, request, prescription_id):
            method = getattr(deps.get_services().review, name)
            args = (_actor(request), prescription_id) + ((body(request),) if needs_body else ())
            return Response(method(*args))

    _Action.__name__ = f"Review_{name}_View"
    return _Action


ReviewClaimView = _action("claim", _DECIDE, False)
ReviewReleaseView = _action("release", _VIEW, False)      # managers/admins may free an abandoned claim
ReviewApproveView = _action("approve", _DECIDE, True)
ReviewRejectView = _action("reject", _DECIDE, True)
ReviewClarifyView = _action("clarify", _DECIDE, True)
