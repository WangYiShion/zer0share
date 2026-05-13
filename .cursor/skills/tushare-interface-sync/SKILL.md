---
name: tushare-interface-sync
description: 将新的 Tushare Pro 数据接口纳入 zer0share 同步、存储、LocalPro 查询、CLI、调度、文档和测试体系。Use when the user asks to add, sync, 接入, 纳入同步范畴, or implement a new Tushare data interface.
---

# Tushare Interface Sync

## 适用场景

当用户要求“将某个 Tushare 数据接口纳入同步范畴”“接入某个 Tushare 接口”“新增某个 Tushare 数据同步”时，使用本 Skill。

本 Skill 基于本仓库已有的 `stk_limit`、`stock_st`、`daily_basic` 与 `suspend_d` 接入过程整理，目标是让新增接口同时具备：

- Tushare 拉取与统一限流；
- Parquet 本地存储；
- 增量同步；
- `LocalPro` 本地查询；
- CLI 与可选调度；
- 文档和测试。

## 必读资料

开始编码前必须先读：

- `docs/tushare-data-expansion-design.md`（含 **「配置、CLI 与调度 · `pipeline.log` 全日成功与精简日志」**：接新接口时改动 `sync --all` / 调度器与日志的必选项）
- `docs/tushare-interface-permissions.json`
- 对应接口在 `tushare_docs_md/` 下的叶子 `data.md`

权限判断优先使用 `docs/tushare-interface-permissions.json`。本项目当前按“用户 8000 积分、未单独购买数据包”理解：积分门槛 `<= 8000` 且不要求单独购买的接口可接入；需要单独购买的数据接口默认不可接入，除非用户明确说明已购买。

`tushare_docs_md/` 中只有“不含子文件夹的目录里的 `data.md`”才视为最终接口文档。父级目录的 `data.md` 常是专题概览，不要直接当成接口字段来源。

## 开发流程

### 1. 确认接口事实

先定位并核对：

- Tushare 接口名，例如 `stk_limit`、`stock_st`、`daily_basic`、`suspend_d`；
- 文档标题、用途、更新时间；
- 输入参数，重点看是否支持 `trade_date`、`start_date`、`end_date`、`ts_code`；
- 输出字段，按文档顺序建立字段常量；
- 单次返回上限，决定是否分页；
- 权限门槛和是否需要单独购买；
- 适合的同步类型：快照型、交易日增量型、公告日/报告期型、专题型。

若权限不足或需要单独购买，先向用户说明，不要直接实现。

### 2. 选择同步策略

优先复用已有模式：

- 快照型：参考 `stock_basic`，写入 `data/<table>/data.parquet`，每次全量覆盖。
- 交易日增量型：参考 `stk_limit`、`stock_st` 或 `daily_basic`，按 SSE 交易日遍历，写入 `data/<table>/date=YYYYMMDD/data.parquet`。
- 报告期或公告日型：先按设计文档确定分区键，再实现，不要硬套交易日模式。

对日频接口，默认支持：

- `sync --table <table> --start-date YYYY-MM-DD --end-date YYYY-MM-DD`
- 分区已存在则跳过；
- 成功写入后推进 `sync_meta.last_date`；
- 若没有交易日历数据，提示先同步 `trade_cal`。

注意：若接口可能返回空结果，先判断是否需要“写空分区并推进进度”。沿用当前 `stk_limit` / `stock_st` 模式时，空结果不写分区，也不推进 `sync_meta`。

### 3. 修改 Fetcher

在 `zer0share/fetcher.py` 中：

- 新增 `<API>_COLS` 字段常量，字段必须来自本地 Tushare 文档；
- 若接口有单次上限，新增 `_API_PAGE_SIZE`；
- 新增 `fetch_<table>()` 方法；
- 每次 HTTP 出站都必须通过 `_call_pro_api("<pro_api_name>", lambda: self._pro.<pro_api_name>(...))`；
- `api_name` 必须与 Tushare SDK 方法名一致，用于统一限流和持久化降档；
- 对日期字段用 `pd.to_datetime(...).dt.date` 转成 `date`；
- `None` 或空 DataFrame 返回带正确列名的空 DataFrame；
- 分页时用 `offset` / `limit`，最后 `concat` 并按业务主键去重。

