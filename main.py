import asyncio
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from fastapi import FastAPI
from indicators import calculate_half_trend

app = FastAPI()

# --- CONFIGURATION ---
NTFY_TOPIC = "halftrend_signals"  # Replace with your actual ntfy app topic name
TICKER_SYMBOL = "^NSEI"  # Yahoo Finance symbol for Nifty 50

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
    
    while True:
        try:
            # 1. Calculate exactly how many seconds until the next 5-minute mark
            now = datetime.now()
            minutes_to_wait = 5 - (now.minute % 5)
            
            # 2. Calculate the exact target time (e.g., 09:20:00)
            target_time = now.replace(minute=(now.minute + minutes_to_wait) % 60, second=0, microsecond=0)
            if minutes_to_wait + now.minute >= 60:
                target_time = target_time + timedelta(hours=1)
                
            sleep_seconds = (target_time - now).total_seconds()
            
            # 3. Wait until the candle closes using ASYNC sleep (doesn't block Render!)
            if sleep_seconds > 0:
                print(f"[{now.strftime('%H:%M:%S')}] ⏰ Waiting {sleep_seconds:.0f}s until candle close at {target_time.strftime('%H:%M:%S')}...")
                await asyncio.sleep(sleep_seconds)
            
            print(f"🔔 Candle closed at {target_time.strftime('%H:%M:%S')}!")
            
            # 4. Wait an extra 5 seconds to ensure Yahoo Finance has fully updated its database
            print(f"⏳ Waiting 5s for Yahoo Finance data refresh...")
            await asyncio.sleep(5)
            
            # 5. Fetch Data & Check Signals
            print(f"📊 Fetching data & checking signals...")
            nifty = yf.Ticker(TICKER_SYMBOL)
            df = nifty.history(period="10d", interval="5m")
            
            if not df.empty:
                candle_count = len(df)
                print(f"✅ Data fetched: {candle_count} candles")
                
                df = df.reset_index()
                df.rename(columns={'Datetime': 'time'}, inplace=True)
                
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
            print(f"❌ Error in trading loop: {e}")
            import traceback
            traceback.print_exc()
            print(f"⏳ Waiting 60s before retry...")
            await asyncio.sleep(60)  # If it fails, wait 1 minute and try again

# --- FASTAPI ENDPOINTS ---

@app.on_event("startup")
async def startup_event():
    """Starts the bot natively in FastAPI's async event loop."""
    asyncio.create_task(run_trading_bot())
    print("✅ Web server started. Background sync task launched!")

@app.get("/")
def read_root():
    return {"status": "Bot is perfectly synced and running!", "interval": "5 minutes (async-synced)"}

@app.get("/ping")
def ping():
    """Endpoint for cron-job.org to keep Render awake."""
    return {"status": "Awake"}
