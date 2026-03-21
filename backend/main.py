"""APEX FX Backend v5 — MT5 data only, dashboard only"""
import asyncio, logging, os
from datetime import datetime, timezone
from typing import Optional
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import database as db
import signal_engine as engine

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler()])
log = logging.getLogger("apexfx")

app = FastAPI(title="APEX FX", version="5.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

clients = []
_mt5_candles = {}
_mt5_prices  = {}
_mt5_last_update = None
MT5_SECRET = os.getenv("MT5_SECRET", "apexfx2026")

SYMBOL_MAP = {"EURUSD":"EURUSD","GBPUSD":"GBPUSD","USDJPY":"USDJPY",
              "AUDUSD":"AUDUSD","USDCAD":"USDCAD","GBPJPY":"GBPJPY","XAUUSD":"XAUUSD","GOLD":"XAUUSD"}
TF_MAP = {"M15":"M15","H1":"H1","H4":"H4","PERIOD_M15":"M15","PERIOD_H1":"H1","PERIOD_H4":"H4"}
DIGITS = {"EURUSD":5,"GBPUSD":5,"USDJPY":3,"AUDUSD":5,"USDCAD":5,"GBPJPY":3,"XAUUSD":2}
PIPS   = {"EURUSD":1e-4,"GBPUSD":1e-4,"USDJPY":0.01,"AUDUSD":1e-4,"USDCAD":1e-4,"GBPJPY":0.01,"XAUUSD":0.1}
BASES  = {"EURUSD":1.08,"GBPUSD":1.27,"USDJPY":149.8,"AUDUSD":0.654,"USDCAD":1.362,"GBPJPY":190.1,"XAUUSD":2314.0}

async def broadcast(data):
    dead=[]
    for ws in clients:
        try: await ws.send_json(data)
        except: dead.append(ws)
    for ws in dead:
        if ws in clients: clients.remove(ws)

def mt5_connected():
    if not _mt5_last_update: return False
    return (datetime.now(timezone.utc)-_mt5_last_update).total_seconds()<300

def get_prices():
    out={}
    for pair,base in BASES.items():
        d=DIGITS[pair]; sp=PIPS[pair]*0.8
        out[pair]={"pair":pair,"mid":base,"bid":round(base-sp/2,d),"ask":round(base+sp/2,d),"change":0,"change_pct":0,"high_24h":base,"low_24h":base}
    out.update(_mt5_prices)
    return out

async def process_item(item):
    global _mt5_last_update
    pair=SYMBOL_MAP.get(str(item.get("pair","")).upper().strip())
    tf=TF_MAP.get(str(item.get("tf","")).upper().strip())
    if not pair or not tf: return []
    _mt5_last_update=datetime.now(timezone.utc)
    price=item.get("price",{})
    if price:
        mid=float(price.get("mid") or price.get("ask") or 0)
        if mid>0:
            d=DIGITS.get(pair,5); base=BASES.get(pair,mid); sp=PIPS.get(pair,1e-4)*0.8
            _mt5_prices[pair]={"pair":pair,"mid":round(mid,d),"bid":round(mid-sp/2,d),"ask":round(mid+sp/2,d),
                "change":round(mid-base,d),"change_pct":round((mid-base)/base*100,4),
                "high_24h":max(_mt5_prices.get(pair,{}).get("high_24h",mid),mid),
                "low_24h":min(_mt5_prices.get(pair,{}).get("low_24h",mid),mid)}
    candles=item.get("candles",[])
    if not candles: return []
    _mt5_candles.setdefault(pair,{})[tf]=candles
    return engine.evaluate(pair,tf,candles)

class MT5Batch(BaseModel):
    secret: str=""
    data: list

class OutcomeUpdate(BaseModel):
    outcome: str

@app.post("/api/mt5/batch")
async def mt5_batch(payload: MT5Batch):
    if payload.secret and payload.secret!=MT5_SECRET:
        return {"status":"error","msg":"unauthorized"}
    all_sigs=[]
    for item in payload.data:
        if isinstance(item,dict):
            sigs=await process_item(item)
            all_sigs.extend(sigs)
    if all_sigs:
        for s in all_sigs: db.save_signal(s)
        await broadcast({"type":"signals","data":all_sigs,"ts":datetime.now(timezone.utc).isoformat()})
        log.info(f"Broadcast {len(all_sigs)} signals")
    await broadcast({"type":"prices","data":get_prices(),"mt5_connected":mt5_connected(),"ts":datetime.now(timezone.utc).isoformat()})
    return {"status":"ok","signals":len(all_sigs)}

@app.get("/api/health")
def health():
    return {"status":"ok","version":"5.0","mt5_connected":mt5_connected(),
            "clients":len(clients),"pairs_loaded":list(_mt5_candles.keys()),
            "ts":datetime.now(timezone.utc).isoformat()}

@app.get("/api/signals")
def get_signals(limit:int=100,pair:Optional[str]=None,strategy:Optional[str]=None,outcome:Optional[str]=None):
    return db.get_signals(limit,pair,strategy,outcome)

@app.get("/api/stats")
def get_stats(): return db.get_stats()

@app.patch("/api/signals/{sid}/outcome")
def update_outcome(sid:str,body:OutcomeUpdate):
    db.update_outcome(sid,body.outcome); return {"status":"ok"}

@app.get("/api/candles/{pair}/{tf}")
def get_candles(pair:str,tf:str):
    return _mt5_candles.get(pair.upper(),{}).get(tf.upper(),[])

@app.get("/api/prices")
def prices(): return get_prices()

@app.websocket("/ws")
async def ws_endpoint(ws:WebSocket):
    await ws.accept(); clients.append(ws)
    try:
        await ws.send_json({"type":"init","prices":get_prices(),"candles":dict(_mt5_candles),
            "signals":db.get_signals(50),"stats":db.get_stats(),"mt5_connected":mt5_connected(),
            "ts":datetime.now(timezone.utc).isoformat()})
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        if ws in clients: clients.remove(ws)

async def keep_alive():
    import aiohttp
    url=os.getenv("RENDER_EXTERNAL_URL","")
    if not url: return
    while True:
        await asyncio.sleep(840)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{url}/api/health"): pass
        except: pass

@app.on_event("startup")
async def startup():
    db.init(); asyncio.create_task(keep_alive())
    log.info("APEX FX v5 started — MT5 only mode")

frontend_path=os.path.join(os.path.dirname(__file__),"..","frontend")
if os.path.exists(frontend_path):
    app.mount("/static",StaticFiles(directory=frontend_path),name="static")

@app.get("/")
def root():
    fp=os.path.join(frontend_path,"index.html")
    if os.path.exists(fp): return FileResponse(fp)
    return {"status":"APEX FX v5 running"}

if __name__=="__main__":
    uvicorn.run("main:app",host="0.0.0.0",port=int(os.getenv("PORT",8000)),reload=False)
