"""
The buyer agent: reasoning only, never touches money or policy.
Takes a natural-language request + the catalog, returns ONE selected
product with reasoning. Everything after this (policy check, payment)
happens outside this file, deliberately.
"""
import json

from google import genai

from app.config import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)

SYSTEM_PROMPT = """You are a shopping assistant reasoning over a merchant's
product catalog. Given a user's natural-language request and a JSON list of
available products (each with id, name, category, price in paise, stock,
and agent_metadata describing what it's best for), select the SINGLE best
matching product.

Respond with ONLY valid JSON, no markdown formatting, no code fences, in
exactly this shape:
{"product_id": <int>, "reasoning": "<one or two sentences explaining the pick>", "budget_ok": <true or false>}

If the user gave a budget and nothing fits within it, still pick the
closest reasonable match but set "budget_ok" to false."""


def select_product(user_request: str, products: list[dict]) -> dict:
    catalog_text = json.dumps(products, indent=2)
    prompt = f"{SYSTEM_PROMPT}\n\nCatalog:\n{catalog_text}\n\nUser request: {user_request}"

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )

    if not response.text:
        raise ValueError("Gemini returned an empty response — check API key, quota, or safety filters")
    text = response.text.strip()

    # Strip markdown code fences if the model added them anyway
    
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    return json.loads(text)