"""
ai_logic.py

All AI-related logic for LegalHelp.

This module is responsible for:
    - Initializing the Gemini client.
    - Building the multimodal request (image + text/audio).
    - Sending the request to Gemini and parsing its structured response.
    - Converting the response text into speech using gTTS.

No Streamlit UI code lives in this file. Everything here is pure Python
so it can be tested and reused independently of the UI layer in app.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import streamlit as st
from google import genai
from google.genai import types
from gtts import gTTS

from config import DEFAULT_TTS_LANGUAGE, MODEL_NAME
from prompts import SYSTEM_PROMPT


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
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from Streamlit secrets. "
            "Add it to .streamlit/secrets.toml before running the app."
        )
    return genai.Client(api_key=api_key)


# --------------------------------------------------------------------------
# Request construction
# --------------------------------------------------------------------------

def _build_contents(
    image_bytes: bytes,
    mime_type: str,
    text_question: Optional[str],
    audio_bytes: Optional[bytes],
    audio_mime_type: Optional[str],
) -> list:
    """
    Build the multimodal `contents` list sent to Gemini.

    Exactly one of `text_question` or `audio_bytes` is included, matching
    the "one input method" rule enforced in the UI layer.

    Args:
        image_bytes: Raw bytes of the uploaded legal document image.
        mime_type: MIME type of the image (e.g. "image/png").
        text_question: The user's typed question, if provided.
        audio_bytes: Raw bytes of the user's recorded question, if provided.
        audio_mime_type: MIME type of the recorded audio, if provided.

    Returns:
        list: A list of Content objects ready to send to Gemini.
    """
    parts = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
    ]

    if text_question:
        parts.append(types.Part.from_text(text=text_question))
    elif audio_bytes:
        parts.append(
            types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime_type)
        )

    return [types.Content(role="user", parts=parts)]


def _parse_gemini_response(raw_text: str) -> tuple[str, str]:
    """
    Parse Gemini's JSON response into (response_text, language_code).

    Falls back gracefully if Gemini wraps the JSON in markdown fences or
    adds stray whitespace, despite being instructed not to.

    Args:
        raw_text: The raw text returned by Gemini.

    Returns:
        tuple[str, str]: (response_text, language_code)

    Raises:
        ValueError: If the response cannot be parsed as valid JSON.
    """
    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        return data["response"], data["language"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError(
            "Gemini did not return the expected JSON structure."
        ) from exc


# --------------------------------------------------------------------------
# Text-to-speech
# --------------------------------------------------------------------------

def _text_to_speech(text: str, language_code: str) -> BytesIO:
    """
    Convert text into spoken audio using gTTS, entirely in memory.

    Args:
        text: The text to convert to speech.
        language_code: The language to synthesize the speech in.

    Returns:
        BytesIO: An in-memory MP3 audio stream, positioned at the start.
    """
    try:
        tts = gTTS(text=text, lang=language_code)
    except ValueError:
        # gTTS didn't recognize the code (e.g. an unusual regional
        # variant) — fall back to the default language rather than
        # failing outright.
        tts = gTTS(text=text, lang=DEFAULT_TTS_LANGUAGE)

    audio_buffer = BytesIO()
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return audio_buffer


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def analyze_document(
    image_bytes: bytes,
    mime_type: str,
    text_question: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    audio_mime_type: Optional[str] = None,
) -> LegalHelpResult:
    """
    Send a legal document image and a question (text or audio) to Gemini,
    then convert the answer into speech.

    Exactly one of `text_question` or `audio_bytes` should be provided;
    if both are given, text takes priority.

    Args:
        image_bytes: Raw bytes of the uploaded legal document image.
        mime_type: MIME type of the image.
        text_question: The user's typed question, if any.
        audio_bytes: The user's recorded question, if any.
        audio_mime_type: MIME type of the recorded audio, if any.

    Returns:
        LegalHelpResult: The explanation text, detected language code,
        and generated speech audio.

    Raises:
        RuntimeError: If the Gemini client cannot be created.
        ValueError: If Gemini's response cannot be parsed.
    """
    client = _get_client()

    contents = _build_contents(
        image_bytes=image_bytes,
        mime_type=mime_type,
        text_question=text_question,
        audio_bytes=audio_bytes,
        audio_mime_type=audio_mime_type,
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )

    response_text, language_code = _parse_gemini_response(response.text)
    audio_bytes_out = _text_to_speech(response_text, language_code)

    return LegalHelpResult(
        response_text=response_text,
        language_code=language_code,
        audio_bytes=audio_bytes_out,
    )