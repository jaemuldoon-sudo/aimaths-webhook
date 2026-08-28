"""
aimaths.ie — Stripe webhook service
Writes a buyer's email into paid_users on checkout.session.completed.

Env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
Start:    uvicorn webhook:app --host 0.0.0.0 --port $PORT
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

        # Stripe objects support direct key access with [] and .get via
        # the mapping interface. Access fields directly rather than converting.
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

        # debug: show what we actually have
        try:
            print(f"[webhook] session id: {session['id']}")
        except Exception:
            pass
        try:
            print(f"[webhook] customer_details: {session['customer_details']}")
        except Exception as e:
            print(f"[webhook] could not read customer_details: {e}")

        print(f"[webhook] resolved email={email!r}")

        if email:
            try:
                result = supabase.table("paid_users").upsert(
                    {"email": str(email).strip().lower()}
                ).execute()
                print(f"[webhook] upsert OK: {result.data}")
            except Exception as e:
                print(f"[webhook] SUPABASE WRITE ERROR: {e}")
                traceback.print_exc()
                return {"status": "error", "detail": str(e)}
        else:
            print("[webhook] no email found on session — nothing written")

    return {"status": "ok"}