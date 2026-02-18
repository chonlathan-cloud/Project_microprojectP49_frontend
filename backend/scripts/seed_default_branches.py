#!/usr/bin/env python3
"""Seed default branches for The 49 into Firestore."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import firestore


DEFAULT_BRANCHES = [
    {"id": "branch_coffee", "name": "Coffee Shop", "type": "COFFEE"},
    {"id": "branch_restaurant", "name": "Restaurant", "type": "RESTAURANT"},
    {"id": "branch_steak", "name": "Steak House", "type": "RESTAURANT"},
]


def main() -> int:
    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env")

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        raise SystemExit("Missing GCP_PROJECT_ID in backend/.env")

    firestore_db = os.getenv("FIRESTORE_DB", "(default)")
    db = firestore.Client(project=project_id, database=firestore_db)

    collection = db.collection("branches")
    for branch in DEFAULT_BRANCHES:
        collection.document(branch["id"]).set(branch, merge=True)
        print(f"Upserted branches/{branch['id']} -> {branch}")

    print("Seeded default branches successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
