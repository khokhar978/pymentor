# PyMentor — Comprehensive Admin API Roadmap

This document serves as the master specification for all administrative REST APIs in PyMentor. All administrative endpoints require the `X-Admin-Secret` header.

---

## Status Overview

| Group | Feature Area | Status | Endpoints |
|-------|--------------|--------|-----------|
| **Group 1** | Problem / Question Management | **Implemented** | CRUD, full details, order, soft/hard delete |
| **Group 2** | Topic / Module Management | **Implemented** | List with stats, add topic, rename with cascade |
| **Group 3** | Student Account Management | **Implemented** | Search/filter, create, edit, single & bulk password reset |
| **Group 4** | Live Lab Session & Grading Overrides | *Planned (Phase 2)* | Problem reset, manual pass, session terminate |
| **Group 5** | Data Export & Reports | *Planned (Phase 2)* | Grades CSV, submissions CSV, problem difficulty analytics |
| **Group 6** | System & AI Live Configuration | *Planned (Phase 3)* | Dynamic model switching, temperature tuning, maintenance mode |

---

## Group 1: Problem / Question Management (Implemented)

### 1. `POST /api/admin/problems`
- **Purpose**: Create a new practice problem on the fly.
- **Request Body**:
  ```json
  {
    "topic": "Decision Making & Conditionals",
    "title": "Grade Calculator",
    "difficulty": "Easy",
    "description": "Calculate letter grade based on mark.",
    "sample_input": "85",
    "sample_output": "Grade: A",
    "concepts": ["if-elif-else", "comparisons"],
    "starter_code": "marks = int(input())\n",
    "ai_rubric": "Check if-elif-else logic and edge cases.",
    "reference_solution": "marks = int(input())\nif marks >= 90: print('Grade: A')...",
    "teacher_instructions": ""
  }
  ```
- **Response**: Created problem object with generated `id`.

### 2. `PUT /api/admin/problems/{id}`
- **Purpose**: Update any field of an existing problem (description, rubrics, samples, difficulty, title, etc.).
- **Request Body**: Any subset of fields from `POST /api/admin/problems`.
- **Response**: Updated problem object.

### 3. `DELETE /api/admin/problems/{id}`
- **Purpose**: Delete or deactivate a problem.
- **Query Parameter**: `?hard=false` (default: soft-delete `is_active=0` to preserve foreign keys and student submission history; `?hard=true` permanently deletes if no active submissions exist).
- **Response**: `{"status": "deactivated" | "deleted", "id": 15}`.

### 4. `GET /api/admin/problems/{id}/full`
- **Purpose**: Retrieve complete problem details including internal `ai_rubric`, `reference_solution`, `teacher_instructions`, and `is_active` status.

### 5. `POST /api/admin/problems/reorder`
- **Purpose**: Update the display ordering of problems within topics.
- **Request Body**: `[{"id": 1, "order_index": 10}, {"id": 2, "order_index": 20}]`.

---

## Group 2: Topic / Module Management (Implemented)

### 1. `GET /api/admin/topics`
- **Purpose**: List all topics with live aggregated stats (number of questions, active questions, total student attempts, solved count).

### 2. `POST /api/admin/topics`
- **Purpose**: Register a new topic/module category for future questions.
- **Request Body**: `{"name": "Week 5: Lists & Tuples", "description": "Sequential data structures"}`.

### 3. `PUT /api/admin/topics/{old_name}`
- **Purpose**: Rename an existing topic and automatically cascade the update to all associated problems in the database.
- **Request Body**: `{"new_name": "Week 5: Python Lists & Tuples"}`.

---

## Group 3: Student Account Management (Implemented)

### 1. `GET /api/admin/students`
- **Purpose**: Search, filter, and paginate students.
- **Query Parameters**:
  - `section`: Filter by section (`A`, `B`, `C`, `D`, `E`, `F`)
  - `search`: Search substring matching roll number or student name
  - `page`: Page number (default: 1)
  - `page_size`: Results per page (default: 50)
- **Response**: List of student profiles with problem completion stats and total time spent.

### 2. `POST /api/admin/students`
- **Purpose**: Manually create an account for a late-joining or transfer student.
- **Request Body**:
  ```json
  {
    "roll_no": "2610998888",
    "name": "Jane Doe",
    "section": "E",
    "email": "jane@example.com",
    "password": "123",
    "needs_password_change": true
  }
  ```

### 3. `POST /api/admin/students/{id}/reset-password`
- **Purpose**: Reset a specific student's password back to `'123'` (or a temporary password) and revoke active tokens.
- **Request Body**: `{"new_password": "123", "require_change": true}`.

### 4. `POST /api/admin/students/bulk-reset-passwords`
- **Purpose**: Bulk reset passwords for an entire section (or all students).
- **Request Body**: `{"section": "E", "default_password": "123"}`.

### 5. `PUT /api/admin/students/{id}`
- **Purpose**: Edit a student's personal details (e.g. fix name typos, section change, email).
- **Request Body**: `{"name": "Jane Doe", "section": "E", "email": "new@example.com"}`.

### 6. `DELETE /api/admin/students/{id}`
- **Purpose**: Deactivate (`is_active=0`) or delete student record.

---

## Group 4: Live Lab Session & Grading Overrides (Planned - Phase 2)

### 1. `POST /api/admin/students/{student_id}/problems/{problem_id}/reset`
- Clear a student's previous submissions and current code on a specific problem so they can start fresh.

### 2. `POST /api/admin/students/{student_id}/problems/{problem_id}/mark-solved`
- Manually mark a problem as `SOLVED` for a student with an instructor note (useful if a student solved with an alternate valid technique or oral exam).

### 3. `POST /api/admin/sessions/{session_id}/terminate`
- Force-close an abandoned or hung student practice session.

---

## Group 5: Data Export & Reports (Planned - Phase 2)

### 1. `GET /api/admin/export/grades.csv`
- Download CSV containing: Roll No, Name, Section, Solved Problem Count, Total Active Time, Submission Count, Last Seen.

### 2. `GET /api/admin/export/submissions.csv`
- Download CSV containing complete historical attempts, student code, AI feedback, and timestamps.

### 3. `GET /api/admin/analytics/problem-stats`
- Summary showing which problems have the highest error rates and what the common error patterns are across the class.

---

## Group 6: System & AI Live Configuration (Planned - Phase 3)

### 1. `GET /api/admin/config/ai` & `POST /api/admin/config/ai`
- Dynamically adjust AI parameters: primary model selection, temperature, token limits, and cooldown intervals without restarting the server.

### 2. `POST /api/admin/system/maintenance-mode`
- Toggle student-facing maintenance banner to pause practice submissions during exams or updates.
