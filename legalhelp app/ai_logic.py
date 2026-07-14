"""
ai_logic.py

All AI-related logic for LegalHelp.

This module is responsible for:
    - Initializing the Gemini client.
    - Building the multimodal request (one or more page images +
      text/audio).
    - Sending the request to Gemini (with retries) and parsing its
      structured response.
    - Converting the response text into speech using gTTS.

No Streamlit UI code lives in this file except reading `st.secrets` for
the API key. Everything else here is pure Python so it can be tested and
reused independently of the UI layer in app.py.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple

import streamlit as st
from google import genai
from google.genai import types
from google.genai.errors import APIError
from gtts import gTTS
from gtts.lang import tts_langs

from config import (
    DEFAULT_TTS_LANGUAGE,
    MAX_API_RETRIES,
    MODEL_NAME,
    RETRY_BACKOFF_SECONDS,
    TTS_LANGUAGE_ALIASES,
)
from prompts import SYSTEM_PROMPT

# Module-level logger. app.py configures logging handlers/format at
# startup; this module just emits records through the standard
# hierarchy so they show up in the terminal running `streamlit run app.py`
# without printing anything to the user-facing UI.
logger = logging.getLogger(__name__)

# Matches a fenced code block, optionally tagged with a language (e.g.
# ```json ... ```), capturing the inner content. Used as a more robust
# fallback than a plain strip() when Gemini wraps JSON in markdown despite
# being told not to.
_FENCE_PATTERN = re.compile(r"```(?:[a-zA-Z0-9]*\n)?(.*?)```", re.DOTALL)

# ISO 639-1 codes that gTTS actually supports, fetched once per process.
# Wrapped defensively since tts_langs() makes a network call the first
# time it's used in some gTTS versions and could fail offline.
try:
    _SUPPORTED_TTS_LANGUAGES = set(tts_langs().keys())
except Exception:  # noqa: BLE001
    logger.warning(
        "Could not load gTTS supported-language list; language validation "
        "will rely solely on runtime fallback."
    )
    _SUPPORTED_TTS_LANGUAGES = set()


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class LegalHelpResult:
    """Structured result returned to the UI layer after processing a request."""
    response_text: str
    language_code: str
    audio_bytes: BytesIO


# --------------------------------------------------------------------------
# Gemini client
# --------------------------------------------------------------------------

def _get_client() -> genai.Client:
    """
    Create a Gemini client using the API key stored in Streamlit secrets.

    Returns:
        genai.Client: An authenticated Gemini client.

    Raises:
        RuntimeError: If the API key is missing from st.secrets.
    """
    try:
        api_key = st.secrets.get("GEMINI_API_KEY")
    except Exception:  # noqa: BLE001 - st.secrets raises if no secrets file exists
        api_key = None

    if not api_key:
        logger.error("GEMINI_API_KEY is missing from Streamlit secrets.")
        raise RuntimeError(
            "GEMINI_API_KEY is missing from Streamlit secrets. "
            "Add it to .streamlit/secrets.toml before running the app."
        )
    return genai.Client(api_key=api_key)


# --------------------------------------------------------------------------
# Request construction
# --------------------------------------------------------------------------

def _build_contents(
    page_images: List[Tuple[bytes, str]],
    text_question: Optional[str],
    audio_bytes: Optional[bytes],
    audio_mime_type: Optional[str],
) -> list:
    """
    Build the multimodal `contents` list sent to Gemini.

    Exactly one of `text_question` or `audio_bytes` is included, matching
    the "one input method" rule enforced in the UI layer. One or more
    page images are always included, in order, as separate parts so
    Gemini can read a multi-page document as a single coherent whole.

    Args:
        page_images: Ordered list of (image_bytes, mime_type) tuples,
            one per document page. Must contain at least one entry.
        text_question: The user's typed question, if provided.
        audio_bytes: Raw bytes of the user's recorded question, if provided.
        audio_mime_type: MIME type of the recorded audio, if provided.

    Returns:
        list: A list of Content objects ready to send to Gemini.

    Raises:
        ValueError: If `page_images` is empty.
    """
    if not page_images:
        raise ValueError("At least one page image is required.")

    parts = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        for image_bytes, mime_type in page_images
    ]

    if text_question:
        parts.append(types.Part.from_text(text=text_question))
    elif audio_bytes:
        parts.append(
            types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime_type)
        )

    logger.info(
        "Built Gemini request with %d page image(s) and %s input.",
        len(page_images),
        "text" if text_question else "audio",
    )

    return [types.Content(role="user", parts=parts)]


def _parse_gemini_response(raw_text: str) -> tuple[str, str]:
    """
    Parse Gemini's JSON response into (response_text, language_code).

    Falls back gracefully if Gemini wraps the JSON in markdown fences,
    adds stray whitespace/preamble text, or uses smart quotes, despite
    being instructed not to.

    Args:
        raw_text: The raw text returned by Gemini.

    Returns:
        tuple[str, str]: (response_text, language_code)

    Raises:
        ValueError: If the response cannot be parsed as valid JSON, or is
            missing/blank required fields.
    """
    if not raw_text or not raw_text.strip():
        logger.error("Gemini returned an empty response body.")
        raise ValueError("Gemini returned an empty response.")

    cleaned = raw_text.strip()

    def _try_parse(candidate: str) -> Optional[dict]:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    data = _try_parse(cleaned)

    if data is None:
        # Fallback 1: pull content out of a ```...``` fenced block,
        # wherever it appears in the response.
        fence_match = _FENCE_PATTERN.search(cleaned)
        if fence_match:
            data = _try_parse(fence_match.group(1).strip())

    if data is None:
        # Fallback 2: the response may have stray preamble/postamble
        # text around the JSON object itself (e.g. "Here's the answer:
        # {...}"). Extract the outermost {...} span and try that.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = _try_parse(cleaned[start : end + 1])

    if data is None:
        logger.error(
            "Failed to parse Gemini response as JSON after all fallbacks. "
            "Raw response (truncated): %.200s",
            cleaned,
        )
        raise ValueError("Gemini did not return the expected JSON structure.")

    try:
        response_text = data["response"]
        language_code = data["language"]
    except (KeyError, TypeError) as exc:
        logger.error("Parsed JSON missing required fields: %s", data)
        raise ValueError(
            "Gemini did not return the expected JSON structure."
        ) from exc

    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("Gemini returned an empty explanation.")
    if not isinstance(language_code, str) or not language_code.strip():
        raise ValueError("Gemini did not return a usable language code.")

    return response_text.strip(), language_code.strip().lower()


# --------------------------------------------------------------------------
# Text-to-speech
# --------------------------------------------------------------------------

# Matches Markdown formatting marks that gTTS would otherwise read aloud
# literally (e.g. saying "asterisk asterisk" for bold text, or "dash" for
# list bullets). This is intentionally limited to punctuation/markup
# symbols -- not word characters -- so it's script-agnostic and safe to
# run on any language Gemini might reply in (Latin, CJK, Arabic, Devanagari,
# etc.) without stripping or mangling actual spoken letters/diacritics.
_MARKDOWN_MARKUP_PATTERN = re.compile(
    r"""
    \*\*|\*|__|_|          # bold / italic markers (**, *, __, _)
    ~~|                    # strikethrough
    `{1,3}|                # inline code / fences
    \#{1,6}\s*|            # heading markers
    ^\s*[-*+]\s+|          # leading list bullets
    ^\s*>\s+                # blockquote markers
    """,
    re.VERBOSE | re.MULTILINE,
)


def _clean_text_for_speech(text: str) -> str:
    """
    Strip Markdown/formatting characters from `text` before it is sent
    to gTTS, so the spoken audio only voices the actual words -- not
    literal symbol names like "asterisk" or "hash" for bullets/headings.

    This only targets ASCII markup punctuation (*, _, #, `, -, >, etc.),
    never letters, numbers, or diacritics, so text in any language or
    script (translated, transliterated, or otherwise) is left intact
    for gTTS to pronounce normally.

    Args:
        text: The raw explanation text (as shown in the UI, which may
            contain Markdown emphasis/headings/bullets).

    Returns:
        str: The same text with Markdown markup characters removed and
        whitespace normalized, safe to pass to gTTS.
    """
    cleaned = _MARKDOWN_MARKUP_PATTERN.sub("", text)

    # Collapse any run of blank lines/spaces left behind by removed
    # markup so gTTS doesn't insert long, unnatural pauses.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def _resolve_tts_language(language_code: str) -> str:
    """
    Map a Gemini-provided language code to one gTTS will accept.

    Checks, in order: an explicit alias table for known mismatches,
    then gTTS's own supported-language set, then falls back to the
    configured default. This runs *before* calling gTTS so the common
    cases are resolved without relying on catching a ValueError.

    Args:
        language_code: Lowercased ISO 639-1 (or similar) code from Gemini.

    Returns:
        str: A language code gTTS is expected to accept.
    """
    if language_code in TTS_LANGUAGE_ALIASES:
        return TTS_LANGUAGE_ALIASES[language_code]

    if _SUPPORTED_TTS_LANGUAGES and language_code not in _SUPPORTED_TTS_LANGUAGES:
        logger.info(
            "Language '%s' not in gTTS supported set; falling back to '%s'.",
            language_code,
            DEFAULT_TTS_LANGUAGE,
        )
        return DEFAULT_TTS_LANGUAGE

    return language_code


def _text_to_speech(text: str, language_code: str) -> BytesIO:
    """
    Convert text into spoken audio using gTTS, entirely in memory.

    Args:
        text: The text to convert to speech.
        language_code: The language to synthesize the speech in.

    Returns:
        BytesIO: An in-memory MP3 audio stream, positioned at the start.
    """
    resolved_language = _resolve_tts_language(language_code)
    speech_text = _clean_text_for_speech(text)

    try:
        tts = gTTS(text=speech_text, lang=resolved_language)
    except ValueError:
        # Belt-and-braces: even after alias/support-set resolution,
        # gTTS didn't recognize the code -- fall back to the default
        # language rather than failing the whole request.
        logger.warning(
            "gTTS rejected language '%s' (resolved from '%s'); falling back "
            "to '%s'.",
            resolved_language,
            language_code,
            DEFAULT_TTS_LANGUAGE,
        )
        tts = gTTS(text=speech_text, lang=DEFAULT_TTS_LANGUAGE)

    audio_buffer = BytesIO()
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return audio_buffer


# --------------------------------------------------------------------------
# Gemini call with retry
# --------------------------------------------------------------------------

def _call_gemini_with_retry(client: genai.Client, contents: list):
    """
    Call Gemini's generate_content, retrying on transient API errors.

    A brief fixed backoff is used between attempts. This is deliberately
    simple (no exponential backoff/jitter) to stay easy to read for a
    beginner-friendly project, while still smoothing over short-lived
    network or server hiccups.

    Args:
        client: An authenticated Gemini client.
        contents: The multimodal contents list to send.

    Returns:
        The Gemini response object.

    Raises:
        RuntimeError: If all attempts fail.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_API_RETRIES + 2):  # +1 initial +1 for range
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                ),
            )
            if attempt > 1:
                logger.info("Gemini call succeeded on attempt %d.", attempt)
            return response
        except APIError as exc:
            last_error = exc
            logger.warning(
                "Gemini API call failed (attempt %d/%d): %s",
                attempt,
                MAX_API_RETRIES + 1,
                exc,
            )
            if attempt <= MAX_API_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)

    logger.error("Gemini API call failed after all retry attempts.")
    raise RuntimeError(
        "Could not reach the Gemini API after several attempts. "
        "Please check your connection and try again."
    ) from last_error


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def analyze_document(
    page_images: List[Tuple[bytes, str]],
    text_question: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    audio_mime_type: Optional[str] = None,
) -> LegalHelpResult:
    """
    Send one or more legal document page images and a question (text or
    audio) to Gemini, then convert the answer into speech.

    Exactly one of `text_question` or `audio_bytes` should be provided;
    if both are given, text takes priority.

    Args:
        page_images: Ordered list of (image_bytes, mime_type) tuples for
            each page of the document. Must contain at least one entry.
        text_question: The user's typed question, if any.
        audio_bytes: The user's recorded question, if any.
        audio_mime_type: MIME type of the recorded audio, if any.

    Returns:
        LegalHelpResult: The explanation text, detected language code,
        and generated speech audio.

    Raises:
        RuntimeError: If the Gemini client cannot be created, or the API
            call fails after retries.
        ValueError: If `page_images` is empty or Gemini's response
            cannot be parsed.
    """
    client = _get_client()

    contents = _build_contents(
        page_images=page_images,
        text_question=text_question,
        audio_bytes=audio_bytes,
        audio_mime_type=audio_mime_type,
    )

    response = _call_gemini_with_retry(client, contents)

    response_text, language_code = _parse_gemini_response(response.text)
    audio_bytes_out = _text_to_speech(response_text, language_code)

    logger.info(
        "Analysis complete: %d page(s), detected language '%s', "
        "explanation length %d chars.",
        len(page_images),
        language_code,
        len(response_text),
    )

    return LegalHelpResult(
        response_text=response_text,
        language_code=language_code,
        audio_bytes=audio_bytes_out,
    )
