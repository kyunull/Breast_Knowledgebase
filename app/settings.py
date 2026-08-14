from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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

    @classmethod
    def from_env(cls, project_root: Path) -> "Settings":
        root = Path(project_root).resolve()
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
            model_revision=os.getenv("KB_MODEL_REVISION") or None,
            model_device=os.getenv("KB_MODEL_DEVICE", "cpu"),
            model_max_seq_length=_positive_int("KB_MODEL_MAX_SEQ_LENGTH", 512),
            embedding_batch_size=_positive_int("KB_EMBEDDING_BATCH_SIZE", 4),
            model_local_files_only=_bool(
                os.getenv("KB_MODEL_LOCAL_FILES_ONLY", "false")
            ),
            bm25_enabled=_bool(os.getenv("KB_BM25_ENABLED", "true")),
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


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
