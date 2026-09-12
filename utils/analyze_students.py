import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_path = r'c:\Users\hp\Desktop\lecture\downloaded_db\pymentor_live_latest.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

# 1. Total Students
c.execute("SELECT COUNT(*) FROM students")
total_students = c.fetchone()[0]

# 2. Students who have auth_tokens (have logged in at least once)
c.execute("SELECT DISTINCT student_id FROM auth_tokens")
logged_in_ids = set(row[0] for row in c.fetchall())

# 3. Students who have changed default password
c.execute("SELECT id FROM students WHERE needs_password_change = 0")
password_changed_ids = set(row[0] for row in c.fetchall())

# 4. Students who have sessions
c.execute("SELECT DISTINCT student_id FROM sessions")
session_ids = set(row[0] for row in c.fetchall())

# 5. Students who made submissions
c.execute("""
    SELECT DISTINCT ses.student_id 
    FROM submissions sub
    JOIN sessions ses ON sub.session_id = ses.id
""")
submission_ids = set(row[0] for row in c.fetchall())

# 6. Students who successfully solved at least 1 problem
c.execute("""
    SELECT DISTINCT ses.student_id 
    FROM submissions sub
    JOIN sessions ses ON sub.session_id = ses.id
    WHERE sub.is_correct = 1
""")
solved_ids = set(row[0] for row in c.fetchall())

# 7. Students with any event in audit log
c.execute("SELECT DISTINCT student_id FROM events WHERE student_id IS NOT NULL")
event_ids = set(row[0] for row in c.fetchall())

# Union of all active indicators
any_activity_ids = logged_in_ids | password_changed_ids | session_ids | submission_ids | event_ids
never_touched_ids = set()

# Fetch all student details
c.execute("SELECT id, roll_no, name, section, needs_password_change, is_active FROM students ORDER BY section, roll_no")
all_students = c.fetchall()

active_students_data = []
inactive_students_data = []

for s_id, roll, name, sec, pwd_change, is_active in all_students:
    has_logged = s_id in logged_in_ids
    has_pwd_chg = pwd_change == 0
    has_sess = s_id in session_ids
    has_sub = s_id in submission_ids
    has_solv = s_id in solved_ids
    has_event = s_id in event_ids
    
    is_ever_active = s_id in any_activity_ids
    
    # Activity stats
    c.execute("SELECT COUNT(*), COALESCE(SUM(time_spent_seconds), 0), COALESCE(SUM(run_count), 0) FROM sessions WHERE student_id = ?", (s_id,))
    sess_cnt, total_time, total_runs = c.fetchone()
    
    c.execute("""
        SELECT COUNT(*), SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END)
        FROM submissions sub
        JOIN sessions ses ON sub.session_id = ses.id
        WHERE ses.student_id = ?
    """, (s_id,))
    total_subs, correct_subs = c.fetchone()
    correct_subs = correct_subs or 0
    
    info = {
        'id': s_id,
        'roll': roll,
        'name': name,
        'section': sec,
        'has_logged': has_logged,
        'has_pwd_chg': has_pwd_chg,
        'sessions': sess_cnt,
        'time_spent': total_time,
        'runs': total_runs,
        'submissions': total_subs,
        'solved': correct_subs,
        'is_active_db': is_active
    }
    
    if is_ever_active:
        active_students_data.append(info)
    else:
        never_touched_ids.add(s_id)
        inactive_students_data.append(info)

print(f"Total Registered Students:     {total_students}")
print(f"Students with ANY Activity:    {len(any_activity_ids)} ({len(any_activity_ids)/total_students*100:.1f}%)")
print(f"  - Logged in (Tokens):        {len(logged_in_ids)}")
print(f"  - Changed Default Password:  {len(password_changed_ids)}")
print(f"  - Started a Problem Session: {len(session_ids)}")
print(f"  - Submitted Code:            {len(submission_ids)}")
print(f"  - Solved at least 1 problem: {len(solved_ids)}")
print(f"Students with ZERO Activity:   {len(never_touched_ids)} ({len(never_touched_ids)/total_students*100:.1f}%)")

print("\n--- BREAKDOWN BY SECTION ---")
c.execute("SELECT section, COUNT(*) FROM students GROUP BY section")
for sec, cnt in c.fetchall():
    sec_active = sum(1 for s in active_students_data if s['section'] == sec)
    sec_inactive = sum(1 for s in inactive_students_data if s['section'] == sec)
    print(f"Section {sec}: Total = {cnt} | Active = {sec_active} ({sec_active/cnt*100:.1f}%) | Inactive (0 activity) = {sec_inactive} ({sec_inactive/cnt*100:.1f}%)")

# Top Active Students
active_students_data.sort(key=lambda x: (x['solved'], x['submissions'], x['time_spent']), reverse=True)
print("\n--- TOP ACTIVE STUDENTS ---")
for idx, s in enumerate(active_students_data[:15], 1):
    print(f"{idx}. {s['name']} ({s['roll']}) - Sec {s['section']} | Solved: {s['solved']} | Subs: {s['submissions']} | Runs: {s['runs']} | Time: {s['time_spent']//60}m")

# Show students who logged in but submitted 0 code
logged_no_sub = [s for s in active_students_data if s['submissions'] == 0]
print(f"\n--- STUDENTS WHO LOGGED IN BUT NEVER SUBMITTED CODE ({len(logged_no_sub)}) ---")
for s in logged_no_sub:
    print(f"  - {s['name']} ({s['roll']}) - Sec {s['section']} | Pwd Changed: {s['has_pwd_chg']} | Sessions opened: {s['sessions']}")

conn.close()
