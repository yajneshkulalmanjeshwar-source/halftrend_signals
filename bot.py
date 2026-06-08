"""
HalfTrend signal bot — Angel One data + ntfy alerts.

Run directly:  python bot.py
Force test:    FORCE_ALERT=1 python bot.py

Required env vars:
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET, NTFY_TOPIC
"""

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from angel_client import AngelOneClient
from indicators import calculate_half_trend

IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = os.environ.get("BOT_STATE_FILE", ".bot_state.json")
MIN_CANDLES = 120  # need ~100 for ATR warm-up


def get_config() -> dict:
    required = {
        "ANGEL_API_KEY": os.environ.get("ANGEL_API_KEY"),
        "ANGEL_CLIENT_CODE": os.environ.get("ANGEL_CLIENT_CODE"),
        "ANGEL_PIN": os.environ.get("ANGEL_PIN"),
        "ANGEL_TOTP_SECRET": os.environ.get("ANGEL_TOTP_SECRET"),
        "NTFY_TOPIC": os.environ.get("NTFY_TOPIC"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
    return required


def is_market_session(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    session_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    session_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return session_start <= now <= session_end


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def send_alert(topic: str, message: str, is_buy: bool) -> None:
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": "NIFTY 50 HALFTREND",
        "Priority": "5",
        "Tags": "chart_with_upwards_trend" if is_buy else "chart_with_downwards_trend",
    }
    requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)


def candles_to_dataframe(candles: list) -> pd.DataFrame:
    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    return df


def analyze(force_alert: bool = False) -> dict:
    cfg = get_config()
    state = load_state()
    last_signal_time = state.get("last_signal_time")

    client = AngelOneClient(
        api_key=cfg["ANGEL_API_KEY"],
        client_code=cfg["ANGEL_CLIENT_CODE"],
        pin=cfg["ANGEL_PIN"],
        totp_secret=cfg["ANGEL_TOTP_SECRET"],
    )

    try:
        client.login()
        candles = client.get_nifty_candles(interval="FIVE_MINUTE", days_back=5)
        df = candles_to_dataframe(candles)

        if len(df) < MIN_CANDLES:
            return {
                "status": "not_enough_data",
                "candles": len(df),
                "required": MIN_CANDLES,
            }

        processed = calculate_half_trend(df, amplitude=10, channel_deviation=3.0)
        if len(processed) < 2:
            return {"status": "not_enough_data"}

        last_closed = processed.iloc[-2]
        bar_time = str(last_closed["time"])
        close_price = float(last_closed["close"])
        bullish = int(last_closed.get("trend", 0)) == 1

        if force_alert:
            trend_label = "BULLISH" if bullish else "BEARISH"
            send_alert(
                cfg["NTFY_TOPIC"],
                f"TEST OK\nTrend: {trend_label}\nPrice: {close_price:.2f}\nTime: {bar_time}",
                is_buy=bullish,
            )
            return {
                "status": "test_alert_sent",
                "price": close_price,
                "time": bar_time,
                "trend": trend_label,
            }

        if bar_time != last_signal_time:
            if last_closed["buy_signal"]:
                send_alert(
                    cfg["NTFY_TOPIC"],
                    f"BUY SIGNAL\nPrice: {close_price:.2f}\nTime: {bar_time}",
                    is_buy=True,
                )
                last_signal_time = bar_time
            elif last_closed["sell_signal"]:
                send_alert(
                    cfg["NTFY_TOPIC"],
                    f"SELL SIGNAL\nPrice: {close_price:.2f}\nTime: {bar_time}",
                    is_buy=False,
                )
                last_signal_time = bar_time

        if last_signal_time != state.get("last_signal_time"):
            state["last_signal_time"] = last_signal_time
            save_state(state)

        return {
            "status": "success",
            "analyzed_time": bar_time,
            "price": close_price,
            "buy_signal": bool(last_closed["buy_signal"]),
            "sell_signal": bool(last_closed["sell_signal"]),
        }
    finally:
        client.logout()


def main() -> int:
    force = os.environ.get("FORCE_ALERT", "").lower() in ("1", "true", "yes")
    now = datetime.now(IST)

    if not force and not is_market_session(now):
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}] Outside market hours — skipping.")
        return 0

    try:
        result = analyze(force_alert=force)
        print(result)
        if result.get("status") == "error":
            return 1
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
