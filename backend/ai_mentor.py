"""
AI Mentoring Engine using Google GenAI with multi-model fallback cascade,
context-aware progression tracking, and 3 Socratic guidance levels.
"""

import os
import re
import difflib
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from google import genai

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(dotenv_path=env_path)
load_dotenv()

try:
    from pymentor.backend.quota_manager import (
        get_available_models,
        get_available_report_models,
        record_model_usage,
        record_model_rate_limited,
        MODEL_CONFIGS
    )
except ImportError:
    from backend.quota_manager import (
        get_available_models,
        get_available_report_models,
        record_model_usage,
        record_model_rate_limited,
        MODEL_CONFIGS
    )

FALLBACK_MODELS = [cfg["model"] for cfg in MODEL_CONFIGS]

logger = logging.getLogger("pymentor.ai")

def get_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

def get_client():
    key = get_api_key()
    if not key:
        return None
    return genai.Client(api_key=key)


# ─────────────────────────────────────────────
# COMPONENT 2: DETERMINISTIC CRASH DETECTION
# ─────────────────────────────────────────────

_CRASH_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"\b\w*Error\b:",          # ValueError:, TypeError:, SyntaxError:, NameError:, etc.
    r"\b\w*Exception\b:",
]

def detect_crash(simulated_output: str) -> bool:
    """
    Deterministic check: does the terminal output contain a Python crash signature?
    Pure pattern-matching, no AI involvement. Returns True if a crash is detected.
    This is used to hard-override any AI 'SOLVED' verdict when the code actually crashed.
    """
    if not simulated_output or not simulated_output.strip():
        return False
    return any(re.search(pattern, simulated_output) for pattern in _CRASH_PATTERNS)


# ─────────────────────────────────────────────
# COMPONENT 3: STRUCTURAL SIMILARITY SCORE
# ─────────────────────────────────────────────

def normalize_output(text: str) -> str:
    """Normalize output for structural comparison: strip whitespace variants, lowercase."""
    text = text.strip()
    text = re.sub(r'[ \t]+', ' ', text)       # collapse repeated spaces/tabs
    text = re.sub(r'\n{2,}', '\n', text)       # collapse repeated blank lines
    return text.lower()

def similarity_score(expected: str, actual: str) -> float:
    """
    Compute structural similarity (0–100%) between expected sample output and
    actual terminal output. Advisory only — handed to the AI as evidence,
    not used as a hard gate, because valid solutions with different inputs
    will legitimately differ from sample text.
    """
    a, b = normalize_output(expected), normalize_output(actual)
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio() * 100, 1)


# ─────────────────────────────────────────────
# BUILD PROMPT
# ─────────────────────────────────────────────

