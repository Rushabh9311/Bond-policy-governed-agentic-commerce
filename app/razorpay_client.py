"""
Thin wrapper around Razorpay's test-mode API.

Deliberately kept dumb and deterministic — this module has ZERO decision
logic in it. It only executes what the policy engine has already approved.
That separation is the whole point of the architecture:

    LLM proposes -> Policy engine authorizes -> THIS MODULE executes

Docs: https://razorpay.com/docs/api/orders/ and
      https://razorpay.com/docs/api/payments/payment-links/
"""
import razorpay

from app.config import settings

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(amount_paise: int, receipt: str, notes: dict | None = None) -> dict:
    """Creates a Razorpay Order. amount_paise must be an int (paise, not rupees).
    e.g. ₹1,799 -> 179900."""
    return client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": notes or {},
        }
    )


def create_payment_link(
    amount_paise: int,
    description: str,
    reference_id: str,
    notes: dict | None = None,
    callback_url: str | None = None,
) -> dict:
    """Creates a hosted Razorpay Payment Link. The returned dict includes
    'short_url' — that's the link you hand to the 'buyer' (the judge) to
    actually pay. No custom checkout UI needed.

    If callback_url is given, Razorpay redirects the buyer's BROWSER back
    to it after payment (with a signed query string) — this is what lets
    us learn a payment succeeded without a public webhook endpoint."""
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "description": description,
        "reference_id": reference_id,
        "notes": notes or {},
    }
    if callback_url:
        payload["callback_url"] = callback_url
        payload["callback_method"] = "get"
    return client.payment_link.create(payload)


def verify_payment_link_signature(params: dict) -> bool:
    """Verifies the signature Razorpay appends to the callback_url redirect
    query string. ALWAYS call this before trusting a payment-link redirect —
    otherwise anyone could hit /payment-return with fake query params and
    mark an unpaid intent as paid."""
    try:
        client.utility.verify_payment_link_signature(params)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_webhook_signature(request_body: bytes, signature: str) -> bool:
    """Verifies the X-Razorpay-Signature header on incoming webhooks.
    Always call this before trusting a webhook payload."""
    try:
        client.utility.verify_webhook_signature(
            request_body.decode(), signature, settings.RAZORPAY_WEBHOOK_SECRET
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False