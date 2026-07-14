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

# gTTS accepts specific language/region codes and will raise ValueError
# for codes it doesn't recognize (e.g. some regional or less-common ISO
# 639-1 codes Gemini might return). This maps a few common cases Gemini
# is likely to emit to a gTTS-supported equivalent, checked before
# falling back to DEFAULT_TTS_LANGUAGE. Not exhaustive by design -- the
# runtime fallback in ai_logic.py already handles anything not listed
# here, so this table only needs to cover the common, known mismatches.
TTS_LANGUAGE_ALIASES = {
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
    "zh": "zh-CN",
    "iw": "he",  # old ISO code for Hebrew, still sometimes emitted
    "jv": "jw",  # Javanese, gTTS uses the older "jw" code
}

# --------------------------------------------------------------------------
# Upload defaults and limits
# --------------------------------------------------------------------------

# Accepted image file types for the document uploader. PDFs are also
# accepted (see ALLOWED_DOCUMENT_TYPES) and are rasterized to page
# images before entering this same pipeline -- see pdf_input.py.
ALLOWED_IMAGE_TYPES = ["png", "jpg", "jpeg"]

# Full set of file types accepted by the uploader widget, including PDF.
ALLOWED_DOCUMENT_TYPES = ALLOWED_IMAGE_TYPES + ["pdf"]

# MIME type fallbacks used if Streamlit can't determine one from the
# uploaded file itself.
DEFAULT_IMAGE_MIME_TYPE = "image/png"
DEFAULT_AUDIO_MIME_TYPE = "audio/wav"
PDF_MIME_TYPE = "application/pdf"

# Maximum accepted upload sizes, in megabytes. Gemini's API and most
# browsers already impose their own ceilings, but checking early gives
# users a clear, fast error instead of a slow failure downstream.
MAX_IMAGE_SIZE_MB = 10
MAX_AUDIO_SIZE_MB = 15

# Maximum accepted PDF size, in megabytes, checked before rasterization.
MAX_PDF_SIZE_MB = 20

# Maximum characters accepted for a typed question, to avoid accidental
# huge pastes being sent to the model.
MAX_QUESTION_LENGTH = 1000

# --------------------------------------------------------------------------
# Multi-page document settings
# --------------------------------------------------------------------------

# Maximum number of page images accepted in a single analysis request.
# See document_pages.py for how pages are validated and sent to Gemini.
MAX_PAGES = 10

# --------------------------------------------------------------------------
# Image quality check settings
# --------------------------------------------------------------------------

# When True, images that trigger quality warnings (blur, glare, low
# resolution, too dark) are still sent to Gemini -- the user just sees
# a warning first and can choose to proceed or re-upload. Set to False
# to hard-block low-quality images instead.
ALLOW_ANALYSIS_WITH_QUALITY_WARNINGS = True

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

# Standard library logging level for the whole app. Streamlit doesn't
# configure logging by default, so app.py sets this up at startup.
# Set via the LOG_LEVEL environment variable in production if a
# different verbosity is needed (e.g. "DEBUG" while diagnosing an issue).
LOG_LEVEL = "INFO"
