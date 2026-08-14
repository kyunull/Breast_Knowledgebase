from __future__ import annotations

from pathlib import Path


class ProjectRootDiscoveryError(RuntimeError):
    """Raised when no repository root can be found from an anchor path."""


def discover_project_root(anchor: Path | str | None = None) -> Path:
    """Find the nearest repository root containing ``pyproject.toml`` and ``app``."""
    start = Path(anchor) if anchor is not None else Path(__file__)
    start = start.resolve()
    if start.is_file():
        start = start.parent

    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "app").is_dir():
            return candidate

    raise ProjectRootDiscoveryError(
        f"could not discover project root from anchor: {start}"
    )
