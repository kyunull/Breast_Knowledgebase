# LlamaIndex 版本化双语指南知识库设计

## 目标

以四份乳腺癌指南的既有 JSONL 分块为输入，建立本地、可审计、可版本管理的中英文循证检索服务。检索结果只返回可核验的原文证据与完整出处，不在首版生成临床结论。

## 已确认的边界

- 知识库与检索框架：LlamaIndex；首版不引入 LangChain。
- 服务接口：本地 FastAPI，不建设 Web UI。
- 运行位置：项目、虚拟环境、受管源文件、索引、数据库、模型缓存、临时文件全部位于 `D:\coding\knowledgebase`；配置不得把运行数据定向到 C 盘或项目目录之外。
- 输入：源 PDF/HTML 的只读副本和四份 JSONL 分块；源文件原件不被修改。
- 生命周期：`draft` -> `active` -> `superseded` / `archived`。导入仅创建 draft；由一名本地审阅人批准后才切换 active；旧版本保留可检索和可比较。
- 追溯：每条证据必须返回指南、版本、语言、来源级别、原始文件名与 SHA-256、原始 chunk、页码/章节、文本哈希及摘录。
- 语言：保留源语言原文；首版不机器翻译、不用 LLM 编造中文或英文引文。

## 方案选择

### 方案 A：LlamaIndex 检索层 + SQLite 治理层（采用）

LlamaIndex 负责 `Document` / `TextNode`、清洗和切分、嵌入、`VectorStoreIndex`、持久化和检索。SQLite 只保存不可替代的业务事实：指南、版本状态、源文件、审批、审计事件与版本差异。

优点是索引和治理职责清晰，版本快照可复现，首版不需要独立向量数据库服务。缺点是跨版本检索需要加载多个本地索引并在应用层合并结果；当前四份指南规模下可接受。

### 方案 B：LlamaIndex + Qdrant

适合大量指南、多人并发和较高检索吞吐，但引入长期运行的 Qdrant 服务与备份运维。当前规模不采用，保留为未来替换向量存储的接口方向。

### 方案 C：仅使用 LlamaIndex 本地存储

部署最少，但无法可靠表达审批、审计和版本差异，不满足本项目核心治理需求，因此不采用。

## 架构与数据流

```text
外部 PDF / HTML + JSONL（只读）
              |
              v
受管副本与内容 SHA-256
              |
              v
SQLite 版本注册（draft） + LlamaIndex IngestionPipeline
              |
              v
每个 guideline_id/version_id 的独立不可变索引快照
              |
       校验通过、人工批准
              |
              v
SQLite 原子切换 active 指针，旧版本标记 superseded
              |
              v
API 先解析允许的版本，再加载相应 LlamaIndex 索引并融合证据
```

索引快照位于 `data/llama_indices/<guideline_id>/<version_id>/`。draft 快照完整落盘和校验后才能被批准；active 或 superseded 快照永不原地更新或删除。版本切换只更新 SQLite 中的状态，确保失败时旧 active 仍保持可用。

## 节点、索引与检索

1. JSONL 的每个原始 chunk 先作为不可变记录保存；异常长 chunk 可以派生多个索引节点，但节点始终指回原 chunk。
2. 节点 ID 采用稳定、可复现的 `<guideline_id>:<version_id>:<raw_chunk_id>:<fragment_ordinal>`；`ref_doc_id` 绑定到版本化的原始 chunk。
3. 每个节点包含 `guideline_id`、`version_id`、`version_label`、`language`、`authority_level`、`source_file_name`、`source_sha256`、`source_kind`、`raw_chunk_id`、页码、章节、原文字符位置、`content_sha256` 和规范化器版本等 metadata。
4. 使用本地 `HuggingFaceEmbedding` 加载 BAAI/bge-m3，CPU 首版默认批量为 4、最大序列长度为 512；下载和缓存目录固定为 `data/model_cache`。
5. 首版以 `VectorStoreIndex` 为基线。BM25 和 RRF 融合作为受控增强：若所固定版本的 LlamaIndex BM25 集成可用，则启用；否则保留向量检索和同一响应结构，不以不稳定插件阻断交付。
6. 检索先由 SQLite 解析默认 active 或显式历史版本，再对对应索引检索；多索引的结果在应用层按确定性 RRF 合并、去重并截取。不得由 LLM 自动选择版本或改写证据。

## 版本、审批、审计与差异

SQLite 是唯一的版本真相来源：`guideline`、`document_version`、`source_file`、`raw_chunk`、`audit_event`、`version_diff`。LlamaIndex 的 docstore 哈希仅用于导入重复检测，不能替代审批流或审计。

导入记录源文件 SHA-256、受管副本路径、导入者、时间和原始 chunk 哈希。批准动作在一个立即事务内校验 draft 索引清单、将现 active 标记为 superseded、将目标 draft 标记 active，并追加不可修改的审计事件。差异按原始 chunk/规范化文本指纹计算为 added、removed、modified、unchanged，并可定位到两版本的证据片段。

## API 契约

- `POST /ingest`：登记源文件、JSONL 和版本，构建并校验 draft 快照。
- `POST /versions/{version_id}/approve`：记录审阅人并原子激活版本。
- `POST /search`：接受查询、可选指南/版本/语言过滤，返回排序证据列表和引用元数据。
- `GET /guidelines`：返回指南及其版本状态。
- `GET /versions/{version_id}/diff`：返回相邻或指定版本之间的差异。
- `GET /audit`：按实体和时间查询追加式审计记录。

响应中的证据字段固定包含：`text`、`score`、`language`、`citation`、`guideline`、`version`、`authority_level`、`raw_chunk_id`、`source_file`、`source_sha256`、`page_or_section`。`citation` 是基于保存 metadata 生成的展示字段，不得替换原始出处。

## 异常处理与安全边界

- 缺失文件、SHA-256 不一致、非法 JSONL、缺少必填定位信息、不可加载模型和索引清单不完整，均使导入失败并记录审计事件；失败版本不得成为 active。
- 任何项目设置中来自环境变量的路径都必须解析后验证为 `D:\coding\knowledgebase` 的子路径；不满足时启动或请求失败。
- 搜索不到结果返回空证据数组及过滤范围，不返回无出处的推断。
- 标记为 `secondary_summary` 的 OncoToolkit 结果必须保留来源等级，不能伪装为 NCCN 原始指南。

## 测试与验收

- 单元测试不下载模型，使用确定性测试 embedding；覆盖 JSONL 规范化、稳定节点 ID、元数据、路径约束和引用组装。
- 集成测试覆盖 LlamaIndex 建索引、持久化、重新加载和中英文查询；验证返回节点能回溯到原始 chunk 和页码/章节。
- 工作流测试覆盖 draft 不进入默认检索、批准原子切换、旧 active 变 superseded、历史版本显式检索、审计不可更新/删除和版本差异。
- 验收在给定四份 JSONL 上完成，并由一组人工定义的中英文查询检查引用、来源等级和版本边界。

## 迁移原则

现有 `app/database.py` 的早期 SQLite/自定义向量雏形不作为最终索引实现。实施时先用测试锁定仍需保留的治理表与审计规则，再删除或替换已被 LlamaIndex 职责取代的 FTS、嵌入 blob 和自定义向量逻辑；不会删除源数据或已生成的审计材料。
