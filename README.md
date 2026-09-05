# PyMentor — Python Practice Lab Platform

A lightweight, secure, and interactive Python practice and learning platform built for classroom lab environments. Features in-browser Python execution (via Pyodide WebAssembly), automated multi-tier AI mentoring guidance powered by Google Gemini, student progress and telemetry tracking, and an administrative analytics dashboard.

---

## Features

- **Topic-Wise Practice Problems:** Collapsible, accordion-style problem browser organized by topic with difficulty indicators and progress markers (Solved, Attempted, Unattempted).
- **In-Browser Execution:** Client-side real-time Python execution powered by Pyodide WebAssembly.
- **AI Guidance System:** Tiered Socratic hints (Level 1: Gentle Hint, Level 2: Target Clue, Level 3: Concrete Direction) powered by Google Gemini with multi-model fallback cascade.
- **Active Practice Time Tracking:** Server-authoritative heartbeat telemetry tracks actual coding time per problem.
- **Student Authentication & Session Security:** Token-based session management, brute-force login lockout, active session revocation upon password change, and enforced initial password update.
- **Admin Dashboard:** Real-time analytics, student activity monitor, tough problem insights, and model quota tracking protected by constant-time secret verification and rate limiting.

---

## Quick Start (Windows)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Pawan978/pymentor.git
   cd pymentor
   ```

2. **Configure Environment Variables:**
   Copy `.env.example` to `.env` and fill in your secrets:
   ```bash
   copy .env.example .env
   ```
   Edit `.env`:
   - `ADMIN_SECRET`: Set a strong, private admin secret passphrase.
   - `GEMINI_API_KEY`: Your Google Gemini API key.
   - `ALLOWED_ORIGINS`: (Optional) Comma-separated CORS allowed domains (e.g. your tunnel or custom domain).

3. **Start the Platform:**
   Double-click or run:
   ```bat
   start_pymentor.bat
   ```
   The launcher will automatically detect Python, install any missing dependencies from `requirements.txt`, initialize the SQLite database, and launch the server on port `8000`.

4. **Access the Application:**
   - **Problems & Practice:** `http://localhost:8000/problems`
   - **Student Login:** `http://localhost:8000/login`
   - **Admin Dashboard:** `http://localhost:8000/admin`

---

## Architecture & Tech Stack

- **Backend:** Python 3.10+, FastAPI, Uvicorn, SQLite3, Pydantic, Bcrypt.
- **Frontend:** HTML5, Modern Vanilla CSS, Vanilla JavaScript, Monaco Editor, Pyodide (WASM), DOMPurify, Marked.js.
- **AI Engine:** Google GenAI SDK (`google-genai`) with fallback quotas across Gemini Flash/Lite models.

---

## Security Architecture

- **Fail-Closed Secrets:** Application halts on startup if `ADMIN_SECRET` is unset or left as default.
- **Constant-Time Verification:** Admin authentication uses `secrets.compare_digest` with 15-minute brute-force IP lockouts.
- **Per-Student Rate Limits & Cooldowns:** Submissions enforce a 3-second cooldown to prevent Gemini API quota abuse, and inputs are capped at 20,000 characters.
- **Session Revocation:** Changing student passwords immediately terminates all active bearer tokens in SQLite.
- **Output Sanitization:** Guidance responses are sanitized with DOMPurify before HTML rendering.