分页接口参考：

```python
chunks: list[pd.DataFrame] = []
offset = 0
while True:
    df = self._call_pro_api(
        "api_name",
        lambda o=offset: self._pro.api_name(
            trade_date=date_str,
            offset=o,
            limit=_API_PAGE_SIZE,
            fields=field_str,
        ),
    )
    if df is None or df.empty:
        break
    chunks.append(df)
    if len(df) < _API_PAGE_SIZE:
        break
    offset += len(df)
```

### 4. 修改 Storage

在 `zer0share/storage.py` 中按同步类型补充：

- `write_<table>()`
- `<table>_partition_exists()`，若是分区表；
- 如已有读取 helper 模式需要覆盖，也补 `read_<table>()`。

日分区路径统一使用：

```text
data/<table>/date=YYYYMMDD/data.parquet
```

### 5. 修改 Pipeline

在 `zer0share/pipeline.py` 中：

- 导入新的 storage helper；
- 新增 `sync_<table>()`；
- 交易日增量型接口复用 `sync_daily_basic` / `sync_stk_limit` / `sync_stock_st` 的结构；
- 失败时记录日志、发送 notifier，并重新抛出异常；
- 成功结束后发送同步摘要。

新增同步方法的行为要覆盖：

- 自动增量；
- 显式日期范围；
- 起止日期校验；
- 无交易日历时报错；
- 无交易日时直接返回；
- 已存在分区跳过。

### 6. 修改 LocalPro

在 `zer0share/api.py` 中：

- 导入新字段常量；
- 新增与 Tushare 同名的本地查询方法；
- 日分区表优先复用 `_query_daily_partitioned()`；
- 将接口加入 `query()` dispatch。

日分区表默认支持：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `fields`

### 7. 修改 CLI、配置、调度与 **`pipeline.log` 全日成功（必查清单）**

在 `zer0share/cli.py` 中：

- 将表名加入 `--table` choices；
- 若支持日期范围，将表名加入日期范围白名单；
- 在 `sync` 命令体中为该表增加 `if table == ...` 分支（与现有表一致）；
- **凡纳入 `sync --all` 的表**：必须在 **`_run_sync_all()`** 中增加对应的 **`run_step("<table>", ...)`**（顺序与依赖与文档「第五步」一致）；仅改 `if sync_all or table ==` 而未改 `_run_sync_all` **视为未完成**，会导致「同步成功」一行不包含该表。
- 在 `status` 输出中加入新表。

在 `zer0share/config.py` 与 `zer0share/scheduler.py` 中：

- 只有适合 **默认定时** 同步的接口才加入调度；
- 配置项使用可选默认值，避免破坏已有 `settings.toml`；
- 调度时间与相近接口错峰，例如 `stk_limit` 18:10、`stock_st` 18:15、`daily_basic` 18:20、`suspend_d` 18:25。
- **凡新增默认定时任务**：必须在 `scheduler.py` 中 **把 `add_job` 的 `id=` 加入元组 `SCHEDULED_JOB_IDS`**，且 **`add_job` 的第一个参数必须是 `_wrap_scheduled_job(cfg.log_path, "<同一 id>", pipeline.sync_*)`**；**不得**只 `add_job(pipeline.sync_*)` 而漏改 `SCHEDULED_JOB_IDS`，否则 **`pipeline.log` 的「当日全部成功」与 `pipeline_day_state.json` 不会对齐**。

在 `zer0share/pipeline.py` 中（与日志契约一致）：

-  **`sync_*` 失败时须 `logger.error(...)`**（现有模式为再 `notifier` + `raise`），以便精简模式下 **错误仍会写入 `pipeline.log`**；勿仅用 `print` 或吞掉异常。

高成本、低频或不适合默认全量刷新接口，不要默认加入 `sync --all` 或 scheduler；须在设计 / `docs/SYNC_GUIDE.md` 中写明取舍。

