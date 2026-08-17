from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.project_paths import discover_project_root


class PathOutsideProjectError(ValueError):
    """Raised when a configured writable path is not below the project root."""


_RUNTIME_DIRECTORY_VARIABLES = (
    "TEMP",
    "TMP",
    "PIP_CACHE_DIR",
    "HF_HOME",
    "HUGGINGFACE_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "SENTENCE_TRANSFORMERS_HOME",
    "TORCH_HOME",
)

_DEFAULT_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    data_dir: Path
    registry_db_path: Path
    managed_sources_dir: Path
    index_root: Path
    model_cache_dir: Path
    runtime_cache_dir: Path
    model_name: str
    model_revision: str | None
    model_device: str
    model_max_seq_length: int
    embedding_batch_size: int
    model_local_files_only: bool
    bm25_enabled: bool
    embedding_provider: str = "local"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = field(default=None, repr=False)
    embedding_model: str | None = None
    embedding_dimension: int = 1024
    embedding_timeout_seconds: float = 30.0
    embedding_max_retries: int = 2

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Settings":
        root = (Path(project_root) if project_root is not None else discover_project_root()).resolve()
        embedding_provider = os.getenv("KB_EMBEDDING_PROVIDER", "local").strip()
        if embedding_provider not in {"local", "remote"}:
            raise ValueError("KB_EMBEDDING_PROVIDER must be 'local' or 'remote'")
        embedding_base_url = os.getenv("KB_EMBEDDING_BASE_URL") or None
        embedding_api_key = os.getenv("KB_EMBEDDING_API_KEY") or None
        embedding_model = os.getenv("KB_EMBEDDING_MODEL") or None
        if embedding_provider == "remote":
            if embedding_base_url is None:
                raise ValueError("KB_EMBEDDING_BASE_URL is required in remote mode")
            if embedding_api_key is None:
                raise ValueError("KB_EMBEDDING_API_KEY is required in remote mode")
            if embedding_model is None:
                raise ValueError("KB_EMBEDDING_MODEL is required in remote mode")
        data_dir = _project_path("KB_DATA_DIR", root / "data", root)
        runtime_cache_dir = _project_path(
            "KB_RUNTIME_CACHE_DIR", data_dir / "runtime_cache", root
        )
        return cls(
            project_root=root,
            data_dir=data_dir,
            registry_db_path=_project_path(
                "KB_REGISTRY_DB_PATH", data_dir / "registry" / "knowledge.sqlite3", root
            ),
            managed_sources_dir=_project_path(
                "KB_MANAGED_SOURCES_DIR", data_dir / "managed_sources", root
            ),
            index_root=_project_path("KB_INDEX_ROOT", data_dir / "llama_indices", root),
            model_cache_dir=_project_path(
                "KB_MODEL_CACHE_DIR", data_dir / "model_cache", root
            ),
            runtime_cache_dir=runtime_cache_dir,
            model_name=os.getenv("KB_MODEL_NAME", "BAAI/bge-m3"),
            model_revision=os.getenv("KB_MODEL_REVISION") or _DEFAULT_MODEL_REVISION,
            model_device=os.getenv("KB_MODEL_DEVICE", "cpu"),
            model_max_seq_length=_positive_int("KB_MODEL_MAX_SEQ_LENGTH", 512),
            embedding_batch_size=_positive_int("KB_EMBEDDING_BATCH_SIZE", 4),
            model_local_files_only=_bool(
                os.getenv("KB_MODEL_LOCAL_FILES_ONLY", "false")
            ),
            bm25_enabled=_bool(os.getenv("KB_BM25_ENABLED", "true")),
            embedding_provider=embedding_provider,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_api_key,
            embedding_model=embedding_model,
            embedding_dimension=_positive_int("KB_EMBEDDING_DIMENSION", 1024),
            embedding_timeout_seconds=_positive_float(
                "KB_EMBEDDING_TIMEOUT_SECONDS", 30.0
            ),
            embedding_max_retries=_nonnegative_int(
                "KB_EMBEDDING_MAX_RETRIES", 2
            ),
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.data_dir,
            self.registry_db_path.parent,
            self.managed_sources_dir,
            self.index_root,
            self.model_cache_dir,
            self.runtime_cache_dir,
            *self.runtime_directories(),
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def runtime_directories(self) -> tuple[Path, ...]:
        environment = self.runtime_environment()
        return tuple(
            Path(environment[name]) for name in _RUNTIME_DIRECTORY_VARIABLES
        )

    def runtime_environment(self) -> dict[str, str]:
        pip_cache_dir = self.runtime_cache_dir / "pip_cache"
        temp_dir = self.runtime_cache_dir / "tmp"
        hf_home = self.model_cache_dir / "huggingface"
        environment = {
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "PIP_CACHE_DIR": str(pip_cache_dir),
            "HF_HOME": str(self.model_cache_dir),
            "HUGGINGFACE_HUB_CACHE": str(self.model_cache_dir),
            "TRANSFORMERS_CACHE": str(hf_home / "transformers"),
            "SENTENCE_TRANSFORMERS_HOME": str(self.model_cache_dir / "sentence_transformers"),
            "TORCH_HOME": str(self.model_cache_dir / "torch"),
            "HF_HUB_DISABLE_XET": "1",
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        }
        if self.model_local_files_only:
            environment["HF_HUB_OFFLINE"] = "1"
        return environment

    def resolve_project_path(self, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            if path.parts and path.parts[0] == "data":
                project_path = (self.project_root / path).resolve()
                if project_path.is_relative_to(self.data_dir.resolve()):
                    path = project_path
                else:
                    path = self.data_dir.joinpath(*path.parts[1:])
            else:
                path = self.project_root / path
        resolved = path.resolve()
        if not resolved.is_relative_to(self.project_root):
            raise PathOutsideProjectError(
                f"path must resolve below the project root: {self.project_root}"
            )
        return resolved


def _project_path(name: str, default: Path, project_root: Path) -> Path:
    value = os.getenv(name)
    path = Path(value) if value else default
    if not path.is_absolute():
        path = project_root / path
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(project_root):
        raise PathOutsideProjectError(
            f"{name} must resolve below the project root: {project_root}"
        )
    return resolved_path


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
