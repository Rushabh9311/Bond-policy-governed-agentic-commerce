"""
Deterministic policy engine — the ONLY thing authorized to approve a
purchase. Never touched by the LLM. Every decision here is a plain rule
check, not a model call — that's deliberate, and it's the whole point of
this architecture.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models

# pyright: reportGeneralTypeIssues=false


def evaluate_policy(agent_id: str, product: models.Product, db: Session) -> dict:
    checks = []

    policy = db.query(models.AgentPolicy).filter(
        models.AgentPolicy.agent_id == agent_id
    ).first()

    if not policy:
        return {
            "result": "fail",
            "reason": f"No policy found for agent_id '{agent_id}'",
            "checks": [{"check": "agent_policy_exists", "status": "FAIL"}],
        }

    # 1. Expiry

    if policy.expires_at and datetime.now(timezone.utc) > policy.expires_at:
        checks.append({"check": "policy_not_expired", "status": "FAIL"})
        return {"result": "fail", "reason": "Agent's policy has expired", "checks": checks}
    checks.append({"check": "policy_not_expired", "status": "PASS"})

    # 2. Category allowed

    if product.category not in (policy.allowed_categories or []):
        checks.append({"check": "category_allowed", "status": "FAIL"})
        return {
            "result": "fail",
            "reason": f"Category '{product.category}' is not in this agent's allowed categories",
            "checks": checks,
        }
    checks.append({"check": "category_allowed", "status": "PASS"})

    # 3. Daily limit

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    todays_intents = (
        db.query(models.PurchaseIntent)
        .filter(
            models.PurchaseIntent.agent_id == agent_id,
            models.PurchaseIntent.created_at >= today_start,
            models.PurchaseIntent.payment_status == "paid",
        )
        .all()
    )
    spent_today = sum(i.amount for i in todays_intents)

    if spent_today + product.price > policy.daily_limit:
        checks.append({"check": "daily_limit", "status": "FAIL"})
        return {
            "result": "fail",
            "reason": f"Would exceed daily limit (already spent ₹{spent_today/100:.2f} of ₹{policy.daily_limit/100:.2f})",
            "checks": checks,
        }
    checks.append({"check": "daily_limit", "status": "PASS"})

    # 4. Transaction size — three tiers: auto-approve / needs approval / hard block
    
    if product.price > policy.max_transaction:
        checks.append({"check": "transaction_limit", "status": "FAIL"})
        return {
            "result": "fail",
            "reason": f"₹{product.price/100:.2f} exceeds the agent's absolute max of ₹{policy.max_transaction/100:.2f} — never allowed autonomously",
            "checks": checks,
        }

    if product.price > policy.requires_approval_above:
        checks.append({"check": "transaction_limit", "status": "APPROVAL_REQUIRED"})
        return {
            "result": "approval_required",
            "reason": f"₹{product.price/100:.2f} exceeds the auto-approve threshold of ₹{policy.requires_approval_above/100:.2f} — needs human approval",
            "checks": checks,
        }

    checks.append({"check": "transaction_limit", "status": "PASS"})
    return {"result": "pass", "reason": "Within all policy limits — auto-approved", "checks": checks}