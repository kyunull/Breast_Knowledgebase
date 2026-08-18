# 多指南双语多样性检索实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重建现有向量快照的情况下，为 CSCO、CACA、NCCN 增加本地双语查询扩展、中文 BM25、正分过滤、封面排除和跨指南最低覆盖。

**Architecture:** 新增纯 Python 术语模块，从已注册 raw chunk 生成带源版本指纹的本地词典；检索层按现有节点 metadata 计算可索引节点 ID，向量检索使用 `node_ids` 过滤，BM25 使用 `bm25s` 的自定义 token 列表按请求构建。各版本先独立融合，再按指南覆盖约束做全局截取，原始 JSONL、SQLite 和向量快照不修改。

**Tech Stack:** Python 3.12, FastAPI, LlamaIndex 0.14.23, `bm25s` 0.3.10, pytest 8.4.2, SQLite。

## Global Constraints

- 只使用本地已导入的 CSCO、CACA、NCCN 内容生成词典，不调用外部翻译 API。
- 所有词典、报告和运行缓存写入 `D:\coding\knowledgebase\data`；不写入 C 盘。
- 原始 JSONL、源 PDF、SQLite 记录和现有向量快照保持不变。
- API `POST /search` 请求和 `SearchResponse` 字段保持不变。
- draft 版本继续禁止默认和显式检索；active/superseded 版本的过滤语义保持不变。
- 生产代码遵循测试驱动：每个行为先写一个会失败的测试，再实现最小行为并运行回归测试。

---

### Task 1: 本地双语术语词典和查询扩展

**Files:**
- Create: `app/terminology.py`
- Test: `tests/test_terminology.py`

**Interfaces:**
- `tokenize_query(text: str) -> tuple[str, ...]`
- `expand_query(query: str, terms: Mapping[str, Sequence[str]]) -> str`
- `build_bilingual_dictionary(chunks: Iterable[RawChunkRecord], seed_terms: Mapping[str, Sequence[str]] | None = None) -> dict[str, tuple[str, ...]]`
- `load_or_build_dictionary(path: Path, chunks: Iterable[RawChunkRecord], source_version_ids: Sequence[str], seed_terms: Mapping[str, Sequence[str]] | None = None) -> dict[str, tuple[str, ...]]`

- [x] **Step 1: Write failing tokenizer and expansion tests**

```python
def test_tokenize_query_emits_chinese_ngrams_and_preserves_english_terms():
    tokens = tokenize_query("复发转移 therapy T-DXd 2.5mg")
    assert "复发" in tokens and "发转" in tokens and "转移" in tokens
    assert "therapy" in tokens and "t-dxd" in tokens and "2.5mg" in tokens

def test_expand_query_longest_match_handles_multiple_separated_keywords():
    terms = {"复发转移": ("recurrent metastatic breast cancer",), "疗法": ("therapy", "treatment")}
    expanded = expand_query("复发转移 疗法", terms)
    assert expanded.startswith("复发转移 疗法")
    assert "recurrent metastatic breast cancer" in expanded
    assert "therapy" in expanded and "treatment" in expanded

def test_build_dictionary_extracts_parenthesized_bilingual_terms_and_reverse_aliases():
    chunks = [_raw_chunk("表观扩散系数（apparent diffusion coefficient，ADC）和乳腺癌治疗")]
    terms = build_bilingual_dictionary(chunks, seed_terms={})
    assert "apparent diffusion coefficient" in terms["表观扩散系数"]
    assert "表观扩散系数" in terms["ADC"]

def test_load_or_build_dictionary_reuses_matching_source_fingerprint(tmp_path):
    path = tmp_path / "bilingual_terms.json"
    chunks = [_raw_chunk("乳腺癌（breast cancer）")]
    first = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    second = load_or_build_dictionary(path, chunks, ["csco-r1"], seed_terms={})
    assert first == second
    assert path.exists()
```

- [x] **Step 2: Run focused tests and verify the expected RED failures**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terminology.py -q`

Expected: FAIL because `app.terminology` does not exist.

- [x] **Step 3: Implement deterministic tokenization, extraction, and cache**

Implement `tokenize_query` with regex tokens for ASCII words/numbers/hyphenated terms and Chinese 2/3-grams. Implement longest-first alias matching while retaining the original query. Extract only short parenthesized English aliases next to Chinese terms, add reverse aliases, merge seed terms, sort keys and values, and write canonical JSON atomically with `schema_version`, sorted `source_version_ids`, source fingerprint, and `terms`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terminology.py -q`

Expected: all terminology tests PASS.

- [x] **Step 5: Commit the terminology unit**

```powershell
git add app/terminology.py tests/test_terminology.py
git commit -m "feat: add local bilingual terminology expansion"
```

