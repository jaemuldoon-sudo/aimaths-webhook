"""
aimaths.ie — Stripe webhook service
-------------------------------------------------------------------------------
A tiny standalone FastAPI app. Its ONLY job: listen for Stripe's
"payment completed" event and write the buyer's email into paid_users.

Deploy this as a SEPARATE service on Railway (not part of the Streamlit app).
It uses the Supabase service_role key, which bypasses RLS so it can write.

-------------------------------------------------------------------------------
Environment variables (set on the Railway *webhook* service):
    SUPABASE_URL            https://kvvdimmkbwudeftsgagc.supabase.co
    SUPABASE_SERVICE_KEY    Supabase service_role key
    STRIPE_SECRET_KEY       sk_test_... (test) then sk_live_... (live)
    STRIPE_WEBHOOK_SECRET   whsec_... (from the Stripe webhook endpoint you create)

Start command on Railway:
    uvicorn webhook:app --host 0.0.0.0 --port $PORT
-------------------------------------------------------------------------------
"""

import os
import stripe
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client

app = FastAPI()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# service_role key — needed to write to paid_users (bypasses RLS)
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)


@app.get("/")
def health():
    # simple health check so you can confirm the service is up in a browser
    return {"status": "aimaths webhook alive"}


@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    # verify the event really came from Stripe (not a forged request)
    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # we only care about a completed checkout
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        # the buyer's email — Stripe puts it in customer_details
        email = (session.get("customer_details") or {}).get("email")
        # fall back to customer_email if present
        if not email:
            email = session.get("customer_email")

        if email:
            # upsert = insert, or do nothing if already there (no duplicates)
            supabase.table("paid_users").upsert(
                {"email": email.strip().lower()}
            ).execute()

    # always 200 so Stripe knows we received it
    return {"status": "ok"}
