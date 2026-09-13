# PyMentor — Claude Question Generation Prompts (Batches 4 to 9)
**Course:** Programming for AI (25COA1102) | **BCA 1st Semester**  
**Target:** 20 Questions Per Batch (10 Questions Per Topic)  
**Standard:** Clean Problem Prose + `### Constraints` (No `### Problem Description`, No `### Input Format`, No `### Output Format`, No `### Example` blocks).

---

## Quick Navigation Index

| Batch | Question IDs | Topic A | Topic B | Target CHO Lectures | Status |
| :---: | :---: | :--- | :--- | :---: | :---: |
| **Batch 3** | **Q61 – Q80** | Advanced Loops & Patterns | Strings — Slicing & Iteration | L08–L10 | ✅ **Generated & Verified** (`pymentor_questions_61_80.json`) |
| [**Batch 4**](#batch-4-ids-81-to-100) | **Q81 – Q100** | String Methods & Text Processing | Lists — Basics & Traversal | L11–L13 | ⏳ **Ready to Generate** |
| [**Batch 5**](#batch-5-ids-101-to-120) | **Q101 – Q120** | List Methods & Modifications | Tuples & Sets | L14–L15 | ⏳ Up Next |
| [**Batch 6**](#batch-6-ids-121-to-140) | **Q121 – Q140** | Dictionaries & Mappings | Functions & Modular Programming | L16–L18 | ⏳ Up Next |
| [**Batch 7**](#batch-7-ids-141-to-160) | **Q141 – Q160** | Recursion | File Handling — Reading & Processing | L19–L22 | ⏳ Up Next |
| [**Batch 8**](#batch-8-ids-161-to-180) | **Q161 – Q180** | File Handling — Writing & CSV | NumPy Fundamentals | L23–L27 | ⏳ Up Next |
| [**Batch 9**](#batch-9-ids-181-to-200) | **Q181 – Q200** | Pandas — Series & DataFrames | Capstone AI Data Applications | L28–L30 | ⏳ Up Next |

---

## Batch 4: IDs 81 to 100

> **How to Use:** If continuing in the same Claude chat, copy the block below and send it.

```text
Generate the next batch of 20 practice problems (IDs 81 to 100) using the exact same JSON schema, description formatting rules (no forbidden headers, only problem prose + ### Constraints), and raw-input consistency:

### Topic 1: String Methods & Text Processing (IDs 81 to 90 — 10 Questions)
- Core methods: .split(), .join(), .strip(), .replace(), .count(), .find(), .startswith(), .endswith()
- Case & validation methods: .upper(), .lower(), .title(), .isdigit(), .isalpha(), .isalnum()
- Practical scenarios: word counting, email username/domain extractor, acronym builder, clean extra whitespace, sensitive info masker, case-insensitive palindrome phrase checker.
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

### Topic 2: Lists — Basics & Traversal (IDs 91 to 100 — 10 Questions)
- Creation, positive/negative indexing, slicing, iteration (for x in lst:, enumerate()), membership (in / not in)
- Algorithmic traversal: manual sum/average, finding max and min without built-ins, counting occurrences, filtering even/odd numbers, linear search with index reporting.
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

IDs must run sequentially from 81 to 100 with is_active: 0 and order_index from 810 to 1000.
```

---

## Batch 5: IDs 101 to 120

> **Topics:** List Methods & In-Place Modification + Tuples & Sets

```text
Generate the next batch of 20 practice problems (IDs 101 to 120) using the exact same JSON schema, description formatting rules (no forbidden headers, only problem prose + ### Constraints), and raw-input consistency:

### Topic 1: List Methods & Modifications (IDs 101 to 110 — 10 Questions)
- Core methods: .append(), .extend(), .insert(), .pop(), .remove(), .sort(), .reverse(), .clear(), .copy()
- List manipulation algorithms: removing duplicate elements while preserving order, rotating a list, merging two sorted lists, separate positives and negatives, stack simulation (push/pop).
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

### Topic 2: Tuples & Sets (IDs 111 to 120 — 10 Questions)
- Tuples: packing, unpacking, immutability concepts, returning multiple values from calculation, coordinate representations.
- Sets: unique item filtering, set operations (.union(), .intersection(), .difference(), .symmetric_difference()), membership testing.
- Real-world: deduplicating student attendance rolls, common interests finder between two groups, vocabulary word counter.
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

IDs must run sequentially from 101 to 120 with is_active: 0 and order_index from 1010 to 1200.
```

---

## Batch 6: IDs 121 to 140

> **Topics:** Dictionaries & Mappings + Functions & Modular Programming

```text
Generate the next batch of 20 practice problems (IDs 121 to 140) using the exact same JSON schema, description formatting rules (no forbidden headers, only problem prose + ### Constraints), and raw-input consistency:

### Topic 1: Dictionaries & Mappings (IDs 121 to 130 — 10 Questions)
- Key-value creation, access, updating, deleting (del, .pop())
- Methods: .keys(), .values(), .items(), .get(key, default)
- Applications: character frequency counter, word frequency analyzer, phonebook directory lookup, grocery price lookup & cart tally, student gradebook lookup by roll number.
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

### Topic 2: Functions & Modular Programming (IDs 131 to 140 — 10 Questions)
- Function definition (def), positional arguments, keyword arguments, default parameters, return values.
- Variable scope (local vs global), docstrings.
- Modular utilities: tax calculator function, unit converter function suite, input validator function, prime checker function used inside a range printer.
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

IDs must run sequentially from 121 to 140 with is_active: 0 and order_index from 1210 to 1400.
```

---

## Batch 7: IDs 141 to 160

> **Topics:** Recursion + File Handling (Reading & Processing)

```text
Generate the next batch of 20 practice problems (IDs 141 to 160) using the exact same JSON schema, description formatting rules (no forbidden headers, only problem prose + ### Constraints), and raw-input consistency:

### Topic 1: Recursion (IDs 141 to 150 — 10 Questions)
- Base case vs recursive step principles.
- Classic algorithmic problems: factorial, nth Fibonacci number, sum of first N natural numbers, sum of digits of a number, power calculation (x^n), reversing a string recursively, decimal to binary conversion recursively.
- Difficulty mix: 3 Easy, 5 Medium, 2 Hard

### Topic 2: File Handling — Reading & Processing (IDs 151 to 160 — 10 Questions)
- File opening modes ('r'), context manager (with open(...)), .read(), .readline(), .readlines().
- Processing text content: line counting, word counting, character counting, searching for a keyword in a log file, finding longest line.
- Note: In PyMentor test environment, string data or multiline text can be simulated or read via standard input / mock file.
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

IDs must run sequentially from 141 to 160 with is_active: 0 and order_index from 1410 to 1600.
```

---

## Batch 8: IDs 161 to 180

> **Topics:** File Handling (Writing & CSV) + NumPy Fundamentals

```text
Generate the next batch of 20 practice problems (IDs 161 to 180) using the exact same JSON schema, description formatting rules (no forbidden headers, only problem prose + ### Constraints), and raw-input consistency:

### Topic 1: File Handling — Writing & CSV Processing (IDs 161 to 170 — 10 Questions)
- Writing modes ('w', 'a'), writing lines, csv module (csv.reader, csv.writer, header row handling).
- Practical tasks: exporting student report card to CSV, filtering rows by column condition (e.g. marks > 75), calculating column average from tabular data.
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

### Topic 2: NumPy Fundamentals (IDs 171 to 180 — 10 Questions)
- 1D and 2D arrays: np.array(), np.arange(), np.zeros(), np.ones(), shape and dtype.
- Vectorized arithmetic (+, -, *, /), universal functions (np.sqrt, np.round, np.abs).
- Statistical aggregations: np.sum(), np.mean(), np.std(), np.min(), np.max() across axes.
- Slicing and boolean masking on arrays (e.g. arr[arr > 0]).
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

IDs must run sequentially from 161 to 180 with is_active: 0 and order_index from 1610 to 1800.
```

---

## Batch 9: IDs 181 to 200

> **Topics:** Pandas (Series & DataFrames) + Capstone AI Data Applications

```text
Generate the final batch of 20 practice problems (IDs 181 to 200) using the exact same JSON schema, description formatting rules (no forbidden headers, only problem prose + ### Constraints), and raw-input consistency:

### Topic 1: Pandas — Series & DataFrames (IDs 181 to 190 — 10 Questions)
- pd.Series and pd.DataFrame creation from dictionaries and lists.
- Inspection: .head(), .tail(), .info(), .describe(), .shape, column selection.
- Filtering rows by condition, adding calculated columns, sorting by column (.sort_values()).
- Handling missing data (.isna(), .fillna(), .dropna()).
- Grouping & aggregation: .groupby('category')['value'].mean().
- Difficulty mix: 4 Easy, 4 Medium, 2 Hard

### Topic 2: Capstone AI & Data Practice Problems (IDs 191 to 200 — 10 Questions)
- End-to-end data pipelines combining functions, lists/dictionaries, NumPy, and Pandas.
- Practical scenarios: Feature normalization (Min-Max scaling formula), Train/Test index split simulation, Accuracy & Confusion Matrix tally from predictions list, Outlier detection using standard deviations.
- Difficulty mix: 3 Easy, 5 Medium, 2 Hard

IDs must run sequentially from 181 to 200 with is_active: 0 and order_index from 1810 to 2000.
```

---

## 📋 Full Prompt Template (If Starting a Brand New Claude Session)

If you start a **fresh/new Claude chat session**, paste this entire block once to establish all rules and schema:

```markdown
# Role & Context
You are an expert Computer Science Professor and curriculum architect designing programming lab questions for 1st-semester BCA (Bachelor of Computer Applications) students at Chitkara University. The students practice Python on an interactive learning platform called PyMentor.

# 🚨 CRITICAL DESCRIPTION FORMATTING RULES (DO NOT VIOLATE)

### ❌ FORBIDDEN IN "description":
1. NO `### Problem Description` or `## Description` header at the top.
2. NO `### Input Format` section.
3. NO `### Output Format` section.
4. NO `### Example 1` or `### Sample Case` sections.
5. NO markdown code blocks (``` ... ```) showing sample inputs or outputs inside `description`.
6. NO `### Explanation` section.

### ✅ REQUIRED IN "description":
1. Problem Statement: 1 to 2 concise, engaging paragraphs explaining the real-world scenario, what inputs to read, what computation to perform, and what to print.
2. `### Constraints` (Required): Use standard markdown bullets for numeric ranges, precision, or strict algorithmic restrictions (e.g. "- Must use a while loop", "- Must not use built-in sort()").

# Input/Output Consistency Rule
- PyMentor feeds `sample_input` directly to Python's standard `input()` function.
- If your starter code or reference solution uses `n = int(input())`, your `sample_input` MUST be pure raw data (e.g. `4` or `4\n10`), NEVER prompt text like `Enter a number: 4`.
- `sample_output` must be the EXACT stdout string produced by executing `reference_solution` with `sample_input`.

# JSON Schema Per Problem
Output a single valid JSON array `[...]` of problem objects with this exact structure:

```json
{
  "id": 81,
  "topic": "String Methods & Text Processing",
  "title": "Problem Title Here",
  "difficulty": "Easy",
  "description": "Problem description prose here.\n\n### Constraints\n- Constraint 1\n- Constraint 2",
  "sample_input": "raw_input_data",
  "sample_output": "exact_output_string",
  "concepts": ["method1", "method2"],
  "starter_code": "text = input()\n# Your code here\n",
  "ai_rubric": "1. Verify approach...\n2. Check boundary conditions...",
  "reference_solution": "text = input()\nprint(text)",
  "teacher_instructions": "",
  "is_active": 0,
  "order_index": 810
}
```
```
