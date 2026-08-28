"""
aimaths.ie — Stripe webhook service
Writes a buyer's email into paid_users on checkout.session.completed.

Env vars (webhook service on Railway):
    SUPABASE_URL, SUPABASE_SERVICE_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET

Start command:
    uvicorn webhook:app --host 0.0.0.0 --port $PORT
"""

import os
import traceback
import stripe
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client

app = FastAPI()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)


def _extract_email(session):
    """
    Safely pull the buyer email from a Stripe checkout session.
    Stripe objects don't behave like plain dicts with .get(), so we
    convert to a plain dict first, then read fields defensively.
    """
    try:
        data = dict(session)
    except Exception:
        data = {}

    # customer_details.email is where hosted-checkout puts it
    details = data.get("customer_details")
    if details:
        try:
            details = dict(details)
        except Exception:
            pass
        email = details.get("email") if isinstance(details, dict) else None
        if email:
            return email

    # fall back to customer_email
    return data.get("customer_email")


@app.get("/")
def health():
    return {"status": "aimaths webhook alive"}


@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    # 1) verify signature
    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception as e:
        print(f"[webhook] SIGNATURE ERROR: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2) handle the completed checkout
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = _extract_email(session)
        print(f"[webhook] checkout.session.completed — email={email!r}")

        if email:
            try:
                result = supabase.table("paid_users").upsert(
                    {"email": email.strip().lower()}
                ).execute()
                print(f"[webhook] upsert OK: {result.data}")
            except Exception as e:
                print(f"[webhook] SUPABASE WRITE ERROR: {e}")
                traceback.print_exc()
                return {"status": "error", "detail": str(e)}
        else:
            print("[webhook] no email on session — nothing written")

    return {"status": "ok"}