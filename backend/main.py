"""
FastAPI backend for Python Practice platform.
Serves REST API and multi-page frontend.
"""

import os
import sys
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ─────────────────────────────────────────────
# DUAL AUDIT LOGGING SETUP (Console + logs.txt)
# ─────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs.txt")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

# File Handler: writes clean audit trail to logs.txt
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=15*1024*1024, backupCount=3, encoding="utf-8")
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

# Console Handler: displays live messages in the server terminal
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger("pymentor")
logger.setLevel(logging.INFO)
logger.handlers.clear()
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.propagate = False

# Ensure submodule loggers (ai_mentor, quota_manager) pipe directly into both handlers
for subname in ["pymentor.ai", "pymentor.quota"]:
    sub = logging.getLogger(subname)
    sub.setLevel(logging.INFO)
    sub.handlers.clear()
    sub.propagate = True

try:
    from pymentor.backend.database import get_connection, init_db
    from pymentor.backend.ai_mentor import evaluate_code, simulate_run, get_api_key, FALLBACK_MODELS
except ImportError:
    from backend.database import get_connection, init_db
    from backend.ai_mentor import evaluate_code, simulate_run, get_api_key, FALLBACK_MODELS

init_db()

# Turn off auto-docs in production to prevent automated scanner fingerprinting
app = FastAPI(
    title="Python Practice API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def audit_http_middleware(request: Request, call_next):
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    method = request.method
    path = request.url.path

    response = await call_next(request)

    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"

    duration_ms = round((time.time() - start_time) * 1000, 1)
    status_code = response.status_code

    # Log API accesses and root HTML page hits for auditing
    if path.startswith("/api") or path in ["/", "/practice"]:
        logger.info(f"[HTTP] {client_ip} - {method} {path} -> {status_code} ({duration_ms}ms)")

    return response

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")


# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────

class StudentLoginRequest(BaseModel):
    section: str
    roll_no: str
    password: str

class ChangePasswordRequest(BaseModel):
    student_id: int
    old_password: str
    new_password: str

class SessionStartRequest(BaseModel):
    student_id: int
    problem_id: int
    help_level: Optional[int] = 1

class RunCodeRequest(BaseModel):
    session_id: int
    code: str

class SaveCodeRequest(BaseModel):
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
def get_status(request: Request, x_admin_secret: Optional[str] = Header(None)):
    admin_secret = os.environ.get("ADMIN_SECRET", "").strip()
    if not admin_secret:
        admin_secret = "pymentor-admin-secret"
    if x_admin_secret != admin_secret:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"[SECURITY] Unauthorized access to /api/status blocked from IP={client_ip}")
        raise HTTPException(status_code=403, detail="Access Denied")

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
def set_api_key(req: SetKeyRequest, request: Request, x_admin_secret: Optional[str] = Header(None)):
    admin_secret = os.environ.get("ADMIN_SECRET", "").strip()
    if not admin_secret:
        admin_secret = "pymentor-admin-secret"
    if x_admin_secret != admin_secret:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"[SECURITY] Unauthorized attempt to update API key from IP={client_ip}")
        raise HTTPException(status_code=403, detail="Forbidden: Valid X-Admin-Secret header required.")

    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    os.environ["GEMINI_API_KEY"] = key
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"GEMINI_API_KEY={key}\n")
    logger.info("[ADMIN] Gemini API Key updated successfully by admin")
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
def login_student(req: StudentLoginRequest, request: Request):
    import re
    client_ip = request.client.host if request.client else "unknown"
    raw_section = (req.section or "").strip().upper()
    raw_roll = (req.roll_no or "").strip()
    password = (req.password or "").strip()

    logger.info(f"[AUTH] Login attempt from IP={client_ip}: section='{raw_section}', roll='{raw_roll}'")

    if not raw_section or not raw_roll or not password:
        logger.warning(f"[AUTH] Login rejected: missing fields from IP={client_ip}")
        raise HTTPException(status_code=400, detail="Section, Roll Number, and Password are required.")

    # Normalize roll_no: strip 'User', 'Roll', 'E-', leading zeroes (e.g. '01' -> '1', 'User 1' -> '1')
    clean_roll = raw_roll.lower().replace("user", "").replace("roll", "").replace("-", "").strip()
    digit_match = re.search(r'\d+', clean_roll)
    if digit_match:
        norm_roll = str(int(digit_match.group(0)))
    else:
        norm_roll = clean_roll

    section = raw_section

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, name, roll_no, section, password 
    FROM students 
    WHERE section = ? AND (roll_no = ? OR roll_no = ?)
    """, (section, norm_roll, raw_roll))
    student = cursor.fetchone()
    conn.close()

    # Prevent roll enumeration: uniform 401 response for non-existent roll or incorrect password
    if not student or student["password"] != password:
        logger.warning(f"[AUTH] Login FAILED from IP={client_ip}: section='{raw_section}', roll='{raw_roll}' (Invalid credentials)")
        raise HTTPException(
            status_code=401, 
            detail="Access Denied: Invalid credentials"
        )

    logger.info(f"[AUTH] Login SUCCESS: ID={student['id']}, Name='{student['name']}', Section={student['section']}, Roll={student['roll_no']} (IP={client_ip})")

    return {
        "student_id": student["id"],
        "name": student["name"],
        "roll_no": student["roll_no"],
        "section": student["section"]
    }

@app.post("/api/student/change-password")
def change_password(req: ChangePasswordRequest):
    new_pwd = req.new_password.strip()
    if not new_pwd or len(new_pwd) < 3:
        raise HTTPException(status_code=400, detail="New password must be at least 3 characters long.")
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password FROM students WHERE id = ?", (req.student_id,))
    student = cursor.fetchone()

    if not student or student["password"] != req.old_password.strip():
        conn.close()
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    cursor.execute("UPDATE students SET password = ? WHERE id = ?", (new_pwd, req.student_id))
    conn.commit()
    conn.close()
    logger.info(f"[AUTH] Password updated successfully for Student ID={req.student_id}")
    return {"message": "Password updated successfully!"}

@app.get("/api/quota")
def check_quota_status(request: Request, x_admin_secret: Optional[str] = Header(None)):
    admin_secret = os.environ.get("ADMIN_SECRET", "").strip()
    if not admin_secret:
        admin_secret = "pymentor-admin-secret"
    if x_admin_secret != admin_secret:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"[SECURITY] Unauthorized access to /api/quota blocked from IP={client_ip}")
        raise HTTPException(status_code=403, detail="Access Denied")

    try:
        from pymentor.backend.quota_manager import get_quota_summary
    except ImportError:
        from backend.quota_manager import get_quota_summary
    return {"quotas": get_quota_summary()}

@app.post("/api/session/start")
def start_session(req: SessionStartRequest):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, help_level, status, last_code
    FROM sessions
    WHERE student_id = ? AND problem_id = ?
    ORDER BY id DESC LIMIT 1
    """, (req.student_id, req.problem_id))
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
        """, (req.student_id, req.problem_id, req.help_level))
        conn.commit()
        session_id = cursor.lastrowid

    logger.info(f"[SESSION] Student ID={req.student_id} opened problem ID={req.problem_id} (session_id={session_id}, level={req.help_level})")

    cursor.execute("""
    SELECT attempt_number, code, ai_response, is_correct, created_at
    FROM submissions
    WHERE session_id = ?
    ORDER BY attempt_number ASC
    """, (session_id,))
    submissions = [dict(r) for r in cursor.fetchall()]
    conn.close()

    last_code = ""
    if session and session["last_code"]:
        last_code = session["last_code"]
    elif submissions:
        last_code = submissions[-1]["code"]

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
def save_session_code(req: SaveCodeRequest):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET last_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (req.code, req.session_id))
    conn.commit()
    conn.close()
    return {"status": "saved"}


@app.post("/api/session/run")
def run_code_simulated(req: RunCodeRequest):
    """
    Simulates Python code execution and returns terminal output.
    Abstraction layer: real subprocess/Docker execution can replace simulate_run later.
    """
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Code cannot be empty")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT problem_id FROM sessions WHERE id = ?", (req.session_id,))
    session = cursor.fetchone()
    conn.close()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT title, topic, difficulty, description, sample_input, sample_output, ai_rubric
    FROM problems WHERE id = ?
    """, (session["problem_id"],))
    problem = dict(cursor.fetchone())
    conn.close()

    result = simulate_run(code=code, problem=problem)
    return result


@app.post("/api/session/submit")
def submit_code(req: SubmitCodeRequest):
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
    WHERE s.id = ?
    """, (req.session_id,))
    session = cursor.fetchone()

    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

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
def serve_problems():
    """Serve the problems browser page."""
    problems_file = os.path.join(FRONTEND_DIR, "problems.html")
    if os.path.exists(problems_file):
        return FileResponse(problems_file)
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Python Practice API is running. Frontend not found."}


@app.get("/practice")
def serve_practice():
    """Serve the code practice page."""
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Practice page not found")
