from __future__ import annotations

import time
import json
from typing import Any, Dict, Iterator, Optional

import httpx

from enzyme_recommender.generators.protocol import (
    GenerationRequest,
    GenerationResponse,
    GenerationStreamChunk,
)


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
        payload = self._build_payload(request)

        last_error: Optional[Exception] = None
        for attempt in range(request.max_retries + 1):
            try:
                response = self._post_chat_completions(payload, timeout=request.timeout_seconds)
                try:
                    data = response.json()
                except ValueError as exc:
                    raise RuntimeError(f"non-JSON generation response from provider {self.provider}") from exc
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

    def stream_generate(self, request: GenerationRequest) -> Iterator[GenerationStreamChunk]:
        payload = self._build_payload(request, stream=True)
        last_error: Optional[Exception] = None
        for attempt in range(request.max_retries + 1):
            emitted_any = False
            try:
                for chunk in self._stream_chat_completions(payload, request.model, timeout=request.timeout_seconds):
                    emitted_any = True
                    yield chunk
                return
            except (httpx.TransportError, httpx.HTTPStatusError, RuntimeError) as exc:
                last_error = exc
                if emitted_any or attempt >= request.max_retries:
                    break
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"stream generation failed for provider {self.provider}: {last_error}") from last_error

    def _build_payload(self, request: GenerationRequest, stream: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream"] = True
        return payload

    def _post_chat_completions(self, payload: Dict[str, Any], timeout: float) -> httpx.Response:
        if self._client is not None:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return response

        with httpx.Client(timeout=max(timeout, self.timeout_seconds), trust_env=False) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
        response.raise_for_status()
        return response

    def _stream_chat_completions(
        self,
        payload: Dict[str, Any],
        model_name: str,
        timeout: float,
    ) -> Iterator[GenerationStreamChunk]:
        if self._client is not None:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                yield from self._iter_stream_response(response, model_name)
            return

        with httpx.Client(timeout=max(timeout, self.timeout_seconds), trust_env=False) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                yield from self._iter_stream_response(response, model_name)

    def _iter_stream_response(
        self,
        response: httpx.Response,
        model_name: str,
    ) -> Iterator[GenerationStreamChunk]:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break
            try:
                data = json.loads(line)
            except ValueError as exc:
                raise RuntimeError(f"non-JSON stream response from provider {self.provider}") from exc

            choices = data.get("choices") or []
            choice = choices[0] if choices else {}
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            content = str(delta.get("content") or message.get("content") or "")
            finish_reason = choice.get("finish_reason")
            usage = data.get("usage") or {}
            if content or finish_reason or usage:
                yield GenerationStreamChunk(
                    provider=self.provider,
                    model=str(data.get("model") or model_name),
                    delta=content,
                    finish_reason=finish_reason,
                    usage=usage if isinstance(usage, dict) else {},
                    raw_event=data if isinstance(data, dict) else None,
                )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
