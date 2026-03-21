"""
APEX FX - Market Scheduler
Generates session and market messages for the dashboard only.
No Telegram, no email.
"""
from datetime import datetime, timezone

_sent: dict = {}

def _key(label): 
    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}:{label}"

def _sent_today(label): 
    return _sent.get(_key(label), False)

def _mark(label): 
    _sent[_key(label)] = True

def market_message(now: datetime) -> dict | None:
    dow  = now.weekday()  # 0=Mon 4=Fri 5=Sat 6=Sun
    h    = now.hour
    m    = now.minute

    # Friday 21:55 — closing warning
    if dow==4 and h==21 and 54<=m<=56 and not _sent_today("fri_warn"):
        _mark("fri_warn")
        return {"type":"warning","text":"⏰ Markets closing in 5 minutes (22:00 UTC). APEX FX will pause."}

    # Friday 22:00 — closed
    if dow==4 and h==22 and m==0 and not _sent_today("fri_close"):
        _mark("fri_close")
        return {"type":"closed","text":"🔴 Forex markets closed. Monitoring paused until Sunday 22:00 UTC."}

    # Sunday 21:55 — opening warning
    if dow==6 and h==21 and 54<=m<=56 and not _sent_today("sun_warn"):
        _mark("sun_warn")
        return {"type":"warning","text":"⏰ Markets opening in 5 minutes (22:00 UTC). Prepare your charts."}

    # Sunday 22:00 — open
    if dow==6 and h==22 and m==0 and not _sent_today("sun_open"):
        _mark("sun_open")
        return {"type":"open","text":f"🟢 New week — markets open. APEX FX monitoring all pairs."}

    # Daily 00:01 — new day
    if dow in range(5) and h==0 and m==1 and not _sent_today("new_day"):
        _mark("new_day")
        day = now.strftime("%A %d %B")
        return {"type":"info","text":f"☀️ New day — {day}\n🌏 Tokyo: 00:00-09:00 · 🇬🇧 London: 08:00-17:00 · 🇺🇸 New York: 13:00-22:00 UTC"}

    # London open 08:00
    if dow in range(5) and h==8 and m==0 and not _sent_today("london"):
        _mark("london")
        return {"type":"session","text":"🇬🇧 London session open — watch EUR/USD, GBP/USD, GBP/JPY\nORB window: 08:00–09:00 UTC"}

    # New York open 13:00
    if dow in range(5) and h==13 and m==0 and not _sent_today("ny"):
        _mark("ny")
        return {"type":"session","text":"🇺🇸 New York session open — London/NY overlap begins\nHighest volume period · ORB window: 13:00–14:00 UTC"}

    return None


def is_market_open() -> bool:
    now = datetime.now(timezone.utc)
    dow = now.weekday(); h = now.hour
    if dow == 5: return False
    if dow == 6 and h < 22: return False
    if dow == 4 and h >= 22: return False
    return True
