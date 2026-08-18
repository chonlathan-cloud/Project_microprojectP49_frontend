from functools import lru_cache

from google.cloud import storage

from app.core.settings import get_settings


@lru_cache
def get_storage_client() -> storage.Client:
    return storage.Client(project=get_settings().gcp_project_id)


def get_service_assets_bucket() -> storage.Bucket:
    bucket_name = get_settings().service_assets_bucket.strip()
    if not bucket_name:
        raise RuntimeError("SERVICE_ASSETS_BUCKET is not configured")
    return get_storage_client().bucket(bucket_name)
