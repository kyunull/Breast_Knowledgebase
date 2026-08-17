from __future__ import annotations

import json
from pathlib import Path

from app.ingestion import read_jsonl
from scripts.reinsert_csco_tables import (
    convert_csco_ocr,
    linearize_table_rows,
    render_table_html,
)


def _cell(
    row_tl: int,
    col_tl: int,
    row_br: int,
    col_br: int,
    text: str,
    *,
    confidence: float = 100,
) -> dict[str, object]:
    return {
        "RowTl": row_tl,
        "ColTl": col_tl,
        "RowBr": row_br,
        "ColBr": col_br,
        "Text": text,
        "Type": "body",
        "Confidence": confidence,
        "Polygon": [],
    }


def _table(
    *, top: int, bottom: int, cells: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "Type": 1,
        "TableCoordPoint": [
            {"X": 100, "Y": top},
            {"X": 1100, "Y": top},
            {"X": 1100, "Y": bottom},
            {"X": 100, "Y": bottom},
        ],
        "Cells": cells,
    }


TABLE_WITH_SPAN = _table(
    top=100,
    bottom=400,
    cells=[
        _cell(0, 0, 1, 1, "分层"),
        _cell(0, 1, 1, 3, "推荐方案"),
        _cell(1, 0, 3, 1, "A&B"),
        _cell(1, 1, 2, 2, "方案甲"),
        _cell(1, 2, 2, 3, "证据1"),
        _cell(2, 1, 3, 2, "方案乙\n第二行"),
        _cell(2, 2, 3, 3, "证据2"),
    ],
)


def test_render_table_html_preserves_spans_and_escapes_text() -> None:
    table_html = render_table_html(TABLE_WITH_SPAN)

    assert '<th colspan="2"' in table_html
    assert '<td rowspan="2"' in table_html
    assert "A&amp;B" in table_html
    assert "方案乙<br>第二行" in table_html
    assert table_html.count("<tr>") == 3


def test_linearize_table_rows_carries_headers_and_merged_values() -> None:
    rows = linearize_table_rows(TABLE_WITH_SPAN, table_title="治疗方案")

    assert rows[0] == "表格：治疗方案\n表头：第1列=分层；第2-3列=推荐方案"
    assert rows[1] == (
        "表格：治疗方案\n第2行：分层=A&B；推荐方案（第2列）=方案甲；"
        "推荐方案（第3列）=证据1"
    )
    assert rows[2] == (
        "表格：治疗方案\n第3行：分层=A&B；推荐方案（第2列）=方案乙\n第二行；"
        "推荐方案（第3列）=证据2"
    )


