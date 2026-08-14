# LlamaIndex 版本化双语指南知识库实施计划

> For agentic workers: use subagent-driven-development task-by-task. Each checkbox is a tracked implementation step.

**目标：** 在 D:\coding\knowledgebase 建立本地的版本化中英文指南知识库；检索只返回可核验的原文证据和出处。

**架构：** LlamaIndex 是唯一的索引和检索框架。每个指南版本各有一个独立、不可变、可重载的 VectorStoreIndex 快照。SQLite 只承担版本注册、源文件/原始 chunk、节点清单、版本差异和追加式审计；FastAPI 在检索前解析允许的版本范围。

**技术栈：** Python 3.12、FastAPI、SQLite、LlamaIndex Core、LlamaIndex HuggingFace embedding integration、可选 BM25 integration、BAAI/bge-m3 本地 CPU、pytest/httpx。

## 全局约束

- 所有可写项目路径必须是 D:\coding\knowledgebase 的子路径：虚拟环境、数据库、索引、受管源文件、模型、临时与下载缓存均不得写入 C 盘。
- 不使用 LangChain、LangGraph、Ollama、外部向量数据库或远程 LLM。
- 原始 PDF、HTML、JSONL 只读；导入时创建受管副本和 SHA-256，绝不改写原文。
- 当前输入共有 1,096 个 JSONL 记录：CACA 270、Gradishar 9、NCCN V6 786、OncoToolkit 31。共同字段为 chunk_id、doc_id、doc_title、section_path、page_code、page_start、page_end、block_type、text。
- 节点 ID 为 guideline_id:version_id:chunk_id:fragment_ordinal；原始 chunk ID 和 JSONL 行号必须保留。
- PDF 的 page_start/page_end 是从 0 开始的页序号；展示为“PDF 页序号 N+1”，不得伪装成印刷页码。HTML 无页码时显示 parent_h1 和 section_path。
- 生命周期只允许 draft 到 active 到 superseded 或 archived。draft 不参加默认检索，审批原子替换活动版本，审计事件不可更新或删除。
- OncoToolkit 必须显示 secondary_summary 来源级别。
- 常规测试不下载模型和不读取真实指南；真实 BGE-M3 检验是显式烟测。
- 下载发生哈希不一致时立即停止，不得绕过完整性校验。
- 当前目录不是 Git 仓库；不创建 worktree 或提交。每个任务的命令、结论和阻塞因素记录在 .sdd\progress.md。

## 目标目录

    app/
      api.py              # FastAPI 路由
      citation.py         # 引用组装
      constants.py        # 枚举
      contracts.py        # 请求与领域数据结构
      diffing.py          # 版本差异
      index_store.py      # LlamaIndex 建立、持久化、加载和校验
      ingestion.py        # JSONL 与受管源文件导入
      lifecycle.py        # 导入和审批工作流
      main.py             # ASGI 入口
      registry.py         # SQLite 注册与审计
      retrieval.py        # 检索和 RRF 融合
      service.py          # API/CLI 的用例门面
      settings.py         # D 盘运行边界
    scripts/
      bootstrap_runtime.ps1
      ingest_guideline.py
      verify_snapshot.py
      verify_wheelhouse.py
    tests/
      fixtures/
      test_*.py
    config/known_sources.example.json
    docs/operations/local-runbook.md
    data/                # 运行期生成并忽略
      registry/knowledge.sqlite3
      managed_sources/
      llama_indices/guideline_id/version_id/
      model_cache/
      runtime_cache/
      vendor_wheels/

---

## Task 0：D 盘边界与可验证依赖预检

**文件：**

- 修改：pyproject.toml、.gitignore、app/settings.py、.sdd/progress.md
- 新建：scripts/bootstrap_runtime.ps1、scripts/verify_wheelhouse.py、tests/test_settings.py

**产生的接口：**

    class PathOutsideProjectError(ValueError): ...

    @dataclass(frozen=True, slots=True)
    class Settings:
        project_root: Path
        data_dir: Path
        registry_db_path: Path
        managed_sources_dir: Path
        index_root: Path
        model_cache_dir: Path
        runtime_cache_dir: Path
        model_name: str
        model_revision: str | None
        model_device: str
        model_max_seq_length: int
        embedding_batch_size: int
        bm25_enabled: bool

        @classmethod
        def from_env(cls, project_root: Path) -> Settings: ...
        def ensure_directories(self) -> None: ...
        def runtime_environment(self) -> dict[str, str]: ...

