"""
tests/test_grading.py — Regression tests for deterministic AI pipeline components.
Run with: python -m pytest tests/test_grading.py -v

These test the pure functions detect_crash() and similarity_score() with no API calls.
Specific failure cases are taken directly from the chat_logs_export.csv data analysis.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.ai_mentor import detect_crash, similarity_score

# ─────────────────────────────────────────────────────────────────────────────
# detect_crash() tests
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_crash_traceback():
    """Submission #84 / #159 scenario: classic Python traceback → must detect crash."""
    output = """Traceback (most recent call last):
  File "code.py", line 3, in <module>
    result = int("abc")
ValueError: invalid literal for int() with base 10: 'abc'"""
    assert detect_crash(output) is True

def test_detect_crash_syntax_error():
    output = """  File "code.py", line 2
    print("hello"
                  ^
SyntaxError: '(' was never closed"""
    assert detect_crash(output) is True

def test_detect_crash_type_error():
    output = "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
    assert detect_crash(output) is True

def test_detect_crash_name_error():
    output = "NameError: name 'printt' is not defined"
    assert detect_crash(output) is True

def test_detect_crash_zero_division():
    output = "ZeroDivisionError: division by zero"
    assert detect_crash(output) is True

def test_detect_crash_clean_output():
    """Clean output with no crash — must NOT be detected as crash."""
    output = "Enter your name: Hello, World!\n5\n10\n15"
    assert detect_crash(output) is False

def test_detect_crash_empty_output():
    """Empty string — must return False, not crash or return True."""
    assert detect_crash("") is False
    assert detect_crash(None) is False
    assert detect_crash("   ") is False

def test_detect_crash_solved_output():
    """Correctly solved problem output — must not be flagged as crash."""
    output = "Simple Interest = 150.0\nMaturity Value = 1150.0"
    assert detect_crash(output) is False

def test_detect_crash_word_error_not_crash():
    """'error' in normal text should not trigger crash detection — only 'XError:' patterns."""
    output = "Please correct your input: the value cannot be negative."
    # This should NOT trigger because it doesn't match '\\w*Error:' (no colon after 'correct')
    assert detect_crash(output) is False


# ─────────────────────────────────────────────────────────────────────────────
# similarity_score() tests
# ─────────────────────────────────────────────────────────────────────────────

def test_similarity_perfect_match():
    expected = "Simple Interest = 150.0\nMaturity Value = 1150.0"
    actual   = "Simple Interest = 150.0\nMaturity Value = 1150.0"
    score = similarity_score(expected, actual)
    assert score == 100.0

def test_similarity_case_insensitive():
    """Normalized comparison is case-insensitive."""
    expected = "Simple Interest = 150.0"
    actual   = "simple interest = 150.0"
    score = similarity_score(expected, actual)
    assert score == 100.0

def test_similarity_whitespace_normalized():
    """Extra spaces/blank lines are collapsed before comparison — should score very high."""
    expected = "Line 1\nLine 2"
    actual   = "Line 1   \n\n\nLine 2"
    score = similarity_score(expected, actual)
    assert score >= 90.0, f"Expected >= 90.0 but got {score}"  # Normalization brings it very close


def test_similarity_completely_different():
    expected = "Simple Interest = 150.0"
    actual   = "Traceback (most recent call last): ValueError: invalid input"
    score = similarity_score(expected, actual)
    assert score < 30.0  # Should be very low but not necessarily 0

def test_similarity_empty_inputs():
    """Empty strings should return 0.0, not error."""
    assert similarity_score("", "some output") == 0.0
    assert similarity_score("expected", "") == 0.0
    assert similarity_score("", "") == 0.0

def test_similarity_partial_match():
    """Partial match should be between 0 and 100."""
    expected = "Enter number: Result is 25"
    actual   = "Enter number: Result is 30"  # Only the number differs
    score = similarity_score(expected, actual)
    assert 50.0 < score < 100.0

def test_similarity_returns_float():
    score = similarity_score("hello world", "hello world")
    assert isinstance(score, float)

# ─────────────────────────────────────────────────────────────────────────────
# Integration: crash override guarantees
# ─────────────────────────────────────────────────────────────────────────────

def test_crash_override_simulation():
    """
    Simulate what evaluate_code() does with the crash override logic.
    If AI returned is_correct=True but output has a crash → must be overridden to False.
    This directly tests the scenario from submissions #84, #159, #160, #162.
    """
    simulated_output = """Traceback (most recent call last):
  File "code.py", line 5, in <module>
    print(total / 0)
ZeroDivisionError: division by zero"""

    # Simulate AI incorrectly marking it SOLVED
    ai_is_correct = True

    # Apply the crash override (same logic as in evaluate_code)
    crashed = detect_crash(simulated_output)
    final_is_correct = ai_is_correct and not crashed  # The override logic

    assert final_is_correct is False, \
        "Crash override failed: AI marked SOLVED on crashing output, override should have caught it"


if __name__ == "__main__":
    # Allow running directly: python tests/test_grading.py
    import traceback
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests.")
