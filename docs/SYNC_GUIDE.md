# 数据同步指南

## 前置条件

### 1. 安装依赖

```bash
uv sync --dev
```

### 2. 配置文件

复制示例配置并填写真实参数：

```bash
cp config/settings.example.toml config/settings.toml
```

编辑 `config/settings.toml`（路径、调度时间等）。**请勿将 Tushare Token 写入文件**，请设置环境变量 `TUSHARE_TOKEN`（见项目 [README.md](../README.md)）。

```toml
[paths]
data_dir = "data"
db_path = "db/meta.duckdb"
log_path = "logs/pipeline.log"

[scheduler]
daily_kline_hour = 18
daily_kline_minute = 0
basic_hour = 8
adj_factor_hour = 18
adj_factor_minute = 5
# 可选；每日涨跌停价同步时间，缺省为 18:10
# stk_limit_hour = 18
# stk_limit_minute = 10
# 可选；ST 股票列表同步时间，缺省为 18:15（官方约交易日 09:20 更新）
# stock_st_hour = 18
# stock_st_minute = 15
# 可选；每日指标同步时间，缺省为 18:20（官方约交易日 15:00～17:00 更新）
# daily_basic_hour = 18
# daily_basic_minute = 20
# 可选；每日停复牌同步时间，缺省为 18:25（官方不定期更新）
# suspend_d_hour = 18
# suspend_d_minute = 25

[notifier]
wecom_webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
enabled = false
```

