"""
APEX FX - Backend Server
MT5 is the sole data source. No Telegram, no email, no simulation.
EA pushes candles -> backend evaluates -> dashboard shows signals.
"""
import asyncio, logging, os
from datetime import datetime, timezone
from typing import Optional
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from store     import DataStore
from engine    import SignalEngine
from scheduler import market_message

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
log = logging.getLogger("apexfx")

app = FastAPI(title="APEX FX", version="1.0")
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

store  = DataStore()
engine = SignalEngine()
clients: list[WebSocket] = []
MT5_SECRET = os.getenv("MT5_SECRET", "apexfx2026")

# ── Broadcast to all connected dashboard clients ───────────────────
async def broadcast(msg: dict):
    dead = []
    for ws in clients:
        try:    await ws.send_json(msg)
        except: dead.append(ws)
    for ws in dead:
        if ws in clients: clients.remove(ws)

# ── Scheduler (session messages) ──────────────────────────────────
async def scheduler_loop():
    last = ""
    while True:
        now = datetime.now(timezone.utc)
        key = now.strftime("%Y-%m-%d %H:%M")
        if key != last:
            last = key
            msg = market_message(now)
            if msg:
                await broadcast({"type": "scheduler", "data": msg})
        await asyncio.sleep(30)

# ── Startup ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    store.init()
    asyncio.create_task(scheduler_loop())
    log.info("APEX FX started. Waiting for MT5 data.")

# ── WebSocket ──────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.append(ws)
    try:
        await ws.send_json({
            "type":    "init",
            "prices":  store.get_prices(),
            "candles": store.get_all_candles(),
            "signals": store.get_signals(50),
            "stats":   store.get_stats(),
            "mt5":     store.mt5_connected(),
            "ts":      datetime.now(timezone.utc).isoformat(),
        })
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in clients: clients.remove(ws)

# ── MT5 data receiver ──────────────────────────────────────────────
class MT5Data(BaseModel):
    secret:        str  = ""
    pair:          str
    tf:            str
    candles:       list = []
    price:         dict = {}
    candle_closed: bool = False

@app.post("/api/mt5")
async def receive_mt5(data: MT5Data):
    if data.secret and data.secret != MT5_SECRET:
        return JSONResponse({"status": "error", "msg": "unauthorized"}, 401)

    pair = data.pair.upper().strip()
    tf   = data.tf.upper().strip()

    if data.candles:
        store.set_candles(pair, tf, data.candles)
        # Broadcast candle update so chart refreshes
        await broadcast({
            "type":    "candle_update",
            "pair":    pair,
            "tf":      tf,
            "candles": data.candles,
        })

    if data.price:
        mid = float(data.price.get("mid") or data.price.get("ask") or 0)
        if mid > 0:
            store.set_price(pair, mid, data.price)

    await broadcast({
        "type":  "price_update",
        "pair":  pair,
        "price": store.get_price(pair),
        "mt5":   True,
    })

    # Only evaluate strategies when a candle just closed
    if data.candle_closed and data.candles:
        log.info(f"Candle closed: {pair}/{tf} — evaluating")
        signals = engine.evaluate_pair(pair, tf, store.get_all_candles())
        if signals:
            for s in signals:
                store.save_signal(s)
            await broadcast({
                "type": "signals",
                "data": signals,
                "ts":   datetime.now(timezone.utc).isoformat(),
            })
            log.info(f"Dispatched {len(signals)} signals for {pair}/{tf}")

    return {"status": "ok", "pair": pair, "tf": tf}

# ── REST endpoints ─────────────────────────────────────────────────
class OutcomeUpdate(BaseModel):
    outcome: str
    note:    str = ""

@app.patch("/api/signals/{sig_id}/outcome")
def update_outcome(sig_id: str, body: OutcomeUpdate):
    store.update_outcome(sig_id, body.outcome, body.note)
    return {"status": "ok"}

@app.get("/api/signals")
def get_signals(limit: int = 100):
    return store.get_signals(limit)

@app.get("/api/candles/{pair}/{tf}")
def get_candles(pair: str, tf: str):
    return store.get_candles(pair.upper(), tf.upper())

@app.get("/api/stats")
def get_stats():
    return store.get_stats()

@app.get("/api/health")
def health():
    return {
        "status":  "ok",
        "mt5":     store.mt5_connected(),
        "clients": len(clients),
        "ts":      datetime.now(timezone.utc).isoformat(),
    }

# ── Frontend ───────────────────────────────────────────────────────
frontend = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend):
    app.mount("/static", StaticFiles(directory=frontend), name="static")

@app.get("/")
def root():
    fp = os.path.join(frontend, "index.html")
    if os.path.exists(fp): return FileResponse(fp)
    return {"status": "APEX FX running"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)), reload=False)
