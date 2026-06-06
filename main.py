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
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # Start with 2 seconds for quick retries

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
        print(f"✅ Alert sent: {message}")
    except Exception as e:
        print(f"❌ Failed to send alert: {e}")

def fetch_data_with_retry():
    """Fetches Nifty 50 data from Yahoo Finance with retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            print(f"📊 Fetching {TICKER_SYMBOL}... (Attempt {attempt + 1}/{MAX_RETRIES})")
            nifty = yf.Ticker(TICKER_SYMBOL)
            df = nifty.history(period="5d", interval="5m")
            
            if df is not None and not df.empty:
                print(f"✅ Data fetched: {len(df)} candles")
                return df
            else:
                # Market closed or no data - this is normal during off-hours
                print("⏸️ No data available (Market closed or off-hours) - will retry in next cycle")
                return None
                
        except Exception as e:
            error_msg = str(e).lower()
            print(f"⚠️ Error on attempt {attempt + 1}: {e}")
            
            # Check for rate limiting specifically
            if "too many requests" in error_msg or "rate limit" in error_msg or "429" in error_msg:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY_BASE * (2 ** attempt)  # 2s, 4s, 8s
                    print(f"⏳ Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"❌ Rate limited after {MAX_RETRIES} attempts. Will try again in next cycle.")
                    return None
            elif attempt < MAX_RETRIES - 1:
                # Other errors - quick retry
                print(f"🔄 Retrying in 2 seconds...")
                time.sleep(2)
                continue
            else:
                print(f"❌ Failed after {MAX_RETRIES} attempts")
                return None
    
    return None

def run_trading_bot():
    """Background loop that fetches data, checks HalfTrend, and sends alerts."""
    global last_signal_time
    
    # Small initial delay to allow server to stabilize
    print("⏳ Starting trading bot... (Initial 5 second delay)")
    time.sleep(5)
    
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
                    print("⚠️ Not enough data to analyze")
            else:
                print("📭 Skipping analysis - no data available")

        except Exception as e:
            print(f"❌ Error in trading loop: {e}")
            import traceback
            traceback.print_exc()
            
        # Sleep until the next 5-minute check
        print(f"⏰ Next check in {CHECK_INTERVAL_SECONDS} seconds...\n")
        time.sleep(CHECK_INTERVAL_SECONDS)

# --- FASTAPI ENDPOINTS ---

@app.on_event("startup")
def startup_event():
    """Starts the background bot loop when the server boots up."""
    thread = threading.Thread(target=run_trading_bot, daemon=True)
    thread.start()
    print("✅ Trading bot background thread started.")

@app.get("/")
def read_root():
    return {"status": "Bot is running perfectly on Yahoo Finance.", "interval": "5 minutes"}

@app.get("/ping")
def ping():
    """Endpoint for cron-job.org to keep Render awake."""
    return {"status": "Awake"}
