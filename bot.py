"""
HalfTrend signal bot — Angel One data + ntfy alerts.

Scheduling: GitHub Actions cron in market-bot.yml (no external cron site needed).

Run locally:  python bot.py
Force test:    FORCE_ALERT=1 python bot.py

Required env vars:
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET, NTFY_TOPIC
  NTFY_TOPIC example: my_secret_nifty_bot_88
"""

import json
import os
import sys
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from angel_client import AngelOneClient
from indicators import calculate_half_trend

IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = os.environ.get("BOT_STATE_FILE", ".bot_state.json")
MIN_CANDLES = 120  # need ~100 bars for ATR warm-up
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
# Allow one extra run after 15:30 to process the final 15:25 candle.
BOT_RUN_END = time(15, 35)


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


def _to_ist(now: datetime) -> datetime:
    return now.astimezone(IST)


def is_market_session(now: datetime | None = None) -> bool:
    """True during NSE cash session plus a short post-close window."""
    now = _to_ist(now or datetime.now(IST))
    if now.weekday() >= 5:
        return False
    current = now.time()
    return MARKET_OPEN <= current <= BOT_RUN_END


def is_market_candle(ts: pd.Timestamp) -> bool:
    ts = ts.tz_convert(IST) if ts.tzinfo else ts.tz_localize(IST)
    if ts.weekday() >= 5:
        return False
    candle_time = ts.time()
    return MARKET_OPEN <= candle_time <= MARKET_CLOSE


def last_closed_candle_open(now: datetime | None = None) -> datetime | None:
    """
    Open time of the latest fully closed NSE 5-minute candle in IST.

    NSE 5m candles: 09:15, 09:20, 09:25, ... 15:25 (close at 15:30).
    """
    now = _to_ist(now or datetime.now(IST))
    if now.weekday() >= 5:
        return None

    market_open = now.replace(
        hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
    )
    market_close = now.replace(
        hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute, second=0, microsecond=0
    )

    if now < market_open + timedelta(minutes=5):
        return None
    if now >= market_close:
        return market_close - timedelta(minutes=5)

    elapsed_minutes = int((now - market_open).total_seconds() // 60)
    period = elapsed_minutes // 5
    if period < 1:
        return None
    return market_open + timedelta(minutes=5 * (period - 1))


def format_bar_time(ts) -> str:
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(IST)
    else:
        stamp = stamp.tz_convert(IST)
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"alerted": {}}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"alerted": {}}

    if "alerted" not in state:
        legacy = state.get("last_signal_time")
        state = {"alerted": {}}
        if legacy:
            state["alerted"][legacy] = "unknown"
    return state


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def send_alert(topic: str, message: str, is_buy: bool) -> None:
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": "NIFTY 50 HALFTREND",
        "Priority": "5",
        "Tags": "chart_with_upwards_trend" if is_buy else "chart_with_downwards_trend",
    }
    response = requests.post(
        url, data=message.encode("utf-8"), headers=headers, timeout=15
    )
    response.raise_for_status()


def candles_to_dataframe(candles: list) -> pd.DataFrame:
    df = pd.DataFrame(
        candles, columns=["time", "open", "high", "low", "close", "volume"]
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["time"])
    if df["time"].dt.tz is None:
        df["time"] = df["time"].dt.tz_localize(IST)
    else:
        df["time"] = df["time"].dt.tz_convert(IST)
    df = df.sort_values("time").reset_index(drop=True)
    return df[df["time"].map(is_market_candle)].reset_index(drop=True)


