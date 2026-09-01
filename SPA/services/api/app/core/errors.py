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


class PaymentNotEligible(DomainError):
    code = "PAYMENT_NOT_ELIGIBLE"


class PaymentMethodUnavailable(DomainError):
    code = "PAYMENT_METHOD_UNAVAILABLE"
    status_code = 422


class PaymentDeviceUnsupported(DomainError):
    code = "PAYMENT_DEVICE_UNSUPPORTED"
    status_code = 422


class FinancialInvariantError(DomainError):
    code = "FINANCIAL_INVARIANT_VIOLATION"


class FinancialConflict(DomainError):
    code = "FINANCIAL_CONFLICT"


class AuthenticationRequired(DomainError):
    code = "AUTHENTICATION_REQUIRED"
    status_code = 401


class AuthenticationInvalid(DomainError):
    code = "AUTHENTICATION_INVALID"
    status_code = 401


class PermissionDenied(DomainError):
    code = "PERMISSION_DENIED"
    status_code = 403


class AuthorizationProfileIncomplete(DomainError):
    code = "AUTHORIZATION_PROFILE_INCOMPLETE"
    status_code = 403


class IdentityProviderUnavailable(DomainError):
    code = "IDENTITY_PROVIDER_UNAVAILABLE"
    status_code = 503


class PersistenceUnavailable(DomainError):
    code = "PERSISTENCE_UNAVAILABLE"
    status_code = 503


class AccountingExportNotEligible(DomainError):
    code = "ACCOUNTING_EXPORT_NOT_ELIGIBLE"


class AccountingExportPurposeUnsupported(DomainError):
    code = "ACCOUNTING_EXPORT_PURPOSE_UNSUPPORTED"
    status_code = 422


class AccountingExportAlreadySynced(DomainError):
    code = "ACCOUNTING_EXPORT_ALREADY_SYNCED"
