# Breast Knowledgebase

团队内部测试版的乳腺癌指南证据知识库。项目使用 LlamaIndex 构建中英文语义检索和 BM25 混合检索，返回原文证据、`raw_chunk_id`、来源等级以及 PDF 页码或 HTML 标题路径。

本服务只提供可溯源证据，不生成临床结论，也不能替代医生判断或正式指南原文。

## 当前数据状态

| 资料 | 版本 ID | 状态 | 分块/节点 | 语言 | 来源等级 |
| --- | --- | --- | ---: | --- | --- |
| CACA 乳腺癌指南 | `caca-breast-cancer-2026` | `active` | 270 | 中文 | `primary_guideline` |
| CACA 乳腺癌指南（中间记录） | `caca-breast-cancer-2026-r2` | `draft` | 324 | 中文 | `primary_guideline` |
| CACA 乳腺癌指南（审核候选） | `caca-breast-cancer-2026-r3` | `draft` | 324 | 中文 | `primary_guideline` |
| NCCN Breast Cancer | `nccn-breast-cancer-6-2026` | `draft` | 786 | 英文 | `primary_guideline` |
| Gradishar NCCN Breast Cancer | `gradishar-nccn-breast-cancer-4-2026` | `draft` | 9 | 英文 | `primary_publication` |
| OncoToolkit HER2 Breast Cancer | `oncotoolkit-her2-breast-cancer-2026` | `draft` | 31 | 英文 | `secondary_summary` |

数据库当前包含 4 个指南、6 个版本、1,744 个原始分块、1,744 个索引节点和 3,525 条追加式审计事件。默认检索只包含 `active` 版本，因此仍只检索原 CACA 2026。r2 是源文件变化期间保留的不可变中间审计记录，不应批准；r3 是唯一待人工审核的 CACA 新候选。

## 运行要求

- Windows x64
- Python `>=3.12,<3.13`
- Git
- 首次安装依赖和下载 BGE-M3 时可以访问互联网
- 建议 16 GB 内存和至少 8 GB 可用磁盘空间
- 项目必须位于 `D:\coding\knowledgebase`

当前版本在应用和运维脚本中固定了项目根目录。克隆到其他路径会在启动、快照验证或导入时失败。

## 目录结构

```text
knowledgebase/
  app/                  FastAPI、检索、版本治理和溯源实现
  config/               四份初始资料的导入配置
  docs/                 运维手册、状态说明和设计文档
  scripts/              导入、快照验证和运行环境脚本
  tests/                自动化测试与真实源契约测试
  data/                 Release 数据、模型和运行缓存，不进入 Git
  pyproject.toml         Python 版本和依赖锁定
```

## 1. 克隆仓库

在 PowerShell 中执行：

```powershell
New-Item -ItemType Directory -Force D:\coding | Out-Null
Set-Location D:\coding
git clone https://github.com/kyunull/Breast_Knowledgebase.git knowledgebase
Set-Location D:\coding\knowledgebase
```

该仓库为私有仓库，克隆账号必须具有访问权限。

## 2. 恢复真实数据

从仓库的私有 GitHub Release `v0.1.0-internal-test` 下载：

```text
breast-knowledgebase-data-v0.1.0-internal-test.zip
breast-knowledgebase-data-v0.1.0-internal-test.zip.sha256
```

将两个文件放到 `D:\coding\knowledgebase\dist`，然后校验并解压：

```powershell
Set-Location D:\coding\knowledgebase

$archive = Join-Path $PWD 'dist\breast-knowledgebase-data-v0.1.0-internal-test.zip'
$checksumFile = "$archive.sha256"
$expected = ((Get-Content -Raw $checksumFile).Trim() -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()

if ($actual -ne $expected) {
    throw "Data archive SHA-256 mismatch: expected $expected, got $actual"
}

Expand-Archive -LiteralPath $archive -DestinationPath $PWD -Force
```

