from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api.v1.operations import _require_admin_role
from app.core.errors import ValidationDomainError
from app.domains.catalog.images import MAX_UPLOAD_BYTES, OUTPUT_SIZE, normalize_service_image


def _image_bytes(format_name: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (800, 800), color=(64, 82, 58)).save(output, format=format_name)
    return output.getvalue()


def test_service_image_is_normalized_to_webp_4_by_3() -> None:
    normalized = normalize_service_image(_image_bytes(), "image/png")

    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "WEBP"
        assert image.size == OUTPUT_SIZE
        assert image.mode == "RGB"


@pytest.mark.parametrize("content_type", ["image/gif", "application/octet-stream", None])
def test_service_image_rejects_unsupported_content_type(content_type: str | None) -> None:
    with pytest.raises(ValidationDomainError):
        normalize_service_image(_image_bytes(), content_type)


def test_service_image_rejects_invalid_or_oversized_content() -> None:
    with pytest.raises(ValidationDomainError):
        normalize_service_image(b"not an image", "image/jpeg")
    with pytest.raises(ValidationDomainError):
        normalize_service_image(b"x" * (MAX_UPLOAD_BYTES + 1), "image/jpeg")


def test_only_admin_role_can_manage_service_images() -> None:
    _require_admin_role({"uid": "admin", "role": "ADMIN"})

    with pytest.raises(HTTPException) as error:
        _require_admin_role({"uid": "staff", "role": "STAFF"})
    assert error.value.status_code == 403
