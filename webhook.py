"""
aimaths.ie — Stripe webhook service
Writes a buyer's email into paid_users on checkout.session.completed,
and emails you a notification that a new customer paid.

Env vars:
    SUPABASE_URL, SUPABASE_SERVICE_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
    RESEND_API_KEY        (to send you the notification)
    NOTIFY_EMAIL          (where to send the "new customer" alert, e.g. your email)
    NOTIFY_FROM           (a verified Resend sender, e.g. noreply@aimaths.ie)
Start:    uvicorn webhook:app --host 0.0.0.0 --port $PORT
"""

import os
import traceback
import requests
import stripe
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client

app = FastAPI()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
NOTIFY_FROM = os.getenv("NOTIFY_FROM", "noreply@aimaths.ie")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)


def notify_new_customer(email, amount=None, currency=None):
    """Email you when a new customer pays. Never blocks the webhook if it fails."""
    if not (RESEND_API_KEY and NOTIFY_EMAIL):
        print("[webhook] notify skipped (RESEND_API_KEY or NOTIFY_EMAIL not set)")
        return
    try:
        amount_str = ""
        if amount is not None and currency:
            amount_str = f" — {currency.upper()} {amount/100:.2f}"
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": f"aimaths.ie <{NOTIFY_FROM}>",
                "to": [NOTIFY_EMAIL],
                "subject": f"💰 New aiMATHS customer: {email}",
                "html": (
                    f"<p><b>New payment received!</b></p>"
                    f"<p>Customer: {email}{amount_str}</p>"
                    f"<p>They've been given access automatically.</p>"
                ),
            },
            timeout=15,
        )
        print(f"[webhook] notification email sent to {NOTIFY_EMAIL}")
    except Exception as e:
        print(f"[webhook] notify failed (non-fatal): {e}")


@app.get("/")
def health():
    return {"status": "aimaths webhook alive"}


@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception as e:
        print(f"[webhook] SIGNATURE ERROR: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        email = None
        try:
            cd = session["customer_details"]
            if cd is not None:
                email = cd["email"]
        except Exception:
            pass
        if not email:
            try:
                email = session["customer_email"]
            except Exception:
                pass

        # amount for the notification (optional)
        amount = None
        currency = None
        try:
            amount = session["amount_total"]
            currency = session["currency"]
        except Exception:
            pass

        print(f"[webhook] resolved email={email!r}")

        if email:
            try:
                result = supabase.table("paid_users").upsert(
                    {"email": str(email).strip().lower()}
                ).execute()
                print(f"[webhook] upsert OK: {result.data}")
                # notify you of the new customer
                notify_new_customer(str(email).strip().lower(), amount, currency)
            except Exception as e:
                print(f"[webhook] SUPABASE WRITE ERROR: {e}")
                traceback.print_exc()
                return {"status": "error", "detail": str(e)}
        else:
            print("[webhook] no email found on session — nothing written")

    return {"status": "ok"}