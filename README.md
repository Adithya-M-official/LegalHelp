# ⚖️ LegalHelp

## Overview

LegalHelp is a Streamlit application that helps everyday people understand legal documents in plain language. A user creates or logs into an account, uploads one or more photos of a legal document, or a PDF (single- or multi-page), and asks a question — either by typing or recording their voice. LegalHelp uses Google's Gemini model to read the document, check the pages for common quality problems, answer the question in simple terms, speak the answer back in the same language it was asked in, and saves the explanation to the user's account so it can be found again later.

## Problem Statement

Legal documents are often dense, jargon-heavy, and inaccessible to people without legal training. This creates a real barrier for individuals with limited literacy, limited time, or limited familiarity with legal language — who may end up signing, ignoring, or misunderstanding documents that materially affect their lives. LegalHelp aims to lower that barrier by turning a photo (or set of photos), or a PDF, and a spoken or typed question into a clear, plain-language explanation — and by keeping a private, per-account record of past explanations so a user isn't starting from scratch every time they revisit a document.

## Features

- 👤 **Accounts, login, and confirmation** — users create an account (email, display name, password), confirm it via a single-use confirmation code, and log in to a private session. See [Accounts & Authentication](#accounts--authentication) below for full details, including the important caveat about how confirmation codes are currently delivered.
- 🔁 **Multiple accounts, one browser session** — more than one account can be logged into during the same browser session and switched between without re-entering a password each time (e.g. a personal account and a family member's account on a shared device).
- 🧠 **Persistent memory of past explanations** — every analysis (question + plain-language explanation) is saved to the logged-in account and shown in a "Saved explanations" panel, so it's available again after logging out and back in, from any device. Individual entries or the whole history can be deleted at any time.
- 📷 **Image-based document input** — upload one or more photos of a legal document (PNG/JPG/JPEG).
- 📄 **Native PDF support** — upload a PDF directly; each page is extracted in memory and read the same way as an uploaded photo, including the same quality checks.
- 📚 **Multi-page support** — upload several page images, a multi-page PDF, or a mix of both at once (up to 10 pages total) and LegalHelp reads them together as a single document, in the order uploaded.
- 🔍 **Automatic image quality checks** — each uploaded page is screened for blur, glare, low resolution, and poor lighting before analysis, with clear warnings so problems are caught early instead of producing a low-quality answer.
- ⌨️🎙️ **Two ways to ask** — type a question or record it as audio.
- 🌍 **Automatic language detection** — Gemini detects the language of the question and responds in that same language.
- 🗣️ **Spoken responses** — answers are converted to speech (via gTTS) so users can listen as well as read, with automatic language-code translation between Gemini's output and gTTS's supported languages.
- 🧠 **Plain-language explanations** — the system prompt instructs Gemini to explain documents simply, preserve legal meaning, avoid unnecessary jargon, and flag uncertainty, without giving definitive legal advice.
- 🔒 **In-memory document processing** — uploaded images and audio are processed entirely in memory and are never written to disk. (Account credentials and saved text explanations *are* persisted — see below.)
- ✅ **Upfront input validation** — per-file size limits (images and PDFs separately), image-format checks, PDF readability checks (including password-protected PDF detection), page-count limits, and question-length limits catch problems before an API call is made.
- 🔁 **Automatic retry on transient failures** — brief Gemini API/network hiccups are retried automatically instead of failing the whole request.
- ⬇️ **Downloadable explanations** — users can save the plain-language explanation as a text file or a formatted PDF for their records, in addition to it being saved automatically to their account history.
- 🪵 **Structured technical logging** — key steps (requests, retries, parsing fallbacks, quality warnings, errors) are logged with standard library `logging` for developer visibility, without exposing internals to end users.
- ♿ **Accessibility touches** — descriptive image captions (serving as alt text), clear labeled inputs, and a persistent on-screen disclaimer.

## Accounts & Authentication

LegalHelp now requires an account before any document can be analyzed. This section explains exactly how that works, including its current limitations, so it isn't mistaken for a production-grade identity system.

- **Signup** collects an email, display name, and password. Passwords are never stored in plain text: each is hashed with **PBKDF2-HMAC-SHA256** (600,000 iterations) and a unique random salt per account, using only Python's standard library (`hashlib`/`secrets`) — no plaintext password ever reaches the database.
- **Confirmation** is required before an account can log in. A random, single-use confirmation code is generated at signup and again on request ("resend code"). Codes expire after 30 minutes.
  - ⚠️ **Important caveat:** this project has no outbound email/SMTP service configured. Rather than silently failing or faking success, the confirmation code is shown directly in the app UI right after signup, clearly labeled as a local/demo step. The *token mechanism itself* (generation, expiry, single-use enforcement, storage) is fully real and production-shaped — only the *delivery channel* (which would normally be an email) is simulated. Wiring up real email delivery (e.g. via SMTP or a transactional email API) would only require changing where the token is sent in `auth.py`/`app.py`, not the underlying logic.
- **Login** verifies the submitted password against the stored hash using a constant-time comparison, and blocks unconfirmed accounts with a clear message pointing back to the confirmation step.
- **Multiple accounts / switching** — logging into a second account during the same browser session adds it to a small "remembered accounts" list (kept only in that session's memory, holding id/email/display name — never a password). Both the login screen and the in-app sidebar offer one-click switching between remembered accounts without re-entering credentials, up to 5 accounts per session.
- **Password changes** are supported (`auth.change_password`) and require the current password.
- **Logging out** clears the active session but leaves the account itself, and its saved history, untouched in the database for the next login.

## Persistent Memory

Every time an analysis completes successfully, the question and the plain-language explanation (plus detected language) are saved to the logged-in account's history in the database. This is shown in a **"Saved explanations"** panel in the sidebar, where each entry can be expanded to re-read, individually deleted, or all cleared at once.

What is **not** persisted, consistent with the app's original privacy design:
- Uploaded document page images (still in-memory only, discarded after the request).
- Generated audio (still in-memory only).
- Recorded voice questions (still in-memory only; only the resulting text is what gets saved if a question was asked by voice, the history entry is labeled "(spoken question)" rather than a transcript, since no transcript is generated separately from the plain-language explanation itself).

## Architecture Overview

LegalHelp follows a simple, layered separation of concerns:

1. **UI layer (`app.py`)** gates access behind login, collects one or more page images and/or a PDF via a top-of-page uploader, and a question via a chat-style composer pinned to the bottom of the screen, sets up application-wide logging, and renders quality warnings, results, account controls, and saved history in between.
2. **Authentication (`auth.py`)** handles signup, login, logout, password hashing/verification, confirmation-token generation and redemption, and multi-account session switching. Holds no direct SQL — delegates all persistence to `storage.py`.
3. **Persistence (`storage.py`)** is a thin SQLite-backed data-access layer for user accounts, confirmation tokens, and saved analysis history. Uses only the Python standard library's `sqlite3` — no external database server required.
4. **PDF handling (`pdf_input.py`)** detects PDF uploads and rasterizes each page in memory into a PNG image, so a PDF re-enters the exact same per-page pipeline as a directly-uploaded photo.
5. **Page validation (`document_pages.py`)** expands any PDFs into their rasterized pages, then validates each resulting page (size, format) and runs it through the image quality checks.
6. **Image quality checks (`image_quality.py`)** screen each page for blur, glare, low resolution, and poor lighting using lightweight Pillow-based heuristics — no extra image-processing dependency required.
7. **Logic layer (`ai_logic.py`)** builds a multimodal request (one or more page images + text or audio), sends it to the Gemini API along with the system prompt, and robustly parses the structured JSON response.
8. **Response handling** — the parsed explanation text is converted to speech with gTTS, with language-code resolution to avoid unnecessary fallbacks, and saved to the user's account history.
9. **Export (`export.py`)** — builds an optional PDF version of the explanation for download.
10. **Output** — the text explanation, generated audio, and download options are displayed back in the Streamlit UI.

Configuration (model name, defaults, limits, auth/database settings) and prompt text are isolated into their own modules so behavior can be tuned without touching UI or logic code.

```
User logs in / creates + confirms an account
            │
            ▼
     auth.py ←→ storage.py (SQLite: users, tokens, history)
            │
            ▼
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
   Parsed response → gTTS (text-to-speech) + storage.py (save to history)
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
| Accounts & history storage | SQLite (Python standard library `sqlite3`) |
| Password hashing | PBKDF2-HMAC-SHA256 (Python standard library `hashlib`/`secrets`) |

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

4. **Database file**

   No setup needed — a local SQLite database (`data/legalhelp.db` by default, configurable in `config.py`) is created automatically the first time the app runs. This file (and the whole `data/` folder) is git-ignored since it contains account data.

## Usage

Run the app with Streamlit:

```bash
streamlit run app.py
```

Then, in the browser window that opens:

1. **Create an account** (email, display name, password) on the **Create account** tab, or **log in** if you already have one.
2. **Confirm your account** using the confirmation code shown right after signup (see the caveat in [Accounts & Authentication](#accounts--authentication) about how this code is currently delivered), on the **Confirm account** tab.
3. Once logged in, upload one or more photos of a legal document (PNG/JPG/JPEG), or a PDF, or a mix of both, using the uploader near the top of the page. For multi-page documents, upload all pages at once, in reading order (up to 10 pages) — a single multi-page PDF works too.
4. Ask a question using the chat-style composer pinned to the bottom of the screen — either type it into the input box, or record it using the audio option beneath it (if both are provided, the typed question takes priority).
5. Click **Analyze**, next to the question box. PDF pages are extracted automatically. If any page has a quality issue (blur, glare, low resolution, poor lighting), you'll see a warning before the explanation is generated.
6. Read the plain-language explanation and/or listen to the generated audio response, both displayed above the composer. The explanation is also saved automatically to your account.
7. Optionally download the explanation as a text file or a PDF, or revisit it later from the **Saved explanations** panel in the sidebar.
8. Use the sidebar to log out, or to switch to another account you've logged into during this session.

## Project Structure

```
├── app.py                          # Streamlit UI — auth gate, uploads, validation, logging setup, result display, history sidebar
├── auth.py                         # Signup, login, logout, password hashing, confirmation tokens, multi-account session switching
├── storage.py                      # SQLite-backed persistence: user accounts, confirmation tokens, saved analysis history
├── ai_logic.py                     # Gemini client, retries, request construction, response parsing, text-to-speech
├── document_pages.py               # Per-page upload validation and quality-check orchestration (images + PDFs)
├── pdf_input.py                    # PDF detection and in-memory rasterization to page images
├── image_quality.py                # Pillow-based blur/glare/resolution/lighting heuristics
├── export.py                       # PDF export of the plain-language explanation
├── config.py                       # Configuration constants (model, limits, retries, auth/db settings, app metadata)
├── prompts.py                      # Gemini system prompt
├── requirements.txt                # Pinned dependencies
├── .streamlit/secrets.toml.example # Template for the required API key file
├── data/                           # SQLite database lives here at runtime (git-ignored, auto-created)
├── .gitignore
└── README.md
```

## Responsible AI Considerations

- **No legal advice**: the system prompt explicitly instructs the model to explain document content without presenting itself as a lawyer or offering a definitive legal recommendation.
- **No claim of legal verification**: the system prompt and UI disclaimer are explicit that explanations are not checked against actual legal statutes or case law — this is an inherent limitation of the tool, not something an update can silently fix, so it is now stated up front rather than left implicit.
- **Uncertainty disclosure**: the model is instructed to clearly state when it is unsure about part of a document, when any page image is unclear or partially unreadable, or how a clause might apply to the user's situation.
- **Meaning preservation**: the prompt directs the model to avoid oversimplifying to the point of inaccuracy, and to briefly explain necessary legal terms rather than omit them.
- **Privacy by design, with account data as an explicit exception**: uploaded images and audio are handled in memory only and are not persisted to disk by the application. Account credentials (hashed, never plaintext) and saved text explanations *are* persisted, by design, to support login and the history feature — this tradeoff is intentional and documented, not accidental.
- **Language accessibility**: responses are generated in the same language the user asked in, rather than defaulting to a single language, to reduce barriers for non-native speakers.
- **Persistent on-screen disclaimer**: the UI displays a visible reminder that LegalHelp is not a substitute for a licensed lawyer, in addition to the reminder baked into every model response and repeated in the PDF export.
- **Anti-hallucination guardrails**: the prompt explicitly instructs the model not to fabricate clauses, dates, or figures, and to say plainly if the uploaded images don't appear to be (or don't coherently form) a legal document.
- **Proactive quality signaling**: rather than silently producing a possibly-degraded answer from a blurry or glare-affected photo, the app now flags likely quality problems before analysis so users can decide whether to proceed or re-upload.
- **Confirmation-delivery transparency**: because there is no real email integration yet, the app is explicit in its own UI (not just this README) that the confirmation code is a local/demo delivery mechanism, so a deployer doesn't mistake it for verified email ownership.

## Limitations

- Responses depend entirely on Gemini's ability to read the uploaded page(s) accurately. LegalHelp now screens image pages for common problems (blur, glare, low resolution, poor lighting) and warns the user beforehand, but this is a heuristic screen, not a guarantee — a technically "sharp" photo can still be misread if handwriting is illegible or the document itself is degraded.
- PDF support rasterizes each page to an image and reuses the same reading pipeline as photo uploads; it does not extract PDF text directly. A PDF that is already a clear, text-based document will generally rasterize cleanly, but a poor-quality scanned PDF is subject to the same quality limitations as an uploaded photo. Password-protected PDFs are detected and rejected with a clear message rather than failing silently.
- The application does not verify or fact-check Gemini's output against actual legal statutes or case law — explanations are informational, not authoritative. This is a fundamental scope boundary of the tool (it explains what a document says, not what the law says) rather than something that can be resolved with better parsing or retries, and is now stated explicitly in both the prompt and the UI.
- Gemini's JSON output is parsed with several layered fallbacks (fenced code blocks, stray pre/postamble text); a response that still can't be parsed after all fallbacks raises a clear error rather than returning a partial or fabricated result.
- gTTS language support is limited; detected language codes are now resolved against gTTS's supported-language list and a small alias table before synthesis, but if a code still isn't supported, speech falls back to a default language rather than failing.
- There is no multi-turn conversation about a single document — each analysis (of one or more pages) is a single, independent request, though the *result* of each is now saved and browsable afterward. Multi-page upload is supported, but treating a single upload as a batch of *separate* documents, or following up with a second question about the same document within one request, is not.
- **Confirmation codes are shown in-app rather than emailed** (see [Accounts & Authentication](#accounts--authentication)) — there is no real email/SMTP integration yet, so account confirmation currently proves "you saw the code in this UI," not "you own this email address." Treat this as a development/demo-mode account system rather than a production-grade one until real email delivery is added.
- The "remembered accounts" multi-account switcher lives only in the current browser session's memory (`st.session_state`) and resets on a full session restart — it is a convenience for switching within one sitting, not a persisted device-level account list.
- There is no password-reset-via-email flow yet (only an authenticated in-app password change); a forgotten password currently has no self-service recovery path.
- Retries only cover transient API-level errors; they will not help if the API key is invalid or the service is down entirely.
- PDF export uses a Latin-1-compatible font for simplicity and portability; explanations containing characters outside that range (e.g. some non-Latin scripts) may render those specific characters as a substitution mark in the PDF even though they display correctly in the UI and in the plain-text download.

## Future Improvements

Implemented in this update: account creation, login, confirmation, multi-account switching, and persistent per-account history of past explanations. Also fixed a startup crash (`TypeError: 'BottomContainerProxy' object is not callable`) caused by calling `st.bottom()` instead of using it as `with st.bottom:`.

Remaining, not yet implemented (deferred because they need larger architectural changes rather than incremental additions):

- Real email delivery for confirmation codes and password resets (SMTP or a transactional email API), replacing the current in-app code display.
- Conversation memory to allow follow-up questions *within* the same document analysis — requires session/state design (what counts as "the same document," how long to retain it, memory limits) beyond the current single-request-per-analysis model. (Note this is distinct from the cross-session history already implemented — history lets you *revisit* past answers, not *continue* a conversation.)
- Confidence indicators or source highlighting within the document image — requires the model or a secondary process to return bounding boxes / spans tied to specific claims, which is a meaningfully different response contract than today's plain-text explanation.
- Expanded automated testing around response parsing, auth edge cases, and history persistence.
- Rate limiting / lockout on repeated failed login attempts.

## License

TBD.
