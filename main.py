import asyncio
import requests
import pandas as pd
from datetime import datetime, timedelta
from fastapi import FastAPI
from indicators import calculate_half_trend

app = FastAPI()

# --- CONFIGURATION ---
NTFY_TOPIC = "my_secret_nifty_bot_88"  # Your ntfy app topic name
TWELVEDATA_API_KEY = "6113e24b65ed4949b6204e7f8308ce7d"  # Put your free key here
SYMBOL = "NIFTY:NSE"  # Twelve Data format for NSE Nifty 50

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

def fetch_and_analyze_data(force_alert=False):
    """Fetches data from Twelve Data, processes it, and checks for signals."""
    global last_signal_time
    
    url = f"https://api.twelvedata.com/time_series?symbol={SYMBOL}&interval=5min&outputsize=150&apikey={TWELVEDATA_API_KEY}"
    
    response = requests.get(url)
    data = response.json()
    
    if "status" in data and data["status"] == "error":
        print(f"❌ API Error: {data.get('message')}")
        return {"status": "error", "message": data.get('message')}
        
    if "values" not in data:
        print("📭 No data available or market closed.")
        return {"status": "no_data"}

    # Convert JSON to DataFrame
    df = pd.DataFrame(data['values'])
    
    # Twelve Data sends the newest data FIRST. We must reverse it for the indicator.
    df = df.iloc[::-1].reset_index(drop=True)
    
    # Rename datetime to time and convert prices to floats
    df.rename(columns={'datetime': 'time'}, inplace=True)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
        
    candle_count = len(df)
    print(f"✅ Data fetched: {candle_count} candles")
    
    # Calculate HalfTrend
    processed_df = calculate_half_trend(df, amplitude=10, channel_deviation=2.0)
    
    if len(processed_df) >= 2:
        last_closed_bar = processed_df.iloc[-2]
        current_bar_time = str(last_closed_bar['time'])
        
        # If this is a manual test, force a notification regardless of a new signal
        if force_alert:
            current_trend = "BULLISH 🟢" if last_closed_bar.get('halftrend_up') else "BEARISH 🔴"
            msg = f"🧪 TEST SUCCESSFUL\nCurrent Trend: {current_trend}\nPrice: {last_closed_bar['close']:.2f}\nTime: {current_bar_time}"
            send_alert(msg, is_buy=True)
            return {"status": "test_alert_sent", "price": last_closed_bar['close']}

        # Normal Bot Logic: Only alert on NEW signals
        if current_bar_time != last_signal_time:
            if last_closed_bar['buy_signal']:
                msg = f"BUY SIGNAL\nPrice: {last_closed_bar['close']:.2f}\nTime: {current_bar_time}"
                send_alert(msg, is_buy=True)
                last_signal_time = current_bar_time
                
            elif last_closed_bar['sell_signal']:
                msg = f"SELL SIGNAL\nPrice: {last_closed_bar['close']:.2f}\nTime: {current_bar_time}"
                send_alert(msg, is_buy=False)
                last_signal_time = current_bar_time
                
        return {"status": "success", "analyzed_time": current_bar_time}
    else:
        return {"status": "not_enough_data"}

async def run_trading_bot():
    """Asynchronous loop that syncs perfectly with 5-minute candle closes."""
    while True:
        try:
            # Calculate exactly how many seconds until the next 5-minute mark
            now = datetime.now()
            minutes_to_wait = 5 - (now.minute % 5)
            
            target_time = now.replace(minute=(now.minute + minutes_to_wait) % 60, second=0, microsecond=0)
            if minutes_to_wait + now.minute >= 60:
                target_time = target_time + timedelta(hours=1)
                
            sleep_seconds = (target_time - now).total_seconds()
            
            if sleep_seconds > 0:
                print(f"[{now.strftime('%H:%M:%S')}] ⏰ Waiting {sleep_seconds:.0f}s until candle close...")
                await asyncio.sleep(sleep_seconds)
            
            print(f"🔔 Candle closed! Waiting 10s for API data refresh...")
            # Wait 10 seconds to ensure Twelve Data has processed the newly closed candle
            await asyncio.sleep(10)
            
            print(f"📊 Fetching data & checking signals...")
            fetch_and_analyze_data(force_alert=False)

        except Exception as e:
            print(f"❌ Error in trading loop: {e}")
            await asyncio.sleep(60)

# --- FASTAPI ENDPOINTS ---

@app.on_event("startup")
async def startup_event():
    """Starts the bot natively in FastAPI's async event loop."""
    asyncio.create_task(run_trading_bot())
    print("✅ Web server started. Background sync task launched!")

@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return {"status": "Bot is running with Twelve Data!", "interval": "5 minutes"}

@app.get("/ping")
def ping():
    """Endpoint for cron-job.org to keep Render awake."""
    return {"status": "Awake"}

@app.get("/test")
def test_bot_pipeline():
    """MANUAL TEST ENDPOINT: Visits this URL to force a data pull and mobile alert."""
    print("🧪 Manual test triggered via /test endpoint")
    result = fetch_and_analyze_data(force_alert=True)
    return {
        "message": "Test triggered. Check your phone!",
        "api_result": result
    }