def build_prompt(
    student_name: str,
    section: str,
    problem: Dict[str, Any],
    help_level: int,
    current_code: str,
    history: List[Dict[str, Any]],
    simulated_output: Optional[str] = None
) -> str:
    level_names = {
        1: "Baby Steps (Level 1) - Very Gentle & Step-by-Step",
        2: "Guided (Level 2) - Conceptual & Targeted Questions",
        3: "Challenge (Level 3) - Minimal Nudges & Independent Thinking"
    }
    help_level_desc = level_names.get(help_level, level_names[1])

    # COMPONENT 6: History is context for narrative only — not for verdict
    history_text = ""
    if history:
        history_text += "\n--- PREVIOUS ATTEMPTS IN THIS SESSION (for context / acknowledging progress ONLY) ---\n"
        for idx, item in enumerate(history, 1):
            history_text += f"\n[Attempt #{item.get('attempt_number', idx)}]\n"
            history_text += f"Student Code:\n```python\n{item.get('code', '')}\n```\n"
            history_text += f"Previous Feedback:\n{item.get('ai_response', '')}\n"
    else:
        history_text = "\n(This is the student's first attempt on this problem.)\n"

    run_output_section = ""
    if simulated_output:
        run_output_section = (
            "\n=== WHAT APPEARED IN THE TERMINAL WHEN THE CODE WAS RUN ===\n"
            f"{simulated_output}\n\n"
            "IMPORTANT — Reference the ACTUAL values above (not hypothetical ones) in your feedback. For example:\n"
            "- 'Notice when you ran the code, the output showed [quote the actual output line] — that means...'\n"
            "- 'The error says [quote the actual error line] which tells us...'\n"
            "Cross-check: if the actual output is functionally correct (same logic, same values, same structure), lean toward [STATUS: SOLVED].\n"
            "Do NOT fail a student for cosmetic differences like different capitalization, punctuation, trailing spaces, or minor formatting variations.\n"
            "If the core logic and numeric/string values are correct, it is SOLVED even if spacing or casing differs slightly.\n"
        )

    # COMPONENT 3: Similarity score as soft evidence
    sim_score_section = ""
    if simulated_output and problem.get("sample_output"):
        score = similarity_score(problem["sample_output"], simulated_output)
        sim_score_section = (
            "\n=== OUTPUT SIMILARITY TO SAMPLE (computed, not your judgment) ===\n"
            f"{score}% structural match against the expected sample output.\n"
            "GRADING RULE (follow strictly):\n"
            "- Score >= 91%: The output is functionally correct. Mark [STATUS: SOLVED] UNLESS the core logic is fundamentally broken (e.g. hardcoded answers, crash, wrong formula).\n"
            "- Score 70–90%: Likely a minor issue (formatting, extra/missing line). Give targeted feedback as IN_PROGRESS but acknowledge the code is close.\n"
            "- Score < 70%: Significant logic or output mismatch. Mark IN_PROGRESS and guide the student.\n"
            "IMPORTANT: Cosmetic differences (capitalization, punctuation, trailing whitespace, minor decimal precision if not explicitly required) MUST NOT cause a failure. Judge on logic and values, not cosmetics.\n\n"
        )

    # COMPONENT 4: Reference solution as grounding context (if provided)
    reference_section = ""
    ref_solution = problem.get("reference_solution", "")
    if ref_solution and ref_solution.strip():
        reference_section = (
            "\n=== REFERENCE SOLUTION (for your understanding only — NEVER show this to the student, "
            "and do not penalize a different but valid approach) ===\n"
            f"{ref_solution}\n\n"
        )

    # Teacher live instructions for this specific problem (if provided)
    teacher_section = ""
    teacher_instructions = problem.get("teacher_instructions", "")
    if teacher_instructions and teacher_instructions.strip():
        teacher_section = (
            "=== INSTRUCTOR INSTRUCTIONS FOR THIS PROBLEM ===\n"
            f"{teacher_instructions.strip()}\n\n"
        )

    # COMPONENT 5: Per-level instructions with genuinely different word budgets AND what gets revealed
    level_instructions_map = {
        1: (
            "\nHELP LEVEL 1 INSTRUCTIONS (Baby Steps) — budget: up to 70 words.\n"
            "- Absolute beginner. Use simple, direct, encouraging English.\n"
            "- Quote the exact line number AND the exact expected-vs-actual value if available.\n"
            "- Break the fix into one tiny, concrete next action.\n"
            "- ALWAYS describe the REAL-WORLD screen effect of the mistake.\n"
            "- Give a direct leading question or tiny hint so they can fix it.\n"
            "- It is fine to be this explicit — the goal is momentum, not independence.\n"
            "- NEVER write out the full solution code!\n"
        ),
        2: (
            "\nHELP LEVEL 2 INSTRUCTIONS (Guided) — budget: up to 45 words.\n"
            "- Name WHICH concept or section is off (e.g. 'your discount calculation'), "
            "but do NOT quote the exact line number or exact expected value.\n"
            "- Ask one question that requires the student to locate the issue themselves.\n"
            "- Acknowledge what they fixed and move to the next problem.\n"
            "- NEVER write out the full solution code!\n"
        ),
        3: (
            "\nHELP LEVEL 3 INSTRUCTIONS (Challenge) — budget: up to 25 words.\n"
            "- State only THAT something is wrong and in which general area (input handling / "
            "logic / output formatting) — no specifics, no line numbers, no line-level hints.\n"
            "- Let the similarity score and their own output be their only real clue.\n"
        ),
    }
    level_instructions = level_instructions_map.get(help_level, level_instructions_map[1])

    prompt = (
        "You are a clear, patient, and encouraging computer science teacher and lab mentor "
        "for 1st-semester BCA students.\n\n"
        "=== TONE & LANGUAGE ===\n"
        "- Use clear, simple, direct English like an approachable college lab teacher.\n"
        "- Natural classroom phrasing: 'See, look at line X...', 'Notice one thing here...', 'What is happening is...'\n"
        "- STRICT RULE 1: NO Hindi or romanized Hindi words (no achha, arre, shabash, bilkul). Standard English only.\n"
        "- STRICT RULE 2: Do NOT mention or address the student by name. Start with a neutral phrase like 'Good start!' or 'You are on the right track!'.\n\n"
        "=== TEACHER INSTRUCTIONS ===\n"
        "1. Do NOT write the complete working solution code.\n"
        "2. RESPONSE STYLE:\n"
        "   - No fluff or generic filler.\n"
        "   - ALWAYS explain the PRACTICAL EFFECT of the mistake (what the student sees on screen).\n"
        "   - If simulated output is provided, ALWAYS reference the actual values that appeared.\n"
        "   - Highlight exact line and give one actionable next step or question.\n"
        "3. Accept ANY valid logic approach.\n"
        "4. Briefly acknowledge changes from previous attempt if any.\n"
        "5. Focus on ONE most important roadblock.\n"
        "6. Evaluate if the code fully solves the problem:\n"
        "   - FULLY CORRECT: First line must be `[STATUS: SOLVED]` then concise praise (max 2 sentences).\n"
        "   - NOT CORRECT/INCOMPLETE: First line must be `[STATUS: IN_PROGRESS]` then guidance.\n\n"
        # COMPONENT 6: Explicit instruction to not anchor verdict on history
        "=== CRITICAL: VERDICT SOURCE OF TRUTH ===\n"
        "Your [STATUS] verdict must be based ONLY on the CURRENT attempt's code and CURRENT "
        "simulated output below — never on what a previous attempt looked like. "
        "Use the attempt history ONLY to acknowledge progress in your praise/feedback text, "
        "never to inform whether this attempt is correct.\n\n"
        f"=== PROBLEM ===\n"
        f"Title: {problem['title']}\n"
        f"Topic: {problem['topic']}\n"
        f"Difficulty: {problem['difficulty']}\n"
        f"Description:\n{problem['description']}\n\n"
        f"Sample Input:\n{problem['sample_input']}\n\n"
        f"Sample Output:\n{problem['sample_output']}\n\n"
        f"=== RUBRIC ===\n{problem['ai_rubric']}\n\n"
        f"{teacher_section}"
        f"{reference_section}"
        f"=== GUIDANCE LEVEL ===\n{help_level_desc}\n{level_instructions}\n"
        f"{run_output_section}"
        f"{sim_score_section}"
        f"{history_text}\n"
        f"=== STUDENT'S CURRENT CODE (Attempt #{len(history) + 1}) ===\n"
        f"```python\n{current_code}\n```\n\n"
        "Provide feedback. First line MUST be `[STATUS: SOLVED]` or `[STATUS: IN_PROGRESS]`.\n"
    )
    return prompt


