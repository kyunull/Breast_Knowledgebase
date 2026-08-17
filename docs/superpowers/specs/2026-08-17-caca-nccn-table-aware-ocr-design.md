# CACA and NCCN Table-Aware OCR Design

## Goal

Reprocess the tables in the 2026 CACA and NCCN Breast Cancer source PDFs with Tencent Cloud `RecognizeTableAccurateOCR`, preserve the existing non-table text, generate retrieval-oriented table-aware JSONL, build new immutable vector snapshots, and approve the verified versions as active.

## Scope

The change covers these sources:

- CACA: `D:\document\HER2乳腺癌专病demo项目\c583d456-9316-4818-b575-b7619748cde3.pdf`
- NCCN: `D:\document\HER2乳腺癌专病demo项目\（2026.V6）NCCN临床实践指南：乳腺癌.pdf`
- Existing baseline chunks: `caca_2026.jsonl` and `nccn_v6_2026.jsonl`

CSCO remains unchanged and acts as the reference implementation for Tencent cell parsing, merged-cell handling, table parent records, and header-qualified row records.

The implementation will not re-OCR non-table prose, install models or dependencies on `C:`, upload BGE-M3, mutate existing snapshots in place, or generate HTML table artifacts.

## Architecture

The workflow has four deterministic stages:

1. Detect candidate pages from the existing PyMuPDF table chunks and re-run PyMuPDF table discovery against the immutable PDF to obtain page and table bounding boxes.
2. Render each distinct candidate PDF page to a high-resolution PNG under `D:\coding\knowledgebase\data\staging\table_ocr` and submit it to Tencent Cloud `RecognizeTableAccurateOCR` with `UseNewModel=true`.
3. Match valid Tencent table detections (`Type` 1 or 2) to baseline table chunks using page order and geometric overlap. Replace each baseline table chunk with one table parent record followed by header-qualified row records while leaving every non-table record byte-for-byte equivalent in `text` and in the same source order.
4. Validate the JSONL, import it through `GuidelineService` / `GuidelineLifecycle`, verify the resulting LlamaIndex snapshot, run representative retrieval checks, and approve the new version as active.

## Components

### Candidate Page Discovery and Rendering

Candidate pages are the union of pages containing `block_type="table"` in the baseline JSONL and pages returned by a fresh PyMuPDF table scan. A mismatch fails closed and is reported before any knowledge-base import.

Pages use the PDF's zero-based page index internally and the one-based PDF page number in filenames and operator reports. PNG filenames are `source-page-NNN.png`. Rendering uses a fixed 2x matrix with no crop so Tencent coordinates share one stable page coordinate system.

### Tencent OCR Client

The client reads `TENCENTCLOUD_SECRET_ID` and `TENCENTCLOUD_SECRET_KEY` from the process or Windows user environment without logging either value. It calls the official Tencent OCR HTTPS endpoint using TC3-HMAC-SHA256 signing, so no new SDK installation is required. Raw successful responses are written atomically as `source-page-NNN.json`; retries skip valid existing responses and use bounded exponential backoff for transient Tencent errors.

Every raw response remains an immutable audit artifact. A summary records page counts, request IDs, success/failure status, model flag, and response hashes, but never credentials.

### Table Reconstruction

The CSCO cell-grid rules are generalized into a document-neutral module:

- Preserve `RowTl`, `ColTl`, `RowBr`, and `ColBr` merged-cell spans.
- Reject overlapping origins, invalid coordinates, empty table grids, and unmatched valid detections.
- Order tables top-to-bottom and left-to-right within each page.
- Carry merged cell values into every covered row during retrieval linearization.
- Use the closest existing table title, section path, and page code as table context.

Each source table produces:

- One `block_type="table"` parent chunk containing the title and a lossless row-oriented plain-text representation.
- One `block_type="table_row"` chunk for every physical row, including a dedicated header row record.
- Stable chunk IDs based on document, one-based PDF page, table ordinal, and row ordinal.

Row text includes the table title and column-qualified values. It does not contain HTML and does not split a physical row across chunks.

### JSONL Assembly

The assembler streams baseline records in source order. Non-table records retain their original `text`, page fields, section path, page code, and block type. At each baseline table position, it emits the matching Tencent-derived parent and row records. Unknown optional baseline metadata is preserved where applicable.

Required knowledge-base fields remain present on every record:

- `chunk_id`
- `doc_id`
- `doc_title`
- `section_path`
- `page_code`
- `page_start`
- `page_end`
- `block_type`
- `text`

The final outputs are:

- `data/staging/caca_breast_2026_table_aware.jsonl`
- `data/staging/nccn_breast_v6_2026_table_aware.jsonl`

The audit artifacts are stored under document-specific directories below `data/staging/table_ocr`.

## Versioning and Activation

The imports create immutable versions:

- `caca-breast-cancer-2026-table-ocr-r1`
- `nccn-breast-cancer-6-2026-table-ocr-r1`

Both versions are built as draft because the existing lifecycle requires verified draft snapshots before approval. After automated source, snapshot, and retrieval checks pass, the same workflow immediately approves each version as active. The user does not need to perform a separate draft review. Existing active versions are not overwritten; registry approval marks the prior active version superseded according to the current lifecycle.

## Validation and Failure Handling

The workflow fails before import when any of these conditions occur:

- Credentials are unavailable.
- A candidate page has no valid Tencent table response.
- A Tencent table cannot be matched exactly once to a baseline table position.
- Cell coordinates overlap inconsistently or a table loses non-empty Tencent cell text.
- A baseline non-table record changes text or relative order.
- Chunk IDs are duplicated, page ranges are invalid, or required fields are missing.
- JSONL hashes or record counts differ between staging and managed copies.
- Snapshot verification or representative retrieval fails.

If import fails after a draft row is created, the version remains a failed draft audit record and is never approved. No prior active version or snapshot is modified.

## Verification

Automated tests cover candidate-page collection, table geometry matching, merged-cell reconstruction, deterministic parent/row IDs, baseline prose preservation, fail-closed behavior, and production JSONL ingestion.

Real-source verification reports, per document:

- PDF page count and candidate table pages.
- Tencent response count, table count, non-empty cell count, and response hashes.
- Baseline versus rebuilt table counts.
- Final record counts by block type.
- Exact hashes for all retained non-table `text` values.
- Snapshot node count and manifest hash.
- Retrieval evidence for at least three table-specific clinical queries and one non-table query.

Approval occurs only after all checks complete successfully.
