from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.source_contract import build_source_contract_report


PROJECT_ROOT = Path(r"D:\coding\knowledgebase")
SOURCE_ROOT = Path(
    r"D:\document\HER2乳腺癌专病demo项目\pipeline\标准文档分块解析"
)
EXPECTED_COUNTS = {
    "caca_2026.jsonl": 324,
    "gradishar_nccn_v4_2026.jsonl": 9,
    "nccn_v6_2026.jsonl": 786,
    "oncotoolkit_her2_2026.jsonl": 31,
}
EXPECTED_CACA_SHA256 = (
    "983e26188f574a8200f367347175e2bfb79c4d430ffd0b26fc2a5187fc62d1f5"
)


def test_source_contract_rejects_a_report_path_outside_the_d_project() -> None:
    with pytest.raises(ValueError, match="report path must remain below project root"):
        build_source_contract_report(
            {}, report_path=Path(r"C:\outside-project\source-contract-report.json")
        )


@pytest.mark.skipif(
    os.getenv("KB_REAL_SOURCE_TESTS") != "1",
    reason="set KB_REAL_SOURCE_TESTS=1 to validate the user-supplied source JSONL files",
)
def test_user_supplied_jsonl_files_meet_the_recorded_source_contract() -> None:
    report_path = PROJECT_ROOT / "data" / "reports" / "source-contract-report.json"

    report = build_source_contract_report(
        {name: SOURCE_ROOT / name for name in EXPECTED_COUNTS},
        report_path=report_path,
    )

    assert report["files"]["caca_2026.jsonl"]["sha256"] == EXPECTED_CACA_SHA256
    assert {
        name: entry["record_count"] for name, entry in report["files"].items()
    } == EXPECTED_COUNTS
    assert report["total_records"] == 1150
    assert report["all_chunk_ids_unique"] is True
    assert all(entry["missing_required_fields"] == [] for entry in report["files"].values())
    assert report_path.is_file()
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
