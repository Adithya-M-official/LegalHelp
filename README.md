# ⚖️ LegalHelp

## Overview

LegalHelp is a Streamlit application that helps everyday people understand legal documents in plain language. A user uploads one or more photos of a legal document, or a PDF (single- or multi-page), and asks a question — either by typing or recording their voice — and LegalHelp uses Google's Gemini model to read the document, check the pages for common quality problems, answer the question in simple terms, and speak the answer back in the same language it was asked in.

## Problem Statement

Legal documents are often dense, jargon-heavy, and inaccessible to people without legal training. This creates a real barrier for individuals with limited literacy, limited time, or limited familiarity with legal language — who may end up signing, ignoring, or misunderstanding documents that materially affect their lives. LegalHelp aims to lower that barrier by turning a photo (or set of photos), or a PDF, and a spoken or typed question into a clear, plain-language explanation.

## Features

- 📷 **Image-based document input** — upload one or more photos of a legal document (PNG/JPG/JPEG).
- 📄 **Native PDF support** — upload a PDF directly; each page is extracted in memory and read the same way as an uploaded photo, including the same quality checks.
- 📚 **Multi-page support** — upload several page images, a multi-page PDF, or a mix of both at once (up to 10 pages total) and LegalHelp reads them together as a single document, in the order uploaded.
- 🔍 **Automatic image quality checks** — each uploaded page is screened for blur, glare, low resolution, and poor lighting before analysis, with clear warnings so problems are caught early instead of producing a low-quality answer.
- ⌨️🎙️ **Two ways to ask** — type a question or record it as audio.
- 🌍 **Automatic language detection** — Gemini detects the language of the question and responds in that same language.
- 🗣️ **Spoken responses** — answers are converted to speech (via gTTS) so users can listen as well as read, with automatic language-code translation between Gemini's output and gTTS's supported languages.
- 🧠 **Plain-language explanations** — the system prompt instructs Gemini to explain documents simply, preserve legal meaning, avoid unnecessary jargon, and flag uncertainty, without giving definitive legal advice.
- 🔒 **In-memory processing** — uploaded images and audio are processed entirely in memory and are never written to disk.
- ✅ **Upfront input validation** — per-file size limits (images and PDFs separately), image-format checks, PDF readability checks (including password-protected PDF detection), page-count limits, and question-length limits catch problems before an API call is made.
- 🔁 **Automatic retry on transient failures** — brief Gemini API/network hiccups are retried automatically instead of failing the whole request.
- ⬇️ **Downloadable explanations** — users can save the plain-language explanation as a text file or a formatted PDF for their records.
- 🪵 **Structured technical logging** — key steps (requests, retries, parsing fallbacks, quality warnings, errors) are logged with standard library `logging` for developer visibility, without exposing internals to end users.
- ♿ **Accessibility touches** — descriptive image captions (serving as alt text), clear labeled inputs, and a persistent on-screen disclaimer.

## Architecture Overview

LegalHelp follows a simple, layered separation of concerns:

1. **UI layer (`app.py`)** collects one or more page images and/or a PDF and a question from the user via Streamlit, sets up application-wide logging, and renders quality warnings and results.
2. **PDF handling (`pdf_input.py`)** detects PDF uploads and rasterizes each page in memory into a PNG image, so a PDF re-enters the exact same per-page pipeline as a directly-uploaded photo.
3. **Page validation (`document_pages.py`)** expands any PDFs into their rasterized pages, then validates each resulting page (size, format) and runs it through the image quality checks.
4. **Image quality checks (`image_quality.py`)** screen each page for blur, glare, low resolution, and poor lighting using lightweight Pillow-based heuristics — no extra image-processing dependency required.
5. **Logic layer (`ai_logic.py`)** builds a multimodal request (one or more page images + text or audio), sends it to the Gemini API along with the system prompt, and robustly parses the structured JSON response.
6. **Response handling** — the parsed explanation text is converted to speech with gTTS, with language-code resolution to avoid unnecessary fallbacks.
7. **Export (`export.py`)** — builds an optional PDF version of the explanation for download.
8. **Output** — the text explanation, generated audio, and download options are displayed back in the Streamlit UI.

Configuration (model name, defaults, limits) and prompt text are isolated into their own modules so behavior can be tuned without touching UI or logic code.

