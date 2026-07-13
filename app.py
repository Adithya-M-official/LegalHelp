"""
app.py

Streamlit UI for LegalHelp.

This module handles ONLY user interaction: file uploads, audio
recording, displaying results, and calling into ai_logic.py for all
AI processing. No Gemini calls, prompt engineering, or speech
generation happen here — see ai_logic.py for that.
"""

from io import BytesIO

import streamlit as st
from PIL import Image

from ai_logic import analyze_document
from config import ALLOWED_IMAGE_TYPES, APP_ICON, APP_NAME, DEFAULT_AUDIO_MIME_TYPE, DEFAULT_IMAGE_MIME_TYPE

# --------------------------------------------------------------------------
# Page setup
# --------------------------------------------------------------------------

st.set_page_config(page_title=APP_NAME, page_icon=APP_ICON)

st.title(f"{APP_ICON} {APP_NAME}")
st.write(
    "Upload a photo of a legal document, then ask a question by typing "
    "or recording your voice. LegalHelp will explain it in plain language."
)

# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

uploaded_image = st.file_uploader(
    "Upload a legal document (image)",
    type=ALLOWED_IMAGE_TYPES,
)

if uploaded_image is not None:
    # Preview so the user can confirm the right file was uploaded.
    st.image(uploaded_image, caption="Uploaded document", use_container_width=True)

typed_question = st.text_input("Type your question (optional)")

st.write("— or —")

recorded_audio = st.audio_input("Record your question instead")

analyze_clicked = st.button("Analyze", type="primary")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _has_valid_input() -> bool:
    """
    Check that submission requirements are met: an image is uploaded,
    and either a typed question or a recorded question is present.

    Returns:
        bool: True if the user has provided enough input to proceed.
    """
    if uploaded_image is None:
        return False
    return bool(typed_question) or recorded_audio is not None


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------

if analyze_clicked:
    if not _has_valid_input():
        st.error(
            "Please upload an image and either type a question or "
            "record one before analyzing."
        )
    else:
        with st.spinner("Reading your document and preparing an answer..."):
            try:
                # Keep the image entirely in memory via BytesIO/Pillow;
                # it is never written to disk.
                image_bytes = uploaded_image.getvalue()
                Image.open(BytesIO(image_bytes))  # validates it's a real image
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