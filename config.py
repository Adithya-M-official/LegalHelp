"""
config.py

Configuration constants for LegalHelp.

Centralizing these values here means you can tweak app behavior
(e.g. swap models, rename the app, change size limits) without
touching any logic in ai_logic.py or app.py.
"""

# --------------------------------------------------------------------------
# App metadata
# --------------------------------------------------------------------------

APP_NAME = "LegalHelp"
APP_ICON = "⚖️"

# --------------------------------------------------------------------------
# Gemini settings
# --------------------------------------------------------------------------

# Change this single variable to swap Gemini models. Update it to whatever
# the current stable Gemini model is at the time you run this project.
MODEL_NAME = "gemini-2.5-flash"

# --------------------------------------------------------------------------
# Text-to-speech settings
# --------------------------------------------------------------------------

# Fallback language used if gTTS doesn't recognize Gemini's detected
# language code (e.g. an unusual regional variant).
DEFAULT_TTS_LANGUAGE = "en"

# --------------------------------------------------------------------------
# Upload defaults
# --------------------------------------------------------------------------

# Accepted image file types for the document uploader.
ALLOWED_IMAGE_TYPES = ["png", "jpg", "jpeg"]

# MIME type fallbacks used if Streamlit can't determine one from the
# uploaded file itself.
DEFAULT_IMAGE_MIME_TYPE = "image/png"
DEFAULT_AUDIO_MIME_TYPE = "audio/wav"