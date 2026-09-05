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
    time_spent_seconds: Optional[int] = None
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
