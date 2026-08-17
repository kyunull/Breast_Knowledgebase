from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from scripts.rebuild_pdf_tables import (
    CandidateManifest,
    CandidatePage,
    discover_candidates,
    rebuild_jsonl,
    render_candidate_pages,
    verify_rebuild,
)
from scripts.table_ocr_core import TableBox


def _cell(row_tl: int, col_tl: int, row_br: int, col_br: int, text: str) -> dict[str, object]:
    return {"RowTl": row_tl, "ColTl": col_tl, "RowBr": row_br, "ColBr": col_br, "Text": text, "Confidence": 99}


def _table(top: int, bottom: int, left: int = 10, right: int = 190) -> dict[str, object]:
    return {
        "Type": 1,
        "TableCoordPoint": [{"X": left, "Y": top}, {"X": right, "Y": top}, {"X": right, "Y": bottom}, {"X": left, "Y": bottom}],
        "Cells": [_cell(0, 0, 1, 1, "列A"), _cell(0, 1, 1, 2, "列B"), _cell(1, 0, 2, 1, "甲"), _cell(1, 1, 2, 2, "乙")],
    }


def _draw_table(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    page.draw_rect(rect, color=(0, 0, 0), width=1)
    page.draw_line((rect.x0 + rect.width / 2, rect.y0), (rect.x0 + rect.width / 2, rect.y1), color=(0, 0, 0), width=1)
    page.draw_line((rect.x0, rect.y0 + rect.height / 2), (rect.x1, rect.y0 + rect.height / 2), color=(0, 0, 0), width=1)
    page.insert_text((rect.x0 + 10, rect.y0 + 20), "A")
    page.insert_text((rect.x0 + rect.width / 2 + 10, rect.y0 + 20), "B")
    page.insert_text((rect.x0 + 10, rect.y0 + rect.height / 2 + 20), "C")
    page.insert_text((rect.x0 + rect.width / 2 + 10, rect.y0 + rect.height / 2 + 20), "D")


def test_discover_candidates_and_render_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "source.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    _draw_table(page, pymupdf.Rect(10, 10, 190, 90))
    page = document.new_page(width=200, height=200)
    _draw_table(page, pymupdf.Rect(10, 100, 190, 190))
    document.save(pdf_path)
    document.close()
    baseline = [
        {"chunk_id": "p1", "doc_id": "doc", "doc_title": "Doc", "section_path": "S", "page_code": None, "page_start": 0, "page_end": 0, "block_type": "table", "text": "old"},
        {"chunk_id": "p2", "doc_id": "doc", "doc_title": "Doc", "section_path": "S", "page_code": None, "page_start": 1, "page_end": 1, "block_type": "table", "text": "old"},
    ]
    manifest = discover_candidates(pdf_path, baseline)
    assert [page.page_index for page in manifest.pages] == [0, 1]
    assert manifest.pages[0].image_name == "source-page-001.png"
    assert manifest.pages[0].boxes[0].x0 == pytest.approx(10)
    assert manifest.pages[0].scaled_boxes[0].x0 == pytest.approx(20)
    render_dir = tmp_path / "pages"
    render_candidate_pages(pdf_path, manifest, render_dir)
    assert (render_dir / "source-page-001.png").is_file()
    assert (render_dir / "source-page-002.png").is_file()


def test_discover_candidates_fails_when_scan_count_differs(tmp_path: Path) -> None:
    pdf_path = tmp_path / "source.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    _draw_table(page, pymupdf.Rect(10, 10, 190, 90))
    document.save(pdf_path)
    document.close()
    baseline = [{"page_start": 0, "block_type": "table"}]
    with pytest.raises(ValueError, match="count"):
        discover_candidates(pdf_path, baseline + [{"page_start": 0, "block_type": "table"}])


def test_rebuild_replaces_only_tables_and_keeps_non_table_records(tmp_path: Path) -> None:
    baseline = [
        {"chunk_id": "text-1", "doc_id": "doc", "doc_title": "Doc", "section_path": "S", "page_code": None, "page_start": 0, "page_end": 0, "block_type": "text", "text": "前文"},
        {"chunk_id": "old-table", "doc_id": "doc", "doc_title": "Doc", "section_path": "S", "page_code": None, "page_start": 0, "page_end": 0, "block_type": "table", "table_title": "治疗", "text": "旧表格"},
        {"chunk_id": "text-2", "doc_id": "doc", "doc_title": "Doc", "section_path": "S", "page_code": None, "page_start": 0, "page_end": 0, "block_type": "text", "text": "后文"},
    ]
    manifest = CandidateManifest(
        pdf_path="source.pdf",
        page_count=1,
        pages=(
            CandidatePage(
                page_index=0,
                page_number=1,
                image_name="source-page-001.png",
                boxes=(TableBox(1, 0, 0, 100, 100),),
                scaled_boxes=(TableBox(1, 0, 0, 200, 200),),
            ),
        ),
    )
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "source-page-001.json").write_text(json.dumps({"TableDetections": [_table(10, 90, 10, 190)]}, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "rebuilt.jsonl"
    report = rebuild_jsonl(baseline_jsonl=tmp_path / "baseline.jsonl", candidate_manifest=manifest, tencent_json_dir=raw_dir, output_jsonl=output, baseline_records=baseline)
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [record["text"] for record in records if record["block_type"] == "text"] == ["前文", "后文"]
    assert [record["block_type"] for record in records] == ["text", "table", "table_row", "table_row", "text"]
    assert records[1]["chunk_id"] == "doc_p001_t01"
    assert report.rebuilt_table_count == 1
    verified = verify_rebuild(baseline, records, report)
    assert verified["status"] == "complete"
