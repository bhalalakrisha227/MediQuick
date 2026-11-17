"""Prescription statuses and limits.

OCR can never reach `approved`. Only a pharmacist's explicit action (review.py) does.
Numbers below are engineering placeholders, not verified legal rules (see docs/COMPLIANCE_CHECKLIST.md).
"""

PROCESSING = "processing"
NEEDS_REVIEW = "needs_customer_review"
SUBMITTED = "submitted"
IN_REVIEW = "in_review"
CLARIFICATION = "clarification_requested"
APPROVED = "approved"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"

# Count towards the "same file twice" rule (rejected and withdrawn files may be uploaded again).
ACTIVE_STATUSES = (PROCESSING, NEEDS_REVIEW, SUBMITTED, IN_REVIEW, CLARIFICATION, APPROVED)
DRAFT_STATUSES = (PROCESSING, NEEDS_REVIEW)          # count towards the draft limit
CUSTOMER_EDITABLE = (NEEDS_REVIEW, CLARIFICATION)    # the customer may edit/submit in these
CUSTOMER_WITHDRAWABLE = (PROCESSING, NEEDS_REVIEW, CLARIFICATION)
STAFF_VISIBLE = (SUBMITTED, IN_REVIEW, CLARIFICATION, APPROVED, REJECTED)   # never drafts or withdrawn
QUEUE_STATUSES = (SUBMITTED, IN_REVIEW)

VIEW_ROLES = ("pharmacist", "pharmacy_manager", "admin")   # may see the queue, details and files (logged)
DECIDE_ROLES = ("pharmacist",)                              # may claim, approve, reject, ask questions
RELEASE_ROLES = ("pharmacist", "pharmacy_manager", "admin")  # may release a claim (managers unstick abandoned reviews)
STAFF_FILE_ROLES = VIEW_ROLES

# Wording is a DRAFT and must be reviewed by a qualified lawyer before real use.
CONSENT_VERSION = "draft-1"
CONSENT_TEXT = ("I confirm this is my own (or my dependant's) prescription. I understand the text read from the image "
                "is automatic, may be wrong, and a pharmacist will check the original before anything is approved.")

MAX_ITEMS = 30
MAX_NOTES = 300
MAX_DRAFTS = 10
MAX_OCR_TEXT = 20_000
MAX_OCR_LINES = 200

# Pharmacist approval limits (placeholders)
MAX_APPROVED_ITEMS = 20
MAX_APPROVED_QUANTITY = 100
DEFAULT_VALID_DAYS = 30
MAX_VALID_DAYS = 180
MAX_REASON = 500
