# 本地运行手册

本手册适用于团队内部 Windows 测试设备。项目可以位于任意绝对路径；所有可写运行数据必须位于当前项目根目录，原始 PDF、HTML 和 JSONL 可以位于任意盘符，但必须是已存在的绝对文件。

## 1. 初始化

```powershell
$ProjectRoot = (Get-Location).Path

powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1
& .\.venv\Scripts\python.exe -m pip check
```

脚本根据 `$PSScriptRoot` 确定仓库，不依赖调用时的工作目录。以下环境变量即使显式设置，也只能解析到 `$ProjectRoot` 内：

```text
KB_DATA_DIR
KB_REGISTRY_DB_PATH
KB_MANAGED_SOURCES_DIR
KB_INDEX_ROOT
KB_MODEL_CACHE_DIR
KB_RUNTIME_CACHE_DIR
```

## 2. 数据包与路径迁移

从已获授权的公开预发布 Release `v0.2.0-internal-test` 下载数据 zip 和 `.sha256`，按 README 校验后解压到 `$ProjectRoot`。数据包包含全部 8 个已注册版本的向量索引和托管源文件，但不包含 BGE-M3 模型；`data/` 不进入 Git。

服务启动时会检查 SQLite 中的 `document_version.snapshot_path` 和 `source_file.managed_path`：

1. 已是项目相对路径时不修改，也不重复写审计。
2. 旧绝对路径会按版本 ID 和文件名映射到当前项目的 `data` 目录。
3. 所有快照目录和托管文件均存在后，才在一个 SQLite 事务中改写。
4. 成功后只追加一条 `project_paths_rebased`，payload 仅记录迁移路径数量。
5. 任一目标缺失或逃逸项目目录时整体回滚并停止启动。

不要通过创建空目录或复制其他版本文件来绕过迁移失败。应重新核对数据包完整性和 SHA-256。

## 3. 选择嵌入模式

### 本地模式

默认使用固定 revision 的 BGE-M3：

```powershell
$env:KB_EMBEDDING_PROVIDER = 'local'
$env:KB_MODEL_NAME = 'BAAI/bge-m3'
$env:KB_MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
$env:KB_MODEL_DEVICE = 'cpu'
$env:KB_EMBEDDING_BATCH_SIZE = '4'
$env:KB_MODEL_MAX_SEQ_LENGTH = '512'
$env:KB_MODEL_LOCAL_FILES_ONLY = 'true'
```

首次下载时暂时将 `KB_MODEL_LOCAL_FILES_ONLY` 设为 `false`，完成一次快照验证后再改回 `true`。

### 远程模式

目标设备需要能访问团队批准的 OpenAI-compatible embeddings 服务：

```powershell
$env:KB_EMBEDDING_PROVIDER = 'remote'
$env:KB_EMBEDDING_BASE_URL = 'https://embedding.example.com/v1'
$env:KB_EMBEDDING_MODEL = 'BAAI/bge-m3'
$env:KB_EMBEDDING_DIMENSION = '1024'
$env:KB_EMBEDDING_TIMEOUT_SECONDS = '30'
$env:KB_EMBEDDING_MAX_RETRIES = '2'

$secureKey = Read-Host 'Embedding API key' -AsSecureString
$env:KB_EMBEDDING_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
```

未知 provider、缺少 key/model/base URL、非回环 HTTP 地址都会在启动或首次加载模型时失败。408、429、5xx 和网络错误只做有限重试。API key 不得进入配置文件、导入 JSON、SQLite、manifest、审计、日志或 Git。

快照 manifest 的 `provider`、`model_name`、`dimension`、`normalize` 必须与当前模式兼容。现有数据包中的索引由本地 BGE-M3 构建，远程模式不能直接查询这些索引；需要用远程模式重新导入为新的 draft，并完成人工审核。

## 4. 启动 API

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

只监听 `127.0.0.1`。当前测试 API 没有身份认证和 TLS。

## 5. 检查当前状态

```powershell
Invoke-RestMethod http://127.0.0.1:8000/guidelines
Invoke-RestMethod http://127.0.0.1:8000/audit
```

不指定版本时只检索 `active`。显式检索 `draft` 返回 HTTP 422；显式检索已注册的 `superseded` 版本用于历史复核。

```powershell
$body = @{
    query = 'HER2阳性乳腺癌辅助治疗'
    top_k = 5
    use_bm25 = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/search `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

响应只能包含证据、实际版本和检索模式。每条证据必须有原文、`raw_chunk_id`、来源等级和 citation；没有 `answer` 字段。

## 6. 导入 draft

导入配置必须位于当前项目内，源文件路径必须是已存在的绝对路径。`jsonl_source_id` 指向 JSONL，`citation_source_id` 指向 PDF 或 HTML。

```powershell
$config = Join-Path $ProjectRoot 'config\new-version.json'
& .\.venv\Scripts\python.exe -m scripts.ingest_guideline --config $config
```

导入成功只打印新 draft 的版本 ID。新托管副本和快照保存在项目内，SQLite 保存项目相对路径；`original_path` 继续保留提交导入时的外部绝对路径用于审计。

现有初始配置：

```text
config/initial_sources.json
config/caca_2026_r2.json
config/caca_2026_r3.json
config/initial_sources_nccn_v6.json
config/initial_sources_gradishar.json
config/initial_sources_oncotoolkit.json
```

这些配置中的源路径属于导入机器，团队目标设备不要保留相同原始路径即可查询已托管的快照。

## 7. 快照复核与批准

```powershell
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot `
  --version-id nccn-breast-cancer-6-2026
```

批准前检查：

- 原始 PDF/HTML 与托管副本哈希一致。
- JSONL 条数、必填字段和 `chunk_id` 唯一性符合预期。
- manifest、组件哈希、节点数和嵌入配置验证通过。
- 抽样中英文查询能返回正确原文和页码/HTML 路径。
- 版本差异符合预期。
- reviewer 使用真实团队标识。

批准命令：

```powershell
$body = @{ reviewer = 'team-reviewer-id' } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/versions/nccn-breast-cancer-6-2026/approve `
  -ContentType application/json `
  -Body $body
```

批准会让该版本变为 `active`，并把同指南旧 `active` 原子更新为 `superseded`。不要在安装烟测中批准任何 draft。CACA r2 是中间审计版本，不能批准。

## 8. 测试与真实源契约

普通验收不依赖开发机原始资料：

```powershell
$env:KB_REAL_SOURCE_TESTS = '0'
& .\.venv\Scripts\python.exe -m pytest -q -W error
& .\.venv\Scripts\python.exe -m compileall -q app scripts
& .\.venv\Scripts\python.exe -m pip check
```

只有持有原始 JSONL 的机器才运行：

```powershell
$env:KB_REAL_SOURCE_TESTS = '1'
& .\.venv\Scripts\python.exe -m pytest tests\test_real_source_contract.py -q -W error
```

当前上游 NCCN 和 Gradishar 文件数量与已导入 draft 不一致，完整真实源契约可能按预期失败。不要为消除失败而修改已导入数据库或直接批准旧 draft。

## 9. 停止与清理凭据

在 Uvicorn 窗口按 `Ctrl+C`。使用远程模式后清理当前进程变量：

```powershell
Remove-Item Env:KB_EMBEDDING_API_KEY -ErrorAction SilentlyContinue
```
