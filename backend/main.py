"""APEX FX - Backend Server v4"""
import asyncio, logging, os
from datetime import datetime, timezone
from typing import Optional
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from price_feed       import PriceFeed
from signal_engine    import SignalEngine
from database         import Database
from alerts           import dispatch_signal, dispatch_trade_event, dispatch_agreement, send_telegram
from trade_tracker    import check_open_trades
from market_scheduler import scheduler_tick

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler()])
log = logging.getLogger("apexfx")

app = FastAPI(title="APEX FX", version="4.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db     = Database()
feed   = PriceFeed()
engine = SignalEngine()
clients: list[WebSocket] = []

# Monitoring state — scheduler controls this automatically
# False on weekends (Fri 22:00 – Sun 22:00 UTC), True otherwise
def _is_market_open() -> bool:
    now = datetime.now(timezone.utc)
    dow = now.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now.hour
    # Saturday all day = closed
    if dow == 5: return False
    # Sunday before 22:00 = closed
    if dow == 6 and hour < 22: return False
    # Friday after 22:00 = closed
    if dow == 4 and hour >= 22: return False
    return True

monitoring_state = {"active": _is_market_open()}

# ── Pydantic models ────────────────────────────────────────────────────────
class AlertConfig(BaseModel):
    email: str = ""
    telegram_chat_id: str = ""
    pairs: list = []
    strategies: list = []
    signal_types: list = []
    min_strength: str = "medium"
    active: bool = True

class OutcomeUpdate(BaseModel):
    outcome: str
    note: str = ""

class TestAlert(BaseModel):
    email: str = ""
    telegram_chat_id: str = ""

# ── Candle close tracker ───────────────────────────────────────────────────
# Tracks the timestamp of the last candle evaluated per pair/timeframe
# so we only run strategies when a NEW candle has formed
_last_candle_ts: dict = {}

def _get_candle_close_minutes(tf: str) -> int:
    """Returns candle duration in minutes."""
    return {"M15": 15, "H1": 60, "H4": 240}.get(tf, 60)

def _new_candles_available(candles_by_pair: dict) -> dict:
    """
    Returns dict of {pair: [timeframes]} where a new candle has closed
    since we last evaluated. Only these pair/tf combos should be evaluated.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    new = {}
    for pair, tfs in candles_by_pair.items():
        for tf, candles in tfs.items():
            if not candles: continue
            last_candle = candles[-1]
            last_ts = last_candle.get("time", "")
            key = f"{pair}:{tf}"
            # Only evaluate if this candle's timestamp is new
            if _last_candle_ts.get(key) != last_ts:
                _last_candle_ts[key] = last_ts
                if pair not in new: new[pair] = []
                new[pair].append(tf)
    return new

def _filter_conflicts(signals: list) -> list:
    """
    Remove conflicting signals — if BUY and SELL fire on the same
    pair+timeframe in the same batch, keep only the higher conviction one.
    Also removes signals where RSI contradicts direction.
    """
    # Group by pair+timeframe
    groups: dict = {}
    for s in signals:
        key = f"{s['pair']}:{s['timeframe']}"
        if key not in groups: groups[key] = []
        groups[key].append(s)

    filtered = []
    for key, group in groups.items():
        if len(group) == 1:
            filtered.append(group[0])
            continue

        # Separate by direction
        buys  = [s for s in group if s["type"] in ("buy","buy_limit","buy_stop")]
        sells = [s for s in group if s["type"] in ("sell","sell_limit","sell_stop")]

        if buys and sells:
            # Conflict — keep only the higher conviction side
            # Use RSI from indicators to decide if available
            best_buy  = max(buys,  key=lambda s: s.get("risk_reward",0))
            best_sell = max(sells, key=lambda s: s.get("risk_reward",0))
            rsi_val = best_buy.get("indicators",{}).get("RSI") or best_sell.get("indicators",{}).get("RSI")
            if rsi_val:
                if rsi_val < 50:
                    filtered.append(best_buy)   # RSI below 50 favours buy
                else:
                    filtered.append(best_sell)  # RSI above 50 favours sell
            else:
                # Keep higher R:R
                if best_buy.get("risk_reward",0) >= best_sell.get("risk_reward",0):
                    filtered.append(best_buy)
                else:
                    filtered.append(best_sell)
        else:
            # No conflict — add all
            filtered.extend(buys or sells)

    return filtered

# ── WebSocket broadcast ────────────────────────────────────────────────────
async def broadcast(data: dict):
    dead = []
    for ws in clients:
        try: await ws.send_json(data)
        except: dead.append(ws)
    for ws in dead:
        if ws in clients: clients.remove(ws)

# ── Scheduler loop (runs every minute) ────────────────────────────────────
async def scheduler_loop():
    while True:
        try:
            await scheduler_tick(db, monitoring_state)
        except Exception as e:
            log.error(f"Scheduler error: {e}")
        await asyncio.sleep(60)

# ── Main signal loop ───────────────────────────────────────────────────────
async def main_loop():
    tick = 0
    while True:
        try:
            await feed.tick()
            prices = feed.get_prices()
            await broadcast({
                "type": "prices", "data": prices,
                "market_open": monitoring_state["active"],
                "ts": datetime.now(timezone.utc).isoformat()
            })

            # Only run signal detection when markets are open
            if monitoring_state["active"]:
                # Fetch candles every 60 seconds
                if tick % 60 == 0:
                    candles = feed.get_all_candles()

                    # Only evaluate pairs/timeframes where a NEW candle has closed
                    new_tf_map = _new_candles_available(candles)

                    if new_tf_map:
                        log.info(f"New candles detected: {new_tf_map}")

                        # Build subset of candles to evaluate
                        candles_to_eval = {
                            pair: {tf: candles[pair][tf] for tf in tfs if tf in candles.get(pair,{})}
                            for pair, tfs in new_tf_map.items()
                        }

                        signals, agreements = engine.evaluate(candles_to_eval)

                        # Filter conflicting signals before sending
                        signals = _filter_conflicts(signals)

                        configs = db.get_active_configs()

                        if signals:
                            for s in signals:
                                db.save_signal(s)
                                await dispatch_signal(s, configs)
                            await broadcast({"type":"signals","data":signals,"ts":datetime.now(timezone.utc).isoformat()})
                            log.info(f"Dispatched {len(signals)} signals")

                        if agreements:
                            agreements = _filter_conflicts(agreements)
                            for ag in agreements:
                                db.save_signal(ag)
                                await dispatch_agreement(ag)
                            await broadcast({"type":"agreements","data":agreements,"ts":datetime.now(timezone.utc).isoformat()})

                if tick % 10 == 0:
                    await check_open_trades(db, prices)

            tick += 1
        except Exception as e:
            log.error(f"Main loop error: {e}")
        await asyncio.sleep(1)

# ── Keep-alive ─────────────────────────────────────────────────────────────
async def keep_alive():
    import aiohttp
    url = os.getenv("RENDER_EXTERNAL_URL","")
    if not url: return
    while True:
        await asyncio.sleep(840)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{url}/api/health"): pass
        except: pass

@app.on_event("startup")
async def startup():
    db.init()
    await feed.init()
    asyncio.create_task(main_loop())
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(keep_alive())
    status = "OPEN" if monitoring_state["active"] else "CLOSED (weekend)"
    log.info(f"APEX FX v4 started. Market: {status}")

# ── WebSocket ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept(); clients.append(ws)
    try:
        await ws.send_json({
            "type": "init",
            "prices": feed.get_prices(),
            "candles": feed.get_all_candles(),
            "signals": db.get_signals(50),
            "stats": db.get_stats(),
            "market_open": monitoring_state["active"],
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        if ws in clients: clients.remove(ws)

# ── REST API ───────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok", "clients": len(clients),
        "feed": feed.source, "market_open": monitoring_state["active"],
        "ts": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/signals")
def get_signals(limit:int=100, pair:Optional[str]=None, strategy:Optional[str]=None, outcome:Optional[str]=None):
    return db.get_signals(limit, pair, strategy, outcome)

@app.get("/api/stats")
def get_stats():
    return db.get_stats()

@app.get("/api/price/{pair}")
def get_price(pair: str):
    return feed.get_price(pair.upper())

@app.patch("/api/signals/{sig_id}/outcome")
def update_outcome(sig_id: str, body: OutcomeUpdate):
    db.update_outcome(sig_id, body.outcome, body.note)
    return {"status":"ok"}

@app.post("/api/alerts/config")
def save_config(cfg: AlertConfig, bg: BackgroundTasks):
    db.save_alert_config(cfg.dict())
    return {"status":"ok"}

@app.get("/api/alerts/config")
def get_configs():
    return db.get_active_configs()

@app.post("/api/alerts/test")
async def test_alert(req: TestAlert):
    msg = "✅ <b>APEX FX Test Alert</b>\nYour Telegram alerts are working correctly."
    if req.telegram_chat_id:
        await send_telegram(msg, req.telegram_chat_id)
    elif os.getenv("TELEGRAM_CHAT_ID"):
        await send_telegram(msg)
    return {"status":"ok"}

@app.get("/api/market/status")
def market_status():
    return {"market_open": monitoring_state["active"], "ts": datetime.now(timezone.utc).isoformat()}

# ── Serve frontend ─────────────────────────────────────────────────────────
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/")
def root():
    fp = os.path.join(frontend_path, "index.html")
    if os.path.exists(fp): return FileResponse(fp)
    return {"status": "APEX FX backend running."}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT",8000)), reload=False)
    # Saturday all day = closed
    if dow == 5: return False
    # Sunday before 22:00 = closed
    if dow == 6 and hour < 22: return False
    # Friday after 22:00 = closed
    if dow == 4 and hour >= 22: return False
    return True

monitoring_state = {"active": _is_market_open()}

# ── Pydantic models ────────────────────────────────────────────────────────
class AlertConfig(BaseModel):
    email: str = ""
    telegram_chat_id: str = ""
    pairs: list = []
    strategies: list = []
    signal_types: list = []
    min_strength: str = "medium"
    active: bool = True

class OutcomeUpdate(BaseModel):
    outcome: str
    note: str = ""

class TestAlert(BaseModel):
    email: str = ""
    telegram_chat_id: str = ""

# ── WebSocket broadcast ────────────────────────────────────────────────────
async def broadcast(data: dict):
    dead = []
    for ws in clients:
        try: await ws.send_json(data)
        except: dead.append(ws)
    for ws in dead:
        if ws in clients: clients.remove(ws)

# ── Scheduler loop (runs every minute) ────────────────────────────────────
async def scheduler_loop():
    while True:
        try:
            await scheduler_tick(db, monitoring_state)
        except Exception as e:
            log.error(f"Scheduler error: {e}")
        await asyncio.sleep(60)

# ── Main signal loop ───────────────────────────────────────────────────────
async def main_loop():
    tick = 0
    while True:
        try:
            await feed.tick()
            prices = feed.get_prices()
            await broadcast({
                "type": "prices", "data": prices,
                "market_open": monitoring_state["active"],
                "ts": datetime.now(timezone.utc).isoformat()
            })

            # Only run signal detection when markets are open
            if monitoring_state["active"]:
                if tick % 30 == 0:
                    candles = feed.get_all_candles()
                    signals, agreements = engine.evaluate(candles)
                    configs = db.get_active_configs()

                    if signals:
                        for s in signals:
                            db.save_signal(s)
                            await dispatch_signal(s, configs)
                        await broadcast({"type":"signals","data":signals,"ts":datetime.now(timezone.utc).isoformat()})

                    if agreements:
                        for ag in agreements:
                            db.save_signal(ag)
                            await dispatch_agreement(ag)
                        await broadcast({"type":"agreements","data":agreements,"ts":datetime.now(timezone.utc).isoformat()})

                if tick % 10 == 0:
                    await check_open_trades(db, prices)

            tick += 1
        except Exception as e:
            log.error(f"Main loop error: {e}")
        await asyncio.sleep(1)

# ── Keep-alive ─────────────────────────────────────────────────────────────
async def keep_alive():
    import aiohttp
    url = os.getenv("RENDER_EXTERNAL_URL","")
    if not url: return
    while True:
        await asyncio.sleep(840)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{url}/api/health"): pass
        except: pass

@app.on_event("startup")
async def startup():
    db.init()
    await feed.init()
    asyncio.create_task(main_loop())
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(keep_alive())
    status = "OPEN" if monitoring_state["active"] else "CLOSED (weekend)"
    log.info(f"APEX FX v4 started. Market: {status}")

# ── WebSocket ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept(); clients.append(ws)
    try:
        await ws.send_json({
            "type": "init",
            "prices": feed.get_prices(),
            "candles": feed.get_all_candles(),
            "signals": db.get_signals(50),
            "stats": db.get_stats(),
            "market_open": monitoring_state["active"],
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        if ws in clients: clients.remove(ws)

# ── REST API ───────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok", "clients": len(clients),
        "feed": feed.source, "market_open": monitoring_state["active"],
        "ts": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/signals")
def get_signals(limit:int=100, pair:Optional[str]=None, strategy:Optional[str]=None, outcome:Optional[str]=None):
    return db.get_signals(limit, pair, strategy, outcome)

@app.get("/api/stats")
def get_stats():
    return db.get_stats()

@app.get("/api/price/{pair}")
def get_price(pair: str):
    return feed.get_price(pair.upper())

@app.patch("/api/signals/{sig_id}/outcome")
def update_outcome(sig_id: str, body: OutcomeUpdate):
    db.update_outcome(sig_id, body.outcome, body.note)
    return {"status":"ok"}

@app.post("/api/alerts/config")
def save_config(cfg: AlertConfig, bg: BackgroundTasks):
    db.save_alert_config(cfg.dict())
    return {"status":"ok"}

@app.get("/api/alerts/config")
def get_configs():
    return db.get_active_configs()

@app.post("/api/alerts/test")
async def test_alert(req: TestAlert):
    msg = "✅ <b>APEX FX Test Alert</b>\nYour Telegram alerts are working correctly."
    if req.telegram_chat_id:
        await send_telegram(msg, req.telegram_chat_id)
    elif os.getenv("TELEGRAM_CHAT_ID"):
        await send_telegram(msg)
    return {"status":"ok"}

@app.get("/api/market/status")
def market_status():
    return {"market_open": monitoring_state["active"], "ts": datetime.now(timezone.utc).isoformat()}

# ── Serve frontend ─────────────────────────────────────────────────────────
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/")
def root():
    fp = os.path.join(frontend_path, "index.html")
    if os.path.exists(fp): return FileResponse(fp)
    return {"status": "APEX FX backend running."}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT",8000)), reload=False)
