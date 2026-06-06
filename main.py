import sys
import os
# Force Python to look in the site-packages directory
sys.path.append(os.path.abspath("/opt/render/project/src/.venv/lib/python3.12/site-packages"))

import asyncio
import requests
import pandas as pd
from datetime import datetime, timedelta
from fastapi import FastAPI
from tvdatafeed.main import TvDatafeed, Interval
from indicators import calculate_half_trend

app = FastAPI()

# --- CONFIGURATION ---
NTFY_TOPIC = "my_secret_nifty_bot_88"  # Your ntfy app topic name
TV_SYMBOL = "NIFTY"                    # TradingView symbol
TV_EXCHANGE = "NSE"                    # TradingView exchange

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

async def run_trading_bot():
    """Asynchronous loop that syncs perfectly with 5-minute candle closes."""
    global last_signal_time
    
    # --- TRADINGVIEW INITIALIZATION ---
    print(f"🔐 Initializing TradingView Guest Session...")
    tv = TvDatafeed()
    print(f"✅ Session initialized. Ready to fetch data.")
    # ----------------------------------
    
    rate_limit_backoff = 60  # Start with 60 seconds
    consecutive_rate_limits = 0
    
    while True:
        try:
            # Reset backoff if we successfully fetched data
            consecutive_rate_limits = 0
            rate_limit_backoff = 60
            
            # Calculate exactly how many seconds until the next 5-minute mark
            now = datetime.now()
            minutes_to_wait = 5 - (now.minute % 5)
            
            target_time = now.replace(minute=(now.minute + minutes_to_wait) % 60, second=0, microsecond=0)
            if minutes_to_wait + now.minute >= 60:
                target_time = target_time + timedelta(hours=1)
                
            sleep_seconds = (target_time - now).total_seconds()
            
            if sleep_seconds > 0:
                print(f"[{now.strftime('%H:%M:%S')}] ⏰ Waiting {sleep_seconds:.0f}s until candle close at {target_time.strftime('%H:%M:%S')}...")
                await asyncio.sleep(sleep_seconds)
            
            print(f"🔔 Candle closed at {target_time.strftime('%H:%M:%S')}!")
            
            # Wait an extra 5 seconds to ensure TradingView has fully updated its database
            print(f"⏳ Waiting 5s for TradingView data refresh...")
            await asyncio.sleep(5)
            
            print(f"📊 Fetching data & checking signals...")
            
            # Fetch the last 150 5-minute candles using TradingView
            df = tv.get_hist(symbol=TV_SYMBOL, exchange=TV_EXCHANGE, interval=Interval.in_5_minute, n_bars=150)
            
            if df is not None and not df.empty:
                candle_count = len(df)
                print(f"✅ Data fetched: {candle_count} candles")
                
                df = df.reset_index()
                # TradingView returns 'datetime', we rename it to 'time' to match indicators.py
                df.rename(columns={'datetime': 'time'}, inplace=True)
                
                processed_df = calculate_half_trend(df, amplitude=10, channel_deviation=2.0)
                
                if len(processed_df) >= 2:
                    last_closed_bar = processed_df.iloc[-2]
                    current_bar_time = str(last_closed_bar['time'])
                    
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
                print("📭 No data available (Market closed or off-hours)")

        except Exception as e:
            error_msg = str(e)
            
            # Keep your exponential backoff in case TradingView ever drops connection
            if "Too Many Requests" in error_msg or "Rate limited" in error_msg or "429" in error_msg:
                consecutive_rate_limits += 1
                rate_limit_backoff = 60 * (2 ** (consecutive_rate_limits - 1))  # Exponential backoff
                print(f"⚠️ Rate limited (attempt #{consecutive_rate_limits})!")
                print(f"⏳ Waiting {rate_limit_backoff}s before retry (exponential backoff)...")
                await asyncio.sleep(rate_limit_backoff)
            else:
                print(f"❌ Error in trading loop: {e}")
                import traceback
                traceback.print_exc()
                print(f"⏳ Waiting 60s before retry...")
                await asyncio.sleep(60)

# --- FASTAPI ENDPOINTS ---

@app.on_event("startup")
async def startup_event():
    """Starts the bot natively in FastAPI's async event loop."""
    asyncio.create_task(run_trading_bot())
    print("✅ Web server started. Background sync task launched!")

@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    """Respond to both GET and HEAD requests (for Render health checks)."""
    return {"status": "Bot is perfectly synced and running with TradingView!", "interval": "5 minutes (async-synced)"}

@app.get("/ping")
def ping():
    """Endpoint for cron-job.org to keep Render awake."""
    return {"status": "Awake"}