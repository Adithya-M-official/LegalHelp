"""
document_pages.py

Support for multi-page / multi-image legal document uploads.

Gemini's multimodal API can accept multiple image parts in a single
request, so "multi-page support" here means: validate each uploaded
page individually (size, format, quality), then hand the full ordered
list of image bytes to ai_logic.py to include as separate parts in one
request. No merging/stitching of images is performed -- Gemini reads
each page as its own image, which preserves quality and avoids extra
image-processing complexity.

Everything here operates on in-memory bytes only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional

from PIL import Image, UnidentifiedImageError

from image_quality import ImageQualityReport, assess_image_quality
from pdf_input import PdfProcessingError, is_pdf, pdf_to_page_files

logger = logging.getLogger(__name__)

# Hard ceiling on the number of pages accepted per request. Keeps
# request size and Gemini latency predictable, and matches the kind
# of document this app targets (leases, contracts, notices) rather
# than entire books.
MAX_PAGES = 10


@dataclass
class PageValidationResult:
    """Per-page validation/quality outcome."""

    index: int
    filename: str
    image_bytes: bytes
    mime_type: str
    quality_report: ImageQualityReport
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None


def _expand_pdfs(uploaded_files: List, max_pages: int) -> List:
    """
    Replace any PDF entries in `uploaded_files` with their rasterized
    page images, leaving image entries untouched.

    This is the only integration point PDF support needs in this
    module: once expanded, every entry in the returned list exposes
    the same `.getvalue()` / `.type` / `.name` interface as a regular
    Streamlit image upload, so the existing per-page validation loop
    below requires no further changes.

    Args:
        uploaded_files: Mixed list of Streamlit UploadedFile objects
            (images and/or PDFs).
        max_pages: Page cap passed through to PDF rasterization.

    Returns:
        list: Flattened list of image-like file objects.
    """
    expanded: List = []

    for uploaded_file in uploaded_files:
        filename = getattr(uploaded_file, "name", "") or ""
        mime_type = getattr(uploaded_file, "type", "") or ""

        if is_pdf(mime_type, filename):
            try:
                pdf_bytes = uploaded_file.getvalue()
                expanded.extend(
                    pdf_to_page_files(
                        pdf_bytes=pdf_bytes,
                        source_filename=filename or "document.pdf",
                        max_pages=max_pages,
                    )
                )
            except PdfProcessingError as exc:
                logger.warning("PDF '%s' could not be processed: %s", filename, exc)
                # Represent the failure as a single failed "page" so it
                # surfaces through the normal per-page error path below.
                expanded.append(_FailedPdfUpload(filename, str(exc)))
        else:
            expanded.append(uploaded_file)

    return expanded


class _FailedPdfUpload(BytesIO):
    """
    Stand-in for a PDF that failed to rasterize, carrying the error
    message through to the normal per-page validation loop so it's
    reported to the user the same way any other bad upload would be.
    """

    def __init__(self, filename: str, error_message: str):
        super().__init__(b"")
        self.name = filename or "document.pdf"
        self.type = "application/pdf"
        self.error_message = error_message


def validate_pages(
    uploaded_files: List,
    max_size_mb: float,
    default_mime_type: str,
    max_pages: int = MAX_PAGES,
) -> List[PageValidationResult]:
    """
    Validate and quality-check a list of uploaded page images and/or
    PDFs.

    PDF uploads are transparently expanded into one rasterized page
    image per PDF page (see pdf_input.py) before validation, so callers
    can pass a mixed list of images and PDFs without special handling.

    Args:
        uploaded_files: A list of Streamlit UploadedFile objects (or any
            object exposing `.getvalue()`, `.type`, and `.name`) -- may
            include image files, PDF files, or both.
        max_size_mb: Maximum accepted size per image page, in megabytes.
            PDFs are checked against MAX_PDF_SIZE_MB before this applies.
        default_mime_type: MIME type to use if one can't be determined.
        max_pages: Maximum number of pages to extract from any PDF.

    Returns:
        list[PageValidationResult]: One result per resulting page, in
        order. Files that fail validation have `.error` set and should
        be surfaced to the user rather than sent on to Gemini.
    """
    results: List[PageValidationResult] = []

    expanded_files = _expand_pdfs(uploaded_files, max_pages=max_pages)

    for index, uploaded_file in enumerate(expanded_files):
        filename = getattr(uploaded_file, "name", f"page_{index + 1}")

        if isinstance(uploaded_file, _FailedPdfUpload):
            results.append(
                PageValidationResult(
                    index=index,
                    filename=filename,
                    image_bytes=b"",
                    mime_type=default_mime_type,
                    quality_report=ImageQualityReport(),
                    error=uploaded_file.error_message,
                )
            )
            continue

        try:
            raw_bytes = uploaded_file.getvalue()
            size_mb = len(raw_bytes) / (1024 * 1024)

            if size_mb > max_size_mb:
                results.append(
                    PageValidationResult(
                        index=index,
                        filename=filename,
                        image_bytes=raw_bytes,
                        mime_type=default_mime_type,
                        quality_report=ImageQualityReport(),
                        error=(
                            f"'{filename}' is larger than the {max_size_mb} MB "
                            "limit."
                        ),
                    )
                )
                continue

            image = Image.open(BytesIO(raw_bytes))
            image.verify()
            # verify() invalidates the file handle for further use, so
            # re-open for the quality checks below.
            image = Image.open(BytesIO(raw_bytes))

            quality_report = assess_image_quality(image)
            mime_type = getattr(uploaded_file, "type", None) or default_mime_type

            results.append(
                PageValidationResult(
                    index=index,
                    filename=filename,
                    image_bytes=raw_bytes,
                    mime_type=mime_type,
                    quality_report=quality_report,
                )
            )

        except UnidentifiedImageError:
            results.append(
                PageValidationResult(
                    index=index,
                    filename=filename,
                    image_bytes=b"",
                    mime_type=default_mime_type,
                    quality_report=ImageQualityReport(),
                    error=(
                        f"'{filename}' doesn't look like a valid image file."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error validating page '%s'", filename)
            results.append(
                PageValidationResult(
                    index=index,
                    filename=filename,
                    image_bytes=b"",
                    mime_type=default_mime_type,
                    quality_report=ImageQualityReport(),
                    error=f"Could not process '{filename}': {exc}",
                )
            )

    return results
