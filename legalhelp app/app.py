"""
app.py

Streamlit UI for LegalHelp.

This module handles ONLY user interaction: file uploads, audio
recording, input validation, displaying results, and calling into
ai_logic.py for all AI processing. No Gemini calls, prompt engineering,
or speech generation happen here — see ai_logic.py for that.
"""

from io import BytesIO
from typing import Optional

import streamlit as st
from PIL import Image, UnidentifiedImageError

from ai_logic import analyze_document
from config import (
    ALLOWED_IMAGE_TYPES,
    APP_ICON,
    APP_NAME,
    DEFAULT_AUDIO_MIME_TYPE,
    DEFAULT_IMAGE_MIME_TYPE,
    MAX_AUDIO_SIZE_MB,
    MAX_IMAGE_SIZE_MB,
    MAX_QUESTION_LENGTH,
)

# --------------------------------------------------------------------------
# Page setup
# --------------------------------------------------------------------------

st.set_page_config(page_title=APP_NAME, page_icon=APP_ICON)

st.title(f"{APP_ICON} {APP_NAME}")
st.write(
    "Upload a photo of a legal document, then ask a question by typing "
    "or recording your voice. LegalHelp will explain it in plain language."
)

st.info(
    "⚠️ **Not legal advice.** LegalHelp explains documents in plain "
    "language to help you understand them. It is not a lawyer and "
    "cannot replace one. For decisions with real consequences, please "
    "consult a licensed legal professional.",
    icon="⚠️",
)

# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

uploaded_image = st.file_uploader(
    "Upload a legal document (image)",
    type=ALLOWED_IMAGE_TYPES,
    help=f"Accepted formats: {', '.join(ALLOWED_IMAGE_TYPES).upper()}. "
    f"Max size: {MAX_IMAGE_SIZE_MB} MB.",
)

if uploaded_image is not None:
    # Preview so the user can confirm the right file was uploaded.
    # A descriptive caption doubles as alt text for screen readers.
    st.image(
        uploaded_image,
        caption="Preview of the uploaded legal document",
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

def _file_size_mb(file_bytes: bytes) -> float:
    """Return the size of `file_bytes` in megabytes."""
    return len(file_bytes) / (1024 * 1024)


def _validate_input() -> Optional[str]:
    """
    Check that submission requirements are met.

    Returns:
        Optional[str]: A user-facing error message if validation fails,
        or None if the input is valid and ready to send to Gemini.
    """
    if uploaded_image is None:
        return "Please upload an image of your legal document."

    if not typed_question and recorded_audio is None:
        return "Please type a question or record one before analyzing."

    if _file_size_mb(uploaded_image.getvalue()) > MAX_IMAGE_SIZE_MB:
        return (
            f"That image is larger than the {MAX_IMAGE_SIZE_MB} MB limit. "
            "Please upload a smaller file."
        )

    if recorded_audio is not None and not typed_question:
        if _file_size_mb(recorded_audio.getvalue()) > MAX_AUDIO_SIZE_MB:
            return (
                f"That recording is larger than the {MAX_AUDIO_SIZE_MB} MB "
                "limit. Please record a shorter question."
            )

    return None


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------

if analyze_clicked:
    validation_error = _validate_input()

    if validation_error:
        st.error(validation_error)
    else:
        with st.spinner("Reading your document and preparing an answer..."):
            try:
                # Keep the image entirely in memory via BytesIO/Pillow;
                # it is never written to disk.
                image_bytes = uploaded_image.getvalue()
                Image.open(BytesIO(image_bytes)).verify()  # validates it's a real image
                image_mime = uploaded_image.type or DEFAULT_IMAGE_MIME_TYPE

                # Exactly one input method is used: text takes priority
                # over audio if both are somehow present.
                if typed_question:
                    result = analyze_document(
                        image_bytes=image_bytes,
                        mime_type=image_mime,
                        text_question=typed_question,
                    )
                else:
                    result = analyze_document(
                        image_bytes=image_bytes,
                        mime_type=image_mime,
                        audio_bytes=recorded_audio.getvalue(),
                        audio_mime_type=recorded_audio.type or DEFAULT_AUDIO_MIME_TYPE,
                    )

                st.success("Here's what LegalHelp found:")
                st.write(result.response_text)
                st.audio(result.audio_bytes, format="audio/mp3")

                # Let users save the explanation for their own records.
                st.download_button(
                    label="Download explanation as text",
                    data=result.response_text,
                    file_name="legalhelp_explanation.txt",
                    mime="text/plain",
                )

            except UnidentifiedImageError:
                st.error(
                    "That file doesn't look like a valid image. Please "
                    "upload a clear PNG or JPG photo of your document."
                )
            except RuntimeError as config_error:
                st.error(f"Configuration error: {config_error}")
            except ValueError as parse_error:
                st.error(
                    "Sorry, LegalHelp had trouble understanding the "
                    f"document. Please try again. ({parse_error})"
                )
            except Exception as unexpected_error:  # noqa: BLE001
                st.error(
                    "Something unexpected went wrong while analyzing "
                    f"your document: {unexpected_error}"
                )
