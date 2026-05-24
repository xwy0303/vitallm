from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MinerUBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MinerUOptions(MinerUBaseModel):
    backend: str = "pipeline"
    lang_list: str = "en"
    parse_method: str = "auto"
    formula_enable: str = "true"
    table_enable: str = "true"
    image_analysis: str = "false"
    return_md: str = "true"
    return_middle_json: str = "true"
    return_model_output: str = "false"
    return_content_list: str = "true"
    return_images: str = "true"
    response_format_zip: str = "true"
    start_page_id: str = "0"
    end_page_id: str = "999"

    def as_form_data(self) -> Dict[str, str]:
        return self.model_dump()


class MinerUInputFile(MinerUBaseModel):
    path: str
    sha256: str
    size_bytes: int


class MinerUTaskManifest(MinerUBaseModel):
    task_id: str
    submitted_at: str
    submit_base_url: str
    result_base_url: str
    input_files: List[MinerUInputFile]
    options: MinerUOptions
    status: str = "submitted"
    artifact_dir: Optional[str] = None
    error_message: Optional[str] = None
    raw_submit_response: Optional[Dict[str, Any]] = None

    @field_validator("submitted_at")
    @classmethod
    def submitted_at_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("submitted_at is required")
        return value


class MinerUFetchResult(MinerUBaseModel):
    task_id: str
    status: str
    content_type: Optional[str] = None
    json_payload: Optional[Dict[str, Any]] = None
    artifact_path: Optional[str] = None
    error_message: Optional[str] = None


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MinerUClient:
    def __init__(
        self,
        submit_base_url: str,
        result_base_url: str,
        timeout: float = 120.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.submit_base_url = submit_base_url.rstrip("/")
        self.result_base_url = result_base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    def submit_pdfs(
        self,
        pdf_paths: Sequence[Path],
        options: Optional[MinerUOptions] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        options = options or MinerUOptions()
        paths = [Path(path).expanduser().resolve() for path in pdf_paths]
        if not paths:
            raise ValueError("at least one PDF path is required")
        for path in paths:
            if not path.exists():
                raise FileNotFoundError(path)
            if path.suffix.lower() != ".pdf":
                raise ValueError(f"expected a PDF file: {path}")

        handles = []
        try:
            files = []
            for path in paths:
                handle = path.open("rb")
                handles.append(handle)
                files.append(("files", (path.name, handle, "application/pdf")))

            response = self._post("/tasks", data=options.as_form_data(), files=files)
            payload = _response_json(response)
            task_id = _extract_task_id(payload)
            return task_id, payload
        finally:
            for handle in handles:
                handle.close()

    def build_manifest(
        self,
        task_id: str,
        pdf_paths: Sequence[Path],
        options: Optional[MinerUOptions] = None,
        raw_submit_response: Optional[Dict[str, Any]] = None,
    ) -> MinerUTaskManifest:
        options = options or MinerUOptions()
        input_files = []
        for raw_path in pdf_paths:
            path = Path(raw_path).expanduser().resolve()
            input_files.append(
                MinerUInputFile(
                    path=str(path),
                    sha256=sha256_file(path),
                    size_bytes=path.stat().st_size,
                )
            )
        return MinerUTaskManifest(
            task_id=task_id,
            submitted_at=datetime.now(timezone.utc).isoformat(),
            submit_base_url=self.submit_base_url,
            result_base_url=self.result_base_url,
            input_files=input_files,
            options=options,
            raw_submit_response=raw_submit_response,
        )

    def write_manifest(self, manifest: MinerUTaskManifest, artifact_dir: Path) -> Path:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "manifest.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(manifest.model_dump(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return path

    def fetch_result(self, task_id: str, artifact_dir: Optional[Path] = None) -> MinerUFetchResult:
        response = self._get(f"/tasks/{task_id}/result")
        content_type = response.headers.get("content-type")

        if _looks_like_zip(response):
            artifact_path = None
            if artifact_dir is not None:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                artifact_path = artifact_dir / f"{task_id}.zip"
                artifact_path.write_bytes(response.content)
            return MinerUFetchResult(
                task_id=task_id,
                status="succeeded",
                content_type=content_type,
                artifact_path=str(artifact_path) if artifact_path else None,
            )

        payload = _response_json(response)
        status = str(payload.get("status") or payload.get("state") or "succeeded")
        return MinerUFetchResult(
            task_id=task_id,
            status=status,
            content_type=content_type,
            json_payload=payload,
        )

    def poll_until_done(
        self,
        task_id: str,
        artifact_dir: Optional[Path] = None,
        timeout_seconds: float = 1800.0,
        interval_seconds: float = 10.0,
    ) -> MinerUFetchResult:
        deadline = time.monotonic() + timeout_seconds
        last_result: Optional[MinerUFetchResult] = None

        while time.monotonic() < deadline:
            try:
                result = self.fetch_result(task_id, artifact_dir=artifact_dir)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code in {502, 503, 504}:
                    last_result = MinerUFetchResult(
                        task_id=task_id,
                        status=f"transient_http_{status_code}",
                        content_type=exc.response.headers.get("content-type"),
                        error_message=exc.response.text[:1000],
                    )
                    time.sleep(interval_seconds)
                    continue
                if status_code == 409:
                    payload = _safe_json_response(exc.response)
                    if isinstance(payload, dict):
                        status = str(payload.get("status") or payload.get("state") or "").strip().lower()
                        error_message = str(
                            payload.get("error")
                            or payload.get("message")
                            or payload.get("detail")
                            or exc.response.text[:1000]
                        )
                        if status in {"failed", "fail", "error", "cancelled", "canceled"}:
                            raise RuntimeError(f"MinerU task {task_id} failed with status={status}: {error_message}")
                        last_result = MinerUFetchResult(
                            task_id=task_id,
                            status=status or f"transient_http_{status_code}",
                            content_type=exc.response.headers.get("content-type"),
                            json_payload=payload,
                            error_message=error_message,
                        )
                    else:
                        last_result = MinerUFetchResult(
                            task_id=task_id,
                            status=f"transient_http_{status_code}",
                            content_type=exc.response.headers.get("content-type"),
                            error_message=exc.response.text[:1000],
                        )
                    time.sleep(interval_seconds)
                    continue
                raise
            last_result = result
            status = result.status.lower()
            if status in {"succeeded", "success", "done", "completed", "finished"}:
                return result
            if status in {"failed", "fail", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"MinerU task {task_id} failed with status={result.status}")
            if result.artifact_path:
                return result
            time.sleep(interval_seconds)

        detail = f"last_status={last_result.status}" if last_result else "no result"
        raise TimeoutError(f"MinerU task {task_id} timed out after {timeout_seconds}s ({detail})")

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("POST", f"{self.submit_base_url}{path}", **kwargs)

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", f"{self.result_base_url}{path}", **kwargs)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._client or httpx.Client(timeout=self.timeout, trust_env=False)
        close_client = self._client is None
        try:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        finally:
            if close_client:
                client.close()


def _response_json(response: httpx.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"expected JSON response, got content-type={response.headers.get('content-type')}") from exc
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object response")
    return payload


def _safe_json_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _extract_task_id(payload: Dict[str, Any]) -> str:
    candidates = [
        payload.get("task_id"),
        payload.get("taskId"),
        payload.get("id"),
    ]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("task_id"), data.get("taskId"), data.get("id")])

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    raise ValueError("submit response does not contain task_id")


def _looks_like_zip(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return "zip" in content_type or response.content.startswith(b"PK\x03\x04")
