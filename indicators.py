import pandas as pd
import numpy as np

def calculate_half_trend(df: pd.DataFrame, amplitude: int = 10, channel_deviation: float = 3.0) -> pd.DataFrame:
    """
    Calculates the HalfTrend indicator matching the original TradingView Pine Script.
    Returns the dataframe with 'halftrend', 'trend', 'buy_signal', and 'sell_signal' columns.
    """
    df = df.copy()
    
    # Ensure columns are lowercase
    df.columns = [col.lower() for col in df.columns]
    
    # --- 1. Calculate ATR (TradingView uses RMA/Wilder's Smoothing for ATR) ---
    prev_close = df['close'].shift(1)
    tr0 = abs(df['high'] - df['low'])
    tr1 = abs(df['high'] - prev_close)
    tr2 = abs(df['low'] - prev_close)
    tr = pd.concat([tr0, tr1, tr2], axis=1).max(axis=1)
    
    df['atr'] = tr.ewm(alpha=1/100, min_periods=100, adjust=False).mean()
    
    # --- 2. Pre-calculate Rolling Values ---
    df['highPrice'] = df['high'].rolling(window=amplitude, min_periods=1).max()
    df['lowPrice'] = df['low'].rolling(window=amplitude, min_periods=1).min()
    df['highma'] = df['high'].rolling(window=amplitude, min_periods=1).mean()
    df['lowma'] = df['low'].rolling(window=amplitude, min_periods=1).mean()

    # --- 3. Initialize State Variables ---
    trend = 0
    nextTrend = 0
    maxLowPrice = df['low'].iloc[0]
    minHighPrice = df['high'].iloc[0]
    up = 0.0
    down = 0.0

    # Arrays to store loop results efficiently
    halftrend_arr = np.full(len(df), np.nan)
    trend_arr = np.zeros(len(df), dtype=int)
    buy_signal_arr = np.zeros(len(df), dtype=bool)
    sell_signal_arr = np.zeros(len(df), dtype=bool)

    # --- 4. Main State Machine Loop ---
    for i in range(1, len(df)):
        highPrice = df['highPrice'].iloc[i]
        lowPrice = df['lowPrice'].iloc[i]
        highma = df['highma'].iloc[i]
        lowma = df['lowma'].iloc[i]
        close = df['close'].iloc[i]
        
        prev_low = df['low'].iloc[i-1]
        prev_high = df['high'].iloc[i-1]

        atr2 = df['atr'].iloc[i] / 2.0 if not np.isnan(df['atr'].iloc[i]) else 0.0
        dev = channel_deviation * atr2

        prev_trend = trend
        prev_up = up
        prev_down = down

        # --- Trend Direction Logic ---
        if nextTrend == 1:
            maxLowPrice = max(lowPrice, maxLowPrice)
            if highma < maxLowPrice and close < prev_low:
                trend = 1
                nextTrend = 0
                minHighPrice = highPrice
        else:
            minHighPrice = min(highPrice, minHighPrice)
            if lowma > minHighPrice and close > prev_high:
                trend = 0
                nextTrend = 1
                maxLowPrice = lowPrice

        # --- Up / Down Channel Calculation ---
        arrowUp = np.nan
        arrowDown = np.nan

        if trend == 0:
            if prev_trend != 0:
                up = prev_down
                arrowUp = up - atr2
            else:
                up = max(maxLowPrice, prev_up) if prev_up != 0.0 else maxLowPrice
        else:
            if prev_trend != 1:
                down = prev_up
                arrowDown = down + atr2
            else:
                down = min(minHighPrice, prev_down) if prev_down != 0.0 else minHighPrice

        # --- Output Storage ---
        halftrend_arr[i] = up if trend == 0 else down
        trend_arr[i] = trend

        # Signals
        if not np.isnan(arrowUp) and trend == 0 and prev_trend == 1:
            buy_signal_arr[i] = True

        if not np.isnan(arrowDown) and trend == 1 and prev_trend == 0:
            sell_signal_arr[i] = True

    # --- 5. Assign to DataFrame and Cleanup ---
    df['halftrend'] = halftrend_arr
    df['trend'] = trend_arr
    df['buy_signal'] = buy_signal_arr
    df['sell_signal'] = sell_signal_arr

    df.drop(columns=['highPrice', 'lowPrice', 'highma', 'lowma'], inplace=True)

    return df