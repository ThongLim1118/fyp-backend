import joblib
import numpy as np
import pandas as pd

from pathlib import Path
from typing import List, Optional

from pandas import DataFrame
from freqtrade.strategy import IStrategy
from freqtrade.enums import CandleType
import torch
import torch.nn as nn

# Simple MLP setup
class MLP(nn.Module):
    def __init__(self, in_dim, hidden_dims=[128, 64], dropout=0.2):
        super().__init__()
        layers = []
        last = in_dim
        for h in hidden_dims:
            layers.append(nn.Linear(last, h))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout))
            last = h
        layers.append(nn.Linear(last, 1))
        self.net = nn.Sequential(*layers)
    
    def forward(self, x):
        return self.net(x).squeeze(-1)
        # return torch.sigmoid(self.net(x)).squeeze(-1)

class MLPMultiTF_5m_v2(IStrategy):
    """
    ML MLP multi-timeframe strategy example

    - Main timeframe: 5m
    - Informative timeframes: 15m, 1h
    - Use pretrained MLP model (best_mlp_model.joblib)
    - Feature columns loaded from feature_columns.joblib
    """

    def _predict_scores(self, X: np.ndarray) -> np.ndarray:
        """
        X: shape (N, in_dim), float32
        return: shape (N,), float32
        """
        if X.size == 0:
            self._debug_log("[MLPMultiTF_5m_v2] _predict_scores: empty X")
            return np.array([], dtype=np.float32)

        # First check for non-finite inputs (should have been cleaned already)
        nonfinite_in = np.sum(~np.isfinite(X))
        if nonfinite_in > 0:
            self._debug_log(
                f"[MLPMultiTF_5m_v2] _predict_scores: non-finite in X = {nonfinite_in}, "
                "applying nan_to_num(0)."
            )
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        self.model.eval()
        with torch.no_grad():
            x_tensor = torch.from_numpy(X).float()  # (N, in_dim)

            outputs = self.model(x_tensor)           # (N,)

            # Raw tensor check
            raw_nan = torch.isnan(outputs).sum().item()
            raw_min = outputs.min().item()
            raw_max = outputs.max().item()
            self._debug_log(
                f"[MLPMultiTF_5m_v2] raw outputs: nan={raw_nan}, "
                f"min={raw_min:.6f}, max={raw_max:.6f}"
            )

            # Just in case: zero out non-finite outputs
            outputs = torch.nan_to_num(outputs, nan=0.0, posinf=0.0, neginf=0.0)

            scores_np = outputs.cpu().numpy().astype(np.float32)

            nan_count = np.isnan(scores_np).sum()
            self._debug_log(
                f"[MLPMultiTF_5m_v2] _predict_scores: shape={scores_np.shape}, "
                f"nan={nan_count}, min={float(np.nanmin(scores_np)):.4f}, "
                f"max={float(np.nanmax(scores_np)):.4f}"
            )

            return scores_np

    INTERFACE_VERSION = 3
    timeframe = "5m"
    startup_candle_count = 50  # Need at least this many candles for full features
    can_short = False

    THRESHOLD = 0.5
    minimal_roi = {
        "0": 0.2
    }
    stoploss = -0.02
    trailing_stop = False

    def __init__(self, config) -> None:
        super().__init__(config)

        base = Path(__file__).resolve().parent.parent  # /freqtrade/user_data
        model_dir = base / "models/mlp/5m/v2"

        state_dict = joblib.load(model_dir / "best_mlp_model_state_dict.joblib")
        self.feature_cols: List[str] = joblib.load(model_dir / "feature_columns.joblib")
        # must be same shape as training
        in_dim = len(self.feature_cols)
        # build model from state dict
        self.model = MLP(
            in_dim=in_dim,
            hidden_dims=[128, 64],
            dropout=0.2,
        )
        # load weights
        self.model.load_state_dict(state_dict)
        self.model.eval()
        self.scaler = joblib.load(model_dir / "feature_scaler.joblib")

        self._debug_log("####################### MLPMultiTF_5m_v2 ################################")
        total_nan = 0
        for name, param in self.model.named_parameters():
            p = param.detach().cpu()
            nan_count = torch.isnan(p).sum().item()
            total_nan += nan_count
            self._debug_log(
                f"[MLPMultiTF_5m_v2] param {name}: "
                f"nan={nan_count}, min={p.min().item():.6f}, max={p.max().item():.6f}"
            )

        self._debug_log(f"[MLPMultiTF_5m_v2] total NaN in params: {total_nan}")

    def informative_pairs(self):
        """
        Tell Freqtrade we need 15m and 1h informative data.
        Return type should be list[tuple[str, str, CandleType]].
        """
        pairs = self.dp.current_whitelist()

        return (
            [(pair, "15m", CandleType.SPOT) for pair in pairs] +
            [(pair, "1h", CandleType.SPOT) for pair in pairs]
        )

    # Utility: suffix column names and align timeframes
    @staticmethod
    def _ensure_sorted(df: DataFrame) -> DataFrame:
        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
        return df

    @staticmethod
    def _suffix_columns(df: DataFrame, suffix: str) -> DataFrame:
        """
        Add timeframe suffix to OHLCV column names, e.g.:
        open -> open_5m, close -> close_15m
        """
        df = df.copy()
        df.columns = [f"{c}_{suffix}" for c in df.columns]
        return df

    def _build_multitimeframe_dataframe(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        From 5m main dataframe + informative 15m / 1h
        Build the same multi-timeframe table as in training:
        - open_5m, high_5m, ..., volume_5m
        - open_15m, ..., volume_15m
        - open_1h,  ..., volume_1h
        """
        pair = metadata["pair"]

        # Main timeframe 5m
        df_5m = self._ensure_sorted(dataframe.copy())

        # Informative timeframes
        df_15m = self.dp.get_pair_dataframe(pair=pair, timeframe="15m")
        df_1h = self.dp.get_pair_dataframe(pair=pair, timeframe="1h")

        df_15m = self._ensure_sorted(df_15m)
        df_1h = self._ensure_sorted(df_1h)

        # Suffix column names
        df_5m_suf = self._suffix_columns(df_5m, "5m")
        idx = df_5m_suf.index

        df_15m_suf = self._suffix_columns(df_15m, "15m").reindex(idx, method="ffill")
        df_1h_suf = self._suffix_columns(df_1h, "1h").reindex(idx, method="ffill")

        merged = df_5m_suf.join(df_15m_suf, how="left").join(df_1h_suf, how="left")

        return merged

    # Feature engineering: keep consistent with training
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
    
    def _add_rsi_macd_features(
        self,
        df: pd.DataFrame,
        base_col: str,
        windows: Optional[List[int]],
    ) -> pd.DataFrame:
        
        df = df.copy()
        if windows is None:
            windows = [5, 15, 30]

        df["rsi_14"] = self.compute_rsi(df[base_col], window=14)
        df["rsi_5"] = self.compute_rsi(df[base_col], window=5)
        macd_df = self.compute_macd(df[base_col])
        df = pd.concat([df, macd_df], axis=1)
        return df

    def _build_tabular_features(self, mtf_df: DataFrame) -> DataFrame:
        """
        Feature engineering on multi-timeframe df (consistent with training)

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
            # If the data source is incomplete, return the original df; the model won't signal
            return df

        df = self._add_lag_features(df, base_col, max_lag)
        df = self._add_return_and_rolling_features(df, base_col, windows)
        df = self._add_cross_timeframe_spreads(df, primary_close=base_col)
        df = self._add_rsi_macd_features(df, base_col, windows)

        # Training drops NaNs; here keep rows and filter during prediction
        return df

    # Build features + model prediction
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Here:
        - Build multi-timeframe table (5m + 15m + 1h)
        - Build features
        - Predict with MLP
        - Write predictions back to dataframe["ml_score"] / ["ml_pred"]
        """
        df_5m = dataframe.copy()

        mtf_df = self._build_multitimeframe_dataframe(df_5m, metadata)
        feat_df = self._build_tabular_features(mtf_df)
        self._debug_log(
            f"[MLPMultiTF_5m_v2] feat_df columns sample: "
            f"{list(feat_df.columns)[:40]}"
        )
        missing = [c for c in self.feature_cols if c not in feat_df.columns]
        available_cols = [c for c in self.feature_cols if c in feat_df.columns]

        if missing:
            self._debug_log(
                f"[MLPMultiTF_5m_v2] Missing {len(missing)} feature columns, "
                f"examples: {missing[:10]}"
            )

        dataframe["ml_score"] = np.nan
        dataframe["ml_pred"] = np.nan

        if not available_cols:
            self._debug_log(
                "[MLPMultiTF_5m_v2] No available ML features in feat_df, "
                "skip ML prediction."
            )
            return dataframe

        # Build model input
        feat_sub = feat_df[available_cols].copy()
        # Coerce to numeric -> non-numeric becomes NaN
        feat_sub = feat_sub.apply(pd.to_numeric, errors="coerce")
        feat_sub = feat_sub.fillna(0.0)
        feat_sub = feat_sub.replace([np.inf, -np.inf], 0.0)
        feat_sub = feat_sub.infer_objects(copy=False)

        valid_idx = feat_sub.index

        X = feat_sub.to_numpy(dtype=np.float32, copy=False)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        X_scaled = self.scaler.transform(X)

        self._debug_log(f"[MLPMultiTF_5m] feature_cols used: {available_cols}")
        self._debug_log(
            f"[MLPMultiTF_5m] feat_sub dtypes: {feat_sub.dtypes.to_dict()}"
        )
        self._debug_log(f"feat_sub mean={feat_sub.mean().mean():.6f}, std={feat_sub.std().mean():.6f}")
        self._debug_log(
            f"[MLPMultiTF_5m] X shape before predict: {X_scaled.shape}, "
            f"non-finite in X: {np.sum(~np.isfinite(X_scaled))}"
        )

        if X_scaled.size == 0:
            self._debug_log("[MLPMultiTF_5m_v2] X is empty, no ML predictions.")
            return dataframe

        # Run MLP prediction
        scores = self._predict_scores(X_scaled)
        proba = 1.0 / (1.0 + np.exp(-scores))

        if scores.shape[0] != len(valid_idx):
            self._debug_log(
                f"[MLPMultiTF_5m_v2] WARNING: scores len {scores.shape[0]} "
                f"!= valid_idx len {len(valid_idx)}"
            )
            return dataframe

        # Write back to original dataframe (aligned by index)
        idx_to_use = dataframe.index.intersection(valid_idx)

        dataframe.loc[idx_to_use, "ml_proba"] = proba[
            np.isin(valid_idx, idx_to_use)
        ]

        dataframe.loc[idx_to_use, "ml_pred"] = (dataframe.loc[idx_to_use, "ml_proba"] > 0.5).astype(float)

        pos = (dataframe["ml_pred"] == 1).sum()
        neg = (dataframe["ml_pred"] == 0).sum()
        nan = dataframe["ml_pred"].isna().sum()
        self._debug_log(f"ml_pred stats: 1={pos}, 0={neg}, NaN={nan}")

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        # Initialize (just in case)
        df["enter_long"] = 0

        # Use model signal as entry condition (skip RSI for now to confirm trades)
        df.loc[
            (df["ml_proba"] > self.THRESHOLD) &
            (df["volume"] > 0),   # Official recommendation: volume > 0
            "enter_long",
        ] = 1

        # Debug: count how many candles enter in this batch
        print(
            f"MLMLPMultiTF: enter_long this batch = "
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

    def compute_rsi(self, series: pd.Series, window: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(window).mean()
        avg_loss = loss.rolling(window).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def compute_macd(self, series: pd.Series,
                    fast: int = 12,
                    slow: int = 26,
                    signal: int = 9) -> pd.DataFrame:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()

        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        macd_hist = macd - macd_signal

        return pd.DataFrame({
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
        })