def drop_forming_candle(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    expected_open = last_closed_candle_open(now)
    if expected_open is None:
        return df.iloc[0:0]
    return df[df["time"] <= expected_open].reset_index(drop=True)


def find_bar_row(df: pd.DataFrame, bar_open: datetime) -> pd.Series | None:
    bar_key = format_bar_time(bar_open)
    df_keys = df["time"].map(format_bar_time)
    matches = df[df_keys == bar_key]
    if matches.empty:
        tolerance = pd.Timedelta(minutes=1)
        near = df[(df["time"] >= bar_open - tolerance) & (df["time"] <= bar_open + tolerance)]
        if near.empty:
            return None
        return near.iloc[-1]
    return matches.iloc[-1]


def collect_pending_alerts(
    processed: pd.DataFrame, alerted: dict[str, str], now: datetime
) -> list[dict]:
    """
    Return un-sent buy/sell signals up to the latest closed IST candle.
    Catches up if GitHub Actions runs a few minutes late.
    """
    expected_open = last_closed_candle_open(now)
    if expected_open is None:
        return []

    closed = processed[processed["time"] <= expected_open]
    signal_rows = closed[closed["buy_signal"] | closed["sell_signal"]]
    pending: list[dict] = []

    for _, row in signal_rows.iterrows():
        bar_time = format_bar_time(row["time"])
        if row["buy_signal"] and alerted.get(bar_time) != "buy":
            pending.append(
                {
                    "type": "buy",
                    "bar_time": bar_time,
                    "price": float(row["close"]),
                }
            )
        elif row["sell_signal"] and alerted.get(bar_time) != "sell":
            pending.append(
                {
                    "type": "sell",
                    "bar_time": bar_time,
                    "price": float(row["close"]),
                }
            )

    return pending


def analyze(force_alert: bool = False) -> dict:
    cfg = get_config()
    state = load_state()
    alerted: dict[str, str] = state.setdefault("alerted", {})
    now = datetime.now(IST)

    client = AngelOneClient(
        api_key=cfg["ANGEL_API_KEY"],
        client_code=cfg["ANGEL_CLIENT_CODE"],
        pin=cfg["ANGEL_PIN"],
        totp_secret=cfg["ANGEL_TOTP_SECRET"],
    )

    try:
        client.login()
        candles = client.get_nifty_candles(interval="FIVE_MINUTE", days_back=10)
        df = candles_to_dataframe(candles)

        if len(df) < MIN_CANDLES:
            return {
                "status": "not_enough_data",
                "candles": len(df),
                "required": MIN_CANDLES,
            }

        processed = calculate_half_trend(df, amplitude=10, channel_deviation=3.0)
        processed = drop_forming_candle(processed, now)
        if processed.empty:
            return {"status": "no_closed_bar_yet", "now": str(now)}

        expected_bar_open = last_closed_candle_open(now)
        if expected_bar_open is None:
            return {"status": "no_closed_bar_yet", "now": str(now)}

        bar_row = find_bar_row(processed, expected_bar_open)
        if bar_row is None:
            return {
                "status": "bar_not_found",
                "expected_bar": format_bar_time(expected_bar_open),
                "latest_bar": format_bar_time(processed["time"].iloc[-1]),
                "candles": len(processed),
            }

        bar_time = format_bar_time(bar_row["time"])
        close_price = float(bar_row["close"])
        bullish = int(bar_row.get("trend", 0)) == 0

        if force_alert:
            trend_label = "BULLISH" if bullish else "BEARISH"
            send_alert(
                cfg["NTFY_TOPIC"],
                f"TEST OK\nTrend: {trend_label}\nPrice: {close_price:.2f}\nBar: {bar_time} IST",
                is_buy=bullish,
            )
            return {
                "status": "test_alert_sent",
                "price": close_price,
                "time": bar_time,
                "trend": trend_label,
                "topic": cfg["NTFY_TOPIC"],
            }

        pending = collect_pending_alerts(processed, alerted, now)
        alerts_sent: list[str] = []
        for item in pending:
            if item["type"] == "buy":
                send_alert(
                    cfg["NTFY_TOPIC"],
                    f"BUY SIGNAL\nPrice: {item['price']:.2f}\nBar: {item['bar_time']} IST",
                    is_buy=True,
                )
                alerted[item["bar_time"]] = "buy"
                alerts_sent.append(f"buy@{item['bar_time']}")
            else:
                send_alert(
                    cfg["NTFY_TOPIC"],
                    f"SELL SIGNAL\nPrice: {item['price']:.2f}\nBar: {item['bar_time']} IST",
                    is_buy=False,
                )
                alerted[item["bar_time"]] = "sell"
                alerts_sent.append(f"sell@{item['bar_time']}")

        cutoff = now - timedelta(days=7)
        pruned: dict[str, str] = {}
        for k, v in alerted.items():
            ts = pd.Timestamp(k).tz_localize(IST)
            if ts >= cutoff:
                pruned[k] = v
        state["alerted"] = pruned
        state["last_checked_bar"] = bar_time
        save_state(state)

        return {
            "status": "success",
            "now_ist": str(_to_ist(now)),
            "checked_bar_ist": bar_time,
            "price": close_price,
            "buy_signal": bool(bar_row["buy_signal"]),
            "sell_signal": bool(bar_row["sell_signal"]),
            "alerts_sent": alerts_sent,
            "topic": cfg["NTFY_TOPIC"],
        }
    finally:
        client.logout()


def main() -> int:
    force = os.environ.get("FORCE_ALERT", "").lower() in ("1", "true", "yes")
    now = datetime.now(IST)

    if not force and not is_market_session(now):
        print(
            f"[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}] Outside market hours — skipping."
        )
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
