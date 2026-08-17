from __future__ import annotations

import pytest

from scripts.table_ocr_core import (
    TableBox,
    build_table_grid,
    group_tables_by_boxes,
    linearize_table_rows,
    make_table_records,
    valid_tables,
)


def _cell(row_tl: int, col_tl: int, row_br: int, col_br: int, text: str) -> dict[str, object]:
    return {
        "RowTl": row_tl,
        "ColTl": col_tl,
        "RowBr": row_br,
        "ColBr": col_br,
        "Text": text,
        "Confidence": 98.0,
    }


TABLE_WITH_SPAN = {
    "Type": 1,
    "TableCoordPoint": [
        {"X": 100, "Y": 100},
        {"X": 500, "Y": 100},
        {"X": 500, "Y": 400},
        {"X": 100, "Y": 400},
    ],
    "Cells": [
        _cell(0, 0, 1, 1, "分层"),
        _cell(0, 1, 1, 2, "方案"),
        _cell(1, 0, 3, 1, "A&B"),
        _cell(1, 1, 2, 2, "方案甲"),
        _cell(2, 1, 3, 2, "方案乙"),
    ],
}


def test_grid_and_linearization_preserve_rowspan() -> None:
    grid = build_table_grid(TABLE_WITH_SPAN)
    assert (grid.rows, grid.columns) == (3, 2)
    rows = linearize_table_rows(TABLE_WITH_SPAN, table_title="治疗方案")
    assert rows[1] == "表格：治疗方案\n第2行：分层=A&B；方案=方案甲"
    assert rows[2] == "表格：治疗方案\n第3行：分层=A&B；方案=方案乙"


def test_grid_rejects_invalid_and_overlapping_cells() -> None:
    with pytest.raises(ValueError, match="span"):
        build_table_grid({"Cells": [_cell(1, 0, 1, 1, "bad")]})
    with pytest.raises(ValueError, match="overlap"):
        build_table_grid(
            {"Cells": [_cell(0, 0, 1, 2, "a"), _cell(0, 1, 1, 2, "b")]}
        )


def test_valid_tables_filters_non_table_detections() -> None:
    payload = {"TableDetections": [{"Type": 0}, {"Type": 1}, {"Type": 2}, {"Type": 3}]}
    assert len(valid_tables(payload)) == 2


def test_geometry_groups_tables_in_reading_order() -> None:
    boxes = [
        TableBox(page_number=7, x0=0, y0=0, x1=100, y1=100),
        TableBox(page_number=7, x0=0, y0=120, x1=100, y1=220),
    ]
    tables = [
        {**TABLE_WITH_SPAN, "TableCoordPoint": [{"X": 10, "Y": 130}, {"X": 90, "Y": 130}, {"X": 90, "Y": 210}, {"X": 10, "Y": 210}]},
        {**TABLE_WITH_SPAN, "TableCoordPoint": [{"X": 10, "Y": 10}, {"X": 90, "Y": 10}, {"X": 90, "Y": 90}, {"X": 10, "Y": 90}]},
    ]
    grouped = group_tables_by_boxes(boxes, tables, page_number=7)
    assert len(grouped) == 2
    assert grouped[0][0]["TableCoordPoint"][0]["Y"] == 10
    with pytest.raises(ValueError, match="match"):
        group_tables_by_boxes(
            boxes,
            [
                {
                    **TABLE_WITH_SPAN,
                    "TableCoordPoint": [
                        {"X": 500, "Y": 500},
                        {"X": 550, "Y": 500},
                        {"X": 550, "Y": 550},
                        {"X": 500, "Y": 550},
                    ],
                }
            ],
            page_number=7,
        )


def test_make_table_records_emits_parent_and_rows() -> None:
    records = make_table_records(
        table=TABLE_WITH_SPAN,
        doc_id="caca_2026",
        doc_title="CACA 2026",
        page_index=25,
        page_code=None,
        section_path="4.2 腋窝处理",
        table_index=1,
        table_title="SLNB指征",
        source_image="source-page-026.png",
    )
    assert records[0]["chunk_id"] == "caca_2026_p026_t01"
    assert records[1]["chunk_id"] == "caca_2026_p026_t01_r01"
    assert records[0]["block_type"] == "table"
    assert all(record["page_start"] == 25 for record in records)
    assert len(records) == 4
    assert records[1]["table_row_index"] == 1
