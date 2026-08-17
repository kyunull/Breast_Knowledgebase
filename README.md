# Breast Knowledgebase

团队内部测试版乳腺癌指南证据知识库。项目采用 LlamaIndex，暂未使用 LangChain；支持中英文语义检索与 BM25 混合检索，返回原文、`raw_chunk_id`、来源等级以及 PDF 页码或 HTML 路径。服务只返回可溯源证据，不生成临床结论。

## 当前数据

| 资料 | 版本 ID | 状态 | 分块/节点 | 来源等级 |
| --- | --- | --- | ---: | --- |
| CACA 原生效版本 | `caca-breast-cancer-2026` | `superseded` | 270 | `primary_guideline` |
| CACA 中间审计版本 | `caca-breast-cancer-2026-r2` | `draft` | 324 | `primary_guideline` |
| CACA 历史结构化版本 | `caca-breast-cancer-2026-r3` | `superseded` | 324 | `primary_guideline` |
| CACA 表格 OCR 历史版本 | `caca-breast-cancer-2026-table-ocr-r1` | `superseded` | 499 | `primary_guideline` |
| CACA 表格 OCR 英文间距规范化当前版本 | `caca-breast-cancer-2026-table-ocr-r2` | `active` | 499 | `primary_guideline` |
| NCCN Breast Cancer V6.2026 历史草稿 | `nccn-breast-cancer-6-2026` | `draft` | 786 | `primary_guideline` |
| NCCN Breast Cancer V6.2026 更新草稿 | `nccn-breast-cancer-6-2026-r2` | `draft` | 822 | `primary_guideline` |
| NCCN Breast Cancer V6.2026 表格 OCR 当前版本 | `nccn-breast-cancer-6-2026-table-ocr-r1` | `active` | 1,509 | `primary_guideline` |
| Gradishar NCCN Breast Cancer | `gradishar-nccn-breast-cancer-4-2026` | `draft` | 9 | `primary_publication` |
| OncoToolkit HER2 Breast Cancer | `oncotoolkit-her2-breast-cancer-2026` | `draft` | 31 | `secondary_summary` |
| CSCO 乳腺癌诊疗指南 2026（表格 OCR 重建） | `csco-breast-cancer-2026-table-ocr-r1` | `active` | 1,071 | `primary_guideline` |

当前本机数据库实测共有 5 个 guideline、11 个 version、6,144 个分块/节点、3,054 条版本差异和 12,360 条追加式审计事件。节点总数包含不可变历史/候选版本，因此不能把它理解为资料的去重分块数。默认检索只使用 `active`，当前检索 CACA、NCCN 和 CSCO 的表格感知版本。不要批准旧的 CACA 中间审计 r2 或旧 NCCN 草稿；Gradishar 和 OncoToolkit 必须分别完成人工审核后再批准。

当前已获授权的公开预发布 Release `v0.2.0-internal-test` 仍是表格重建前的 8 版本数据包。重新发布数据包前必须包含新的 CACA/NCCN table-aware JSONL、两个 active 快照和更新后的 SQLite；任何数据包都不得包含 BGE-M3 模型、运行缓存或 wheelhouse。

## 运行要求

- Windows x64
- Python `>=3.12,<3.13`
- Git
- 首次安装依赖和下载本地 BGE-M3 时可联网
- 建议至少 16 GB 内存和 8 GB 可用磁盘空间
- GitHub 仓库和已获授权的数据包访问权限

项目可以克隆到任意现有绝对路径和任意盘符。程序从代码位置发现项目根目录，不依赖当前工作目录或固定盘符。SQLite、索引、托管源副本、模型、报告、包缓存和临时文件都必须留在当前项目根目录内；只读 PDF、HTML、JSONL 输入可以位于其他绝对路径。

## 快速安装

在 PowerShell 中执行：

```powershell
git clone https://github.com/kyunull/Breast_Knowledgebase.git
Set-Location .\Breast_Knowledgebase
$ProjectRoot = (Get-Location).Path

powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1
& .\.venv\Scripts\python.exe -m pip check
```

`bootstrap_runtime.ps1` 从脚本自身位置确定仓库根目录。显式传入 `-ProjectRoot` 时，只接受该脚本所属仓库，避免把运行数据写入另一个目录。

## 恢复真实数据

真实 PDF、HTML、JSONL、SQLite 和索引不进入 Git。它们通过已获授权的公开预发布 Release `v0.2.0-internal-test` 的以下文件交付：

```text
breast-knowledgebase-data-v0.2.0-internal-test.zip
breast-knowledgebase-data-v0.2.0-internal-test.zip.sha256
```

把两个文件放到项目的 `dist` 目录后校验并解压：

