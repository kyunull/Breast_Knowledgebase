# CACA and NCCN Table-Aware OCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the CACA and NCCN table chunks from Tencent accurate table OCR, create verified vector snapshots, and approve the new versions as active.

**Architecture:** A reusable table core validates Tencent cells and emits table parent/row chunks. A separate Tencent client performs TC3-signed OCR calls, while a PDF orchestrator discovers candidate table boxes with PyMuPDF, renders complete pages, groups Tencent tables by geometric overlap, and replaces only baseline table records. Existing lifecycle services ingest, verify, and activate the resulting immutable versions.

**Tech Stack:** Python 3.12, PyMuPDF 1.28.2, Python standard-library HTTPS and cryptography primitives, Tencent Cloud OCR API 2018-11-19, pytest 8.4, LlamaIndex 0.14.23, local BGE-M3.

## Global Constraints

- Preserve both original PDFs and baseline JSONL files byte-for-byte.
- Store every new writable artifact below `D:\coding\knowledgebase`; install PyMuPDF only into `D:\coding\knowledgebase\.venv` with the pip cache below `data\runtime_cache`.
- Never print, persist, commit, or place Tencent credentials in command arguments.
- Use only Tencent table detections whose `Type` is `1` or `2`.
- Preserve merged cells and reject ambiguous, overlapping, or unmatched table geometry.
- Preserve every non-table baseline record's `text` and source order exactly.
- Emit one table parent record and one header-qualified record for every physical table row.
- Do not emit HTML table artifacts.
- Import through `GuidelineService` / `GuidelineLifecycle`; do not edit SQLite or LlamaIndex snapshots directly.
- Approve both verified versions immediately; do not leave them as review drafts.
- Do not upload or package BGE-M3 as part of this task.

---

### Task 1: Preserve Table Metadata Through Ingestion

**Files:**
- Modify: `D:\coding\knowledgebase\app\ingestion.py`
- Modify: `D:\coding\knowledgebase\tests\test_ingestion.py`

**Interfaces:**
- Consumes: JSONL records with table provenance fields.
- Produces: `make_node_metadata(...)` output containing table IDs, row indices, table dimensions, source page image, and OCR confidence.

- [ ] **Step 1: Write the failing ingestion test**

Add a JSONL fixture containing these fields and assert they survive `read_jsonl` and `make_node_metadata`:

```python
TABLE_METADATA = {
    "table_id": "caca_2026_p026_t01",
    "table_index": 1,
    "table_title": "SLNB指征",
    "table_row_index": 2,
    "parent_table_chunk_id": "caca_2026_p026_t01",
    "table_row_count": 11,
    "table_column_count": 3,
    "table_cell_count": 21,
    "source_image": "source-page-026.png",
    "ocr_confidence_min": 91.5,
    "ocr_confidence_mean": 98.2,
}
assert all(metadata[key] == value for key, value in TABLE_METADATA.items())
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_ingestion.py -q
```

Expected: FAIL because the table fields are currently omitted from `locator_json`.

- [ ] **Step 3: Add the table locator fields**

Extend `OPTIONAL_CHUNK_FIELDS` with exactly:

```python
"table_id", "table_index", "table_title", "table_row_index",
"parent_table_chunk_id", "table_row_count", "table_column_count",
"table_cell_count", "source_image", "ocr_confidence_min",
"ocr_confidence_mean",
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2. Expected: all `tests/test_ingestion.py` tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/ingestion.py tests/test_ingestion.py
git commit -m "feat: preserve table OCR metadata during ingestion"
```

---

### Task 2: Extract a Document-Neutral Tencent Table Core

**Files:**
- Create: `D:\coding\knowledgebase\scripts\table_ocr_core.py`
- Create: `D:\coding\knowledgebase\tests\test_table_ocr_core.py`

**Interfaces:**
- Consumes: Tencent `TableDetections`, baseline table context, and page table boxes.
- Produces: `valid_tables`, `build_table_grid`, `linearize_table_rows`, `group_tables_by_boxes`, and `make_table_records`.

