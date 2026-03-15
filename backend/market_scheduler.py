"""
APEX FX - Market Scheduler
Handles automatic market open/close based on forex session times.

Schedule (all UTC):
  Friday    21:55  → 5-minute warning (market closing soon)
  Friday    22:00  → End of week summary + monitoring paused
  Sunday    21:55  → 5-minute warning (market opening soon)
  Sunday    22:00  → New week message + monitoring resumes
  Daily     22:00  → End of day summary (Mon-Thu)
  Daily     00:01  → New day message (Mon-Fri)
"""

import logging
from datetime import datetime, timezone
from alerts import send_telegram, ALERT_EMAIL, send_email

log = logging.getLogger("apexfx.scheduler")

# Track what messages have been sent today to avoid duplicates
_sent: dict = {}


def _key(label: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m-%d')}:{label}"


def _already_sent(label: str) -> bool:
    return _sent.get(_key(label), False)


def _mark_sent(label: str):
    _sent[_key(label)] = True


# ── Telegram message formatters ───────────────────────────────────────────────

def _msg_market_warning_close():
    return (
        "⏰ <b>MARKET CLOSING IN 5 MINUTES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Forex markets close at 22:00 UTC.\n"
        "APEX FX will pause monitoring until Sunday 22:00 UTC.\n"
        "Close any open trades if needed."
    )

def _msg_market_close(stats: dict):
    total = stats.get("total", 0)
    wins  = stats.get("wins",  0)
    losses= stats.get("losses",0)
    today = stats.get("today", 0)
    wr    = f"{round(wins/(wins+losses)*100,1)}%" if (wins+losses) > 0 else "—"
    by_pair  = stats.get("by_pair",  {})
    by_strat = stats.get("by_strat", {})
    top_pair  = max(by_pair,  key=by_pair.get)  if by_pair  else "—"
    top_strat = max(by_strat, key=by_strat.get) if by_strat else "—"

    return (
        "🔴 <b>MARKETS CLOSED — END OF WEEK</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Weekly Summary</b>\n"
        f"  Total signals:    <code>{total}</code>\n"
        f"  This session:     <code>{today}</code>\n"
        f"  Marked wins:      <code>{wins}</code>\n"
        f"  Marked losses:    <code>{losses}</code>\n"
        f"  Win rate:         <b>{wr}</b>\n"
        f"  Top pair:         <code>{top_pair}</code>\n"
        f"  Top strategy:     <code>{top_strat}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏸ Monitoring paused. Resuming Sunday 22:00 UTC.\n"
        "<i>Review your journal and mark any open trades.</i>"
    )

def _msg_market_warning_open():
    return (
        "⏰ <b>MARKET OPENING IN 5 MINUTES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Forex markets open at 22:00 UTC (Sunday).\n"
        "APEX FX will resume monitoring shortly.\n"
        "Prepare your charts."
    )

def _msg_market_open():
    now = datetime.now(timezone.utc)
    week = now.strftime("Week %W, %Y")
    return (
        "🟢 <b>MARKETS OPEN — NEW WEEK</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {week}\n\n"
        "APEX FX is now monitoring:\n"
        "  💱 EUR/USD · GBP/USD · USD/JPY\n"
        "  💱 AUD/USD · USD/CAD · GBP/JPY\n"
        "  🥇 XAU/USD (Gold)\n\n"
        "  ⏱ Timeframes: M15 · H1 · H4\n"
        "  📐 Strategies: 14 active\n\n"
        "▶ Monitoring resumed. Good luck this week."
    )

def _msg_end_of_day(stats: dict):
    now = datetime.now(timezone.utc)
    day = now.strftime("%A %d %B")
    today_sigs = stats.get("today", 0)
    wins  = stats.get("wins",  0)
    losses= stats.get("losses",0)
    wr    = f"{round(wins/(wins+losses)*100,1)}%" if (wins+losses) > 0 else "—"
    by_pair  = stats.get("by_pair",  {})
    top_pair = max(by_pair, key=by_pair.get) if by_pair else "—"

    return (
        f"🌙 <b>END OF DAY — {day}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"  Signals today:    <code>{today_sigs}</code>\n"
        f"  Marked wins:      <code>{wins}</code>\n"
        f"  Marked losses:    <code>{losses}</code>\n"
        f"  Win rate:         <b>{wr}</b>\n"
        f"  Most active pair: <code>{top_pair}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Markets continue overnight. New day summary at 00:01 UTC.</i>"
    )

def _msg_new_day():
    now = datetime.now(timezone.utc)
    day = now.strftime("%A %d %B %Y")
    sessions = {
        0: "Asian session active",
        1: "Asian session active",
        2: "Asian/London overlap soon",
        3: "Asian/London overlap soon",
        4: "Asian/London overlap soon",
        5: "Asian/London overlap soon",
        6: "Pre-London",
        7: "London session opening soon",
        8: "🇬🇧 London session open",
    }
    sess = sessions.get(now.hour, "Markets active")
    return (
        f"☀️ <b>NEW DAY — {day}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"  {sess}\n\n"
        "  Key session times (UTC):\n"
        "  🌏 Tokyo:    00:00 – 09:00\n"
        "  🇬🇧 London:   08:00 – 17:00\n"
        "  🇺🇸 New York: 13:00 – 22:00\n"
        "  ⚡ Overlap:  13:00 – 17:00 (highest volume)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "▶ APEX FX monitoring all pairs."
    )

def _msg_london_open():
    return (
        "🇬🇧 <b>LONDON SESSION OPEN</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "08:00 UTC — London is the most active forex session.\n"
        "Watch for ORB setups and increased volatility on:\n"
        "  EUR/USD · GBP/USD · GBP/JPY\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Opening Range Breakout window: 08:00–09:00 UTC</i>"
    )

def _msg_newyork_open():
    return (
        "🇺🇸 <b>NEW YORK SESSION OPEN</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "13:00 UTC — London/NY overlap begins.\n"
        "Highest volume period of the day.\n"
        "Watch for ORB setups on:\n"
        "  EUR/USD · USD/CAD · XAU/USD\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Opening Range Breakout window: 13:00–14:00 UTC</i>"
    )


# ── Email formatters ──────────────────────────────────────────────────────────

def _email_eow(stats: dict) -> tuple:
    total = stats.get("total",0); wins = stats.get("wins",0)
    losses = stats.get("losses",0)
    wr = f"{round(wins/(wins+losses)*100,1)}%" if (wins+losses) > 0 else "—"
    subj = f"APEX FX — End of Week Summary | {wins}W / {losses}L | WR: {wr}"
    html = f"""<!DOCTYPE html><html><body style="background:#040C11;padding:24px;font-family:'Courier New',monospace;">
<table width="520" style="margin:0 auto;background:#0C1820;border:1px solid #162230;border-radius:5px;overflow:hidden;">
<tr><td style="background:#FF3D5A;height:3px;"></td></tr>
<tr><td style="padding:22px 24px;">
<p style="font-size:20px;font-weight:bold;color:#00C8F0;letter-spacing:3px;margin:0 0 4px;">APEX<span style="color:#D8EAF0;">FX</span></p>
<p style="font-size:16px;font-weight:bold;color:#D8EAF0;margin:0 0 16px;">🔴 End of Week Summary</p>
<table width="100%" style="border:1px solid #162230;border-radius:3px;overflow:hidden;">
<tr style="background:#081218;"><td style="padding:8px 12px;color:#567080;font-size:11px;">Total Signals</td><td style="padding:8px 12px;color:#D8EAF0;font-size:13px;font-weight:bold;">{total}</td></tr>
<tr><td style="padding:8px 12px;color:#567080;font-size:11px;">Wins</td><td style="padding:8px 12px;color:#00E87A;font-size:13px;">{wins}</td></tr>
<tr style="background:#081218;"><td style="padding:8px 12px;color:#567080;font-size:11px;">Losses</td><td style="padding:8px 12px;color:#FF3D5A;font-size:13px;">{losses}</td></tr>
<tr><td style="padding:8px 12px;color:#567080;font-size:11px;">Win Rate</td><td style="padding:8px 12px;color:#00C8F0;font-size:15px;font-weight:bold;">{wr}</td></tr>
</table>
<p style="font-size:10px;color:#567080;margin-top:16px;">Monitoring paused until Sunday 22:00 UTC. Review your journal.</p>
</td></tr>
<tr><td style="background:#FF3D5A;height:2px;"></td></tr>
</table></body></html>"""
    return subj, html

def _email_eod(stats: dict) -> tuple:
    now = datetime.now(timezone.utc)
    day = now.strftime("%A %d %B")
    today = stats.get("today",0); wins = stats.get("wins",0); losses = stats.get("losses",0)
    wr = f"{round(wins/(wins+losses)*100,1)}%" if (wins+losses) > 0 else "—"
    subj = f"APEX FX — End of Day {day} | {today} signals"
    html = f"""<!DOCTYPE html><html><body style="background:#040C11;padding:24px;font-family:'Courier New',monospace;">
<table width="520" style="margin:0 auto;background:#0C1820;border:1px solid #162230;border-radius:5px;overflow:hidden;">
<tr><td style="background:#FFB300;height:3px;"></td></tr>
<tr><td style="padding:22px 24px;">
<p style="font-size:20px;font-weight:bold;color:#00C8F0;letter-spacing:3px;margin:0 0 4px;">APEX<span style="color:#D8EAF0;">FX</span></p>
<p style="font-size:16px;font-weight:bold;color:#D8EAF0;margin:0 0 16px;">🌙 End of Day — {day}</p>
<table width="100%"  style="border:1px solid #162230;border-radius:3px;overflow:hidden;">
<tr style="background:#081218;"><td style="padding:8px 12px;color:#567080;font-size:11px;">Signals Today</td><td style="padding:8px 12px;color:#D8EAF0;font-size:13px;font-weight:bold;">{today}</td></tr>
<tr><td style="padding:8px 12px;color:#567080;font-size:11px;">Win Rate</td><td style="padding:8px 12px;color:#00C8F0;font-size:13px;">{wr}</td></tr>
</table>
<p style="font-size:10px;color:#567080;margin-top:16px;">Markets continue overnight. Check the journal at dracoprimexr@gmail.com</p>
</td></tr>
<tr><td style="background:#FFB300;height:2px;"></td></tr>
</table></body></html>"""
    return subj, html


# ── Main scheduler tick ───────────────────────────────────────────────────────

async def scheduler_tick(db, monitoring_state: dict):
    """
    Call this every minute from the main loop.
    monitoring_state is a dict with key 'active' (bool) that main.py controls.
    """
    now  = datetime.now(timezone.utc)
    dow  = now.weekday()   # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now.hour
    minute = now.minute

    stats = db.get_stats()

    # ── FRIDAY 21:55 — 5-minute warning ──────────────────────────────────────
    if dow == 4 and hour == 21 and minute == 55:
        if not _already_sent("fri_warning"):
            await send_telegram(_msg_market_warning_close())
            _mark_sent("fri_warning")
            log.info("Sent: Friday market close warning")

    # ── FRIDAY 22:00 — End of week, pause monitoring ─────────────────────────
    if dow == 4 and hour == 22 and minute == 0:
        if not _already_sent("fri_close"):
            monitoring_state["active"] = False
            await send_telegram(_msg_market_close(stats))
            subj, html = _email_eow(stats)
            send_email(ALERT_EMAIL, subj, html)
            _mark_sent("fri_close")
            log.info("Market closed — monitoring paused for weekend")

    # ── SUNDAY 21:55 — 5-minute warning ──────────────────────────────────────
    if dow == 6 and hour == 21 and minute == 55:
        if not _already_sent("sun_warning"):
            await send_telegram(_msg_market_warning_open())
            _mark_sent("sun_warning")
            log.info("Sent: Sunday market open warning")

    # ── SUNDAY 22:00 — New week, resume monitoring ────────────────────────────
    if dow == 6 and hour == 22 and minute == 0:
        if not _already_sent("sun_open"):
            monitoring_state["active"] = True
            await send_telegram(_msg_market_open())
            _mark_sent("sun_open")
            log.info("Market opened — monitoring resumed")

    # ── DAILY 22:00 — End of day summary (Mon–Thu) ───────────────────────────
    if dow in (0,1,2,3) and hour == 22 and minute == 0:
        if not _already_sent("eod"):
            await send_telegram(_msg_end_of_day(stats))
            subj, html = _email_eod(stats)
            send_email(ALERT_EMAIL, subj, html)
            _mark_sent("eod")
            log.info("Sent: End of day summary")

    # ── DAILY 00:01 — New day message (Mon–Fri) ───────────────────────────────
    if dow in (0,1,2,3,4) and hour == 0 and minute == 1:
        if not _already_sent("new_day"):
            await send_telegram(_msg_new_day())
            _mark_sent("new_day")
            log.info("Sent: New day message")

    # ── LONDON OPEN 08:00 — Session alert ────────────────────────────────────
    if dow in (0,1,2,3,4) and hour == 8 and minute == 0:
        if not _already_sent("london_open"):
            await send_telegram(_msg_london_open())
            _mark_sent("london_open")
            log.info("Sent: London session open")

    # ── NEW YORK OPEN 13:00 — Session alert ──────────────────────────────────
    if dow in (0,1,2,3,4) and hour == 13 and minute == 0:
        if not _already_sent("ny_open"):
            await send_telegram(_msg_newyork_open())
            _mark_sent("ny_open")
            log.info("Sent: New York session open")
