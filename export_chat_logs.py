#!/usr/bin/env python3
"""
PyMentor Chat Logs & Interaction Exporter
========================================
Extracts student submissions, AI mentor responses, prompt context, help levels,
simulated outputs, and outcome evaluations from `pymentor.db` into CSV and JSON.

Usage:
    python export_chat_logs.py
    python export_chat_logs.py --output custom_logs.csv
    python export_chat_logs.py --json-only
    python export_chat_logs.py --csv-only
"""

import sqlite3
import csv
import json
import os
import sys
from datetime import datetime

# Determine default paths relative to script location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pymentor.db")
DEFAULT_CSV_PATH = os.path.join(BASE_DIR, "chat_logs_export.csv")
DEFAULT_JSON_PATH = os.path.join(BASE_DIR, "chat_logs_export.json")


def fetch_all_interactions(db_path: str):
    """
    Query all submissions joined with session, student, and problem metadata.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
    SELECT 
        sub.id AS submission_id,
        sub.created_at AS timestamp,
        st.id AS student_id,
        st.roll_no AS roll_no,
        st.name AS student_name,
        st.section AS section,
        p.id AS problem_id,
        p.title AS problem_title,
        p.topic AS problem_topic,
        p.difficulty AS difficulty,
        s.id AS session_id,
        s.help_level AS help_level,
        sub.attempt_number AS attempt_number,
        sub.is_correct AS is_correct_raw,
        CASE WHEN sub.is_correct = 1 THEN 'Correct' ELSE 'Incorrect' END AS is_correct,
        sub.model_used AS model_used,
        sub.code AS student_code,
        COALESCE(sub.simulated_output, '') AS simulated_output,
        sub.ai_response AS ai_response,
        s.status AS session_status,
        s.run_count AS session_run_count,
        s.time_spent_seconds AS session_time_spent_sec,
        p.concepts AS problem_concepts
    FROM submissions sub
    LEFT JOIN sessions s ON sub.session_id = s.id
    LEFT JOIN students st ON s.student_id = st.id
    LEFT JOIN problems p ON s.problem_id = p.id
    ORDER BY sub.id ASC
    """

    cursor.execute(query)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def export_to_csv(rows, output_path: str):
    """Write interactions list to a clean, standard CSV file."""
    if not rows:
        print("[WARN] No submissions found to export.")
        return

    fieldnames = [
        "submission_id",
        "timestamp",
        "section",
        "roll_no",
        "student_name",
        "student_id",
        "session_id",
        "problem_id",
        "problem_title",
        "problem_topic",
        "difficulty",
        "help_level",
        "attempt_number",
        "is_correct",
        "model_used",
        "student_code",
        "simulated_output",
        "ai_response",
        "session_status",
        "session_run_count",
        "session_time_spent_sec",
        "problem_concepts"
    ]

    with open(output_path, mode="w", newline="", encoding="utf-8-sig") as f:
        # utf-8-sig ensures Excel on Windows displays accents/special characters correctly
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for r in rows:
            # Format row data safely for CSV
            row_dict = {k: r.get(k, "") for k in fieldnames}
            writer.writerow(row_dict)

    print(f"[OK] Successfully exported {len(rows)} rows to CSV:\n     -> {output_path}")


def export_to_json(rows, output_path: str):
    """Write interactions list to JSON for easier programmatic parsing in Python/Pandas."""
    if not rows:
        return

    with open(output_path, mode="w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    print(f"[OK] Successfully exported {len(rows)} records to JSON:\n     -> {output_path}")


def print_summary(rows):
    """Print high-level statistics to assist with prompt and help-level fine-tuning."""
    if not rows:
        return

    total = len(rows)
    correct_count = sum(1 for r in rows if r.get("is_correct") == "Correct")
    incorrect_count = total - correct_count
    unique_students = len(set(f"{r.get('section')}_{r.get('roll_no')}" for r in rows if r.get("roll_no")))
    unique_problems = len(set(r.get("problem_id") for r in rows if r.get("problem_id")))

    # Help level counts
    help_levels = {}
    for r in rows:
        hl = r.get("help_level", "Unknown")
        help_levels[hl] = help_levels.get(hl, 0) + 1

    # Models used
    models = {}
    for r in rows:
        m = r.get("model_used") or "Unknown"
        models[m] = models.get(m, 0) + 1

    print("\n" + "=" * 60)
    print("           PYMENTOR INTERACTION LOG SUMMARY")
    print("=" * 60)
    print(f" Total Submissions Exported: {total}")
    print(f" Unique Students:            {unique_students}")
    print(f" Unique Problems Attempted:  {unique_problems}")
    print(f" Correct Submissions:        {correct_count} ({correct_count/total*100:.1f}%)")
    print(f" Incorrect Submissions:      {incorrect_count} ({incorrect_count/total*100:.1f}%)")
    print("-" * 60)
    print(" Submissions by Help Level:")
    for hl, cnt in sorted(help_levels.items(), key=lambda x: str(x[0])):
        label = {1: "Level 1 (Socratic / Gentle Hint)", 
                 2: "Level 2 (Targeted Direction)", 
                 3: "Level 3 (Concrete Solution Guidance)"}.get(hl, f"Level {hl}")
        print(f"   * {label:<38}: {cnt:>4} ({cnt/total*100:5.1f}%)")
    print("-" * 60)
    print(" Submissions by Model:")
    for m, cnt in sorted(models.items(), key=lambda x: x[1], reverse=True):
        print(f"   * {m:<38}: {cnt:>4} ({cnt/total*100:5.1f}%)")
    print("=" * 60 + "\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export PyMentor submissions and AI interactions.")
    parser.add_argument("--db", default=DB_PATH, help=f"Path to SQLite database (default: {DB_PATH})")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help=f"CSV output path (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("--json", default=DEFAULT_JSON_PATH, help=f"JSON output path (default: {DEFAULT_JSON_PATH})")
    parser.add_argument("--csv-only", action="store_true", help="Only export CSV")
    parser.add_argument("--json-only", action="store_true", help="Only export JSON")

    args = parser.parse_args()

    print(f"[INFO] Reading database: {args.db} ...")
    interactions = fetch_all_interactions(args.db)

    print_summary(interactions)

    if not args.json_only:
        export_to_csv(interactions, args.csv)

    if not args.csv_only:
        export_to_json(interactions, args.json)

    print("[SUCCESS] All logs extracted! Open chat_logs_export.csv in Excel/Pandas to analyze student code vs AI responses.\n")


if __name__ == "__main__":
    main()
