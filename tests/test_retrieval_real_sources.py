from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_real_source_report_records_indexable_filter_and_guideline_coverage():
    report = PROJECT_ROOT / "data" / "reports" / "retrieval-multilingual-r1.json"
    assert report.is_file()
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert payload["queries"]
    assert payload["source_versions"]
    assert payload["cover_nodes_excluded"] >= 1
