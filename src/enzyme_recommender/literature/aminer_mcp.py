from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_KEYWORD_TOOL = "search_papers_by_keyword"
SEARCH_TOOL_CANDIDATES = (
    "search_papers_by_keyword",
    "search_papers_advanced",
    "paper_search_assistant",
)
ERROR_SIGNAL_RE = re.compile(
    r"("
    r"余额不足|请充值|insufficient\s+(?:balance|credit|quota)|"
    r"quota\s+(?:exceeded|limit)|credit\s+(?:exhausted|limit)|recharge|"
    r"unauthori[sz]ed|invalid\s+token|forbidden|permission\s+denied|"
    r"rate\s*limit|tool\s*error|mcp\s*error"
    r")",
    re.I,
)
ERROR_STATUS_VALUES = {"error", "failed", "failure", "fail", "unauthorized", "forbidden"}
ERROR_FIELD_KEYS = ("error", "errors", "errmsg", "error_message")
MESSAGE_FIELD_KEYS = ("message", "msg", "detail", "details", "reason")
PAPER_LIKE_KEYS = {
    "title",
    "name",
    "paper_title",
    "abstract",
    "summary",
    "authors",
    "authors_name",
    "author",
    "year",
    "pub_year",
    "venue",
    "journal",
    "conference",
    "n_citation",
    "citation_count",
    "citations",
    "url",
    "pdf",
    "link",
}


class ExternalLiteratureItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str = ""
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    citation_count: Optional[int] = None
    url: Optional[str] = None


class ExternalLiteratureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "aminer_mcp"
    status: str
    query: str
    tool_name: Optional[str] = None
    message: Optional[str] = None
    items: List[ExternalLiteratureItem] = Field(default_factory=list)

    def context_text(self, max_chars_per_item: int = 700) -> str:
        if self.status != "success" or not self.items:
            return f"AMiner MCP status={self.status}; message={self.message or '-'}"
        blocks = []
        for index, item in enumerate(self.items, start=1):
            details = [
                f"[AMiner-{index}] title={item.title}",
                f"year={item.year or '-'} venue={item.venue or '-'} citations={item.citation_count if item.citation_count is not None else '-'}",
                f"authors={', '.join(item.authors[:6]) or '-'}",
            ]
            if item.url:
                details.append(f"url={item.url}")
            if item.summary:
                details.append(f"summary={item.summary[:max_chars_per_item]}")
            blocks.append("\n".join(details))
        return "\n\n".join(blocks)

    def summaries(self, limit: int = 5) -> List[str]:
        if self.status != "success":
            return [f"AMiner MCP 外部检索未启用或不可用：{self.message or self.status}"]
        summaries = []
        for index, item in enumerate(self.items[:limit], start=1):
            meta = " / ".join(part for part in [str(item.year) if item.year else "", item.venue or ""] if part)
            suffix = f"（{meta}）" if meta else ""
            summaries.append(f"[AMiner-{index}] {item.title}{suffix}")
        return summaries


@dataclass(frozen=True)
class MCPEvent:
    event: str
    data: str


