# Bilingual Terminology Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Rebuild a high-precision bilingual retrieval glossary from the CACA, CSCO, and NCCN chunks, with deterministic rejection of OCR-derived units, identifiers, and sentence fragments.

**Architecture:** Keep glossary generation in `app/terminology.py`. Add strict candidate validators and a deterministic audit payload while preserving the existing `build_bilingual_dictionary()` and `load_or_build_dictionary()` interfaces. Seed only reviewed oncology concepts, write the runtime glossary plus a sibling audit report, and leave source chunks and vector indexes unchanged.

**Tech Stack:** Python 3.12, pytest, JSON, existing `RawChunkRecord` and glossary cache.

## Global Constraints

- Preserve the original Chinese query and append only verified aliases.
- Reject units, doses, percentages, identifiers, URLs, comparison/statistical fragments, and sentence fragments from automatic aliases.
- Treat uncertain mappings as rejected rather than inferred.
- Keep all writable artifacts below `D:\coding\knowledgebase`.
- Do not download or re-embed any model for this glossary-only change.

### Task 1: Lock down rejection and seed behavior with failing tests

**Files:**
- Modify: `tests/test_terminology.py`

**Interfaces:**
- Consumes: `build_bilingual_dictionary`, `expand_query`, and `RawChunkRecord`.
- Produces: regression coverage for strict extraction and verified seed expansion.

- [ ] **Step 1: Add failing tests for invalid candidates.**

```python
def test_build_dictionary_rejects_measurement_unit_parenthetical_alias():
    terms = build_bilingual_dictionary(
        [_raw_chunk("LDL-C理想水平：4.9 mmol/L（高危）")],
        seed_terms={},
    )

    assert "mmol/L" not in terms
    assert "高危" not in terms


def test_build_dictionary_rejects_sentence_fragment_parenthetical_alias():
    terms = build_bilingual_dictionary(
        [_raw_chunk("digital mammography（如果后续诊断性数字乳腺X线摄影）")],
        seed_terms={},
    )

    assert "digital mammography" not in terms


def test_build_dictionary_rejects_identifier_and_threshold_aliases():
    terms = build_bilingual_dictionary(
        [_raw_chunk("ORCID: 0000-0001-7241-0760（张瑾）")],
        seed_terms={},
    )

    assert "ORCID: 0000-0001-7241-0760" not in terms
```

- [ ] **Step 2: Add failing tests for reviewed clinical seeds and query expansion.**

```python
def test_default_seeds_cover_lymph_node_metastasis_and_high_risk():
    terms = build_bilingual_dictionary([], seed_terms=DEFAULT_SEED_TERMS)

    assert set(terms["淋巴转移"]) == {"lymph node metastasis", "nodal metastasis"}
    assert set(terms["高危"]) == {"high risk", "high-risk"}


def test_query_expansion_never_adds_measurement_unit_from_source_noise():
    terms = build_bilingual_dictionary(
        [_raw_chunk("4.9 mmol/L（高危）")],
        seed_terms=DEFAULT_SEED_TERMS,
    )

    expanded = expand_query("淋巴转移 高危", terms)

    assert "lymph node metastasis" in expanded
    assert "high risk" in expanded
    assert "mmol/L" not in expanded
```