- [ ] 1. 先以 D 盘 TEMP、TMP、PIP_CACHE_DIR 复现并记录 pytest 安装的当前结果；不修改安装器配置。
- [ ] 2. 先写 tests/test_settings.py。测试 C 盘的 KB_DATA_DIR 必须抛出 PathOutsideProjectError；默认 registry、source、index、model、runtime 路径都必须是项目根目录子路径；HF_HOME 也必须位于项目根目录。
- [ ] 3. 运行 python -m pytest tests/test_settings.py -q，确认因接口缺失而 RED；若 pytest 仍不可用，记录阻塞并先执行完整性预检。
- [ ] 4. 最小实现 Settings：解析环境变量后用 Path.resolve 与 Path.is_relative_to 强制 D:\coding\knowledgebase；runtime_environment 固定设置 TEMP、TMP、PIP_CACHE_DIR、HF_HOME、HUGGINGFACE_HUB_CACHE、TRANSFORMERS_CACHE、SENTENCE_TRANSFORMERS_HOME、TORCH_HOME。默认 CPU、batch=4、max_length=512。
- [ ] 5. 建立 wheelhouse 流程：bootstrap_runtime.ps1 只在 data\runtime_cache 和 data\vendor_wheels 操作；verify_wheelhouse.py 对每个 wheel 计算 SHA-256，并与官方 PyPI JSON 的同名同版本文件哈希比对；不匹配立即非零退出。
- [ ] 6. 将 pyproject 由旧 sentence-transformers/自定义向量堆栈改为精确版本的 llama-index-core、llama-index-embeddings-huggingface、llama-index-retrievers-bm25、FastAPI、Uvicorn、pytest、httpx；不加入 LangChain。
- [ ] 7. 运行 focused pytest、pip check 和 wheel 验证。把命令和完整性结论写入 .sdd/progress.md。

**验收命令：**

    & .\.venv\Scripts\python.exe -m pytest tests\test_settings.py -q
    & .\.venv\Scripts\python.exe -m pip check

预期：Settings 测试通过，pip check 无 broken requirements。若可信依赖安装仍被哈希问题阻断，任务标记 blocked，绝不关闭校验。

## Task 1：SQLite 版本注册与审计基础

**文件：**

- 修改：app/constants.py、.sdd/progress.md
- 新建：app/contracts.py、app/registry.py、tests/test_registry.py
- 停止运行时使用：app/database.py

**接口：**

    Registry(path).initialize()
    Registry.create_guideline(input) -> GuidelineRecord
    Registry.create_draft_version(input) -> VersionRecord
    Registry.add_source_file(record) -> None
    Registry.add_raw_chunks(records) -> None
    Registry.add_node_manifest(records) -> None
    Registry.approve_version(version_id, actor, snapshot_manifest_sha256) -> VersionRecord
    Registry.list_searchable_versions(...) -> list[VersionRecord]
    Registry.list_audit(...) -> list[AuditEvent]

- [ ] 1. 先写测试：创建两份同指南 draft，分别批准；第二份批准后第一份必须 superseded、第二份必须 active。直接 UPDATE/DELETE audit_event 必须触发 SQLite DatabaseError。
- [ ] 2. 执行 tests/test_registry.py，确认接口缺失导致 RED。
- [ ] 3. 实现 registry schema：guideline、document_version、source_file、raw_chunk、node_manifest、version_diff、audit_event。document_version 有活动版本的 partial unique index；node_manifest 不存向量；audit_event 建 update/delete 拦截 trigger。
- [ ] 4. approve_version 用 BEGIN IMMEDIATE：验证目标是带已校验清单哈希的 draft，先 supersede 旧 active，再 active 目标，并写入审批审计事件后提交。
- [ ] 5. 执行 focused pytest，记录 Green 证据。

**验收：** draft/active/superseded 状态机、单一 active、审计不可变、源文件/原始 chunk/节点清单可保存。

## Task 2：无损 JSONL 导入与引用元数据

**文件：**

- 新建：app/ingestion.py、app/citation.py、tests/fixtures/caca.jsonl、tests/fixtures/gradishar.jsonl、tests/fixtures/nccn.jsonl、tests/fixtures/oncotoolkit.jsonl、tests/test_ingestion.py、tests/test_citation.py
- 修改：.sdd/progress.md

**接口：**

    read_jsonl(path: Path) -> list[RawChunkRecord]
    copy_and_register_sources(...) -> list[SourceFileRecord]
    make_node_metadata(...) -> dict[str, object]
    format_citation(metadata: Mapping[str, object]) -> Citation

