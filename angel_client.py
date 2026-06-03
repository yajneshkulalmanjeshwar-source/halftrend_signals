import time
import pandas as pd
import pyotp
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from config import Config

class AngelManager:
    def __init__(self):
        self.smart_api = None
        self.ws = None
        self.history_df = None
        self.current_candle = None
        self.on_signal_callback = None

    def login(self):
        Config.validate()
        self.smart_api = SmartConnect(api_key=Config.API_KEY)
        totp = pyotp.TOTP(Config.TOTP_SECRET).now()
        
        session = self.smart_api.generateSession(Config.CLIENT_ID, Config.PASSWORD, totp)
        if not session.get('status'):
            raise Exception(f"Angel One Login failed: {session.get('message')}")
        
        # Acquire JWT auth and refresh access capabilities
        auth_token = session['data']['jwtToken']
        feed_token = self.smart_api.getfeedToken()
        return auth_token, feed_token

    def fetch_historical_candles(self):
        """Fetches recent historical bars to pre-warm the moving calculation windows."""
        # Query window: last 5 market days to ensure adequate bars for an ATR-100 window
        to_date = time.strftime("%Y-%m-%d %H:%M")
        from_date = (pd.Timestamp.now() - pd.Timedelta(days=5)).strftime("%Y-%m-%d 09:15")
        
        params = {
            "exchange": Config.EXCHANGE,
            "symboltoken": Config.NIFTY_TOKEN,
            "interval": Config.INTERVAL,
            "fromdate": from_date,
            "todate": to_date
        }
        
        response = self.smart_api.getCandleData(params)
        if response.get('status') and response.get('data'):
            # Angel returns list format: [time, open, high, low, close, volume]
            df = pd.DataFrame(response['data'], columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].astype(float)
            self.history_df = df
            print(f"Preloaded {len(self.history_df)} candles for calculation warmups.")
        else:
            raise Exception("Failed to load historical initialization candles from Angel API.")

    def start_streaming(self, callback):
        self.on_signal_callback = callback
        auth_token, feed_token = self.login()
        self.fetch_historical_candles()

        # Initialize background streaming client
        self.ws = SmartWebSocketV2(auth_token, Config.CLIENT_ID, feed_token, Config.API_KEY)
        
        def on_data(wsapp, msg):
            self.process_live_tick(msg)

        def on_open(wsapp):
            # Subscribe explicitly to Nifty 50 Quote data points
            correlation_id = "halftrend_stream_01"
            action = 1  # Subscribe Action ID
            mode = 3    # Snapquote data depth mode
            # Ensure token is strictly a string for Angel One API compatibility
            token_list = [{"exchangeType": 1, "tokens": [str(Config.NIFTY_TOKEN)]}]
            self.ws.subscribe(correlation_id, action, mode, token_list)

        def on_error(wsapp, error):
            print(f"[ERROR] WebSocket connection failed: {error}")
            import traceback
            traceback.print_exc()

        self.ws.on_data = on_data
        self.ws.on_open = on_open
        self.ws.on_error = on_error
        
        # Starts the loop thread
        self.ws.connect()

    def process_live_tick(self, tick_msg):
        """Builds and closes incoming live bars into the historical framework structure."""
        try:
            # Handle heartbeat/ack messages that don't contain price data
            if not isinstance(tick_msg, dict):
                return
            
            if 'last_traded_price' not in tick_msg:
                return
            
            # Safely extract and convert the last traded price
            try:
                ltp = float(tick_msg['last_traded_price']) / 100.0  # Normalize decimal points if needed
            except (ValueError, TypeError) as e:
                print(f"[WARN] Invalid price in tick message: {tick_msg.get('last_traded_price')} - {e}")
                return
            
            tick_time = pd.Timestamp.now()
            
            # Round timestamps to group chunks depending on Config.INTERVAL
            # Simple five-minute group bucket calculation representation:
            candle_bucket = tick_time.floor('5min').strftime("%Y-%m-%d %H:%M")

            if self.current_candle is None or self.current_candle['time'] != candle_bucket:
                # Commit last finished live structure bar to history stream
                if self.current_candle is not None:
                    new_row = pd.DataFrame([self.current_candle])
                    self.history_df = pd.concat([self.history_df, new_row], ignore_index=True)
                    # Keep cache slim
                    if len(self.history_df) > 500:
                        self.history_df = self.history_df.iloc[1:].reset_index(drop=True)
                    
                    # Execute signal trigger processing check on completed closed bar
                    try:
                        self.on_signal_callback(self.history_df)
                    except Exception as callback_error:
                        print(f"[ERROR] Signal callback failed: {callback_error}")
                        import traceback
                        traceback.print_exc()

                # Initialize tracking parameters for the new cycle timeframe
                self.current_candle = {
                    'time': candle_bucket, 'open': ltp, 'high': ltp, 'low': ltp, 'close': ltp, 'volume': 0
                }
            else:
                # Update running high, low, and closing values on current bar tick
                self.current_candle['high'] = max(self.current_candle['high'], ltp)
                self.current_candle['low'] = min(self.current_candle['low'], ltp)
                self.current_candle['close'] = ltp
                
        except Exception as e:
            print(f"[ERROR] Error processing live tick: {e}")
            print(f"[DEBUG] Raw tick message: {tick_msg}")
            import traceback
            traceback.print_exc()
            # Don't re-raise - we want the WebSocket thread to stay alive