- [ ] **Step 3: Run only the new tests and confirm they fail for the expected reason.**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terminology.py -q`

Expected: FAIL because the current permissive parser accepts `mmol/L`, sentence fragments, and does not seed the two reviewed Chinese concepts.

### Task 2: Implement strict extraction and deterministic audit output

**Files:**
- Modify: `app/terminology.py`
- Modify: `tests/test_terminology.py`

**Interfaces:**
- Consumes: the existing parenthesized bilingual extraction and cache fingerprint.
- Produces: the same dictionary-returning public functions plus `data/retrieval/bilingual_terms.audit.json` on rebuild.

- [ ] **Step 1: Add reviewed seeds.**

Extend `DEFAULT_SEED_TERMS` with:

```python
"淋巴转移": ("lymph node metastasis", "nodal metastasis"),
"高危": ("high risk", "high-risk"),
```

- [ ] **Step 2: Add validators before alias insertion.**

Add explicit pattern groups and reason-returning validation helpers:

```python
_MEASUREMENT_UNIT = re.compile(
    r"(?i)^(?:mmol|mol|mg|g|kg|ml|l|cm|mm|hz)(?:/[a-z]+)?(?:[²³23])?$"
)
_IDENTIFIER = re.compile(r"(?i)(?:^|\b)(?:orcid|nct\d+|www\.|https?://)")
_COMPARISON = re.compile(r"[<>=≤≥%]|\d+(?:\.\d+)?\s*(?:mmol|mg|kg|cm|mm|ml|g/l)", re.I)
_CLAUSE_PREFIXES = (
    "如果", "依据", "同时", "包括", "其中", "对于", "通过", "建议", "推荐",
)
_GENERIC_CHINESE_LABELS = frozenset({"个月", "分期", "推荐", "可选", "阳性", "阴性"})


def _english_rejection_reason(value: str) -> str | None:
    if _IDENTIFIER.search(value):
        return "identifier"
    if _MEASUREMENT_UNIT.fullmatch(value) or _COMPARISON.search(value):
        return "measurement_or_threshold"
    if len(re.findall(r"[A-Za-z]", value)) < 3:
        return "invalid_term_shape"
    if len(value) > 80 or any("\u3400" <= char <= "\u9fff" for char in value):
        return "invalid_term_shape"
    return None


def _chinese_rejection_reason(value: str) -> str | None:
    if value in _GENERIC_CHINESE_LABELS or value.startswith(_CLAUSE_PREFIXES):
        return "sentence_fragment"
    if not 2 <= len(value) <= 24 or re.search(r"[，。；：,.;:（）()]", value):
        return "invalid_term_shape"
    if not re.search(r"[\u3400-\u9fff]", value):
        return "invalid_term_shape"
    return None
```

`_is_english_alias()` and `_is_chinese_term()` return true only when the corresponding rejection helper returns `None`. Reviewed short abbreviations remain available through seeds.

- [ ] **Step 3: Make candidate processing auditable.**

Introduce `_build_bilingual_dictionary_with_audit(...) -> tuple[dict[str, tuple[str, ...]], dict[str, object]]`. It accumulates rejected records with exactly these keys:

```python
{
    "chunk_id": chunk.chunk_id,
    "source": cleaned_source,
    "target": cleaned_target,
    "reason": rejection_reason,
}
```

Sort records by `(chunk_id, source.casefold(), target.casefold(), reason)`, deduplicate identical records, and keep `build_bilingual_dictionary()` returning only `terms` for compatibility.

- [ ] **Step 4: Write the audit report during a rebuild.**

Have `load_or_build_dictionary()` write `bilingual_terms.audit.json` next to `bilingual_terms.json` with schema version, source versions, accepted pair count, rejected candidate count, rejected candidates, and reviewed seeds. Use sorted keys and stable ordering; do not include UUIDs or timestamps.

- [ ] **Step 5: Run the focused tests and the full terminology suite.**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terminology.py -q`

Expected: all terminology tests pass, including rejection of `mmol/L（高危）` and acceptance of the reviewed seeds.

Run: `\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_service.py -q`

Expected: no retrieval or service regressions.

### Task 3: Rebuild and audit the production glossary

**Files:**
- Create or replace: `data/retrieval/bilingual_terms.json`
- Create or replace: `data/retrieval/bilingual_terms.audit.json`
- Create: `scripts/audit_bilingual_terms.py`
- Test: `tests/test_terminology.py`

**Interfaces:**
- Consumes: searchable raw chunks registered for CACA, CSCO, and NCCN.
- Produces: deterministic runtime glossary, audit report, and a standalone quality gate.

- [ ] **Step 1: Add a standalone audit script.**

Create `scripts/audit_bilingual_terms.py` with a `main() -> int` entry point. It loads `data/retrieval/bilingual_terms.json`, walks every directed pair, and appends errors for:

