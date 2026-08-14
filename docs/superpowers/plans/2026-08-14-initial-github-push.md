# Initial GitHub Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the first usable internal-test code revision to the private GitHub repository with a complete team README and without committing runtime data or caches.

**Architecture:** Keep source, tests, configuration, and operational documentation in Git. Keep the real corpus, SQLite registry, and LlamaIndex snapshots out of Git history for delivery as a separate private Release asset; download the pinned BGE-M3 model on each online test device.

**Tech Stack:** Python 3.12, PowerShell, FastAPI, LlamaIndex, Hugging Face BGE-M3, Git, private GitHub repository.

## Global Constraints

- Work directly on `main` because the user explicitly requested an initial commit and push.
- The runtime project path remains exactly `D:\coding\knowledgebase`.
- The remote is `https://github.com/kyunull/Breast_Knowledgebase.git`.
- Never track `data/`, `.venv/`, `.sdd/`, runtime caches, release staging directories, or generated archives.
- Do not include credentials, GitHub tokens, private URLs with embedded secrets, or user-specific home-directory paths.
- Pin BGE-M3 to revision `5617a9f61b028005a4858fdac845db406aefb181`.
- Bind the test API only to `127.0.0.1`.
- This plan does not create the real-data GitHub Release; that is a separate plan after the initial code push.

---

### Task 1: Complete README And Publish The Initial Code Revision

**Files:**
- Create: `README.md`
- Modify: `.gitignore`
- Include unchanged: `app/`, `scripts/`, `config/`, `tests/`, `docs/`, `pyproject.toml`
- Exclude: `data/`, `.venv/`, `.sdd/`, `dist/`, `.release/`

**Interfaces:**
- Consumes: the validated runtime commands and import status in `docs/operations/`.
- Produces: a cloneable private repository whose README fully describes data restoration, online model setup, validation, startup, search, governance, and security limits.

- [ ] **Step 1: Write the root README**

Create `README.md` with these exact sections and values:

```markdown
# Breast Knowledgebase

Internal test version of a local, versioned bilingual breast-cancer guideline evidence API built with LlamaIndex. It returns source evidence and citations; it does not generate clinical conclusions.

## Current Data Status

| Source | Version | Status | Nodes | Authority |
| CACA | 2026 | active | 270 | primary_guideline |
| NCCN | 6.2026 | draft | 786 | primary_guideline |
| Gradishar | 4.2026 | draft | 9 | primary_publication |
| OncoToolkit | 2026 | draft | 31 | secondary_summary |

## Requirements

- Windows x64
- Python 3.12
- Clone path: `D:\coding\knowledgebase`
- Private Release data archive from this repository
- Network access for dependency and first model download

## Install, Restore Data, Configure Model, Verify, Run, Search, Governance, Troubleshooting, Security
```

Under those sections include complete PowerShell commands for cloning to the required path, creating `.venv`, relocating all caches below `data/`, installing `.[dev]`, downloading and verifying pinned BGE-M3 through `scripts.verify_snapshot`, switching to `KB_MODEL_LOCAL_FILES_ONLY=true`, running both test modes, starting Uvicorn, issuing Chinese and English `/search` requests, listing `/guidelines` and `/audit`, and stopping the service. State that draft search returns 422 and that `/ingest` and `/approve` are unauthenticated local-test endpoints.

- [ ] **Step 2: Harden repository ignores**

Append these entries to `.gitignore` while preserving existing entries:

```gitignore
.sdd/
.release/
dist/
```

- [ ] **Step 3: Verify README accuracy and repository boundaries**

Run:

```powershell
rg -n "D:\\coding\\knowledgebase|5617a9f61b028005a4858fdac845db406aefb181|KB_MODEL_LOCAL_FILES_ONLY|127.0.0.1|KB_REAL_SOURCE_TESTS" README.md
git check-ignore -v data\registry\knowledge.sqlite3 .venv .sdd
git status --short
git diff --check
```

Expected: README contains every required runtime constant; all three private/runtime paths are ignored; `git status` contains only intended source and documentation files; `git diff --check` exits 0.

- [ ] **Step 4: Run fresh verification before publication**

Run with cache and temp paths below `D:\coding\knowledgebase\data`:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -W error
$env:KB_REAL_SOURCE_TESTS = '1'
& .\.venv\Scripts\python.exe -m pytest tests\test_real_source_contract.py -q -W error
& .\.venv\Scripts\python.exe -m compileall -q app scripts
& .\.venv\Scripts\python.exe -m pip check
```

Expected: `79 passed, 1 skipped`; `2 passed`; compileall exits 0; pip reports no broken requirements.

- [ ] **Step 5: Stage only intended repository content**

Run:

```powershell
git add README.md .gitignore pyproject.toml app scripts config tests docs
git status --short
git ls-files
```

Expected: no path begins with `data/`, `.venv/`, `.sdd/`, `.release/`, or `dist/`.

- [ ] **Step 6: Commit and push `main`**

Run:

```powershell
git commit -m "docs: publish internal test setup"
git push -u origin main
git status --short --branch
git log --oneline --decorate -2
```

Expected: push exits 0; `main` tracks `origin/main`; the work tree is clean; the two commits are the release design commit and the internal-test setup commit.
