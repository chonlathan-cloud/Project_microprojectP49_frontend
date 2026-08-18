"""Seed the minimum SPA branch configuration into the named Firestore database."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import firestore

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "the49-487609")
DATABASE = os.getenv("FIRESTORE_DATABASE", "spa-db")
BRANCH_ID = os.getenv("DEFAULT_BRANCH_ID", "branch_001")
ADMIN_EMAIL = os.getenv("SPA_ADMIN_EMAIL", "chonlathan@manee-son.com").strip().lower()


def main() -> None:
    client = firestore.Client(project=PROJECT_ID, database=DATABASE)
    now = datetime.now(UTC)
    batch = client.batch()
    branch_ref = client.collection("branches").document(BRANCH_ID)
    map_url = "https://www.bing.com/maps/search?q=53%2F72+ถนนเฉลิมพระเกียรติ+ร.+9+หนองบอน+ประเวศ+กรุงเทพมหานคร+10250"
    batch.set(
        branch_ref,
        {
            "branchId": BRANCH_ID,
            "name": "SPA49",
            "phone": "0643654949",
            "address": "53/72 ถนนเฉลิมพระเกียรติ ร.9 แขวงหนองบอน เขตประเวศ กรุงเทพมหานคร 10250",
            "mapUrl": map_url,
            "timezone": "Asia/Bangkok",
            "currency": "THB",
            "capacityUnits": 7,
            "activeCapacityUnits": 5,
            "bufferMinutes": 0,
            "operatingHours": {str(day): {"open": "10:00", "close": "22:00"} for day in range(7)},
            "bookingWindow": {"minDays": 1, "maxDays": 30},
            "priceIncludesVat": True,
            "healthRetentionYears": 3,
            "healthRetentionPolicyVersion": "health-3y-approved-v1",
            "active": True,
            "updatedAt": now,
        },
        merge=True,
    )
    for index in range(1, 8):
        resource_ref = client.collection("resources").document(f"bed_{index:03d}")
        batch.set(
            resource_ref,
            {
                "branchId": BRANCH_ID,
                "resourceId": f"bed_{index:03d}",
                "name": f"Treatment bed {index}",
                "type": "BED",
                "capacityUnits": 1,
                "active": index <= 5,
                "flexible": True,
                "version": 1,
                "updatedAt": now,
            },
            merge=True,
        )
    catalog_path = Path(__file__).with_name("service-catalog.v1.json")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    for service in catalog["services"]:
        service_ref = client.collection("services").document(service["id"])
        batch.set(
            service_ref,
            {
                "branchId": BRANCH_ID,
                "serviceId": service["id"],
                "category": service["category"],
                "nameTh": service["nameTh"],
                "nameEn": service["nameEn"],
                "descriptionTh": service["descriptionTh"],
                "descriptionEn": service["descriptionEn"],
                "displayOrder": service["displayOrder"],
                "active": service["active"],
                "variants": [
                    {
                        "variantId": variant["id"],
                        "durationMinutes": variant["durationMinutes"],
                        "priceSatang": variant["priceSatang"],
                        "pricingMode": variant["pricingMode"],
                        "requiredPax": variant["requiredPax"],
                        "active": variant["active"],
                        "resourceRequirements": [{"resourceType": "BED", "units": 1}],
                    }
                    for variant in service["variants"]
                ],
                "updatedAt": now,
            },
            merge=True,
        )
    invite_ref = client.collection("admin_invites").document(ADMIN_EMAIL.replace("@", "_at_"))
    batch.set(
        invite_ref,
        {
            "email": ADMIN_EMAIL,
            "role": "ADMIN",
            "active": True,
            "updatedAt": now,
        },
        merge=True,
    )
    batch.commit()
    print(f"Seeded {BRANCH_ID} into projects/{PROJECT_ID}/databases/{DATABASE}")


if __name__ == "__main__":
    main()
