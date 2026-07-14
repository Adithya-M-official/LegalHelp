"""
pdf_input.py

Native PDF document support for LegalHelp.

Gemini's vision path only accepts image parts, and the rest of the
pipeline (image_quality.py, document_pages.py) is already built around
per-page images. Rather than branching the whole app around a second
"PDF mode", a PDF upload is rasterized here into one in-memory image
per page, at which point it re-enters the existing image pipeline
unchanged: same validation, same quality checks, same multi-page
request construction in ai_logic.py.

Uses PyMuPDF (`fitz`) for rasterization -- a small, pure-binary-wheel
library (no system dependency like Poppler) that can both render pages
to images and report page count without any extra tooling. This keeps
the addition lightweight and consistent with the "no heavy image
libraries" constraint already followed for image_quality.py.

Everything here operates on in-memory bytes only; nothing is written
to disk.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import List

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Rendered at this resolution (DPI-equivalent zoom) so text stays legible
# for Gemini and for the existing blur/resolution quality heuristics.
# 200 DPI is a common sweet spot for OCR/document-reading quality without
# producing excessively large images.
PDF_RENDER_ZOOM = 200 / 72  # fitz default page units are 72 DPI

# Output format for rasterized pages -- PNG keeps text edges crisp,
# which matters for the existing blur heuristic in image_quality.py.
PDF_PAGE_OUTPUT_FORMAT = "png"
PDF_PAGE_MIME_TYPE = "image/png"


class PdfProcessingError(ValueError):
    """Raised when a PDF cannot be opened or rasterized."""


def is_pdf(mime_type: str, filename: str) -> bool:
    """
    Determine whether an uploaded file should be treated as a PDF.

    Checks both the reported MIME type and the filename extension,
    since Streamlit's reported `.type` is not always populated
    consistently across browsers.
    """
    if mime_type and mime_type.lower() == "application/pdf":
        return True
    return filename.lower().endswith(".pdf")


def rasterize_pdf_to_pages(pdf_bytes: bytes, max_pages: int) -> List[bytes]:
    """
    Render each page of a PDF to an in-memory PNG image.

    Args:
        pdf_bytes: Raw bytes of the uploaded PDF.
        max_pages: Maximum number of pages to render. Extra pages are
            ignored (matches the existing MAX_PAGES cap already applied
            to multi-image uploads).

    Returns:
        list[bytes]: One PNG image (as bytes) per rendered page, in
        page order.

    Raises:
        PdfProcessingError: If the PDF cannot be opened, is encrypted
            without a usable password, or contains no pages.
    """
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to open uploaded PDF.")
        raise PdfProcessingError(
            "That file doesn't look like a valid PDF."
        ) from exc

    try:
        if document.is_encrypted:
            logger.warning("Uploaded PDF is encrypted and could not be read.")
            raise PdfProcessingError(
                "This PDF is password-protected. Please upload an "
                "unlocked version of the document."
            )

        page_count = document.page_count
        if page_count == 0:
            raise PdfProcessingError("This PDF doesn't contain any pages.")

        pages_to_render = min(page_count, max_pages)
        matrix = fitz.Matrix(PDF_RENDER_ZOOM, PDF_RENDER_ZOOM)

        rendered_pages: List[bytes] = []
        for page_index in range(pages_to_render):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix)
            rendered_pages.append(pixmap.tobytes(PDF_PAGE_OUTPUT_FORMAT))

        logger.info(
            "Rasterized %d of %d PDF page(s) for analysis.",
            len(rendered_pages),
            page_count,
        )
        return rendered_pages

    finally:
        document.close()


class RasterizedPdfPage(BytesIO):
    """
    Thin wrapper so a rasterized PDF page can be handed to
    document_pages.validate_pages() as if it were a regular Streamlit
    UploadedFile -- it only needs to expose `.getvalue()`, `.type`, and
    `.name`, which this provides on top of BytesIO's existing buffer.
    """

    def __init__(self, image_bytes: bytes, name: str, mime_type: str = PDF_PAGE_MIME_TYPE):
        super().__init__(image_bytes)
        self.name = name
        self.type = mime_type

    def getvalue(self) -> bytes:  # noqa: D102 - inherited behavior, explicit for clarity
        return super().getvalue()


def pdf_to_page_files(
    pdf_bytes: bytes, source_filename: str, max_pages: int
) -> List[RasterizedPdfPage]:
    """
    Convert an uploaded PDF into a list of page "files" compatible with
    the existing multi-image upload pipeline in document_pages.py.

    Args:
        pdf_bytes: Raw bytes of the uploaded PDF.
        source_filename: Original PDF filename, used to build readable
            per-page labels (e.g. "lease.pdf (page 1)").
        max_pages: Maximum number of pages to render.

    Returns:
        list[RasterizedPdfPage]: Page images ready to pass into
        document_pages.validate_pages() alongside or instead of
        directly-uploaded images.

    Raises:
        PdfProcessingError: If the PDF cannot be processed.
    """
    page_images = rasterize_pdf_to_pages(pdf_bytes, max_pages=max_pages)
    return [
        RasterizedPdfPage(
            image_bytes=image_bytes,
            name=f"{source_filename} (page {index + 1})",
        )
        for index, image_bytes in enumerate(page_images)
    ]
