# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app import buyer_agent, policy_engine, upsell
from app.config import settings
from app.database import Base, engine, get_db
from app import models, razorpay_client
import json
import uuid

app = FastAPI(title="Policy-Governed Agentic Commerce")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Product/category -> image filename. Mirrors the same mapping used in
# catalog.html so JSON responses (e.g. /agent/request) can include an
# image_url too. Keep both in sync if you add a new product image.

PRODUCT_IMAGES = {
    'Mechanical Keyboard - Red Switch': 'product-mechanical-keyboard-red-switch.png',
    'Ergonomic Wrist Rest': 'product-ergonomic-wrist-rest.png',
    'Budget Wired Headphones': 'product-budget-wired-headphones.png',
    'Laptop Carrying Case': 'product-laptop-carrying-case.png',
    'USB-C Hub 7-in-1': 'product-usbc-hub.png',
    'Desk Mat XL': 'product-desk-mat-xl.png',
    'Webcam 1080p': 'product-webcam-1080p.png',
}
CATEGORY_IMAGES = {
    'keyboards': 'product-keyboards.png', 'accessories': 'product-accessories.png',
    'audio': 'product-audio.png', 'laptops': 'product-laptops.png',
    'storage': 'product-storage.png', 'displays': 'product-displays.png',
    'furniture': 'product-furniture.png',
}

def get_product_image_url(product: models.Product) -> str:
    filename = PRODUCT_IMAGES.get(product.name, CATEGORY_IMAGES.get(product.category, 'product-accessories.png'))
    return f"/static/images/{filename}"

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return RedirectResponse(url="/agent-page")

@app.get("/health")
def health():
    return {"status": "ok"}

# Merchant 

class MerchantCreate(BaseModel):
    name: str

@app.post("/merchants")
def create_merchant(payload: MerchantCreate, db: Session = Depends(get_db)):
    merchant = models.Merchant(name=payload.name)
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return {"id": merchant.id, "name": merchant.name}

@app.get("/merchants")
def list_merchants(db: Session = Depends(get_db)):
    return db.query(models.Merchant).all()

# Catalog 

@app.get("/catalog")
def list_catalog(category: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Product)
    if category:
        query = query.filter(models.Product.category == category)
    return query.all()

@app.get("/catalog/search")
def search_catalog(q: str, max_price_paise: int | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Product).filter(models.Product.name.ilike(f"%{q}%"))
    if max_price_paise:
        query = query.filter(models.Product.price <= max_price_paise)
    return query.all()

