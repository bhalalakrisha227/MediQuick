"""Framework-independent error types. Views translate these into HTTP responses."""


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, fields: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = fields or {}


class ValidationFailed(ServiceError):
    def __init__(self, fields: dict):
        super().__init__("validation_error", "Some fields are invalid.", 400, fields)


class DuplicateError(Exception):
    """Raised by repositories when a unique index is violated."""
