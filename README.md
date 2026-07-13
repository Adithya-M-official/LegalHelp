# ⚖️ LegalHelp

## Overview

LegalHelp is a Streamlit application that helps everyday people understand legal documents in plain language. A user uploads a photo of a legal document and asks a question — either by typing or recording their voice — and LegalHelp uses Google's Gemini model to read the document, answer the question in simple terms, and speak the answer back in the same language it was asked in.

## Problem Statement

Legal documents are often dense, jargon-heavy, and inaccessible to people without legal training. This creates a real barrier for individuals with limited literacy, limited time, or limited familiarity with legal language — who may end up signing, ignoring, or misunderstanding documents that materially affect their lives. LegalHelp aims to lower that barrier by turning a photo and a spoken or typed question into a clear, plain-language explanation.

## Features

- 📷 **Image-based document input** — upload a photo of any legal document (PNG/JPG/JPEG).
- ⌨️🎙️ **Two ways to ask** — type a question or record it as audio.
- 🌍 **Automatic language detection** — Gemini detects the language of the question and responds in that same language.
- 🗣️ **Spoken responses** — answers are converted to speech (via gTTS) so users can listen as well as read.
- 🧠 **Plain-language explanations** — the system prompt instructs Gemini to explain documents simply, preserve legal meaning, avoid unnecessary jargon, and flag uncertainty, without giving definitive legal advice.
- 🔒 **In-memory processing** — uploaded images and audio are processed entirely in memory and are never written to disk.
- ✅ **Upfront input validation** — file size limits, image-format checks, and question-length limits catch problems before an API call is made.
- 🔁 **Automatic retry on transient failures** — brief Gemini API/network hiccups are retried automatically instead of failing the whole request.
- ⬇️ **Downloadable explanations** — users can save the plain-language explanation as a text file for their records.
- ♿ **Accessibility touches** — descriptive image captions (serving as alt text), clear labeled inputs, and a persistent on-screen disclaimer.

## Architecture Overview

LegalHelp follows a simple, four-file separation of concerns:

1. **UI layer (`app.py`)** collects the image and question from the user via Streamlit.
2. **Logic layer (`ai_logic.py`)** builds a multimodal request (image + text or audio), sends it to the Gemini API along with the system prompt, and parses the structured JSON response.
3. **Response handling** — the parsed explanation text is converted to speech with gTTS.
4. **Output** — both the text explanation and the generated audio are displayed back in the Streamlit UI.

Configuration (model name, defaults) and prompt text are isolated into their own modules so behavior can be tuned without touching UI or logic code.

```
User uploads image + asks question (text or audio)
            │
            ▼
        app.py (Streamlit UI)
            │
            ▼
     ai_logic.py → Gemini API (multimodal, JSON-structured response)
            │
            ▼
   Parsed response → gTTS (text-to-speech)
            │
            ▼
   Displayed back in app.py (text + audio)
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python |
| UI framework | [Streamlit](https://streamlit.io/) |
| AI model | Google Gemini (`google-genai` SDK) |
| Text-to-speech | [gTTS](https://pypi.org/project/gTTS/) |
| Image handling | [Pillow](https://python-pillow.org/) |

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd legalhelp
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Add your Gemini API key**

   Copy the example secrets file and fill in your key:
   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```
   Then edit `.streamlit/secrets.toml`:
   ```toml
   GEMINI_API_KEY = "your-api-key-here"
   ```
   This file is git-ignored so your key is never committed.

## Usage

Run the app with Streamlit:

```bash
streamlit run app.py
```

Then, in the browser window that opens:

1. Upload a photo of a legal document (PNG/JPG/JPEG).
2. Ask a question — either type it into the text box, or record it using the audio input (if both are provided, the typed question takes priority).
3. Click **Analyze**.
4. Read the plain-language explanation and/or listen to the generated audio response.

## Project Structure

```
├── app.py                          # Streamlit UI — file upload, audio input, validation, result display
├── ai_logic.py                     # Gemini client, retries, request construction, response parsing, text-to-speech
├── config.py                       # Configuration constants (model, limits, retries, app metadata)
├── prompts.py                      # Gemini system prompt
├── requirements.txt                # Pinned dependencies
├── .streamlit/secrets.toml.example # Template for the required API key file
├── .gitignore
└── README.md
```

## Responsible AI Considerations

- **No legal advice**: the system prompt explicitly instructs the model to explain document content without presenting itself as a lawyer or offering a definitive legal recommendation.
- **Uncertainty disclosure**: the model is instructed to clearly state when it is unsure about part of a document or how it applies to the user's situation.
- **Meaning preservation**: the prompt directs the model to avoid oversimplifying to the point of inaccuracy, and to briefly explain necessary legal terms rather than omit them.
- **Privacy by design**: uploaded images and audio are handled in memory only and are not persisted to disk by the application.
- **Language accessibility**: responses are generated in the same language the user asked in, rather than defaulting to a single language, to reduce barriers for non-native speakers.
- **Persistent on-screen disclaimer**: the UI displays a visible reminder that LegalHelp is not a substitute for a licensed lawyer, in addition to the reminder baked into every model response.
- **Anti-hallucination guardrails**: the prompt explicitly instructs the model not to fabricate clauses, dates, or figures, and to say plainly if an uploaded image doesn't appear to be a legal document.

## Limitations

- Responses depend entirely on Gemini's ability to read the uploaded image accurately; poor image quality (blur, glare, handwriting) can affect output quality.
- The application does not verify or fact-check Gemini's output against actual legal statutes — explanations are informational, not authoritative.
- Gemini's JSON output is parsed with a best-effort fallback for markdown-fenced responses; malformed responses will raise a parsing error rather than a partial result.
- gTTS language support is limited; if the detected language code isn't supported, speech falls back to a default language rather than failing.
- There is no persistent storage, chat history, or multi-turn conversation — each analysis is a single, independent request.
- Retries only cover transient API-level errors; they will not help if the API key is invalid or the service is down entirely.

## Future Improvements

- Support for multi-page or multi-image document uploads.
- Conversation memory to allow follow-up questions about the same document.
- Confidence indicators or source highlighting within the document image.
- Expanded automated testing around response parsing and edge cases.
- Optional export of the explanation (e.g., as a PDF or text file).

## License

TBD.
