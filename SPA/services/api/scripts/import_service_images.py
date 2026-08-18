"""Import the legacy local service covers into private Cloud Storage.

Dry-run is the default. Pass --apply after provisioning the target bucket.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from google.cloud import firestore, storage

from app.domains.catalog.images import OUTPUT_SIZE, normalize_service_image

SPA_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_IMAGE_DIR = SPA_ROOT / "apps/customer-web/public/images/services"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write objects and Firestore metadata")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing Firestore image metadata",
    )
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_id = os.getenv("GCP_PROJECT_ID", "the49-487609")
    database = os.getenv("FIRESTORE_DATABASE", "spa-db")
    bucket_name = os.getenv("SERVICE_ASSETS_BUCKET", "").strip()
    if not bucket_name:
        raise SystemExit("SERVICE_ASSETS_BUCKET is required")

    firestore_client = firestore.Client(project=project_id, database=database)
    bucket = storage.Client(project=project_id).bucket(bucket_name)
    candidates = sorted(args.image_dir.glob("*.webp"))
    if not candidates:
        raise SystemExit(f"No WebP files found in {args.image_dir}")

    imported = 0
    skipped = 0
    for source_path in candidates:
        service_id = source_path.stem
        ref = firestore_client.collection("services").document(service_id)
        snapshot = ref.get()
        if not snapshot.exists:
            print(f"SKIP {service_id}: Firestore service does not exist")
            skipped += 1
            continue
        data = snapshot.to_dict() or {}
        current_image = data.get("image") if isinstance(data.get("image"), dict) else {}
        if current_image and not args.replace:
            print(f"SKIP {service_id}: image metadata already exists")
            skipped += 1
            continue
        print(f"{'IMPORT' if args.apply else 'PLAN'} {service_id} <- {source_path.name}")
        if not args.apply:
            continue

        image_version = uuid4().hex
        object_path = (
            f"services/{data.get('branchId', 'branch_001')}/{service_id}/{image_version}.webp"
        )
        normalized = normalize_service_image(source_path.read_bytes(), "image/webp")
        blob = bucket.blob(object_path)
        blob.cache_control = "public, max-age=31536000, immutable"
        blob.upload_from_string(normalized, content_type="image/webp", if_generation_match=0)
        previous_path = str(current_image.get("objectPath", ""))
        try:
            ref.update(
                {
                    "image": {
                        "objectPath": object_path,
                        "version": image_version,
                        "contentType": "image/webp",
                        "width": OUTPUT_SIZE[0],
                        "height": OUTPUT_SIZE[1],
                        "updatedAt": datetime.now(UTC),
                        "updatedBy": "migration:legacy-service-covers",
                    },
                    "version": int(data.get("version", 1)) + 1,
                    "updatedAt": datetime.now(UTC),
                }
            )
        except Exception:
            blob.delete()
            raise
        if previous_path and previous_path != object_path:
            bucket.blob(previous_path).delete()
        imported += 1

    print(f"Done: imported={imported}, skipped={skipped}, apply={args.apply}")


if __name__ == "__main__":
    main()