def test_convert_csco_ocr_replaces_two_tables_and_writes_valid_jsonl(
    tmp_path: Path,
) -> None:
    source_markdown = tmp_path / "guideline_ocr.md"
    source_markdown.write_text(
        "# 2026 CSCO Breast Cancer Guideline OCR\n\n"
        "---\n\n## PDF page 55\n\n"
        "## （四）三阴性乳腺癌新辅助治疗\n\n"
        "### 1. 新辅助化疗+免疫治疗\n\n"
        '<div style="text-align: center;"><img src="pages_markdown/imgs/'
        'img_in_table_box_112_199_1102_332.jpg" alt="Image" width="83%" /></div>\n\n'
        "### 2. 新辅助化疗\n\n"
        '<div style="text-align: center;"><img src="pages_markdown/imgs/'
        'img_in_table_box_110_422_1101_617.jpg" alt="Image" width="83%" /></div>\n',
        encoding="utf-8",
    )
    tencent_dir = tmp_path / "raw_json"
    tencent_dir.mkdir()
    ignored_region = {
        "Type": 0,
        "TableCoordPoint": [{"X": 1, "Y": 1}, {"X": 2, "Y": 2}],
        "Cells": [_cell(-1, -1, -1, -1, "页眉")],
    }
    first_table = _table(
        top=196,
        bottom=336,
        cells=[
            _cell(0, 0, 1, 1, "I级推荐"),
            _cell(0, 1, 1, 2, "II级推荐"),
            _cell(1, 0, 2, 1, "方案A"),
            _cell(1, 1, 2, 2, "方案B"),
        ],
    )
    second_table = _table(
        top=420,
        bottom=618,
        cells=[
            _cell(0, 0, 1, 1, "I级推荐"),
            _cell(0, 1, 1, 2, "II级推荐"),
            _cell(1, 0, 2, 1, "方案C"),
            _cell(1, 1, 2, 2, "方案D"),
        ],
    )
    (tencent_dir / "source-page-055.json").write_text(
        json.dumps(
            {"TableDetections": [ignored_region, second_table, first_table]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_markdown = tmp_path / "guideline_ocr_with_tables.md"
    output_jsonl = tmp_path / "csco_breast_2026_table_aware.jsonl"

    report = convert_csco_ocr(
        source_markdown=source_markdown,
        tencent_json_dir=tencent_dir,
        output_markdown=output_markdown,
        output_jsonl=output_jsonl,
    )

    restored = output_markdown.read_text(encoding="utf-8")
    records = [
        json.loads(line)
        for line in output_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert report.markdown_replacements == 2
    assert report.table_count == 2
    assert report.row_record_count == 4
    assert restored.count("<table") == 2
    assert "img_in_table_box" not in restored
    assert restored.index("方案A") < restored.index("方案C")
    assert len(records) == 6
    assert len(read_jsonl(output_jsonl)) == 6
    assert len({record["chunk_id"] for record in records}) == 6
    assert {record["block_type"] for record in records} == {"table", "table_row"}
    assert {record["page_start"] for record in records} == {54}
    assert records[0]["chunk_id"] == "csco_2026_p055_t01"
    assert records[0]["section_path"].endswith("1. 新辅助化疗+免疫治疗")
    assert "I级推荐=方案A" in records[2]["text"]
    assert records[3]["chunk_id"] == "csco_2026_p055_t02"
    assert "II级推荐=方案D" in records[5]["text"]


def test_convert_csco_ocr_rejects_table_count_mismatch(tmp_path: Path) -> None:
    source_markdown = tmp_path / "guideline_ocr.md"
    source_markdown.write_text(
        "## PDF page 18\n\n"
        '<div><img src="pages_markdown/imgs/'
        'img_in_table_box_100_200_1100_500.jpg" /></div>\n',
        encoding="utf-8",
    )
    tencent_dir = tmp_path / "raw_json"
    tencent_dir.mkdir()
    (tencent_dir / "source-page-018.json").write_text(
        json.dumps({"TableDetections": []}),
        encoding="utf-8",
    )

    try:
        convert_csco_ocr(
            source_markdown=source_markdown,
            tencent_json_dir=tencent_dir,
            output_markdown=tmp_path / "out.md",
            output_jsonl=tmp_path / "out.jsonl",
        )
    except ValueError as error:
        assert "PDF page 18" in str(error)
        assert "1 table images but 0 valid Tencent tables" in str(error)
    else:
        raise AssertionError("table/image count mismatch must fail closed")


def test_convert_csco_ocr_groups_two_tables_inside_one_image_box(tmp_path: Path) -> None:
    source_markdown = tmp_path / "guideline_ocr.md"
    source_markdown.write_text(
        "## PDF page 183\n\n## 1. TKI相关性腹泻\n\n腹泻处理说明。\n\n"
        "## PDF page 184\n\n"
        '<div><img src="pages_markdown/imgs/'
        'img_in_table_box_90_101_1089_521.jpg" /></div>\n',
        encoding="utf-8",
    )
    tencent_dir = tmp_path / "raw_json"
    tencent_dir.mkdir()
    first_table = _table(
        top=100,
        bottom=295,
        cells=[
            _cell(0, 0, 1, 1, "时间"),
            _cell(0, 1, 1, 2, "剂量"),
            _cell(1, 0, 2, 1, "第1周"),
            _cell(1, 1, 2, 2, "4"),
        ],
    )
    second_table = _table(
        top=327,
        bottom=523,
        cells=[
            _cell(0, 0, 1, 1, "时间"),
            _cell(0, 1, 1, 2, "奈拉替尼剂量"),
            _cell(1, 0, 2, 1, "第1周"),
            _cell(1, 1, 2, 2, "120"),
        ],
    )
    (tencent_dir / "source-page-184.json").write_text(
        json.dumps({"TableDetections": [first_table, second_table]}, ensure_ascii=False),
        encoding="utf-8",
    )
    output_markdown = tmp_path / "guideline_ocr_with_tables.md"
    output_jsonl = tmp_path / "csco_breast_2026_table_aware.jsonl"

    report = convert_csco_ocr(
        source_markdown=source_markdown,
        tencent_json_dir=tencent_dir,
        output_markdown=output_markdown,
        output_jsonl=output_jsonl,
    )

    restored = output_markdown.read_text(encoding="utf-8")
    records = [
        json.loads(line)
        for line in output_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert report.markdown_replacements == 1
    assert report.table_count == 2
    assert report.row_record_count == 4
    assert restored.count("<table") == 2
    assert restored.index("第1周") < restored.index("奈拉替尼剂量")
    assert [record["chunk_id"] for record in records if record["block_type"] == "table"] == [
        "csco_2026_p184_t01",
        "csco_2026_p184_t02",
    ]
    assert {
        record["table_title"] for record in records if record["block_type"] == "table"
    } == {"1. TKI相关性腹泻"}


def test_convert_csco_ocr_accepts_table_box_that_contains_the_image_box(
    tmp_path: Path,
) -> None:
    source_markdown = tmp_path / "guideline_ocr.md"
    source_markdown.write_text(
        "## PDF page 163\n\n"
        '<div><img src="pages_markdown/imgs/'
        'img_in_table_box_109_204_1105_601.jpg" /></div>\n',
        encoding="utf-8",
    )
    tencent_dir = tmp_path / "raw_json"
    tencent_dir.mkdir()
    expanded_table = _table(
        top=201,
        bottom=823,
        cells=[
            _cell(0, 0, 1, 1, "致吐风险分级"),
            _cell(0, 1, 1, 2, "方案"),
            _cell(1, 0, 2, 1, "高致吐风险"),
            _cell(1, 1, 2, 2, "三联方案"),
        ],
    )
    (tencent_dir / "source-page-163.json").write_text(
        json.dumps({"TableDetections": [expanded_table]}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = convert_csco_ocr(
        source_markdown=source_markdown,
        tencent_json_dir=tencent_dir,
        output_markdown=tmp_path / "out.md",
        output_jsonl=tmp_path / "out.jsonl",
    )

    assert report.markdown_replacements == 1
    assert report.table_count == 1


def test_convert_csco_ocr_emits_non_table_text_around_table_in_source_order(
    tmp_path: Path,
) -> None:
    source_markdown = tmp_path / "guideline_ocr.md"
    source_markdown.write_text(
        "# OCR pipeline title\n\nSource: scanned PDF.\n\n"
        "---\n\n## PDF page 26\n\n"
        "## HER2阳性乳腺癌\n\n"
        "表格前的诊疗正文，必须进入检索。\n\n"
        '<div><img src="pages_markdown/imgs/'
        'img_in_table_box_100_200_1100_500.jpg" /></div>\n\n'
        "注：表格后的说明也必须进入检索。\n\n"
        '<div><img src="pages_markdown/imgs/img_in_image_box_1_2_3_4.jpg" /></div>\n',
        encoding="utf-8",
    )
    tencent_dir = tmp_path / "raw_json"
    tencent_dir.mkdir()
    table = _table(
        top=201,
        bottom=499,
        cells=[
            _cell(0, 0, 1, 1, "分层"),
            _cell(0, 1, 1, 2, "推荐"),
            _cell(1, 0, 2, 1, "HER2阳性"),
            _cell(1, 1, 2, 2, "治疗方案A"),
        ],
    )
    (tencent_dir / "source-page-026.json").write_text(
        json.dumps({"TableDetections": [table]}, ensure_ascii=False),
        encoding="utf-8",
    )
    output_jsonl = tmp_path / "out.jsonl"

    report = convert_csco_ocr(
        source_markdown=source_markdown,
        tencent_json_dir=tencent_dir,
        output_markdown=tmp_path / "out.md",
        output_jsonl=output_jsonl,
    )

    records = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    block_types = [record["block_type"] for record in records]
    assert report.text_record_count == 2
    assert block_types == ["paragraph", "table", "table_row", "table_row", "note"]
    assert records[0]["text"] == "表格前的诊疗正文，必须进入检索。"
    assert records[0]["section_path"] == "HER2阳性乳腺癌"
    assert records[-1]["text"] == "注：表格后的说明也必须进入检索。"
    assert records[-1]["chunk_id"] == "csco_2026_p026_b002"
    assert all("img_in_image_box" not in record["text"] for record in records)
    assert all("OCR pipeline title" not in record["text"] for record in records)


def test_convert_csco_ocr_splits_long_paragraph_without_losing_characters(
    tmp_path: Path,
) -> None:
    long_paragraph = "甲" * 450 + "。" + "乙" * 450 + "。" + "丙" * 300 + "。"
    source_markdown = tmp_path / "guideline_ocr.md"
    source_markdown.write_text(
        "## PDF page 30\n\n## 长段落章节\n\n" + long_paragraph + "\n",
        encoding="utf-8",
    )
    tencent_dir = tmp_path / "raw_json"
    tencent_dir.mkdir()
    output_jsonl = tmp_path / "out.jsonl"

    convert_csco_ocr(
        source_markdown=source_markdown,
        tencent_json_dir=tencent_dir,
        output_markdown=tmp_path / "out.md",
        output_jsonl=output_jsonl,
    )

    records = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert all(record["block_type"] == "paragraph" for record in records)
    assert all(len(record["text"]) <= 900 for record in records)
    assert "".join(record["text"] for record in records) == long_paragraph


def test_convert_csco_ocr_preserves_clinical_comparison_operators(
    tmp_path: Path,
) -> None:
    source_markdown = tmp_path / "guideline_ocr.md"
    source_markdown.write_text(
        "## PDF page 169\n\n"
        '<div style="text-align: center;">贫血处理</div>\n\n'
        "缺铁（SF 30~500g/L且TSAT<50%）。\n"
        "非缺铁（SF>800g/L或TSAT≥50%）。\n"
        "肿块T<2cm，年龄<40岁，另一肿块>2cm。\n",
        encoding="utf-8",
    )
    tencent_dir = tmp_path / "raw_json"
    tencent_dir.mkdir()
    output_jsonl = tmp_path / "out.jsonl"

    convert_csco_ocr(
        source_markdown=source_markdown,
        tencent_json_dir=tencent_dir,
        output_markdown=tmp_path / "out.md",
        output_jsonl=output_jsonl,
    )

    records = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    text = "\n".join(record["text"] for record in records)
    assert "贫血处理" in text
    assert "TSAT<50%" in text
    assert "SF>800g/L" in text
    assert "T<2cm" in text
    assert "年龄<40岁" in text
    assert "肿块>2cm" in text
    assert "<div" not in text