@app.get("/catalog/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.get("/catalog-page")
def catalog_page(request: Request, db: Session = Depends(get_db)):
    products = db.query(models.Product).all()
    return templates.TemplateResponse(
        request, "catalog.html", {"products": products}
    )

@app.get("/agent-page")
def agent_page(request: Request):
    return templates.TemplateResponse(request, "agent.html", {})

# Buyer agent + policy engine + upsell 

class AgentRequestBody(BaseModel):
    agent_id: str = "buyer_agent_1"
    user_request: str

class PolicyUpdateBody(BaseModel):
    max_transaction_rupees: int
    daily_limit_rupees: int
    approval_threshold_rupees: int
    allowed_categories: list[str]

def _policy_context(policy: models.AgentPolicy, db: Session) -> dict:
    """Shared context builder for the policy settings page."""
    categories = [category[0] for category in db.query(models.Product.category).distinct().order_by(models.Product.category).all()]
    return {"policy": policy, "categories": categories}

@app.get("/policy-settings")
def policy_settings_page(request: Request, db: Session = Depends(get_db)):
    policy = db.query(models.AgentPolicy).filter(models.AgentPolicy.agent_id == "buyer_agent_1").first()
    if not policy:
        raise HTTPException(status_code=404, detail="Buyer agent policy not found")
    return templates.TemplateResponse(request, "policy_settings.html", _policy_context(policy, db))

@app.post("/policy-settings")
def update_policy_settings(payload: PolicyUpdateBody, db: Session = Depends(get_db)):
    """Lets a merchant adjust the buyer agent's spending guardrails live."""
    if min(payload.max_transaction_rupees, payload.daily_limit_rupees, payload.approval_threshold_rupees) <= 0:
        raise HTTPException(status_code=422, detail="All spending limits must be greater than ₹0")
    if payload.approval_threshold_rupees > payload.max_transaction_rupees:
        raise HTTPException(status_code=422, detail="The approval threshold cannot be higher than the hard transaction limit")
    if not payload.allowed_categories:
        raise HTTPException(status_code=422, detail="Select at least one category the agent can buy from")

    policy = db.query(models.AgentPolicy).filter(models.AgentPolicy.agent_id == "buyer_agent_1").first()
    if not policy:
        raise HTTPException(status_code=404, detail="Buyer agent policy not found")

    policy.max_transaction = payload.max_transaction_rupees * 100
    policy.daily_limit = payload.daily_limit_rupees * 100
    policy.requires_approval_above = payload.approval_threshold_rupees * 100
    policy.allowed_categories = payload.allowed_categories
    db.add(models.AuditEvent(
        event_type="POLICY_UPDATED",
        actor="merchant",
        payload={
            "agent_id": policy.agent_id,
            "max_transaction_rupees": payload.max_transaction_rupees,
            "daily_limit_rupees": payload.daily_limit_rupees,
            "approval_threshold_rupees": payload.approval_threshold_rupees,
            "allowed_categories": payload.allowed_categories,
        },
    ))
    db.commit()

    return {"message": "Policy saved. New agent requests will use these rules."}

@app.post("/agent/request")
def agent_request(payload: AgentRequestBody, db: Session = Depends(get_db)):
    """Core flow: buyer agent reasons over the catalog and picks a
    product -> policy engine authorizes it -> an upsell is suggested
    if the purchase wasn't blocked. Every step is written to the audit
    trail as it happens."""
    products = db.query(models.Product).all()
    catalog = [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "price": p.price,
            "stock": p.stock,
            "agent_metadata": p.agent_metadata,
        }
        for p in products
    ]

    try:
        result = buyer_agent.select_product(payload.user_request, catalog)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"Agent could not select a product: {exc}") from exc
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="The AI provider could not complete the request. Check the Gemini API key, quota, and server logs, then try again.",
        )
    product = db.query(models.Product).filter(models.Product.id == result["product_id"]).first()

    if not product:
        raise HTTPException(status_code=500, detail="Agent selected an invalid product_id")

    intent = models.PurchaseIntent(
        agent_id=payload.agent_id,
        user_request=payload.user_request,
        product_id=product.id,
        amount=product.price,
        reason=result["reasoning"],
        policy_result="pending",
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)

    db.add(models.AuditEvent(
        intent_id=intent.id, event_type="PRODUCT_SELECTED",
        actor="buyer_agent", payload=result,
    ))
    db.commit()

    policy_outcome = policy_engine.evaluate_policy(payload.agent_id, product, db)

    intent.policy_result = policy_outcome["result"]
    intent.approval_status = "pending" if policy_outcome["result"] == "approval_required" else "not_required"
    db.commit()

    db.add(models.AuditEvent(
        intent_id=intent.id, event_type="POLICY_CHECK",
        actor="policy_engine", payload=policy_outcome,
    ))
    db.commit()

    upsell_suggestion = None
    if policy_outcome["result"] != "fail":
        upsell_suggestion = upsell.suggest_upsell(product, db)
        if upsell_suggestion:
            db.add(models.AuditEvent(
                intent_id=intent.id, event_type="UPSELL_SUGGESTED",
                actor="upsell_engine", payload=upsell_suggestion,
            ))
            db.commit()

    return {
        "intent_id": intent.id,
        "product": {
            "id": product.id,
            "name": product.name,
            "price_paise": product.price,
            "image_url": get_product_image_url(product),
        },
        "reasoning": result["reasoning"],
        "policy_result": policy_outcome["result"],
        "policy_reason": policy_outcome["reason"],
        "approval_status": intent.approval_status,
        "upsell": upsell_suggestion,
    }

