import pandas as pd
import numpy as np


def _price_at_highest_bars(series: pd.Series, length: int) -> pd.Series:
    """Pine: high[math.abs(ta.highestbars(length))] — value at most recent extreme bar."""
    values = series.values
    out = np.empty(len(values))
    for i in range(len(values)):
        start = max(0, i - length + 1)
        window = values[start : i + 1]
        max_val = window.max()
        for j in range(len(window) - 1, -1, -1):
            if window[j] == max_val:
                out[i] = window[j]
                break
    return pd.Series(out, index=series.index)


def _price_at_lowest_bars(series: pd.Series, length: int) -> pd.Series:
    """Pine: low[math.abs(ta.lowestbars(length))] — value at most recent extreme bar."""
    values = series.values
    out = np.empty(len(values))
    for i in range(len(values)):
        start = max(0, i - length + 1)
        window = values[start : i + 1]
        min_val = window.min()
        for j in range(len(window) - 1, -1, -1):
            if window[j] == min_val:
                out[i] = window[j]
                break
    return pd.Series(out, index=series.index)


def calculate_half_trend(
    df: pd.DataFrame, amplitude: int = 10, channel_deviation: float = 3.0
) -> pd.DataFrame:
    """
    HalfTrend indicator matching the TradingView Pine Script (everget).
    Returns dataframe with halftrend, trend, buy_signal, and sell_signal columns.
    """
    df = df.copy()
    df.columns = [col.lower() for col in df.columns]

    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 100, min_periods=100, adjust=False).mean()

    df["highPrice"] = _price_at_highest_bars(df["high"], amplitude)
    df["lowPrice"] = _price_at_lowest_bars(df["low"], amplitude)
    df["highma"] = df["high"].rolling(window=amplitude, min_periods=1).mean()
    df["lowma"] = df["low"].rolling(window=amplitude, min_periods=1).mean()

    # Pine: var maxLowPrice = nz(low[1], low); var minHighPrice = nz(high[1], high)
    trend = 0
    next_trend = 0
    max_low_price = df["low"].iloc[0]
    min_high_price = df["high"].iloc[0]
    up = np.nan
    down = np.nan

    halftrend_arr = np.full(len(df), np.nan)
    trend_arr = np.zeros(len(df), dtype=int)
    buy_signal_arr = np.zeros(len(df), dtype=bool)
    sell_signal_arr = np.zeros(len(df), dtype=bool)

    for i in range(len(df)):
        high_price = df["highPrice"].iloc[i]
        low_price = df["lowPrice"].iloc[i]
        highma = df["highma"].iloc[i]
        lowma = df["lowma"].iloc[i]
        close = df["close"].iloc[i]

        prev_low = df["low"].iloc[i - 1] if i > 0 else df["low"].iloc[i]
        prev_high = df["high"].iloc[i - 1] if i > 0 else df["high"].iloc[i]

        atr_val = df["atr"].iloc[i]
        atr2 = atr_val / 2.0 if not np.isnan(atr_val) else 0.0

        prev_trend = trend
        prev_up = up
        prev_down = down

        if next_trend == 1:
            max_low_price = max(low_price, max_low_price)
            if highma < max_low_price and close < prev_low:
                trend = 1
                next_trend = 0
                min_high_price = high_price
        else:
            min_high_price = min(high_price, min_high_price)
            if lowma > min_high_price and close > prev_high:
                trend = 0
                next_trend = 1
                max_low_price = low_price

        arrow_up = np.nan
        arrow_down = np.nan

        if trend == 0:
            if i > 0 and prev_trend != 0:
                up = prev_down if not np.isnan(prev_down) else down
                arrow_up = up - atr2
            else:
                up = max_low_price if np.isnan(prev_up) else max(max_low_price, prev_up)
        else:
            if i > 0 and prev_trend != 1:
                down = prev_up if not np.isnan(prev_up) else up
                arrow_down = down + atr2
            else:
                down = (
                    min_high_price
                    if np.isnan(prev_down)
                    else min(min_high_price, prev_down)
                )

        halftrend_arr[i] = up if trend == 0 else down
        trend_arr[i] = trend

        if not np.isnan(arrow_up) and trend == 0 and prev_trend == 1:
            buy_signal_arr[i] = True
        if not np.isnan(arrow_down) and trend == 1 and prev_trend == 0:
            sell_signal_arr[i] = True

    df["halftrend"] = halftrend_arr
    df["trend"] = trend_arr
    df["buy_signal"] = buy_signal_arr
    df["sell_signal"] = sell_signal_arr
    df.drop(columns=["highPrice", "lowPrice", "highma", "lowma", "atr"], inplace=True)

    return df
