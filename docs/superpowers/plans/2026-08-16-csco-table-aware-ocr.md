# CSCO Table-Aware OCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Tencent Cloud table OCR output at each original CSCO OCR table-image location and produce a provenance-preserving JSONL input optimized for row-level retrieval.

**Architecture:** A standalone deterministic converter reads the immutable OCR Markdown and Tencent raw table JSON. It replaces each table image in the merged Markdown with span-aware HTML table markup, then emits the complete document as heading-aware paragraph chunks plus table and table-row JSONL records in original source order. The source Markdown and Tencent OCR payloads remain unchanged.

**Tech Stack:** Python 3.12 standard library, pytest 8.4, existing JSONL source contract.

## Global Constraints

- Preserve `C:\Users\PC\Documents\Codex\2026-08-15\zh\outputs\2026CSCO_breast_cancer_guideline_OCR\guideline_ocr.md` byte-for-byte.
- Create exactly two user-facing outputs: `guideline_ocr_with_tables.md` and `csco_breast_2026_table_aware.jsonl`.
- Treat only Tencent `TableDetections` where `Type` is `1` or `2` as tables.
- Match each Tencent table to the containing or overlapping image box by vertical coordinates; page 55 and page 61 each have two images, while page 184 has one image containing two separate tables.
- Preserve merged cells using HTML `rowspan` and `colspan`; never use pipe-table syntax for source restoration.
- Keep retrieval text as plain, header-qualified Chinese text; do not embed HTML as `text` in JSONL.
- Include every non-table OCR text block in the JSONL; skip only page separators, pipeline preamble, and image-only tags.
- Every JSONL record must include the current knowledgebase required fields and a zero-based `page_start`/`page_end`.
- Write runtime data below `D:\coding\knowledgebase`; do not install software under `C:\`.

---

### Task 1: Specify and Test Table Reconstruction

**Files:**
- Create: `D:\coding\knowledgebase\tests\test_csco_table_reinsertion.py`
- Create: `D:\coding\knowledgebase\scripts\reinsert_csco_tables.py`

**Interfaces:**
- Produces: `render_table_html(table: Mapping[str, object]) -> str`
- Produces: `linearize_table_rows(table: Mapping[str, object], *, table_title: str) -> list[str]`
- Produces: `convert_csco_ocr(...) -> ConversionReport`

- [x] **Step 1: Write the failing tests**

```python
def test_render_table_html_preserves_spans_and_escapes_text() -> None:
    html = render_table_html(TABLE_WITH_SPAN)
    assert '<td rowspan="2">A&amp;B</td>' in html
    assert '<td colspan="2">Header</td>' in html


def test_linearize_table_rows_carries_headers_and_merged_values() -> None:
    rows = linearize_table_rows(TABLE_WITH_SPAN, table_title="治疗方案")
    assert rows == ["表格：治疗方案\n第一列=A&B；第二列=方案甲"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_csco_table_reinsertion.py -q`

Expected: FAIL because `scripts.reinsert_csco_tables` does not exist.

- [x] **Step 3: Implement the minimum pure conversion functions**

```python
def render_table_html(table: Mapping[str, object]) -> str:
    # Build an occupancy grid from RowTl/RowBr/ColTl/ColBr.
    # Emit only top-left cells with HTML spans and escaped text.
    ...


def linearize_table_rows(table: Mapping[str, object], *, table_title: str) -> list[str]:
    # Expand merged cells over their covered grid before producing row strings.
    ...
```

- [x] **Step 4: Run the focused tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_csco_table_reinsertion.py -q`

Expected: PASS with no warnings.

### Task 2: Specify and Test Source-Level Conversion

**Files:**
- Modify: `D:\coding\knowledgebase\tests\test_csco_table_reinsertion.py`
- Modify: `D:\coding\knowledgebase\scripts\reinsert_csco_tables.py`

**Interfaces:**
- Consumes: page Markdown containing `img_in_table_box_<left>_<top>_<right>_<bottom>.jpg`.
- Consumes: Tencent JSON mapping with `TableDetections`.
- Produces: `ConversionReport(markdown_replacements: int, table_count: int, row_record_count: int, text_record_count: int, page_count: int)`.

- [x] **Step 1: Write the failing end-to-end fixture test**

```python
def test_convert_csco_ocr_replaces_each_table_image_and_writes_row_records(tmp_path: Path) -> None:
    report = convert_csco_ocr(...)
    markdown = output_markdown.read_text(encoding="utf-8")
    records = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    assert report.markdown_replacements == 2
    assert markdown.count("<table") == 2
    assert all("img_in_table_box" not in line for line in markdown.splitlines())
    assert {record["block_type"] for record in records} == {"table", "table_row"}
    assert {record["page_start"] for record in records} == {54}
```

- [x] **Step 2: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_csco_table_reinsertion.py -q`

Expected: FAIL because source-level conversion is not implemented.

- [x] **Step 3: Implement deterministic matching and output writing**

```python
def convert_csco_ocr(
    *, source_markdown: Path, tencent_json_dir: Path,
    output_markdown: Path, output_jsonl: Path,
) -> ConversionReport:
    # Group valid table detections into image boxes by vertical containment.
    # Reject unassigned tables and unmatched image boxes instead of producing incorrect output.
    # Replace only exact image tags in the corresponding merged-PDF-page section.
    # Emit paragraph, table parent, and row records in source order.
    ...
```

- [x] **Step 4: Run the focused tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_csco_table_reinsertion.py -q`

Expected: PASS with no warnings.

### Task 3: Generate and Validate CSCO Deliverables

**Files:**
- Create: `C:\Users\PC\Documents\Codex\2026-08-15\zh\outputs\2026CSCO_breast_cancer_guideline_OCR\guideline_ocr_with_tables.md`
- Create: `D:\coding\knowledgebase\data\staging\csco_breast_2026_table_aware.jsonl`

**Interfaces:**
- Consumes: `convert_csco_ocr` from Task 2.
- Produces: a Markdown review source and valid JSONL knowledgebase source.

- [x] **Step 1: Run the converter with immutable source paths**

Run: `& .\.venv\Scripts\python.exe .\scripts\reinsert_csco_tables.py --source-markdown <absolute path> --tencent-json-dir <absolute path> --output-markdown <absolute path> --output-jsonl <absolute path>`

Expected: prints the replacement, table, and row-record counts.

- [x] **Step 2: Run full structural validation**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_csco_table_reinsertion.py tests\test_real_source_contract.py -q`

Expected: PASS; all output records satisfy the knowledgebase JSONL required fields.

- [x] **Step 3: Validate the generated JSONL with the production reader and inspect representative pages**

Run: `& .\.venv\Scripts\python.exe -c "from pathlib import Path; from app.ingestion import read_jsonl; records=read_jsonl(Path(r'D:\coding\knowledgebase\data\staging\csco_breast_2026_table_aware.jsonl')); assert len(records) == 1071; print(len(records))"`

Expected: prints `1071`; independent coverage checks confirm 91 image replacements, 92 tables, 362 text chunks, 617 table-row chunks, no unmatched image tags, and no missing source text or non-empty Tencent cells.

- [x] **Step 4: Commit**

```powershell
git add scripts/reinsert_csco_tables.py tests/test_csco_table_reinsertion.py docs/superpowers/plans/2026-08-16-csco-table-aware-ocr.md
git commit -m "feat: add CSCO table-aware OCR conversion"
```
