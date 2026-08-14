from dataclasses import dataclass
from uuid import UUID, uuid4

from app.core.types import ActorType, AppRole


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: UUID
    correlation_id: UUID
    actor_type: ActorType
    actor_id: str | None = None
    role: AppRole | None = None
    branch_ids: tuple[str, ...] = ()
    ip_key: str | None = None
    user_agent_hash: str | None = None

    @classmethod
    def anonymous(cls) -> "RequestContext":
        return cls(
            request_id=uuid4(),
            correlation_id=uuid4(),
            actor_type=ActorType.GUEST,
        )

    def safe_log_fields(self) -> dict[str, str]:
        return {
            "requestId": str(self.request_id),
            "correlationId": str(self.correlation_id),
            "actorType": self.actor_type,
        }
