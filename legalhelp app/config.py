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

# Network calls to Gemini are retried this many times (with a short backoff)
# before the app gives up and shows the user an error. This helps ride out
# brief network blips without any extra code in ai_logic.py's main logic.
MAX_API_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5

# --------------------------------------------------------------------------
# Text-to-speech settings
# --------------------------------------------------------------------------

# Fallback language used if gTTS doesn't recognize Gemini's detected
# language code (e.g. an unusual regional variant).
DEFAULT_TTS_LANGUAGE = "en"

# --------------------------------------------------------------------------
# Upload defaults and limits
# --------------------------------------------------------------------------

# Accepted image file types for the document uploader.
ALLOWED_IMAGE_TYPES = ["png", "jpg", "jpeg"]

# MIME type fallbacks used if Streamlit can't determine one from the
# uploaded file itself.
DEFAULT_IMAGE_MIME_TYPE = "image/png"
DEFAULT_AUDIO_MIME_TYPE = "audio/wav"

# Maximum accepted upload sizes, in megabytes. Gemini's API and most
# browsers already impose their own ceilings, but checking early gives
# users a clear, fast error instead of a slow failure downstream.
MAX_IMAGE_SIZE_MB = 10
MAX_AUDIO_SIZE_MB = 15

# Maximum characters accepted for a typed question, to avoid accidental
# huge pastes being sent to the model.
MAX_QUESTION_LENGTH = 1000
