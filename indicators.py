import pandas as pd
import numpy as np

def calculate_atr(df: pd.DataFrame, period: int = 100) -> pd.Series:
    """Calculates True Range and Average True Range."""
    high = df['high']
    low = df['low']
    close = df['close']
    
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # Match Pine Script default RMA/EMA-style smoothing for ATR
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr

def calculate_half_trend(df: pd.DataFrame, amplitude: int = 10, channel_deviation: float = 3.0) -> pd.DataFrame:
    """
    Direct Python conversion of the Pine Script v6 HalfTrend implementation.
    Expects a pandas DataFrame containing 'open', 'high', 'low', 'close' data columns.
    """
    df = df.copy().reset_index(drop=True)
    n = len(df)
    
    # Pre-calculate rolling vectors to simulate Pine arrays
    atr2 = calculate_atr(df, 100) / 2
    dev = channel_deviation * atr2
    
    high_ma = df['high'].rolling(window=amplitude).mean()
    low_ma = df['low'].rolling(window=amplitude).mean()
    
    # Initialize state tracking containers
    trend = np.zeros(n, dtype=int)
    next_trend = np.zeros(n, dtype=int)
    max_low_price = np.zeros(n, dtype=float)
    min_high_price = np.zeros(n, dtype=float)
    
    up = np.zeros(n, dtype=float)
    down = np.zeros(n, dtype=float)
    atr_high = np.zeros(n, dtype=float)
    atr_low = np.zeros(n, dtype=float)
    
    buy_signal = np.zeros(n, dtype=bool)
    sell_signal = np.zeros(n, dtype=bool)

    # Initialize first row baseline data points
    max_low_price[0] = df['low'].iloc[0]
    min_high_price[0] = df['high'].iloc[0]

    for i in range(1, n):
        # Emulate high[math.abs(ta.highestbars(amplitude))]
        start_idx = max(0, i - amplitude + 1)
        high_window = df['high'].iloc[start_idx:i+1]
        low_window = df['low'].iloc[start_idx:i+1]
        
        high_price = high_window.max()
        low_price = low_window.min()
        
        # Bring previous bar states forward
        max_low_price[i] = max_low_price[i-1]
        min_high_price[i] = min_high_price[i-1]
        trend[i] = trend[i-1]
        next_trend[i] = next_trend[i-1]
        up[i] = up[i-1]
        down[i] = down[i-1]
        
        close_curr = df['close'].iloc[i]
        low_curr = df['low'].iloc[i]
        high_curr = df['high'].iloc[i]
        low_prev = df['low'].iloc[i-1]
        high_prev = df['high'].iloc[i-1]

        if next_trend[i-1] == 1:
            max_low_price[i] = max(low_price, max_low_price[i-1])
            if high_ma.iloc[i] < min_high_price[i] and close_curr < low_prev:
                trend[i] = 1
                next_trend[i] = 0
                min_high_price[i] = high_price
        else:
            min_high_price[i] = min(high_price, min_high_price[i-1])
            if low_ma.iloc[i] > max_low_price[i] and close_curr > high_prev:
                trend[i] = 0
                next_trend[i] = 1
                max_low_price[i] = low_price

        # Line Plots State Logic
        if trend[i] == 0:
            if trend[i-1] != 0:
                up[i] = down[i-1] if (up[i-1] == 0 or np.isnan(up[i-1])) else up[i-1]
            else:
                up[i] = max_low_price[i] if (up[i-1] == 0 or np.isnan(up[i-1])) else max(max_low_price[i], up[i-1])
            atr_high[i] = up[i] + dev.iloc[i]
            atr_low[i] = up[i] - dev.iloc[i]
        else:
            if trend[i-1] != 1:
                down[i] = up[i-1] if (down[i-1] == 0 or np.isnan(down[i-1])) else down[i-1]
            else:
                down[i] = min_high_price[i] if (down[i-1] == 0 or np.isnan(down[i-1])) else min(min_high_price[i], down[i-1])
            atr_high[i] = down[i] + dev.iloc[i]
            atr_low[i] = down[i] - dev.iloc[i]

        # Signal Flags Check
        if trend[i] == 0 and trend[i-1] == 1:
            buy_signal[i] = True
        if trend[i] == 1 and trend[i-1] == 0:
            sell_signal[i] = True

    df['trend'] = trend
    df['half_trend'] = np.where(trend == 0, up, down)
    df['buy_signal'] = buy_signal
    df['sell_signal'] = sell_signal
    
    return df
