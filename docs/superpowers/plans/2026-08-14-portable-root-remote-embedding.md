# Portable Project Root And Remote Embedding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the fixed `D:\coding\knowledgebase` assumption, migrate runtime paths safely when a project moves, and add an explicit OpenAI-compatible remote BGE-M3 embedding mode without weakening local/offline operation.

**Architecture:** Discover the repository from the code/script location. Keep all writable runtime paths below that root, persist new runtime paths relative to it, and transactionally rebase legacy absolute paths. Add a `RemoteEmbedding` LlamaIndex adapter using `urllib.request`, selected only by explicit environment configuration; local Hugging Face BGE-M3 remains the default.

**Tech Stack:** Python 3.12, FastAPI, LlamaIndex Core 0.14.23, SQLite, PowerShell, `urllib.request`, pytest.

## Global Constraints

- The project may be located under any existing absolute path and on any Windows drive.
- All writable database, index, managed-source, model-cache, report, package-cache, and temporary paths must remain below the current project root.
- PDF, HTML, and JSONL inputs may be on any drive but must be existing absolute read-only paths.
- Local BGE-M3 remains the default provider with revision `5617a9f61b028005a4858fdac845db406aefb181`.
- Remote embeddings are opt-in through `KB_EMBEDDING_PROVIDER=remote` and `POST /embeddings`.
- `KB_EMBEDDING_API_KEY` must never be persisted in SQLite, manifests, audit payloads, exception messages, or logs.
- No LangChain, answer generation, public data release, draft approval, or unrelated source reimport is included.
- Existing CACA active, r2 draft, and r3 draft lifecycle states remain unchanged.

---

### Task 1: Dynamic Root Discovery

**Files:** Create `app/project_paths.py`; modify `app/settings.py`, `app/main.py`; test `tests/test_project_paths.py`, `tests/test_settings.py`.

**Interfaces:** Add `discover_project_root(anchor: Path | str | None = None) -> Path` and `ProjectRootDiscoveryError`. Change `Settings.from_env(project_root: Path | None = None)` so an omitted root is discovered automatically.

- [ ] Write a failing test that discovers a temporary repository marker (`pyproject.toml` plus `app/`) from a nested path and rejects an anchor outside a repository.
- [ ] Run `& .\.venv\Scripts\python.exe -m pytest tests\test_project_paths.py -q`; expect import failure because the helper does not exist.
- [ ] Implement upward marker search from the anchor or helper module location; do not use a drive letter or current working directory.
- [ ] Make `app.main` call `GuidelineService(Settings.from_env())`; retain explicit roots for tests and embedded callers.
- [ ] Run `pytest tests\test_project_paths.py tests\test_settings.py tests\test_api.py -q`; expect all focused tests to pass.
- [ ] Commit with `git add app tests; git commit -m "feat: discover project root dynamically"`.

### Task 2: Remove Fixed-Drive Restrictions

**Files:** Modify `app/service.py`, `app/lifecycle.py`, `app/source_contract.py`, `scripts/ingest_guideline.py`, `scripts/verify_snapshot.py`, `scripts/bootstrap_runtime.ps1`; update `tests/test_api.py`, `tests/test_lifecycle.py`, `tests/test_real_source_contract.py`, `tests/test_bootstrap_runtime.py`.

**Interfaces:** Sources remain absolute and existing but may be on any drive. Report output remains inside the discovered project root. Scripts use discovery when no root is explicitly provided.

- [ ] Write failing tests that accept a source file outside the project root, reject a relative source, and accept a temporary project on a non-D drive.
- [ ] Run `pytest tests\test_api.py tests\test_lifecycle.py tests\test_real_source_contract.py tests\test_bootstrap_runtime.py -q`; expect failures from current D-drive checks.
- [ ] Remove module-level fixed roots and all `drive.upper() != "D:"` checks; retain absolute-file and writable-path containment checks.
- [ ] Change bootstrap default to `Resolve-Path (Join-Path $PSScriptRoot '..')`; a supplied `-ProjectRoot` must match that script-owned repository before any directory is created.
- [ ] Run the affected tests and `compileall -q app scripts`; expect pass.
- [ ] Commit with `git add app scripts tests; git commit -m "feat: allow portable source and runtime paths"`.

### Task 3: Relative Runtime Paths And Legacy Migration

**Files:** Modify `app/registry.py`, `app/service.py`, `app/lifecycle.py`, `app/retrieval.py`, `app/ingestion.py`, `app/settings.py`; create `tests/test_portability.py`; update registry/lifecycle/retrieval tests.

**Interfaces:** Add `Settings.resolve_project_path(value: str | Path) -> Path` and `Registry.rebase_runtime_paths(*, project_root: Path, managed_sources_dir: Path, index_root: Path, actor: str) -> int`.

- [ ] Write failing tests with a temporary project containing target managed files and snapshots, a registry containing legacy absolute paths, and a missing-target case. Assert relative paths, one `project_paths_rebased` event, idempotence, and full rollback on missing targets.
- [ ] Run `pytest tests\test_portability.py -q`; expect failure because migration and resolution do not exist.
- [ ] Implement `resolve_project_path`: resolve relative values under the root, accept absolute values only when contained, and raise `PathOutsideProjectError` otherwise.
- [ ] Implement one `BEGIN IMMEDIATE` migration transaction. Derive snapshot targets from `index_root/guideline_id/version_id` and managed targets from `managed_sources_dir/version_id/basename(old_path)`; validate every target before updating to project-relative POSIX strings; write one count-only audit event.
- [ ] Store new managed and snapshot paths relatively; resolve them before JSONL reads, snapshot construction, approval, and retrieval. Preserve `original_path`.
- [ ] Run `pytest tests\test_portability.py tests\test_registry.py tests\test_lifecycle.py tests\test_retrieval.py -q`; expect pass.
- [ ] Commit with `git add app tests; git commit -m "feat: migrate runtime paths for portable projects"`.

