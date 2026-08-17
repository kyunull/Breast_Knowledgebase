# 表格感知 OCR 工作流

本流程用于 CACA、NCCN 等 PDF 的表格重建。最终检索输入只有 table-aware JSONL；不生成 HTML 表格。原 PDF 和基线 JSONL 保持只读，所有 PNG、OCR 原始响应、报告、托管源和索引写入项目 `data` 目录。

## 处理顺序

1. 从基线 JSONL 读取 `block_type=table` 的页序号和表格上下文。
2. 仅在这些页面调用 PyMuPDF `page.find_tables()`，用基线表格文本选择候选框，排除流程图和表单误检。
3. 以 2 倍分辨率渲染完整页面为 `source-page-NNN.png`。
4. 调用腾讯云 `RecognizeTableAccurateOCR`，固定 `UseNewModel=true`，逐页原子保存原始 JSON。
5. 只接受腾讯 `Type=1/2` 表格。整页失败时将候选框以 3 倍分辨率裁剪后重试。
6. 若整页和裁剪都没有 `Type=1/2`，使用同一候选框的 PyMuPDF 矢量单元格作为审计回退；绝不把腾讯 `Type=0` 当表格。
7. 每个物理表格生成一个父 chunk，每个物理行生成一个带表头限定的 `table_row` chunk；合并单元格内容传播到其覆盖行。
8. 非表格记录原样保留并比较顺序及 SHA-256，重复 ID、非法 span、几何歧义或缺失候选均停止处理。
9. 通过 `GuidelineService` 导入不可变快照，运行 manifest 验证和显式版本检索后批准为 `active`。

## 腾讯凭据

凭据只从当前进程或 Windows 用户环境变量读取：

```text
TENCENTCLOUD_SECRET_ID
TENCENTCLOUD_SECRET_KEY
```

SecretId/SecretKey 不得写入命令参数、JSON、SQLite、manifest、日志或 Git。原始 OCR JSON 不包含凭据。BGE-M3 模型也不得进入数据包。

## 运行命令

安装固定版本依赖到项目虚拟环境：

```powershell
& .\.venv\Scripts\python.exe -m pip install `
  --cache-dir .\data\runtime_cache\pip_cache `
  "pymupdf==1.28.2"
```

准备候选页并渲染 PNG：

```powershell
& .\.venv\Scripts\python.exe -m scripts.rebuild_pdf_tables prepare `
  --pdf '<源 PDF 绝对路径>' `
  --baseline-jsonl '<基线 JSONL 绝对路径>' `
  --output-root '.\data\staging\table_ocr\<document>'
```

逐页 OCR 支持断点续跑；已有有效响应不会覆盖：

```powershell
& .\.venv\Scripts\python.exe -m scripts.rebuild_pdf_tables ocr `
  --output-root '.\data\staging\table_ocr\<document>' `
  --page-number 72

& .\.venv\Scripts\python.exe -m scripts.rebuild_pdf_tables ocr-crops `
  --output-root '.\data\staging\table_ocr\<document>' `
  --page-number 72
```

重建并验证 JSONL：

```powershell
& .\.venv\Scripts\python.exe -m scripts.rebuild_pdf_tables rebuild `
  --baseline-jsonl '<基线 JSONL 绝对路径>' `
  --output-root '.\data\staging\table_ocr\<document>' `
  --output-jsonl '.\data\staging\<document>_table_aware.jsonl' `
  --report '.\data\reports\<document>-table-ocr-r1.json'
```

本次结果：CACA 为 18 个候选页、32 个父表格、175 个行 chunk、0 个 PyMuPDF 回退；NCCN 为 52 个候选页、77 个父表格、687 个行 chunk、46 个 PyMuPDF 矢量回退。

## CACA 英文 OCR 间距规范化

CACA 的非表格 OCR 文本可能把英文术语拆成孤立字母，例如 `m a x i m u m i n t e n s i t y`。不要用删除所有英文字母空格的正则；作者首字母（`JOHNSTON S R D`）和图标签（`A B C D E`）必须保留。使用显式、可审计的术语规则生成新 JSONL，原 r1 文件和 active 快照保持不变：

```powershell
& .\.venv\Scripts\python.exe -m scripts.normalize_caca_ocr_spacing `
  --input-jsonl '.\data\staging\caca_breast_2026_table_aware.jsonl' `
  --output-jsonl '.\data\staging\caca_breast_2026_table_aware_r2.jsonl' `
  --report '.\data\reports\caca-ocr-spacing-r2.json'
```

报告必须记录输入/输出 SHA-256、受影响记录数、规则替换数和残留小写拆字数；本次为 499 条记录、13 条受影响、16 次替换、0 条残留。用 `config/caca_2026_table_ocr_r2.json` 导入并验证新快照后再审批；规范化后的 JSONL 不改变表格父子结构或非文本字段。

## 导入与验证

```powershell
$env:KB_EMBEDDING_PROVIDER = 'local'
$env:KB_MODEL_LOCAL_FILES_ONLY = 'true'
$env:KB_MODEL_DEVICE = 'cpu'

& .\.venv\Scripts\python.exe -m scripts.ingest_guideline `
  --config .\config\caca_2026_table_ocr_r2.json
& .\.venv\Scripts\python.exe -m scripts.ingest_guideline `
  --config .\config\nccn_v6_2026_table_ocr_r1.json

& .\.venv\Scripts\python.exe -m scripts.verify_snapshot `
  --version-id caca-breast-cancer-2026-table-ocr-r2
& .\.venv\Scripts\python.exe -m scripts.verify_snapshot `
  --version-id nccn-breast-cancer-6-2026-table-ocr-r1
```

真实源契约测试：

```powershell
$env:KB_TABLE_OCR_REAL_SOURCE_TESTS = '1'
& .\.venv\Scripts\python.exe -m pytest `
  .\tests\test_table_ocr_real_sources.py -q
```
