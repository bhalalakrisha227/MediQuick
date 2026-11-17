"""
Notifications: an in-app list plus an email outbox. No Django / MongoDB imports.

Safety design:
 * A notification can never break the action that caused it: every emit is wrapped, failures are only logged.
 * One notification per (event, entity, occurrence) - a unique key - so retries cannot send duplicates.
 * Emails go through an outbox with an atomic claim and a lease, bounded retries with back-off, and a permanent
   failure state. Nothing is sent from inside the web request; a worker command sends them.
 * Messages never contain medicine names, addresses or the delivery code (see rules.py).
 * Users can switch email off; in-app notifications always exist.
"""
import logging
import uuid
from datetime import timedelta

from apps.accounts.errors import DuplicateError, ServiceError

from . import rules
from .email_adapters import EmailError

logger = logging.getLogger(__name__)


def public_notification(n: dict) -> dict:
    return {"id": n["_id"], "event": n["event"], "title": n["title"], "body": n["body"], "link": n["link"],
            "read": n.get("read_at") is not None, "created_at": n["created_at"].isoformat()}


class NotificationService:
    def __init__(self, repo, users, email, base_url, clock):
        self.repo, self.users, self.email, self.base_url, self.clock = repo, users, email, base_url.rstrip("/"), clock

    # ---- creating (called by observers; never raises) -------------------------
    def emit(self, event: str, user_id, entity_id: str, link: str, occurrence=0, order_number="", amount_paise=0) -> bool:
        try:
            title, body, wants_email = rules.render(event, order_number, amount_paise)
            user = self.users.get(user_id) if isinstance(user_id, str) else None
            if not user:
                return False
            now = self.clock()
            email_on = wants_email and user.get("notify_email", True) and bool(user.get("email"))
            doc = {"_id": uuid.uuid4().hex, "key": f"{event}:{entity_id}:{occurrence}", "user_id": user_id, "event": event,
                   "entity_id": entity_id, "title": title, "body": body, "link": link, "created_at": now, "read_at": None,
                   "email": {"status": "pending" if email_on else "skipped", "attempts": 0, "next_attempt_at": now,
                             "lease_until": None, "last_error": ""}}
            try:
                self.repo.insert(doc)
            except DuplicateError:
                return False
            return True
        except Exception:
            logger.exception("Could not create notification %s", event)
            return False

    # ---- customer API ---------------------------------------------------------
    def list(self, user_id: str, unread_only=False, page=1) -> dict:
        page = page if isinstance(page, int) and page >= 1 else 1
        rows, total = self.repo.list_for_user(user_id, unread_only, (page - 1) * rules.PAGE_SIZE, rules.PAGE_SIZE)
        return {"results": [public_notification(n) for n in rows], "page": page, "total": total,
                "unread": self.repo.unread_count(user_id)}

    def unread_count(self, user_id: str) -> dict:
        return {"unread": self.repo.unread_count(user_id)}

    def mark_read(self, user_id: str, notification_id) -> dict:
        if not isinstance(notification_id, str) or not self.repo.mark_read(user_id, notification_id, self.clock()):
            # Either not theirs or not there. Marking an already-read one is fine, so check it is theirs.
            n = self.repo.get(notification_id) if isinstance(notification_id, str) else None
            if not n or n["user_id"] != user_id:
                raise ServiceError("not_found", "Notification not found.", 404)
        return self.unread_count(user_id)

    def mark_all_read(self, user_id: str) -> dict:
        self.repo.mark_all_read(user_id, self.clock())
        return self.unread_count(user_id)

    def get_settings(self, user_id: str) -> dict:
        user = self.users.get(user_id) or {}
        return {"email": bool(user.get("notify_email", True)), "email_provider": self.email.name if self.email else "none",
                "sms": False}

    def update_settings(self, user_id: str, data: dict) -> dict:
        value = data.get("email") if isinstance(data, dict) else None
        if not isinstance(value, bool):
            raise ServiceError("validation_error", "Send email as true or false.", 400, {"email": "Must be true or false."})
        self.users.update(user_id, {"notify_email": value})
        return self.get_settings(user_id)

    # ---- worker ---------------------------------------------------------------
    def send_due(self, limit=50) -> dict:
        counts = {"sent": 0, "retry": 0, "failed": 0, "skipped": 0}
        for _ in range(limit):
            now = self.clock()
            n = self.repo.claim_due(now, now + timedelta(minutes=rules.LEASE_MINUTES))
            if not n:
                break
            counts[self._send_one(n)] += 1
        return counts

    def _send_one(self, n: dict) -> str:
        now, attempts = self.clock(), n["email"]["attempts"] + 1
        user = self.users.get(n["user_id"])
        if self.email is None or not user or not user.get("email") or not user.get("notify_email", True):
            self.repo.finish_email(n["_id"], {"status": "skipped", "attempts": attempts, "last_error": "email not sent (disabled, off or no address)"})
            return "skipped"
        text = f"{n['body']}\n\n{self.base_url}{n['link']}\n\nMediQuick. This is an automated message. We never ask for your password, OTP or payment details by email."
        try:
            self.email.send(user["email"], n["title"], text)
        except EmailError as exc:
            if exc.permanent or attempts >= rules.MAX_EMAIL_ATTEMPTS:
                self.repo.finish_email(n["_id"], {"status": "failed", "attempts": attempts, "last_error": str(exc)[:200]})
                return "failed"
            wait = rules.BACKOFF_MINUTES[min(attempts - 1, len(rules.BACKOFF_MINUTES) - 1)]
            self.repo.finish_email(n["_id"], {"status": "pending", "attempts": attempts, "last_error": str(exc)[:200],
                                              "next_attempt_at": now + timedelta(minutes=wait)})
            return "retry"
        except Exception:
            logger.exception("Unexpected error sending notification %s", n["_id"])
            self.repo.finish_email(n["_id"], {"status": "failed", "attempts": attempts, "last_error": "unexpected error"})
            return "failed"
        self.repo.finish_email(n["_id"], {"status": "sent", "attempts": attempts, "last_error": "", "sent_at": now})
        return "sent"
