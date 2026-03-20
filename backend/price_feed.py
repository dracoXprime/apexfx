"""APEX FX - Price Feed v2 (MT5 primary, Twelve Data fallback, Simulation)"""
import os, asyncio, logging, random
from datetime import datetime, timezone, timedelta
from typing import Optional
import aiohttp

log = logging.getLogger("apexfx.feed")

PAIRS = {
    "EURUSD": {"base":1.0854,"pip":0.0001,"digits":5,"spread":0.00008,"td":"EUR/USD"},
    "GBPUSD": {"base":1.2701,"pip":0.0001,"digits":5,"spread":0.00010,"td":"GBP/USD"},
    "USDJPY": {"base":149.82,"pip":0.01,  "digits":3,"spread":0.009,  "td":"USD/JPY"},
    "AUDUSD": {"base":0.6543,"pip":0.0001,"digits":5,"spread":0.00009,"td":"AUD/USD"},
    "USDCAD": {"base":1.3621,"pip":0.0001,"digits":5,"spread":0.00011,"td":"USD/CAD"},
    "GBPJPY": {"base":190.12,"pip":0.01,  "digits":3,"spread":0.014,  "td":"GBP/JPY"},
    "XAUUSD": {"base":2314.5,"pip":0.1,   "digits":2,"spread":0.35,   "td":"XAU/USD"},
}

TIMEFRAMES = ["M15", "H1", "H4"]
TF_MINUTES  = {"M15": 15, "H1": 60, "H4": 240}
TD_TF       = {"M15": "15min", "H1": "1h", "H4": "4h"}

MT5_SYMBOL_MAP = {
    "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD", "USDCAD": "USDCAD", "GBPJPY": "GBPJPY",
    "XAUUSD": "XAUUSD", "GOLD":   "XAUUSD",
}
MT5_TF_MAP = {
    "M15": "M15", "H1": "H1", "H4": "H4",
    "PERIOD_M15": "M15", "PERIOD_H1": "H1", "PERIOD_H4": "H4",
}


