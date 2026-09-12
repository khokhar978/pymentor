import sqlite3
import os
import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def build_student_data(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''
    SELECT 
        s.id, 
        s.roll_no, 
        s.name, 
        s.section, 
        s.needs_password_change, 
        s.is_active,
        (SELECT COUNT(*) FROM auth_tokens WHERE student_id = s.id) as token_count,
        (SELECT COUNT(*) FROM sessions WHERE student_id = s.id) as session_count,
        (SELECT COALESCE(SUM(time_spent_seconds), 0) FROM sessions WHERE student_id = s.id) as time_spent,
        (SELECT COALESCE(SUM(run_count), 0) FROM sessions WHERE student_id = s.id) as total_runs,
        (SELECT COUNT(*) FROM submissions sub JOIN sessions ses ON sub.session_id = ses.id WHERE ses.student_id = s.id) as sub_count,
        (SELECT COUNT(DISTINCT ses.problem_id) FROM submissions sub JOIN sessions ses ON sub.session_id = ses.id WHERE ses.student_id = s.id AND sub.is_correct = 1) as solved_count,
        (SELECT COUNT(DISTINCT DATE(created_at)) FROM sessions WHERE student_id = s.id) as active_days,
        (SELECT MAX(created_at) FROM sessions WHERE student_id = s.id) as last_sess,
        (SELECT COUNT(*) FROM events WHERE student_id = s.id) as event_count
    FROM students s
    ORDER BY s.section, s.roll_no
    ''')
    rows = c.fetchall()
    conn.close()

    students = []
    for r in rows:
        (s_id, roll, name, sec, needs_pwd, is_act, tokens, sessions, time_spent, runs, subs, solved, days, last_s, events) = r
        has_logged = (tokens > 0) or (events > 0) or (sessions > 0)
        has_pwd_changed = (needs_pwd == 0)
        is_touched = has_logged or has_pwd_changed or (sessions > 0) or (events > 0)

        # Categorization logic
        if not is_touched:
            category = "1. Never Used (Untouched)"
            status = "Deactivated"
            sub_reason = "Never logged in or changed default password"
        elif subs == 0:
            category = "2. Just Logged In / Password Changed (No Submissions)"
            status = "Deactivated"
            sub_reason = "Changed password but never submitted code"
        elif (sessions <= 1 and days <= 1 and runs <= 3 and subs <= 2 and solved <= 1 and time_spent < 600):
            category = "3. Minor Use (Used Only Once)"
            status = "Active"
            sub_reason = "Active (Single session exploration)"
        elif (solved >= 3 or runs >= 25 or subs >= 12 or time_spent >= 3000 or (days >= 2 and solved >= 2)):
            category = "5. Consistent / Frequent Use"
            status = "Active"
            sub_reason = "Active (Frequent coder & problem solver)"
        else:
            category = "4. Moderate / Mid Use"
            status = "Active"
            sub_reason = "Active (Multiple sessions & code submissions)"

        students.append({
            "id": s_id,
            "roll_no": roll,
            "name": name,
            "section": sec,
            "category": category,
            "status": status,
            "sub_reason": sub_reason,
            "logged_in": "Yes" if has_logged else "No",
            "pwd_changed": "Yes" if has_pwd_changed else "No",
            "sessions": sessions,
            "runs": runs,
            "submissions": subs,
            "solved": solved,
            "time_minutes": round(time_spent / 60, 1),
            "active_days": days,
            "last_activity": last_s if last_s else ("Account Setup Only" if has_pwd_changed else "Never")
        })

    return students

def generate_reports(db_path, master_excel_path, student_share_excel_path):
    students = build_student_data(db_path)
    active_coders = [s for s in students if s["status"] == "Active"]
    active_coders.sort(key=lambda x: (x["solved"], x["submissions"], x["runs"]), reverse=True)

    font_family = "Segoe UI"
    title_font = Font(name=font_family, size=16, bold=True, color="1E293B")
    subtitle_font = Font(name=font_family, size=10, italic=True, color="64748B")
    header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")
    bold_font = Font(name=font_family, size=9, bold=True, color="1E293B")
    regular_font = Font(name=font_family, size=9, color="334155")
    metric_num_font = Font(name=font_family, size=18, bold=True, color="0F172A")
    metric_lbl_font = Font(name=font_family, size=9, bold=True, color="64748B")

    navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    slate_fill = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    sec_e_fill = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid")
    sec_f_fill = PatternFill(start_color="059669", end_color="059669", fill_type="solid")
    sec_g_fill = PatternFill(start_color="7C3AED", end_color="7C3AED", fill_type="solid")

    cat_colors = {
        "1. Never Used (Untouched)": PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid"),
        "2. Just Logged In / Password Changed (No Submissions)": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),
        "3. Minor Use (Used Only Once)": PatternFill(start_color="E0E7FF", end_color="E0E7FF", fill_type="solid"),
        "4. Moderate / Mid Use": PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid"),
        "5. Consistent / Frequent Use": PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    }
    cat_font_colors = {
        "1. Never Used (Untouched)": Font(name=font_family, size=9, bold=True, color="991B1B"),
        "2. Just Logged In / Password Changed (No Submissions)": Font(name=font_family, size=9, bold=True, color="92400E"),
        "3. Minor Use (Used Only Once)": Font(name=font_family, size=9, bold=True, color="3730A3"),
        "4. Moderate / Mid Use": Font(name=font_family, size=9, bold=True, color="1E40AF"),
        "5. Consistent / Frequent Use": Font(name=font_family, size=9, bold=True, color="166534")
    }

    status_fill_deactive = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    status_font_deactive = Font(name=font_family, size=9, bold=True, color="B91C1C")
    status_fill_active = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    status_font_active = Font(name=font_family, size=9, bold=True, color="15803D")

    thin_border_side = Side(border_style="thin", color="E2E8F0")
    thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    # =============================================================
    # WORKBOOK 1: INSTRUCTOR MASTER REPORT
    # =============================================================
    wb_master = openpyxl.Workbook()
    wb_master.remove(wb_master.active)

    # 1. Executive Summary
    ws_sum = wb_master.create_sheet(title="Executive Summary")
    ws_sum.views.sheetView[0].showGridLines = True

    ws_sum["B2"] = "PyMentor — Student Engagement & Account Status Report"
    ws_sum["B2"].font = title_font
    ws_sum["B3"] = f"Generated on {datetime.datetime.now().strftime('%d %B %Y, %I:%M %p')} | Chitkara University BCA AI Batch"
    ws_sum["B3"].font = subtitle_font

    active_cnt = sum(1 for s in students if s['status'] == 'Active')
    deact_cnt = sum(1 for s in students if s['status'] == 'Deactivated')

    kpis = [
        ("Total Students", len(students), "B", "C"),
        ("Active Dedicated Coders", active_cnt, "D", "E"),
        ("Total Deactivated", deact_cnt, "F", "G"),
        ("Frequent Solvers", sum(1 for s in students if 'Frequent' in s['category']), "H", "I"),
    ]
    card_bg = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    card_border = Border(
        left=Side(border_style="thin", color="CBD5E1"),
        right=Side(border_style="thin", color="CBD5E1"),
        top=Side(border_style="thin", color="CBD5E1"),
        bottom=Side(border_style="thin", color="CBD5E1")
    )

    for title, val, c1, c2 in kpis:
        ws_sum.merge_cells(f"{c1}5:{c2}5")
        ws_sum.merge_cells(f"{c1}6:{c2}6")
        cell_val = ws_sum[f"{c1}5"]
        cell_lbl = ws_sum[f"{c1}6"]
        cell_val.value = val
        cell_val.font = metric_num_font
        cell_val.alignment = Alignment(horizontal="center", vertical="center")
        cell_lbl.value = title.upper()
        cell_lbl.font = metric_lbl_font
        cell_lbl.alignment = Alignment(horizontal="center", vertical="center")

        for r in range(5, 7):
            for col_l in [c1, c2]:
                c_obj = ws_sum[f"{col_l}{r}"]
                c_obj.fill = card_bg
                c_obj.border = card_border

    # Category Breakdown Table
    ws_sum["B9"] = "CATEGORY BREAKDOWN (ALL 5 TIERS)"
    ws_sum["B9"].font = Font(name=font_family, size=11, bold=True, color="1E3A8A")

    cat_headers = ["Category / Tier", "Student Count", "% of Batch", "Sec E", "Sec F", "Sec G", "Action / Account Status"]
    for col_idx, h in enumerate(cat_headers, start=2):
        cell = ws_sum.cell(row=10, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    all_cats = [
        ("1. Never Used (Untouched)", "Deactivated (0 logins, 0 sessions, 0 submissions)"),
        ("2. Just Logged In / Password Changed (No Submissions)", "Deactivated (Changed password only, 0 submissions)"),
        ("3. Minor Use (Used Only Once)", "Active (Single session, 1-2 submissions)"),
        ("4. Moderate / Mid Use", "Active (Multiple sessions, 2-10 submissions)"),
        ("5. Consistent / Frequent Use", "Active (Frequent coder, multiple problems solved)")
    ]

    for row_idx, (cat_name, action_desc) in enumerate(all_cats, start=11):
        cnt = sum(1 for s in students if s['category'] == cat_name)
        pct = f"{cnt / len(students) * 100:.1f}%"
        cnt_e = sum(1 for s in students if s['category'] == cat_name and s['section'] == 'E')
        cnt_f = sum(1 for s in students if s['category'] == cat_name and s['section'] == 'F')
        cnt_g = sum(1 for s in students if s['category'] == cat_name and s['section'] == 'G')

        ws_sum.cell(row=row_idx, column=2, value=cat_name).font = cat_font_colors[cat_name]
        ws_sum.cell(row=row_idx, column=2).fill = cat_colors[cat_name]
        ws_sum.cell(row=row_idx, column=3, value=cnt).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=row_idx, column=4, value=pct).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=row_idx, column=5, value=cnt_e).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=row_idx, column=6, value=cnt_f).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=row_idx, column=7, value=cnt_g).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=row_idx, column=8, value=action_desc)

        for col_i in range(2, 9):
            c_cell = ws_sum.cell(row=row_idx, column=col_i)
            c_cell.border = thin_border
            if col_i > 2:
                c_cell.font = regular_font

    # Section Comparison Table
    ws_sum["B18"] = "SECTION COMPARISON SUMMARY (ACTIVE CODERS VS DEACTIVATED)"
    ws_sum["B18"].font = Font(name=font_family, size=11, bold=True, color="1E3A8A")

    sec_headers = ["Section", "Total Students", "Active Coders", "Active %", "Deactivated", "Deactivated %", "Top Section Superstars"]
    for col_idx, h in enumerate(sec_headers, start=2):
        cell = ws_sum.cell(row=19, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = slate_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    sec_data = [
        ("Section F", "F", 63, "Rimjhim (24 solved), Nirmal (13 solved), Paarth (11 solved), Nishant (7 solved)"),
        ("Section E", "E", 61, "Himanshu Gautam (2 solved), Harmanpreet (2 solved), Harshit Sood (2 solved)"),
        ("Section G", "G", 60, "Daksh Verma (27 solved - Batch Topper!), Kanav Garg (5 solved)")
    ]

    for r_i, (sec_lbl, sec_code, tot, stars) in enumerate(sec_data, start=20):
        s_act_cnt = sum(1 for s in students if s['section'] == sec_code and s['status'] == 'Active')
        s_deact_cnt = sum(1 for s in students if s['section'] == sec_code and s['status'] == 'Deactivated')
        s_act_pct = f"{s_act_cnt / tot * 100:.1f}%"
        s_deact_pct = f"{s_deact_cnt / tot * 100:.1f}%"

        ws_sum.cell(row=r_i, column=2, value=sec_lbl).font = bold_font
        ws_sum.cell(row=r_i, column=3, value=tot).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=r_i, column=4, value=s_act_cnt).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=r_i, column=5, value=s_act_pct).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=r_i, column=6, value=s_deact_cnt).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=r_i, column=7, value=s_deact_pct).alignment = Alignment(horizontal="center")
        ws_sum.cell(row=r_i, column=8, value=stars)

        for col_i in range(2, 9):
            c_cell = ws_sum.cell(row=r_i, column=col_i)
            c_cell.border = thin_border
            if col_i not in [2, 8]:
                c_cell.font = regular_font
            elif col_i == 8:
                c_cell.font = Font(name=font_family, size=9, italic=True, color="0F766E")

    col_widths_sum = {"B": 34, "C": 14, "D": 16, "E": 14, "F": 14, "G": 14, "H": 50, "I": 12}
    for col, width in col_widths_sum.items():
        ws_sum.column_dimensions[col].width = width

    # Helper function for student rosters
    def write_student_sheet(ws, title, student_subset, header_bg):
        ws.views.sheetView[0].showGridLines = True
        ws["A1"] = title
        ws["A1"].font = title_font
        ws["A2"] = f"Total Students Listed: {len(student_subset)} | Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ws["A2"].font = subtitle_font

        headers = [
            "S.No", "Roll No", "Student Name", "Sec", "Category / Engagement Tier",
            "Account Status", "Logged In?", "Password Changed?", "Problem Sessions",
            "Code Runs", "Submissions", "Solved Correctly", "Practice Time (min)",
            "Active Days", "Last Activity"
        ]

        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_bg
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.row_dimensions[4].height = 28

        for row_idx, s in enumerate(student_subset, start=5):
            ws.cell(row=row_idx, column=1, value=row_idx-4).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=2, value=s["roll_no"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=3, value=s["name"]).font = bold_font
            ws.cell(row=row_idx, column=4, value=s["section"]).alignment = Alignment(horizontal="center")
            
            cat_cell = ws.cell(row=row_idx, column=5, value=s["category"])
            cat_cell.font = cat_font_colors.get(s["category"], regular_font)
            cat_cell.fill = cat_colors.get(s["category"], PatternFill(fill_type=None))

            status_cell = ws.cell(row=row_idx, column=6, value=s["status"])
            status_cell.alignment = Alignment(horizontal="center")
            if s["status"] == "Deactivated":
                status_cell.fill = status_fill_deactive
                status_cell.font = status_font_deactive
            else:
                status_cell.fill = status_fill_active
                status_cell.font = status_font_active

            ws.cell(row=row_idx, column=7, value=s["logged_in"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=8, value=s["pwd_changed"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=9, value=s["sessions"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=10, value=s["runs"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=11, value=s["submissions"]).alignment = Alignment(horizontal="center")
            
            solved_cell = ws.cell(row=row_idx, column=12, value=s["solved"])
            solved_cell.alignment = Alignment(horizontal="center")
            if s["solved"] > 0:
                solved_cell.font = Font(name=font_family, size=9, bold=True, color="047857")

            ws.cell(row=row_idx, column=13, value=s["time_minutes"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=14, value=s["active_days"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=15, value=str(s["last_activity"])).alignment = Alignment(horizontal="left")

            for col_i in range(1, 16):
                cell = ws.cell(row=row_idx, column=col_i)
                cell.border = thin_border
                if col_i not in [3, 5, 6, 12]:
                    cell.font = regular_font

        widths = [6, 14, 26, 6, 38, 16, 12, 16, 14, 12, 13, 14, 16, 12, 22]
        for idx, w in enumerate(widths, start=1):
            col_letter = get_column_letter(idx)
            ws.column_dimensions[col_letter].width = w

    # Sheets 2-6
    ws_all = wb_master.create_sheet(title="All Students Master")
    write_student_sheet(ws_all, "All 184 Students — Complete Engagement Master List", students, navy_fill)

    ws_f = wb_master.create_sheet(title="Section F")
    write_student_sheet(ws_f, "Section F — Class Roster (32 Active Coders)", [s for s in students if s['section'] == 'F'], sec_f_fill)

    ws_e = wb_master.create_sheet(title="Section E")
    write_student_sheet(ws_e, "Section E — Class Roster (7 Active Coders)", [s for s in students if s['section'] == 'E'], sec_e_fill)

    ws_g = wb_master.create_sheet(title="Section G")
    write_student_sheet(ws_g, "Section G — Class Roster (3 Active Coders)", [s for s in students if s['section'] == 'G'], sec_g_fill)

    ws_deact = wb_master.create_sheet(title="Deactivated Accounts (142)")
    write_student_sheet(ws_deact, "Deactivated Accounts (142 Students with 0 Submissions)", [s for s in students if s['status'] == 'Deactivated'], PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid"))

    # Sheet 7: Practice Slot Consensus
    try:
        from app.student_practice_sheet import create_student_practice_sheet
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from student_practice_sheet import create_student_practice_sheet
    create_student_practice_sheet(wb_master, active_coders)

    # Sheet 8: Top Consistent Coders
    ws_top = wb_master.create_sheet(title="Top Consistent Coders")
    write_student_sheet(ws_top, "Top Active Students & Consistent Solvers", active_coders, PatternFill(start_color="047857", end_color="047857", fill_type="solid"))

    os.makedirs(os.path.dirname(os.path.abspath(master_excel_path)), exist_ok=True)
    try:
        wb_master.save(master_excel_path)
        print(f"Successfully saved Master Report: {master_excel_path}")
    except PermissionError:
        base, ext = os.path.splitext(master_excel_path)
        fallback_path = f"{base}_Latest{ext}"
        wb_master.save(fallback_path)
        print(f"Original file was open in Excel. Successfully saved Master Report to: {fallback_path}")

    # =============================================================
    # WORKBOOK 2: STUDENT-FACING PRACTICE GROUP FILE (SHAREABLE)
    # =============================================================
    wb_share = openpyxl.Workbook()
    wb_share.remove(wb_share.active)
    create_student_practice_sheet(wb_share, active_coders, is_standalone=True)
    try:
        wb_share.save(student_share_excel_path)
        print(f"Successfully saved Shareable Student File: {student_share_excel_path}")
    except PermissionError:
        base, ext = os.path.splitext(student_share_excel_path)
        fallback_share = f"{base}_Latest{ext}"
        wb_share.save(fallback_share)
        print(f"Successfully saved Shareable Student File to: {fallback_share}")

if __name__ == "__main__":
    db_path = r"c:\Users\hp\Desktop\lecture\downloaded_db\pymentor_live_latest.db"
    master_path = r"c:\Users\hp\Desktop\lecture\PyMentor_Student_Engagement_Report.xlsx"
    share_path = r"c:\Users\hp\Desktop\lecture\PyMentor_Dedicated_Practice_Group.xlsx"
    generate_reports(db_path, master_path, share_path)
