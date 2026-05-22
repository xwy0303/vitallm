from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


Role = Literal["system", "user", "assistant"]
ResponseFormat = Literal["text", "json_object"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    role: Role
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must not be empty")
        return value


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    messages: List[ChatMessage]
    model: str
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    response_format: ResponseFormat = "text"
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)

    @field_validator("messages")
    @classmethod
    def messages_must_not_be_empty(cls, value: List[ChatMessage]) -> List[ChatMessage]:
        if not value:
            raise ValueError("at least one message is required")
        return value


class GenerationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    provider: str
    model: str
    content: str
    finish_reason: Optional[str] = None
    usage: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Optional[Dict[str, Any]] = None


class GeneratorClient(Protocol):
    provider: str

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        ...


class MockGeneratorClient:
    provider = "mock"

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        user_messages = [message.content for message in request.messages if message.role == "user"]
        query = user_messages[-1] if user_messages else ""
        if request.response_format == "json_object":
            content = (
                "{"
                '"recommendation":"mock response: evidence-backed immobilization recommendation",'
                f'"query_preview":"{escape_json_string(query[:120])}",'
                '"limitations":["mock generator only validates pipeline contract"]'
                "}"
            )
        else:
            content = (
                "Mock recommendation response. "
                "This validates runtime wiring only; connect SiliconFlow or DeepSeek for real generation. "
                f"Query preview: {query[:160]}"
            )
        return GenerationResponse(
            provider=self.provider,
            model=request.model,
            content=content,
            finish_reason="stop",
            usage={"mock": True},
        )


def escape_json_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