- [ ] **Step 1: Write failing cell-grid and row-linearization tests**

Use a fixture with a two-row merged cell and assert:

```python
grid = build_table_grid(TABLE_WITH_SPAN)
assert (grid.rows, grid.columns) == (3, 2)
rows = linearize_table_rows(TABLE_WITH_SPAN, table_title="治疗方案")
assert rows[1] == "表格：治疗方案\n第2行：分层=A&B；方案=方案甲"
assert rows[2] == "表格：治疗方案\n第3行：分层=A&B；方案=方案乙"
```

Also assert that invalid spans and overlapping cells raise `ValueError`.

- [ ] **Step 2: Run the core test and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_table_ocr_core.py -q
```

Expected: import failure because `scripts.table_ocr_core` does not exist.

- [ ] **Step 3: Implement the grid and linearization functions**

Create immutable `TableCell` and `TableGrid` dataclasses. Parse `RowTl`, `ColTl`, `RowBr`, `ColBr`, `Text`, and `Confidence`; fill every covered occupancy coordinate; reject invalid or overlapping spans; and derive stable column labels from the first physical row.

- [ ] **Step 4: Run the core test and verify GREEN**

Run the command from Step 2. Expected: cell-grid tests pass.

- [ ] **Step 5: Write failing geometry-grouping tests**

Define two baseline `TableBox` values and three Tencent detections. Assert two detections group into the first box, one into the second, order follows `(top, left)`, and a non-overlapping detection raises `ValueError`.

- [ ] **Step 6: Implement geometry and valid-table filtering**

Provide:

```python
def valid_tables(payload: Mapping[str, object]) -> tuple[Mapping[str, object], ...]: ...
def group_tables_by_boxes(
    boxes: Sequence[TableBox],
    tables: Sequence[Mapping[str, object]],
    *,
    page_number: int,
    minimum_overlap: float = 0.70,
) -> tuple[tuple[Mapping[str, object], ...], ...]: ...
```

Use intersection divided by the smaller rectangle area. Every box must receive at least one table and every valid table must map to exactly one highest-overlap box.

- [ ] **Step 7: Write failing parent/row record tests**

Assert stable IDs and required fields:

```python
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
```

- [ ] **Step 8: Implement record creation and run all core tests**

The parent `text` is the newline join of all linearized rows. Row records carry `parent_table_chunk_id`, one-based `table_row_index`, table dimensions, confidence summary, and source image. Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_table_ocr_core.py -q
```

Expected: all core tests pass.

- [ ] **Step 9: Commit**

```powershell
git add scripts/table_ocr_core.py tests/test_table_ocr_core.py
git commit -m "feat: add reusable Tencent table OCR core"
```

---

### Task 3: Implement the Tencent TC3 OCR Client

**Files:**
- Create: `D:\coding\knowledgebase\scripts\tencent_table_ocr.py`
- Create: `D:\coding\knowledgebase\tests\test_tencent_table_ocr.py`

**Interfaces:**
- Consumes: PNG bytes and credentials from process or Windows user environment.
- Produces: `TencentCredentials`, `build_tc3_headers`, and `TencentTableOcrClient.recognize_png`.

- [ ] **Step 1: Write failing credential-resolution tests**

Use injected environment mappings and a fake user-environment reader. Assert process values win, user values are the fallback, missing credentials raise `RuntimeError`, and `repr(credentials)` does not contain either secret.

- [ ] **Step 2: Run the client tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_tencent_table_ocr.py -q
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement secret-safe credential resolution**

Create a frozen dataclass with both fields declared `repr=False`. Read process variables first, then `HKEY_CURRENT_USER\Environment` through `winreg`. Error messages identify only the missing variable names.

- [ ] **Step 4: Write failing deterministic signing tests**

For timestamp `1786896000`, body `{"ImageBase64":"YWJj","UseNewModel":true}`, and fake credentials, assert:

```python
assert headers["Host"] == "ocr.tencentcloudapi.com"
assert headers["X-TC-Action"] == "RecognizeTableAccurateOCR"
assert headers["X-TC-Version"] == "2018-11-19"
assert headers["X-TC-Timestamp"] == "1786896000"
assert "Credential=AKIDEXAMPLE/2026-08-17/ocr/tc3_request" in headers["Authorization"]
assert "SecretKeyExample" not in repr(headers)
```

- [ ] **Step 5: Implement TC3-HMAC-SHA256 signing**

Use canonical headers `content-type;host`, service `ocr`, endpoint `https://ocr.tencentcloudapi.com`, and JSON encoded with `sort_keys=True`, compact separators, and UTF-8.

- [ ] **Step 6: Write failing HTTP and error-sanitization tests**

Inject a transport callable. Assert the client unwraps `Response`, preserves `RequestId`, sends `UseNewModel=true`, rejects Tencent `Response.Error`, retries only transient network/5xx failures, and never places credential values in exceptions.

- [ ] **Step 7: Implement the client and atomic raw-response writer**

Provide:

```python
def recognize_png(self, png_path: Path) -> dict[str, object]: ...
def write_response_atomic(path: Path, payload: Mapping[str, object]) -> None: ...
```

Use at most three attempts with delays of 1 and 2 seconds. Existing valid JSON responses are reused by the orchestrator and are never overwritten.

- [ ] **Step 8: Run tests and commit**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_tencent_table_ocr.py -q
git add scripts/tencent_table_ocr.py tests/test_tencent_table_ocr.py
git commit -m "feat: add secret-safe Tencent table OCR client"
```

Expected: all client tests pass.

---

### Task 4: Build the PDF Candidate and JSONL Rebuilder

**Files:**
- Create: `D:\coding\knowledgebase\scripts\rebuild_pdf_tables.py`
- Create: `D:\coding\knowledgebase\tests\test_pdf_table_rebuild.py`
- Modify: `D:\coding\knowledgebase\pyproject.toml`

**Interfaces:**
- Consumes: source PDF, baseline JSONL, document identity, output root, and Tencent raw JSON directory.
- Produces: candidate manifest, full-page PNGs, table-aware JSONL, and structural verification report.

- [ ] **Step 1: Add the optional OCR dependency**

Add:

```toml
ocr = ["pymupdf==1.28.2"]
```

Install it only into the D-drive virtual environment:

```powershell
& .\.venv\Scripts\python.exe -m pip install `
  --cache-dir D:\coding\knowledgebase\data\runtime_cache\pip_cache `
  "pymupdf==1.28.2"
```

Expected: `D:\coding\knowledgebase\.venv\Scripts\python.exe -c "import pymupdf; print(pymupdf.__version__)"` prints `1.28.2`.

- [ ] **Step 2: Write failing candidate discovery tests**

Build a temporary two-page PDF with PyMuPDF, one table per page, and a baseline JSONL containing corresponding table records. Assert `discover_candidates` returns zero-based page indices, one-based filenames, scaled boxes, and fails when baseline and fresh scan table counts differ.

- [ ] **Step 3: Run the rebuild tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_pdf_table_rebuild.py -q
```

Expected: import failure because `scripts.rebuild_pdf_tables` does not exist.

- [ ] **Step 4: Implement discovery and full-page rendering**

Provide:

```python
def discover_candidates(pdf_path: Path, baseline_records: Sequence[dict[str, object]]) -> CandidateManifest: ...
def render_candidate_pages(pdf_path: Path, manifest: CandidateManifest, output_dir: Path) -> None: ...
```

Use `page.find_tables().tables`, sort boxes by `(y0, x0)`, and render `page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)` to `source-page-NNN.png`.

- [ ] **Step 5: Write failing JSONL replacement tests**

Use baseline order `[text, table, text, table]` and matching Tencent fixtures. Assert:

- non-table records are exactly equal before and after;
- each table position expands to parent followed by row records;
- additional Tencent tables assigned to one baseline box remain adjacent;
- duplicate IDs or unmatched geometry fail;
- `read_jsonl` accepts the output.

- [ ] **Step 6: Implement replacement and validation**

