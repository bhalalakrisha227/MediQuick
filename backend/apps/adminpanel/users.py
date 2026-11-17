"""
Account administration for admins. No Django / MongoDB imports.

Deliberately small: list accounts and switch one on or off. Roles are NOT editable here (staff roles are created
with the create_staff_user command on the server), so a stolen admin session cannot promote anyone.
Switching an account off takes effect on the next request (tokens are re-checked against the database) and blocks refresh.
"""
import re

from apps.accounts import roles as role_names
from apps.accounts.errors import ServiceError

from . import rules
from .attention import AuditLog


def _forbidden():
    return ServiceError("forbidden", "You do not have permission to perform this action.", 403)


def public_account(u: dict) -> dict:
    return {"id": u["_id"], "email": u["email"], "full_name": u.get("full_name", ""), "role": u["role"],
            "is_active": bool(u.get("is_active")), "created_at": u["created_at"].isoformat()}


class UserAdminService:
    def __init__(self, users, audit: AuditLog, clock):
        self.users, self.audit, self.clock = users, audit, clock

    def list(self, role: str, params: dict) -> dict:
        if role not in rules.USER_ADMIN_ROLES:
            raise _forbidden()
        q = params.get("q", "")
        wanted = params.get("role", "")
        if not isinstance(q, str) or len(q) > 100:
            raise ServiceError("validation_error", "Search text is too long.", 400, {"q": "At most 100 characters."})
        if wanted and wanted not in role_names.ALL_ROLES:
            raise ServiceError("validation_error", "Unknown role.", 400, {"role": "Unknown role."})
        page = int(params["page"]) if str(params.get("page", "")).isdigit() and int(params["page"]) >= 1 else 1
        rows, total = self.users.list_page(re.escape(q.strip()), wanted, (page - 1) * rules.USER_PAGE_SIZE, rules.USER_PAGE_SIZE)
        return {"results": [public_account(u) for u in rows], "page": page, "page_size": rules.USER_PAGE_SIZE, "total": total}

    def set_active(self, actor_id: str, role: str, user_id, data: dict) -> dict:
        if role not in rules.USER_ADMIN_ROLES:
            raise _forbidden()
        active = data.get("active") if isinstance(data, dict) else None
        note = (data.get("note") or "").strip() if isinstance(data, dict) and isinstance(data.get("note"), str) else ""
        if not isinstance(active, bool):
            raise ServiceError("validation_error", "Send active as true or false.", 400, {"active": "Must be true or false."})
        if not rules.MIN_NOTE <= len(note) <= rules.MAX_NOTE:
            raise ServiceError("validation_error", "Write the reason (5 to 500 characters).", 400, {"note": "Required."})
        target = self.users.get(user_id) if isinstance(user_id, str) else None
        if not target:
            raise ServiceError("not_found", "Account not found.", 404)
        if target["_id"] == actor_id:
            raise ServiceError("own_account", "You cannot change your own account.", 409)
        if bool(target.get("is_active")) == active:
            return public_account(target)
        self.users.update(target["_id"], {"is_active": active})
        if not active and target["role"] == role_names.ADMIN and self.users.count_active_admins() == 0:
            self.users.update(target["_id"], {"is_active": True})       # never leave the shop without an admin
            raise ServiceError("last_admin", "This is the last active admin account.", 409)
        self.audit.record(actor_id, role, "account_activated" if active else "account_deactivated", "user", target["_id"],
                          {"note": note, "target_role": target["role"]})
        return public_account(self.users.get(target["_id"]))
