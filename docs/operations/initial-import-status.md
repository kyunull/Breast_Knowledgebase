# 初始资料导入状态

更新时间：2026-08-17

本项目已用四份真实资料和对应 JSONL 建立版本独立的 LlamaIndex 快照。项目可以移动到任意绝对目录；可写数据位于当前项目的 `data` 子目录。源文件未被修改，SQLite 中的 `original_path` 仅作为导入来源审计记录。

## 当前版本

| 指南 | 版本 ID | 状态 | 分块/节点 | 来源等级 |
| --- | --- | --- | ---: | --- |
| CACA 原生效版本 | `caca-breast-cancer-2026` | `superseded` | 270 | `primary_guideline` |
| CACA 中间审计版本 | `caca-breast-cancer-2026-r2` | `draft` | 324 | `primary_guideline` |
| CACA 历史结构化版本 | `caca-breast-cancer-2026-r3` | `superseded` | 324 | `primary_guideline` |
| CACA 表格 OCR 历史版本 | `caca-breast-cancer-2026-table-ocr-r1` | `superseded` | 499 | `primary_guideline` |
| CACA 表格 OCR 英文间距规范化当前版本 | `caca-breast-cancer-2026-table-ocr-r2` | `active` | 499 | `primary_guideline` |
| Gradishar NCCN Breast Cancer | `gradishar-nccn-breast-cancer-4-2026` | `draft` | 9 | `primary_publication` |
| NCCN Breast Cancer 历史草稿 | `nccn-breast-cancer-6-2026` | `draft` | 786 | `primary_guideline` |
| NCCN Breast Cancer 更新草稿 | `nccn-breast-cancer-6-2026-r2` | `draft` | 822 | `primary_guideline` |
| NCCN Breast Cancer 表格 OCR 当前版本 | `nccn-breast-cancer-6-2026-table-ocr-r1` | `active` | 1,509 | `primary_guideline` |
| OncoToolkit HER2 Breast Cancer | `oncotoolkit-her2-breast-cancer-2026` | `draft` | 31 | `secondary_summary` |
| CSCO 乳腺癌诊疗指南 2026（表格 OCR 重建） | `csco-breast-cancer-2026-table-ocr-r1` | `active` | 1,071 | `primary_guideline` |

当前数据库实测：5 个 guideline、11 个 version、6,144 个 raw chunk、6,144 个索引节点、3,054 条版本差异和 12,360 条追加式审计事件。节点数包含 CACA、NCCN 和 CSCO 的历史/候选版本。

默认检索只包含 `active`，因此目前返回 CACA、NCCN 和 CSCO 的表格感知版本。CACA 表格 OCR r1 已由 r2 原子替换为 `superseded`；旧 CACA 中间审计 r2 和旧 NCCN 草稿仍是保留但不批准的审计记录。Gradishar 不是 NCCN V6 的历史版本，OncoToolkit 始终是 `secondary_summary`。

## 已验证能力

