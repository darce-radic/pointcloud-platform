"""
Stripe Billing Router
Handles subscription management, checkout sessions, customer portal, and webhooks.

Pricing tiers (all billed monthly):
  Starter    — $49/mo  — 50 GB storage, 5 projects, 10M pts/upload
  Pro        — $149/mo — 500 GB storage, unlimited projects, 100M pts/upload, AI assistant
  Enterprise — $499/mo — 5 TB storage, unlimited everything, priority support, custom domain
"""
from __future__ import annotations

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from supabase import Client

from config import settings
from dependencies import get_current_user, get_supabase, AuthenticatedUser

N8N_PAYMENT_FAILED_WEBHOOK = "https://n8n-production-74b2f.up.railway.app/webhook/payment-failed"
N8N_NEW_USER_WEBHOOK = "https://n8n-production-74b2f.up.railway.app/webhook/new-user-onboarding"


async def _notify_n8n(url: str, payload: dict) -> None:
    """Fire-and-forget POST to an n8n webhook. Errors are silently logged."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload)
    except Exception:
        pass  # Never let n8n notification failures break the main flow

router = APIRouter(prefix="/billing", tags=["Billing"])

# Stripe plan metadata — price IDs are created in Stripe Dashboard
# In test mode these are populated from env vars; in prod swap for live IDs.
PLANS: dict[str, dict] = {
    "starter": {
        "name": "Starter",
        "price_usd": 49,
        "price_id_env": "STRIPE_STARTER_PRICE_ID",
        "storage_bytes": 50 * 1024 ** 3,          # 50 GB
        "max_projects": 5,
        "max_points_per_upload": 10_000_000,
        "features": [
            "50 GB storage",
            "5 active projects",
            "10M points per upload",
            "COPC viewer",
            "Email support",
        ],
    },
    "pro": {
        "name": "Pro",
        "price_usd": 149,
        "price_id_env": "STRIPE_PRO_PRICE_ID",
        "storage_bytes": 500 * 1024 ** 3,          # 500 GB
        "max_projects": None,                        # unlimited
        "max_points_per_upload": 100_000_000,
        "features": [
            "500 GB storage",
            "Unlimited projects",
            "100M points per upload",
            "AI assistant (GPT-4.1)",
            "n8n workflow automation",
            "Priority email support",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "price_usd": 499,
        "price_id_env": "STRIPE_ENTERPRISE_PRICE_ID",
        "storage_bytes": 5 * 1024 ** 4,             # 5 TB
        "max_projects": None,
        "max_points_per_upload": None,
        "features": [
            "5 TB storage",
            "Unlimited projects & uploads",
            "Custom processing pipelines",
            "Dedicated AI assistant",
            "Custom domain",
            "SLA + dedicated support",
        ],
    },
}


def _stripe_client() -> stripe.Stripe:
    """Return a configured Stripe client."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured on this server.",
        )
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


# ── Schema ────────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str  # "starter" | "pro" | "enterprise"
    success_url: str | None = None
    cancel_url: str | None = None


class PortalRequest(BaseModel):
    return_url: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/plans")
async def list_plans():
    """Return available subscription plans (no auth required)."""
    return {
        plan_key: {
            "name": plan["name"],
            "price_usd": plan["price_usd"],
            "features": plan["features"],
            "storage_gb": plan["storage_bytes"] // (1024 ** 3),
            "max_projects": plan["max_projects"],
        }
        for plan_key, plan in PLANS.items()
    }


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Create a Stripe Checkout session for the given plan.
    Returns a URL the frontend should redirect to.
    """
    if body.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    plan = PLANS[body.plan]
    price_id = getattr(settings, plan["price_id_env"], "")
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Price ID for plan '{body.plan}' is not configured.",
        )

    sc = _stripe_client()

    # Get or create Stripe customer
    profile = (
        supabase.table("profiles")
        .select("stripe_customer_id, email")
        .eq("id", user.user_id)
        .single()
        .execute()
    )
    stripe_customer_id = profile.data.get("stripe_customer_id") if profile.data else None

    if not stripe_customer_id:
        customer = sc.customers.create(params={
            "email": user.email,
            "metadata": {"supabase_user_id": user.user_id},
        })
        stripe_customer_id = customer.id
        supabase.table("profiles").update(
            {"stripe_customer_id": stripe_customer_id}
        ).eq("id", user.user_id).execute()

    success_url = body.success_url or f"{settings.APP_DOMAIN}/billing?success=1"
    cancel_url = body.cancel_url or f"{settings.APP_DOMAIN}/billing?cancelled=1"

    session = sc.checkout.sessions.create(params={
        "customer": stripe_customer_id,
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {
            "supabase_user_id": user.user_id,
            "plan": body.plan,
        },
        "subscription_data": {
            "metadata": {
                "supabase_user_id": user.user_id,
                "plan": body.plan,
            }
        },
        "allow_promotion_codes": True,
    })

    return {"checkout_url": session.url}


@router.post("/portal")
async def create_customer_portal(
    body: PortalRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Create a Stripe Customer Portal session so the user can manage
    their subscription, update payment method, or cancel.
    """
    sc = _stripe_client()

    profile = (
        supabase.table("profiles")
        .select("stripe_customer_id")
        .eq("id", user.user_id)
        .single()
        .execute()
    )
    stripe_customer_id = profile.data.get("stripe_customer_id") if profile.data else None

    if not stripe_customer_id:
        raise HTTPException(
            status_code=404,
            detail="No billing account found. Please subscribe to a plan first.",
        )

    return_url = body.return_url or f"{settings.APP_DOMAIN}/billing"

    portal = sc.billing_portal.sessions.create(params={
        "customer": stripe_customer_id,
        "return_url": return_url,
    })

    return {"portal_url": portal.url}


