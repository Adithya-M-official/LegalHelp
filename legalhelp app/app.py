"""
app.py

Streamlit UI for LegalHelp.

This module handles user interaction: account authentication, file
uploads, audio recording, input validation, displaying results, and
calling into ai_logic.py for all AI processing. No Gemini calls, prompt
engineering, or speech generation happen here -- see ai_logic.py for
that. No password hashing or session logic happens here -- see auth.py.
No direct SQL happens here -- see storage.py.
"""

import logging
from typing import List, Optional

import streamlit as st
from PIL import UnidentifiedImageError

import auth
import storage
from ai_logic import analyze_document
from config import (
    ALLOWED_DOCUMENT_TYPES,
    ALLOW_ANALYSIS_WITH_QUALITY_WARNINGS,
    APP_ICON,
    APP_NAME,
    DEFAULT_AUDIO_MIME_TYPE,
    DEFAULT_IMAGE_MIME_TYPE,
    LOG_LEVEL,
    MAX_AUDIO_SIZE_MB,
    MAX_HISTORY_ITEMS_DISPLAYED,
    MAX_IMAGE_SIZE_MB,
    MAX_PAGES,
    MAX_PDF_SIZE_MB,
    MAX_QUESTION_LENGTH,
)
from document_pages import validate_pages
from export import build_explanation_pdf
from pdf_input import is_pdf

# --------------------------------------------------------------------------
# Logging setup
# --------------------------------------------------------------------------
# Streamlit doesn't configure logging by default. Setting this up once,
# here at the UI entry point, gives every module's logger.* calls a
# consistent format and destination (stderr, visible in the terminal
# running `streamlit run app.py`) without printing anything into the
# user-facing UI itself.

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Database schema is created (if missing) once per process start.
storage.init_db()

# --------------------------------------------------------------------------
# Page setup
# --------------------------------------------------------------------------

st.set_page_config(page_title=APP_NAME, page_icon=APP_ICON, layout="centered")

