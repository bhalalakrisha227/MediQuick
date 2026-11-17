"""DRF authentication: verifies the Bearer access token, then re-checks the user in the database."""
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from . import deps, security


class AuthUser:
    is_authenticated = True

    def __init__(self, doc: dict):
        self.id = doc["_id"]
        self.email = doc["email"]
        self.full_name = doc.get("full_name", "")
        self.role = doc["role"]  # taken from the database, not from the token

    @property
    def pk(self):
        return self.id


class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Invalid Authorization header.")
        services = deps.get_services()
        try:
            payload = security.decode_access_token(parts[1].decode("utf-8"), services.config.jwt_secret)
        except (security.TokenError, UnicodeDecodeError):
            raise AuthenticationFailed("Invalid or expired token.")
        user = services.users.get(payload["sub"])
        if user is None or not user.get("is_active"):
            raise AuthenticationFailed("Account not available.")
        return AuthUser(user), payload

    def authenticate_header(self, request):
        return "Bearer"
