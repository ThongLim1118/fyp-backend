import joblib
import numpy as np
import pandas as pd

from pathlib import Path
from typing import List

from pandas import DataFrame
from freqtrade.strategy import IStrategy
from freqtrade.enums import CandleType


class MLXGBoostMultiTF_5m(IStrategy):
    """
    ML XGBoost Multi Timeframe Strategy

    - Main Timeframe: 5m
    - Informative Timeframes: 15m, 1h
    - Uses a pre-trained XGBoost model (best_xgboost_model.joblib)
    - Features are loaded from feature_columns.joblib
    """

    INTERFACE_VERSION = 3
    timeframe = "5m"
    startup_candle_count = 50  # At least enough for feature calculations
    can_short = False

    THRESHOLD = 0.5
    minimal_roi = {
        "0": 0.08
    }
    stoploss = -0.02
    trailing_stop = False

    def __init__(self, config) -> None:
        super().__init__(config)

        base = Path(__file__).resolve().parent.parent  # /freqtrade/user_data
        model_dir = base / "models/xgboost/5m/v1"

        self.model = joblib.load(model_dir / "best_xgboost_model.joblib")
        self.feature_cols: List[str] = joblib.load(model_dir / "feature_columns.joblib")
        self._debug_log("#######################################################")

    def predict_direction(self, x_features, threshold=THRESHOLD):
        """
        x_features: 2D array / DataFrame with same feature cols as training set
        """
        proba = self.model.predict_proba(x_features)[:, 1]
        return (proba >= threshold).astype(int), proba

    def informative_pairs(self):
        """
        Tells Freqtrade we want 15m and 1h informative data.
        Return type should be list[tuple[str, str, CandleType]].
        """
        pairs = self.dp.current_whitelist()

        return (
            [(pair, "15m", CandleType.SPOT) for pair in pairs] +
            [(pair, "1h", CandleType.SPOT) for pair in pairs]
        )

    # Tool function: suffix columns align with timeframe
    @staticmethod
    def _ensure_sorted(df: DataFrame) -> DataFrame:
        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
        return df

    @staticmethod
    def _suffix_columns(df: DataFrame, suffix: str) -> DataFrame:
        """
        Add column names with timeframe suffix, e.g.:
        open -> open_5m, close -> close_15m
        """
        df = df.copy()
        df.columns = [f"{c}_{suffix}" for c in df.columns]
        return df

    def _build_multitimeframe_dataframe(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        5m as main dataframe + informative 15m / 1h
        Create multi-timeframe table that is same as training data:
        - open_5m, high_5m, ..., volume_5m
        - open_15m, ..., volume_15m
        - open_1h,  ..., volume_1h
        """
        pair = metadata["pair"]

        # Main timeframe 5m
        df_5m = self._ensure_sorted(dataframe.copy())

        # informative timeframes
        df_15m = self.dp.get_pair_dataframe(pair=pair, timeframe="15m")
        df_1h = self.dp.get_pair_dataframe(pair=pair, timeframe="1h")

        df_15m = self._ensure_sorted(df_15m)
        df_1h = self._ensure_sorted(df_1h)

        # suffix columns
        df_5m_suf = self._suffix_columns(df_5m, "5m")
        idx = df_5m_suf.index

        df_15m_suf = self._suffix_columns(df_15m, "15m").reindex(idx, method="ffill")
        df_1h_suf = self._suffix_columns(df_1h, "1h").reindex(idx, method="ffill")

        merged = df_5m_suf.join(df_15m_suf, how="left").join(df_1h_suf, how="left")

        return merged

    # Feature creation: with training stage
    @staticmethod
    def _add_lag_features(df: DataFrame, base_col: str, max_lag: int) -> DataFrame:
        df = df.copy()
        for lag in range(1, max_lag + 1):
            df[f"{base_col}_lag{lag}"] = df[base_col].shift(lag)
        return df

    @staticmethod
    def _add_return_and_rolling_features(
        df: DataFrame,
        base_col: str,
        windows: List[int],
    ) -> DataFrame:
        df = df.copy()

        df["ret_1"] = df[base_col].pct_change()

        for w in windows:
            df[f"ret_{w}"] = df[base_col].pct_change(w)
            df[f"ma_{w}"] = df[base_col].rolling(w).mean()
            df[f"vol_{w}"] = df["ret_1"].rolling(w).std()

        return df

    @staticmethod
    def _add_cross_timeframe_spreads(
        df: DataFrame,
        primary_close: str = "close_5m",
    ) -> DataFrame:
        df = df.copy()
        close_cols = [c for c in df.columns if c.startswith("close_")]

        if primary_close not in close_cols:
            return df

        for c in close_cols:
            if c == primary_close:
                continue
            spread_name = f"{primary_close}_minus_{c}"
            df[spread_name] = df[primary_close] - df[c]

        return df

    def _build_tabular_features(self, mtf_df: DataFrame) -> DataFrame:
        """
        Feature engineering on multi-timeframe df (align with training set):

        - base_price_col = "close_5m"
        - max_lag = 10
        - rolling_windows = [5, 10, 20]
        - include_cross_tf_spread = True
        """
        df = mtf_df.copy()

        base_col = "close_5m"
        max_lag = 20
        windows = [5, 10, 20]

        if base_col not in df.columns:
            # If dataset incomplete, here return original df, model won't generate signals
            return df

        df = self._add_lag_features(df, base_col, max_lag)
        df = self._add_return_and_rolling_features(df, base_col, windows)
        df = self._add_cross_timeframe_spreads(df, primary_close=base_col)

        # Training stage will dropna, here don't drop rows, filter in prediction
        return df

    # Feature creation + model prediction
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Here:
        - Build multi-timeframe table (5m + 15m + 1h)
        - Build features
        - Use XGBoost prediction
        - Write prediction result back to original dataframe["ml_pred"]
        """
        df = dataframe.copy()

        # Build multi-timeframe DataFrame
        mtf_df = self._build_multitimeframe_dataframe(df, metadata)

        # Feature engineering
        feat_df = self._build_tabular_features(mtf_df)

        # Debug: Examine missing columns
        missing = [c for c in self.feature_cols if c not in feat_df.columns]
        if missing:
            self._debug_log(
                f"MLXGBoostMultiTF: Missing {len(missing)} feature columns "
                f"(e.g. {missing[:10]})"
            )

        # Only keep feature columns that are in both feat_df and self.feature_cols
        available_cols = [c for c in self.feature_cols if c in feat_df.columns]
        df["ml_pred"] = np.nan

        if not available_cols:
            return df

        # Filter rows with NaN (lags/rolling will produce NaN in early rows)
        feat_sub = feat_df[available_cols]
        valid_idx = feat_sub.fillna(0).index

        if len(valid_idx) > 0:
            X = feat_sub.loc[valid_idx].values
            preds, _ = self.predict_direction(X)
            # Write prediction result back to dataframe's corresponding index
            df.loc[valid_idx, "ml_pred"] = preds

        if "ml_pred" in df.columns:
            pos = (df["ml_pred"] == 1).sum()
            neg = (df["ml_pred"] == 0).sum()
            nan = df["ml_pred"].isna().sum()
            self._debug_log(f"ml_pred stats: 1={pos}, 0={neg}, NaN={nan}")
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        # Initialize enter_long column
        df["enter_long"] = 0

        df.loc[
            (df["ml_pred"] == 1.0) &
            (df["volume"] > 0),   # Official recommendation: volume > 0
            "enter_long",
        ] = 1

        # Debug: See how many candles to enter long
        print(
            f"MLXGBoostMultiTF: enter_long this batch = "
            f"{int(df['enter_long'].fillna(0).sum())}"
        )

        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def _debug_log(self, msg: str) -> None:
        from pathlib import Path
        log_path = Path(__file__).resolve().parent.parent / "logs/ml_debug.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
