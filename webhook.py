"""
aimaths.ie — Stripe webhook service
Writes a buyer's email into paid_users on checkout.session.completed.

Env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
Start:    uvicorn webhook:app --host 0.0.0.0 --port $PORT
"""

import os
import json
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


def _extract_email(session_dict):
    """Look for the buyer email in every place Stripe might put it."""
    # 1) customer_details.email
    cd = session_dict.get("customer_details")
    if isinstance(cd, dict) and cd.get("email"):
        return cd["email"]
    # 2) customer_email
    if session_dict.get("customer_email"):
        return session_dict["customer_email"]
    # 3) prefilled.email (payment links)
    pf = session_dict.get("prefilled")
    if isinstance(pf, dict) and pf.get("email"):
        return pf["email"]
    return None


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

        # convert the Stripe object to a plain dict robustly
        try:
            session_dict = json.loads(json.dumps(session, default=lambda o: dict(o)))
        except Exception:
            try:
                session_dict = dict(session)
            except Exception:
                session_dict = {}

        # DEBUG: log the keys and the customer bits so we can see what's there
        print(f"[webhook] session keys: {list(session_dict.keys())}")
        print(f"[webhook] customer_details: {session_dict.get('customer_details')}")
        print(f"[webhook] customer_email: {session_dict.get('customer_email')}")

        email = _extract_email(session_dict)
        print(f"[webhook] resolved email={email!r}")

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
            print("[webhook] no email found on session — nothing written")

    return {"status": "ok"}