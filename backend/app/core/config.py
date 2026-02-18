import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings:
    """
    Application settings loaded from environment variables.
    Reference: LDD Section 5 (.env)
    """

    # Google Cloud Config
    GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "project-the491")
    GCP_LOCATION: str = os.getenv("GCP_LOCATION", "asia-southeast1")
    GCP_STORAGE_BUCKET: str = os.getenv("GCP_STORAGE_BUCKET", "the491-receipts")
    # Service-specific regions (fallback to GCP_LOCATION for backward compatibility)
    DOCAI_LOCATION: str = os.getenv(
        "DOCAI_LOCATION", os.getenv("GCP_LOCATION", "asia-southeast1")
    )
    VERTEX_AI_LOCATION: str = os.getenv(
        "VERTEX_AI_LOCATION", os.getenv("GCP_LOCATION", "asia-southeast1")
    )

    # Document AI
    DOCAI_PROCESSOR_ID: str = os.getenv("DOCAI_PROCESSOR_ID", "")

    # Vertex AI
    VERTEX_AI_MODEL: str = os.getenv("VERTEX_AI_MODEL", "gemini-pro")
    VERTEX_AI_RECEIPT_MODEL: str = os.getenv(
        "VERTEX_AI_RECEIPT_MODEL",
        "gemini-2.5-flash-lite",
    )
    RECEIPT_EXTRACTION_MODE: str = os.getenv(
        "RECEIPT_EXTRACTION_MODE", "vision_first"
    ).strip().lower()
    VISION_TIMEOUT_MS: int = _env_int("VISION_TIMEOUT_MS", 9000)
    VISION_MAX_RETRY: int = _env_int("VISION_MAX_RETRY", 0)
    VISION_PREPROCESS_ENABLED: bool = _env_bool("VISION_PREPROCESS_ENABLED", True)
    VISION_MAX_IMAGE_EDGE: int = _env_int("VISION_MAX_IMAGE_EDGE", 1400)
    VISION_JPEG_QUALITY: int = _env_int("VISION_JPEG_QUALITY", 78)
    OCR_REFINEMENT_ENABLED: bool = _env_bool("OCR_REFINEMENT_ENABLED", True)
    OCR_PREPROCESS_ENABLED: bool = _env_bool("OCR_PREPROCESS_ENABLED", True)
    OCR_MAX_IMAGE_EDGE: int = _env_int("OCR_MAX_IMAGE_EDGE", 1600)
    OCR_JPEG_QUALITY: int = _env_int("OCR_JPEG_QUALITY", 85)

    # Database
    FIRESTORE_DB: str = os.getenv("FIRESTORE_DB", "(default)")
    BIGQUERY_DATASET: str = os.getenv("BIGQUERY_DATASET", "the491_analytics")
    _SIGNED_URL_EXPIRY_SECONDS_RAW: str = os.getenv("SIGNED_URL_EXPIRY_SECONDS", "1800")
    try:
        SIGNED_URL_EXPIRY_SECONDS: int = int(_SIGNED_URL_EXPIRY_SECONDS_RAW)
    except ValueError:
        SIGNED_URL_EXPIRY_SECONDS: int = 1800

    # Security
    FIREBASE_CREDENTIALS_PATH: str = os.getenv(
        "FIREBASE_CREDENTIALS_PATH", "./firebase-adminsdk.json"
    )


settings = Settings()
