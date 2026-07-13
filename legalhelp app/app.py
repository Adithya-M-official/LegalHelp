"""
app.py

Streamlit UI for LegalHelp.

This module handles ONLY user interaction: file uploads, audio
recording, input validation, displaying results, and calling into
ai_logic.py for all AI processing. No Gemini calls, prompt engineering,
or speech generation happen here -- see ai_logic.py for that.
"""

import logging
from typing import List, Optional

import streamlit as st
from PIL import UnidentifiedImageError

from ai_logic import analyze_document
from config import (
    ALLOWED_IMAGE_TYPES,
    ALLOW_ANALYSIS_WITH_QUALITY_WARNINGS,
    APP_ICON,
    APP_NAME,
    DEFAULT_AUDIO_MIME_TYPE,
    DEFAULT_IMAGE_MIME_TYPE,
    LOG_LEVEL,
    MAX_AUDIO_SIZE_MB,
    MAX_IMAGE_SIZE_MB,
    MAX_PAGES,
    MAX_QUESTION_LENGTH,
)
from document_pages import validate_pages
from export import build_explanation_pdf

# --------------------------------------------------------------------------
# Logging setup
# --------------------------------------------------------------------------
# Streamlit doesn't configure logging by default. Setting this up once,
# here at the UI entry point, gives every module's logger.* calls a
# consistent format and destination (stderr, visible in the terminal
# running `streamlit run app.py`) without printing anything into the
# user-facing UI itself.

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Page setup
# --------------------------------------------------------------------------

st.set_page_config(page_title=APP_NAME, page_icon=APP_ICON)

st.title(f"{APP_ICON} {APP_NAME}")
st.write(
    "Upload one or more photos of a legal document, then ask a question "
    "by typing or recording your voice. LegalHelp will explain it in "
    "plain language."
)

st.info(
    "⚠️ **Not legal advice.** LegalHelp explains documents in plain "
    "language to help you understand them. It is not a lawyer, and its "
    "explanations are not checked against actual legal statutes or case "
    "law. It cannot replace a licensed legal professional. For decisions "
    "with real consequences, please consult one.",
    icon="⚠️",
)

# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

uploaded_images = st.file_uploader(
    "Upload a legal document (image)",
    type=ALLOWED_IMAGE_TYPES,
    accept_multiple_files=True,
    help=(
        f"Accepted formats: {', '.join(ALLOWED_IMAGE_TYPES).upper()}. "
        f"Max size per file: {MAX_IMAGE_SIZE_MB} MB. "
        f"Up to {MAX_PAGES} pages — upload multiple images if your "
        "document has more than one page, in reading order."
    ),
)

