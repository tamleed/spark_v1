from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    not_completed = "not_completed"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 512
    stream: bool = False
    async_mode: bool = Field(default=True, alias="async")


class JobCreateRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 512
    stream: bool = False


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    requested_model: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    queue_position: Optional[int] = None
    progress: Optional[float] = None
    error: Optional[str] = None


class AdminSwitchRequest(BaseModel):
    model: str


class ModelInfo(BaseModel):
    name: str
    source: Dict[str, Any]
    backend: Dict[str, Any]
    resources: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class GatewayStatus(BaseModel):
    active_model: Optional[str]
    switching: bool
    backend_state: str
    queue_length: int
    uptime_seconds: int


class QueueStatus(BaseModel):
    queue_length: int
    current_job: Optional[str]
    active_model: Optional[str]
    switching: bool
    drain_mode: bool
