import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import os
import datetime

def create_student_practice_sheet(wb, active_students, is_standalone=False):
    ws = wb.create_sheet(title="Practice Schedule Consensus")
    ws.views.sheetView[0].showGridLines = True

    font_family = "Segoe UI"
    title_font = Font(name=font_family, size=15, bold=True, color="0F172A")
    subtitle_font = Font(name=font_family, size=10, italic=True, color="475569")
    section_title_font = Font(name=font_family, size=11, bold=True, color="1E3A8A")
    header_font = Font(name=font_family, size=9, bold=True, color="FFFFFF")
    bold_font = Font(name=font_family, size=9, bold=True, color="1E293B")
    regular_font = Font(name=font_family, size=9, color="334155")

    # Colors
    navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    blue_accent = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    emerald_fill = PatternFill(start_color="059669", end_color="059669", fill_type="solid")
    amber_fill = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid")
    light_blue_fill = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")
    light_green_fill = PatternFill(start_color="F0FDF4", end_color="F0FDF4", fill_type="solid")
    light_amber_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    card_bg = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    thin_border_side = Side(border_style="thin", color="CBD5E1")
    thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    callout_border = Border(left=Side(border_style="medium", color="2563EB"), right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    # 1. Main Banner
    ws["B2"] = "PyMentor — Dedicated Practice Group & Schedule Coordination"
    ws["B2"].font = title_font
    ws["B3"] = f"Chitkara University | BCA AI Batch | Updated on {datetime.datetime.now().strftime('%d %B %Y')}"
    ws["B3"].font = subtitle_font

    # 2. Instructor Announcement Box (Open-ended, no fixed slots, Google Form friendly)
    ws.merge_cells("B5:K9")
    msg_cell = ws["B5"]
    msg_cell.value = (
        f"📢 INSTRUCTOR NOTICE TO DEDICATED PYMENTOR CODERS (ALL {len(active_students)} ACTIVE STUDENTS):\n"
        "Congratulations on actively writing, testing, and submitting code on PyMentor! "
        "Because PyMentor is hosted on a dedicated system, we will no longer run it 24/7 idle. Instead, it will be powered on daily during a focused live practice window.\n"
        "• NO FIXED SLOTS ARE IMPOSED: You are free to propose whatever time range suits your routine.\n"
        "• SUBMISSION: Submit your preferred daily hours (e.g. 7:30 PM – 10:00 PM, 9:00 PM – 11:30 PM, etc.) directly in this sheet or via the shared Google Form.\n"
        "• EVALUATION & PREFERENCE: To ensure fairness, higher preference will be given to students who have invested more practice time and effort on the platform. The consensus window will be announced once all responses are in."
    )
    msg_cell.font = Font(name=font_family, size=9, color="1E3A8A")
    msg_cell.alignment = Alignment(wrap_text=True, vertical="top")

    for r in range(5, 10):
        for c in range(2, 12):
            cell = ws.cell(row=r, column=c)
            cell.fill = light_blue_fill
            cell.border = thin_border
    ws["B5"].border = callout_border

    # 3. Schedule Preference Criteria & Priority Weighting Guide
    ws["B11"] = "HOW PRACTICE HOURS WILL BE EVALUATED (PRIORITY TIERS)"
    ws["B11"].font = section_title_font

    guide_headers = ["Priority Tier", "Qualification Criteria", "Weight in Schedule Finalization", "Number of Coders"]
    for c_i, h in enumerate(guide_headers, start=2):
        cell = ws.cell(row=12, column=c_i, value=h)
        cell.font = header_font
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    tier_1_cnt = sum(1 for s in active_students if s["time_minutes"] >= 60 or s["solved"] >= 5)
    tier_2_cnt = sum(1 for s in active_students if (s["time_minutes"] >= 25 or s["solved"] >= 2 or s["runs"] >= 20) and s not in [x for x in active_students if x["time_minutes"] >= 60 or x["solved"] >= 5])
    tier_3_cnt = len(active_students) - tier_1_cnt - tier_2_cnt

    guides = [
        ("Tier 1: High Priority (Power Users)", "Invested 60+ mins of practice OR solved 5+ problems", "Highest Weight (Core Window anchored around their availability)", f"{tier_1_cnt} students"),
        ("Tier 2: Medium Priority (Consistent Users)", "Invested 25-60 mins OR solved 2-4 problems OR 20+ runs", "Medium Weight (Window adjusted to maximize their overlap)", f"{tier_2_cnt} students"),
        ("Tier 3: Standard Priority (Active Starters)", "Submitted 1-2 problems / early practice", "Standard Weight (Encouraged to join the finalized group window)", f"{tier_3_cnt} students")
    ]

    for r_i, g_data in enumerate(guides, start=13):
        for c_i, val in enumerate(g_data, start=2):
            cell = ws.cell(row=r_i, column=c_i, value=val)
            cell.border = thin_border
            if c_i == 2:
                cell.font = bold_font
            else:
                cell.font = regular_font
            if c_i in [2, 5]:
                cell.alignment = Alignment(horizontal="center")

    # 4. Qualified Active Coders Roster (Ranked by Practice Time & Engagement)
    # Sort active students primarily by practice time descending, then solved, then submissions
    active_students_ranked = sorted(active_students, key=lambda x: (x["time_minutes"], x["solved"], x["runs"], x["submissions"]), reverse=True)

    ws["B18"] = f"ACTIVE CODERS ROSTER — SUBMIT YOUR PREFERRED TIME RANGE (ALL {len(active_students_ranked)} STUDENTS)"
    ws["B18"].font = section_title_font

    roster_headers = [
        "Priority Rank", "Roll Number", "Student Name", "Sec", "Practice Time",
        "Code Runs", "Solved", "Submissions", "Priority Weight", "Your Preferred Time Range (e.g. 8 PM - 10:30 PM)", "Preferred Days / Remarks"
    ]
    for c_i, h in enumerate(roster_headers, start=2):
        cell = ws.cell(row=19, column=c_i, value=h)
        cell.font = header_font
        cell.fill = emerald_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.row_dimensions[19].height = 28

    for idx, s in enumerate(active_students_ranked, start=1):
        r_i = 19 + idx
        ws.cell(row=r_i, column=2, value=idx).alignment = Alignment(horizontal="center")
        ws.cell(row=r_i, column=3, value=s["roll_no"]).alignment = Alignment(horizontal="center")
        ws.cell(row=r_i, column=4, value=s["name"]).font = bold_font
        ws.cell(row=r_i, column=5, value=s["section"]).alignment = Alignment(horizontal="center")
        
        # Practice time highlighted
        time_cell = ws.cell(row=r_i, column=6, value=f"{s['time_minutes']} mins")
        time_cell.alignment = Alignment(horizontal="center")
        if s["time_minutes"] >= 60:
            time_cell.font = Font(name=font_family, size=9, bold=True, color="047857")

        ws.cell(row=r_i, column=7, value=s["runs"]).alignment = Alignment(horizontal="center")
        
        solved_cell = ws.cell(row=r_i, column=8, value=s["solved"])
        solved_cell.alignment = Alignment(horizontal="center")
        if s["solved"] > 0:
            solved_cell.font = Font(name=font_family, size=9, bold=True, color="047857")

        ws.cell(row=r_i, column=9, value=s["submissions"]).alignment = Alignment(horizontal="center")
        
        # Priority Weight Badge
        if s["time_minutes"] >= 60 or s["solved"] >= 5:
            p_weight = "⭐ High (Top Contributor)"
            p_font = Font(name=font_family, size=9, bold=True, color="92400E")
            p_fill = light_amber_fill
        elif s["time_minutes"] >= 25 or s["solved"] >= 2 or s["runs"] >= 20:
            p_weight = "🟢 Medium (Consistent)"
            p_font = Font(name=font_family, size=9, bold=True, color="166534")
            p_fill = light_green_fill
        else:
            p_weight = "🔵 Standard (Active)"
            p_font = Font(name=font_family, size=9, color="1E40AF")
            p_fill = light_blue_fill

        weight_cell = ws.cell(row=r_i, column=10, value=p_weight)
        weight_cell.alignment = Alignment(horizontal="center")
        weight_cell.font = p_font
        weight_cell.fill = p_fill

        # Blank input columns for student response / Google form recording
        ws.cell(row=r_i, column=11, value="").alignment = Alignment(horizontal="center")
        ws.cell(row=r_i, column=12, value="").alignment = Alignment(horizontal="left")

        for c_i in range(2, 13):
            cell = ws.cell(row=r_i, column=c_i)
            cell.border = thin_border
            if c_i not in [4, 6, 8, 10]:
                cell.font = regular_font

    col_widths = {
        "A": 4, "B": 12, "C": 15, "D": 26, "E": 6, "F": 16,
        "G": 12, "H": 10, "I": 13, "J": 25, "K": 34, "L": 26
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    return ws
