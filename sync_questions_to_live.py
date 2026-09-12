"""
PyMentor — Live Question Synchronizer
Syncs problem statements, constraints, sample I/O, concepts, and rubrics
from the local SQLite database to the live production server (https://khokhar.in.net).

Usage:
    python sync_questions_to_live.py              # Interactive mode (asks before each question)
    python sync_questions_to_live.py --all        # Sync all questions automatically 1-by-1
    python sync_questions_to_live.py --id 2       # Sync a single question by ID
    python sync_questions_to_live.py --from 2 --to 5  # Sync a range of questions
"""

import os
import sys
import json
import sqlite3
import argparse
import urllib.request
import urllib.error
import ssl
from typing import Dict, Any, Optional

# Configuration
LOCAL_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pymentor.db")
# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SSL_CONTEXT = ssl.create_default_context()


def get_headers() -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Admin-Secret": ADMIN_SECRET
    }


def api_request(endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Any:
    """Makes a reliable authenticated HTTP request to the live PyMentor server."""
    url = f"{LIVE_SERVER_URL}{endpoint}"
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=payload, headers=get_headers(), method=method)
    
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(error_body)
            detail = parsed.get("detail", error_body)
        except Exception:
            detail = error_body
        raise RuntimeError(f"HTTP {e.code} on {method} {endpoint}: {detail}")
    except Exception as e:
        raise RuntimeError(f"Network error on {method} {endpoint}: {e}")


def fetch_live_problem_ids() -> set:
    """Fetches the list of existing problem IDs currently hosted on the live server."""
    res = api_request("/api/admin/problems")
    problems = res.get("problems", []) if isinstance(res, dict) else res
    return {p["id"] for p in problems if "id" in p}


def fetch_local_problems() -> list:
    """Reads all problem definitions from the local SQLite database."""
    if not os.path.exists(LOCAL_DB_PATH):
        raise FileNotFoundError(f"Local database not found at: {LOCAL_DB_PATH}")

    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, topic, title, difficulty, description, sample_input, sample_output,
               concepts, starter_code, ai_rubric,
               COALESCE(reference_solution, '') as reference_solution,
               COALESCE(teacher_instructions, '') as teacher_instructions,
               COALESCE(order_index, 0) as order_index
        FROM problems
        ORDER BY id ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Parse concepts JSON string into native list
    for r in rows:
        try:
            r["concepts"] = json.loads(r["concepts"]) if isinstance(r["concepts"], str) else (r["concepts"] or [])
        except Exception:
            r["concepts"] = []
    return rows


def sync_single_problem(problem: Dict[str, Any], live_ids: set) -> None:
    """Syncs one problem to the live server (PUT if exists, POST if new)."""
    pid = problem["id"]
    title = problem["title"]
    topic = problem["topic"]
    
    payload = {
        "title": title,
        "topic": topic,
        "difficulty": problem["difficulty"],
        "description": problem["description"],
        "sample_input": problem["sample_input"],
        "sample_output": problem["sample_output"],
        "concepts": problem["concepts"],
        "starter_code": problem["starter_code"],
        "ai_rubric": problem["ai_rubric"],
        "reference_solution": problem.get("reference_solution", ""),
        "teacher_instructions": problem.get("teacher_instructions", ""),
        "order_index": problem.get("order_index", 0)
    }

    if pid in live_ids:
        # Update existing problem
        res = api_request(f"/api/admin/problems/{pid}", method="PUT", data=payload)
        action = "UPDATED"
    else:
        # Create new problem
        res = api_request("/api/admin/problems", method="POST", data=payload)
        action = "CREATED"

    # Verify updated content by fetching back
    verified = api_request(f"/api/admin/problems/{pid}/full", method="GET")
    has_constraints = "Constraints" in (verified.get("description") or "")
    
    print(f"  [{action}] Q{pid:02d}: {title}")
    print(f"            Topic: {topic} | Status: Success")
    print(f"            Constraints present on live: {has_constraints}")
    print(f"            Sample Input: {repr((verified.get('sample_input') or '')[:30])}...")


def main():
    parser = argparse.ArgumentParser(description="Sync local questions to live PyMentor server.")
    parser.add_argument("--all", action="store_true", help="Sync all questions sequentially without prompting")
    parser.add_argument("--id", type=int, help="Sync a specific question by ID")
    parser.add_argument("--from", dest="from_id", type=int, help="Start from this question ID")
    parser.add_argument("--to", dest="to_id", type=int, help="End at this question ID")
    args = parser.parse_args()

    print("=" * 65)
    print("      PyMentor — Question Synchronizer (Local -> Live)")
    print(f"  Target Server : {LIVE_SERVER_URL}")
    print(f"  Local Database: {LOCAL_DB_PATH}")
    print("=" * 65)

    # 1. Health check live server
    try:
        status = api_request("/api/status")
        print(f"\n[OK] Connected to live server. Server status: {status.get('status')}")
    except Exception as e:
        print(f"\n[ERROR] Could not connect to live server at {LIVE_SERVER_URL}: {e}")
        sys.exit(1)

    # 2. Fetch live and local questions
    live_ids = fetch_live_problem_ids()
    local_problems = fetch_local_problems()
    print(f"[INFO] Live currently has {len(live_ids)} problems. Local DB has {len(local_problems)} problems.\n")

    # Filter problems based on CLI args
    target_problems = local_problems
    if args.id:
        target_problems = [p for p in local_problems if p["id"] == args.id]
        if not target_problems:
            print(f"[ERROR] Question ID {args.id} not found in local database.")
            sys.exit(1)
    else:
        if args.from_id:
            target_problems = [p for p in target_problems if p["id"] >= args.from_id]
        if args.to_id:
            target_problems = [p for p in target_problems if p["id"] <= args.to_id]

    total = len(target_problems)
    print(f"Ready to sync {total} question(s) to {LIVE_SERVER_URL}:\n")

    for idx, prob in enumerate(target_problems, 1):
        pid = prob["id"]
        title = prob["title"]
        
        # If not --all and syncing multiple, ask for user confirmation 1 by 1
        if not args.all and total > 1 and not args.id:
            try:
                ans = input(f"[{idx}/{total}] Sync Q{pid} ('{title}') to live? [Y/n/q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nSync aborted by user.")
                break
            if ans == "q":
                print("Exiting sync.")
                break
            if ans in ("n", "no"):
                print(f"Skipped Q{pid}.")
                continue

        try:
            sync_single_problem(prob, live_ids)
            print("-" * 50)
        except Exception as err:
            print(f"  [FAILED] Q{pid}: {err}")
            if not args.all:
                retry = input("  Retry this question? [Y/n]: ").strip().lower()
                if retry not in ("n", "no"):
                    try:
                        sync_single_problem(prob, live_ids)
                    except Exception as err2:
                        print(f"  [RETRY FAILED]: {err2}")

    print("\n[SUCCESS] Sync process completed.")


if __name__ == "__main__":
    main()
