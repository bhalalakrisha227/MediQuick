"""Input validation. Pure Python so it can be tested without Django."""
import re

from .errors import ValidationFailed

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9]{10,13}$")
PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")
COMMON_PASSWORDS = {
    "password", "password1", "password123", "1234567890", "12345678910", "qwertyuiop",
    "iloveyou123", "admin12345", "welcome123", "letmein123", "medicine123",
}
MAX_ADDRESSES = 10


def _text(data: dict, key: str, errors: dict, *, required=True, min_len=0, max_len=200) -> str:
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[key] = "This field is required."
        return ""
    if not isinstance(value, str):
        errors[key] = "Must be text."
        return ""
    value = value.strip()
    if len(value) < min_len or len(value) > max_len:
        errors[key] = f"Must be between {min_len} and {max_len} characters."
    return value


def normalize_email(value: str) -> str:
    return value.strip().lower()


def password_problems(password: str, email: str = "") -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("Use at least 10 characters.")
    if len(password) > 128:
        problems.append("Use at most 128 characters.")
    if password.isdigit():
        problems.append("Must not be only digits.")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("This password is too common.")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        problems.append("Must not contain your email name.")
    return problems


def _phone(data: dict, key: str, errors: dict, required=False) -> str:
    raw = _text(data, key, errors, required=required, max_len=20)
    if not raw:
        return ""
    cleaned = re.sub(r"[\s-]", "", raw)
    if not PHONE_RE.match(cleaned):
        errors[key] = "Enter a valid phone number (10-13 digits, optional +)."
    return cleaned


def validate_registration(data: dict) -> dict:
    errors: dict = {}
    email = normalize_email(_text(data, "email", errors, max_len=254))
    if email and not EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address."
    full_name = _text(data, "full_name", errors, min_len=2, max_len=80)
    phone = _phone(data, "phone", errors)
    password = data.get("password")
    if not isinstance(password, str) or not password:
        errors["password"] = "This field is required."
    else:
        problems = password_problems(password, email)
        if problems:
            errors["password"] = " ".join(problems)
    if errors:
        raise ValidationFailed(errors)
    return {"email": email, "full_name": full_name, "phone": phone, "password": password}


def validate_profile_update(data: dict) -> dict:
    errors: dict = {}
    cleaned: dict = {}
    if "full_name" in data:
        cleaned["full_name"] = _text(data, "full_name", errors, min_len=2, max_len=80)
    if "phone" in data:
        cleaned["phone"] = _phone(data, "phone", errors)
    if not cleaned and not errors:
        errors["non_field"] = "Provide full_name and/or phone."
    if errors:
        raise ValidationFailed(errors)
    return cleaned


def validate_address(data: dict, partial: bool = False) -> dict:
    errors: dict = {}
    cleaned: dict = {}
    spec = {
        "label": dict(required=False, max_len=30),
        "recipient_name": dict(min_len=2, max_len=80),
        "line1": dict(min_len=3, max_len=120),
        "line2": dict(required=False, max_len=120),
        "landmark": dict(required=False, max_len=80),
        "city": dict(min_len=2, max_len=60),
        "state": dict(min_len=2, max_len=60),
    }
    for key, opts in spec.items():
        if partial and key not in data:
            continue
        cleaned[key] = _text(data, key, errors, **opts)
    if not partial or "phone" in data:
        cleaned["phone"] = _phone(data, "phone", errors, required=True)
    if not partial or "pincode" in data:
        pin = data.get("pincode")
        pin = pin.strip() if isinstance(pin, str) else (str(pin) if isinstance(pin, int) else "")
        if not PINCODE_RE.match(pin):
            errors["pincode"] = "Enter a valid 6-digit PIN code."
        cleaned["pincode"] = pin
    if "is_default" in data:
        if not isinstance(data["is_default"], bool):
            errors["is_default"] = "Must be true or false."
        cleaned["is_default"] = data["is_default"] is True
    if not partial and not cleaned.get("label"):
        cleaned["label"] = "Home"
    if errors:
        raise ValidationFailed(errors)
    return cleaned
