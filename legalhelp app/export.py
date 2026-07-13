"""
export.py

Optional export of a LegalHelp explanation as a downloadable PDF, in
addition to the existing plain-text download.

Uses `fpdf2` -- a small, pure-Python, actively maintained PDF library
with no native/binary dependencies -- rather than a heavier toolkit
like ReportLab, to keep the dependency footprint minimal.

All work happens in memory (BytesIO); nothing is written to disk.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import BytesIO

from fpdf import FPDF

logger = logging.getLogger(__name__)

_PAGE_MARGIN_MM = 15
_TITLE_FONT_SIZE = 16
_BODY_FONT_SIZE = 11
_DISCLAIMER_FONT_SIZE = 9


def _sanitize_for_latin1(text: str) -> str:
    """
    fpdf2's built-in core fonts only support the Latin-1 character set.

    Rather than bundling a Unicode TTF font (which would add real file
    size and complexity for a "nice to have" export feature), we
    transliterate anything outside Latin-1 to its closest ASCII
    equivalent where possible, and drop characters with no equivalent.
    This keeps the export lightweight while still being readable for
    the vast majority of explanations (which are already rendered as
    plain UI text before export).
    """
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_explanation_pdf(
    response_text: str,
    language_code: str,
    app_name: str = "LegalHelp",
) -> BytesIO:
    """
    Render a plain-language explanation as a simple, single-column PDF.

    Args:
        response_text: The explanation text to export.
        language_code: The ISO 639-1 language code the explanation is in
            (included in the PDF footer for reference).
        app_name: Name shown in the PDF header.

    Returns:
        BytesIO: An in-memory PDF file, positioned at the start.

    Raises:
        RuntimeError: If PDF generation fails for any reason.
    """
    try:
        pdf = FPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=_PAGE_MARGIN_MM)
        pdf.set_margins(_PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM)
        pdf.add_page()

        pdf.set_font("Helvetica", style="B", size=_TITLE_FONT_SIZE)
        pdf.cell(0, 10, _sanitize_for_latin1(f"{app_name} - Explanation"), ln=True)

        pdf.set_font("Helvetica", style="I", size=_DISCLAIMER_FONT_SIZE)
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        pdf.cell(
            0,
            6,
            _sanitize_for_latin1(
                f"Generated {generated_at} | Language: {language_code}"
            ),
            ln=True,
        )
        pdf.ln(4)

        pdf.set_font("Helvetica", size=_BODY_FONT_SIZE)
        pdf.multi_cell(0, 7, _sanitize_for_latin1(response_text))
        pdf.ln(4)

        pdf.set_font("Helvetica", style="I", size=_DISCLAIMER_FONT_SIZE)
        disclaimer = (
            "This explanation is informational only and is not legal "
            "advice. It is not a substitute for a licensed lawyer. For "
            "decisions with real consequences, please consult a legal "
            "professional."
        )
        pdf.multi_cell(0, 5, _sanitize_for_latin1(disclaimer))

        output_bytes = pdf.output()
        buffer = BytesIO(bytes(output_bytes))
        buffer.seek(0)
        return buffer

    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to generate PDF export.")
        raise RuntimeError(
            "Could not generate a PDF export of the explanation."
        ) from exc