### Task 4: Remote Embedding Adapter

**Files:** Create `app/embeddings.py`, `tests/test_embeddings.py`; modify `app/settings.py`, `app/service.py`, `tests/test_settings.py`.

**Interfaces:** Add `RemoteEmbedding(BaseEmbedding)` with `base_url`, `api_key`, `model_name`, `dimension`, `embed_batch_size`, `timeout_seconds`, and `max_retries`. Add settings for `KB_EMBEDDING_PROVIDER`, `KB_EMBEDDING_BASE_URL`, `KB_EMBEDDING_API_KEY`, `KB_EMBEDDING_MODEL`, `KB_EMBEDDING_DIMENSION` (default `1024`), timeout, and retries.

- [ ] Write loopback `ThreadingHTTPServer` tests for batch input order, response-index sorting, missing key, HTTPS/loopback validation, 401, malformed JSON, count mismatch, non-numeric vectors, retryable 429, and API-key redaction from payloads/errors.
- [ ] Run `pytest tests\test_embeddings.py tests\test_settings.py -q`; expect import failure.
- [ ] Implement `POST <base_url>/embeddings` with JSON `{ "input": [...], "model": "..." }`, Bearer authentication, bounded timeout, and retries only for 408/429/5xx. Parse and validate indexed numeric vectors; never expose the key.
- [ ] Select the adapter only when provider is exactly `remote`; require a non-empty key/model and HTTPS except loopback HTTP. Unknown providers fail without local fallback.
- [ ] Run `pytest tests\test_embeddings.py tests\test_settings.py tests\test_api.py -q`; expect all mock tests and local-mode tests to pass.
- [ ] Commit with `git add app tests; git commit -m "feat: support remote embedding APIs"`.

### Task 5: Manifest Compatibility

**Files:** Modify `app/index_store.py`, `app/service.py`, `app/settings.py`; update `tests/test_index_store.py`, `tests/test_embeddings.py`.

**Interfaces:** New manifests contain safe `model.provider`, `model.model_name`, `model.dimension`, and `model.normalize` metadata. Legacy manifests without these fields are treated as the pinned local BGE-M3 profile.

- [ ] Write failing tests that assert new metadata, reject dimension/provider mismatches with `SnapshotIntegrityError`, accept a legacy local manifest, and ensure API keys never occur in manifest bytes.
- [ ] Run `pytest tests\test_index_store.py -q`; expect the new assertions to fail against the old manifest shape.
- [ ] Add redacted metadata normalization and compatibility validation before LlamaIndex loads. Use the configured local/remote dimension (remote default `1024`) before loading, then reject any service response whose vector dimension differs.
- [ ] Run fixture index build/load tests using deterministic local and mock-remote embeddings; verify the evidence response shape is unchanged.
- [ ] Commit with `git add app tests; git commit -m "feat: validate embedding compatibility in snapshots"`.

### Task 6: Portable And Remote-Mode Documentation

**Files:** Modify `README.md`, `docs/operations/local-runbook.md`, `docs/operations/initial-import-status.md`, and the portable-root spec.

- [ ] Replace active README/runbook commands and claims requiring `D:\coding\knowledgebase` with `$ProjectRoot = (Get-Location).Path` or `$PSScriptRoot`; historical design notes may retain the old path as history.
- [ ] Document local mode as default and remote setup only through environment variables, including `KB_EMBEDDING_API_KEY` from a prompt; state that keys never belong in JSON or Git.
- [ ] Document automatic legacy-path migration, project-local write boundaries, missing-file failure, remote network requirements, and vector compatibility.
- [ ] Run `rg -n -F 'D:\coding\knowledgebase' README.md docs\operations` and `rg -n 'KB_EMBEDDING_PROVIDER|KB_EMBEDDING_BASE_URL|KB_EMBEDDING_API_KEY|KB_MODEL_LOCAL_FILES_ONLY' README.md docs\operations`; expect no active fixed-path instruction and both modes documented.
- [ ] Commit with `git add README.md docs; git commit -m "docs: document portable and remote embedding modes"`.

### Task 7: Full Verification And Push

**Files:** No new source files; verify the committed implementation and ignored runtime data.

- [ ] Run `$env:KB_REAL_SOURCE_TESTS='0'; & .\.venv\Scripts\python.exe -m pytest -q -W error`; expect zero failures.
- [ ] With the pinned local model variables, run `python -m scripts.verify_snapshot --version-id caca-breast-cancer-2026-r3` and both HER2 queries; confirm active/draft resolution is unchanged.
- [ ] Run `compileall -q app scripts`, `pip check`, and `git diff --check`.
- [ ] Assert no tracked path starts with `data/`, `.venv/`, `.sdd/`, `.release/`, or `dist/`; scan repository text for literal bearer tokens or API keys.
- [ ] Run `git status --short --branch`, `git push origin main`, `git ls-remote origin refs/heads/main`, and `git status --short --branch`; expect remote and local commits to match and the worktree to be clean.
