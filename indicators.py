import pandas as pd
import numpy as np

def calculate_half_trend(df: pd.DataFrame, amplitude: int = 10, channel_deviation: float = 2.0) -> pd.DataFrame:
    """
    Calculates the HalfTrend indicator using ATR and High/Low prices.
    Returns the dataframe with 'buy_signal' and 'sell_signal' boolean columns.
    """
    # Ensure columns are lowercase
    df.columns = [col.lower() for col in df.columns]
    
    # Calculate ATR (Average True Range) - requires 100 candles minimum for meaningful values
    df['prev_close'] = df['close'].shift(1)
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['prev_close'])
    df['tr2'] = abs(df['low'] - df['prev_close'])
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=100).mean()  # ATR-100: requires 100 candles to warm up
    # Note: Signals before candle #100 may be unreliable as ATR is still calculating
    
    # HalfTrend logic setup
    df['trend'] = 0
    df['halftrend'] = 0.0
    df['buy_signal'] = False
    df['sell_signal'] = False
    
    up = 0.0
    down = 0.0
    trend = 0
    
    for i in range(1, len(df)):
        dev = channel_deviation * df['atr'].iloc[i] / 2.0
        high_price = df['high'].iloc[max(0, i-amplitude):i].max()
        low_price = df['low'].iloc[max(0, i-amplitude):i].min()
        
        if trend == 0:
            if df['close'].iloc[i] > down:
                trend = 1
                df.at[df.index[i], 'buy_signal'] = True
        else:
            if df['close'].iloc[i] < up:
                trend = 0
                df.at[df.index[i], 'sell_signal'] = True
        
        if trend == 1:
            up = high_price + dev
            down = low_price - dev
            df.at[df.index[i], 'halftrend'] = down
        else:
            up = high_price + dev
            down = low_price - dev
            df.at[df.index[i], 'halftrend'] = up
        
        df.at[df.index[i], 'trend'] = trend
    
    return df