- [ ] 1. 先写最小 fixture：四种来源各一条；CACA/NCCN multipart、NCCN algorithm/table、HTML null 页码与 parent_h1、11 字符文本至少各一例。
- [ ] 2. 写 RED 测试：JSONL 文本逐字符不变、source_ordinal 从 1 开始、重复 chunk_id 和缺字段报出行号；PDF page_start=0 显示“PDF 页序号 1”；HTML 页码为空时显示 parent_h1 > section_path。
- [ ] 3. 运行 tests/test_ingestion.py 和 tests/test_citation.py，确认 RED。
- [ ] 4. 实现逐行 UTF-8 JSONL 解析、受管文件字节复制和 SHA-256；metadata 显式保留共同字段、可选 part/part_count/parent_h1/heading_level、源文件哈希、版本、语言和 authority_level。不得清洗 raw text。
- [ ] 5. 运行 focused pytest，记录 Green 证据。

**验收：** 每个结果可回到受管源文件、原始 chunk、JSONL 行号、正确页码/章节和来源级别。

## Task 3：LlamaIndex 不可变快照存储

**文件：**

- 新建：app/index_store.py、tests/test_index_store.py
- 修改：app/ingestion.py、.sdd/progress.md

**接口：**

    ProvenanceNodeBuilder.build(raw_chunks, context) -> list[TextNode]
    IndexSnapshotStore.build(version, nodes) -> SnapshotInfo
    IndexSnapshotStore.load(snapshot) -> VectorStoreIndex
    IndexSnapshotStore.verify(snapshot) -> None

- [ ] 1. 先写不下载模型的测试，使用 llama_index.core.embeddings.MockEmbedding(embed_dim=8) 或确定性 BaseEmbedding：建立快照、校验、重载；验证 node ID 为 nccn:nccn-v6:nccn_v6_2026_0000:0，metadata 中 raw_chunk_id 和 source_ordinal 保留；清单哈希可复算。
- [ ] 2. 运行 tests/test_index_store.py，确认因模块缺失 RED。
- [ ] 3. 实现 provenance-aware 节点构造：原始 chunk 可派生多个嵌入节点，但每个节点保留 raw_chunk_id、原文字符区间与 fragment_ordinal，且 registry 的 raw chunk 永不改写。
- [ ] 4. 以注入 embedding 建立 VectorStoreIndex。先写入版本目录下的 staging，StorageContext 持久化后生成 manifest.json（version ID、index ID、节点数、排序 node ID、组件哈希、模型标识）；verify 后原子重命名到 data\llama_indices\guideline_id\version_id。已发布目录绝不原地改写。
- [ ] 5. 运行 focused pytest，验证持久化、重载、元数据和损坏检测均 Green。

**验收：** 每个版本都有可复现、可独立加载、可校验的 LlamaIndex 快照，且没有自定义 embedding blob 或 SQLite FTS 参与索引。

## Task 4：Draft 导入、审批保护与版本差异

**文件：**

- 新建：app/lifecycle.py、app/diffing.py、tests/test_lifecycle.py、tests/test_diffing.py
- 修改：.sdd/progress.md

**接口：**

    GuidelineLifecycle.ingest(request, actor) -> VersionRecord
    GuidelineLifecycle.approve(version_id, actor) -> VersionRecord
    GuidelineLifecycle.diff(prior_version_id, current_version_id) -> list[VersionDiffRecord]

- [ ] 1. 写 RED workflow 测试：ingest 后版本为 draft 且默认 searchable 为空；approve 后成为 active。再导入并批准新版本时，旧版本为 superseded。
- [ ] 2. 写版本差异 RED 测试：根据原始 chunk ID 和规范化文本 SHA-256 产生 added、removed、modified、unchanged 四类记录。
- [ ] 3. 运行 tests/test_lifecycle.py tests/test_diffing.py，确认 RED。
- [ ] 4. 实现 ingest：创建 draft、复制并登记源文件、保存 raw chunk/node manifest、建立并 verify 快照、与最近同指南 active/superseded 比较、写成功/失败审计。任一步失败均不可成为 active。
- [ ] 5. 实现 approve：再次 verify 清单与索引后才调用 registry 的原子审批。diff 只允许同 guideline 的版本对，保存旧/新 chunk ID 和 hash。
- [ ] 6. 运行 focused pytest，记录 Green。

**验收：** draft 不能默认检索；审批失败不损害旧 active；历史版本始终可查和可比。

## Task 5：确定性中英文证据检索

**文件：**

- 新建：app/retrieval.py、tests/test_retrieval.py
- 修改：app/citation.py、.sdd/progress.md

**接口：**

    EvidenceRetriever.search(request: SearchRequest) -> SearchResponse
    rrf_merge(vector, bm25, k: int = 60) -> list[NodeWithScore]

SearchRequest 包含 query、可选 guideline_ids、可选 version_ids、可选 language、top_k、use_bm25。SearchResponse 仅包含 evidence、resolved_version_ids、retrieval_modes，禁止 answer/生成字段。