class AminerMCPClient:
    """Minimal JSON-RPC over SSE client for the hosted AMiner MCP endpoint.

    The official MCP Python SDK currently requires a newer Python than this
    LaunchAgent runtime. This client implements only the small subset needed by
    GeneralQA: initialize, tools/list and tools/call.
    """

    def __init__(
        self,
        sse_url: str,
        auth_token: str,
        timeout_seconds: float = 20.0,
        max_results: int = 5,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.sse_url = sse_url
        self.auth_token = auth_token
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self._client = client

    def search_papers(self, query: str, max_results: Optional[int] = None) -> ExternalLiteratureResult:
        if not self.auth_token.strip():
            return ExternalLiteratureResult(status="missing_token", query=query, message="AMiner MCP auth token is not configured")
        query = normalize_literature_query(query)
        limit = max(1, min(max_results or self.max_results, 10))
        started_at = time.perf_counter()
        try:
            with self._http_client() as client:
                with client.stream("GET", self.sse_url, headers=self._headers()) as response:
                    response.raise_for_status()
                    events = iter_sse_events(response.iter_lines())
                    endpoint = self._wait_for_endpoint(events)
                    self._request(client, endpoint, events, "initialize", initialize_params())
                    self._notify(client, endpoint, "notifications/initialized")
                    tools_result = self._request(client, endpoint, events, "tools/list")
                    tool_name = select_search_tool(tools_result)
                    result = self._request(
                        client,
                        endpoint,
                        events,
                        "tools/call",
                        {
                            "name": tool_name,
                            "arguments": build_tool_arguments(tool_name, query, limit),
                        },
                    )
            tool_error = detect_tool_result_error(result)
            if tool_error:
                return ExternalLiteratureResult(
                    status="error",
                    query=query,
                    tool_name=tool_name,
                    message=tool_error,
                )
            items = normalize_tool_result(result, limit=limit)
            return ExternalLiteratureResult(
                status="success" if items else "empty",
                query=query,
                tool_name=tool_name,
                message=None if items else "AMiner MCP returned no paper items",
                items=items,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            return ExternalLiteratureResult(
                status="error",
                query=query,
                message=f"{exc.__class__.__name__}: {str(exc)[:220]} ({elapsed_ms} ms)",
            )

    def _http_client(self):
        if self._client is not None:
            return nullcontext(self._client)
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=min(10.0, self.timeout_seconds),
            read=self.timeout_seconds,
            write=min(10.0, self.timeout_seconds),
            pool=min(10.0, self.timeout_seconds),
        )
        return httpx.Client(timeout=timeout, trust_env=False)

    def _wait_for_endpoint(self, events: Iterator[MCPEvent]) -> str:
        for event in events:
            if event.event == "endpoint" and event.data.strip():
                return urljoin(self.sse_url, event.data.strip())
            if looks_like_endpoint(event.data):
                return urljoin(self.sse_url, event.data.strip())
        raise RuntimeError("MCP SSE endpoint event was not received")

    def _request(
        self,
        client: httpx.Client,
        endpoint: str,
        events: Iterator[MCPEvent],
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        request_id = next_request_id()
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = client.post(endpoint, headers=self._headers(), json=payload)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and ("result" in data or "error" in data):
            if data.get("error"):
                raise RuntimeError(format_jsonrpc_error(data["error"]))
            return data.get("result", data)
        data = wait_for_jsonrpc_response(events, request_id)
        if data.get("error"):
            raise RuntimeError(format_jsonrpc_error(data["error"]))
        return data.get("result", data)

    def _notify(self, client: httpx.Client, endpoint: str, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        response = client.post(endpoint, headers=self._headers(), json=payload)
        response.raise_for_status()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }


class nullcontext:
    def __init__(self, value: httpx.Client) -> None:
        self.value = value

    def __enter__(self) -> httpx.Client:
        return self.value

    def __exit__(self, *_args: Any) -> None:
        return None


_REQUEST_COUNTER = 0


def next_request_id() -> int:
    global _REQUEST_COUNTER
    _REQUEST_COUNTER += 1
    return _REQUEST_COUNTER


def initialize_params() -> Dict[str, Any]:
    return {
        "protocolVersion": DEFAULT_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "shengji-general-qa", "version": "0.1.0"},
    }


def iter_sse_events(lines: Iterator[str]) -> Iterator[MCPEvent]:
    event_name = "message"
    data_lines: List[str] = []
    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.rstrip("\n")
        if not line:
            if data_lines:
                yield MCPEvent(event=event_name, data="\n".join(data_lines))
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if data_lines:
        yield MCPEvent(event=event_name, data="\n".join(data_lines))


def wait_for_jsonrpc_response(events: Iterator[MCPEvent], request_id: int) -> Dict[str, Any]:
    for event in events:
        if event.event not in {"message", "response"}:
            continue
        try:
            payload = json.loads(event.data)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("id") == request_id:
            return payload
    raise RuntimeError(f"MCP JSON-RPC response was not received for id={request_id}")


def looks_like_endpoint(value: str) -> bool:
    text = value.strip()
    return text.startswith(("http://", "https://", "/"))


def select_search_tool(tools_result: Any) -> str:
    tools = tools_result.get("tools") if isinstance(tools_result, dict) else []
    names = [str(tool.get("name") or "") for tool in tools if isinstance(tool, dict)]
    for candidate in SEARCH_TOOL_CANDIDATES:
        if candidate in names:
            return candidate
    for name in names:
        lowered = name.lower()
        if "paper" in lowered and ("keyword" in lowered or "search" in lowered):
            return name
    return DEFAULT_KEYWORD_TOOL


def build_tool_arguments(tool_name: str, query: str, size: int) -> Dict[str, Any]:
    common = {"page": 0, "size": size, "order": "year"}
    if tool_name == "search_papers_advanced":
        return {"keyword": query, **common}
    if tool_name == "paper_search_assistant":
        return {"query": query, **common}
    return {"keyword": query, **common}


def normalize_literature_query(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:260] or "enzyme immobilization MOF microfluidics"


def normalize_tool_result(result: Any, limit: int) -> List[ExternalLiteratureItem]:
    if detect_tool_result_error(result):
        return []
    candidates = extract_candidate_items(result)
    items: List[ExternalLiteratureItem] = []
    for candidate in candidates:
        item = build_literature_item(candidate)
        if item and item.title not in {existing.title for existing in items}:
            items.append(item)
        if len(items) >= limit:
            break
    return items


def extract_candidate_items(value: Any) -> List[Any]:
    if isinstance(value, dict):
        for key in ["papers", "results", "items", "data"]:
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
            if isinstance(nested, dict):
                extracted = extract_candidate_items(nested)
                if extracted:
                    return extracted
        content = value.get("content")
        if isinstance(content, list):
            extracted: List[Any] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    extracted.extend(extract_text_items(str(item.get("text") or "")))
            if extracted:
                return extracted
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return extract_text_items(value)
    return []


def extract_text_items(text: str) -> List[Any]:
    stripped = text.strip()
    if not stripped:
        return []
    if detect_text_error(stripped):
        return []
    try:
        parsed = json.loads(stripped)
    except ValueError:
        parsed = None
    if parsed is not None:
        extracted = extract_candidate_items(parsed)
        if extracted:
            return extracted
    blocks = [block.strip() for block in re.split(r"\n\s*\n|(?=\n\d+[\).]\s+)", stripped) if block.strip()]
    return [{"title": first_non_empty_line(block), "summary": block} for block in blocks if first_non_empty_line(block)]


def first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[\).])\s*", "", line).strip()
        if cleaned:
            return cleaned[:180]
    return ""