# ─────────────────────────────────────────────
# EVALUATE CODE
# ─────────────────────────────────────────────

# Placeholder text for failed API calls stored in history
# COMPONENT 7: Don't pollute future prompts with raw error strings
_FAILED_ATTEMPT_PLACEHOLDER = "(A temporary issue prevented feedback on this attempt.)"

def evaluate_code(
    student_name: str,
    section: str,
    problem: Dict[str, Any],
    help_level: int,
    current_code: str,
    history: List[Dict[str, Any]],
    simulated_output: Optional[str] = None
) -> Dict[str, Any]:
    client = get_client()
    if not client:
        return {
            "is_correct": False,
            "feedback": "**API key not configured.** Please contact your instructor.",
            "model_used": "none",
            "error": "API_KEY_MISSING",
            "store_as_placeholder": False
        }

    prompt = build_prompt(
        student_name=student_name,
        section=section,
        problem=problem,
        help_level=help_level,
        current_code=current_code,
        history=history,
        simulated_output=simulated_output
    )

    candidate_models = get_available_models()
    last_error = None
    for model_name in candidate_models:
        try:
            logger.info(f"Calling model: {model_name} for guidance...")
            response = client.models.generate_content(model=model_name, contents=prompt)
            raw_text = response.text.strip() if response.text else ""
            if not raw_text:
                continue

            record_model_usage(model_name)

            is_correct = False
            feedback_text = raw_text

            if raw_text.startswith("[STATUS: SOLVED]"):
                is_correct = True
                feedback_text = raw_text.replace("[STATUS: SOLVED]", "").strip()
            elif raw_text.startswith("[STATUS: IN_PROGRESS]"):
                is_correct = False
                feedback_text = raw_text.replace("[STATUS: IN_PROGRESS]", "").strip()
            else:
                if "STATUS: SOLVED" in raw_text[:60]:
                    is_correct = True
                    feedback_text = re.sub(r"\[?STATUS:\s*SOLVED\]?", "", raw_text).strip()
                elif "STATUS: IN_PROGRESS" in raw_text[:60]:
                    is_correct = False
                    feedback_text = re.sub(r"\[?STATUS:\s*IN_PROGRESS\]?", "", raw_text).strip()

            # COMPONENT 2: Hard crash override — AI cannot mark a crashing submission as SOLVED
            crashed = detect_crash(simulated_output)
            if crashed and is_correct:
                logger.warning(
                    f"[CRASH-OVERRIDE] AI marked SOLVED on a crashing output — verdict overridden to IN_PROGRESS. "
                    f"problem={problem.get('id', '?')}, model={model_name}"
                )
                is_correct = False
                # Keep the AI's feedback text — it's usually still useful explanation of what went wrong

            return {
                "is_correct": is_correct,
                "feedback": feedback_text,
                "model_used": model_name,
                "error": None,
                "store_as_placeholder": False
            }
        except Exception as e:
            error_str = str(e)
            logger.warning(f"Model {model_name} failed: {error_str}")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                record_model_rate_limited(model_name, error_str)
            last_error = error_str
            continue

    logger.error(f"All AI fallback models failed to evaluate submission. Last error: {last_error}")
    return {
        "is_correct": False,
        "feedback": "AI guidance is temporarily unavailable. Please wait a few moments and click **Submit / Guidance** again.",
        "model_used": "failed",
        "error": "AI service temporarily unavailable",
        # COMPONENT 7: Signal to caller to store placeholder in DB instead of error text
        "store_as_placeholder": True,
        "placeholder_text": _FAILED_ATTEMPT_PLACEHOLDER
    }


