"""Domain errors that map cleanly onto HTTP responses."""

from __future__ import annotations


class Pull1secError(Exception):
    """Base class for expected, user-facing failures."""

    code = "error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class MediaUnavailableError(Pull1secError):
    """The link is valid but the media cannot be retrieved."""

    code = "media_unavailable"
    status_code = 422


class UnsupportedSiteError(MediaUnavailableError):
    code = "unsupported_site"


class AuthenticationRequiredError(MediaUnavailableError):
    code = "authentication_required"


class JobNotFoundError(Pull1secError):
    code = "job_not_found"
    status_code = 404


class JobNotReadyError(Pull1secError):
    code = "job_not_ready"
    status_code = 409


class TooManyJobsError(Pull1secError):
    code = "too_many_jobs"
    status_code = 429


class UnauthorizedError(Pull1secError):
    """A request that needs a session arrived without a valid one."""

    code = "unauthorized"
    status_code = 401


class AuthSetupRequiredError(Pull1secError):
    """No account exists yet, so nobody can log in."""

    code = "auth_not_configured"
    status_code = 409


class BadCredentialsError(Pull1secError):
    code = "bad_credentials"
    status_code = 401


class TooManyAttemptsError(Pull1secError):
    """Too many failed logins from this address."""

    code = "too_many_attempts"
    status_code = 429
