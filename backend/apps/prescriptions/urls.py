from django.urls import path

from . import views

urlpatterns = [
    path("prescriptions/", views.PrescriptionListCreateView.as_view(), name="prescriptions"),
    path("prescriptions/allowances/", views.AllowancesView.as_view(), name="prescription-allowances"),
    path("prescriptions/<str:prescription_id>/", views.PrescriptionDetailView.as_view(), name="prescription-detail"),
    path("prescriptions/<str:prescription_id>/submit/", views.PrescriptionSubmitView.as_view(), name="prescription-submit"),
    path("prescriptions/<str:prescription_id>/withdraw/", views.PrescriptionWithdrawView.as_view(), name="prescription-withdraw"),
    path("prescriptions/<str:prescription_id>/retry-ocr/", views.PrescriptionRetryView.as_view(), name="prescription-retry"),
    path("prescriptions/<str:prescription_id>/file/", views.PrescriptionFileView.as_view(), name="prescription-file"),
    # pharmacist portal
    path("staff/prescriptions/", views.ReviewQueueView.as_view(), name="review-queue"),
    path("staff/prescriptions/<str:prescription_id>/", views.ReviewDetailView.as_view(), name="review-detail"),
    path("staff/prescriptions/<str:prescription_id>/claim/", views.ReviewClaimView.as_view(), name="review-claim"),
    path("staff/prescriptions/<str:prescription_id>/release/", views.ReviewReleaseView.as_view(), name="review-release"),
    path("staff/prescriptions/<str:prescription_id>/approve/", views.ReviewApproveView.as_view(), name="review-approve"),
    path("staff/prescriptions/<str:prescription_id>/reject/", views.ReviewRejectView.as_view(), name="review-reject"),
    path("staff/prescriptions/<str:prescription_id>/clarify/", views.ReviewClarifyView.as_view(), name="review-clarify"),
]