Provide:

```python
def rebuild_jsonl(
    *, baseline_jsonl: Path, candidate_manifest: CandidateManifest,
    tencent_json_dir: Path, output_jsonl: Path,
) -> RebuildReport: ...
def verify_rebuild(
    baseline_records: Sequence[dict[str, object]],
    rebuilt_records: Sequence[dict[str, object]],
    report: RebuildReport,
) -> dict[str, object]: ...
```

Compare SHA-256 hashes of each retained non-table `text`, validate page ranges and required fields, count all non-empty Tencent cells, and write output atomically.

- [ ] **Step 7: Add the resumable CLI**

Support:

```text
python -m scripts.rebuild_pdf_tables prepare --pdf ... --baseline-jsonl ... --output-root ...
python -m scripts.rebuild_pdf_tables ocr --output-root ...
python -m scripts.rebuild_pdf_tables rebuild --baseline-jsonl ... --output-root ... --output-jsonl ...
python -m scripts.rebuild_pdf_tables all --pdf ... --baseline-jsonl ... --output-root ... --output-jsonl ...
```

`ocr` reads the candidate manifest, reuses valid raw JSON, writes progress after every page, and stops nonzero if any page fails.

- [ ] **Step 8: Run focused and regression tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest `
  tests\test_pdf_table_rebuild.py `
  tests\test_table_ocr_core.py `
  tests\test_tencent_table_ocr.py `
  tests\test_csco_table_reinsertion.py -q
```

Expected: all focused tests and existing CSCO table tests pass.

- [ ] **Step 9: Commit**

```powershell
git add pyproject.toml scripts/rebuild_pdf_tables.py tests/test_pdf_table_rebuild.py
git commit -m "feat: rebuild PDF table chunks from Tencent OCR"
```

---

### Task 5: Process the Real CACA and NCCN Sources

**Files:**
- Create: `D:\coding\knowledgebase\data\staging\caca_breast_2026_table_aware.jsonl`
- Create: `D:\coding\knowledgebase\data\staging\nccn_breast_v6_2026_table_aware.jsonl`
- Create: document-specific artifacts below `D:\coding\knowledgebase\data\staging\table_ocr`
- Create: verification reports below `D:\coding\knowledgebase\data\reports`

**Interfaces:**
- Consumes: production PDFs, baseline JSONL, Windows user Tencent credentials, and Tasks 2-4.
- Produces: verified real-source table-aware JSONL and auditable OCR responses.

- [ ] **Step 1: Verify credentials without displaying values**

```powershell
$id = [Environment]::GetEnvironmentVariable('TENCENTCLOUD_SECRET_ID', 'User')
$key = [Environment]::GetEnvironmentVariable('TENCENTCLOUD_SECRET_KEY', 'User')
if ([string]::IsNullOrWhiteSpace($id) -or [string]::IsNullOrWhiteSpace($key)) {
    throw 'Tencent Cloud user environment variables are not configured.'
}
```

- [ ] **Step 2: Run CACA end to end**

```powershell
& .\.venv\Scripts\python.exe -m scripts.rebuild_pdf_tables all `
  --pdf 'D:\document\HER2乳腺癌专病demo项目\c583d456-9316-4818-b575-b7619748cde3.pdf' `
  --baseline-jsonl 'D:\document\HER2乳腺癌专病demo项目\pipeline\标准文档分块解析\caca_2026.jsonl' `
  --output-root 'D:\coding\knowledgebase\data\staging\table_ocr\caca_2026' `
  --output-jsonl 'D:\coding\knowledgebase\data\staging\caca_breast_2026_table_aware.jsonl' `
  --report 'D:\coding\knowledgebase\data\reports\caca-table-ocr-r1.json'
```

Expected: all candidate pages succeed, no baseline non-table hash changes, and the report has `status="complete"`.

- [ ] **Step 3: Run NCCN end to end**

