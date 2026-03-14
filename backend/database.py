"""APEX FX - Database"""
import sqlite3, json, os
from datetime import datetime, timezone
from typing import Optional

class Database:
    def __init__(self, path="data/apexfx.db"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def init(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY, pair TEXT, timeframe TEXT, type TEXT,
                    entry REAL, tp1 REAL, tp2 REAL, sl_tight REAL, sl_standard REAL, sl_wide REAL,
                    strategy TEXT, reason TEXT, strength TEXT, risk_reward REAL,
                    indicators TEXT, fib_data TEXT, fvg_data TEXT,
                    timestamp TEXT, outcome TEXT DEFAULT 'pending',
                    outcome_note TEXT, created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS alert_configs (
                    email TEXT PRIMARY KEY, telegram_chat_id TEXT,
                    pairs TEXT, strategies TEXT, signal_types TEXT,
                    min_strength TEXT DEFAULT 'medium', active INTEGER DEFAULT 1,
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS open_trades (
                    id TEXT PRIMARY KEY, signal_id TEXT, pair TEXT, type TEXT,
                    entry REAL, tp1 REAL, tp2 REAL, sl REAL,
                    tp1_hit INTEGER DEFAULT 0, be_alerted INTEGER DEFAULT 0,
                    opened_at TEXT, closed_at TEXT, status TEXT DEFAULT 'open'
                );
                CREATE INDEX IF NOT EXISTS idx_sig_pair ON signals(pair);
                CREATE INDEX IF NOT EXISTS idx_sig_ts   ON signals(timestamp);
                CREATE INDEX IF NOT EXISTS idx_sig_strat ON signals(strategy);
            """)

    def save_signal(self, s: dict):
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO signals
                (id,pair,timeframe,type,entry,tp1,tp2,sl_tight,sl_standard,sl_wide,
                 strategy,reason,strength,risk_reward,indicators,fib_data,fvg_data,timestamp)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                s["id"], s["pair"], s.get("timeframe","H1"), s["type"],
                s["entry"], s.get("tp1", s.get("tp")), s.get("tp2"),
                s.get("sl_tight"), s.get("sl_standard", s.get("sl")), s.get("sl_wide"),
                s["strategy"], s.get("reason",""), s.get("strength","medium"),
                s.get("risk_reward",0), json.dumps(s.get("indicators",{})),
               json.dumps(s.get("fib_levels")), json.dumps(s.get("fvg")),
                s.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ))

    def update_outcome(self, sig_id: str, outcome: str, note: str = ""):
        with self._conn() as c:
            c.execute("UPDATE signals SET outcome=?,outcome_note=? WHERE id=?", (outcome, note, sig_id))

    def get_signals(self, limit=100, pair=None, strategy=None, outcome=None):
        q = "SELECT * FROM signals WHERE 1=1"
        args = []
        if pair:     q += " AND pair=?";     args.append(pair)
        if strategy: q += " AND strategy=?"; args.append(strategy)
        if outcome:  q += " AND outcome=?";  args.append(outcome)
        q += " ORDER BY timestamp DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for f in ("indicators","fib_data","fvg_data"):
                try: d[f] = json.loads(d.get(f) or "{}")
                except: d[f] = {}
            out.append(d)
        return out

    def get_stats(self):
        with self._conn() as c:
            total   = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            today   = c.execute("SELECT COUNT(*) FROM signals WHERE DATE(timestamp)=DATE('now')").fetchone()[0]
            by_type = c.execute("SELECT type,COUNT(*) n FROM signals GROUP BY type").fetchall()
            by_pair = c.execute("SELECT pair,COUNT(*) n FROM signals GROUP BY pair ORDER BY n DESC").fetchall()
            by_strat= c.execute("SELECT strategy,COUNT(*) n FROM signals GROUP BY strategy ORDER BY n DESC").fetchall()
            wins    = c.execute("SELECT COUNT(*) FROM signals WHERE outcome='win'").fetchone()[0]
            losses  = c.execute("SELECT COUNT(*) FROM signals WHERE outcome='loss'").fetchone()[0]
            avg_rr  = c.execute("SELECT AVG(risk_reward) FROM signals WHERE outcome IN ('win','loss')").fetchone()[0]
        closed = wins + losses
        return {
            "total": total, "today": today, "wins": wins, "losses": losses,
            "win_rate": round(wins/closed*100,1) if closed else 0,
            "avg_rr": round(avg_rr,2) if avg_rr else 0,
            "by_type":  [dict(r) for r in by_type],
            "by_pair":  [dict(r) for r in by_pair],
            "by_strat": [dict(r) for r in by_strat],
        }

    def save_alert_config(self, cfg: dict):
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO alert_configs
                (email,telegram_chat_id,pairs,strategies,signal_types,min_strength,active,updated_at)
                VALUES(?,?,?,?,?,?,?,datetime('now'))""", (
                cfg.get("email",""), cfg.get("telegram_chat_id",""),
                json.dumps(cfg.get("pairs",[])), json.dumps(cfg.get("strategies",[])),
                json.dumps(cfg.get("signal_types",[])), cfg.get("min_strength","medium"),
                1 if cfg.get("active",True) else 0,
            ))

    def get_active_configs(self):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM alert_configs WHERE active=1").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for f in ("pairs","strategies","signal_types"):
                try: d[f] = json.loads(d.get(f) or "[]")
                except: d[f] = []
            out.append(d)
        return out

    def open_trade(self, sig: dict, sl_choice: str):
        sl_map = {"tight": sig.get("sl_tight"), "standard": sig.get("sl_standard", sig.get("sl")), "wide": sig.get("sl_wide")}
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO open_trades
                (id,signal_id,pair,type,entry,tp1,tp2,sl,opened_at)
                VALUES(?,?,?,?,?,?,?,?,datetime('now'))""", (
                sig["id"], sig["id"], sig["pair"], sig["type"],
                sig["entry"], sig.get("tp1"), sig.get("tp2"),
                sl_map.get(sl_choice, sig.get("sl_standard")),
            ))

    def get_open_trades(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM open_trades WHERE status='open'").fetchall()]

    def update_trade(self, trade_id: str, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        with self._conn() as c:
            c.execute(f"UPDATE open_trades SET {sets} WHERE id=?", (*kwargs.values(), trade_id))
