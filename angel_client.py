"""Angel One SmartAPI client for Nifty 50 historical candles."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pyotp
from SmartApi.smartConnect import SmartConnect

IST = ZoneInfo("Asia/Kolkata")
NIFTY_50_TOKEN = "99926000"


class AngelOneClient:
    def __init__(self, api_key: str, client_code: str, pin: str, totp_secret: str):
        self.client_code = client_code
        self.pin = pin
        self.totp_secret = totp_secret.replace(" ", "")
        self.api = SmartConnect(api_key)

    def login(self) -> dict:
        totp = pyotp.TOTP(self.totp_secret).now()
        data = self.api.generateSession(self.client_code, self.pin, totp)
        if not data.get("status"):
            raise RuntimeError(f"Angel One login failed: {data.get('message', data)}")
        return data

    def get_nifty_candles(
        self,
        interval: str = "FIVE_MINUTE",
        days_back: int = 10,
    ) -> list:
        end = datetime.now(IST)
        start = end - timedelta(days=days_back)
        params = {
            "exchange": "NSE",
            "symboltoken": NIFTY_50_TOKEN,
            "interval": interval,
            "fromdate": start.strftime("%Y-%m-%d %H:%M"),
            "todate": end.strftime("%Y-%m-%d %H:%M"),
        }
        result = self.api.getCandleData(params)
        if not result or not result.get("status"):
            raise RuntimeError(f"getCandleData failed: {result}")
        data = result.get("data")
        if not data:
            raise RuntimeError("No candle data returned (market closed or empty range)")
        return data

    def logout(self) -> None:
        try:
            self.api.terminateSession(self.client_code)
        except Exception:
            pass
