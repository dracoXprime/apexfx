"""APEX FX - Trade Tracker: monitors open trades and fires management alerts."""
import logging
from alerts import dispatch_trade_event

log = logging.getLogger("apexfx.tracker")

async def check_open_trades(db, prices: dict):
    trades = db.get_open_trades()
    for t in trades:
        price_data = prices.get(t["pair"],{})
        if not price_data: continue
        price = price_data.get("mid", 0)
        if not price: continue

        is_long = t["type"] in ("buy","buy_limit")
        entry   = t["entry"]
        tp1     = t["tp1"]
        tp2     = t["tp2"]
        sl      = t["sl"]

        # SL hit
        if is_long and price <= sl:
            db.update_trade(t["id"], status="closed")
            db.update_outcome(t["signal_id"], "loss", f"SL hit at {price}")
            await dispatch_trade_event("sl", t)
            log.info(f"SL HIT {t['pair']} @ {price}")
            continue
        if not is_long and price >= sl:
            db.update_trade(t["id"], status="closed")
            db.update_outcome(t["signal_id"], "loss", f"SL hit at {price}")
            await dispatch_trade_event("sl", t)
            continue

        # TP2 hit (full target)
        if tp2:
            if is_long and price >= tp2:
                db.update_trade(t["id"], status="closed")
                db.update_outcome(t["signal_id"], "win", f"TP2 hit at {price}")
                await dispatch_trade_event("tp2", t)
                log.info(f"TP2 HIT {t['pair']} @ {price}")
                continue
            if not is_long and price <= tp2:
                db.update_trade(t["id"], status="closed")
                db.update_outcome(t["signal_id"], "win", f"TP2 hit at {price}")
                await dispatch_trade_event("tp2", t)
                continue

        # TP1 hit (50% close, move SL to BE)
        if tp1 and not t.get("tp1_hit"):
            if (is_long and price >= tp1) or (not is_long and price <= tp1):
                db.update_trade(t["id"], tp1_hit=1)
                db.update_outcome(t["signal_id"], "partial", f"TP1 hit at {price}")
                await dispatch_trade_event("tp1", t)
                log.info(f"TP1 HIT {t['pair']} @ {price}")
                continue

        # Break-even alert (1:1 reached, not yet alerted)
        if not t.get("be_alerted"):
            risk = abs(entry - sl)
            if risk > 0:
                if is_long and price >= entry + risk:
                    db.update_trade(t["id"], be_alerted=1)
                    await dispatch_trade_event("be", t)
                if not is_long and price <= entry - risk:
                    db.update_trade(t["id"], be_alerted=1)
                    await dispatch_trade_event("be", t)
