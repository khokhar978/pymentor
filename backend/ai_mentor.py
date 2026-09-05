"""
AI Mentoring Engine using Google GenAI with multi-model fallback cascade,
context-aware progression tracking, and 3 Socratic guidance levels.
"""

import os
import re
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

    history_text = ""
    if history:
        history_text += "\n--- PREVIOUS ATTEMPTS IN THIS SESSION ---\n"
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

    level_instructions = ""
    if help_level == 1:
        level_instructions = (
            "\nHELP LEVEL 1 INSTRUCTIONS (Baby Steps):\n"
            "- Absolute beginner. Use simple, direct, encouraging English.\n"
            "- Break down logic into single, bite-sized tasks.\n"
            "- Reference specific line numbers for any error or gap.\n"
            "- ALWAYS describe the REAL-WORLD screen effect of the mistake.\n"
            "- If simulated output is available, reference it: 'See, when you ran the code...'\n"
            "- Give a direct leading question or tiny hint so they can fix it.\n"
            "- NEVER write out the full solution code!\n"
        )
    elif help_level == 2:
        level_instructions = (
            "\nHELP LEVEL 2 INSTRUCTIONS (Guided):\n"
            "- Point to the specific line or logic block needing attention.\n"
            "- Explain the practical symptom or conceptual gap, reference simulated output if available.\n"
            "- Ask questions that lead them to inspect operators, logic, or edge cases.\n"
            "- Acknowledge what they fixed and move to the next problem.\n"
        )
    else:
        level_instructions = (
            "\nHELP LEVEL 3 INSTRUCTIONS (Challenge):\n"
            "- Minimal nudges only.\n"
            "- If simulated output is available, point to it and let student reason from it.\n"
            "- Point out the failing scenario without revealing the fix.\n"
            "- Let the student debug their own syntax and flow.\n"
        )

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
        "   - Entire response body (EXCLUDING the STATUS line) must be UNDER 80 WORDS. Count carefully.\n"
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
        f"=== PROBLEM ===\n"
        f"Title: {problem['title']}\n"
        f"Topic: {problem['topic']}\n"
        f"Difficulty: {problem['difficulty']}\n"
        f"Description:\n{problem['description']}\n\n"
        f"Sample Input:\n{problem['sample_input']}\n\n"
        f"Sample Output:\n{problem['sample_output']}\n\n"
        f"=== RUBRIC ===\n{problem['ai_rubric']}\n\n"
        f"=== GUIDANCE LEVEL ===\n{help_level_desc}\n{level_instructions}\n"
        f"{run_output_section}"
        f"{history_text}\n"
        f"=== STUDENT'S CURRENT CODE (Attempt #{len(history) + 1}) ===\n"
        f"```python\n{current_code}\n```\n\n"
        "Provide feedback. First line MUST be `[STATUS: SOLVED]` or `[STATUS: IN_PROGRESS]`.\n"
    )
    return prompt


# ─────────────────────────────────────────────
# EVALUATE CODE
# ─────────────────────────────────────────────

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
            "error": "API_KEY_MISSING"
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

            return {
                "is_correct": is_correct,
                "feedback": feedback_text,
                "model_used": model_name,
                "error": None
            }
        except Exception as e:
            error_str = str(e)
            logger.warning(f"Model {model_name} failed: {error_str}")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                record_model_rate_limited(model_name, error_str)
            last_error = error_str
            continue

    return {
        "is_correct": False,
        "feedback": f"All models are currently busy. Please wait a moment and try again.\n\nDetails: {last_error}",
        "model_used": "failed",
        "error": str(last_error)
    }
