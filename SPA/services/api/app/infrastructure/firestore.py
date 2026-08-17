import os
from functools import lru_cache

from google.cloud import firestore

from app.core.settings import get_settings


@lru_cache
def get_firestore_client() -> firestore.Client:
    settings = get_settings()
    return firestore.Client(project=settings.gcp_project_id, database=settings.firestore_database)


def check_firestore_connection() -> tuple[bool, str | None]:
    """Perform a read-only connectivity check against the configured named database."""
    # Avoid waiting on the metadata server during local UI development when no
    # emulator or Application Default Credentials have been configured.
    if not any(
        os.getenv(name)
        for name in ("K_SERVICE", "FIRESTORE_EMULATOR_HOST", "GOOGLE_APPLICATION_CREDENTIALS")
    ):
        return False, "credentials_not_configured"
    try:
        get_firestore_client().collection("_spa_health").limit(1).get(timeout=5)
    except Exception as error:  # pragma: no cover - provider/credential errors vary by runtime
        return False, type(error).__name__
    return True, None