@app.post("/intents/{intent_id}/upsell/accept")
def accept_upsell(intent_id: int, db: Session = Depends(get_db)):
    """Turns an accepted upsell suggestion into its own policy-checked
    purchase intent, linked back to the original via an audit event."""
    original = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not original:
        raise HTTPException(status_code=404, detail="Original intent not found")

    original_product = db.query(models.Product).filter(models.Product.id == original.product_id).first()
    suggestion = upsell.suggest_upsell(original_product, db)
    if not suggestion:
        raise HTTPException(status_code=400, detail="No upsell available for this intent")

    upsell_product = db.query(models.Product).filter(models.Product.id == suggestion["product_id"]).first()
    if not upsell_product:
        raise HTTPException(status_code=500, detail="Upsell product referenced by suggestion no longer exists")

    new_intent = models.PurchaseIntent(
        agent_id=original.agent_id,
        user_request=f"Upsell: bundled with intent #{intent_id}",
        product_id=upsell_product.id,
        amount=upsell_product.price,
        reason=suggestion["reason"],
        policy_result="pending",
    )
    db.add(new_intent)
    db.commit()
    db.refresh(new_intent)

    policy_outcome = policy_engine.evaluate_policy(original.agent_id, upsell_product, db)
    new_intent.policy_result = policy_outcome["result"]
    new_intent.approval_status = "pending" if policy_outcome["result"] == "approval_required" else "not_required"
    db.commit()

    db.add(models.AuditEvent(
        intent_id=intent_id, event_type="UPSELL_ACCEPTED",
        actor="human", payload={"new_intent_id": new_intent.id},
    ))
    db.add(models.AuditEvent(
        intent_id=new_intent.id, event_type="POLICY_CHECK",
        actor="policy_engine", payload=policy_outcome,
    ))
    db.commit()

    return {
        "intent_id": new_intent.id,
        "product": {"id": upsell_product.id, "name": upsell_product.name, "price_paise": upsell_product.price},
        "reasoning": suggestion["reason"],
        "policy_result": policy_outcome["result"],
        "policy_reason": policy_outcome["reason"],
        "approval_status": new_intent.approval_status,
        "upsell": None,
    }

def _event_tone(event_type: str, payload: dict) -> str:
    """Maps an event to a visual tone for the audit trail UI."""
    if event_type in ("ORDER_CREATION_FAILED", "APPROVAL_REJECTED"):
        return "fail"
    if event_type == "POLICY_CHECK":
        result = (payload or {}).get("result")
        return {"pass": "pass", "fail": "fail", "approval_required": "approval"}.get(result, "info")
    if event_type in ("PAYMENT_CAPTURED", "ORDER_CREATED", "ORDER_RETRY_SUCCESS", "APPROVAL_GRANTED"):
        return "pass"
    return "info"

@app.post("/admin/reset-demo-data")
def reset_demo_data(db: Session = Depends(get_db)):
    """Wipes all purchase/payment history for demo rehearsals. Catalog
    and policy are left untouched. Doesn't touch Razorpay's side —
    old test-mode payment links there are simply left unused."""
    db.query(models.AuditEvent).delete()
    db.query(models.Order).delete()
    db.query(models.PaymentIntent).delete()
    db.query(models.PurchaseIntent).delete()
    db.commit()
    return {"message": "All purchase history cleared. Catalog and policy are untouched."}

@app.get("/audit")
def audit_list_page(request: Request, db: Session = Depends(get_db)):
    intents = db.query(models.PurchaseIntent).order_by(models.PurchaseIntent.created_at.desc()).all()
    return templates.TemplateResponse(request, "audit_list.html", {"intents": intents})

@app.get("/audit/{intent_id}")
def audit_detail_page(intent_id: int, request: Request, db: Session = Depends(get_db)):
    intent = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    raw_events = (
        db.query(models.AuditEvent)
        .filter(models.AuditEvent.intent_id == intent_id)
        .order_by(models.AuditEvent.timestamp)
        .all()
    )
    events = [
        {
            "event_type": e.event_type,
            "actor": e.actor,
            "timestamp": e.timestamp,
            "tone": _event_tone(e.event_type, e.payload),
            "payload_json": json.dumps(e.payload, indent=2) if e.payload else "",
        }
        for e in raw_events
    ]
    return templates.TemplateResponse(request, "audit_detail.html", {"intent": intent, "events": events})

