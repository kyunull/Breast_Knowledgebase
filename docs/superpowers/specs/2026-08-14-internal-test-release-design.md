# 团队内部测试版发布设计

## 目标

将 Breast Knowledgebase 作为团队内部测试版本发布到私有 GitHub 仓库。代码、配置、测试和文档进入 Git；真实资料与现有知识库状态作为同一仓库的私有 Release 附件交付；BGE-M3 模型和 Python 依赖由目标设备联网下载。

## 发布边界

Git 仓库包含：

- `app/`、`scripts/`、`config/`、`tests/` 和 `docs/`
- `pyproject.toml`、`.gitignore` 和根目录 `README.md`
- 不包含 `.venv/`、Python 缓存、pytest 缓存、运行日志、临时文件或模型缓存

私有 GitHub Release 附件包含：

- `data/registry/knowledge.sqlite3`
- `data/llama_indices/` 下四个已验证的 LlamaIndex 快照
- `data/managed_sources/` 下四份真实 PDF/HTML 及四份 JSONL 受管副本
- `data/reports/source-contract-report.json`
- 数据包内的 `DATA_MANIFEST.json`，记录每个文件的相对路径、字节数和 SHA-256

Release 附件不包含：

- `data/model_cache/`
- `data/vendor_wheels/`
- `data/runtime_cache/`
- SQLite 的临时 WAL/SHM 文件

## 交付结构

代码仓库首个内部测试版本使用 `v0.1.0-internal-test` 标签。对应 Release 附件命名为：

```text
breast-knowledgebase-data-v0.1.0-internal-test.zip
breast-knowledgebase-data-v0.1.0-internal-test.zip.sha256
```

数据压缩包解压后以 `data/` 为顶层目录。团队成员将其解压到 `D:\coding\knowledgebase`，得到与当前运行时一致的目录结构。

## 目标设备安装流程

内部测试目标为 Windows x64 和 Python 3.12。当前代码仍要求项目位于 `D:\coding\knowledgebase`，README 必须将此限制放在安装步骤之前。

目标设备执行以下流程：

1. 将私有仓库克隆到 `D:\coding\knowledgebase`。
2. 从对应的私有 GitHub Release 下载数据包及 SHA-256 文件。
3. 校验数据包 SHA-256，再解压到项目根目录。
4. 在项目目录创建 `.venv`，从 PyPI 在线安装 `.[dev]`。
5. 设置模型名、固定 revision、CPU、batch size 和最大序列长度。
6. 首次运行时允许 Hugging Face 下载 pinned BGE-M3 到 `data/model_cache`。
7. 下载成功后设置 `KB_MODEL_LOCAL_FILES_ONLY=true`，验证四个快照均可离线重开。
8. 运行完整测试、真实源契约测试和中英文检索烟测。
9. 仅在 `127.0.0.1:8000` 启动 Uvicorn。

## README 内容

根目录 README 面向第一次接触项目的团队成员，按以下顺序编写：

1. 项目定位和非临床结论边界
2. 当前数据集与版本状态
3. 系统要求和固定 D 盘路径限制
4. 克隆、数据包下载与 SHA-256 校验
5. Python 3.12 虚拟环境和在线依赖安装
6. pinned BGE-M3 首次下载与后续离线设置
7. 快照验证、自动化测试与真实源契约测试
8. 服务启动和中英文查询示例
9. draft 审批、版本差异和审计说明
10. 常见故障与停止条件
11. 安全与资料使用范围

README 不承诺 draft 可通过 `/search` 检索；它必须明确当前接口只允许 active 或 superseded 版本参与检索。README 也必须明确 API 无身份认证，只能用于受控设备上的本地测试。

## 数据包生成

发布前停止 Uvicorn，确认没有写入中的导入或审批操作。对 SQLite 执行 `PRAGMA wal_checkpoint(TRUNCATE)`，然后只从白名单目录复制文件到独立 staging 目录。不得直接压缩整个 `data/`，避免包含模型日志、pip 缓存或测试临时数据库。

生成器为每个文件计算 SHA-256，写入确定性排序的 `DATA_MANIFEST.json`。ZIP 使用固定的相对目录结构，不写入 C 盘。发布包生成后重新解压到 D 盘临时验收目录，验证 manifest 中的文件集合、字节数和哈希全部一致。

## 缓存策略

GitHub 仓库和 Release 数据包均不携带 BGE-M3。目标设备首次联网下载：

```text
model_name: BAAI/bge-m3
revision: 5617a9f61b028005a4858fdac845db406aefb181
cache: D:\coding\knowledgebase\data\model_cache
```

下载完成后，正常启动命令必须设置 `KB_MODEL_LOCAL_FILES_ONLY=true`。该策略避免把当前约 6.37 GiB 的 Hugging Face 缓存提交到 GitHub，同时保持快照模型元数据可重复验证。

## GitHub 发布流程

1. 在 `main` 上提交 README、发布脚本和现有项目源文件。
2. 推送到 `https://github.com/kyunull/Breast_Knowledgebase.git`。
3. 创建 annotated tag `v0.1.0-internal-test` 并推送。
4. 在私有仓库创建同名 GitHub Release。
5. 上传数据 ZIP 和 `.sha256` 文件。
6. 使用另一个有仓库权限的团队账号完成克隆、Release 下载和启动验收。

当前设备没有 GitHub CLI。代码使用 Git 推送；Release 可通过 GitHub 网页创建，或在安装并认证 GitHub CLI 后自动上传。不得把访问令牌写入仓库、README、脚本或命令输出日志。

## 验收标准

- Git 工作树不跟踪 `data/`、`.venv/`、缓存或日志。
- README 中的命令可在新的 Windows x64 测试设备上逐条执行。
- 数据包只包含白名单文件，外层 SHA-256 与包内 manifest 均校验通过。
- 在线安装后 `pip check` 无错误。
- 完整测试结果为 `79 passed, 1 skipped`；启用 `KB_REAL_SOURCE_TESTS=1` 后真实源契约测试为 `2 passed`。
- 四个快照在 pinned BGE-M3 下验证通过。
- 中文和英文 HER2 查询只解析到当前 active 的 CACA 2026，并返回原文、`raw_chunk_id`、来源等级和页码引用。
- 显式检索 draft 返回 422，不发生静默回退。
- 服务只监听 `127.0.0.1`。

## 非目标

- 不在本次内部测试发布中实现任意安装路径支持。
- 不提供 Docker 镜像、Windows 安装器或公网服务。
- 不增加 API 身份认证、TLS 或多用户权限管理。
- 不把 BGE-M3、wheelhouse 或虚拟环境上传到 GitHub。
