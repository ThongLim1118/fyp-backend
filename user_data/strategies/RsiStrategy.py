from freqtrade.strategy import IStrategy, IntParameter
import pandas as pd
import talib as ta

class RsiStrategy(IStrategy):
    INTERFACE_VERSION = 3
    minimal_roi = {"0": 0.03}
    stoploss = -0.03
    timeframe = '1h'

    rsi_buy = IntParameter(20, 40, default=30, space='buy')
    rsi_sell = IntParameter(60, 80, default=70, space='sell')

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Pass the close price series to TA-Lib's RSI function
        close_array = dataframe['close'].to_numpy(dtype='float64')
        rsi_values = ta.RSI(close_array)
        dataframe['rsi'] = pd.Series(rsi_values, index=dataframe.index)
        return dataframe

    def populate_buy_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            dataframe['rsi'] < self.rsi_buy.value,
            'buy'] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe.loc[
            dataframe['rsi'] > self.rsi_sell.value,
            'sell'] = 1
        return dataframe