### Task 2: Chinese BM25 and indexability filtering

**Files:**
- Modify: `app/retrieval.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**
- `bm25_tokenizer(text: str) -> list[str]`
- `filter_positive_bm25(items: Sequence[NodeWithScore]) -> list[NodeWithScore]`
- `is_indexable_node(node: BaseNode) -> bool`
- `retrieve_bm25(nodes: Sequence[BaseNode], query: str, top_k: int) -> list[NodeWithScore]`

- [x] **Step 1: Write failing BM25 and cover-filter tests**

```python
def test_bm25_tokenizer_supports_chinese_ngrams_and_drug_tokens():
    tokens = retrieval_module.bm25_tokenizer("复发转移 T-DXd 2.5mg")
    assert {"复发", "发转", "转移", "t-dxd", "2.5mg"}.issubset(tokens)

def test_filter_positive_bm25_drops_zero_and_nonfinite_scores():
    nodes = [TextNode(id_="zero", text="zero"), TextNode(id_="hit", text="hit")]
    items = [NodeWithScore(nodes[0], score=0.0), NodeWithScore(nodes[1], score=2.0)]
    assert [item.node.node_id for item in filter_positive_bm25(items)] == ["hit"]

def test_cover_and_empty_nodes_are_not_indexable():
    cover = TextNode(id_="cover", text="NCCN Clinical Practice Guidelines", metadata={"page_start": 0, "section_path": "NCCN", "block_type": "text"})
    body = TextNode(id_="body", text="Recurrent metastatic disease treatment", metadata={"page_start": 10, "section_path": "BINV-P", "block_type": "algorithm"})
    empty = TextNode(id_="empty", text=" ", metadata={"block_type": "paragraph"})
    assert not is_indexable_node(cover)
    assert is_indexable_node(body)
    assert not is_indexable_node(empty)
```

- [x] **Step 2: Run the focused tests and verify RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -k "tokenizer or positive_bm25 or indexable" -q`

Expected: FAIL because the new helpers do not exist or cover metadata is not filtered.

- [x] **Step 3: Implement helpers and request-time BM25**

Use `bm25s.BM25` directly because the pinned LlamaIndex `BM25Retriever.from_defaults(tokenizer=...)` accepts but ignores its deprecated tokenizer argument. Index lists returned by `bm25_tokenizer`, retrieve with the same string tokens, map indices back to nodes, then filter scores with `math.isfinite(score) and score > 0`. Use explicit `indexable=false` metadata when present; otherwise exclude blank text and obvious cover/CIP/committee/TOC/legal metadata while retaining tables, table rows, algorithms, clinical summaries, headings, and notes.

- [x] **Step 4: Update vector/BM25 retrieval to use the helpers**

Load docstore nodes, compute `indexable_nodes`, pass their IDs through `index.as_retriever(node_ids=..., similarity_top_k=...)`, and call `retrieve_bm25` only on those nodes. Use the expanded query from Task 1. Keep the existing vector-only fallback when `BM25Retriever` is unavailable.

- [x] **Step 5: Run retrieval regression tests and verify GREEN**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -q`

Expected: all existing retrieval tests plus the new helper tests PASS, and zero-score candidates never reach RRF.

- [x] **Step 6: Commit the BM25/filtering unit**

```powershell
git add app/retrieval.py tests/test_retrieval.py
git commit -m "fix: filter noisy nodes and support Chinese BM25"
```

### Task 3: Multi-guide coverage and service glossary wiring

**Files:**
- Modify: `app/retrieval.py`
- Modify: `app/service.py`
- Test: `tests/test_retrieval.py`
- Test: `tests/test_api.py`

**Interfaces:**
- `ensure_guideline_coverage(items: Sequence[NodeWithScore], resolved_guideline_ids: Sequence[str], top_k: int) -> list[NodeWithScore]`
- `EvidenceRetriever(..., glossary_path: Path | None = None)`

- [x] **Step 1: Write failing coverage and bilingual integration tests**

```python
def test_coverage_reserves_one_result_per_guideline_when_top_k_allows_it():
    a = NodeWithScore(TextNode(id_="a", text="a", metadata={"guideline_id": "caca"}), score=0.2)
    b = NodeWithScore(TextNode(id_="b", text="b", metadata={"guideline_id": "csco"}), score=0.1)
    c = NodeWithScore(TextNode(id_="c", text="c", metadata={"guideline_id": "nccn"}), score=0.05)
    ranked = ensure_guideline_coverage([a, b, c], ("caca", "csco", "nccn"), 3)
    assert {item.node.metadata["guideline_id"] for item in ranked} == {"caca", "csco", "nccn"}

