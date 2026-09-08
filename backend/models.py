"""
Pydantic Request & Data Models for PyMentor API.
"""

from typing import Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    section: str
    roll_no: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class SessionStartRequest(BaseModel):
    problem_id: int
    help_level: Optional[int] = 1


class SessionSaveRequest(BaseModel):
    session_id: int
    code: str = Field(..., max_length=20000)
    is_run: Optional[bool] = True


class SubmitCodeRequest(BaseModel):
    session_id: int
    code: str = Field(..., max_length=20000)
    help_level: Optional[int] = 1
    simulated_output: Optional[str] = Field(None, max_length=10000)


class SetKeyRequest(BaseModel):
    api_key: str


class HeartbeatRequest(BaseModel):
    session_id: int


class TelemetryEventRequest(BaseModel):
    session_id: Optional[int] = None
    problem_id: Optional[int] = None
    event_type: str
    event_data: Optional[dict] = None


class UpdateSettingsRequest(BaseModel):
    default_help_level: int = Field(..., ge=1, le=3)


class TeacherInstructionsRequest(BaseModel):
    instructions: str = Field("", max_length=2000)


class SqlQueryRequest(BaseModel):
    query: str = Field(..., max_length=5000)
    params: Optional[list] = None


# ─────────────────────────────────────────────
# ADMIN GROUP 1: PROBLEM MANAGEMENT MODELS
# ─────────────────────────────────────────────

class CreateProblemRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=200)
    difficulty: str = Field("Easy", max_length=50)
    description: str = Field(..., min_length=1)
    sample_input: Optional[str] = ""
    sample_output: str = Field(..., min_length=1)
    concepts: Optional[list] = []
    starter_code: Optional[str] = ""
    ai_rubric: str = Field(..., min_length=1)
    reference_solution: Optional[str] = ""
    teacher_instructions: Optional[str] = ""
    order_index: Optional[int] = 0


class UpdateProblemRequest(BaseModel):
    topic: Optional[str] = None
    title: Optional[str] = None
    difficulty: Optional[str] = None
    description: Optional[str] = None
    sample_input: Optional[str] = None
    sample_output: Optional[str] = None
    concepts: Optional[list] = None
    starter_code: Optional[str] = None
    ai_rubric: Optional[str] = None
    reference_solution: Optional[str] = None
    teacher_instructions: Optional[str] = None
    is_active: Optional[bool] = None
    order_index: Optional[int] = None


class ReorderItem(BaseModel):
    id: int
    order_index: int


class ReorderProblemsRequest(BaseModel):
    items: list[ReorderItem]


# ─────────────────────────────────────────────
# ADMIN GROUP 2: TOPIC MANAGEMENT MODELS
# ─────────────────────────────────────────────

class CreateTopicRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = ""
    order_index: Optional[int] = 0


class RenameTopicRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


# ─────────────────────────────────────────────
# ADMIN GROUP 3: STUDENT MANAGEMENT MODELS
# ─────────────────────────────────────────────

class CreateStudentRequest(BaseModel):
    roll_no: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    section: str = Field(..., min_length=1, max_length=10)
    email: Optional[str] = ""
    password: Optional[str] = "123"
    needs_password_change: Optional[bool] = True
    default_help_level: Optional[int] = 1


class UpdateStudentRequest(BaseModel):
    name: Optional[str] = None
    section: Optional[str] = None
    email: Optional[str] = None
    default_help_level: Optional[int] = None
    is_active: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    new_password: Optional[str] = "123"
    require_change: Optional[bool] = True


class BulkResetPasswordRequest(BaseModel):
    section: Optional[str] = None
    default_password: Optional[str] = "123"