if uploaded_images:
    if len(uploaded_images) > MAX_PAGES:
        st.warning(
            f"You uploaded {len(uploaded_images)} images, but only the "
            f"first {MAX_PAGES} will be analyzed. Consider splitting "
            "very long documents into separate requests."
        )
    # Preview so the user can confirm the right files were uploaded, in
    # the order they'll be sent. Descriptive captions double as alt text
    # for screen readers.
    preview_images = uploaded_images[:MAX_PAGES]
    columns = st.columns(min(len(preview_images), 4)) if preview_images else []
    for position, (column, image_file) in enumerate(
        zip(columns * (len(preview_images) // max(len(columns), 1) + 1), preview_images)
    ):
        with column:
            st.image(
                image_file,
                caption=f"Page {position + 1}: {image_file.name}",
                use_container_width=True,
            )

typed_question = st.text_input(
    "Type your question (optional)",
    max_chars=MAX_QUESTION_LENGTH,
)

st.write("— or —")

recorded_audio = st.audio_input("Record your question instead")

analyze_clicked = st.button("Analyze", type="primary")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _validate_basic_input() -> Optional[str]:
    """
    Check that the basic submission requirements are met, before any
    per-page validation or quality analysis runs.

    Returns:
        Optional[str]: A user-facing error message if validation fails,
        or None if the input is ready for per-page validation.
    """
    if not uploaded_images:
        return "Please upload at least one image of your legal document."

    if not typed_question and recorded_audio is None:
        return "Please type a question or record one before analyzing."

    if recorded_audio is not None and not typed_question:
        audio_size_mb = len(recorded_audio.getvalue()) / (1024 * 1024)
        if audio_size_mb > MAX_AUDIO_SIZE_MB:
            return (
                f"That recording is larger than the {MAX_AUDIO_SIZE_MB} MB "
                "limit. Please record a shorter question."
            )

    return None


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------

if analyze_clicked:
    basic_error = _validate_basic_input()

    if basic_error:
        st.error(basic_error)
    else:
        pages_to_check = uploaded_images[:MAX_PAGES]
        page_results = validate_pages(
            uploaded_files=pages_to_check,
            max_size_mb=MAX_IMAGE_SIZE_MB,
            default_mime_type=DEFAULT_IMAGE_MIME_TYPE,
        )

        page_errors = [result.error for result in page_results if not result.is_valid]

        if page_errors:
            for error_message in page_errors:
                st.error(error_message)
        else:
            # Surface any image-quality warnings up front. Depending on
            # config, this either blocks analysis or just informs the
            # user before proceeding.
            all_quality_warnings: List[str] = []
            for result in page_results:
                for warning in result.quality_report.warnings:
                    all_quality_warnings.append(f"**{result.filename}:** {warning}")

            if all_quality_warnings:
                warning_block = "\n\n".join(f"- {w}" for w in all_quality_warnings)
                if ALLOW_ANALYSIS_WITH_QUALITY_WARNINGS:
                    st.warning(
                        "We noticed some possible image quality issues. "
                        "LegalHelp will still try to analyze the document, "
                        "but accuracy may be affected:\n\n" + warning_block
                    )
                else:
                    st.error(
                        "The uploaded image(s) have quality issues that may "
                        "prevent an accurate reading. Please re-upload "
                        "clearer photos:\n\n" + warning_block
                    )
                    page_results = []  # block downstream processing

            if page_results and not (
                all_quality_warnings and not ALLOW_ANALYSIS_WITH_QUALITY_WARNINGS
            ):
                with st.spinner(
                    "Reading your document and preparing an answer..."
                ):
                    try:
                        page_images = [
                            (result.image_bytes, result.mime_type)
                            for result in page_results
                        ]

                        # Exactly one input method is used: text takes
                        # priority over audio if both are somehow present.
                        if typed_question:
                            result = analyze_document(
                                page_images=page_images,
                                text_question=typed_question,
                            )
                        else:
                            result = analyze_document(
                                page_images=page_images,
                                audio_bytes=recorded_audio.getvalue(),
                                audio_mime_type=(
                                    recorded_audio.type or DEFAULT_AUDIO_MIME_TYPE
                                ),
                            )

                        st.success("Here's what LegalHelp found:")
                        st.write(result.response_text)
                        st.audio(result.audio_bytes, format="audio/mp3")

                        # Let users save the explanation for their own
                        # records, either as plain text or as a PDF.
                        download_col1, download_col2 = st.columns(2)

                        with download_col1:
                            st.download_button(
                                label="Download as text",
                                data=result.response_text,
                                file_name="legalhelp_explanation.txt",
                                mime="text/plain",
                            )

                        with download_col2:
                            try:
                                pdf_buffer = build_explanation_pdf(
                                    response_text=result.response_text,
                                    language_code=result.language_code,
                                    app_name=APP_NAME,
                                )
                                st.download_button(
                                    label="Download as PDF",
                                    data=pdf_buffer,
                                    file_name="legalhelp_explanation.pdf",
                                    mime="application/pdf",
                                )
                            except RuntimeError as pdf_error:
                                logger.warning(
                                    "PDF export unavailable: %s", pdf_error
                                )
                                st.caption(
                                    "PDF export isn't available right now, "
                                    "but you can still download the text "
                                    "version above."
                                )

                    except UnidentifiedImageError:
                        logger.exception("Uploaded file failed image validation.")
                        st.error(
                            "That file doesn't look like a valid image. "
                            "Please upload a clear PNG or JPG photo of "
                            "your document."
                        )
                    except RuntimeError as config_error:
                        logger.exception("Configuration or connectivity error.")
                        st.error(f"Configuration error: {config_error}")
                    except ValueError as parse_error:
                        logger.exception("Failed to parse Gemini response.")
                        st.error(
                            "Sorry, LegalHelp had trouble understanding "
                            f"the document. Please try again. ({parse_error})"
                        )
                    except Exception as unexpected_error:  # noqa: BLE001
                        logger.exception("Unexpected error during analysis.")
                        st.error(
                            "Something unexpected went wrong while "
                            f"analyzing your document: {unexpected_error}"
                        )