def test_coverage_does_not_force_guidelines_when_top_k_is_smaller():
    a = NodeWithScore(TextNode(id_="a", text="a", metadata={"guideline_id": "caca"}), score=0.2)
    b = NodeWithScore(TextNode(id_="b", text="b", metadata={"guideline_id": "csco"}), score=0.1)
    assert len(ensure_guideline_coverage([a, b], ("caca", "csco", "nccn"), 2)) == 2

def test_multi_keyword_search_preserves_query_and_expands_local_aliases():
    _, _, retriever = _system()
    response = retriever.search(SearchRequest(query="复发转移 疗法", top_k=2, use_bm25=True))
    assert response.evidence
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -k "coverage or multi_keyword" -q`

Expected: FAIL because coverage is not applied and glossary expansion is not wired.

- [x] **Step 3: Implement deterministic coverage and glossary lifecycle**

After per-version RRF, sort globally, reserve the highest-ranked candidate for each unique resolved guideline when `top_k >= guideline_count`, then fill remaining slots from the global ranking. In `GuidelineService.retriever`, pass `settings.data_dir / "retrieval" / "bilingual_terms.json"`; build the dictionary from registered searchable CSCO/CACA/NCCN raw chunks and the fixed seed terms, reusing the source-version fingerprint on subsequent searches. A missing or malformed glossary falls back to seed terms/original query.

- [x] **Step 4: Run the full retrieval and API tests**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py tests/test_api.py -q`

Expected: all tests PASS and the public API response shape remains unchanged.

- [x] **Step 5: Commit coverage and service wiring**

```powershell
git add app/retrieval.py app/service.py tests/test_retrieval.py tests/test_api.py
git commit -m "feat: diversify search across guideline sources"
```

### Task 4: Real-data validation and documentation

**Files:**
- Create: `scripts/verify_multilingual_retrieval.py`
- Create: `data/reports/retrieval-multilingual-r1.json`
- Modify: `README.md`
- Modify: `docs/operations/local-runbook.md`
- Test: `tests/test_retrieval_real_sources.py`

**Interfaces:**
- Script loads `Settings.from_env`, runs fixed Chinese/English/multi-keyword searches, and writes a JSON report without credentials or model weights.

- [x] **Step 1: Write failing real-source contract test**

```python
def test_real_source_report_records_indexable_filter_and_guideline_coverage():
    report = PROJECT_ROOT / "data" / "reports" / "retrieval-multilingual-r1.json"
    assert report.is_file()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["queries"]
    assert payload["source_versions"]
    assert payload["cover_nodes_excluded"] >= 1
```

- [x] **Step 2: Run the contract test and verify RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_retrieval_real_sources.py -q`

Expected: FAIL because the report and script do not exist.

- [x] **Step 3: Implement the validation script**

Run queries `复发转移`, `复发转移 疗法`, `trastuzumab deruxtecan`, and `recurrent metastatic disease` with BM25 enabled across active CSCO/CACA/NCCN versions. Record resolved versions, returned guideline IDs, node IDs, locators, query modes, glossary source versions, and counts of excluded cover/empty nodes. Use only existing local indices and write the report atomically below `data/reports`.

- [x] **Step 4: Run the real-source validation and inspect results**

Run: `\.venv\Scripts\python.exe scripts/verify_multilingual_retrieval.py`

Expected: report is generated; no result text is empty; no excluded cover node appears; for `top_k=3`, each available guideline contributes at least one result; source locators remain present.

- [x] **Step 5: Update runbook and README**

Document the automatic dictionary path, query expansion behavior, BM25 positive-score rule, cover filtering, and the fact that changing only retrieval filters does not require re-vectorization.

- [x] **Step 6: Run the full test suite and commit**

Run: `\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests PASS.

```powershell
git add scripts/verify_multilingual_retrieval.py data/reports/retrieval-multilingual-r1.json README.md docs/operations/local-runbook.md tests/test_retrieval_real_sources.py
git commit -m "test: validate multilingual diverse retrieval"
```

## Plan Self-Review

- Spec coverage: glossary extraction/cache (Task 1), Chinese BM25 and positive-score filtering (Task 2), cover exclusion without vector rebuild (Task 2), multilingual expansion and guideline coverage (Task 3), and real three-guide acceptance (Task 4) are all assigned.
- Placeholder scan: no TBD/TODO or unspecified implementation steps are used; each task names files, interfaces, commands, and expected outcomes.
- Type consistency: `expand_query` returns the string consumed by `EvidenceRetriever`; `is_indexable_node` feeds both vector `node_ids` and `retrieve_bm25`; `ensure_guideline_coverage` consumes the final `NodeWithScore` sequence and resolved guideline IDs.
- Data safety: the report and glossary are generated below `data`; `evidence_cards/` and existing snapshots are outside the modified file list and remain untouched.
