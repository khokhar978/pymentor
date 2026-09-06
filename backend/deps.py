"""
Authentication and Authorization Dependencies for PyMentor.
"""

import time
import secrets
import logging
from fastapi import Request, HTTPException, Depends

try:
    from pymentor.backend.config import ADMIN_SECRET
    from pymentor.backend import state
    from pymentor.backend.database import get_connection, verify_password
except ImportError:
    from backend.config import ADMIN_SECRET
    from backend import state
    from backend.database import get_connection, verify_password

logger = logging.getLogger("pymentor")


def get_current_student(request: Request) -> int:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    parts = auth.split(" ")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Malformed Authorization header")
    token = parts[1]

    conn = get_connection()
    cursor = conn.cursor()

    # Opportunistic pruning of expired auth tokens
    if int(time.time()) % 15 == 0:
        try:
            cursor.execute(
                "DELETE FROM auth_tokens WHERE expires_at IS NOT NULL AND expires_at < datetime('now', 'localtime')"
            )
            conn.commit()
        except Exception:
            pass

    cursor.execute(
        "SELECT student_id FROM auth_tokens WHERE token = ? AND (expires_at IS NULL OR expires_at > datetime('now', 'localtime'))",
        (token,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return row["student_id"]


def require_password_changed(student_id: int = Depends(get_current_student)) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT needs_password_change, password FROM students WHERE id = ?", (student_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Student not found")

    needs_change = (
        bool(row["needs_password_change"])
        if ("needs_password_change" in row.keys() and row["needs_password_change"] is not None)
        else verify_password("123", row["password"])
    )
    if needs_change:
        raise HTTPException(
            status_code=403,
            detail="Security notice: Please change your default password in Profile before practicing."
        )
    return student_id


def verify_admin(request: Request) -> bool:
    cf_ip = request.headers.get("CF-Connecting-IP")
    client_ip = cf_ip.strip() if cf_ip else (request.client.host if request.client else "unknown")
    now = time.time()

    # Periodic cleanup of expired lockout entries
    if len(state.admin_attempts) > 50:
        for ip in list(state.admin_attempts.keys()):
            if state.admin_attempts[ip][1] <= now:
                del state.admin_attempts[ip]

    if client_ip in state.admin_attempts:
        failures, locked_until = state.admin_attempts[client_ip]
        if now < locked_until:
            wait_seconds = int(locked_until - now)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed admin attempts. Locked out for {wait_seconds}s."
            )
        elif now >= locked_until and locked_until > 0:
            state.admin_attempts[client_ip] = (0, 0)

    secret = request.headers.get("X-Admin-Secret", "")
    if not secret or not secrets.compare_digest(secret, ADMIN_SECRET):
        fails = state.admin_attempts.get(client_ip, (0, 0))[0] + 1
        lock = now + 900 if fails >= 5 else 0  # 15 minutes lockout after 5 failed attempts
        state.admin_attempts[client_ip] = (fails, lock)
        logger.warning(f"Failed admin authentication attempt from {client_ip} (Attempt {fails}/5)")
        raise HTTPException(status_code=401, detail="Admin unauthorized")

    # Reset failed attempts on success
    if client_ip in state.admin_attempts:
        del state.admin_attempts[client_ip]
    return True