- [ ] 1. 写 RED 测试：默认检索排除 draft、包含完整 citation；指定 superseded ID 可检索；RRF 对同 node ID 去重；BM25 不可用时 retrieval_modes 为 vector。
- [ ] 2. 运行 tests/test_retrieval.py，确认 RED。
- [ ] 3. 在 registry 先解析 allowed versions，之后才 load 对应 VectorStoreIndex 并调用 as_retriever。固定 BM25 integration 可导入且 use_bm25=true 时，对同版本节点检索并以 k=60 的确定性 RRF 合并；无法导入则显式 vector fallback，不能阻塞核心检索。
- [ ] 4. 返回原语言 text、score、language、authority_level、version 和 metadata 引用。无法检索的指定历史版本必须报告验证错误，绝不能偷偷降级为 active。
- [ ] 5. 运行 focused pytest，记录 Green。

**验收：** 检索不会调用 LLM 或 response synthesizer；每一个结果都有原文和可见出处。

## Task 6：本地 FastAPI、CLI 与运行手册

**文件：**

- 新建：app/api.py、app/main.py、app/service.py、scripts/ingest_guideline.py、scripts/verify_snapshot.py、config/known_sources.example.json、docs/operations/local-runbook.md、tests/test_api.py
- 修改：.sdd/progress.md

**接口：**

    create_app(service: GuidelineService) -> FastAPI

路由为 POST /ingest、POST /versions/{version_id}/approve、POST /search、GET /guidelines、GET /versions/{version_id}/diff、GET /audit。

- [ ] 1. 写 API RED 测试：/search 的 JSON 有 evidence/citation/raw_chunk_id 且没有 answer；/approve 缺 reviewer 返回 422；显式指定不存在版本返回验证错误。
- [ ] 2. 运行 tests/test_api.py，确认 RED。
- [ ] 3. 实现 Pydantic 请求校验和服务门面。/ingest 仅接收显式 D 盘源文件与 JSONL 路径、版本与来源信息；/approve 要求非空 reviewer；/search 直接序列化 EvidenceRetriever 的证据响应。
- [ ] 4. 编写 CLI：ingest_guideline.py 读目录配置并打印 draft ID；verify_snapshot.py 重新打开并校验 manifest。目录示例只能含 schema 和占位符，不能含 C 盘路径或密钥。
- [ ] 5. 编写运行手册：D 盘环境、可信 bootstrap、导入、审批、检索、历史检索、diff、audit、显式真实模型烟测命令和停止条件。
- [ ] 6. 运行 tests/test_api.py、compileall app scripts，记录 Green。

**验收：** 本地操作员不需要 UI 即可完成完整生命周期，且 API 永远暴露证据而非临床生成答案。

## Task 7：全量验证、真实数据契约与交接记录

**文件：**

- 新建：tests/test_real_source_contract.py
- 修改：docs/operations/local-runbook.md、.sdd/progress.md

- [ ] 1. 写 opt-in real_source 测试：只在 KB_REAL_SOURCE_TESTS=1 时读取四份给定 JSONL，不建模型；断言总数 1,096、各文件 270/9/786/31、共同字段存在、所有 chunk_id 唯一。
- [ ] 2. 默认运行 python -m pytest -q，确认常规测试全通过而 real_source 测试 skip。
- [ ] 3. 设置 KB_REAL_SOURCE_TESTS=1，运行该测试，生成 data\reports\source-contract-report.json，写入日期、每个计数和 SHA-256。
- [ ] 4. 前提是 wheel 验证与依赖安装已成功：显式下载 BGE-M3 到 data\model_cache，用小 fixture 或明确选定版本完成一次 ingest、approve、中英查询；每一结果必须含源语言摘录和 citation。之后设置 KB_MODEL_LOCAL_FILES_ONLY=true 重跑，验证不发生第二次网络下载。
- [ ] 5. 最后运行 python -m pytest -q、python -m pip check、python -m compileall app scripts。让独立审阅者检查完整文件集和设计要求，记录测试计数、包版本、真实模型结果/完整性阻塞、索引路径、已知局限性。

## 计划自检

- 覆盖：Task 0 管理 D 盘与可信依赖；Task 1–4 管理治理、溯源、LlamaIndex 快照、审批、差异；Task 5 是中英文证据检索；Task 6 是本地运行入口；Task 7 使用真实源数据验证。
- 一致性：只有 LlamaIndex 保存和查询向量；SQLite 不再存 FTS 或 embedding blob；每份 active 版本必须有已校验快照。
- 范围：不包括 UI、Agent、LLM 答案生成、云向量库、认证服务、机器翻译或临床结论生成。
- 明确决定：BM25 仅在固定版本集成可导入时启用；否则返回明确 vector 模式。PDF 页码展示为页序号，不宣称印刷页码。
