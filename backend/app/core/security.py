import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import auth, credentials

from app.core.config import settings

# --- Firebase Admin SDK Initialization ---
# This logic supports two authentication methods:
# 1. JSON Key File: If FIREBASE_CREDENTIALS_PATH is set and the file exists.
# 2. Application Default Credentials (ADC): If the path is not set, it uses ADC,
#    perfect for `gcloud auth` or Cloud Run environments.

if not firebase_admin._apps:
    cred_path = settings.FIREBASE_CREDENTIALS_PATH
    # Check if the path is not the default empty one and if the file actually exists
    if cred_path and os.path.exists(cred_path):
        print(f"✅ Initializing Firebase with key file: {cred_path}")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        print("✅ Initializing Firebase with Application Default Credentials (ADC).")
        # If no cred path, initialize_app() automatically finds ADC
        firebase_admin.initialize_app()

# Security scheme for Swagger UI
security_scheme = HTTPBearer()


async def verify_token(
    creds: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> dict:
    """
    FastAPI dependency that extracts and verifies a Firebase ID token
    from the Authorization: Bearer <token> header.

    Reference: HLD Section 4 (Security), LDD Section 5 (Config)

    Returns:
        dict: Decoded token payload containing at least 'uid'.

    Raises:
        HTTPException 401: If token is missing, expired, or invalid.
    """
    token = creds.credentials

    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token  # Contains 'uid', 'email', etc.
    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please re-authenticate.",
        )
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
        )


def get_current_user(decoded_token: dict = Depends(verify_token)) -> dict:
    """
    Convenience dependency that returns the decoded Firebase token.
    Use as: current_user = Depends(get_current_user)

    Returns:
        dict: {'uid': str, 'email': str, ...}
    """
    return decoded_token
