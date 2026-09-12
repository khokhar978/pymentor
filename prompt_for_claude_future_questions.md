# Master Prompt for Claude: Generate PyMentor Questions (Batch 3: IDs 61 to 80)

> **Instructions for Instructor:**  
> Copy and paste the entire block below directly into Claude (Claude 3.5 Sonnet / Claude 3.7 Sonnet). It has been specifically crafted with guardrails against the formatting and description errors observed in earlier batches.

---

```markdown
# Role & Context
You are an expert Computer Science Professor and curriculum architect designing programming lab questions for 1st-semester BCA (Bachelor of Computer Applications) students at Chitkara University. The students practice Python on an interactive learning platform called **PyMentor**.

Students are beginner programmers who have just completed basic variables, operators, math module, conditionals, and basic for/while loops.

---

# Your Task
Generate a JSON array of **20 brand-new, high-quality, beginner-friendly practice problems** (IDs 61 to 80) covering the next syllabus topics:

### Topic 1: Advanced Loops & Patterns (IDs 61 to 70 — 10 Questions)
- `break`, `continue`, and `pass` in practical scenarios (e.g. search with early termination, skip negatives)
- Nested loops for 2D patterns (number triangles, star pyramids, multiplication grid, coordinate pairs)
- Loop accumulators & running simulations (e.g. year-by-year bank interest growth, number guessing round counter, rolling dice sum)
- **Difficulty Mix:** 4 Easy, 4 Medium, 2 Hard

### Topic 2: Strings — Slicing & Iteration (IDs 71 to 80 — 10 Questions)
- String indexing: positive (`s[0]`) and negative (`s[-1]`) access
- String slicing: `s[start:stop]`, `s[::2]`, `s[::-1]` (reversing without `.reverse()`)
- Character-by-character traversal using `for char in text:` (counting vowels, counting digits vs letters, masking sensitive chars like card numbers with `*`)
- Basic string immutability concepts & concatenation
- **Difficulty Mix:** 4 Easy, 4 Medium, 2 Hard

---

# 🚨 CRITICAL DESCRIPTION FORMATTING RULES (DO NOT VIOLATE)

In previous generations, the output required tedious manual regex sanitization because unwanted subsections were placed inside the `"description"` string. **You must strictly avoid this.**

### ❌ FORBIDDEN IN `"description"`:
1. **NO `### Problem Description` or `## Description` header at the top.** (The platform UI already displays the title as `<h1>` and a "Problem Statement" header).
2. **NO `### Input Format` section.** (Input requirements must be naturally explained in the problem prose).
3. **NO `### Output Format` section.** (Output requirements must be naturally explained in the problem prose).
4. **NO `### Example 1` or `### Sample Case` sections.** (The platform UI has a dedicated interactive Sample I/O card with a "Copy" button rendered from `sample_input` and `sample_output`).
5. **NO markdown code blocks (``` ... ```) showing sample inputs or outputs inside `description`.** (Putting codeblocks in `description` duplicates what the student sees below it).
6. **NO `### Explanation` section.**

### ✅ REQUIRED IN `"description"`:
1. **Problem Statement:** 1 to 2 concise, engaging paragraphs explaining the real-world scenario, what inputs to read, what computation to perform, and what to print.
2. **`### Constraints` (Optional / As needed):** Use standard markdown bullets for numeric ranges, precision (`:.2f`), or strict algorithmic restrictions (e.g. `- Must use a nested for loop`, `- Must not use string reverse methods`).

---

# Input/Output Consistency Rule
- PyMentor feeds `sample_input` directly to Python's standard `input()` function.
- If your starter code or reference solution uses `n = int(input())`, your `sample_input` MUST be pure raw data (e.g. `5` or `5\n10`), **NEVER** prompt text like `Enter a number: 5`.
- `sample_output` must be the EXACT stdout string produced by executing `reference_solution` with `sample_input`.

---

# JSON Schema Per Problem
Output a single valid JSON array `[...]` containing 20 problem objects with this exact structure:

```json
{
  "id": 61,
  "topic": "Advanced Loops & Patterns",
  "title": "Right-Angled Number Triangle",
  "difficulty": "Easy",
  "description": "Write a Python program that accepts a positive integer N from the user and prints a right-angled triangle pattern of height N. On line 1, print 1. On line 2, print 1 2, and continue until line N which prints numbers from 1 to N, separated by spaces.\n\n### Constraints\n- 1 <= N <= 20\n- Each row must have space-separated numbers without trailing spaces at the end of the line.",
  "sample_input": "4",
  "sample_output": "1\n1 2\n1 2 3\n1 2 3 4",
  "concepts": ["nested loops", "for loop", "range()", "print formatting"],
  "starter_code": "n = int(input())\n# Write your nested loop to generate the pattern\n",
  "ai_rubric": "1. Verify that the solution uses a nested loop structure (outer loop for rows, inner loop for column values).\n2. Ensure the inner loop prints numbers from 1 up to the current row number.\n3. Verify numbers on the same row are separated by spaces and each row ends with a newline.\n4. Accept both range() with print end=' ' and string joining approaches.",
  "reference_solution": "n = int(input())\nfor i in range(1, n + 1):\n    for j in range(1, i + 1):\n        if j == i:\n            print(j)\n        else:\n            print(j, end=' ')",
  "teacher_instructions": "",
  "is_active": 0,
  "order_index": 610
}
```

---

# Checklist Before You Respond:
- [ ] Exactly 20 problem objects (IDs 61 to 80).
- [ ] IDs 61–70 have `"topic": "Advanced Loops & Patterns"`.
- [ ] IDs 71–80 have `"topic": "Strings — Slicing & Iteration"`.
- [ ] `"description"` contains NO `### Problem Description`, NO `### Input Format`, NO `### Output Format`, and NO `### Example` blocks.
- [ ] `"description"` contains ONLY problem statement prose + `### Constraints`.
- [ ] Every `reference_solution` is tested and produces `sample_output` when given `sample_input`.
- [ ] `"is_active"` is `0` for all 20 problems.
- [ ] Valid JSON output only (wrapped in ```json ... ```).
```