@router.get("/subscription")
async def get_subscription(
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Return the current user's subscription status and plan."""
    profile = (
        supabase.table("profiles")
        .select("subscription_plan, subscription_status, storage_used_bytes, storage_limit_bytes")
        .eq("id", user.user_id)
        .single()
        .execute()
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    data = profile.data
    plan_key = data.get("subscription_plan", "starter")
    plan_info = PLANS.get(plan_key, PLANS["starter"])

    return {
        "plan": plan_key,
        "plan_name": plan_info["name"],
        "status": data.get("subscription_status", "inactive"),
        "storage_used_bytes": data.get("storage_used_bytes", 0),
        "storage_limit_bytes": data.get("storage_limit_bytes", plan_info["storage_bytes"]),
        "features": plan_info["features"],
    }


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    supabase: Client = Depends(get_supabase),
):
    """
    Stripe webhook endpoint — processes subscription lifecycle events.
    Must be registered in Stripe Dashboard → Developers → Webhooks.
    Endpoint URL: https://api-production-4d522.up.railway.app/billing/webhook
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event["type"]
    data = event["data"]["object"]

    # ── Subscription created / updated ────────────────────────────────────────
    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        subscription = data
        customer_id = subscription.get("customer")
        plan_key = subscription.get("metadata", {}).get("plan", "starter")
        sub_status = subscription.get("status", "inactive")

        plan_info = PLANS.get(plan_key, PLANS["starter"])

        # Map Stripe status to our simplified status
        status_map = {
            "active": "active",
            "trialing": "trialing",
            "past_due": "past_due",
            "canceled": "canceled",
            "unpaid": "past_due",
            "incomplete": "inactive",
            "incomplete_expired": "inactive",
        }
        mapped_status = status_map.get(sub_status, "inactive")

        supabase.table("profiles").update({
            "subscription_plan": plan_key,
            "subscription_status": mapped_status,
            "storage_limit_bytes": plan_info["storage_bytes"],
        }).eq("stripe_customer_id", customer_id).execute()

    # ── Subscription cancelled ────────────────────────────────────────────────
    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        supabase.table("profiles").update({
            "subscription_status": "canceled",
            "subscription_plan": "starter",
            "storage_limit_bytes": PLANS["starter"]["storage_bytes"],
        }).eq("stripe_customer_id", customer_id).execute()

    # ── Checkout completed ────────────────────────────────────────────────────
    elif event_type == "checkout.session.completed":
        session = data
        if session.get("mode") == "subscription":
            user_id = session.get("metadata", {}).get("supabase_user_id")
            plan_key = session.get("metadata", {}).get("plan", "starter")
            customer_id = session.get("customer")

            if user_id:
                plan_info = PLANS.get(plan_key, PLANS["starter"])
                supabase.table("profiles").update({
                    "stripe_customer_id": customer_id,
                    "subscription_plan": plan_key,
                    "subscription_status": "active",
                    "storage_limit_bytes": plan_info["storage_bytes"],
                }).eq("id", user_id).execute()

    # ── Invoice paid ──────────────────────────────────────────────────────────
    elif event_type == "invoice.payment_succeeded":
        customer_id = data.get("customer")
        supabase.table("profiles").update({
            "subscription_status": "active",
        }).eq("stripe_customer_id", customer_id).execute()

    # ── Invoice payment failed ────────────────────────────────────────────────
    elif event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        amount_due = data.get("amount_due", 0)
        invoice_id = data.get("id", "")

        # Update profile status
        supabase.table("profiles").update({
            "subscription_status": "past_due",
        }).eq("stripe_customer_id", customer_id).execute()

        # Look up customer email from Stripe
        try:
            sc = _stripe_client()
            customer = sc.customers.retrieve(customer_id)
            customer_email = customer.get("email", "")
            customer_name = customer.get("name", "")
        except Exception:
            customer_email = ""
            customer_name = ""

        # Notify n8n payment failure workflow
        await _notify_n8n(N8N_PAYMENT_FAILED_WEBHOOK, {
            "stripe_customer_id": customer_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "amount_due": amount_due,
            "invoice_id": invoice_id,
        })

    return {"received": True}
