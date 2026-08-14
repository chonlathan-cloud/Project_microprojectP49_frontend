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


class CapacityUnavailable(DomainError):
    code = "CAPACITY_UNAVAILABLE"
