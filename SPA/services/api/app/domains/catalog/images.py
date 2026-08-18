from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import ValidationDomainError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
OUTPUT_SIZE = (1600, 1200)
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SOURCE_PIXELS = 20_000_000


def normalize_service_image(content: bytes, content_type: str | None) -> bytes:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationDomainError("Image must be JPEG, PNG, or WebP")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValidationDomainError("Image must be non-empty and no larger than 5 MB")
    try:
        with Image.open(BytesIO(content)) as source:
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise ValidationDomainError("Image dimensions are too large")
            source.verify()
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image = ImageOps.fit(image, OUTPUT_SIZE, method=Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValidationDomainError("Uploaded file is not a valid image") from error
    output = BytesIO()
    image.save(output, format="WEBP", quality=84, method=6)
    return output.getvalue()
