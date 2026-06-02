import requests
from fastapi import FastAPI
from config import Config
from angel_client import AngelManager
from indicators import calculate_half_trend

app = FastAPI(title="Nifty HalfTrend Alarm Backend Engine")
angel_manager = AngelManager()

def dispatch_ntfy_alert(message: str, is_buy: bool):
    """Sends immediate high-priority alert parameters to iOS ntfy client app."""
    url = f"https://ntfy.sh/{Config.NTFY_TOPIC}"
    headers = {
        "Title": "🚨 NIFTY 50 HALFTREND SIGNAL",
        "Priority": "5",  # Priority 5 forces max alarm execution/volume levels on your lockscreen
        "Tags": "chart_with_upwards_trend,rotating_light" if is_buy else "chart_with_downwards_trend,rotating_light"
    }
    try:
        response = requests.post(url, data=message.encode('utf-8'), headers=headers, timeout=5)
        print(f"Notification status successfully updated to ntfy server: {response.status_code}")
    except Exception as err:
        print(f"Failed to post system update packet down to phone: {err}")

def evaluate_signals_on_close(df):
    """Calculates the indicators and pushes updates if a true crossover happened."""
    processed_df = calculate_half_trend(df, amplitude=10, channel_deviation=3.0)
    last_completed_bar = processed_df.iloc[-1]
    
    if last_completed_bar['buy_signal']:
        msg = f"BUY SIGNAL CONFIRMED\nPrice: {last_completed_bar['close']}\nTime: {last_completed_bar['time']}"
        dispatch_ntfy_alert(msg, is_buy=True)
        
    elif last_completed_bar['sell_signal']:
        msg = f"SELL SIGNAL CONFIRMED\nPrice: {last_completed_bar['close']}\nTime: {last_completed_bar['time']}"
        dispatch_ntfy_alert(msg, is_buy=False)

@app.on_event("startup")
def start_trading_bot():
    print("Initializing Market System Links...")
    try:
        # Start streaming calculations on startup event loop
        import threading
        bot_thread = threading.Thread(target=angel_manager.start_streaming, args=(evaluate_signals_on_close,), daemon=True)
        bot_thread.start()
    except Exception as e:
        print(f"Unable to launch streaming links automatically: {e}")

@app.get("/ping")
def health_check_ping():
    """Endpoint targets for keeping the Render instance fully alert via external cron tasks."""
    return {"status": "online", "message": "Engine running actively inside memory allocations."}