def build_literature_item(value: Any) -> Optional[ExternalLiteratureItem]:
    if not isinstance(value, dict):
        return None
    title = str(value.get("title") or value.get("name") or value.get("paper_title") or "").strip()
    if not is_meaningful_literature_title(title):
        return None
    authors = normalize_authors(value.get("authors") or value.get("authors_name") or value.get("author"))
    return ExternalLiteratureItem(
        title=title[:240],
        summary=str(value.get("abstract") or value.get("summary") or value.get("description") or "").strip(),
        authors=authors,
        year=safe_int(value.get("year") or value.get("pub_year")),
        venue=str(value.get("venue") or value.get("journal") or value.get("conference") or "").strip() or None,
        citation_count=safe_int(value.get("n_citation") or value.get("citation_count") or value.get("citations")),
        url=str(value.get("url") or value.get("pdf") or value.get("link") or "").strip() or None,
    )


def detect_tool_result_error(value: Any, depth: int = 0) -> Optional[str]:
    if depth > 6:
        return None
    if isinstance(value, dict):
        if value.get("isError") is True:
            return coerce_error_message(value) or "AMiner MCP tool returned an error"
        status = str(value.get("status") or value.get("state") or "").strip().lower()
        if status in ERROR_STATUS_VALUES:
            return coerce_error_message(value) or f"AMiner MCP status={status}"
        for key in ERROR_FIELD_KEYS:
            if key in value and value.get(key) not in (None, "", [], {}):
                return coerce_error_message(value.get(key)) or coerce_error_message(value) or f"AMiner MCP error field: {key}"
        for key in MESSAGE_FIELD_KEYS:
            message_error = detect_text_error(str(value.get(key) or ""), depth=depth + 1)
            if message_error:
                return message_error
        if looks_like_paper_record(value):
            return None
        content = value.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    content_error = detect_text_error(str(item.get("text") or ""), depth=depth + 1)
                    if content_error:
                        return content_error
        for key in ("data", "result", "response", "payload"):
            if key in value:
                nested_error = detect_tool_result_error(value[key], depth=depth + 1)
                if nested_error:
                    return nested_error
    if isinstance(value, list):
        for item in value:
            item_error = detect_tool_result_error(item, depth=depth + 1)
            if item_error:
                return item_error
    if isinstance(value, str):
        return detect_text_error(value, depth=depth + 1)
    return None


