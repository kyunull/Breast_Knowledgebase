# 初始资料导入状态

更新时间：2026-08-17

本项目已用四份真实资料和对应 JSONL 建立版本独立的 LlamaIndex 快照。项目可以移动到任意绝对目录；可写数据位于当前项目的 `data` 子目录。源文件未被修改，SQLite 中的 `original_path` 仅作为导入来源审计记录。

## 当前版本

| 指南 | 版本 ID | 状态 | 分块/节点 | 来源等级 |
| --- | --- | --- | ---: | --- |
| CACA 原生效版本 | `caca-breast-cancer-2026` | `superseded` | 270 | `primary_guideline` |
| CACA 中间审计版本 | `caca-breast-cancer-2026-r2` | `draft` | 324 | `primary_guideline` |
| CACA 当前生效版本 | `caca-breast-cancer-2026-r3` | `active` | 324 | `primary_guideline` |
| Gradishar NCCN Breast Cancer | `gradishar-nccn-breast-cancer-4-2026` | `draft` | 9 | `primary_publication` |
| NCCN Breast Cancer 历史草稿 | `nccn-breast-cancer-6-2026` | `draft` | 786 | `primary_guideline` |
| NCCN Breast Cancer 更新草稿 | `nccn-breast-cancer-6-2026-r2` | `draft` | 822 | `primary_guideline` |
| OncoToolkit HER2 Breast Cancer | `oncotoolkit-her2-breast-cancer-2026` | `draft` | 31 | `secondary_summary` |
| CSCO 乳腺癌诊疗指南 2026（表格 OCR 重建） | `csco-breast-cancer-2026-table-ocr-r1` | `active` | 1,071 | `primary_guideline` |

当前数据库实测：4 个 guideline、8 个 version、3,637 个 raw chunk、3,637 个索引节点、2,024 条版本差异和 7,326 条追加式审计事件。节点总数包含 CACA、NCCN 和 CSCO 的历史/候选版本。

默认检索只包含 `active`，因此目前返回 CACA r3 和 CSCO 表格 OCR r1。原 CACA 2026 已变为 `superseded`，CACA r2 仍是保留但不批准的中间审计记录。NCCN r2、Gradishar 和 OncoToolkit 必须分别审核，互不覆盖；旧 NCCN 草稿保留用于版本对比，不应批准。Gradishar 不是 NCCN V6 的历史版本，OncoToolkit 始终是 `secondary_summary`。

## 已验证能力

- CACA r3 的中文与英文 HER2 查询均命中 CACA 原文证据，并返回 `raw_chunk_id` 和 PDF 页码。
- CACA r3 托管 JSONL 为 324 条，SHA-256 为 `983e26188f574a8200f367347175e2bfb79c4d430ffd0b26fc2a5187fc62d1f5`。
- CACA r3 快照可在固定 revision 的本地 BGE-M3 模式下重新打开并校验 manifest。
- CACA r3 已由审核人 `dongy` 批准为 `active`，原 CACA 2026 已原子更新为 `superseded`。
- CSCO 表格 OCR r1 已由审核人 `codex-user-requested` 批准为 `active`；版本包含 1,071 个节点、92 个表格父块和 617 个表格行块。
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

1. CACA r3 已完成审批；复核默认检索只解析到 `caca-breast-cancer-2026-r3`，不要批准 r2。
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

已获授权的公开预发布 Release `v0.2.0-internal-test` 已重新打包并发布当前运行时数据。数据包包含全部 8 个版本索引、SQLite、托管源文件、staging JSONL 和校验 manifest，不包含 BGE-M3 模型；下载者需按 README 校验 SHA-256 后解压到项目根目录。

完整命令和停止条件见 [本地运行手册](local-runbook.md)。
