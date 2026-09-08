"""
Production Database Setup and Student Enrollment Script for PyMentor.
- Clears all test activity (submissions, sessions, events, auth_tokens)
- Wipes test accounts and initializes 183 students from 'Programing for AI' sheet
- Adds personal account for Pawan (Roll: 978, Section: E, Email: pawan@cqst)
- Ensures 'email' field is created and populated
- Sets default password '123' (bcrypt hashed) with needs_password_change=1
- Retains all 20 curriculum problems intact
"""

import os
import sqlite3
import openpyxl
from backend.database import DB_PATH, get_connection, hash_password, init_db

EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "New IBCA-AI&ML 2026 Attendance Sheet(CQ) (2).xlsx")

def wipe_test_data(conn):
    cursor = conn.cursor()
    print("Clearing test activity data...")
    cursor.execute("DELETE FROM events")
    cursor.execute("DELETE FROM submissions")
    cursor.execute("DELETE FROM sessions")
    cursor.execute("DELETE FROM auth_tokens")
    cursor.execute("DELETE FROM students")
    
    # Reset auto-increment sequences for wiped tables
    try:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('submissions', 'sessions', 'events', 'students')")
    except Exception:
        pass
    
    conn.commit()
    print("All test data wiped successfully.")

def import_students():
    print(f"Ensuring database schema at {DB_PATH}...")
    init_db()
    
    conn = get_connection()
    wipe_test_data(conn)
    cursor = conn.cursor()

    if not os.path.exists(EXCEL_PATH):
        raise FileNotFoundError(f"Excel file not found at: {EXCEL_PATH}")

    print(f"Loading Excel file: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    sheet_name = "Programing for AI"
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Sheet '{sheet_name}' not found. Available sheets: {wb.sheetnames}")

    ws = wb[sheet_name]
    default_hashed_pwd = hash_password("123")

    enrolled = 0
    section_counts = {}

    for row_idx in range(3, ws.max_row + 1):
        roll_raw = ws.cell(row=row_idx, column=2).value
        name_raw = ws.cell(row=row_idx, column=3).value
        email_raw = ws.cell(row=row_idx, column=4).value
        section_raw = ws.cell(row=row_idx, column=5).value

        if roll_raw is None or not str(roll_raw).strip():
            continue

        if isinstance(roll_raw, float) and roll_raw.is_integer():
            roll_no = str(int(roll_raw))
        else:
            roll_no = str(roll_raw).strip()

        name = str(name_raw).strip() if name_raw else "Student"
        email = str(email_raw).strip() if email_raw else ""
        section = str(section_raw).strip().upper() if section_raw else "E"

        cursor.execute("""
            INSERT INTO students (roll_no, name, section, email, password, needs_password_change, default_help_level)
            VALUES (?, ?, ?, ?, ?, 1, 1)
        """, (roll_no, name, section, email, default_hashed_pwd))
        
        enrolled += 1
        section_counts[section] = section_counts.get(section, 0) + 1

    # Personal account for Pawan
    pawan_account = {
        "roll_no": "978",
        "name": "Pawan",
        "section": "E",
        "email": "pawan@cqst",
        "password": default_hashed_pwd,
        "needs_password_change": 1,
        "default_help_level": 1
    }

    cursor.execute("""
        INSERT INTO students (roll_no, name, section, email, password, needs_password_change, default_help_level)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        pawan_account["roll_no"],
        pawan_account["name"],
        pawan_account["section"],
        pawan_account["email"],
        pawan_account["password"],
        pawan_account["needs_password_change"],
        pawan_account["default_help_level"]
    ))
    enrolled += 1
    section_counts["E"] = section_counts.get("E", 0) + 1

    conn.commit()

    # Verification queries
    cursor.execute("SELECT COUNT(*) as c FROM students")
    total_students = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM problems")
    total_problems = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM sessions")
    total_sessions = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM submissions")
    total_submissions = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM events")
    total_events = cursor.fetchone()["c"]

    cursor.execute("SELECT id, roll_no, name, section, email FROM students WHERE roll_no = '978' AND section = 'E'")
    pawan_row = cursor.fetchone()

    conn.close()

    print("=" * 60)
    print(f"DATABASE ENROLLMENT COMPLETE")
    print("=" * 60)
    print(f"Total students registered: {total_students} (183 from Excel + 1 Pawan)")
    print(f"Distribution across sections:")
    for sec in sorted(section_counts.keys()):
        print(f"  - Section {sec}: {section_counts[sec]} accounts")
    print(f"Pawan Account verified: ID={pawan_row['id']} | Roll={pawan_row['roll_no']} | Name={pawan_row['name']} | Sec={pawan_row['section']} | Email={pawan_row['email']}")
    print("-" * 60)
    print(f"Clean Database State:")
    print(f"  - Problems preserved:  {total_problems}")
    print(f"  - Active sessions:     {total_sessions} (Clean)")
    print(f"  - Submissions:         {total_submissions} (Clean)")
    print(f"  - Telemetry events:    {total_events} (Clean)")
    print("=" * 60)

if __name__ == "__main__":
    import_students()