@app.get("/dashboard")
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    all_intents = db.query(models.PurchaseIntent).all()
    paid_intents = [i for i in all_intents if i.payment_status == "paid"]

    total_intents = len(all_intents)
    ai_orders = len(paid_intents)
    conversion = (ai_orders / total_intents * 100) if total_intents else 0
    ai_revenue = sum(i.amount for i in paid_intents)
    aov = (ai_revenue / ai_orders) if ai_orders else 0

    pass_count = sum(1 for i in all_intents if i.policy_result == "pass")
    approval_count = sum(1 for i in all_intents if i.policy_result == "approval_required")
    fail_count = sum(1 for i in all_intents if i.policy_result == "fail")

    upsell_suggested = db.query(models.AuditEvent).filter(models.AuditEvent.event_type == "UPSELL_SUGGESTED").count()
    upsell_accepted = db.query(models.AuditEvent).filter(models.AuditEvent.event_type == "UPSELL_ACCEPTED").count()

    category_revenue: dict[str, int] = {}
    for i in paid_intents:
        product = db.query(models.Product).filter(models.Product.id == i.product_id).first()
        if product:
            category_revenue[product.category] = category_revenue.get(product.category, 0) + i.amount

    max_category_revenue = max(category_revenue.values()) if category_revenue else 1
    top_category = max(category_revenue, key=category_revenue.get) if category_revenue else "keyboards"

    return templates.TemplateResponse(request, "dashboard.html", {
        "ai_orders": ai_orders,
        "conversion": round(conversion, 1),
        "ai_revenue": ai_revenue,
        "aov": aov,
        "pass_count": pass_count,
        "approval_count": approval_count,
        "fail_count": fail_count,
        "upsell_suggested": upsell_suggested,
        "upsell_accepted": upsell_accepted,
        "category_revenue": category_revenue,
        "max_category_revenue": max_category_revenue,
        "top_category": top_category,
    })

@app.get("/intents/{intent_id}")
def get_intent(intent_id: int, db: Session = Depends(get_db)):
    intent = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    return {
        "id": intent.id,
        "agent_id": intent.agent_id,
        "user_request": intent.user_request,
        "product_id": intent.product_id,
        "amount_paise": intent.amount,
        "reason": intent.reason,
        "policy_result": intent.policy_result,
        "approval_status": intent.approval_status,
        "payment_status": intent.payment_status,
    }

@app.post("/intents/{intent_id}/approve")
def approve_intent(intent_id: int, db: Session = Depends(get_db)):
    intent = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    if intent.policy_result != "approval_required":
        raise HTTPException(status_code=400, detail="This intent doesn't require approval")

    intent.approval_status = "approved"
    db.commit()

    db.add(models.AuditEvent(
        intent_id=intent.id, event_type="APPROVAL_GRANTED",
        actor="human", payload={"note": "Manually approved via /intents/{id}/approve"},
    ))
    db.commit()
    return {"intent_id": intent.id, "approval_status": intent.approval_status}

@app.post("/intents/{intent_id}/reject")
def reject_intent(intent_id: int, db: Session = Depends(get_db)):
    intent = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    if intent.policy_result != "approval_required":
        raise HTTPException(status_code=400, detail="This intent doesn't require approval")

    intent.approval_status = "rejected"
    db.commit()

    db.add(models.AuditEvent(
        intent_id=intent.id, event_type="APPROVAL_REJECTED",
        actor="human", payload={"note": "Manually rejected via /intents/{id}/reject"},
    ))
    db.commit()
    return {"intent_id": intent.id, "approval_status": intent.approval_status}

# Payment 

def _create_order_record(intent_id: int, razorpay_payment_id: str, db: Session, simulate_failure: bool = False):
    """Split out on its own because this is the exact step the failure
    demo targets — in a real system this might call a fulfillment
    service that can genuinely go down even after payment succeeds."""
    if simulate_failure:
        raise RuntimeError("Simulated fulfillment service outage — order creation failed")

    order = models.Order(
        intent_id=intent_id,
        razorpay_payment_id=razorpay_payment_id,
        status="created",
    )
    db.add(order)
    db.commit()
    return order

