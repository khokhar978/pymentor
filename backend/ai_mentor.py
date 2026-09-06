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
        record_model_usage,
        record_model_rate_limited,
        MODEL_CONFIGS
    )
except ImportError:
    from backend.quota_manager import (
        get_available_models,
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
            "Cross-check: if the actual output EXACTLY matches the expected sample output, strongly lean toward [STATUS: SOLVED].\n"
        )

    # COMPONENT 3: Similarity score as soft evidence
    sim_score_section = ""
    if simulated_output and problem.get("sample_output"):
        score = similarity_score(problem["sample_output"], simulated_output)
        sim_score_section = (
            "\n=== OUTPUT SIMILARITY TO SAMPLE (computed, not your judgment) ===\n"
            f"{score}% structural match against the expected sample output.\n"
            "(This score ignores exact names/numbers since those legitimately vary — "
            "treat it as one signal among several, not a verdict.)\n\n"
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
        "feedback": "AI guidance is temporarily unavailable. Please wait a few moments and click **Get Guidance** again.",
        "model_used": "failed",
        "error": "AI service temporarily unavailable",
        # COMPONENT 7: Signal to caller to store placeholder in DB instead of error text
        "store_as_placeholder": True,
        "placeholder_text": _FAILED_ATTEMPT_PLACEHOLDER
    }
