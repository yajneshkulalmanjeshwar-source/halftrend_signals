import time
import threading
import requests
import pandas as pd
import yfinance as yf
from fastapi import FastAPI
from indicators import calculate_half_trend

app = FastAPI()

# --- CONFIGURATION ---
NTFY_TOPIC = "halftrend_signals"  # Replace with your actual ntfy app topic name
TICKER_SYMBOL = "^NSEI"  # Yahoo Finance symbol for Nifty 50
CHECK_INTERVAL_SECONDS = 300  # Check every 5 minutes

# Global variable to remember the last signal time so it doesn't spam you
last_signal_time = None

def send_alert(message: str, is_buy: bool):
    """Sends a push notification to your iPhone via ntfy."""
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    headers = {
        "Title": "🚨 NIFTY 50 HALFTREND",
        "Priority": "5",
        "Tags": "chart_with_upwards_trend" if is_buy else "chart_with_downwards_trend"
    }
    try:
        requests.post(url, data=message.encode('utf-8'), headers=headers)
        print(f"Alert sent: {message}")
    except Exception as e:
        print(f"Failed to send alert: {e}")

def run_trading_bot():
    """Background loop that fetches data, checks HalfTrend, and sends alerts."""
    global last_signal_time
    
    while True:
        try:
            print(f"Fetching latest data for {TICKER_SYMBOL}...")
            # Fetch 5 days of data, 5-minute candles
            nifty = yf.Ticker(TICKER_SYMBOL)
            df = nifty.history(period="5d", interval="5m")
            
            if not df.empty:
                # Format dataframe for our indicator function
                df = df.reset_index()
                df.rename(columns={'Datetime': 'time'}, inplace=True)
                
                # Apply HalfTrend (Amplitude 10, Channel 2)
                processed_df = calculate_half_trend(df, amplitude=10, channel_deviation=2.0)
                
                # Look at the last fully closed candle (index -2)
                last_closed_bar = processed_df.iloc[-2]
                current_bar_time = str(last_closed_bar['time'])
                
                # Check for signals, ensuring we haven't already alerted for this specific timestamp
                if current_bar_time != last_signal_time:
                    
                    if last_closed_bar['buy_signal']:
                        msg = f"BUY SIGNAL\nPrice: {last_closed_bar['close']:.2f}\nTime: {current_bar_time}"
                        send_alert(msg, is_buy=True)
                        last_signal_time = current_bar_time
                        
                    elif last_closed_bar['sell_signal']:
                        msg = f"SELL SIGNAL\nPrice: {last_closed_bar['close']:.2f}\nTime: {current_bar_time}"
                        send_alert(msg, is_buy=False)
                        last_signal_time = current_bar_time

        except Exception as e:
            print(f"Error in trading loop: {e}")
            
        # Sleep until the next 5-minute check
        time.sleep(CHECK_INTERVAL_SECONDS)

# --- FASTAPI ENDPOINTS ---

@app.on_event("startup")
def startup_event():
    """Starts the background bot loop when the server boots up."""
    thread = threading.Thread(target=run_trading_bot, daemon=True)
    thread.start()
    print("Trading bot background thread started.")

@app.get("/")
def read_root():
    return {"status": "Bot is running perfectly on Yahoo Finance."}

@app.get("/ping")
def ping():
    """Endpoint for cron-job.org to keep Render awake."""
    return {"status": "Awake"}
