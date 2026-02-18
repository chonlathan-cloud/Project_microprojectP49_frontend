import os
from dotenv import load_dotenv

load_dotenv()


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