通知还可通过环境变量 `PUSHPLUS_TOKEN` 启用 [PushPlus](https://www.pushplus.plus/)（与企业微信并列，未设置则仅走 `notifier` 配置）。

`python main.py sync --all` 与定时调度在 **当日全部 Level1 任务结束** 时：**全部成功** 只推送一条「当日全部 Level1 数据同步成功」；若有失败则 **只推送一条**，正文中列出 **所有** 失败接口及原因（与 `pipeline.log` 精简成功行策略一致）。单独执行 `sync --table …` 时仍按表推送成功摘要或失败信息。

> Tushare Token 在 [tushare.pro](https://tushare.pro) 注册后获取，需要积分 >= 2000 才能调用 `daily` 接口。

---

## 首次同步

### 步骤一：同步交易日历

交易日历是其他同步的前置依赖，**必须最先执行**。

```bash
uv run python main.py sync --table trade_cal
```

此命令会：
- 拉取 SSE、SZSE、CFFEX、SHFE、CZCE、DCE、INE 共 7 个交易所从 1990-01-01 至今的全量日历
- 写入 `data/trade_cal/exchange=XXX/data.parquet`
- 加载到 DuckDB 供后续查询

预计耗时：1～3 分钟（受网络和 Tushare 限速影响）。

### 步骤二：同步股票基础信息

```bash
uv run python main.py sync --table stock_basic
```

此命令会：
- 拉取全市场所有状态（上市 L、退市 D、暂停 P、精选层 G）的股票基础信息（Tushare `stock_basic`）
- 写入 `data/stock_basic/data.parquet`

### 步骤三：同步日线行情

```bash
uv run python main.py sync --table daily_kline
```

此命令会：
- 以 SSE 交易日历为基准，只对真实交易日拉取数据（跳过周末和节假日）
- 从 2016-01-01 起增量同步到今天
- 每个交易日写入 `data/daily_kline/date=YYYYMMDD/data.parquet`

> **注意**：首次同步历史数据量较大（约 10 年 × 3800 只股票），耗时可能在 1～2 小时，受 Tushare 每分钟调用频次限制影响。

### 步骤四：同步复权因子

```bash
uv run python main.py sync --table adj_factor
```

此命令会：
- 以 SSE 交易日历为基准，拉取每个交易日全市场的前复权因子
- 从 2016-01-01 起增量同步到今天
- 每个交易日写入 `data/adj_factor/date=YYYYMMDD/data.parquet`

字段：`ts_code`（股票代码）、`trade_date`（交易日）、`adj_factor`（复权因子值）。

### 步骤五：同步每日指标（daily_basic）

```bash
uv run python main.py sync --table daily_basic
```

此命令会：

- 调用 Tushare [`daily_basic`](https://tushare.pro/document/2?doc_id=32)，按交易日获取全市场个股的每日基本面指标（换手率、估值、市值等），与官方文档字段一致。
- 以 SSE 交易日历为基准，仅交易日拉取；从 2016-01-01 起增量同步到今天。
- `ts_code` 传空字符串表示全市场；单日记录可能超过单次接口上限（约 6000 条），客户端自动分页合并。
- 写入 `data/daily_basic/date=YYYYMMDD/data.parquet`。

字段：`ts_code`、`trade_date`、`close`、`turnover_rate`、`turnover_rate_f`、`volume_ratio`、`pe`、`pe_ttm`、`pb`、`ps`、`ps_ttm`、`dv_ratio`、`dv_ttm`、`total_share`、`float_share`、`free_share`、`total_mv`、`circ_mv`。

### 步骤六：同步每日停复牌信息（suspend_d）

```bash
uv run python main.py sync --table suspend_d
```

此命令会：

- 调用 Tushare [`suspend_d`](https://tushare.pro/document/2?doc_id=214)，按交易日获取全市场停牌/复牌记录（不传 `suspend_type` 时尽可能一次拉取停牌与复牌）；与官方文档字段一致。
- 以 SSE 交易日历为基准，仅交易日拉取；从 2016-01-01 起增量同步到今天。
- 单日记录可能较多时按 `limit`/`offset` 分页合并（每页 5000 条）。
- 写入 `data/suspend_d/date=YYYYMMDD/data.parquet`。

字段：`ts_code`、`trade_date`、`suspend_timing`、`suspend_type`（`S` 停牌，`R` 复牌）。

### 步骤七：同步每日涨跌停价格

```bash
uv run python main.py sync --table stk_limit
```

此命令会：
- 调用 Tushare [`stk_limit`](https://tushare.pro/document/2?doc_id=183)，拉取全市场（含 A/B 股与基金等）每个交易日的涨停价、跌停价及昨收，与官方文档字段一致。
- 以 SSE 交易日历为基准，仅交易日拉取；从 2016-01-01 起增量同步到今天。
- 单日记录可能超过单次接口上限（约 5800 条），客户端会自动分页合并。
- 写入 `data/stk_limit/date=YYYYMMDD/data.parquet`。

字段：`ts_code`、`trade_date`、`pre_close`、`up_limit`、`down_limit`。

### 步骤八：同步 ST 股票列表

```bash
uv run python main.py sync --table stock_st
```

此命令会：

- 调用 Tushare [`stock_st`](https://tushare.pro/document/2?doc_id=397)，按交易日获取当日 ST / *ST 等风险警示证券列表；与官方文档字段一致。
- 以 SSE 交易日历为基准，仅交易日拉取；从 2016-01-01 起增量同步到今天。
- 单次请求最多返回约 1000 行，多于该数量时客户端自动分页合并。
- 写入 `data/stock_st/date=YYYYMMDD/data.parquet`。

字段：`ts_code`、`name`、`trade_date`、`type`、`type_name`。

---

## 一键同步全部

以上八步可合并为一条命令，顺序固定为 trade_cal → stock_basic → daily_kline → adj_factor → daily_basic → suspend_d → stk_limit → stock_st：

```bash
uv run python main.py sync --all
```

---

## 查看同步状态

```bash
uv run python main.py status
```

输出示例：

```
trade_cal     last sync: 2026-04-17
daily_kline   last sync: 2026-04-17
adj_factor    last sync: 2026-04-17
daily_basic   last sync: 2026-04-17
suspend_d     last sync: 2026-04-17
stk_limit     last sync: 2026-04-17
stock_st      last sync: 2026-04-17
stock_basic   last sync: 2026-04-17
```

---

## 增量更新

再次运行任意 `sync` 命令时，pipeline 会自动从上次同步的日期之后继续拉取，无需重新全量同步。

```bash
# 每个交易日收盘后更新日线行情
uv run python main.py sync --table daily_kline
```

---

## 自动化调度

启动后台定时任务，按配置自动在收盘后同步：

```bash
uv run python main.py scheduler start
```

默认调度时间（可在 `settings.toml` 修改）：

| 任务 | 触发时间 | 说明 |
|------|----------|------|
| daily_kline | 每天 18:00 | 仅交易日写入数据，非交易日自动跳过 |
| adj_factor | 每天 18:05 | 仅交易日写入数据，非交易日自动跳过 |
| stk_limit | 每天 18:10（可配置 `stk_limit_hour` / `stk_limit_minute`） | 仅交易日写入；官方约每个交易日 08:40 更新当日涨跌停价 |
| stock_st | 每天 18:15（可配置 `stock_st_hour` / `stock_st_minute`） | 仅交易日写入；官方约每个交易日 09:20 更新当日 ST 列表 |
| daily_basic | 每天 18:20（可配置 `daily_basic_hour` / `daily_basic_minute`） | 仅交易日写入；官方约每个交易日 15:00～17:00 更新当日指标 |
| suspend_d | 每天 18:25（可配置 `suspend_d_hour` / `suspend_d_minute`） | 仅交易日写入；官方不定期更新 |
| stock_basic | 每天 08:00 | 每日全量刷新（`basic_hour` 配置项） |

> 调度器需保持进程运行。生产环境建议配合 `systemd` 或 `supervisor` 管理进程。

---

## 数据目录结构

同步完成后，本地数据布局如下：

```
data/
├── trade_cal/
│   ├── exchange=SSE/data.parquet
│   ├── exchange=SZSE/data.parquet
│   ├── exchange=CFFEX/data.parquet
│   ├── exchange=SHFE/data.parquet
│   ├── exchange=CZCE/data.parquet
│   ├── exchange=DCE/data.parquet
│   └── exchange=INE/data.parquet
├── stock_basic/
│   └── data.parquet
├── daily_kline/
│   ├── date=20160104/data.parquet
│   ├── date=20160105/data.parquet
│   └── ...
├── adj_factor/
│   ├── date=20160104/data.parquet
│   ├── date=20160105/data.parquet
│   └── ...
├── daily_basic/
│   ├── date=20160104/data.parquet
│   └── ...
├── suspend_d/
│   ├── date=20160104/data.parquet
│   └── ...
├── stk_limit/
│   ├── date=20160104/data.parquet
│   └── ...
└── stock_st/
    ├── date=20160104/data.parquet
    └── ...
db/
└── meta.duckdb
logs/
└── pipeline.log
```