# ─────────────────────────────────────────────
# LEARNING REPORT — COMPLETELY SEPARATE SYSTEM
# Not connected to guidance/evaluation logic in any way.
# ─────────────────────────────────────────────
# Model selection is fully delegated to the quota manager via get_available_report_models().
# Only premium models (uses='both') are ever considered — never flash-lite or Gemma.

def build_learning_report_prompt(
    problem: Dict[str, Any],
    submissions: List[Dict[str, Any]]
) -> str:
    """
    Build a prompt that compiles all of a student's attempts for a problem
    into a structured learning debrief. Completely separate from guidance prompts.
    """
    problem_section = (
        f"=== PROBLEM ===\n"
        f"Title: {problem.get('title', 'Unknown')}\n"
        f"Topic: {problem.get('topic', '')}\n"
        f"Description:\n{problem.get('description', '')}\n\n"
        f"Sample Input:\n{problem.get('sample_input', '')}\n\n"
        f"Sample Output:\n{problem.get('sample_output', '')}\n\n"
    )

    attempts_section = "=== STUDENT'S FULL ATTEMPT HISTORY ===\n"
    for idx, sub in enumerate(submissions, 1):
        is_final = (idx == len(submissions))
        label = f"[Attempt #{idx}{'  ← FINAL (SOLVED)' if is_final else ''}]"
        attempts_section += f"\n{label}\n"
        attempts_section += f"Code:\n```python\n{sub.get('code', '(no code)')}\n```\n"
        sim_out = sub.get("simulated_output", "").strip()
        if sim_out:
            attempts_section += f"Terminal Output:\n{sim_out}\n"
        ai_resp = sub.get("ai_response", "").strip()
        if ai_resp and not is_final:
            attempts_section += f"Feedback Given:\n{ai_resp}\n"

    report_instructions = (
        "=== YOUR TASK ===\n"
        "Write a structured, personal learning debrief for this student. "
        "Your goal is to help them deeply understand what happened in this session — not just list concepts, "
        "but explain WHY things work the way they do using the student's own code and output as evidence.\n\n"
        "FORMAT (use these exact headings):\n\n"
        "## ✅ What You Got Right\n"
        "Point out what was correctly done from the start or well-structured. "
        "Reference specific code lines or constructs from their earliest attempt.\n\n"
        "## ❌ Key Mistakes Made\n"
        "Describe each significant mistake. For each:\n"
        "- Quote the EXACT incorrect line(s) from the code (use inline code formatting)\n"
        "- Explain WHY it was wrong at a conceptual level — not just 'it was wrong', but what Python was actually doing\n"
        "- Show what effect it had on the output (quote the actual terminal output)\n\n"
        "## 🔧 How You Fixed It\n"
        "Trace the progression across attempts. What specifically changed between attempts? "
        "Quote the corrected line(s) and explain why the fix works.\n\n"
        "## 💡 Core Concept to Understand\n"
        "Explain the key concept(s) this problem tested in plain language. "
        "Do NOT just name the concept (e.g. don't say 'this uses f-strings'). "
        "Explain HOW and WHY it works, with a tiny illustrative example if needed. "
        "Make them feel like they truly understand it, not just memorized a fix.\n\n"
        "## 🚀 If You Try Again\n"
        "One specific, actionable suggestion to make their solution even better or more Pythonic. "
        "Keep this brief — one concrete idea.\n\n"
        "RULES:\n"
        "- Address the student directly ('you', 'your code')\n"
        "- Always quote actual code lines or terminal output when making a point — never speak abstractly\n"
        "- Encouraging tone, but honest about the mistakes\n"
        "- Total length: 250–400 words\n"
        "- Do NOT start with 'Certainly!' or generic AI filler\n"
    )

    return problem_section + attempts_section + "\n" + report_instructions


