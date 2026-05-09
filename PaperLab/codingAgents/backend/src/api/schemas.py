"""API 请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    session_id: str | None = None
    paper_context: str = ""
    objective: str = ""


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str


class StepRequest(BaseModel):
    session_id: str


class ApprovalRequest(BaseModel):
    session_id: str
    approved: bool


class SessionStateResponse(BaseModel):
    session_id: str
    phase: str
    iteration: int
    plan: str
    paper_context: str
    actions: list[dict[str, Any]]
    pending_action: dict[str, Any] | None
    error: str
    summary: str


class SendMessageRequest(BaseModel):
    session_id: str
    message: str
