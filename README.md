# Bond — Policy-Governed Agentic Commerce

Built for **Razorpay Buildathon Track 01: "AI Growth & Agentic Commerce."**

An AI buyer agent reasons over a merchant's catalog, proposes a purchase, a deterministic policy engine (never the LLM) authorizes or blocks it, and a payment service executes it via Razorpay — with every step logged to an audit trail.

**The core rule, enforced everywhere in the code:**
> The LLM proposes. The policy engine authorizes. The payment service executes.

## How buyers actually use this

Bond is meant to be installed by a **merchant**, like a payment gateway — the buyer never installs anything. They keep using whatever AI agent they already have (ChatGPT, Perplexity, etc.), and it automatically gets Bond's safety rails because the merchant's backend enforces them.

`/agent-page` in this repo is a stand-in "reference buyer agent" for demo purposes.

## Architecture

Three layers, each with one job:

1. **`buyer_agent.py`** — LLM call, reasoning only. Returns `{product_id, reasoning, budget_ok}`. Never touches money or policy.
2. **`policy_engine.py`** — deterministic, no LLM. Checks: policy not expired → category allowed → daily limit → transaction size (auto-approve / needs approval / hard block). Every check is logged for the audit trail.
3. **`razorpay_client.py`** — deterministic execution via Razorpay Orders + Payment Links. Idempotent by design.

## Tech stack

- **Backend:** Python + FastAPI
- **Database:** PostgreSQL via SQLAlchemy
- **LLM:** Google Gemini (`gemini-3.6-flash`) via `google-genai`
- **Payments:** Razorpay test-mode API (Orders + Payment Links)
- **Frontend:** Server-rendered Jinja2 templates, no React — cream/lime/ink design system

## Local setup

```bash
# 1. Start Postgres
docker compose up -d

# 2. Python environment
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt --break-system-packages

# 3. Configure environment
# Create a .env file with:
#   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/agentic_commerce
#   RAZORPAY_KEY_ID=your_test_key_id
#   RAZORPAY_KEY_SECRET=your_test_key_secret
#   GEMINI_API_KEY=your_gemini_key
#   BASE_URL=http://localhost:8000

# 4. Seed the database
python -m app.seed

# 5. Run
uvicorn app.main:app --reload
```

Visit `http://localhost:8000` — it redirects to `/agent-page`, the main demo screen.

## Resetting demo data

To reset the database entirely (products + policy + history):
```bash
docker compose down -v && docker compose up -d && python -m app.seed
```

To just clear purchase history between rehearsals (keeps catalog + policy), click **"Clear history"** on the `/audit` page.

## Test credentials

| Card | Behavior |
|---|---|
| `4100 2800 0000 1007` | Success |
| `4000 0000 0000 0341` | Decline (for the failure demo) |

Any future expiry date, any CVV, any 4+ digit OTP.

## Key pages

| Route | Purpose |
|---|---|
| `/agent-page` | Main demo screen — ask the agent to buy something |
| `/catalog-page` | Full agent-readable product catalog |
| `/audit` | Every purchase intent, with a full explainable event timeline |
| `/dashboard` | Merchant revenue/conversion/trust metrics |
| `/policy-settings` | Adjust the agent's spending guardrails |

## The standout feature: failure/recovery

A payment can succeed while order creation fails (simulated via `simulate_order_failure=true`). The payment is never touched again; `/retry-order` recovers idempotently. This mirrors a retry/DLQ pattern for resilient event processing.

---
