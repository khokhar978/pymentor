"""
Hint Friction Engine for PyMentor.
Enforces pedagogical scaffolding via progressive ratio cycles:
Cycle 1: 3 Baby Steps -> 2 Guided -> 1 Challenge
Cycle 2: 6 Baby Steps -> 4 Guided -> 2 Challenge
Cycle 3: 12 Baby Steps -> 8 Guided -> 4 Challenge
(doubles each cycle)

If the student's profile default_help_level is 2 or higher:
Baby Steps are set to 0 (e.g. 0:2:1 -> 0:4:2).
If default_help_level is 3:
All hints are Level 3 (Challenge).
"""

LEVEL_INFO = {
    1: {"name": "Baby Steps", "icon": "🟢", "desc": "Step-by-step guidance"},
    2: {"name": "Guided", "icon": "🟡", "desc": "Conceptual hints & diagnostic questions"},
    3: {"name": "Challenge", "icon": "🔴", "desc": "Category nudges only"}
}


def compute_effective_level(submission_count: int, default_help_level: int = 1) -> dict:
    """
    Computes the server-enforced guidance level and progress state for a session.
    
    Args:
        submission_count: Number of submissions already recorded for this session.
        default_help_level: Student's profile preference (1, 2, or 3).
        
    Returns:
        dict with effective_level, level_label, level_icon, cycle,
        used_in_band, total_in_band, next_level_in, progress_text, badge_text
    """
    default_hl = default_help_level or 1
    sub_count = max(0, int(submission_count or 0))

    # Profile Level 3 (Challenge mode): strictly Level 3
    if default_hl >= 3:
        return {
            "effective_level": 3,
            "level_label": LEVEL_INFO[3]["name"],
            "level_icon": LEVEL_INFO[3]["icon"],
            "cycle": 1,
            "used_in_band": sub_count,
            "total_in_band": None,
            "next_level_in": None,
            "progress_text": "Challenge Mode",
            "badge_text": f"{LEVEL_INFO[3]['icon']} {LEVEL_INFO[3]['name']}"
        }

    # Base ratios
    # Level 1 student gets 3:2:1 base
    # Level 2 student gets 0:2:1 base
    base_l1 = 3 if default_hl == 1 else 0
    base_l2 = 2
    base_l3 = 1

    pos = sub_count
    cycle = 1

    while True:
        multiplier = 2 ** (cycle - 1)
        l1_count = base_l1 * multiplier
        l2_count = base_l2 * multiplier
        l3_count = base_l3 * multiplier
        cycle_total = l1_count + l2_count + l3_count

        if pos < cycle_total:
            # Within this cycle
            if pos < l1_count:
                used = pos
                total = l1_count
                rem = total - used
                return {
                    "effective_level": 1,
                    "level_label": LEVEL_INFO[1]["name"],
                    "level_icon": LEVEL_INFO[1]["icon"],
                    "cycle": cycle,
                    "used_in_band": used,
                    "total_in_band": total,
                    "next_level_in": rem,
                    "progress_text": f"{used + 1}/{total} hints in band ({rem - 1} left after this)" if rem > 1 else f"{total}/{total} (last one before Guided)",
                    "badge_text": f"{LEVEL_INFO[1]['icon']} {LEVEL_INFO[1]['name']} ({used + 1}/{total})"
                }
            elif pos < l1_count + l2_count:
                offset = pos - l1_count
                used = offset
                total = l2_count
                rem = total - used
                return {
                    "effective_level": 2,
                    "level_label": LEVEL_INFO[2]["name"],
                    "level_icon": LEVEL_INFO[2]["icon"],
                    "cycle": cycle,
                    "used_in_band": used,
                    "total_in_band": total,
                    "next_level_in": rem,
                    "progress_text": f"{used + 1}/{total} hints in band ({rem - 1} left after this)" if rem > 1 else f"{total}/{total} (last one before Challenge)",
                    "badge_text": f"{LEVEL_INFO[2]['icon']} {LEVEL_INFO[2]['name']} ({used + 1}/{total})"
                }
            else:
                offset = pos - l1_count - l2_count
                used = offset
                total = l3_count
                rem = total - used
                next_cycle = cycle + 1
                return {
                    "effective_level": 3,
                    "level_label": LEVEL_INFO[3]["name"],
                    "level_icon": LEVEL_INFO[3]["icon"],
                    "cycle": cycle,
                    "used_in_band": used,
                    "total_in_band": total,
                    "next_level_in": rem,
                    "progress_text": f"{used + 1}/{total} hints in band ({rem - 1} left after this)" if rem > 1 else f"Cycle {cycle} complete (Cycle {next_cycle} next)",
                    "badge_text": f"{LEVEL_INFO[3]['icon']} {LEVEL_INFO[3]['name']} ({used + 1}/{total})"
                }

        pos -= cycle_total
        cycle += 1
