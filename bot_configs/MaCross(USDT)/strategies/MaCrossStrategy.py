from freqtrade.strategy import IStrategy, IntParameter, CategoricalParameter
import pandas as pd
import talib as ta
import numpy as np

class MaCrossStrategy(IStrategy):
    INTERFACE_VERSION = 3
    minimal_roi = {"0": 0.05}
    stoploss = -0.05
    timeframe = '1h'

    # 可调参数
    fast_length = IntParameter(5, 20, default=10, space='buy')
    slow_length = IntParameter(20, 60, default=30, space='buy')

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe['ma_fast'] = ta.SMA(np.asarray(dataframe['close'], dtype=np.float64), timeperiod=self.fast_length.value)
        dataframe['ma_slow'] = ta.SMA(np.asarray(dataframe['close'], dtype=np.float64), timeperiod=self.slow_length.value)
        return dataframe

    def populate_buy_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe['ma_fast'] > dataframe['ma_slow']) &
            (dataframe['ma_fast'].shift(1) <= dataframe['ma_slow'].shift(1)),
            'buy'] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            (dataframe['ma_fast'] < dataframe['ma_slow']) &
            (dataframe['ma_fast'].shift(1) >= dataframe['ma_slow'].shift(1)),
            'sell'] = 1
        return dataframe
