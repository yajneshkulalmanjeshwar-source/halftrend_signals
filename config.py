import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
    PASSWORD = os.getenv("ANGEL_PASSWORD")
    API_KEY = os.getenv("ANGEL_API_KEY")
    TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
    NTFY_TOPIC = os.getenv("NTFY_TOPIC", "nifty_halftrend_default_topic")
    
    # Nifty 50 Token configurations for Angel One
    NIFTY_TOKEN = "99926000"  # Nifty 50 Index token on NSE
    EXCHANGE = "NSE"
    INTERVAL = "FIVE_MINUTE"  # Set your trading timeframe here (e.g., ONE_MINUTE, FIVE_MINUTE)

    @classmethod
    def validate(cls):
        missing = [k for k, v in {
            "ANGEL_CLIENT_ID": cls.CLIENT_ID,
            "ANGEL_PASSWORD": cls.PASSWORD,
            "ANGEL_API_KEY": cls.API_KEY,
            "ANGEL_TOTP_SECRET": cls.TOTP_SECRET
        }.items() if not v]
        if missing:
            raise ValueError(f"Missing essential configuration variables: {', '.join(missing)}")
