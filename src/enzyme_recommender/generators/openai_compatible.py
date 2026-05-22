from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx

from enzyme_recommender.generators.protocol import GenerationRequest, GenerationResponse


class OpenAICompatibleGeneratorClient:
    """Chat-completions adapter for SiliconFlow, DeepSeek and similar APIs."""

    def __init__(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            raise ValueError(f"api_key is required for generator provider: {provider}")
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client = client

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        last_error: Optional[Exception] = None
        for attempt in range(request.max_retries + 1):
            try:
                response = self._post_chat_completions(payload, timeout=request.timeout_seconds)
                data = response.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                content = str(message.get("content") or "")
                if not content.strip():
                    raise RuntimeError(f"empty generation response from provider {self.provider}")
                return GenerationResponse(
                    provider=self.provider,
                    model=request.model,
                    content=content,
                    finish_reason=choice.get("finish_reason"),
                    usage=data.get("usage") or {},
                    raw_response=data,
                )
            except (httpx.TransportError, httpx.HTTPStatusError, RuntimeError) as exc:
                last_error = exc
                if attempt >= request.max_retries:
                    break
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"generation failed for provider {self.provider}: {last_error}") from last_error

    def _post_chat_completions(self, payload: Dict[str, Any], timeout: float) -> httpx.Response:
        client = self._client or httpx.Client(timeout=max(timeout, self.timeout_seconds), trust_env=False)
        response = client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response
