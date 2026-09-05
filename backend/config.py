"""
Configuration and Environment Settings for PyMentor.
"""

import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger("pymentor")

# Base paths
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
ENV_PATH = os.path.join(BASE_DIR, ".env")
LOG_FILE_PATH = os.path.join(BASE_DIR, "logs.txt")

# Load environment variables
load_dotenv(dotenv_path=ENV_PATH)
load_dotenv()

# Admin Secret Verification (Fail-Closed)
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()
if not ADMIN_SECRET or ADMIN_SECRET == "default-admin-secret-change-me":
    logger.critical(
        "CRITICAL: ADMIN_SECRET is not configured or still set to default placeholder in .env. "
        "Application refusing to start to prevent unauthenticated admin takeover."
    )
    raise SystemExit(
        "CRITICAL: ADMIN_SECRET must be set in .env to a non-default secret phrase. "
        "Application refusing to start."
    )

# CORS Origins & Regex
raw_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
if raw_origins:
    ALLOWED_ORIGINS = [o.strip() for o in raw_origins.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = [
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ]

ALLOWED_ORIGIN_REGEX = (
    r"^https?://(localhost|127\.0\.0\.1|"
    r"192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|"
    r".*\.trycloudflare\.com|.*\.ngrok-free\.app|.*\.loca\.lt)(:\d+)?$"
)

# Operational parameters
SUBMIT_COOLDOWN_SECONDS = 3.0
