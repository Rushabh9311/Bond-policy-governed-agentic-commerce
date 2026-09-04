"""
Rule-based upsell suggestions — deliberately NOT an LLM call. Uses the
frequently_bought_with pairings seeded on each product's agent_metadata.
This is the "grow revenue" half of the pitch, kept just as deterministic
and explainable as the policy engine.
"""
from sqlalchemy.orm import Session

from app import models


def suggest_upsell(product: models.Product, db: Session) -> dict | None:
    pairs = (product.agent_metadata or {}).get("frequently_bought_with", [])
    if not pairs:
        return None

    upsell_id = pairs[0]
    upsell_product = db.query(models.Product).filter(models.Product.id == upsell_id).first()
    if not upsell_product:
        return None

    return {
        "product_id": upsell_product.id,
        "name": upsell_product.name,
        "price_paise": upsell_product.price,
        "reason": f"Frequently bought together with {product.name}.",
    }