```
User uploads 1+ page images and/or a PDF + asks question (text or audio)
            │
            ▼
        app.py (Streamlit UI)
            │
            ▼
  document_pages.py → pdf_input.py (rasterize any PDF pages to images)
            │
            ▼
  document_pages.py → image_quality.py (per-page validation + quality checks)
            │
            ▼
     ai_logic.py → Gemini API (multimodal, JSON-structured response)
            │
            ▼
   Parsed response → gTTS (text-to-speech)
            │
            ▼
   Displayed back in app.py (text + audio + text/PDF download)
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python |
| UI framework | [Streamlit](https://streamlit.io/) |
| AI model | Google Gemini (`google-genai` SDK) |
| Text-to-speech | [gTTS](https://pypi.org/project/gTTS/) |
| Image handling & quality checks | [Pillow](https://python-pillow.org/) |
| PDF export | [fpdf2](https://pypi.org/project/fpdf2/) |
| PDF input (rasterization) | [PyMuPDF](https://pypi.org/project/PyMuPDF/) |

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

1. Upload one or more photos of a legal document (PNG/JPG/JPEG), or a PDF, or a mix of both. For multi-page documents, upload all pages at once, in reading order (up to 10 pages) — a single multi-page PDF works too.
2. Ask a question — either type it into the text box, or record it using the audio input (if both are provided, the typed question takes priority).
3. Click **Analyze**. PDF pages are extracted automatically. If any page has a quality issue (blur, glare, low resolution, poor lighting), you'll see a warning before the explanation is generated.
4. Read the plain-language explanation and/or listen to the generated audio response.
5. Optionally download the explanation as a text file or a PDF.

## Project Structure

```
├── app.py                          # Streamlit UI — uploads, validation, logging setup, result display
├── ai_logic.py                     # Gemini client, retries, request construction, response parsing, text-to-speech
├── document_pages.py               # Per-page upload validation and quality-check orchestration (images + PDFs)
├── pdf_input.py                    # PDF detection and in-memory rasterization to page images
├── image_quality.py                # Pillow-based blur/glare/resolution/lighting heuristics
├── export.py                       # PDF export of the plain-language explanation
├── config.py                       # Configuration constants (model, limits, retries, app metadata)
├── prompts.py                      # Gemini system prompt
├── requirements.txt                # Pinned dependencies
├── .streamlit/secrets.toml.example # Template for the required API key file
├── .gitignore
└── README.md
```

## Responsible AI Considerations

- **No legal advice**: the system prompt explicitly instructs the model to explain document content without presenting itself as a lawyer or offering a definitive legal recommendation.
- **No claim of legal verification**: the system prompt and UI disclaimer are explicit that explanations are not checked against actual legal statutes or case law — this is an inherent limitation of the tool, not something an update can silently fix, so it is now stated up front rather than left implicit.
- **Uncertainty disclosure**: the model is instructed to clearly state when it is unsure about part of a document, when any page image is unclear or partially unreadable, or how a clause might apply to the user's situation.
- **Meaning preservation**: the prompt directs the model to avoid oversimplifying to the point of inaccuracy, and to briefly explain necessary legal terms rather than omit them.
- **Privacy by design**: uploaded images and audio are handled in memory only and are not persisted to disk by the application.
- **Language accessibility**: responses are generated in the same language the user asked in, rather than defaulting to a single language, to reduce barriers for non-native speakers.
- **Persistent on-screen disclaimer**: the UI displays a visible reminder that LegalHelp is not a substitute for a licensed lawyer, in addition to the reminder baked into every model response and repeated in the PDF export.
- **Anti-hallucination guardrails**: the prompt explicitly instructs the model not to fabricate clauses, dates, or figures, and to say plainly if the uploaded images don't appear to be (or don't coherently form) a legal document.
- **Proactive quality signaling**: rather than silently producing a possibly-degraded answer from a blurry or glare-affected photo, the app now flags likely quality problems before analysis so users can decide whether to proceed or re-upload.

## Limitations

- Responses depend entirely on Gemini's ability to read the uploaded page(s) accurately. LegalHelp now screens image pages for common problems (blur, glare, low resolution, poor lighting) and warns the user beforehand, but this is a heuristic screen, not a guarantee — a technically "sharp" photo can still be misread if handwriting is illegible or the document itself is degraded.
- PDF support rasterizes each page to an image and reuses the same reading pipeline as photo uploads; it does not extract PDF text directly. A PDF that is already a clear, text-based document will generally rasterize cleanly, but a poor-quality scanned PDF is subject to the same quality limitations as an uploaded photo. Password-protected PDFs are detected and rejected with a clear message rather than failing silently.
- The application does not verify or fact-check Gemini's output against actual legal statutes or case law — explanations are informational, not authoritative. This is a fundamental scope boundary of the tool (it explains what a document says, not what the law says) rather than something that can be resolved with better parsing or retries, and is now stated explicitly in both the prompt and the UI.
- Gemini's JSON output is parsed with several layered fallbacks (fenced code blocks, stray pre/postamble text); a response that still can't be parsed after all fallbacks raises a clear error rather than returning a partial or fabricated result.
- gTTS language support is limited; detected language codes are now resolved against gTTS's supported-language list and a small alias table before synthesis, but if a code still isn't supported, speech falls back to a default language rather than failing.
- There is no persistent storage or multi-turn conversation — each analysis (of one or more pages) is a single, independent request. Multi-page upload is supported, but treating a single upload as a batch of *separate* documents, or following up with a second question about the same document, is not.
- Retries only cover transient API-level errors; they will not help if the API key is invalid or the service is down entirely.
- PDF export uses a Latin-1-compatible font for simplicity and portability; explanations containing characters outside that range (e.g. some non-Latin scripts) may render those specific characters as a substitution mark in the PDF even though they display correctly in the UI and in the plain-text download.

## Future Improvements

Implemented in this update: multi-page document uploads, PDF export of the explanation, and native PDF document upload/input.

Remaining, not yet implemented (deferred because they need larger architectural changes rather than incremental additions):

- Conversation memory to allow follow-up questions about the same document — requires session/state design (what counts as "the same document," how long to retain it, memory limits) beyond the current single-request model.
- Confidence indicators or source highlighting within the document image — requires the model or a secondary process to return bounding boxes / spans tied to specific claims, which is a meaningfully different response contract than today's plain-text explanation.
- Expanded automated testing around response parsing and edge cases.

## License

TBD.