def detect_text_error(text: str, depth: int = 0) -> Optional[str]:
    stripped = re.sub(r"\s+", " ", text or "").strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except ValueError:
        parsed = None
    if parsed is not None:
        parsed_error = detect_tool_result_error(parsed, depth=depth + 1)
        if parsed_error:
            return parsed_error
        if isinstance(parsed, (dict, list)):
            return None
    if ERROR_SIGNAL_RE.search(stripped):
        return compact_error_message(stripped)
    return None


def coerce_error_message(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key in (*MESSAGE_FIELD_KEYS, *ERROR_FIELD_KEYS):
            if key in value and value.get(key) not in (None, "", [], {}):
                message = coerce_error_message(value.get(key))
                if message:
                    return message
        content = value.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    message = coerce_error_message(item.get("text"))
                    if message:
                        return message
        return compact_error_message(json.dumps(value, ensure_ascii=False))
    if isinstance(value, list):
        for item in value:
            message = coerce_error_message(item)
            if message:
                return message
        return None
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if parsed is not None and parsed is not value:
        parsed_message = coerce_error_message(parsed)
        if parsed_message:
            return parsed_message
    return compact_error_message(text)


def compact_error_message(text: str, limit: int = 220) -> str:
    compacted = re.sub(r"\s+", " ", text or "").strip()
    if len(compacted) <= limit:
        return compacted
    match = ERROR_SIGNAL_RE.search(compacted)
    if not match:
        return f"{compacted[:limit].rstrip()}..."
    start = max(0, match.start() - 70)
    end = min(len(compacted), match.end() + 140)
    prefix = "..." if start else ""
    suffix = "..." if end < len(compacted) else ""
    return f"{prefix}{compacted[start:end].strip()}{suffix}"


def looks_like_paper_record(value: Dict[str, Any]) -> bool:
    return bool(PAPER_LIKE_KEYS.intersection(value.keys())) and any(
        key in value for key in ("title", "name", "paper_title", "abstract", "authors", "authors_name", "year", "pub_year")
    )


def is_meaningful_literature_title(title: str) -> bool:
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    if len(cleaned) < 4:
        return False
    if cleaned in {"{", "}", "[", "]"} or re.fullmatch(r"[\{\}\[\]\",:]+", cleaned):
        return False
    if cleaned.startswith(("{", "[")) or cleaned.endswith(("}", "]")):
        return False
    if re.match(r"^(?:error|errors|message|status|code)\s*[:=]", cleaned, re.I):
        return False
    if ERROR_SIGNAL_RE.search(cleaned):
        return False
    return True


def normalize_authors(value: Any) -> List[str]:
    if isinstance(value, list):
        names = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("name_zh") or item.get("name_en")
            else:
                name = item
            if str(name or "").strip():
                names.append(str(name).strip())
        return names
    if isinstance(value, str):
        return [item.strip() for item in re.split(r",|;|、", value) if item.strip()]
    return []


def safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_jsonrpc_error(value: Any) -> str:
    if isinstance(value, dict):
        message = value.get("message") or value.get("code") or value
        return f"MCP JSON-RPC error: {message}"
    return f"MCP JSON-RPC error: {value}"
