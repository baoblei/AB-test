from typing import List, Optional

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class VoteSubmit(BaseModel):
    task_type: str
    eval_mode: str = "full"
    task_id: int
    v_left: str
    v_right: str
    scene: str
    filename: str
    worker: str
    overall: Optional[str] = None
    aesthetic: Optional[str] = None
    logic: Optional[str] = None
    consistency: Optional[str] = None
    fidelity: Optional[str] = None
    bad_case_left: Optional[List[str]] = None
    bad_case_right: Optional[List[str]] = None
    duration_seconds: Optional[int] = None


class ExportRequest(BaseModel):
    task_type: str
    v1: str
    v2: str
    scenes: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    workers: List[str] = Field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    eval_modes: List[str] = Field(default_factory=lambda: ["full", "overall"])
    result_filter: str = "all"
    bad_case_filter: str = "all"
    include_images: bool = False
    include_bad_cases: bool = True
    include_duration: bool = True
