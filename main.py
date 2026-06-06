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
CHECK_INTERVAL_SECONDS = 600  # Check every 10 minutes to avoid rate limiting (was 5 min)
MAX_RETRIES = 3
RETRY_DELAY_BASE = 5  # Start with 5 seconds, exponential backoff

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
        requests.post(url, data=message.encode('utf-8'), headers=headers, timeout=5)
        print(f"Alert sent: {message}")
    except Exception as e:
        print(f"Failed to send alert: {e}")

def fetch_data_with_retry():
    """Fetches Nifty 50 data from Yahoo Finance with exponential backoff retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            print(f"Fetching latest data for {TICKER_SYMBOL}... (Attempt {attempt + 1}/{MAX_RETRIES})")
            # Fetch 5 days of data, 5-minute candles
            nifty = yf.Ticker(TICKER_SYMBOL)
            df = nifty.history(period="5d", interval="5m")
            
            if not df.empty:
                return df
            else:
                print("Warning: Empty dataframe returned from Yahoo Finance")
                
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check for rate limiting specifically
            if "too many requests" in error_msg or "rate limit" in error_msg or "429" in error_msg:
                wait_time = RETRY_DELAY_BASE * (2 ** attempt)  # Exponential backoff
                print(f"⏳ Rate limited. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue
            elif attempt < MAX_RETRIES - 1:
                print(f"⚠️ Error: {e}. Retrying in 10 seconds...")
                time.sleep(10)
                continue
            else:
                print(f"❌ Failed after {MAX_RETRIES} attempts: {e}")
                return None
    
    return None

def run_trading_bot():
    """Background loop that fetches data, checks HalfTrend, and sends alerts."""
    global last_signal_time
    
    # Add initial delay to allow server to stabilize
    print("Waiting 30 seconds before first fetch...")
    time.sleep(30)
    
    while True:
        try:
            df = fetch_data_with_retry()
            
            if df is not None and not df.empty:
                # Format dataframe for our indicator function
                df = df.reset_index()
                df.rename(columns={'Datetime': 'time'}, inplace=True)
                
                # Apply HalfTrend (Amplitude 10, Channel 2)
                processed_df = calculate_half_trend(df, amplitude=10, channel_deviation=2.0)
                
                # Look at the last fully closed candle (index -2)
                if len(processed_df) >= 2:
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
                else:
                    print("Warning: Not enough data to analyze (need at least 2 candles)")

        except Exception as e:
            print(f"Error in trading loop: {e}")
            import traceback
            traceback.print_exc()
            
        # Sleep until the next check (10 minutes to avoid rate limiting)
        print(f"⏸️ Next check in {CHECK_INTERVAL_SECONDS} seconds...")
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
