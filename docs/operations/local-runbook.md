# 本地运行手册

本知识库只在 `D:\coding\knowledgebase` 下写入数据。原始 PDF、HTML 和 JSONL 只读；系统把字节一致的受管副本、SQLite 注册表、LlamaIndex 快照、模型缓存和临时文件写入项目的 `data` 子目录。API 只返回原文证据和引用，不生成临床结论。

## 1. 初始化环境

在 PowerShell 中执行：

```powershell
Set-Location D:\coding\knowledgebase
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1 -ProjectRoot D:\coding\knowledgebase
& .\.venv\Scripts\python.exe -m pip check
```

启动前不要把 `KB_DATA_DIR`、`KB_REGISTRY_DB_PATH`、`KB_INDEX_ROOT`、`KB_MODEL_CACHE_DIR` 或 `KB_RUNTIME_CACHE_DIR` 指到项目外。程序会拒绝项目外的可写路径，也会拒绝 C 盘源文件。

## 2. 导入草稿

复制 `config\known_sources.example.json` 为项目内的新配置文件，例如 `config\nccn-v6.json`，替换全部占位符。源文件和 JSONL 路径必须显式填写为 D 盘绝对路径；`jsonl_source_id` 必须指向 JSONL 项，`citation_source_id` 必须指向 PDF 或 HTML 项。

首次导入某指南时保留 `guideline` 对象；后续版本可以删除该对象，但 `version.guideline_id`、语言和来源等级必须与已注册指南一致。

```powershell
& .\.venv\Scripts\python.exe -m scripts.ingest_guideline --config D:\coding\knowledgebase\config\nccn-v6.json
```

命令成功时只打印新建的 draft 版本 ID。draft 不参与默认检索。

本次已导入的真实资料、版本状态和审核命令见 initial-import-status.md。

### 首次资料配置

项目已提供四份经过实际源文件盘点的初始导入配置；它们都只引用用户提供的 D 盘原件。四者是独立的生命周期对象，不能将 Gradishar 精选发表当成 NCCN V6 的历史版本；OncoToolkit 始终以 secondary_summary 标注。

    .\config\initial_sources.json                   # CACA 2026 active，270 条，历史导入配置
    .\config\caca_2026_r2.json                      # CACA r2 draft，324 条，仅保留中间审计记录
    .\config\caca_2026_r3.json                      # CACA r3 draft，324 条，当前审核候选
    .\config\initial_sources_nccn_v6.json           # NCCN V6.2026，786 条，英文，primary_guideline
    .\config\initial_sources_gradishar.json         # Gradishar 4.2026，9 条，英文，primary_publication
    .\config\initial_sources_oncotoolkit.json       # OncoToolkit 2026，31 条，英文，secondary_summary

首次使用真实模型前，固定模型 revision 并启用本地文件模式：

    $env:KB_MODEL_NAME = 'BAAI/bge-m3'
    $env:KB_MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
    $env:KB_MODEL_DEVICE = 'cpu'
    $env:KB_EMBEDDING_BATCH_SIZE = '4'
    $env:KB_MODEL_MAX_SEQ_LENGTH = '512'
    $env:KB_MODEL_LOCAL_FILES_ONLY = 'true'

## 3. 启动本地 API

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

只监听 `127.0.0.1`。另开 PowerShell 窗口执行后续命令。

## 4. 审批与快照复核

审批前独立重开并校验 LlamaIndex 快照及 manifest：

```powershell
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot --version-id nccn-breast-cancer-6-2026
```

审批需要非空 reviewer；审批会再次验证快照。新版本变为 active，旧 active 原子地变为 superseded。

```powershell
$body = @{ reviewer = 'replace-with-reviewer-id' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/versions/nccn-breast-cancer-6-2026/approve -ContentType application/json -Body $body
```

## 5. 当前版本与历史版本检索

不指定版本时只检索 active 版本：

```powershell
$body = @{ query = 'HER2阳性乳腺癌辅助治疗'; top_k = 5; use_bm25 = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/search -ContentType application/json -Body $body
```

指定 superseded 版本可做历史检索；不存在、draft 或损坏的显式版本会返回验证错误，不会静默回退到 active：

```powershell
$body = @{ query = 'trastuzumab'; version_ids = @('replace-with-superseded-version-id'); top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/search -ContentType application/json -Body $body
```

响应只有 `evidence`、`resolved_version_ids` 和 `retrieval_modes`。每条 evidence 包含原文、`raw_chunk_id` 和 citation；没有 `answer` 字段。

## 6. 版本、差异与审计

```powershell
Invoke-RestMethod http://127.0.0.1:8000/guidelines
Invoke-RestMethod 'http://127.0.0.1:8000/versions/replace-with-current-version-id/diff?prior_version_id=replace-with-prior-version-id'
Invoke-RestMethod http://127.0.0.1:8000/audit
```

差异接口只接受同一指南的两个已注册版本。审计事件是追加式记录，SQLite 触发器会拒绝更新或删除。

## 7. 显式真实模型烟测

常规测试使用模拟嵌入，不下载模型。只有在依赖校验通过、磁盘空间充足、网络来源获准时，才运行以下命令让首次导入显式下载 `BAAI/bge-m3` 到 `D:\coding\knowledgebase\data\model_cache`：

```powershell
$env:KB_MODEL_NAME = 'BAAI/bge-m3'
$env:KB_MODEL_DEVICE = 'cpu'
$env:KB_EMBEDDING_BATCH_SIZE = '4'
$env:KB_MODEL_MAX_SEQ_LENGTH = '512'
& .\.venv\Scripts\python.exe -m scripts.ingest_guideline --config D:\coding\knowledgebase\config\smoke.json
```

首次成功后验证离线重载：

```powershell
$env:KB_MODEL_LOCAL_FILES_ONLY = 'true'
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot --version-id replace-with-smoke-version-id
```

验证源文件契约但不建索引：

    $env:KB_REAL_SOURCE_TESTS = '1'
    & .\.venv\Scripts\python.exe -m pytest tests\test_real_source_contract.py -q -W error
    Get-Content .\data\reports\source-contract-report.json -Encoding utf8

当前全量源契约会因上游资料仍在变化而失败。最新一次检查时，NCCN 上游文件为 822 条、已导入 draft 为 786 条，Gradishar 上游文件为 8 条、已导入 draft 为 9 条；OncoToolkit 的 31 条及哈希未变化。CACA r3 已按 324 条和锁定 SHA-256 单独验证。不要把全量契约失败误判为 CACA r3 索引失败，也不要为消除失败而修改既有 draft。

遇到以下任一情况立即停止，不审批该 draft：wheel/hash 校验失败；模型文件写到项目外；源文件或 JSONL 数量/字段不符合预期；快照无法验证或重载；证据缺少原文、`raw_chunk_id` 或 citation；中英文测试查询明显无法定位预期证据。保留 draft 和审计记录供排查，不修改原始文件，也不删除旧 active。

## 8. 本地验收与停止服务

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m compileall app scripts
& .\.venv\Scripts\python.exe -m pip check
```

在运行 Uvicorn 的窗口按 `Ctrl+C` 停止服务。