# Minor spacing tweak to pair with the sticky bottom composer below, plus
# styling for the chat-bubble presentation of the question/answer pair
# shown after an analysis runs.
st.markdown(
    """
    <style>
    .block-container { padding-bottom: 2rem; }

    .lh-chat-row {
        display: flex;
        width: 100%;
        margin: 6px 0;
    }
    .lh-chat-row.lh-user { justify-content: flex-end; }
    .lh-chat-row.lh-ai { justify-content: flex-start; }

    .lh-bubble {
        max-width: 75%;
        padding: 10px 14px;
        border-radius: 16px;
        line-height: 1.45;
        font-size: 0.95rem;
        white-space: pre-wrap;
        word-wrap: break-word;
        box-shadow: 0 1px 2px rgba(0,0,0,0.08);
    }
    .lh-bubble-user {
        background-color: #2563eb;
        color: #ffffff;
        border-bottom-right-radius: 4px;
    }
    .lh-bubble-ai {
        background-color: #f1f3f5;
        color: #111111;
        border: 1px solid #e2e4e8;
        border-bottom-left-radius: 4px;
    }
    .lh-bubble-label {
        display: block;
        font-size: 0.72rem;
        font-weight: 600;
        opacity: 0.7;
        margin-bottom: 4px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _render_chat_bubble(text: str, *, is_user: bool) -> None:
    """
    Render a single chat-style bubble.

    User messages are right-aligned (blue); AI responses are
    left-aligned (light gray) and rendered underneath. HTML is escaped
    to avoid breaking layout or injecting markup from document text.
    """
    import html as _html

    row_class = "lh-user" if is_user else "lh-ai"
    bubble_class = "lh-bubble-user" if is_user else "lh-bubble-ai"
    label = "You" if is_user else APP_NAME
    safe_text = _html.escape(text)

    st.markdown(
        f"""
        <div class="lh-chat-row {row_class}">
            <div class="lh-bubble {bubble_class}">
                <span class="lh-bubble-label">{label}</span>
                {safe_text}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Authentication gate
# --------------------------------------------------------------------------
# Nothing below this block runs until a confirmed account is logged in.
# Signup, login, account confirmation, and switching between previously
# -used accounts (within this browser session) all happen here.

def _render_login_form() -> None:
    login_tab, signup_tab, confirm_tab = st.tabs(
        ["Log in", "Create account", "Confirm account"]
    )

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Log in", type="primary")
        if submitted:
            success, message = auth.log_in(email, password)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

    with signup_tab:
        with st.form("signup_form"):
            new_display_name = st.text_input("Display name", key="signup_name")
            new_email = st.text_input("Email", key="signup_email")
            new_password = st.text_input(
                "Password", type="password", key="signup_password"
            )
            new_password_confirm = st.text_input(
                "Confirm password", type="password", key="signup_password_confirm"
            )
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            success, message, token = auth.sign_up(
                new_email, new_display_name, new_password, new_password_confirm
            )
            if success:
                st.success(message)
                st.info(
                    "**Demo confirmation step:** this project has no email "
                    "server configured, so instead of emailing you a "
                    "confirmation link, here is your confirmation code. "
                    "Copy it into the **Confirm account** tab to activate "
                    f"your account:\n\n`{token}`"
                )
            else:
                st.error(message)

    with confirm_tab:
        st.caption(
            "Enter the confirmation code shown after signup to activate "
            "your account."
        )
        with st.form("confirm_form"):
            confirm_code = st.text_input("Confirmation code", key="confirm_code")
            confirm_submitted = st.form_submit_button("Confirm account")
        if confirm_submitted:
            success, message = auth.confirm_account(confirm_code)
            if success:
                st.success(message)
            else:
                st.error(message)

        st.divider()
        st.caption("Didn't get a code, or it expired? Request a new one.")
        with st.form("resend_form"):
            resend_email = st.text_input("Account email", key="resend_email")
            resend_submitted = st.form_submit_button("Resend confirmation code")
        if resend_submitted:
            success, message, token = auth.resend_confirmation_token(resend_email)
            if success:
                st.success(message)
                st.info(f"New confirmation code:\n\n`{token}`")
            else:
                st.warning(message)


def _render_account_switcher_landing() -> None:
    """
    Shown above the login form when there are already accounts
    remembered in this browser session, so switching back doesn't
    require re-entering a password.
    """
    remembered = auth.get_remembered_accounts()
    if not remembered:
        return

    st.write("**Switch to a previously used account:**")
    for account in remembered:
        col_label, col_button = st.columns([4, 1])
        with col_label:
            st.write(f"{account.display_name} — {account.email}")
        with col_button:
            if st.button("Switch", key=f"switch_{account.id}"):
                success, message = auth.switch_account(account.id)
                if success:
                    st.rerun()
                else:
                    st.error(message)
    st.divider()


st.title(f"{APP_ICON} {APP_NAME}")

if not auth.is_logged_in():
    st.write(
        "Upload one or more photos of a legal document, or a PDF, then ask "
        "a question by typing or recording your voice. LegalHelp will "
        "explain it in plain language."
    )
    st.write("Log in or create an account to get started — this also lets "
              "LegalHelp save your past explanations so you can find them "
              "again later.")
    _render_account_switcher_landing()
    _render_login_form()
    st.stop()


# --------------------------------------------------------------------------
# Sidebar: account info, account switching, and saved history
# --------------------------------------------------------------------------

current_user = auth.get_current_user()

with st.sidebar:
    st.subheader("Account")
    st.write(f"**{current_user.display_name}**")
    st.caption(current_user.email)

    if st.button("Log out", use_container_width=True):
        auth.log_out()
        st.rerun()

    remembered_accounts = [
        account for account in auth.get_remembered_accounts()
        if account.id != current_user.id
    ]
    if remembered_accounts:
        st.divider()
        st.caption("Switch account")
        for account in remembered_accounts:
            if st.button(
                f"{account.display_name} ({account.email})",
                key=f"sidebar_switch_{account.id}",
                use_container_width=True,
            ):
                success, message = auth.switch_account(account.id)
                if success:
                    st.rerun()
                else:
                    st.error(message)

    st.divider()
    with st.expander("Add another account"):
        _render_login_form()

    st.divider()
    st.subheader("Saved explanations")
    st.caption(
        "Your past questions and explanations are saved to your account "
        "so you can find them again later."
    )
    history_entries = storage.get_history_for_user(
        current_user.id, limit=MAX_HISTORY_ITEMS_DISPLAYED
    )
    if not history_entries:
        st.caption("No saved explanations yet.")
    else:
        for entry in history_entries:
            with st.expander(f"{entry.created_at[:16].replace('T', ' ')} — {entry.question[:40]}"):
                st.write(f"**Q:** {entry.question}")
                st.write(entry.response_text)
                if st.button("Delete", key=f"delete_history_{entry.id}"):
                    storage.delete_history_entry(entry.id, current_user.id)
                    st.rerun()
        if st.button("Clear all history", use_container_width=True):
            storage.clear_history_for_user(current_user.id)
            st.rerun()


# --------------------------------------------------------------------------
# Main app body
# --------------------------------------------------------------------------

st.write(
    "Upload one or more photos of a legal document, or a PDF, then ask "
    "a question by typing or recording your voice. LegalHelp will "
    "explain it in plain language."
)

st.info(
    "⚠️ **Not legal advice.** LegalHelp explains documents in plain "
    "language to help you understand them. It is not a lawyer, and its "
    "explanations are not checked against actual legal statutes or case "
    "law. It cannot replace a licensed legal professional. For decisions "
    "with real consequences, please consult one.",
    icon="⚠️",
)

# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

uploaded_images = st.file_uploader(
    "Upload a legal document (image or PDF)",
    type=ALLOWED_DOCUMENT_TYPES,
    accept_multiple_files=True,
    help=(
        f"Accepted formats: {', '.join(ALLOWED_DOCUMENT_TYPES).upper()}. "
        f"Max size per image: {MAX_IMAGE_SIZE_MB} MB, per PDF: "
        f"{MAX_PDF_SIZE_MB} MB. Up to {MAX_PAGES} pages — upload "
        "multiple images (or a single multi-page PDF) if your document "
        "has more than one page, in reading order."
    ),
)

if uploaded_images:
    if len(uploaded_images) > MAX_PAGES:
        st.warning(
            f"You uploaded {len(uploaded_images)} files, but only the "
            f"first {MAX_PAGES} pages will be analyzed. Consider "
            "splitting very long documents into separate requests."
        )
    # Preview so the user can confirm the right files were uploaded, in
    # the order they'll be sent. Descriptive captions double as alt text
    # for screen readers. PDFs can't be previewed inline as an image
    # here (they're only rasterized during analysis), so they get a
    # simple file-name placeholder instead.
    preview_images = uploaded_images[:MAX_PAGES]
    columns = st.columns(min(len(preview_images), 4)) if preview_images else []
    for position, (column, doc_file) in enumerate(
        zip(columns * (len(preview_images) // max(len(columns), 1) + 1), preview_images)
    ):
        with column:
            if is_pdf(doc_file.type or "", doc_file.name):
                st.markdown(f"📄 **{doc_file.name}**")
                st.caption("PDF — pages will be extracted during analysis.")
            else:
                st.image(
                    doc_file,
                    caption=f"Page {position + 1}: {doc_file.name}",
                    use_container_width=True,
                )

# Chat-style composer, pinned to the bottom of the viewport via
# Streamlit's native bottom container (st.bottom, 1.38+).
#
# NOTE: `st.bottom` is a *property* that returns a container object,
# not a function -- it must be used as `with st.bottom:`, NOT
# `with st.bottom():`. Calling it (`st.bottom()`) raises
# `TypeError: 'BottomContainerProxy' object is not callable`, which is
# the bug this revision fixes.
with st.bottom:
    input_col, button_col = st.columns([5, 1], vertical_alignment="bottom")
    with input_col:
        typed_question = st.text_input(
            "Type your question (optional)",
            max_chars=MAX_QUESTION_LENGTH,
            placeholder="Ask about your document...",
            label_visibility="collapsed",
        )
    with button_col:
        analyze_clicked = st.button(
            "Analyze", type="primary", use_container_width=True
        )
    recorded_audio = st.audio_input("Or record your question instead")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _validate_basic_input() -> Optional[str]:
    """
    Check that the basic submission requirements are met, before any
    per-page validation or quality analysis runs.

    Returns:
        Optional[str]: A user-facing error message if validation fails,
        or None if the input is ready for per-page validation.
    """
    if not uploaded_images:
        return "Please upload at least one image or PDF of your legal document."

    if not typed_question and recorded_audio is None:
        return "Please type a question or record one before analyzing."

    for doc_file in uploaded_images[:MAX_PAGES]:
        if is_pdf(doc_file.type or "", doc_file.name):
            pdf_size_mb = len(doc_file.getvalue()) / (1024 * 1024)
            if pdf_size_mb > MAX_PDF_SIZE_MB:
                return (
                    f"'{doc_file.name}' is larger than the {MAX_PDF_SIZE_MB} MB "
                    "PDF size limit. Please upload a smaller file."
                )

    if recorded_audio is not None and not typed_question:
        audio_size_mb = len(recorded_audio.getvalue()) / (1024 * 1024)
        if audio_size_mb > MAX_AUDIO_SIZE_MB:
            return (
                f"That recording is larger than the {MAX_AUDIO_SIZE_MB} MB "
                "limit. Please record a shorter question."
            )

    return None


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------

if analyze_clicked:
    basic_error = _validate_basic_input()

    if basic_error:
        st.error(basic_error)
    else:
        # Show the user's question as a right-aligned chat bubble
        # immediately, before the (potentially slow) analysis runs, so
        # there's instant feedback that the request was received.
        _render_chat_bubble(
            typed_question if typed_question else "\U0001F3A4 (spoken question)",
            is_user=True,
        )
        pages_to_check = uploaded_images[:MAX_PAGES]
        page_results = validate_pages(
            uploaded_files=pages_to_check,
            max_size_mb=MAX_IMAGE_SIZE_MB,
            default_mime_type=DEFAULT_IMAGE_MIME_TYPE,
        )

        page_errors = [result.error for result in page_results if not result.is_valid]

        if page_errors:
            for error_message in page_errors:
                st.error(error_message)
        else:
            # Surface any image-quality warnings up front. Depending on
            # config, this either blocks analysis or just informs the
            # user before proceeding.
            all_quality_warnings: List[str] = []
            for result in page_results:
                for warning in result.quality_report.warnings:
                    all_quality_warnings.append(f"**{result.filename}:** {warning}")

            if all_quality_warnings:
                warning_block = "\n\n".join(f"- {w}" for w in all_quality_warnings)
                if ALLOW_ANALYSIS_WITH_QUALITY_WARNINGS:
                    st.warning(
                        "We noticed some possible image quality issues. "
                        "LegalHelp will still try to analyze the document, "
                        "but accuracy may be affected:\n\n" + warning_block
                    )
                else:
                    st.error(
                        "The uploaded image(s) have quality issues that may "
                        "prevent an accurate reading. Please re-upload "
                        "clearer photos:\n\n" + warning_block
                    )
                    page_results = []  # block downstream processing

            if page_results and not (
                all_quality_warnings and not ALLOW_ANALYSIS_WITH_QUALITY_WARNINGS
            ):
                with st.spinner(
                    "Reading your document and preparing an answer..."
                ):
                    try:
                        page_images = [
                            (result.image_bytes, result.mime_type)
                            for result in page_results
                        ]

                        # Exactly one input method is used: text takes
                        # priority over audio if both are somehow present.
                        if typed_question:
                            result = analyze_document(
                                page_images=page_images,
                                text_question=typed_question,
                            )
                        else:
                            result = analyze_document(
                                page_images=page_images,
                                audio_bytes=recorded_audio.getvalue(),
                                audio_mime_type=(
                                    recorded_audio.type or DEFAULT_AUDIO_MIME_TYPE
                                ),
                            )

                        # AI response rendered as a left-aligned chat
                        # bubble directly beneath the user's question
                        # bubble shown above.
                        _render_chat_bubble(result.response_text, is_user=False)
                        st.audio(result.audio_bytes, format="audio/mp3")

                        # Persist this Q&A to the logged-in account's
                        # history ("persistent memory"). Only the text
                        # exchange is stored -- uploaded page images and
                        # generated audio remain in-memory only, per the
                        # app's existing privacy design.
                        try:
                            storage.save_history_entry(
                                user_id=current_user.id,
                                question=(
                                    typed_question
                                    if typed_question
                                    else "(spoken question)"
                                ),
                                response_text=result.response_text,
                                language_code=result.language_code,
                            )
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "Failed to save analysis to history; "
                                "continuing without blocking the response."
                            )

                        # Let users save the explanation for their own
                        # records, either as plain text or as a PDF.
                        download_col1, download_col2 = st.columns(2)

                        with download_col1:
                            st.download_button(
                                label="Download as text",
                                data=result.response_text,
                                file_name="legalhelp_explanation.txt",
                                mime="text/plain",
                            )

                        with download_col2:
                            try:
                                pdf_buffer = build_explanation_pdf(
                                    response_text=result.response_text,
                                    language_code=result.language_code,
                                    app_name=APP_NAME,
                                )
                                st.download_button(
                                    label="Download as PDF",
                                    data=pdf_buffer,
                                    file_name="legalhelp_explanation.pdf",
                                    mime="application/pdf",
                                )
                            except RuntimeError as pdf_error:
                                logger.warning(
                                    "PDF export unavailable: %s", pdf_error
                                )
                                st.caption(
                                    "PDF export isn't available right now, "
                                    "but you can still download the text "
                                    "version above."
                                )

                    except UnidentifiedImageError:
                        logger.exception("Uploaded file failed image validation.")
                        st.error(
                            "That file doesn't look like a valid image or "
                            "PDF. Please upload a clear PNG/JPG photo or a "
                            "readable PDF of your document."
                        )
                    except RuntimeError as config_error:
                        logger.exception("Configuration or connectivity error.")
                        st.error(f"Configuration error: {config_error}")
                    except ValueError as parse_error:
                        logger.exception("Failed to parse Gemini response.")
                        st.error(
                            "Sorry, LegalHelp had trouble understanding "
                            f"the document. Please try again. ({parse_error})"
                        )
                    except Exception as unexpected_error:  # noqa: BLE001
                        logger.exception("Unexpected error during analysis.")
                        st.error(
                            "Something unexpected went wrong while "
                            f"analyzing your document: {unexpected_error}"
                        )
