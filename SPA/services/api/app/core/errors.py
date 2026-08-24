class DomainError(Exception):
    code = "DOMAIN_ERROR"
    status_code = 409

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidStateTransition(DomainError):
    code = "INVALID_STATE_TRANSITION"


class ValidationDomainError(DomainError):
    code = "VALIDATION_FAILED"
    status_code = 422


class AdvanceWindowViolation(DomainError):
    code = "ADVANCE_WINDOW_VIOLATION"
    status_code = 422


class DependencyUnavailable(DomainError):
    code = "DEPENDENCY_UNAVAILABLE"
    status_code = 503


class CapacityUnavailable(DomainError):
    code = "CAPACITY_UNAVAILABLE"


class ConflictDomainError(DomainError):
    code = "RESOURCE_VERSION_CONFLICT"


class IdempotencyConflict(DomainError):
    code = "IDEMPOTENCY_CONFLICT"


class NotFoundDomainError(DomainError):
    code = "NOT_FOUND"
    status_code = 404


class LineFriendshipRequired(DomainError):
    code = "LINE_FRIENDSHIP_REQUIRED"
    status_code = 422


class DuplicateBooking(DomainError):
    code = "DUPLICATE_BOOKING"


class ActivePendingLimit(DomainError):
    code = "ACTIVE_PENDING_LIMIT"