@app.post("/intents/{intent_id}/pay")
def pay_intent(intent_id: int, db: Session = Depends(get_db)):
    intent = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    allowed = intent.policy_result == "pass" or (
        intent.policy_result == "approval_required" and intent.approval_status == "approved"
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot pay — policy_result={intent.policy_result}, approval_status={intent.approval_status}",
        )

    existing = db.query(models.PaymentIntent).filter(models.PaymentIntent.intent_id == intent_id).first()
    if existing:
        return {
            "intent_id": intent_id,
            "razorpay_order_id": existing.razorpay_order_id,
            "status": existing.status,
            "note": "Payment already initiated for this intent — returning the existing link, not creating a duplicate.",
        }

    product = db.query(models.Product).filter(models.Product.id == intent.product_id).first()
    if not product:
        raise HTTPException(status_code=500, detail="Product referenced by this intent no longer exists")

    # reference_id must be unique across the whole Razorpay test account
    # forever — it isn't reset by a local reseed, so a bare intent_id
    # can collide with an old test run. Random suffix avoids that; local
    # idempotency is still handled above via the `existing` lookup.
    unique_ref = f"intent_{intent_id}_{uuid.uuid4().hex[:8]}"

    order = razorpay_client.create_order(amount_paise=intent.amount, receipt=unique_ref)
    link = razorpay_client.create_payment_link(
        amount_paise=intent.amount,
        description=f"{product.name} (auto-purchased by agent)",
        reference_id=unique_ref,
        notes={"intent_id": str(intent_id)},
        callback_url=f"{settings.BASE_URL}/payment-return",
    )

    payment_intent = models.PaymentIntent(
        intent_id=intent_id,
        razorpay_order_id=order["id"],
        razorpay_payment_link_id=link["id"],
        status="created",
    )
    db.add(payment_intent)
    db.commit()

    db.add(models.AuditEvent(
        intent_id=intent_id, event_type="PAYMENT_LINK_CREATED",
        actor="payment_service",
        payload={"razorpay_order_id": order["id"], "payment_link": link["short_url"]},
    ))
    db.commit()

    return {
        "intent_id": intent_id,
        "razorpay_order_id": order["id"],
        "payment_link": link["short_url"],
        "status": "created",
    }

def _confirm_payment_internal(
    intent_id: int,
    razorpay_payment_id: str,
    db: Session,
    actor: str = "webhook",
    simulate_order_failure: bool = False,
) -> dict:
    """Shared 'a payment came in for this intent' logic — called from the
    manual endpoint (used for the simulated-failure demo) and from the
    real browser-redirect route below. Idempotent: an already-paid
    intent is not re-processed."""
    intent = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    payment_intent = db.query(models.PaymentIntent).filter(models.PaymentIntent.intent_id == intent_id).first()
    if not payment_intent:
        raise HTTPException(status_code=400, detail="No payment was ever initiated for this intent")

    if intent.payment_status == "paid":
        existing_order = db.query(models.Order).filter(
            models.Order.intent_id == intent_id, models.Order.status == "created"
        ).first()
        return {
            "intent_id": intent_id,
            "payment_status": "paid",
            "order_status": "created" if existing_order else "failed",
            "note": "Already confirmed — not re-processing.",
        }

    payment_intent.status = "captured"
    intent.payment_status = "paid"
    db.commit()

    db.add(models.AuditEvent(
        intent_id=intent_id, event_type="PAYMENT_CAPTURED",
        actor=actor, payload={"razorpay_payment_id": razorpay_payment_id},
    ))
    db.commit()

    try:
        order = _create_order_record(intent_id, razorpay_payment_id, db, simulate_failure=simulate_order_failure)
        db.add(models.AuditEvent(
            intent_id=intent_id, event_type="ORDER_CREATED",
            actor="order_service", payload={"order_id": order.id},
        ))
        db.commit()
        return {"intent_id": intent_id, "payment_status": "paid", "order_status": "created"}

    except RuntimeError as e:
        failed_order = models.Order(intent_id=intent_id, razorpay_payment_id=razorpay_payment_id, status="failed")
        db.add(failed_order)
        db.commit()

        db.add(models.AuditEvent(
            intent_id=intent_id, event_type="ORDER_CREATION_FAILED",
            actor="order_service", payload={"error": str(e)},
        ))
        db.commit()

        return {
            "intent_id": intent_id,
            "payment_status": "paid",
            "order_status": "failed",
            "note": "Payment succeeded and was NOT touched. Order creation failed — call /intents/{id}/retry-order to recover.",
        }