解压后至少应存在：

```text
data/registry/knowledge.sqlite3
data/llama_indices/
data/managed_sources/
data/reports/source-contract-report.json
data/DATA_MANIFEST.json
```

## 3. 创建 Python 环境

先把临时目录和包缓存固定到项目 D 盘，再创建虚拟环境并在线安装锁定依赖：

```powershell
Set-Location D:\coding\knowledgebase

$runtimeCache = Join-Path $PWD 'data\runtime_cache'
$tempDir = Join-Path $runtimeCache 'tmp'
$pipCache = Join-Path $runtimeCache 'pip_cache'
New-Item -ItemType Directory -Force $tempDir, $pipCache | Out-Null

$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:PIP_CACHE_DIR = $pipCache

py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install ".[dev]"
& .\.venv\Scripts\python.exe -m pip check
```

项目使用 LlamaIndex，没有引入 LangChain。

## 4. 下载并固定 BGE-M3

在同一个 PowerShell 窗口中设置模型参数。首次运行允许联网，将固定 revision 下载到项目的 `data\model_cache`：

```powershell
$env:KB_MODEL_NAME = 'BAAI/bge-m3'
$env:KB_MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
$env:KB_MODEL_DEVICE = 'cpu'
$env:KB_EMBEDDING_BATCH_SIZE = '4'
$env:KB_MODEL_MAX_SEQ_LENGTH = '512'
$env:KB_MODEL_LOCAL_FILES_ONLY = 'false'

& .\.venv\Scripts\python.exe -m scripts.verify_snapshot `
  --version-id caca-breast-cancer-2026
```

首次下载完成后切换为本地文件模式，并验证全部快照：

```powershell
$env:KB_MODEL_LOCAL_FILES_ONLY = 'true'

$versionIds = @(
    'caca-breast-cancer-2026',
    'caca-breast-cancer-2026-r2',
    'caca-breast-cancer-2026-r3',
    'gradishar-nccn-breast-cancer-4-2026',
    'nccn-breast-cancer-6-2026',
    'oncotoolkit-her2-breast-cancer-2026'
)

foreach ($versionId in $versionIds) {
    & .\.venv\Scripts\python.exe -m scripts.verify_snapshot --version-id $versionId
    if ($LASTEXITCODE -ne 0) { throw "Snapshot verification failed: $versionId" }
}
```

以后每次打开新的 PowerShell 窗口，都需要重新设置以上 `KB_MODEL_*` 环境变量。正常使用时保持 `KB_MODEL_LOCAL_FILES_ONLY=true`。

## 5. 运行验收测试

普通测试使用模拟嵌入，真实源契约测试需要显式开启：

```powershell
$env:KB_REAL_SOURCE_TESTS = '0'
& .\.venv\Scripts\python.exe -m pytest -q -W error

& .\.venv\Scripts\python.exe -m compileall -q app scripts
& .\.venv\Scripts\python.exe -m pip check
```

当前基线结果：

```text
79 passed, 1 skipped
No broken requirements found.
```

默认测试中的一个 skip 是需要开发机原始资料的全量真实源契约测试。当前 CACA r3 已按 324 条和 SHA-256 `983e26188f574a8200f367347175e2bfb79c4d430ffd0b26fc2a5187fc62d1f5` 单独验证通过。最新一次检查时，上游 NCCN JSONL 为 822 条而已导入 draft 为 786 条，上游 Gradishar 为 8 条而已导入 draft 为 9 条；因此这两份资料重新导入前，全量真实源契约会有意失败，不能作为当前发布通过项。OncoToolkit 的 31 条及哈希未变化。不要为消除失败而改写已导入数据库。

需要查看该差异时，在持有原始资料的开发机运行：

```powershell
$env:KB_REAL_SOURCE_TESTS = '1'
& .\.venv\Scripts\python.exe -m pytest tests\test_real_source_contract.py -q -W error
```

团队目标设备只恢复私有 Release 中的托管资料和索引，不要求存在开发机的 `D:\document` 原始路径，因此保持 `KB_REAL_SOURCE_TESTS=0`。

## 6. 启动服务

确认数据包、模型变量和快照验证都已完成后启动：

```powershell
Set-Location D:\coding\knowledgebase

