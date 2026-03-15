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
