from functools import lru_cache
from typing import Annotated

import firebase_admin
from fastapi import Depends, Header, HTTPException, status
from firebase_admin import auth
from google.cloud import firestore

from app.infrastructure.firestore import get_firestore_client


@lru_cache
def _firebase_app() -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app()


def require_admin_user(
    authorization: Annotated[str | None, Header()] = None,
    client: Annotated[firestore.Client, Depends(get_firestore_client)] = None,
) -> dict[str, object]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required"
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        decoded = auth.verify_id_token(token, app=_firebase_app(), check_revoked=True)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Firebase ID token"
        ) from error

    uid = str(decoded.get("uid", ""))
    user_snapshot = client.collection("app_users").document(uid).get()
    user = user_snapshot.to_dict() if user_snapshot.exists else None
    if not user:
        email = str(decoded.get("email", "")).lower()
        invitations = list(
            client.collection("admin_invites")
            .where("email", "==", email)
            .where("active", "==", True)
            .limit(1)
            .stream()
        )
        if invitations:
            invitation = invitations[0].to_dict() or {}
            user = {"email": email, "role": invitation.get("role", "STAFF"), "active": True}
            client.collection("app_users").document(uid).set(
                {**user, "firebaseUid": uid}, merge=True
            )
    if not user or user.get("active") is not True or user.get("role") not in {"ADMIN", "STAFF"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Active SPA admin invitation required"
        )
    return {"uid": uid, **user}
