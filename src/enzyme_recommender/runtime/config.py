from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RuntimeConfigError(ValueError):
    pass


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DocumentParserConfig(StrictBaseModel):
    provider: Literal["mineru_local"] = "mineru_local"
    network_scope: Literal["self_hosted", "local"] = "self_hosted"
    submit_base_url: str = "http://127.0.0.1:8000"
    result_base_url: str = "http://127.0.0.1:8000"
    timeout_seconds: float = Field(default=120.0, gt=0)

    @model_validator(mode="after")
    def forbid_non_local_parser(self) -> "DocumentParserConfig":
        for url in [self.submit_base_url, self.result_base_url]:
            if "220." in url or "ctyun" in url.lower():
                raise ValueError("ctyun MinerU endpoints are not allowed in this project")
        return self


class VectorStoreConfig(StrictBaseModel):
    provider: Literal["qdrant"] = "qdrant"
    url: str = "http://127.0.0.1:6333"
    collection: str = "enzyme_immobilization"
    timeout_seconds: float = Field(default=30.0, gt=0)


class EmbeddingConfig(StrictBaseModel):
    provider: Literal["hash_v1", "sentence"] = "hash_v1"
    dimensions: int = Field(default=384, ge=64, le=4096)
    model_name: str = Field(default="BAAI/bge-base-en-v1.5")
    device: str = Field(default="mps")
    cache_folder: Optional[str] = None
    local_files_only: bool = False


class RetrievalConfig(StrictBaseModel):
    top_k: int = Field(default=8, ge=1, le=100)
    usable_only: bool = True


class GeneratorProviderConfig(StrictBaseModel):
    enabled: bool = False
    model: str
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None

    @field_validator("model")
    @classmethod
    def model_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must not be empty")
        return value


class GeneratorConfig(StrictBaseModel):
    provider: str = "mock"
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)


class RuntimeConfig(StrictBaseModel):
    document_parser: DocumentParserConfig = Field(default_factory=DocumentParserConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generator: GeneratorConfig = Field(default_factory=GeneratorConfig)
    generator_providers: Dict[str, GeneratorProviderConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_generator_provider(self) -> "RuntimeConfig":
        provider = self.generator.provider
        if provider not in self.generator_providers:
            raise ValueError(f"generator provider is not configured: {provider}")
        provider_config = self.generator_providers[provider]
        if not provider_config.enabled:
            raise ValueError(f"generator provider is disabled: {provider}")
        if provider != "mock":
            if not provider_config.base_url:
                raise ValueError(f"base_url is required for generator provider: {provider}")
            if not provider_config.api_key_env:
                raise ValueError(f"api_key_env is required for generator provider: {provider}")
        return self

    @classmethod
    def from_file(cls, path: Path | str) -> "RuntimeConfig":
        path = Path(path).expanduser().resolve()
        payload = load_config_mapping(path)
        return cls.model_validate(payload)

    def require_generator_api_key(self) -> str:
        provider = self.generator.provider
        provider_config = self.generator_providers[provider]
        if provider == "mock":
            return ""
        assert provider_config.api_key_env is not None
        load_local_env_files()
        value = os.environ.get(provider_config.api_key_env)
        if not value:
            raise RuntimeConfigError(
                f"missing API key env var for generator provider {provider}: {provider_config.api_key_env}"
            )
        return value


_LOCAL_ENV_LOADED = False


def load_local_env_files() -> None:
    global _LOCAL_ENV_LOADED
    if _LOCAL_ENV_LOADED:
        return
    _LOCAL_ENV_LOADED = True
    candidates = [
        Path.cwd() / ".env.local",
        Path.cwd() / ".env",
    ]
    for path in candidates:
        if path.exists():
            load_env_file(path)


def load_env_file(path: Path) -> None:
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeConfigError(f"invalid env line in {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise RuntimeConfigError(f"empty env key in {path}:{line_number}")
        os.environ.setdefault(key, value)


def load_config_mapping(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = parse_minimal_yaml(text, path)
    if not isinstance(payload, dict):
        raise RuntimeConfigError(f"runtime config must be a mapping: {path}")
    return payload


def parse_minimal_yaml(text: str, path: Path) -> Dict[str, Any]:
    """Parse the small YAML subset used by configs/local.yaml.

    This avoids forcing PyYAML into the MVP runtime. It supports nested mappings
    with two-space indentation and scalar values. Lists, anchors and multiline
    strings intentionally fail fast with a clear config error.
    """

    root: Dict[str, Any] = {}
    stack: list[tuple[int, Dict[str, Any]]] = [(-1, root)]

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line:
            raise RuntimeConfigError(f"tabs are not supported in {path}:{line_number}")
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent % 2 != 0:
            raise RuntimeConfigError(f"indentation must use multiples of two spaces in {path}:{line_number}")
        stripped = strip_inline_comment(raw_line.strip())
        if not stripped:
            continue
        if stripped.startswith("- "):
            raise RuntimeConfigError(f"lists are not supported by the minimal YAML parser in {path}:{line_number}")
        if ":" not in stripped:
            raise RuntimeConfigError(f"expected key: value in {path}:{line_number}")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            raise RuntimeConfigError(f"empty key in {path}:{line_number}")

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise RuntimeConfigError(f"invalid indentation in {path}:{line_number}")
        parent = stack[-1][1]

        if raw_value == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(raw_value)

    return root


def strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value


def parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value
