from typing import List, Optional

from pydantic import BaseModel


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