- CACA r3 的中文与英文 HER2 查询均命中 CACA 原文证据，并返回 `raw_chunk_id` 和 PDF 页码。
- CACA r3 托管 JSONL 为 324 条，SHA-256 为 `983e26188f574a8200f367347175e2bfb79c4d430ffd0b26fc2a5187fc62d1f5`。
- CACA r3 快照可在固定 revision 的本地 BGE-M3 模式下重新打开并校验 manifest。
- CACA r3 已由审核人 `dongy` 批准为 `active`，原 CACA 2026 已原子更新为 `superseded`。
- CSCO 表格 OCR r1 已由审核人 `codex-user-requested` 批准为 `active`；版本包含 1,071 个节点、92 个表格父块和 617 个表格行块。
- CACA 表格 OCR r1 已由审核人 `codex-user-approved` 批准为 `active`；版本包含 499 个节点、32 个表格父块和 175 个表格行块，manifest 为 `72f224a3446f976c28010d6a1f8f4377930fe88ca1e1be3189791f57174825ad`。
- CACA 表格 OCR r2 已由审核人 `codex-user-approved-spacing-r2` 批准为 `active`；版本包含 499 个节点、32 个表格父块和 175 个表格行块，manifest 为 `b81dc8b1c2aa185df07506c4a315614b05a95084a0d29cb319b044cb398653f5`。它基于 r1 JSONL 的 13 条记录执行 16 次显式英文间距规范化，输出 JSONL SHA-256 为 `aac41f6c485683900e9eaf5e7a614fa564c05338a181bbf02d8c454cf1765546`，无残留小写英文拆字。
- NCCN 表格 OCR r1 已由审核人 `codex-user-approved` 批准为 `active`；版本包含 1,509 个节点、77 个表格父块和 687 个表格行块，manifest 为 `c23f1eb36ee0c16d146b6c47cf84c687d64a6ab213fd2164a43ec684c76f4828`。
- CACA 292 条、NCCN 745 条非表格记录在重建前后顺序及文本 SHA-256 完全一致；CACA 全部表格由腾讯 `Type=1/2` 重建，NCCN 有 46 个复杂表格采用 PyMuPDF 矢量单元格回退。
- CACA/NCCN 各 3 条表格查询均在前 5 条证据中命中表格父块或行块，检索证据见 `data/reports/table-ocr-retrieval-r1.json`。
- NCCN r2 托管 JSONL 为 822 条，SHA-256 为 `8f04b5f19e710948daff64ffa50d1767a6c3ffca9393c9488d933d285f1a7e3b`；PDF SHA-256 为 `9d7bac09e03956dbe875516c23a6cfbfea05507a33a145f8e66474f3cfe00820`。
- NCCN r2 快照 manifest 为 `3f5f06689a27f76e28dbb965fd3e5426bad97ffbc7ae06fa681d603ccd41053b`，可用固定 revision 的本地 BGE-M3 重新打开。
- 旧 NCCN 草稿到 r2 共记录 1,142 条版本差异：356 条新增、320 条删除、348 条修改、118 条不变。
- NCCN r2 的英文 HER2 查询命中 NCCN 原文，并返回 `raw_chunk_id`、来源等级和 PDF 页码元数据。
- 新导入的托管源和快照路径以项目相对路径保存；旧绝对路径会在文件完整时事务迁移。
- 本地模式固定 `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`。
- 远程模式支持 OpenAI-compatible `/embeddings`，并校验 provider、模型名、维度、归一化、响应数量和响应顺序。
- API key 不进入 SQLite、manifest、审计 payload、日志或异常消息。
- 审批会重新校验快照，并原子地把同指南旧 `active` 更新为 `superseded`。

## 审核顺序

1. CACA 表格 OCR r2 已完成审批；复核默认检索只解析到 `caca-breast-cancer-2026-table-ocr-r2`。旧的 `caca-breast-cancer-2026-r2` 仍是未批准的中间审计版本。
2. 审核 NCCN r2 的 822 条托管 JSONL、PDF 引用、版本差异和抽样查询；保留旧 NCCN 草稿但不要批准。
3. 启动 API，确认显式检索 NCCN r2 draft 返回 HTTP 422；审核通过后再以真实审核人 ID 批准 r2。
4. 分别处理 Gradishar 和 OncoToolkit。上游 Gradishar 数量与当前 draft 不一致时，先导入新版本，不直接批准旧 draft。

批准示例：

```powershell
$body = @{ reviewer = 'team-reviewer-id' } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/versions/nccn-breast-cancer-6-2026-r2/approve `
  -ContentType application/json `
  -Body $body
```

## 嵌入模式注意事项

当前交付索引由本地 pinned BGE-M3 构建。本地模式可以直接校验和查询。远程 provider 与本地 provider 的 manifest 契约不同，不能直接加载当前本地索引；如需评估远程 API，应使用远程模式创建新的 draft 快照，并在相同 provider/model/dimension/normalize 配置下检索。

远程 key 只通过当前 PowerShell 进程的 `KB_EMBEDDING_API_KEY` 提供，不写入任何项目文件。

## 验证记录

- 严格自动化测试：`111 passed, 1 skipped`。
- 默认 skip 是需要开发机原始资料的完整真实源契约测试。
- CACA r3 单源契约：324 条、必填字段完整、`chunk_id` 唯一、固定 SHA-256 一致。
- NCCN r2 单源契约：822 条、必填字段完整、`chunk_id` 唯一、固定 SHA-256 一致。
- 启用完整真实源契约后，NCCN 已满足新契约；当前唯一失败是尚未重新导入的 Gradishar 上游文件为 8 条、数据库草稿为 9 条。
- 最新检查中，NCCN r2 已按上游 822 条重新导入；上游 Gradishar 为 8 条而当前 draft 为 9 条；OncoToolkit 31 条及哈希未变化。

已获授权的公开预发布 Release `v0.2.0-internal-test` 仍是本次 CACA/NCCN 表格重建前的数据包。重新发布时必须包含 10 个版本的 SQLite、托管源文件、staging JSONL、两个新增向量快照和校验 manifest，且不得包含 BGE-M3 模型。

完整命令和停止条件见 [本地运行手册](local-runbook.md) 和 [表格感知 OCR 工作流](table-aware-ocr-workflow.md)。
