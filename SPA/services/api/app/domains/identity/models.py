from dataclasses import dataclass

from app.core.types import AppRole


@dataclass(frozen=True, slots=True)
class FirebaseIdentity:
    uid: str
    email: str
    email_verified: bool


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    uid: str
    email: str
    role: AppRole
    branch_ids: tuple[str, ...]

    def require_branch(self, branch_id: str) -> None:
        from app.core.errors import AuthorizationProfileIncomplete, PermissionDenied

        if not self.branch_ids:
            raise AuthorizationProfileIncomplete("Admin branch scope is not configured")
        if branch_id not in self.branch_ids:
            raise PermissionDenied("Admin is not authorized for this branch")


@dataclass(frozen=True, slots=True)
class LinePrincipal:
    user_id: str
    channel_id: str
