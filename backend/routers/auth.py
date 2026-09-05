"""
Student Authentication, token issuance, logout, and password change.
"""

import time
import secrets
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException, Depends

try:
    from pymentor.backend import state
    from pymentor.backend.models import LoginRequest, ChangePasswordRequest
    from pymentor.backend.deps import get_current_student
    from pymentor.backend.database import get_connection, verify_password, hash_password, log_event
except ImportError:
    from backend import state
    from backend.models import LoginRequest, ChangePasswordRequest
    from backend.deps import get_current_student
    from backend.database import get_connection, verify_password, hash_password, log_event

logger = logging.getLogger("pymentor")

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/student/login")
def login_student(req: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    section = req.section.strip().upper()
    roll_no = req.roll_no.strip()
    password = req.password.strip()

    # Rate Limiting Check
    rate_key = (roll_no, section)
    now = time.time()

    # Periodic cleanup of expired lockout entries
    if len(state.login_attempts) > 100:
        for k in list(state.login_attempts.keys()):
            if state.login_attempts[k][1] <= now:
                del state.login_attempts[k]

    if rate_key in state.login_attempts:
        failures, locked_until = state.login_attempts[rate_key]
        if now < locked_until:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
        elif now >= locked_until and locked_until > 0:
            # Lockout expired
            state.login_attempts[rate_key] = (0, 0)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, section, roll_no, password, needs_password_change FROM students WHERE roll_no = ? AND section = ?",
        (roll_no, section)
    )
    student = cursor.fetchone()

    if not student or not verify_password(password, student["password"]):
        conn.close()
        # Record failure
        fails = state.login_attempts.get(rate_key, (0, 0))[0] + 1
        lock = now + 300 if fails >= 5 else 0  # 5 minutes lockout after 5 attempts
        state.login_attempts[rate_key] = (fails, lock)
        logger.warning(f"[STUDENT AUTH] Login FAILED: Sec '{section}', Roll '{roll_no}' from IP={client_ip} (Attempt {fails}/5)")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Success, reset failures
    if rate_key in state.login_attempts:
        del state.login_attempts[rate_key]

    # Generate token with expiry (+7 days)
    token = secrets.token_hex(32)
    expires = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO auth_tokens (token, student_id, expires_at) VALUES (?, ?, ?)", (token, student["id"], expires))
    conn.commit()

    needs_password_change = (
        bool(student["needs_password_change"])
        if ("needs_password_change" in student.keys() and student["needs_password_change"] is not None)
        else verify_password("123", student["password"])
    )
    conn.close()

    log_event(student_id=student["id"], event_type="login", event_data={"section": section, "roll_no": roll_no})
    logger.info(f"[STUDENT AUTH] Login SUCCESS: '{student['name']}' (Sec {section}, Roll {roll_no}) from IP={client_ip}")

    return {
        "student_id": student["id"],
        "name": student["name"],
        "roll_no": student["roll_no"],
        "section": student["section"],
        "token": token,
        "needs_password_change": needs_password_change
    }


@router.post("/auth/logout")
def logout(request: Request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        parts = auth.split(" ")
        if len(parts) == 2:
            token = parts[1]
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT student_id FROM auth_tokens WHERE token = ?", (token,))
            row = cursor.fetchone()
            if row:
                log_event(student_id=row["student_id"], event_type="logout")
                logger.info(f"[STUDENT AUTH] Logout: Student ID={row['student_id']}")
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
            conn.commit()
            conn.close()
    return {"message": "Logged out successfully"}


@router.post("/auth/change-password")
def change_password(req: ChangePasswordRequest, student_id: int = Depends(get_current_student)):
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters long")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()

    if not verify_password(req.current_password, student["password"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Incorrect current password")

    hashed = hash_password(req.new_password)
    cursor.execute("UPDATE students SET password = ?, needs_password_change = 0 WHERE id = ?", (hashed, student_id))
    # Security: Revoke all existing auth tokens for this student so old sessions are terminated immediately
    cursor.execute("DELETE FROM auth_tokens WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()

    log_event(student_id=student_id, event_type="password_change")
    logger.info(f"[STUDENT AUTH] Password changed for Student ID={student_id}")

    return {"message": "Password updated successfully. All sessions revoked. Please log in with your new password."}