#### 接新表时 `pipeline.log` / 全日成功检查清单（必打勾）

- [ ] **`zer0share/cli.py`**：`_run_sync_all()` 已为新表添加 `run_step`（表名与 `sync --table` 一致）。
- [ ] **`zer0share/scheduler.py`**（仅当纳入默认定时）：`SCHEDULED_JOB_IDS` 含与 `add_job(..., id=...)` **完全相同**的字符串；`add_job` 使用 `_wrap_scheduled_job(cfg.log_path, id, ...)`。
- [ ] **`zer0share/pipeline.py`**：`sync_*` 失败路径含 **`logger.error`**（及既有 `notifier` / `raise` 约定）。
- [ ] **`tests/test_scheduler.py`**：若调度 job 集合有约定测试，已更新期望值。

### 8. 修改文档和示例

至少更新：

- `README.md`
- `docs/SYNC_GUIDE.md`
- `docs/tushare-data-expansion-design.md`
- `examples/local_query_api_smoke.py`，如果该接口适合展示本地查询。

文档要写清：

- Tushare 接口名和官方文档链接；
- 权限门槛；
- 同步命令；
- 存储路径；
- 字段列表；
- `sync --all` 顺序；
- 本地查询方法。

整理 Markdown 时优先使用 `mdformat`（GFM）；若环境没有 `mdformat`，说明未运行格式化。

### 9. 添加测试

按层补测试，至少覆盖新增行为：

- `tests/test_fetcher.py`：字段、空返回、分页、必要时限流重试；
- `tests/test_storage.py`：写入路径和存在判断；
- `tests/test_pipeline.py`：写分区、跳过已有分区、日期范围；
- `tests/test_api.py`：本地查询、字段筛选、`query("<api>")` 分发；
- `tests/test_cli.py`：CLI 表名与日期范围；
- `tests/test_config.py`：可选调度默认值；
- `tests/test_scheduler.py`：调度注册，仅当新接口加入 scheduler。

测试数据尽量小而完整，字段名必须与文档一致。

### 10. 验证

修改后运行：

```bash
C:/Users/Erich/miniforge3/envs/free/python.exe -m pytest -q
```

如果项目当前使用 `uv run pytest -q` 且用户未要求固定解释器，也可沿用仓库现有命令；但本用户规则优先要求 Python 使用 `C:/Users/Erich/miniforge3/envs/free/python.exe`。

再检查最近编辑文件的 linter。不要提交 token、webhook 或本机私密路径。

### 11. 提交 Git commit

**每次将一个新的数据接口完整纳入同步范畴后，在测试通过的前提下，必须执行一次 Git 提交**（`git add` 相关改动，`git commit`），使该接口的代码、文档与测试在版本历史上可单独追溯，便于评审与回滚。一次提交应聚焦于该接口（或该接口加上配套 skill/文档小修正），避免与大范围无关重构混在同一 commit。

推送远程仓库（`git push`）按团队习惯执行；本地至少要有 commit。

## 完成标准

一个新 Tushare 接口只有满足以下条件，才算完整纳入同步范畴：

- 已确认权限可调用；
- 已阅读并引用本地叶子 `data.md`；
- Fetcher 通过 `_call_pro_api` 调用 Tushare；
- 数据可写入本地 Parquet；
- Pipeline 可增量同步；
- **`sync_*` 失败路径含 `logger.error`（及项目约定的通知/抛异常）**；
- CLI 可单独触发；
- **若该表在 `sync --all` 范围内**：已在 **`cli.py` 的 `_run_sync_all()`** 中增加 **`run_step`**；
- **若该表在默认定时调度范围内**：已更新 **`scheduler.py` 的 `SCHEDULED_JOB_IDS`** 且 **`add_job` 使用 `_wrap_scheduled_job`**；
- LocalPro 可本地查询；
- 文档说明同步与查询方式（且与 `--all`/调度器是否收录一致）；
- 相关测试通过（含 **若动到调度器则更新 `tests/test_scheduler.py` 的 job 集合断言**）；
- **已就本次接口接入完成 Git commit**（见上文「11. 提交 Git commit」）。
