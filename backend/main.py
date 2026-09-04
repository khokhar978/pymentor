"""
FastAPI backend for Python Practice platform.
Serves REST API and multi-page frontend.
"""

import os
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from pymentor.backend.database import get_connection, init_db, verify_password, hash_password
from pymentor.backend.ai_mentor import evaluate_code, simulate_run, FALLBACK_MODELS, get_api_key

init_db()

app = FastAPI(title="Python Practice API", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

# Configure basic file logging to logs.txt
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs.txt")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pymentor")

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "default-admin-secret-change-me")

# Rate limiting dictionary: (roll_no, section) -> (failed_attempts, locked_until)
login_attempts = {}


# ─────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────
def get_current_student(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    parts = auth.split(" ")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Malformed Authorization header")
    token = parts[1]
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT student_id FROM auth_tokens WHERE token = ? AND (expires_at IS NULL OR expires_at > datetime('now'))",
        (token,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return row["student_id"]

def verify_admin(request: Request):
    secret = request.headers.get("X-Admin-Secret")
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Admin unauthorized")
    return True


# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────
class LoginRequest(BaseModel):
    section: str
    roll_no: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class SessionStartRequest(BaseModel):
    problem_id: int
    help_level: Optional[int] = 1

class SessionSaveRequest(BaseModel):
    session_id: int
    code: str

class RunCodeRequest(BaseModel):
    session_id: int
    code: str

class SubmitCodeRequest(BaseModel):
    session_id: int
    code: str
    help_level: Optional[int] = 1
    simulated_output: Optional[str] = None

class SetKeyRequest(BaseModel):
    api_key: str


# ─────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/api/status")
def get_status(admin: bool = Depends(verify_admin)):
    has_key = bool(get_api_key())
    masked_key = ""
    if has_key:
        key = get_api_key()
        masked_key = key[:4] + "..." + key[-4:] if len(key) > 8 else "***"
    return {
        "status": "online",
        "has_api_key": has_key,
        "masked_key": masked_key,
        "fallback_models": FALLBACK_MODELS
    }

@app.post("/api/config/key")
def set_api_key(req: SetKeyRequest, admin: bool = Depends(verify_admin)):
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    os.environ["GEMINI_API_KEY"] = key
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"GEMINI_API_KEY={key}\n")
    return {"message": "API Key saved successfully!", "has_api_key": True}

@app.get("/api/topics")
def get_topics():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, topic, title, difficulty, concepts
    FROM problems
    ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    topics_dict = {}
    for r in rows:
        t = r["topic"]
        if t not in topics_dict:
            topics_dict[t] = []
        topics_dict[t].append({
            "id": r["id"],
            "title": r["title"],
            "difficulty": r["difficulty"],
            "concepts": json.loads(r["concepts"]) if r["concepts"] else []
        })

    result = [{"topic": k, "problems": v} for k, v in topics_dict.items()]
    return {"topics": result}

@app.get("/api/problems/{problem_id}")
def get_problem(problem_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, topic, title, difficulty, description, sample_input, sample_output, concepts, starter_code
    FROM problems
    WHERE id = ?
    """, (problem_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Problem not found")

    return {
        "id": row["id"],
        "topic": row["topic"],
        "title": row["title"],
        "difficulty": row["difficulty"],
        "description": row["description"],
        "sample_input": row["sample_input"],
        "sample_output": row["sample_output"],
        "concepts": json.loads(row["concepts"]) if row["concepts"] else [],
        "starter_code": row["starter_code"] or ""
    }

@app.post("/api/student/login")
def login_student(req: LoginRequest):
    section = req.section.strip().upper()
    roll_no = req.roll_no.strip()
    password = req.password.strip()
    
    # Rate Limiting Check
    rate_key = (roll_no, section)
    now = time.time()
    if rate_key in login_attempts:
        failures, locked_until = login_attempts[rate_key]
        if now < locked_until:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
        elif now >= locked_until and locked_until > 0:
            # Lockout expired
            login_attempts[rate_key] = (0, 0)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, section, roll_no, password FROM students WHERE roll_no = ? AND section = ?", (roll_no, section))
    student = cursor.fetchone()
    
    if not student or not verify_password(password, student["password"]):
        conn.close()
        # Record failure
        fails = login_attempts.get(rate_key, (0, 0))[0] + 1
        lock = now + 300 if fails >= 5 else 0 # 5 minutes lockout after 5 attempts
        login_attempts[rate_key] = (fails, lock)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Success, reset failures
    if rate_key in login_attempts:
        del login_attempts[rate_key]

    # Generate token with expiry (+7 days)
    token = secrets.token_hex(32)
    expires = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO auth_tokens (token, student_id, expires_at) VALUES (?, ?, ?)", (token, student["id"], expires))
    conn.commit()
    
    needs_password_change = verify_password("123", student["password"])
    conn.close()

    return {
        "student_id": student["id"],
        "name": student["name"],
        "roll_no": student["roll_no"],
        "section": student["section"],
        "token": token,
        "needs_password_change": needs_password_change
    }

@app.post("/api/auth/logout")
def logout(request: Request):
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        parts = auth.split(" ")
        if len(parts) == 2:
            token = parts[1]
            conn = get_connection()
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
            conn.commit()
            conn.close()
    return {"message": "Logged out successfully"}

@app.post("/api/auth/change-password")
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
    cursor.execute("UPDATE students SET password = ? WHERE id = ?", (hashed, student_id))
    conn.commit()
    conn.close()
    return {"message": "Password updated successfully"}

@app.post("/api/session/start")
def start_session(req: SessionStartRequest, student_id: int = Depends(get_current_student)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, help_level, status
    FROM sessions
    WHERE student_id = ? AND problem_id = ?
    ORDER BY id DESC LIMIT 1
    """, (student_id, req.problem_id))
    session = cursor.fetchone()

    if session:
        session_id = session["id"]
        cursor.execute("""
        UPDATE sessions SET help_level = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (req.help_level, session_id))
        conn.commit()
    else:
        cursor.execute("""
        INSERT INTO sessions (student_id, problem_id, help_level)
        VALUES (?, ?, ?)
        """, (student_id, req.problem_id, req.help_level))
        conn.commit()
        session_id = cursor.lastrowid

    cursor.execute("""
    SELECT attempt_number, code, ai_response, is_correct, created_at
    FROM submissions
    WHERE session_id = ?
    ORDER BY attempt_number ASC
    """, (session_id,))
    submissions = [dict(r) for r in cursor.fetchall()]
    
    # Retrieve last_code from session
    cursor.execute("SELECT last_code FROM sessions WHERE id = ?", (session_id,))
    last_code = cursor.fetchone()["last_code"]
    conn.close()

    is_solved = any(s["is_correct"] == 1 for s in submissions)

    return {
        "session_id": session_id,
        "help_level": req.help_level,
        "attempts_count": len(submissions),
        "is_solved": is_solved,
        "last_code": last_code,
        "history_count": len(submissions)
    }

@app.post("/api/session/save")
def save_session(req: SessionSaveRequest, student_id: int = Depends(get_current_student)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sessions WHERE id = ? AND student_id = ?", (req.session_id, student_id))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
        
    cursor.execute("UPDATE sessions SET last_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (req.code, req.session_id))
    conn.commit()
    conn.close()
    return {"message": "Saved"}

@app.post("/api/session/run")
def run_code_simulated(req: RunCodeRequest, student_id: int = Depends(get_current_student)):
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Code cannot be empty")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT problem_id FROM sessions WHERE id = ? AND student_id = ?", (req.session_id, student_id))
    session = cursor.fetchone()
    
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    cursor.execute("""
    SELECT title, topic, difficulty, description, sample_input, sample_output, ai_rubric
    FROM problems WHERE id = ?
    """, (session["problem_id"],))
    problem = dict(cursor.fetchone())
    conn.close()

    result = simulate_run(code=code, problem=problem)
    return result

@app.post("/api/session/submit")
def submit_code(req: SubmitCodeRequest, student_id: int = Depends(get_current_student)):
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Please write your Python code before requesting guidance!")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT s.id, s.student_id, s.problem_id, s.help_level, s.status,
           st.name as student_name, st.section as student_section, st.roll_no as student_roll
    FROM sessions s
    JOIN students st ON s.student_id = st.id
    WHERE s.id = ? AND s.student_id = ?
    """, (req.session_id, student_id))
    session = cursor.fetchone()

    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found or not authorized")

    problem_id = session["problem_id"]
    help_level = req.help_level or session["help_level"]

    cursor.execute("""
    SELECT title, topic, difficulty, description, sample_input, sample_output, ai_rubric
    FROM problems WHERE id = ?
    """, (problem_id,))
    problem = dict(cursor.fetchone())

    cursor.execute("""
    SELECT attempt_number, code, ai_response, is_correct
    FROM submissions
    WHERE session_id = ?
    ORDER BY attempt_number ASC
    """, (req.session_id,))
    history = [dict(r) for r in cursor.fetchall()]
    attempt_number = len(history) + 1

    eval_start = time.time()
    eval_result = evaluate_code(
        student_name=session["student_name"],
        section=session["student_section"],
        problem=problem,
        help_level=help_level,
        current_code=code,
        history=history,
        simulated_output=req.simulated_output
    )
    eval_duration_ms = round((time.time() - eval_start) * 1000, 1)

    is_correct = 1 if eval_result["is_correct"] else 0
    feedback = eval_result["feedback"]
    model_used = eval_result.get("model_used", "")

    cursor.execute("""
    INSERT INTO submissions (session_id, code, ai_response, is_correct, attempt_number, model_used)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (req.session_id, code, feedback, is_correct, attempt_number, model_used))

    if is_correct:
        cursor.execute("UPDATE sessions SET status = 'solved', last_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (code, req.session_id,))
    else:
        cursor.execute("UPDATE sessions SET last_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (code, req.session_id,))

    conn.commit()
    conn.close()

    result_label = "SOLVED" if is_correct else "IN_PROGRESS"
    logger.info(f"[EVAL] Submit Attempt #{attempt_number}: Student='{session['student_name']}' (Sec {session['student_section']}, Roll {session['student_roll']}) Problem='{problem['title']}' -> Result={result_label} Model='{model_used}' ({eval_duration_ms}ms)")

    return {
        "is_correct": bool(is_correct),
        "feedback": feedback,
        "attempt_number": attempt_number,
        "model_used": model_used,
        "error": eval_result.get("error")
    }

@app.get("/api/student/profile")
def get_profile(student_id: int = Depends(get_current_student)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, roll_no, section FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        raise HTTPException(status_code=404, detail="Student not found")

    # 1. Overall Stats
    cursor.execute("SELECT COUNT(*) as total_sessions FROM sessions WHERE student_id = ?", (student_id,))
    total_sessions = cursor.fetchone()["total_sessions"]

    cursor.execute("SELECT COUNT(DISTINCT problem_id) as completed_problems FROM sessions WHERE student_id = ? AND status = 'solved'", (student_id,))
    completed_problems = cursor.fetchone()["completed_problems"]
    
    cursor.execute("""
        SELECT COUNT(*) as total_attempts 
        FROM submissions sub 
        JOIN sessions s ON sub.session_id = s.id 
        WHERE s.student_id = ?
    """, (student_id,))
    total_attempts = cursor.fetchone()["total_attempts"]

    # 2. Topic Mastery
    cursor.execute("""
        SELECT p.topic, 
               COUNT(p.id) as total,
               SUM(CASE WHEN s.status = 'solved' THEN 1 ELSE 0 END) as completed
        FROM problems p
        LEFT JOIN sessions s ON p.id = s.problem_id AND s.student_id = ?
        GROUP BY p.topic
        ORDER BY p.topic
    """, (student_id,))
    topic_mastery = [dict(row) for row in cursor.fetchall()]
    
    # Fill in None completions with 0
    for t in topic_mastery:
        if t["completed"] is None:
            t["completed"] = 0

    # 3. Activity History
    cursor.execute("""
        SELECT p.title as problem_title, s.status, s.updated_at, 
               s.status = 'solved' as is_solved,
               (SELECT COUNT(*) FROM submissions sub WHERE sub.session_id = s.id) as attempts_count
        FROM sessions s
        JOIN problems p ON s.problem_id = p.id
        WHERE s.student_id = ?
        ORDER BY s.updated_at DESC
        LIMIT 10
    """, (student_id,))
    activity_history = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return {
        "student": dict(student),
        "stats": {
            "completed_problems": completed_problems,
            "total_attempts": total_attempts,
            "total_sessions": total_sessions
        },
        "topic_mastery": topic_mastery,
        "activity_history": activity_history
    }


# ─────────────────────────────────────────────
# STATIC FILE SERVING
# ─────────────────────────────────────────────

if os.path.exists(FRONTEND_DIR):
    css_dir = os.path.join(FRONTEND_DIR, "css")
    js_dir = os.path.join(FRONTEND_DIR, "js")
    if os.path.exists(css_dir):
        app.mount("/css", StaticFiles(directory=css_dir), name="css")
    if os.path.exists(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")


@app.get("/")
def serve_root():
    """Redirect root to /problems."""
    return RedirectResponse(url="/problems")


@app.get("/problems")
def serve_problems():
    """Serve the problems browser page."""
    problems_file = os.path.join(FRONTEND_DIR, "problems.html")
    if os.path.exists(problems_file):
        return FileResponse(problems_file)
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Python Practice API is running. Frontend not found."}


@app.get("/login")
def serve_login():
    """Serve the login page."""
    login_file = os.path.join(FRONTEND_DIR, "login.html")
    if os.path.exists(login_file):
        return FileResponse(login_file)
    raise HTTPException(status_code=404, detail="Login page not found")


@app.get("/practice")
def serve_practice():
    """Serve the code practice page."""
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Practice page not found")
    
@app.get("/profile")
def serve_profile():
    """Serve the profile dashboard."""
    profile_file = os.path.join(FRONTEND_DIR, "profile.html")
    if os.path.exists(profile_file):
        return FileResponse(profile_file)
    return {"message": "Profile page not found."}
