# 多指南双语多样性检索设计

## 目标

在不改变 `POST /search` 请求和响应契约的前提下，提升 CSCO、CACA、NCCN 三份本地乳腺癌指南的中文检索、英文回溯和多指南覆盖效果。重点解决中文 BM25 无有效词项、BM25 零分封面进入 RRF、以及查询 `复发转移 疗法` 只命中一个词或一个指南的问题。

## 已确认的边界

- 只使用本地已导入的 CSCO、CACA、NCCN 活跃版本内容生成词典，不调用外部翻译 API，不新增凭据要求。
- 保留源文档原文和现有证据引用；词典只用于扩展检索查询，不替换返回的 `evidence[].text`。
- API 继续接受 `query`、`guideline_ids`、`version_ids`、`language`、`top_k`、`use_bm25`，不增加必填字段。
- 所有生成的词典、统计和缓存写入 `D:\coding\knowledgebase\data` 下，模型和临时文件不写入 C 盘。
- active 版本按现有注册表解析；显式历史版本仍可检索，draft 仍拒绝检索。

## 方案选择

### 方案 A：本地词典 + 查询扩展 + 中文字符 n-gram BM25（采用）

新增一个纯 Python 的本地术语模块：从每个可搜索版本的 raw chunk 读取中英文术语候选，依据中英文共现、规范化别名和有限的内置术语种子生成 `data/retrieval/bilingual_terms.json`。查询时使用最长匹配和分隔符切分，将中文片段保留并追加词典中的英文别名；BM25 使用中文字符二元组/三元组以及英文词、数字和连字符词的确定性 tokenizer。该方案无网络依赖，能覆盖 OCR 中出现的新术语，并且易于审计。

### 方案 B：只用外部机器翻译后做向量检索

中文查询先调用翻译服务再检索。实现简单但需要凭据、网络可用性和成本控制，翻译结果不可稳定复现，也不能解决 BM25 零分候选问题。不采用。

### 方案 C：引入中文分词模型和独立检索服务

使用 jieba/分词模型加 Qdrant 或 Elasticsearch。中文召回可能更强，但增加依赖、服务和引迁移成本；当前三本指南规模不需要。不采用。

## 组件与接口

### `app/terminology.py`

- `tokenize_query(text: str) -> tuple[str, ...]`：把连续中文切成字符 2-gram/3-gram，同时保留英文单词、数字、药名缩写及连字符词；空白、标点只作为分隔。
- `expand_query(query: str, terms: Mapping[str, tuple[str, ...]]) -> str`：按最长中文短语匹配，分段处理多个空白/标点分隔的关键词，保留原查询并追加去重后的英文别名。
- `build_bilingual_dictionary(chunks: Iterable[RawChunkRecord], seed_terms: Mapping[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]`：从本地 raw chunk 统计中英文共现和已知种子，输出确定性排序的别名表。
- `load_or_build_dictionary(...)`：从 `data/retrieval/bilingual_terms.json` 读取；输入内容指纹变化时重新构建并原子替换，文件包含 schema 版本、源版本 ID、条目数和 SHA-256。

词典生成只保留有明确证据的别名：内置乳腺肿瘤术语种子覆盖 `复发转移`、`疗法`、`治疗`、`手术`、常见 HER2 药物和 `ADC` 等；其余候选必须在同一 chunk 或相邻 chunk 中与中英文形式共现。词典值限制为短别名列表，避免把整段文本当成翻译。

### `app/retrieval.py`

- `bm25_tokenizer(text: str) -> list[str]`：传入 `BM25Retriever.from_defaults(tokenizer=...)`，统一处理中文、英文、数字和连字符。
- `filter_positive_bm25(items: Sequence[NodeWithScore]) -> list[NodeWithScore]`：丢弃原始 BM25 分数 `<= 0` 或非有限值的候选，并保持稳定排序。
- `rrf_merge(...)`：只对过滤后的 BM25 排名和向量排名融合；RRF 分数仍是排序分，不把 BM25 原始分数伪装成证据置信度。
- `ensure_guideline_coverage(items, candidates_by_guideline, resolved_guideline_ids, top_k)`：当 `top_k >=` 解析出的指南数时，先为每个指南保留一个最高融合分候选，再按全局融合顺序补足剩余槽位；无法命中的指南不制造空证据。

检索流程为：解析版本 -> 构造扩展查询 -> 各版本向量检索和 BM25 正分检索 -> 版本内 RRF -> 跨版本全局排序 -> 指南最低覆盖约束 -> 截取 `top_k`。向量检索继续使用原始 query 与扩展 query 中得分较高的一组，默认合并两次向量候选后去重，以避免扩展词压过中文原词。

## 双语查询行为

输入 `复发转移 疗法` 时，先按空格分成 `复发转移`、`疗法`，再对每段做最长匹配；扩展结果示例为：

```text
复发转移 疗法 recurrent metastatic breast cancer therapy treatment
```

原中文始终参与检索，英文别名仅追加，不写回证据文本。用户输入英文时，如果词典有中文别名，则对称追加中文，支持 `recurrent metastatic therapy` 回溯中文 CSCO/CACA 内容。

## 数据流与缓存

```text
active/specified versions
        |
        v
raw_chunk 文本 --构建/读取--> data/retrieval/bilingual_terms.json
        |
        v
原查询 --最长匹配扩展--> 中文原词 + 英文别名
        |
        +--> vector(original + expanded)
        +--> BM25(custom tokenizer, score > 0)
                         |
                         v
                 RRF + guideline coverage
                         |
                         v
                    evidence JSON
```

词典缓存按源版本和 raw chunk 内容哈希失效；重建采用临时文件加 `replace`，服务重启后可直接读取。词典文件不参与向量索引，避免改变现有快照完整性；检索升级只修改应用层排序和查询构造。

## 错误处理与兼容性

- BM25 插件不可导入时保持 `retrieval_modes=("vector",)`，查询扩展仍可用于向量检索。
- 词典缺失、损坏或无条目时回退到原始 query，不阻断检索；构建错误写入日志并返回可用的向量结果。
- `top_k < 指南数` 时不强行覆盖所有指南；`top_k >= 指南数` 且某指南没有正分/向量候选时只返回实际命中的指南。
- `language`、`guideline_ids`、`version_ids` 过滤语义不变；过滤后的指南集合才参与覆盖约束。

## 测试与验收

- 单元测试：中文 n-gram、英文/数字/连字符保留、最长匹配、多个分隔关键词、词典确定性和缓存失效。
- 检索回归：BM25 分数为 0 的封面不进入 RRF；正分 BM25 仍可召回；RRF 去重结果稳定。
- 覆盖约束：三指南 `top_k=3` 各返回一条；`top_k=2` 不强行补第三指南；过滤到单指南时只返回该指南。
- 双语集成：中文 `复发转移` 能召回英文 NCCN 相关内容，英文术语能召回中文指南；`复发转移 疗法` 的每个关键词均影响候选排序。
- 真实数据验收：在本地三个 active 版本上运行固定查询，确认不再出现无关封面页，并记录各指南命中数和词典摘要到 `data/reports/retrieval-multilingual-r1.json`。

## 非目标

- 不翻译或改写证据文本，不新增 LLM 生成答案。
- 不重建已有向量快照，不删除 `evidence_cards/` 或其他用户文件。
- 不保证每个中文词都有人工认可的英文翻译；无证据别名时仅使用原文和 n-gram。
