"""
FastAPI backend for Python Practice platform.
Initializes application, registers middleware, mounts static assets, and includes modular API routers.
"""

import os
import time
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

try:
    from pymentor.backend import config, state
    from pymentor.backend.database import init_db
    from pymentor.backend.routers import pages, content, auth, session, telemetry, admin
except ImportError:
    from backend import config, state
    from backend.database import init_db
    from backend.routers import pages, content, auth, session, telemetry, admin

# Configure basic file logging to logs.txt
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pymentor")


# Mute repetitive admin heartbeat polling from access logs
class AdminHeartbeatFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/admin/dashboard" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(AdminHeartbeatFilter())

# Initialize database schema and seeds
init_db()

# Create FastAPI application
app = FastAPI(
    title="Python Practice API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

# Configure CORS - Restrict methods, headers, and origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=config.ALLOWED_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Secret"],
)


@app.middleware("http")
async def track_requests_and_add_headers(request: Request, call_next):
    state.request_times.append(time.time())
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

    # Safari (macOS / iOS) does not support 'credentialless' and requires 'require-corp'
    # to enable cross-origin isolation and SharedArrayBuffer for interactive input().
    # Chromium and Firefox fully support 'credentialless'.
    ua = request.headers.get("user-agent", "")
    is_safari = "Safari" in ua and not any(b in ua for b in ["Chrome", "Chromium", "Edg", "Firefox", "OPR"])
    if is_safari:
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    else:
        response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers
        )
    logger.error(f"Unhandled server exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."}
    )


# Mount static assets
if os.path.exists(config.FRONTEND_DIR):
    css_dir = os.path.join(config.FRONTEND_DIR, "css")
    js_dir = os.path.join(config.FRONTEND_DIR, "js")
    if os.path.exists(css_dir):
        app.mount("/css", StaticFiles(directory=css_dir), name="css")
    if os.path.exists(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")


# Include all modular routers
app.include_router(pages.router)
app.include_router(content.router)
app.include_router(auth.router)
app.include_router(session.router)
app.include_router(telemetry.router)
app.include_router(admin.router)

# Backward-compatibility aliases for existing imports
ADMIN_SECRET = config.ADMIN_SECRET
FRONTEND_DIR = config.FRONTEND_DIR
SUBMIT_COOLDOWN_SECONDS = config.SUBMIT_COOLDOWN_SECONDS
login_attempts = state.login_attempts
admin_attempts = state.admin_attempts
submit_cooldowns = state.submit_cooldowns
request_times = state.request_times