@app.post("/intents/{intent_id}/confirm-payment")
def confirm_payment(intent_id: int, razorpay_payment_id: str, simulate_order_failure: bool = False, db: Session = Depends(get_db)):
    """Manual trigger, kept for the deliberate-failure demo. Real
    payments confirm automatically via /payment-return instead."""
    return _confirm_payment_internal(
        intent_id, razorpay_payment_id, db, actor="webhook", simulate_order_failure=simulate_order_failure
    )

@app.get("/payment-return")
def payment_return(
    razorpay_payment_id: str,
    razorpay_payment_link_id: str,
    razorpay_payment_link_reference_id: str,
    razorpay_payment_link_status: str,
    razorpay_signature: str,
    db: Session = Depends(get_db),
):
    """Razorpay redirects the buyer's browser here after they pay via the
    hosted Payment Link (callback_url set in /pay). Browser redirect, not
    a server-to-server webhook — so nothing needs to be publicly reachable."""
    valid = razorpay_client.verify_payment_link_signature({
        "payment_link_id": razorpay_payment_link_id,
        "payment_link_reference_id": razorpay_payment_link_reference_id,
        "payment_link_status": razorpay_payment_link_status,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature,
    })

    if not valid or razorpay_payment_link_status != "paid":
        return HTMLResponse("""
            <html><body style="font-family:sans-serif;text-align:center;padding:60px;">
            <h2>⚠️ Payment could not be verified</h2>
            <p>You can close this tab and check the audit trail for details.</p>
            </body></html>
        """, status_code=400)

    # reference_id is "intent_{id}_{random suffix}" — see /pay
    intent_id = int(razorpay_payment_link_reference_id.split("_")[1])
    result = _confirm_payment_internal(intent_id, razorpay_payment_id, db, actor="payment_link_redirect")

    return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;text-align:center;padding:60px;">
        <h2>✅ Payment confirmed</h2>
        <p>Order status: {result.get('order_status')}. You can close this tab.</p>
        <script>
          if (window.opener) {{
            window.opener.postMessage(
              {{ type: 'bond-payment-confirmed', intent_id: {intent_id}, order_status: '{result.get("order_status")}' }},
              '*'
            );
          }}
          setTimeout(() => window.close(), 1500);
        </script>
        </body></html>
    """)

@app.post("/intents/{intent_id}/retry-order")
def retry_order(intent_id: int, db: Session = Depends(get_db)):
    existing_success = (
        db.query(models.Order)
        .filter(models.Order.intent_id == intent_id, models.Order.status == "created")
        .first()
    )
    if existing_success:
        return {"intent_id": intent_id, "order_status": "created", "note": "Order already exists — not retrying."}

    intent = db.query(models.PurchaseIntent).filter(models.PurchaseIntent.id == intent_id).first()
    if not intent or intent.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Cannot retry order — payment was never confirmed for this intent")

    payment_intent = db.query(models.PaymentIntent).filter(models.PaymentIntent.intent_id == intent_id).first()
    if not payment_intent:
        raise HTTPException(status_code=400, detail="No payment record exists for this intent — call /pay first")

    order = _create_order_record(intent_id, payment_intent.razorpay_order_id, db, simulate_failure=False)

    db.add(models.AuditEvent(
        intent_id=intent_id, event_type="ORDER_RETRY_SUCCESS",
        actor="order_service", payload={"order_id": order.id},
    ))
    db.commit()

    return {"intent_id": intent_id, "order_status": "created", "note": "Retry succeeded — recovered from the earlier failure."}

# Debug: proves the Razorpay integration works 

class TestOrderRequest(BaseModel):
    amount_rupees: float
    description: str = "Test order — Day 1 integration check"

@app.post("/_debug/razorpay-test-order")
def razorpay_test_order(payload: TestOrderRequest):
    amount_paise = int(payload.amount_rupees * 100)
    try:
        order = razorpay_client.create_order(
            amount_paise=amount_paise, receipt="debug_test_1"
        )
        link = razorpay_client.create_payment_link(
            amount_paise=amount_paise,
            description=payload.description,
            reference_id="debug_test_1",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Razorpay call failed: {e}")

    return {
        "order_id": order["id"],
        "payment_link": link["short_url"],
        "note": "Open payment_link in a browser and pay with test card "
        "4100 2800 0000 1007 to confirm the whole flow works end to end.",
    }