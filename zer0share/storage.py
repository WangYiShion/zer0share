import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import date, datetime, timezone
from pathlib import Path


class MetaStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_meta (
                table_name  VARCHAR PRIMARY KEY,
                last_date   DATE,
                updated_at  TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_cal (
                exchange      VARCHAR,
                cal_date      DATE,
                is_open       BOOLEAN,
                pretrade_date DATE,
                PRIMARY KEY (exchange, cal_date)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tushare_api_rate_caps (
                api_name         VARCHAR PRIMARY KEY,
                max_per_minute   INTEGER NOT NULL,
                max_per_second   INTEGER NOT NULL,
                updated_at       TIMESTAMP NOT NULL
            )
        """)

    def get_last_date(self, table_name: str) -> date | None:
        row = self._conn.execute(
            "SELECT last_date FROM sync_meta WHERE table_name = ?",
            [table_name]
        ).fetchone()
        return row[0] if row else None

    def update_last_date(self, table_name: str, last_date: date):
        self._conn.execute("""
            INSERT INTO sync_meta (table_name, last_date, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (table_name) DO UPDATE SET
                last_date = excluded.last_date,
                updated_at = excluded.updated_at
        """, [table_name, last_date, datetime.now(timezone.utc)])

    def __enter__(self) -> "MetaStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False

    def load_trade_cal_from_parquet(self, data_dir: Path) -> None:
        trade_cal_dir = data_dir / "trade_cal"
        if not trade_cal_dir.exists():
            return
        self._conn.execute("BEGIN")
        try:
            self._conn.execute("DELETE FROM trade_cal")
            for exchange_dir in sorted(trade_cal_dir.iterdir()):
                if not exchange_dir.is_dir():
                    continue
                parquet_path = exchange_dir / "data.parquet"
                if not parquet_path.exists():
                    continue
                self._conn.execute(
                    "INSERT INTO trade_cal SELECT * FROM read_parquet(?)",
                    [str(parquet_path)]
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def get_trading_days(
        self, exchange: str, start: date, end: date
    ) -> list[date]:
        rows = self._conn.execute(
            """
            SELECT cal_date FROM trade_cal
            WHERE exchange = ?
              AND cal_date >= ?
              AND cal_date <= ?
              AND is_open = TRUE
            ORDER BY cal_date
            """,
            [exchange, start, end]
        ).fetchall()
        return [row[0] for row in rows]

    def get_tushare_api_rate_cap(self, api_name: str) -> tuple[int, int] | None:
        row = self._conn.execute(
            """
            SELECT max_per_minute, max_per_second
            FROM tushare_api_rate_caps
            WHERE api_name = ?
            """,
            [api_name],
        ).fetchone()
        return (int(row[0]), int(row[1])) if row else None

    def upsert_tushare_api_rate_cap(
        self,
        api_name: str,
        max_per_minute: int,
        max_per_second: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO tushare_api_rate_caps
                (api_name, max_per_minute, max_per_second, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (api_name) DO UPDATE SET
                max_per_minute = excluded.max_per_minute,
                max_per_second = excluded.max_per_second,
                updated_at = excluded.updated_at
            """,
            [
                api_name,
                max_per_minute,
                max_per_second,
                datetime.now(timezone.utc),
            ],
        )

    def close(self):
        self._conn.close()


def write_daily_kline(data_dir: Path, trade_date: date, df: pd.DataFrame) -> None:
    partition_dir = data_dir / "daily_kline" / f"date={trade_date.strftime('%Y%m%d')}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, partition_dir / "data.parquet")


def daily_kline_partition_exists(data_dir: Path, trade_date: date) -> bool:
    path = data_dir / "daily_kline" / f"date={trade_date.strftime('%Y%m%d')}" / "data.parquet"
    return path.exists()


def read_daily_kline(data_dir: Path, trade_date: date) -> pd.DataFrame:
    path = data_dir / "daily_kline" / f"date={trade_date.strftime('%Y%m%d')}" / "data.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pq.read_table(path).to_pandas()


def write_adj_factor(data_dir: Path, trade_date: date, df: pd.DataFrame) -> None:
    partition_dir = data_dir / "adj_factor" / f"date={trade_date.strftime('%Y%m%d')}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, partition_dir / "data.parquet")


def adj_factor_partition_exists(data_dir: Path, trade_date: date) -> bool:
    path = data_dir / "adj_factor" / f"date={trade_date.strftime('%Y%m%d')}" / "data.parquet"
    return path.exists()


def write_stk_limit(data_dir: Path, trade_date: date, df: pd.DataFrame) -> None:
    partition_dir = data_dir / "stk_limit" / f"date={trade_date.strftime('%Y%m%d')}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, partition_dir / "data.parquet")


def stk_limit_partition_exists(data_dir: Path, trade_date: date) -> bool:
    path = data_dir / "stk_limit" / f"date={trade_date.strftime('%Y%m%d')}" / "data.parquet"
    return path.exists()


def write_stock_st(data_dir: Path, trade_date: date, df: pd.DataFrame) -> None:
    partition_dir = data_dir / "stock_st" / f"date={trade_date.strftime('%Y%m%d')}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, partition_dir / "data.parquet")


def stock_st_partition_exists(data_dir: Path, trade_date: date) -> bool:
    path = (
        data_dir / "stock_st" / f"date={trade_date.strftime('%Y%m%d')}" / "data.parquet"
    )
    return path.exists()


def write_daily_basic(data_dir: Path, trade_date: date, df: pd.DataFrame) -> None:
    partition_dir = data_dir / "daily_basic" / f"date={trade_date.strftime('%Y%m%d')}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, partition_dir / "data.parquet")


def daily_basic_partition_exists(data_dir: Path, trade_date: date) -> bool:
    path = (
        data_dir / "daily_basic" / f"date={trade_date.strftime('%Y%m%d')}"
        / "data.parquet"
    )
    return path.exists()


def write_stock_basic(data_dir: Path, df: pd.DataFrame) -> None:
    stock_basic_dir = data_dir / "stock_basic"
    stock_basic_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, stock_basic_dir / "data.parquet")


def read_stock_basic(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "stock_basic" / "data.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pq.read_table(path).to_pandas()


def write_trade_cal(data_dir: Path, exchange: str, df: pd.DataFrame) -> None:
    partition_dir = data_dir / "trade_cal" / f"exchange={exchange}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, partition_dir / "data.parquet")


def read_trade_cal(data_dir: Path, exchange: str) -> pd.DataFrame:
    path = data_dir / "trade_cal" / f"exchange={exchange}" / "data.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pq.read_table(path, schema=pq.read_schema(path)).to_pandas()