```python
if target not in terms or source not in terms[target]:
    errors.append(f"non-reciprocal: {source!r} -> {target!r}")
if forbidden_pattern.search(source) or forbidden_pattern.search(target):
    errors.append(f"forbidden mapping: {source!r} -> {target!r}")
if not source.strip() or not target.strip() or source.casefold() == target.casefold():
    errors.append(f"invalid mapping: {source!r} -> {target!r}")
```

Print `term_count`, `directed_pair_count`, `unique_pair_count`, and every error. Return `1` when errors exist and `0` otherwise.

- [ ] **Step 2: Rebuild through the existing service/registry source path.**

Run: `\.venv\Scripts\python.exe -c "from pathlib import Path; from app.registry import Registry; from app.settings import Settings; from app.terminology import load_or_build_dictionary, DEFAULT_SEED_TERMS; s=Settings.from_env(Path('.').resolve()); r=Registry(s.registry_db_path); r.initialize(); v=[x for x in r.list_searchable_versions() if x.guideline_id in {'caca-breast-cancer','csco-breast-cancer','nccn-breast-cancer'}]; c=[z for x in v for z in r.list_raw_chunks_for_version(x.id)]; load_or_build_dictionary(s.data_dir/'retrieval'/'bilingual_terms.json', c, [x.id for x in v], seed_terms=DEFAULT_SEED_TERMS); print('rebuilt')"`

- [ ] **Step 3: Run the standalone quality gate.**

Run: `\.venv\Scripts\python.exe scripts/audit_bilingual_terms.py`

Expected: exit code 0, no forbidden mapping, reciprocal checks pass, and the audit report is present.

- [ ] **Step 4: Verify representative expansions and source-noise exclusion.**

Run a UTF-8 Python check for `淋巴转移 高危`, `复发转移 疗法`, `ADC`, and `trastuzumab deruxtecan`. Assert the first query contains `lymph node metastasis` and `high risk`, and none contains `mmol/L`, ORCID, NCT identifiers, or sentence fragments.

- [ ] **Step 5: Run the full test suite and inspect the final diff.**

Run: `\.venv\Scripts\python.exe -m pytest -q`

Expected: exit code 0. Then run `git diff --check`, inspect the glossary/audit counts, and confirm no vector index or model cache files changed.

### Task 4: Operational verification

**Files:**
- Modify: `README.md` only if the audit artifact or rebuild command needs documenting.

**Interfaces:**
- Consumes: the rebuilt glossary and current API process.
- Produces: verified runtime query behavior after a service restart.

- [ ] **Step 1: Restart the API on port 8001 without changing model or index files.**

Run in PowerShell:

```powershell
$connection = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($connection) { Stop-Process -Id $connection.OwningProcess -Force }
Start-Process -FilePath "C:\Users\PC\AppData\Local\Programs\Python\Python312\python.exe" -WorkingDirectory "D:\coding\knowledgebase" -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8001" -WindowStyle Hidden
Start-Sleep -Seconds 5
```

- [ ] **Step 2: POST `淋巴转移 高危` to `/search` and inspect evidence.**

Run:

```powershell
$body = @{query="淋巴转移 高危"; guideline_ids=@(); version_ids=@(); language=$null; top_k=5; use_bm25=$true} | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://127.0.0.1:8001/search" -Method Post -ContentType "application/json" -Body $body
$response | ConvertTo-Json -Depth 10
```

- [ ] **Step 3: Confirm the query expansion no longer introduces `mmol/L` and that NCCN cover content is not returned by the restarted process.**

Check:

```powershell
$response.evidence.text -notmatch "NCCN recognizes the importance of clinical trials"
$env:PYTHONUTF8="1"
.\.venv\Scripts\python.exe -c "import json; from app.terminology import expand_query; d=json.load(open('data/retrieval/bilingual_terms.json',encoding='utf-8'))['terms']; q=expand_query('淋巴转移 高危',d); print(q); assert 'mmol/L' not in q"
```

Expected: PowerShell prints `True`; the expanded query contains verified metastasis/high-risk aliases and the Python assertion exits successfully.
