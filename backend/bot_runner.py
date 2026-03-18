import MetaTrader5 as mt5
import requests
from datetime import datetime
import time

# MT5 initialization
if not mt5.initialize():
    print("❌ MT5 init failed")
    quit()

# Platform endpoint
API_URL = "https://apexfx.onrender.com/api/marketdata"  # create an endpoint to receive data

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]
TIMEFRAMES = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5}
SLEEP_TIME = 60  # send data every 60 seconds

while True:
    payload = {}
    for symbol in SYMBOLS:
        payload[symbol] = {}
        for tf_name, tf in TIMEFRAMES.items():
            candles = mt5.copy_rates_from_pos(symbol, tf, 0, 10)  # last 10 candles
            payload[symbol][tf_name] = [
                {
                    "time": int(c['time']),
                    "open": c['open'],
                    "high": c['high'],
                    "low": c['low'],
                    "close": c['close'],
                    "volume": c['tick_volume']
                }
                for c in candles
            ]
    # Send data to your platform
    try:
        response = requests.post(API_URL, json=payload)
        if response.status_code == 200:
            print(f"✅ Data sent at {datetime.now()}")
        else:
            print(f"❌ Failed to send data: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Error sending data: {e}")
    
    time.sleep(SLEEP_TIME)
