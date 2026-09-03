import secrets

import resend

from src.config import BACKEND_BASE_URL, RESEND_API_KEY, RESEND_FROM_EMAIL

# resend.api_key defaults to None and is NOT auto-read from the
# environment (confirmed by inspecting the installed package) -- must be
# set explicitly before any Emails.send() call.
resend.api_key = RESEND_API_KEY


def check_resend_configured() -> None:
    """Same fail-fast pattern as check_jwt_secret_configured() /
    check_qdrant_reachable(): a missing key is an obvious startup error,
    not a confusing failure on the first signup call."""
    if not RESEND_API_KEY:
        raise RuntimeError(
            "RESEND_API_KEY is not set. Set it as an environment variable "
            "before starting the API (e.g. `setx RESEND_API_KEY <key>` on "
            "Windows, then reopen the shell)."
        )


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def send_verification_email(email: str, token: str) -> None:
    verify_url = f"{BACKEND_BASE_URL}/verify?token={token}"
    resend.Emails.send(
        {
            "from": RESEND_FROM_EMAIL,
            "to": email,
            "subject": "Verify your Tata Steel RAG account",
            "html": f'<p>Click the link below to verify your account:</p><p><a href="{verify_url}">{verify_url}</a></p>',
        }
    )