def generate_learning_report(
    problem: Dict[str, Any],
    submissions: List[Dict[str, Any]]
) -> str:
    """
    Generate a learning report using the quota manager's premium model cascade.
    Asks get_available_report_models() for candidates (same logic as guidance),
    then tries each in priority order with identical quota tracking.
    Raises RuntimeError if all premium quota is exhausted — never falls back to
    flash-lite or Gemma for a learning report.
    """
    client = get_client()
    if not client:
        raise RuntimeError("API key not configured — cannot generate learning report.")

    candidate_models = get_available_report_models()
    if not candidate_models:
        raise RuntimeError(
            "Learning report generation is temporarily unavailable — "
            "all premium model quota is exhausted. Please try again tomorrow."
        )

    prompt = build_learning_report_prompt(problem, submissions)
    last_error = None

    for model_name in candidate_models:
        try:
            logger.info(f"[REPORT] Trying model: {model_name} for problem '{problem.get('title', '?')}'")
            response = client.models.generate_content(model=model_name, contents=prompt)
            text = response.text.strip() if response.text else ""

            if not text:
                logger.warning(f"[REPORT] Empty response from {model_name}, trying next.")
                last_error = "Empty response"
                continue

            # Track quota usage — identical call to what guidance uses
            record_model_usage(model_name)
            logger.info(f"[REPORT] Report generated via {model_name} ({len(text)} chars)")
            return text

        except Exception as e:
            error_str = str(e)
            logger.warning(f"[REPORT] Model {model_name} failed: {error_str}")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                record_model_rate_limited(model_name, error_str)
            last_error = error_str
            continue

    logger.error(f"[REPORT] All premium models exhausted. Last error: {last_error}")
    raise RuntimeError(
        "Learning report generation is temporarily unavailable — "
        "all premium model quota is exhausted. Please try again later or ask your instructor."
    )
