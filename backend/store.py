"""
APEX FX - Data Store
In-memory store for candles, prices, and signals.
SQLite for signal persistence across restarts.
"""
import sqlite3, json, logging, os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("apexfx.store")

PAIRS = ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","GBPJPY","XAUUSD"]
TFS   = ["M15","H1","H4"]

DIGITS = {"EURUSD":5,"GBPUSD":5,"AUDUSD":5,"USDCAD":5,
          "GBPJPY":3,"USDJPY":3,"XAUUSD":2}

DB_PATH = os.getenv("DB_PATH", "/tmp/apexfx.db")


class DataStore:

    def __init__(self):
        self._candles: dict = {p: {tf: [] for tf in TFS} for p in PAIRS}
        self._prices:  dict = {}
        self._mt5_last: Optional[datetime] = None

    # ── Init ──────────────────────────────────────────────────────────────

    def init(self):
        with self._db() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    pair TEXT, tf TEXT, type TEXT,
                    entry REAL, tp1 REAL, tp2 REAL,
                    sl_tight REAL, sl_standard REAL, sl_wide REAL,
                    strategy TEXT, reason TEXT, strength TEXT,
                    risk_reward REAL, outcome TEXT DEFAULT 'pending',
                    note TEXT DEFAULT '',
                    ts TEXT
                )
            """)
        log.info("DataStore initialised")

    def _db(self):
        return sqlite3.connect(DB_PATH)

    # ── Candles ───────────────────────────────────────────────────────────

    def set_candles(self, pair: str, tf: str, candles: list):
        if pair in self._candles and tf in TFS:
            self._candles[pair][tf] = candles
            self._mt5_last = datetime.now(timezone.utc)

    def get_candles(self, pair: str, tf: str) -> list:
        return list(self._candles.get(pair, {}).get(tf, []))

    def get_all_candles(self) -> dict:
        return {p: {tf: self.get_candles(p, tf) for tf in TFS} for p in PAIRS}

    # ── Prices ────────────────────────────────────────────────────────────

    def set_price(self, pair: str, mid: float, raw: dict):
        d = DIGITS.get(pair, 5)
        bid = float(raw.get("bid", mid))
        ask = float(raw.get("ask", mid))
        self._prices[pair] = {
            "pair":   pair,
            "mid":    round(mid, d),
            "bid":    round(bid, d),
            "ask":    round(ask, d),
            "spread": round(ask - bid, d),
        }
        self._mt5_last = datetime.now(timezone.utc)

    def get_price(self, pair: str) -> dict:
        return self._prices.get(pair, {"pair": pair, "mid": 0})

    def get_prices(self) -> dict:
        return dict(self._prices)

    # ── MT5 status ────────────────────────────────────────────────────────

    def mt5_connected(self) -> bool:
        if not self._mt5_last:
            return False
        age = (datetime.now(timezone.utc) - self._mt5_last).total_seconds()
        return age < 300  # connected if data received within 5 minutes

    # ── Signals ───────────────────────────────────────────────────────────

    def save_signal(self, s: dict):
        try:
            with self._db() as c:
                c.execute("""
                    INSERT OR REPLACE INTO signals
                    (id,pair,tf,type,entry,tp1,tp2,sl_tight,sl_standard,sl_wide,
                     strategy,reason,strength,risk_reward,outcome,note,ts)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    s["id"], s["pair"], s.get("tf","H1"), s["type"],
                    s["entry"], s.get("tp1"), s.get("tp2"),
                    s.get("sl_tight"), s.get("sl_standard"), s.get("sl_wide"),
                    s["strategy"], s.get("reason",""), s.get("strength","medium"),
                    s.get("risk_reward", 0), "pending", "",
                    s.get("ts", datetime.now(timezone.utc).isoformat())
                ))
        except Exception as e:
            log.error(f"save_signal error: {e}")

    def get_signals(self, limit: int = 100) -> list:
        try:
            with self._db() as c:
                rows = c.execute("""
                    SELECT id,pair,tf,type,entry,tp1,tp2,sl_tight,sl_standard,sl_wide,
                           strategy,reason,strength,risk_reward,outcome,note,ts
                    FROM signals ORDER BY ts DESC LIMIT ?
                """, (limit,)).fetchall()
            return [self._row_to_signal(r) for r in rows]
        except:
            return []

    def update_outcome(self, sig_id: str, outcome: str, note: str = ""):
        try:
            with self._db() as c:
                c.execute("UPDATE signals SET outcome=?,note=? WHERE id=?",
                    (outcome, note, sig_id))
        except Exception as e:
            log.error(f"update_outcome error: {e}")

    def _row_to_signal(self, r) -> dict:
        return {
            "id": r[0], "pair": r[1], "tf": r[2], "type": r[3],
            "entry": r[4], "tp1": r[5], "tp2": r[6],
            "sl_tight": r[7], "sl_standard": r[8], "sl_wide": r[9],
            "strategy": r[10], "reason": r[11], "strength": r[12],
            "risk_reward": r[13], "outcome": r[14], "note": r[15], "ts": r[16],
        }

    def get_stats(self) -> dict:
        try:
            with self._db() as c:
                total  = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
                wins   = c.execute("SELECT COUNT(*) FROM signals WHERE outcome='win'").fetchone()[0]
                losses = c.execute("SELECT COUNT(*) FROM signals WHERE outcome='loss'").fetchone()[0]
                today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                today_c= c.execute("SELECT COUNT(*) FROM signals WHERE ts LIKE ?",
                    (today+"%",)).fetchone()[0]
                # By strategy
                rows = c.execute("""
                    SELECT strategy, COUNT(*) as n FROM signals
                    GROUP BY strategy ORDER BY n DESC LIMIT 10
                """).fetchall()
                by_strat = {r[0]: r[1] for r in rows}
                # By pair
                rows = c.execute("""
                    SELECT pair, COUNT(*) as n FROM signals
                    GROUP BY pair ORDER BY n DESC
                """).fetchall()
                by_pair = {r[0]: r[1] for r in rows}
            return {
                "total": total, "wins": wins, "losses": losses,
                "today": today_c, "by_strategy": by_strat, "by_pair": by_pair,
            }
        except:
            return {"total":0,"wins":0,"losses":0,"today":0,"by_strategy":{},"by_pair":{}}