& .\.venv\Scripts\python.exe -m uvicorn app.main:app `
  --host 127.0.0.1 `
  --port 8000
```

API 文档地址：<http://127.0.0.1:8000/docs>

不要把监听地址改成 `0.0.0.0`。当前内部测试 API 没有身份认证、TLS 或多用户权限控制。

## 7. 检索示例

另开一个 PowerShell 窗口。中文查询：

```powershell
$body = @{
    query = 'HER2阳性乳腺癌治疗'
    top_k = 5
    use_bm25 = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/search `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

英文查询：

```powershell
$body = @{
    query = 'HER2-positive breast cancer treatment'
    top_k = 5
    use_bm25 = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/search `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

响应包含：

- `evidence[].text`：原文
- `evidence[].raw_chunk_id`：原始分块标识
- `evidence[].authority_level`：来源等级
- `evidence[].citation`：指南、版本、PDF 页码或 HTML 路径
- `resolved_version_ids`：实际参与检索的版本
- `retrieval_modes`：`vector` 或 `vector + bm25`

响应不包含生成式 `answer` 字段。

## 8. 版本治理与审计

查看指南、版本和审计记录：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/guidelines
Invoke-RestMethod http://127.0.0.1:8000/audit
```

当前 `/search` 不允许检索 `draft`，显式请求 draft 会返回 HTTP 422。只能先通过原始资料、JSONL、来源契约报告和快照验证完成人工审查，再执行批准。CACA 只审核并考虑批准 `caca-breast-cancer-2026-r3`，不要批准 r2。

批准会把版本变为 `active`；如果同一指南已有 active 版本，旧版会原子地变为 `superseded`。批准前必须使用真实审核人标识：

```powershell
$body = @{ reviewer = 'team-reviewer-id' } | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/versions/caca-breast-cancer-2026-r3/approve `
  -ContentType 'application/json' `
  -Body $body
```

不要在安装烟测中执行批准。批准会修改共享 SQLite 状态并写入追加式审计记录。

## 9. 常见问题

### 项目根目录错误

报错包含 `project root must be D:\coding\knowledgebase` 时，确认仓库位于固定路径，不要通过环境变量把数据库、索引或缓存指向项目外。

### 首次模型加载失败

确认首次下载时设置了：

```powershell
$env:KB_MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
$env:KB_MODEL_LOCAL_FILES_ONLY = 'false'
```

模型下载成功并完成一次快照验证后，再改为 `true`。

### 快照模型配置不一致

不得使用 BGE-M3 的浮动 `main` 版本。检查模型名、revision、device 和最大序列长度是否与本文一致。

### draft 查询返回 422

这是当前版本的预期行为，不是检索故障。不要为了烟测临时批准 draft。

### PowerShell 中文显示异常

可在当前窗口设置：

```powershell
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
```

## 10. 安全与资料范围

- 仅供已授权团队成员在受控设备上测试。
- 私有 Release 中的 PDF、HTML、JSONL、SQLite 和索引不得转发到公共仓库。
- API 的 `/ingest` 和 `/versions/{version_id}/approve` 没有身份认证，只能本机使用。
- 不得将 GitHub Token、用户名密码或带凭据的 URL 写入配置、脚本、README 或日志。
- OncoToolkit 标记为 `secondary_summary`，不能替代指南原文。
- 所有检索结果都需要由具备资质的人员结合正式来源复核。

更完整的运行和导入说明见：

- [`docs/operations/local-runbook.md`](docs/operations/local-runbook.md)
- [`docs/operations/initial-import-status.md`](docs/operations/initial-import-status.md)
