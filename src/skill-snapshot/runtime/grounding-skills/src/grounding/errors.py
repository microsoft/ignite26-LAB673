"""Structured errors and stable exit codes shared by all three CLIs."""

from __future__ import annotations

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_BLOCKED = 2  # usage error, validation failure, refused by a safety gate
EXIT_AUTH = 3  # sign-in, tenant/subscription mismatch, missing role
EXIT_SERVICE = 4  # Azure or Wikidata returned an error
EXIT_APPROVAL = 5  # plan ID missing or not equal to the displayed plan


class GroundingError(Exception):
    """An expected failure with a machine-readable code and a next step."""

    def __init__(self, code: str, message: str, next_step: str = "", exit_code: int = EXIT_BLOCKED,
                 detail: object = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_step = next_step
        self.exit_code = exit_code
        self.detail = detail

    def envelope(self) -> dict:
        out = {"ok": False, "code": self.code, "message": self.message}
        if self.next_step:
            out["next_step"] = self.next_step
        if self.detail is not None:
            out["detail"] = self.detail
        return out


class AuthError(GroundingError):
    def __init__(self, code: str, message: str, next_step: str = "", detail: object = None):
        super().__init__(code, message, next_step, EXIT_AUTH, detail)


class ServiceError(GroundingError):
    def __init__(self, code: str, message: str, next_step: str = "", detail: object = None):
        super().__init__(code, message, next_step, EXIT_SERVICE, detail)


class ApprovalError(GroundingError):
    def __init__(self, code: str, message: str, next_step: str = "", detail: object = None):
        super().__init__(code, message, next_step, EXIT_APPROVAL, detail)
