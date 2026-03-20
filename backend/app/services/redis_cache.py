import json
import logging
from threading import Lock
from typing import Any

from app.core.config import settings

try:
    import redis
except Exception:  # pragma: no cover - optional dependency until installed in runtime
    redis = None


logger = logging.getLogger(__name__)
_client_lock = Lock()
_redis_client = None


def _is_redis_configured() -> bool:
    return bool(settings.REDIS_ENABLED and settings.REDIS_HOST)


def get_client():
    global _redis_client

    if not _is_redis_configured() or redis is None:
        return None

    with _client_lock:
        if _redis_client is not None:
            return _redis_client

        try:
            _redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=max(0.1, float(settings.REDIS_CONNECT_TIMEOUT_SECONDS)),
                socket_timeout=max(0.1, float(settings.REDIS_SOCKET_TIMEOUT_SECONDS)),
                health_check_interval=30,
            )
        except Exception as exc:
            logger.warning("Redis client initialization failed: %s", str(exc))
            _redis_client = None

        return _redis_client


def get_json(key: str) -> Any | None:
    client = get_client()
    if client is None:
        return None

    try:
        raw_value = client.get(key)
        if raw_value is None:
            return None
        return json.loads(raw_value)
    except Exception as exc:
        logger.warning("Redis get failed for key '%s': %s", key, str(exc))
        return None


def set_json(key: str, value: Any, ttl_seconds: int) -> bool:
    client = get_client()
    if client is None:
        return False

    try:
        payload = json.dumps(value, ensure_ascii=False)
        client.set(name=key, value=payload, ex=max(1, int(ttl_seconds)))
        return True
    except Exception as exc:
        logger.warning("Redis set failed for key '%s': %s", key, str(exc))
        return False
