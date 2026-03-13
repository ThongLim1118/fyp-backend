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
    ML XGBoost 多周期策略示例

    - 主周期: 5m
    - informative 周期: 15m, 1h
    - 使用已训练好的 XGBoost 模型 (best_xgboost_model.joblib)
    - 特征列从 feature_columns.joblib 读取
    """

    # 基本配置
    timeframe = "5m"
    startup_candle_count = 50  # 至少要有这么多根 K 才有完整特征
    can_short = False

    # 简单 ROI / 止损 (你可以以后自己调)
    minimal_roi = {
        "0": 0.05
    }
    stoploss = -0.1
    trailing_stop = False

    def __init__(self, config) -> None:
        super().__init__(config)

        # 模型 / 特征路径: 假定在 /freqtrade/user_data/models 下
        base = Path(__file__).resolve().parent.parent  # /freqtrade/user_data
        model_dir = base / "models/xgboost/5m/v1"

        self.model = joblib.load(model_dir / "best_xgboost_model.joblib")
        self.feature_cols: List[str] = joblib.load(model_dir / "feature_columns.joblib")

    def informative_pairs(self):
        """
        告诉 Freqtrade 我们要 15m 和 1h 的 informative 数据。
        返回类型要是 list[tuple[str, str, CandleType]]。
        """
        pairs = self.dp.current_whitelist()

        return (
            [(pair, "15m", CandleType.SPOT) for pair in pairs] +
            [(pair, "1h", CandleType.SPOT) for pair in pairs]
        )

    # 工具函数：suffix 列名、对齐多周期
    @staticmethod
    def _ensure_sorted(df: DataFrame) -> DataFrame:
        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
        return df

    @staticmethod
    def _suffix_columns(df: DataFrame, suffix: str) -> DataFrame:
        """
        把 OHLCV 列名加上 timeframe 后缀，例如:
        open -> open_5m, close -> close_15m
        """
        df = df.copy()
        df.columns = [f"{c}_{suffix}" for c in df.columns]
        return df

    def _build_multitimeframe_dataframe(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        从 5m 主 dataframe + informative 15m / 1h
        构建和训练时一样的 multi-timeframe 表：
        - open_5m, high_5m, ..., volume_5m
        - open_15m, ..., volume_15m
        - open_1h,  ..., volume_1h
        """
        pair = metadata["pair"]

        # 主周期 5m
        df_5m = self._ensure_sorted(dataframe)

        # informative 周期
        df_15m = self.dp.get_pair_dataframe(pair=pair, timeframe="15m")
        df_1h = self.dp.get_pair_dataframe(pair=pair, timeframe="1h")

        df_15m = self._ensure_sorted(df_15m)
        df_1h = self._ensure_sorted(df_1h)

        # suffix 列名
        df_5m_suf = self._suffix_columns(df_5m, "5m")
        idx = df_5m_suf.index

        df_15m_suf = self._suffix_columns(df_15m, "15m").reindex(idx, method="ffill")
        df_1h_suf = self._suffix_columns(df_1h, "1h").reindex(idx, method="ffill")

        merged = df_5m_suf.join(df_15m_suf, how="left").join(df_1h_suf, how="left")

        return merged

    # 特征构建：与训练阶段保持一致
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
        对 multi-timeframe df 进行特征工程 (与训练阶段一致)

        - base_price_col = "close_5m"
        - max_lag = 10
        - rolling_windows = [5, 10, 20]
        - include_cross_tf_spread = True
        """
        df = mtf_df.copy()

        base_col = "close_5m"
        max_lag = 10
        windows = [5, 10, 20]

        if base_col not in df.columns:
            # 如果数据源不完整，这里直接返回原 df，后面模型不会产生信号
            return df

        df = self._add_lag_features(df, base_col, max_lag)
        df = self._add_return_and_rolling_features(df, base_col, windows)
        df = self._add_cross_timeframe_spreads(df, primary_close=base_col)

        # 训练阶段会 dropna，这里不 drop 行，而是在预测时过滤
        return df

    # 构建特征 + 模型预测
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        这里：
        - 构建多周期表 (5m + 15m + 1h)
        - 构建特征
        - 用 XGBoost 预测
        - 把预测结果写回原 dataframe["ml_pred"]
        """
        df = dataframe.copy()

        # 构建 multi-timeframe DataFrame
        mtf_df = self._build_multitimeframe_dataframe(df, metadata)

        # 特征工程
        feat_df = self._build_tabular_features(mtf_df)

        # Debug: 检查缺失的特征列
        missing = [c for c in self.feature_cols if c not in feat_df.columns]
        if missing:
            # 使用 freqtrade 的日志；如果你不确定，可以改成 print
            print(
                f"MLXGBoostMultiTF: Missing {len(missing)} feature columns "
                f"(e.g. {missing[:10]})"
            )

        # 只用策略里实际有的那部分特征列
        available_cols = [c for c in self.feature_cols if c in feat_df.columns]
        df["ml_pred"] = np.nan

        if not available_cols:
            # 一个特征都对不上，直接返回，不发信号
            return df

        # 过滤掉含 NaN 的行 (lags/rolling 前期会产生 NaN)
        feat_sub = feat_df[available_cols]
        valid_idx = feat_sub.dropna().index

        if len(valid_idx) > 0:
            X = feat_sub.loc[valid_idx].values
            preds = self.model.predict(X)
            # 将预测结果写回主 dataframe 的对应 index
            df.loc[valid_idx, "ml_pred"] = preds

        return df

    # 5. 入场 / 出场逻辑
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        # 注意：如果当前策略是用 'buy' / 'sell'，请把下面两行改成 'buy'
        df.loc[
            (df["ml_pred"] == 1.0),
            "enter_long",
        ] = 1

        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        # 这里先给一个最简单的例子：有仓就允许 exit
        # 同样，如果你用的是 'sell' 列，请改成 'sell'
        df["exit_long"] = 1

        return df
