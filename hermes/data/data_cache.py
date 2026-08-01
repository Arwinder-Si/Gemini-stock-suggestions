"""
Parquet-backed 1-min candle historical data cache.
Storage layout: data/candles/security_id=<id>/<YYYY-MM>.parquet
"""

import os
from pathlib import Path
from datetime import date, datetime
import pandas as pd


class CandleCache:
    """
    Parquet candle cache partitioned by security_id and YYYY-MM.
    Schema: [symbol, security_id, timestamp, open, high, low, close, volume]
    """

    def __init__(self, base_dir: str = "data/candles"):
        self.base_dir = Path(base_dir)

    def _get_partition_dir(self, security_id: str) -> Path:
        return self.base_dir / f"security_id={security_id}"

    def write(self, security_id: str, df: pd.DataFrame) -> None:
        """
        Write or append 1-min candles for a security_id.
        Handles deduplication and sorting by timestamp.
        """
        if df.empty:
            return

        required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"DataFrame missing required columns: {required_cols - set(df.columns)}")

        work_df = df.copy()
        work_df["timestamp"] = pd.to_datetime(work_df["timestamp"])
        if "security_id" not in work_df.columns:
            work_df["security_id"] = str(security_id)

        # Group by YYYY-MM and save to monthly parquet files
        work_df["month_key"] = work_df["timestamp"].dt.strftime("%Y-%m")
        partition_dir = self._get_partition_dir(str(security_id))
        partition_dir.mkdir(parents=True, exist_ok=True)

        for month_key, month_df in work_df.groupby("month_key"):
            file_path = partition_dir / f"{month_key}.parquet"
            clean_month_df = month_df.drop(columns=["month_key"])

            if file_path.exists():
                existing_df = pd.read_parquet(file_path)
                combined = pd.concat([existing_df, clean_month_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
                combined = combined.sort_values(by="timestamp").reset_index(drop=True)
                combined.to_parquet(file_path, index=False)
            else:
                clean_month_df = clean_month_df.sort_values(by="timestamp").reset_index(drop=True)
                clean_month_df.to_parquet(file_path, index=False)

    def read(self, security_id: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        """Read candle history for security_id between start and end dates (inclusive)."""
        partition_dir = self._get_partition_dir(str(security_id))
        if not partition_dir.exists():
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "security_id"])

        files = sorted(list(partition_dir.glob("*.parquet")))
        if not files:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "security_id"])

        dfs = []
        for file_path in files:
            file_month_str = file_path.stem  # YYYY-MM
            # Quick check if month is out of range
            if start and file_month_str < start.strftime("%Y-%m"):
                continue
            if end and file_month_str > end.strftime("%Y-%m"):
                continue
            dfs.append(pd.read_parquet(file_path))

        if not dfs:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "security_id"])

        full_df = pd.concat(dfs, ignore_index=True)
        full_df["timestamp"] = pd.to_datetime(full_df["timestamp"])

        if start:
            start_dt = pd.Timestamp(start)
            full_df = full_df[full_df["timestamp"] >= start_dt]
        if end:
            # Include full end date up to end of day
            end_dt = pd.Timestamp(end) + pd.Timedelta(days=1)
            full_df = full_df[full_df["timestamp"] < end_dt]

        return full_df.sort_values(by="timestamp").reset_index(drop=True)

    def coverage(self, security_id: str) -> list[tuple[date, date]]:
        """Return list of (min_date, max_date) continuous coverage ranges for security_id."""
        df = self.read(security_id)
        if df.empty:
            return []

        df["date"] = df["timestamp"].dt.date
        unique_dates = sorted(df["date"].unique())
        if not unique_dates:
            return []

        # Find contiguous date blocks
        ranges = []
        start_d = unique_dates[0]
        prev_d = start_d

        for cur_d in unique_dates[1:]:
            if (cur_d - prev_d).days > 3:  # Allow weekend gap of up to 3 days
                ranges.append((start_d, prev_d))
                start_d = cur_d
            prev_d = cur_d

        ranges.append((start_d, prev_d))
        return ranges