class PriceFeed:

    def __init__(self):
        self.key    = os.getenv("TWELVE_DATA_API_KEY", "")
        self.source = "simulation"
        self._session = None
        self._sim_prices  = {}
        self._sim_candles = {}
        self._mt5_prices  = {}
        self._mt5_candles = {}
        self._mt5_last_update = None

    def ingest_mt5(self, payload):
        raw_pair = str(payload.get("pair", "")).upper().strip()
        raw_tf   = str(payload.get("tf",   "")).upper().strip()
        pair = MT5_SYMBOL_MAP.get(raw_pair)
        tf   = MT5_TF_MAP.get(raw_tf)
        if not pair or not tf:
            return False
        candles = payload.get("candles", [])
        if candles:
            self._mt5_candles.setdefault(pair, {})[tf] = candles
            self._mt5_last_update = datetime.now(timezone.utc)
            if self.source != "mt5":
                self.source = "mt5"
                log.info("Data source switched to MT5")
            log.info(f"MT5 ingested {pair}/{tf} — {len(candles)} candles")
        price = payload.get("price", {})
        if price and pair in PAIRS:
            info = PAIRS[pair]
            mid  = float(price.get("mid") or price.get("ask") or 0)
            if mid > 0:
                self._mt5_prices[pair] = self._mk_price(pair, mid, info)
        return True

    def ingest_mt5_batch(self, payloads):
        count = 0
        for item in payloads:
            if isinstance(item, dict) and self.ingest_mt5(item):
                count += 1
        return count

    def mt5_connected(self):
        if not self._mt5_last_update:
            return False
        age = (datetime.now(timezone.utc) - self._mt5_last_update).total_seconds()
        return age < 300

    def _init_simulation(self):
        for pair, info in PAIRS.items():
            self._sim_prices[pair]  = self._mk_price(pair, info["base"], info)
            self._sim_candles[pair] = {}
            for tf in TIMEFRAMES:
                self._sim_candles[pair][tf] = self._gen_history(pair, info, TF_MINUTES[tf], 220)

    def _gen_history(self, pair, info, tf_mins, count):
        price = info["base"]
        vol   = info["pip"] * 8
        now   = datetime.now(timezone.utc)
        out   = []
        for i in range(count, 0, -1):
            ts    = now - timedelta(minutes=tf_mins * i)
            drift = (random.random() - 0.498) * vol + (info["base"] - price) * 0.001
            price = max(price + drift, info["base"] * 0.88)
            cv    = vol * (0.5 + random.random())
            o = price
            h = price + abs(random.gauss(0, cv))
            l = price - abs(random.gauss(0, cv))
            c = max(l, min(h, price + random.gauss(0, cv * 0.5)))
            out.append({"time": ts.isoformat(), "open": round(o, info["digits"]), "high": round(h, info["digits"]), "low": round(l, info["digits"]), "close": round(c, info["digits"]), "volume": random.randint(400, 5000)})
        return out

    def _mk_price(self, pair, mid, info):
        d = info["digits"]; s = info["spread"]; b = info["base"]
        return {"pair": pair, "mid": round(mid, d), "bid": round(mid - s/2, d), "ask": round(mid + s/2, d), "spread": s, "change": round(mid - b, d), "change_pct": round((mid - b)/b*100, 4), "high_24h": round(mid*1.005, d), "low_24h": round(mid*0.995, d)}

    def _tick(self):
        for pair, info in PAIRS.items():
            p   = self._sim_prices[pair]
            vol = info["pip"] * (0.4 + random.random() * 0.9)
            drift = (info["base"] - p["mid"]) * 0.0006 + (random.random() - 0.5) * vol
            mid = round(p["mid"] + drift, info["digits"])
            p.update({"mid": mid, "bid": round(mid - info["spread"]/2, info["digits"]), "ask": round(mid + info["spread"]/2, info["digits"]), "change": round(mid - info["base"], info["digits"]), "change_pct": round((mid - info["base"])/info["base"]*100, 4), "high_24h": max(p["high_24h"], mid), "low_24h": min(p["low_24h"], mid)})
            for tf in TIMEFRAMES:
                last = self._sim_candles[pair][tf][-1]
                last["close"]  = mid
                last["high"]   = max(last["high"], mid)
                last["low"]    = min(last["low"],  mid)
                last["volume"] += random.randint(5, 80)

    async def _fetch_all_candles(self):
        for pair in PAIRS:
            self._sim_candles.setdefault(pair, {})
            for tf in TIMEFRAMES:
                try:
                    candles = await self._td_candles(pair, tf, 220)
                    if candles:
                        self._sim_candles[pair][tf] = candles
                except Exception as e:
                    log.error(f"TD candle fetch {pair}/{tf}: {e}")
                await asyncio.sleep(0.5)

    async def _td_candles(self, pair, tf, count):
        info   = PAIRS[pair]
        url    = "https://api.twelvedata.com/time_series"
        params = {"symbol": info["td"], "interval": TD_TF[tf], "outputsize": count, "apikey": self.key, "format": "JSON"}
        async with self._session.get(url, params=params) as r:
            data = await r.json()
        if "values" not in data:
            return []
        return [{"time": c["datetime"], "open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"]), "volume": int(c.get("volume", 0))} for c in reversed(data["values"])]

    async def _td_prices(self):
        symbols = ",".join(info["td"] for info in PAIRS.values())
        url     = "https://api.twelvedata.com/price"
        async with self._session.get(url, params={"symbol": symbols, "apikey": self.key}) as r:
            data = await r.json()
        for pair, info in PAIRS.items():
            entry = data.get(info["td"], {})
            mid   = float(entry.get("price", 0))
            if mid > 0:
                self._sim_prices[pair] = self._mk_price(pair, mid, info)

    async def init(self):
        self._session = aiohttp.ClientSession()
        self._init_simulation()
        if self.key:
            self.source = "twelve_data"
            log.info("Twelve Data key found — fetching live candles")
            await self._fetch_all_candles()
        else:
            log.info("No API key — simulation mode")

    async def tick(self):
        if self.mt5_connected():
            pass
        elif self.source == "twelve_data":
            try:
                await self._td_prices()
            except Exception as e:
                log.debug(f"TD price tick: {e}")
                self._tick()
        else:
            self._tick()

    def get_prices(self):
        prices = dict(self._sim_prices)
        prices.update(self._mt5_prices)
        return prices

    def get_candles(self, pair, tf):
        mt5 = self._mt5_candles.get(pair, {}).get(tf)
        if mt5:
            return list(mt5)
        return list(self._sim_candles.get(pair, {}).get(tf, []))

    def get_all_candles(self):
        return {pair: {tf: self.get_candles(pair, tf) for tf in TIMEFRAMES} for pair in PAIRS}

    def get_price(self, pair):
        return self._mt5_prices.get(pair) or self._sim_prices.get(pair, {})
