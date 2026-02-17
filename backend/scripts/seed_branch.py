#!/usr/bin/env python3
"""Seed one branch document into Firestore."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import firestore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update a branch document in Firestore."
    )
    parser.add_argument("--branch-id", default="branch_001", help="Firestore document ID")
    parser.add_argument("--name", default="Siam Square One", help="Branch name")
    parser.add_argument(
        "--type",
        default="COFFEE",
        choices=["COFFEE", "RESTAURANT"],
        help="Business type for this branch",
    )
    parser.add_argument(
        "--collection",
        default="branches",
        help="Firestore collection name",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env")

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        raise SystemExit("Missing GCP_PROJECT_ID in environment/.env")

    firestore_db = os.getenv("FIRESTORE_DB", "(default)")

    db = firestore.Client(project=project_id, database=firestore_db)
    doc_ref = db.collection(args.collection).document(args.branch_id)

    payload = {
        "id": args.branch_id,
        "name": args.name,
        "type": args.type,
    }

    doc_ref.set(payload, merge=True)

    print("Seed complete")
    print(f"project={project_id}")
    print(f"database={firestore_db}")
    print(f"document={args.collection}/{args.branch_id}")
    print(f"payload={payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
