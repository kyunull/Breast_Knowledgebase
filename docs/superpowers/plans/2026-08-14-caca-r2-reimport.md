# CACA R2 Reimport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the regenerated 324-record CACA JSONL as a new verified draft while preserving the current 270-node active version and its audit history.

**Architecture:** Use the existing immutable lifecycle with a new version ID and globally unique source IDs. The lifecycle copies source bytes into `data/managed_sources`, builds a version-scoped LlamaIndex snapshot, verifies it, and records a diff from the current active version without changing active search.

**Tech Stack:** Python 3.12, LlamaIndex, BAAI/bge-m3 pinned revision, SQLite, JSONL, PowerShell.

## Global Constraints

- Keep `caca-breast-cancer-2026` active and unchanged.
- Create `caca-breast-cancer-2026-r2` with version label `2026年版-r2` and initial status `draft`.
- Use actor `caca-r2-import` for all automated import and diff audit events.
- Use source IDs `caca-2026-r2-pdf` and `caca-2026-r2-jsonl`.
- Pin BGE-M3 to revision `5617a9f61b028005a4858fdac845db406aefb181` and set `KB_MODEL_LOCAL_FILES_ONLY=true`.
- Write all project data, caches, reports, and temporary files below `D:\coding\knowledgebase`.
- Do not approve, archive, supersede, delete, or overwrite any version in this plan.
- Do not change NCCN, Gradishar, or OncoToolkit data.

---

### Task 1: Validate And Configure The Regenerated CACA Source

**Files:**
- Create: `config/caca_2026_r2.json`
- Create at runtime: `data/reports/caca-r2-source-contract.json`

**Interfaces:**
- Consumes: regenerated `D:\document\HER2乳腺癌专病demo项目\pipeline\标准文档分块解析\caca_2026.jsonl` and existing CACA PDF.
- Produces: a validated ingest request for `scripts.ingest_guideline`.

- [ ] **Step 1: Validate the single-source contract**

Run `build_source_contract_report` for CACA only. Require exactly 324 records, unique chunk IDs, no missing required fields, and SHA-256 `9eb1bf535e665ede5641e6a72899eece2555164fca64f69ae36cf287cfff543d`.

- [ ] **Step 2: Create the r2 ingest config**

Create `config/caca_2026_r2.json` without a `guideline` object. Use the existing CACA guideline ID, language, authority level, PDF path, and regenerated JSONL path; use the r2 version and source IDs from Global Constraints.

- [ ] **Step 3: Validate the config without importing**

Run `scripts.ingest_guideline.load_ingest_config` and assert the actor, version ID, source roles, language, and authority level.

### Task 2: Import, Index, Diff, And Review The CACA Draft

**Files:**
- Create at runtime: `data/managed_sources/caca-breast-cancer-2026-r2/`
- Create at runtime: `data/llama_indices/caca-breast-cancer/caca-breast-cancer-2026-r2/`
- Modify at runtime: `data/registry/knowledge.sqlite3`

**Interfaces:**
- Consumes: the validated r2 config and pinned local BGE-M3 cache.
- Produces: a 324-node draft snapshot, an automatic diff against `caca-breast-cancer-2026`, and append-only audit events.

- [ ] **Step 1: Run the import exactly once**

Run `python -m scripts.ingest_guideline --config D:\coding\knowledgebase\config\caca_2026_r2.json` with all runtime and model cache variables below the project root.

- [ ] **Step 2: Reopen and verify the snapshot**

Run `python -m scripts.verify_snapshot --version-id caca-breast-cancer-2026-r2`. Require exit 0 and a manifest hash.

- [ ] **Step 3: Verify registry and diff invariants**

Require old CACA status `active`, new status `draft`, new raw chunk and node counts `324`, source hashes matching the original inputs, and diff rows for the exact old/new version pair. Report counts by `added`, `removed`, `modified`, and `unchanged`.

- [ ] **Step 4: Review bilingual HER2 evidence without approving**

Load the new snapshot directly through `GuidelineService.index_store`, run Chinese and English HER2 queries against that exact draft index, and require non-empty CACA evidence with `raw_chunk_id`, `primary_guideline`, and PDF page locator metadata.

- [ ] **Step 5: Confirm default search remains unchanged**

Use the service search boundary to require default resolution to `caca-breast-cancer-2026` and explicit draft search to raise `draft version is not searchable`.

### Task 3: Document And Verify The New Draft State

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/initial-import-status.md`

**Interfaces:**
- Consumes: verified registry counts, manifest hash, diff summary, and query evidence from Task 2.
- Produces: accurate operator-facing status while leaving approval to a human reviewer.

- [ ] **Step 1: Update status documentation with measured values**

Add the new CACA r2 draft, its 324 nodes, manifest hash, and diff summary. Keep the original CACA version marked active and state that approval has not occurred.

- [ ] **Step 2: Run scoped and full automated verification**

Run the complete default suite, the CACA-only source contract, `compileall`, and `pip check`. Record that the all-source optional contract remains blocked by the independently changed NCCN source until NCCN is reimported.

- [ ] **Step 3: Inspect Git and runtime state**

Require that no `data/` path is tracked or staged, and report all source/config/document changes separately from ignored runtime data.

### Task 4: Preserve Mid-Import Drift And Import The Stable CACA Candidate

During Task 2, the upstream CACA JSONL changed after the immutable r2 managed copy had been created. Preserve r2 as a draft audit record. After the upstream file remains stable across repeated hash samples, create `caca-breast-cancer-2026-r3` with actor `caca-r3-import`, source IDs `caca-2026-r3-pdf` and `caca-2026-r3-jsonl`, and locked JSONL SHA-256 `983e26188f574a8200f367347175e2bfb79c4d430ffd0b26fc2a5187fc62d1f5`.

- [ ] **Step 1: Import r3 from the stable source**

Validate 324 records and the locked hash, then run the standard import exactly once with pinned local BGE-M3.

- [ ] **Step 2: Verify r3 and compare it with active and r2**

Require a verified 324-node r3 snapshot, automatic diff records against the old active version, and an explicit structured comparison against r2 showing the four upstream text changes.

- [ ] **Step 3: Treat r3 as the review candidate**

Run Chinese and English draft snapshot retrieval against r3. Keep r2 and r3 draft, keep the original version active, and document r3 as the only candidate intended for human approval.
