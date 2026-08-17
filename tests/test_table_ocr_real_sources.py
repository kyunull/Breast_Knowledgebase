from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from app.ingestion import REQUIRED_CHUNK_FIELDS, read_jsonl


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "caca": {
        "path": PROJECT_ROOT / "data" / "staging" / "caca_breast_2026_table_aware.jsonl",
        "report": PROJECT_ROOT / "data" / "reports" / "caca-table-ocr-r1.json",
        "sha256": "329da9f2a3bda6ef671b763bc1985fd5c1262753f49e4df935174df52f20e7d6",
        "record_count": 499,
    },
    "nccn": {
        "path": PROJECT_ROOT / "data" / "staging" / "nccn_breast_v6_2026_table_aware.jsonl",
        "report": PROJECT_ROOT / "data" / "reports" / "nccn-table-ocr-r1.json",
        "sha256": "219f99e36944306775b440946820e484bb4133c9fbec93912ca70a131b5e4165",
        "record_count": 1509,
    },
}
NORMALIZED_CACA = {
    "path": PROJECT_ROOT / "data" / "staging" / "caca_breast_2026_table_aware_r2.jsonl",
    "report": PROJECT_ROOT / "data" / "reports" / "caca-ocr-spacing-r2.json",
    "sha256": "aac41f6c485683900e9eaf5e7a614fa564c05338a181bbf02d8c454cf1765546",
    "input_sha256": "329da9f2a3bda6ef671b763bc1985fd5c1262753f49e4df935174df52f20e7d6",
    "record_count": 499,
}


@pytest.mark.skipif(
    os.getenv("KB_TABLE_OCR_REAL_SOURCE_TESTS") != "1",
    reason="set KB_TABLE_OCR_REAL_SOURCE_TESTS=1 to validate table-aware sources",
)
@pytest.mark.parametrize("source", SOURCES.values(), ids=SOURCES.keys())
def test_table_ocr_sources_meet_recorded_contract(source: dict[str, object]) -> None:
    path = Path(source["path"])
    report_path = Path(source["report"])
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(read_jsonl(path)) == source["record_count"]
    assert sha256(path.read_bytes()).hexdigest() == source["sha256"]
    assert all(field in record for record in records for field in REQUIRED_CHUNK_FIELDS)
    ids = [record["chunk_id"] for record in records]
    assert len(ids) == len(set(ids))
    parents = {record["chunk_id"] for record in records if record["block_type"] == "table"}
    child_parents = {
        record["parent_table_chunk_id"]
        for record in records
        if record["block_type"] == "table_row"
    }
    assert parents == child_parents
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert report["output_jsonl_sha256"] == source["sha256"]
    assert report["baseline_non_table_sha256"] == report["rebuilt_non_table_sha256"]


@pytest.mark.skipif(
    os.getenv("KB_TABLE_OCR_REAL_SOURCE_TESTS") != "1",
    reason="set KB_TABLE_OCR_REAL_SOURCE_TESTS=1 to validate table-aware sources",
)
def test_normalized_caca_source_meets_recorded_contract() -> None:
    source = NORMALIZED_CACA
    path = Path(source["path"])
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(read_jsonl(path)) == source["record_count"]
    assert sha256(path.read_bytes()).hexdigest() == source["sha256"]
    assert all(field in record for record in records for field in REQUIRED_CHUNK_FIELDS)
    ids = [record["chunk_id"] for record in records]
    assert len(ids) == len(set(ids))
    parents = {record["chunk_id"] for record in records if record["block_type"] == "table"}
    child_parents = {
        record["parent_table_chunk_id"]
        for record in records
        if record["block_type"] == "table_row"
    }
    assert parents == child_parents
    assert not any("m a x i m u m" in record["text"] for record in records)
    assert not any("a p p a r e n t" in record["text"] for record in records)

    report = json.loads(Path(source["report"]).read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert report["input_jsonl_sha256"] == source["input_sha256"]
    assert report["output_jsonl_sha256"] == source["sha256"]
    assert report["record_count"] == source["record_count"]
    assert report["affected_record_count"] == 13
    assert report["replacement_count"] == 16
    assert report["residual_lowercase_split_count"] == 0
