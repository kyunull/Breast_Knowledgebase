# 初始资料导入状态

更新时间：2026-08-14

本项目已用用户提供的四份源文件和对应 JSONL 建立版本独立的 LlamaIndex 快照。源文件没有被修改；可写数据均位于 D:\coding\knowledgebase\data。

## 当前可检索范围

| 指南 | 版本 ID | 状态 | 分块和节点数 | 来源等级 |
| --- | --- | --- | --- | --- |
| CACA 乳腺癌 | caca-breast-cancer-2026 | active | 270 / 270 | primary_guideline |
| CACA 乳腺癌（中间记录） | caca-breast-cancer-2026-r2 | draft | 324 / 324 | primary_guideline |
| CACA 乳腺癌（审核候选） | caca-breast-cancer-2026-r3 | draft | 324 / 324 | primary_guideline |
| Gradishar NCCN Breast Cancer | gradishar-nccn-breast-cancer-4-2026 | draft | 9 / 9 | primary_publication |
| NCCN Breast Cancer | nccn-breast-cancer-6-2026 | draft | 786 / 786 | primary_guideline |
| OncoToolkit HER2 Breast Cancer | oncotoolkit-her2-breast-cancer-2026 | draft | 31 / 31 | secondary_summary |

默认检索只包含 active 版本，因此现在仍只检索原 CACA 2026。CACA r2 是上游文件变化期间生成的不可变中间审计记录，保留但不应批准；r3 是唯一待人工审核的 CACA 新候选。其他三个 draft 在人工复核并批准前也不会出现在默认检索结果中。Gradishar 是独立的 JNCCN 精选发表，不是 NCCN V6 的历史版本。OncoToolkit 保持 secondary_summary 标记，不能作为指南原文替代。

## 已验证的能力

- 在 r3 草稿快照上，中文查询 HER2 阳性乳腺癌治疗 与英文查询 HER2-positive breast cancer treatment 的第一命中均为 caca_2026_0160_p1，返回 primary_guideline 与 PDF 页序号 44-45。
- r3 的托管 JSONL 为 324 条、578,832 字节，SHA-256 为 983e26188f574a8200f367347175e2bfb79c4d430ffd0b26fc2a5187fc62d1f5；与当前上游文件一致。
- r3 快照已在本地模型模式下重新打开并校验 manifest；manifest SHA-256 为 3dba69364f02c4fc370bc2a85c98d8ba63eff55cc864a363181c463b0facada0。
- SQLite 中有 4 个指南、6 个版本、1,744 条原始分块、1,744 个节点、882 条版本差异记录和 3,525 条追加式审计事件。
- r3 相对原 active CACA 的差异为新增 171、修改 142、删除 117、不变 11，共 441 条。r3 相对 r2 没有新增或删除，只有 caca_2026_0122、caca_2026_0239、caca_2026_0255、caca_2026_0256 四条文本变化。
- 版本审批会重新校验快照；新 active 版本会原子地将同一指南的旧 active 版本转为 superseded。

## 明早的审核步骤

1. 审核 CACA r3 的 324 条托管 JSONL、PDF 引用、版本差异和抽样查询；不要审批 r2。
2. 启动本地 API，确认默认检索仍只返回原 CACA 2026 的证据，显式查询 r3 draft 返回 422。
3. 若确认 r3 可投入默认检索，以实际审核人标识审批；审批后原 CACA active 会变为 superseded：

    $body = @{ reviewer = 'your-reviewer-id' } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/versions/caca-breast-cancer-2026-r3/approve -ContentType application/json -Body $body

4. 之后再分别处理 NCCN、Gradishar 和 OncoToolkit；最新一次检查时，上游 NCCN JSONL 为 822 条而已导入 draft 为 786 条，上游 Gradishar 为 8 条而已导入 draft 为 9 条。两者必须先重新导入新版本，不能直接把当前 draft 当成最新上游资料批准。OncoToolkit 的 31 条及哈希未变化。

每个指南在首次审批时是彼此独立的；四份资料不会因审批其中一份而覆盖另一份。完整命令和停止条件见 local-runbook.md。

## 验证记录

- 严格测试基线：79 passed，1 skipped。
- CACA r3 单源契约：324 条、必填字段完整、chunk_id 唯一、锁定哈希一致。
- 全量真实源契约暂不通过：CACA 已同步到 324 条；最新检查中，上游 NCCN 为 822 条（已导入 786），上游 Gradishar 为 8 条（已导入 9）。等待两者分别重建。
- 模型固定为 BAAI/bge-m3 的 revision 5617a9f61b028005a4858fdac845db406aefb181，并支持 KB_MODEL_LOCAL_FILES_ONLY=true 的离线加载。
- 快照 manifest 前缀：CACA active 21a103c6d9af；CACA r2 afaa6dd47353；CACA r3 3dba69364f02；Gradishar ad68adccf008；NCCN ca78d7d299cc；OncoToolkit 01f7e5656c6d。
