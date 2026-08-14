from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.api import IngestModel, to_domain_ingest
from app.contracts import GuidelineInput
from app.lifecycle import GuidelineIngestRequest
from app.project_paths import discover_project_root
from app.service import GuidelineService
from app.settings import Settings


def load_ingest_config(
    path: Path, *, project_root: Path | None = None
) -> tuple[str, GuidelineIngestRequest, GuidelineInput | None]:
    root = (
        Path(project_root) if project_root is not None else discover_project_root()
    ).resolve()
    config_path = Path(path).resolve()
    if not config_path.is_relative_to(root):
        raise ValueError(f"config path must resolve below project root: {root}")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"config is not valid JSON: {error.msg}") from error
    try:
        model = IngestModel.model_validate(payload)
    except ValidationError as error:
        raise ValueError(f"invalid ingest config: {error}") from error
    request, guideline = to_domain_ingest(model)
    return model.actor, request, guideline


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a guideline as a draft version")
    parser.add_argument("--config", required=True, type=Path)
    arguments = parser.parse_args()
    actor, request, guideline = load_ingest_config(arguments.config)
    service = GuidelineService(Settings.from_env())
    version = service.ingest(request, actor=actor, guideline=guideline)
    print(version.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
