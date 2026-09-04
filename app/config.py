import os
from dotenv import load_dotenv

load_dotenv()


class Settings:

    # Postgres connection — matches the docker-compose service we'll add next

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/agentic_commerce",
    )

    # Razorpay TEST MODE keys — from Razorpay Dashboard > Settings > API Keys
    # (make sure the "Test Mode" toggle is ON before generating keys)

    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")

    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Used to build the Razorpay Payment Link callback_url so the buyer's
    # browser gets redirected back to us after paying. For local dev this
    # is just http://localhost:8000 — Razorpay redirects the BROWSER, not
    # our server, so this works fine without ngrok/a public URL.

    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")


settings = Settings()