```powershell
& .\.venv\Scripts\python.exe -m scripts.rebuild_pdf_tables all `
  --pdf 'D:\document\HER2乳腺癌专病demo项目\（2026.V6）NCCN临床实践指南：乳腺癌.pdf' `
  --baseline-jsonl 'D:\document\HER2乳腺癌专病demo项目\pipeline\标准文档分块解析\nccn_v6_2026.jsonl' `
  --output-root 'D:\coding\knowledgebase\data\staging\table_ocr\nccn_v6_2026' `
  --output-jsonl 'D:\coding\knowledgebase\data\staging\nccn_breast_v6_2026_table_aware.jsonl' `
  --report 'D:\coding\knowledgebase\data\reports\nccn-table-ocr-r1.json'
```

Expected: all candidate pages succeed, no baseline non-table hash changes, and the report has `status="complete"`.

- [ ] **Step 4: Run production JSONL readers and real-source validation**

```powershell
& .\.venv\Scripts\python.exe -c "from pathlib import Path; from app.ingestion import read_jsonl; paths=[Path(r'data\staging\caca_breast_2026_table_aware.jsonl'),Path(r'data\staging\nccn_breast_v6_2026_table_aware.jsonl')]; print([(p.name,len(read_jsonl(p))) for p in paths])"
```

Expected: both files load without `JsonlIngestionError`; each has unique chunk IDs and more records than its baseline because of row chunks.

---

### Task 6: Import, Verify, and Activate New Versions

**Files:**
- Create: `D:\coding\knowledgebase\config\caca_2026_table_ocr_r1.json`
- Create: `D:\coding\knowledgebase\config\nccn_v6_2026_table_ocr_r1.json`
- Create: `D:\coding\knowledgebase\tests\test_table_ocr_real_sources.py`

**Interfaces:**
- Consumes: final table-aware JSONL and original PDFs.
- Produces: managed immutable sources, BGE-M3 vector snapshots, registry rows, and active version status.

- [ ] **Step 1: Add a separate real-source test for the generated files**

Create `test_table_ocr_real_sources.py` guarded by `KB_TABLE_OCR_REAL_SOURCE_TESTS=1`. Record the real SHA-256 and record counts from Task 5 for only the two generated files. Assert missing fields are empty, IDs are unique, all table parents have row children, and staging hashes match the two table-OCR reports. Leave the existing all-source contract test unchanged because its historical Gradishar fixture is outside this task's scope.

- [ ] **Step 2: Run the table-OCR real-source test and verify it passes**

```powershell
$env:KB_TABLE_OCR_REAL_SOURCE_TESTS = '1'
& .\.venv\Scripts\python.exe -m pytest tests\test_table_ocr_real_sources.py -q
```

Expected: all source contract checks pass.

- [ ] **Step 3: Create and validate the ingest configs**

Use version IDs:

```text
caca-breast-cancer-2026-table-ocr-r1
nccn-breast-cancer-6-2026-table-ocr-r1
```

Each config references the original PDF as `citation_source` and the corresponding staging JSONL as `chunk_input`. Provenance includes Tencent provider, action, `UseNewModel=true`, candidate page count, table parent count, row count, record count, and report SHA-256.

Validate without importing:

```powershell
& .\.venv\Scripts\python.exe -c "from pathlib import Path; from scripts.ingest_guideline import load_ingest_config; [load_ingest_config(Path(p)) for p in (r'config\caca_2026_table_ocr_r1.json',r'config\nccn_v6_2026_table_ocr_r1.json')]; print('configs-valid')"
```

Expected: `configs-valid`.

- [ ] **Step 4: Import both versions with pinned offline BGE-M3**

```powershell
$env:KB_EMBEDDING_PROVIDER = 'local'
$env:KB_MODEL_LOCAL_FILES_ONLY = 'true'
$env:KB_MODEL_DEVICE = 'cpu'
& .\.venv\Scripts\python.exe -m scripts.ingest_guideline --config config\caca_2026_table_ocr_r1.json
& .\.venv\Scripts\python.exe -m scripts.ingest_guideline --config config\nccn_v6_2026_table_ocr_r1.json
```

Expected: each command prints its new version ID and leaves a verified draft snapshot.

- [ ] **Step 5: Verify both snapshots independently**

```powershell
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot --version-id caca-breast-cancer-2026-table-ocr-r1
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot --version-id nccn-breast-cancer-6-2026-table-ocr-r1
```

Expected: both commands exit 0 with matching node counts and manifest hashes.

- [ ] **Step 6: Run explicit draft retrieval checks**

Instantiate `GuidelineService`, search each version explicitly with three table-specific queries and one prose query, and write evidence summaries without embedding credentials to `data/reports/table-ocr-retrieval-r1.json`. Require every query to return evidence from the requested version and at least the table queries to return `block_type` of `table` or `table_row`.

- [ ] **Step 7: Approve both versions immediately**

```powershell
& .\.venv\Scripts\python.exe -c "from app.service import GuidelineService; from app.settings import Settings; s=GuidelineService(Settings.from_env()); print(s.approve('caca-breast-cancer-2026-table-ocr-r1', reviewer='codex-user-approved').status.value); print(s.approve('nccn-breast-cancer-6-2026-table-ocr-r1', reviewer='codex-user-approved').status.value)"
```

Expected: prints `active` twice. Verify CACA r3 is `superseded`, both new versions are `active`, and no NCCN draft was accidentally promoted.

- [ ] **Step 8: Commit source code and configs**

```powershell
git add config/caca_2026_table_ocr_r1.json config/nccn_v6_2026_table_ocr_r1.json tests/test_table_ocr_real_sources.py
git commit -m "data: register CACA and NCCN table OCR versions"
```

---

### Task 7: Document the Workflow and Perform Final Verification

**Files:**
- Create: `D:\coding\knowledgebase\docs\operations\table-aware-ocr-workflow.md`
- Modify: `D:\coding\knowledgebase\docs\operations\initial-import-status.md`
- Modify: `D:\coding\knowledgebase\README.md`

**Interfaces:**
- Consumes: completed workflow, registry results, counts, hashes, and retrieval report.
- Produces: repeatable operator procedure and current knowledge-base inventory.

- [ ] **Step 1: Document the CSCO-derived workflow**

The runbook must cover candidate detection, full-page rendering, Tencent credential resolution, resumable OCR calls, raw response retention, merged-cell reconstruction, parent/row chunking, source-contract validation, lifecycle import, snapshot verification, activation, and audit queries. Include exact commands for CACA and NCCN and explicitly state that API credentials and BGE-M3 are never packaged.

- [ ] **Step 2: Update current version counts and status**

Update README and initial import status with the actual CACA/NCCN table-aware node counts, manifest hashes, active/superseded states, total registry counts, and representative retrieval results.

- [ ] **Step 3: Run full fresh verification**

```powershell
$env:KB_TABLE_OCR_REAL_SOURCE_TESTS = '1'
$env:KB_MODEL_LOCAL_FILES_ONLY = 'true'
& .\.venv\Scripts\python.exe -m pytest -q -W error
& .\.venv\Scripts\python.exe -m compileall -q app scripts
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot --version-id caca-breast-cancer-2026-table-ocr-r1
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot --version-id nccn-breast-cancer-6-2026-table-ocr-r1
```

Expected: tests pass with zero warnings, compilation and pip checks exit 0, and both snapshots verify.

- [ ] **Step 4: Inspect repository state and prevent secret/data leakage**

```powershell
git diff --check
git status --short
git diff -- . ':!data'
rg -n "TENCENTCLOUD_SECRET|SecretKey|AKID" . -g '!data/**' -g '!.git/**'
```

Expected: no credential values appear, generated `data` remains ignored, and only intended code/config/docs changes are tracked.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md docs/operations/table-aware-ocr-workflow.md docs/operations/initial-import-status.md
git commit -m "docs: record active CACA and NCCN table OCR indexes"
```

- [ ] **Step 6: Report the final active versions**

Provide the user with record counts by block type, candidate page counts, OCR table counts, snapshot manifest hashes, active/superseded states, verification commands, and paths to both final JSONL files and the workflow runbook.
