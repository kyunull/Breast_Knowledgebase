# 初始资料导入状态

更新时间：2026-08-14

本项目已用四份真实资料和对应 JSONL 建立版本独立的 LlamaIndex 快照。项目可以移动到任意绝对目录；可写数据位于当前项目的 `data` 子目录。源文件未被修改，SQLite 中的 `original_path` 仅作为导入来源审计记录。

## 当前版本

| 指南 | 版本 ID | 状态 | 分块/节点 | 来源等级 |
| --- | --- | --- | ---: | --- |
| CACA 乳腺癌指南 | `caca-breast-cancer-2026` | `active` | 270 | `primary_guideline` |
| CACA 中间审计版本 | `caca-breast-cancer-2026-r2` | `draft` | 324 | `primary_guideline` |
| CACA 当前审核候选 | `caca-breast-cancer-2026-r3` | `draft` | 324 | `primary_guideline` |
| Gradishar NCCN Breast Cancer | `gradishar-nccn-breast-cancer-4-2026` | `draft` | 9 | `primary_publication` |
| NCCN Breast Cancer | `nccn-breast-cancer-6-2026` | `draft` | 786 | `primary_guideline` |
| OncoToolkit HER2 Breast Cancer | `oncotoolkit-her2-breast-cancer-2026` | `draft` | 31 | `secondary_summary` |

当前数据库实测：4 个 guideline、6 个 version、1,744 个 raw chunk、1,744 个索引节点、882 条版本差异和 3,525 条追加式审计事件。总数包含三个 CACA 历史/候选版本。

默认检索只包含 `active`，因此目前仍只返回原 CACA 2026。CACA r2 是不可变的中间审计记录，保留但不批准。CACA r3 是唯一可考虑替换当前 CACA active 的候选。NCCN、Gradishar 和 OncoToolkit 必须分别审核，互不覆盖；Gradishar 不是 NCCN V6 的历史版本，OncoToolkit 始终是 `secondary_summary`。

## 已验证能力

- CACA r3 的中文与英文 HER2 查询均命中 CACA 原文证据，并返回 `raw_chunk_id` 和 PDF 页码。
- CACA r3 托管 JSONL 为 324 条，SHA-256 为 `983e26188f574a8200f367347175e2bfb79c4d430ffd0b26fc2a5187fc62d1f5`。
- CACA r3 快照可在固定 revision 的本地 BGE-M3 模式下重新打开并校验 manifest。
- 新导入的托管源和快照路径以项目相对路径保存；旧绝对路径会在文件完整时事务迁移。
- 本地模式固定 `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`。
- 远程模式支持 OpenAI-compatible `/embeddings`，并校验 provider、模型名、维度、归一化、响应数量和响应顺序。
- API key 不进入 SQLite、manifest、审计 payload、日志或异常消息。
- 审批会重新校验快照，并原子地把同指南旧 `active` 更新为 `superseded`。

## 审核顺序

1. 审核 CACA r3 的 324 条托管 JSONL、PDF 引用、版本差异和抽样查询；不要批准 r2。
2. 启动 API，确认默认检索仍只返回原 CACA 2026，显式检索 r3 draft 返回 HTTP 422。
3. 若 r3 审核通过，以真实审核人 ID 批准；批准后原 CACA active 会变为 `superseded`。
4. 分别处理 NCCN、Gradishar 和 OncoToolkit。上游 NCCN/Gradishar 数量与当前 draft 不一致时，先导入新版本，不直接批准旧 draft。

批准示例：

```powershell
$body = @{ reviewer = 'team-reviewer-id' } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/versions/caca-breast-cancer-2026-r3/approve `
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
- 最新检查中，上游 NCCN 为 822 条而当前 draft 为 786 条；上游 Gradishar 为 8 条而当前 draft 为 9 条；OncoToolkit 31 条及哈希未变化。

完整命令和停止条件见 [本地运行手册](local-runbook.md)。