```powershell
$ProjectRoot = (Get-Location).Path
$archive = Join-Path $ProjectRoot 'dist\breast-knowledgebase-data-v0.2.0-internal-test.zip'
$checksumFile = "$archive.sha256"
$expected = ((Get-Content -Raw $checksumFile).Trim() -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()

if ($actual -ne $expected) {
    throw "Data archive SHA-256 mismatch: expected $expected, got $actual"
}

Expand-Archive -LiteralPath $archive -DestinationPath $ProjectRoot -Force
```

解压后至少应存在：

```text
data/registry/knowledge.sqlite3
data/llama_indices/
data/managed_sources/
data/reports/source-contract-report.json
data/DATA_MANIFEST.json
```

首次启动会检查旧 SQLite 中的绝对运行时路径。只有当前项目内对应的托管文件和快照全部存在时，程序才会在一个事务中改写为项目相对路径并追加一条 `project_paths_rebased` 审计事件。任何目标缺失都会整体回滚，不会创建空索引或部分迁移。

## 嵌入模式

### 本地 BGE-M3，默认

本地模式是默认值，模型固定为：

```text
BAAI/bge-m3
revision 5617a9f61b028005a4858fdac845db406aefb181
dimension 1024
normalize true
```

首次联网下载：

```powershell
$env:KB_EMBEDDING_PROVIDER = 'local'
$env:KB_MODEL_LOCAL_FILES_ONLY = 'false'
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot `
  --version-id caca-breast-cancer-2026
```

下载完成后可切换为离线加载：

```powershell
$env:KB_MODEL_LOCAL_FILES_ONLY = 'true'
```

模型和 Hugging Face 缓存都写入当前项目的 `data\model_cache`。

### 远程 OpenAI-compatible API

远程模式是显式 opt-in，调用 `<KB_EMBEDDING_BASE_URL>/embeddings`：

```powershell
$env:KB_EMBEDDING_PROVIDER = 'remote'
$env:KB_EMBEDDING_BASE_URL = 'https://embedding.example.com/v1'
$env:KB_EMBEDDING_MODEL = 'BAAI/bge-m3'
$env:KB_EMBEDDING_DIMENSION = '1024'

$secureKey = Read-Host 'Embedding API key' -AsSecureString
$env:KB_EMBEDDING_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
```

非回环地址必须使用 HTTPS；`http://127.0.0.1` 和 `http://localhost` 只用于本机测试。API key 只能存在于当前进程环境变量中，不得写入 JSON、SQLite、manifest、日志、命令脚本或 Git。关闭窗口或执行以下命令后清除：

```powershell
Remove-Item Env:KB_EMBEDDING_API_KEY -ErrorAction SilentlyContinue
```

manifest 会校验 provider、模型名、维度和归一化配置。远程 provider 与现有本地 provider 的快照不兼容；需要在远程模式下创建新的 draft 快照，不能绕过检查加载旧索引。远程服务返回数量、顺序、数值类型或维度异常时会立即失败，不会回退到本地模型。

## 启动与验证

```powershell
$ProjectRoot = (Get-Location).Path
$env:KB_REAL_SOURCE_TESTS = '0'

& .\.venv\Scripts\python.exe -m pytest -q -W error
& .\.venv\Scripts\python.exe -m compileall -q app scripts
& .\.venv\Scripts\python.exe -m pip check

& .\.venv\Scripts\python.exe -m uvicorn app.main:app `
  --host 127.0.0.1 `
  --port 8000
```

API 文档：<http://127.0.0.1:8000/docs>

当前内部服务没有身份认证、TLS 或多用户权限控制，只能监听 `127.0.0.1`，不要直接改为 `0.0.0.0`。

## 检索示例

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

响应包含 `evidence[].text`、`raw_chunk_id`、`authority_level`、`citation`、`resolved_version_ids` 和 `retrieval_modes`，不包含生成式 `answer` 字段。

## 审核与批准

先查看版本和审计：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/guidelines
Invoke-RestMethod http://127.0.0.1:8000/audit
```

审批前必须重新验证快照并由真实审核人检查原始资料、JSONL、引用和版本差异。审批会修改共享 SQLite：新版本变为 `active`，同指南旧 `active` 原子变为 `superseded`，并追加审计记录。不要在安装烟测中执行审批。

完整审核步骤见：

- [本地运行手册](docs/operations/local-runbook.md)
- [表格感知 OCR 工作流](docs/operations/table-aware-ocr-workflow.md)
- [初始导入状态](docs/operations/initial-import-status.md)

## 安全范围

- 仅供已授权团队成员在受控设备上测试。
- 真实资料和数据包仅可在项目授权范围内使用和转发；当前公开预发布 Release 已获得项目所有者授权。
- 不得提交 GitHub Token、API key、用户名密码或带凭据的 URL。
- OncoToolkit 是 `secondary_summary`，不能替代正式指南原文。
- 所有检索证据都需要由具备资质的人员结合正式来源复核。
