import MetaTrader5 as mt5
from datetime import datetime
import time

# Import YOUR engine
from signal_engine import SignalEngine


# ==============================
# CONFIG
# ==============================
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]
TIMEFRAMES = {
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1
}

LOT_SIZE = 0.01
MIN_RR = 1.5
MAX_SPREAD = 30  # points
SLEEP_TIME = 60  # seconds


# ==============================
# MT5 INIT
# ==============================
def init_mt5():
    if not mt5.initialize():
        print("❌ MT5 initialization failed")
        quit()
    print("✅ MT5 Connected")


# ==============================
# FETCH CANDLES
# ==============================
def get_candles(symbol, timeframe, n=200):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None:
        return []

    candles = []
    for r in rates:
        candles.append({
            "time": r["time"],
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "tick_volume": r["tick_volume"]
        })
    return candles


# ==============================
# BUILD DATA STRUCTURE
# ==============================
def build_market_data():
    data = {}
    for symbol in SYMBOLS:
        data[symbol] = {}
        for tf_name, tf in TIMEFRAMES.items():
            candles = get_candles(symbol, tf)
            if candles:
                data[symbol][tf_name] = candles
    return data


# ==============================
# SPREAD CHECK
# ==============================
def is_spread_ok(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False
    spread = (tick.ask - tick.bid) / mt5.symbol_info(symbol).point
    return spread <= MAX_SPREAD


# ==============================
# CHECK OPEN POSITIONS
# ==============================
def has_open_trade(symbol, direction):
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        return False

    for pos in positions:
        if direction == "buy" and pos.type == 0:
            return True
        if direction == "sell" and pos.type == 1:
            return True
    return False


# ==============================
# RISK:REWARD CHECK
# ==============================
def valid_rr(signal):
    entry = signal["entry"]
    sl = signal["sl"]
    tp = signal["tp"]

    risk = abs(entry - sl)
    reward = abs(tp - entry)

    if risk == 0:
        return False

    rr = reward / risk
    return rr >= MIN_RR


# ==============================
# EXECUTE TRADE
# ==============================
def place_trade(signal):
    symbol = signal["pair"]
    direction = signal["type"]
    entry = signal["entry"]
    sl = signal["sl"]
    tp = signal["tp"]

    if not is_spread_ok(symbol):
        print(f"❌ Spread too high for {symbol}")
        return

    if has_open_trade(symbol, direction):
        print(f"⚠️ Trade already open for {symbol}")
        return

    if not valid_rr(signal):
        print(f"❌ R:R too low for {symbol}")
        return

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"❌ Symbol not found: {symbol}")
        return

    point = symbol_info.point
    price = mt5.symbol_info_tick(symbol).ask if "buy" in direction else mt5.symbol_info_tick(symbol).bid

    order_type = None

    if direction == "buy":
        order_type = mt5.ORDER_TYPE_BUY
    elif direction == "sell":
        order_type = mt5.ORDER_TYPE_SELL
    elif direction == "buy_limit":
        order_type = mt5.ORDER_TYPE_BUY_LIMIT
    elif direction == "sell_limit":
        order_type = mt5.ORDER_TYPE_SELL_LIMIT
    elif direction == "buy_stop":
        order_type = mt5.ORDER_TYPE_BUY_STOP
    elif direction == "sell_stop":
        order_type = mt5.ORDER_TYPE_SELL_STOP
    else:
        print("❌ Unknown order type")
        return

    request = {
        "action": mt5.TRADE_ACTION_DEAL if "limit" not in direction and "stop" not in direction else mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": entry,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 123456,
        "comment": "AutoBot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Trade failed: {result.retcode}")
    else:
        print(f"✅ Trade placed: {symbol} {direction}")


# ==============================
# MAIN LOOP
# ==============================
def run():
    init_mt5()
    engine = SignalEngine()

    while True:
        print(f"\n⏳ Scanning market... {datetime.now()}")

        market_data = build_market_data()
        if not market_data:
            print("❌ No data fetched")
            time.sleep(SLEEP_TIME)
            continue

        regular, agreements = engine.evaluate(market_data)

        # Prioritize strong signals
        all_signals = agreements + regular

        for signal in all_signals:
            try:
                place_trade(signal)
            except Exception as e:
                print(f"⚠️ Error placing trade: {e}")

        time.sleep(SLEEP_TIME)


# ==============================
# START
# ==============================
if __name__ == "__main__":
    run()
