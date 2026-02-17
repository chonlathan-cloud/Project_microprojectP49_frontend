from google.cloud import documentai_v1 as documentai

from app.core.config import settings

# --- Document AI Client ---
# Reference: LDD Section 3.2, HLD Section 2.4

client = documentai.DocumentProcessorServiceClient(
    client_options={"api_endpoint": f"{settings.DOCAI_LOCATION}-documentai.googleapis.com"}
)

# Full resource name for the Invoice Processor
PROCESSOR_NAME = client.processor_path(
    settings.GCP_PROJECT_ID,
    settings.DOCAI_LOCATION,
    settings.DOCAI_PROCESSOR_ID,
)


def process_invoice(file_content: bytes, mime_type: str) -> dict:
    """
    Send a receipt/invoice image to Google Document AI for OCR processing.

    Reference: LDD Section 3.2, TDD Section 2.1 (Upload Receipt flow)

    The processor used is the pre-trained "Invoice Processor" which
    handles Thai-language receipts out of the box (HLD Section 2.4).

    Args:
        file_content: Raw bytes of the uploaded image/PDF.
        mime_type: MIME type string (e.g., "image/jpeg", "application/pdf").

    Returns:
        dict: Parsed document data containing:
            - "text": Full extracted text
            - "entities": List of extracted fields (date, total, supplier, etc.)
            - "pages": Page-level layout information
    """
    raw_document = documentai.RawDocument(
        content=file_content,
        mime_type=mime_type,
    )

    request = documentai.ProcessRequest(
        name=PROCESSOR_NAME,
        raw_document=raw_document,
    )

    result = client.process_document(request=request)
    document = result.document

    # --- Extract structured data from the Document AI response ---

    # 1. Full text
    full_text = document.text

    # 2. Entities (header fields: merchant, date, total, etc.)
    entities = []
    for entity in document.entities:
        entity_data = {
            "type": entity.type_,
            "mention_text": entity.mention_text,
            "confidence": entity.confidence,
        }
        # Include normalized value if available (e.g., date, money)
        if entity.normalized_value:
            entity_data["normalized_value"] = entity.normalized_value.text
        entities.append(entity_data)

    # 3. Page-level info (optional, for bounding box overlay)
    pages = []
    for page in document.pages:
        page_data = {
            "page_number": page.page_number,
            "width": page.dimension.width if page.dimension else None,
            "height": page.dimension.height if page.dimension else None,
        }
        pages.append(page_data)

    return {
        "text": full_text,
        "entities": entities,
        "pages": pages,
    }
