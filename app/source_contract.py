from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from app.ingestion import REQUIRED_CHUNK_FIELDS
from app.project_paths import discover_project_root


def build_source_contract_report(
    source_paths: Mapping[str, Path], *, report_path: Path
) -> dict[str, object]:
    """Validate supplied JSONL inputs without altering their bytes or building an index."""
    file_reports: dict[str, dict[str, object]] = {}
    all_chunk_ids: list[str] = []

    for name, submitted_path in sorted(source_paths.items()):
        source_path = Path(submitted_path)
        if not source_path.is_absolute():
            raise ValueError(f"{name}: absolute source path required: {source_path}")
        path = source_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        source_bytes = path.read_bytes()
        records: list[dict[str, object]] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line.strip("\r\n") == "":
                    raise ValueError(f"{name} line {line_number}: empty JSONL record")
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{name} line {line_number}: invalid JSON: {error.msg}"
                    ) from error
                if not isinstance(payload, dict):
                    raise ValueError(
                        f"{name} line {line_number}: JSONL record must be an object"
                    )
                records.append(payload)

        missing_required_fields = sorted(
            {
                field
                for payload in records
                for field in REQUIRED_CHUNK_FIELDS
                if field not in payload
            }
        )
        chunk_ids = [
            payload["chunk_id"]
            for payload in records
            if isinstance(payload.get("chunk_id"), str) and payload["chunk_id"]
        ]
        if len(chunk_ids) != len(records):
            raise ValueError(f"{name}: every record must have a non-empty chunk_id")
        all_chunk_ids.extend(chunk_ids)
        file_reports[name] = {
            "path": str(path.resolve()),
            "sha256": sha256(source_bytes).hexdigest(),
            "byte_size": len(source_bytes),
            "record_count": len(records),
            "missing_required_fields": missing_required_fields,
            "unique_chunk_ids": len(chunk_ids) == len(set(chunk_ids)),
        }

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": file_reports,
        "total_records": sum(entry["record_count"] for entry in file_reports.values()),
        "all_chunk_ids_unique": len(all_chunk_ids) == len(set(all_chunk_ids)),
        "required_fields": list(REQUIRED_CHUNK_FIELDS),
    }
    report_destination = Path(report_path).resolve()
    project_root = discover_project_root()
    if not report_destination.is_relative_to(project_root):
        raise ValueError(
            f"report path must remain below project root: {project_root}"
        )
    report_destination.parent.mkdir(parents=True, exist_ok=True)
    report_destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
