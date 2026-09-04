from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
    ARRAY,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    products = relationship("Product", back_populates="merchant")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)

    # Amounts stored in paise (smallest INR unit) — matches Razorpay's convention.
    # e.g. ₹1,799 is stored as 179900.
    
    price = Column(Integer, nullable=False)
    stock = Column(Integer, default=0)

    # Agent-readable metadata: best_for, not_ideal_for, compatible_with, etc.

    # We'll design the actual shape of this on Days 3-4.

    agent_metadata = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    merchant = relationship("Merchant", back_populates="products")


class AgentPolicy(Base):
    """Bounded financial identity for an AI buyer agent. Deterministic —
    never touched by the LLM, only read by the policy engine."""

    __tablename__ = "agent_policies"

    agent_id = Column(String, primary_key=True)
    max_transaction = Column(Integer, nullable=False)  # paise
    daily_limit = Column(Integer, nullable=False)  # paise
    allowed_categories = Column(ARRAY(String), default=list)
    requires_approval_above = Column(Integer, nullable=False)  # paise
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PurchaseIntent(Base):
    """The core record: what the agent wants to buy, why, and what the
    policy engine decided. This is the spine of the audit trail."""

    __tablename__ = "purchase_intents"

    id = Column(Integer, primary_key=True)
    agent_id = Column(String, ForeignKey("agent_policies.agent_id"), nullable=False)
    user_request = Column(Text, nullable=False)  # raw natural-language request
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    amount = Column(Integer, nullable=False)  # paise
    reason = Column(Text)  # LLM's stated reasoning for this pick

    # pass / fail / approval_required

    policy_result = Column(String, nullable=False, default="pending")

    # not_required / pending / approved / rejected

    approval_status = Column(String, nullable=False, default="not_required")

    # pending / paid / failed

    payment_status = Column(String, nullable=False, default="pending")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product")


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id = Column(Integer, primary_key=True)
    intent_id = Column(Integer, ForeignKey("purchase_intents.id"), nullable=False)
    razorpay_order_id = Column(String, nullable=True)
    razorpay_payment_link_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    intent_id = Column(Integer, ForeignKey("purchase_intents.id"), nullable=False)
    razorpay_payment_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    """Append-only event log. Every meaningful thing that happens gets a
    row here — this is what powers the 'why did it spend this' view."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    intent_id = Column(Integer, ForeignKey("purchase_intents.id"), nullable=True)
    event_type = Column(String, nullable=False)  # e.g. POLICY_CHECK, PAYMENT_SUCCESS
    actor = Column(String, nullable=False)  # e.g. buyer_agent, policy_engine, webhook
    payload = Column(JSONB, default=dict)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())