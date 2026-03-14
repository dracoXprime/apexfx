"""APEX FX - Telegram + Email Alerts"""
import os, logging, smtplib, aiohttp
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger("apexfx.alerts")

TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN","")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")
SMTP_USER  = os.getenv("SMTP_USER","")
SMTP_PASS  = os.getenv("SMTP_PASS","")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
ALERT_EMAIL= os.getenv("ALERT_EMAIL","dracoprimexr@gmail.com")

TYPE_EMOJI = {"buy":"🟢","sell":"🔴","buy_limit":"🟡","sell_limit":"🟠"}
TYPE_LABEL = {"buy":"BUY ↑","sell":"SELL ↓","buy_limit":"BUY LIMIT ↑","sell_limit":"SELL LIMIT ↓"}
STRENGTH_EMOJI = {"high":"🔥","medium":"⚡","low":"💧"}

def _pair_display(pair):
    return f"{pair[:3]}/{pair[3:]}"

# ─── Telegram ──────────────────────────────────────────────────────────────

async def send_telegram(text: str, chat_id: str = ""):
    if not TG_TOKEN: return
    cid = chat_id or TG_CHAT_ID
    if not cid: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=payload) as r:
                if r.status != 200:
                    log.error(f"Telegram error {r.status}: {await r.text()}")
    except Exception as e:
        log.error(f"Telegram send error: {e}")


def format_signal_tg(sig: dict) -> str:
    d = DIGITS.get(sig["pair"], 5)
    te = TYPE_EMOJI.get(sig["type"],"⚪")
    tl = TYPE_LABEL.get(sig["type"], sig["type"].upper())
    se = STRENGTH_EMOJI.get(sig["strength"],"⚡")
    pair = _pair_display(sig["pair"])
    tf = sig.get("timeframe","")
    strat = sig.get("strategy","")
    star = "⭐ " if strat == "Fib Golden Zone + FVG" else ""

    tp2_line = f"\n  TP2:     <code>{sig['tp2']}</code> (1.618 ext)" if sig.get("tp2") else ""
    fib_line = ""
    if sig.get("fib_levels"):
        fl = sig["fib_levels"]
        fib_line = f"\n📐 <b>Fib:</b> 50%={fl.get('50','?')}  61.8%={fl.get('61.8','?')}  78.6%={fl.get('78.6','?')}"
    fvg_line = ""
    if sig.get("fvg"):
        fvg = sig["fvg"]
        fvg_line = f"\n🔷 <b>FVG Zone:</b> {fvg.get('bot','?')} – {fvg.get('top','?')}"

    sl_lines = ""
    if sig.get("sl_tight") != sig.get("sl_standard"):
        sl_lines = (
            f"\n  SL Tight:    <code>{sig['sl_tight']}</code>"
            f"\n  SL Standard: <code>{sig['sl_standard']}</code>"
            f"\n  SL Wide:     <code>{sig['sl_wide']}</code>"
        )
    else:
        sl_lines = f"\n  SL:      <code>{sig['sl_standard']}</code>"

    rr = sig.get("risk_reward",0)
    rr_str = f"1:{rr}" if rr else "—"

    return (
        f"{te} <b>{star}{tl}</b>  {se} {sig['strength'].upper()}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💱 <b>{pair}</b>  |  {tf}  |  {star}{strat}\n"
        f"\n"
        f"  Entry:   <code>{sig['entry']}</code>\n"
        f"  TP1:     <code>{sig['tp1']}</code>{tp2_line}{sl_lines}\n"
        f"  R:R      <b>{rr_str}</b>\n"
        f"{fib_line}{fvg_line}\n"
        f"\n"
        f"📋 {sig.get('reason','')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>APEX FX · {sig.get('timestamp','')[:19]} UTC</i>"
    )

DIGITS = {"EURUSD":5,"GBPUSD":5,"AUDUSD":5,"USDCAD":5,"GBPJPY":3,"USDJPY":3,"XAUUSD":2}

def format_trade_event_tg(event: str, trade: dict) -> str:
    pair = _pair_display(trade["pair"])
    events = {
        "be": f"↗️ <b>MOVE SL TO BREAK-EVEN</b>\n💱 {pair} trade is now 1:1 — protect your position.\nSL → <code>{trade['entry']}</code>",
        "tp1": f"✅ <b>TP1 HIT!</b>\n💱 {pair} — first target reached at <code>{trade['tp1']}</code>.\nClose 50% now. Move SL to break-even for the runner.",
        "tp2": f"🏆 <b>TP2 HIT!</b>\n💱 {pair} — full target reached at <code>{trade['tp2']}</code>.\nExcellent trade — full position can be closed.",
        "sl":  f"❌ <b>SL HIT</b>\n💱 {pair} — stop loss hit at <code>{trade['sl']}</code>.\nTrade closed. Review and move on.",
    }
    return events.get(event, f"📌 Trade update: {pair}")

# ─── Email ─────────────────────────────────────────────────────────────────

def format_signal_email(sig: dict) -> tuple[str, str]:
    d = DIGITS.get(sig["pair"], 5)
    pair = _pair_display(sig["pair"])
    tl = TYPE_LABEL.get(sig["type"], sig["type"].upper())
    strat = sig.get("strategy","")
    is_user_strat = strat == "Fib Golden Zone + FVG"
    accent = "#00E87A" if "buy" in sig["type"] else "#FF3D5A"
    star = "⭐ " if is_user_strat else ""

    tp2_row = f'<tr><td style="color:#567080;padding:5px 12px;font-size:11px;">TP2 (1.618 ext)</td><td style="color:#00C8F0;padding:5px 12px;font-size:11px;">{sig["tp2"]}</td></tr>' if sig.get("tp2") else ""
    fib_section = ""
    if sig.get("fib_levels"):
        fl = sig["fib_levels"]
        fib_section = f"""
        <div style="margin:14px 0;padding:10px 14px;background:#0F1A22;border:1px solid #1A2A35;border-radius:3px;font-size:10px;color:#8899AA;">
          <div style="color:#FFB300;font-size:9px;letter-spacing:2px;margin-bottom:6px;">📐 FIB LEVELS</div>
          50% = {fl.get('50','?')} &nbsp;·&nbsp; 61.8% = {fl.get('61.8','?')} &nbsp;·&nbsp; 78.6% = {fl.get('78.6','?')}
        </div>"""
    fvg_section = ""
    if sig.get("fvg"):
        fvg = sig["fvg"]
        fvg_section = f"""
        <div style="margin:14px 0;padding:10px 14px;background:#0A1F15;border:1px solid #1A3525;border-radius:3px;font-size:10px;color:#00E87A;">
          <div style="font-size:9px;letter-spacing:2px;margin-bottom:4px;">🔷 FVG ZONE</div>
          {fvg.get('bot','?')} – {fvg.get('top','?')} &nbsp;(midpoint: {fvg.get('mid','?')})
        </div>"""
    sl_rows = f"""
        <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">SL Tight</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get('sl_tight','—')}</td></tr>
        <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">SL Standard</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get('sl_standard','—')}</td></tr>
        <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">SL Wide</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get('sl_wide','—')}</td></tr>
    """ if sig.get("sl_tight") != sig.get("sl_standard") else f'<tr><td style="color:#567080;padding:5px 12px;font-size:11px;">Stop Loss</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get("sl_standard","—")}</td></tr>'

    subject = f"{'⭐ ' if is_user_strat else ''}APEX FX: {tl} {pair} @ {sig['entry']} | {sig.get('timeframe','')} | {sig['strength'].upper()}"
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:32px 16px;background:#040C11;font-family:'Courier New',monospace;">
<table width="560" cellpadding="0" cellspacing="0" style="margin:0 auto;background:#0C1820;border:1px solid #162230;border-radius:5px;overflow:hidden;max-width:100%;">
  <tr><td style="background:{accent};height:3px;"></td></tr>
  <tr><td style="padding:22px 28px 16px;border-bottom:1px solid #162230;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><span style="font-size:20px;font-weight:bold;letter-spacing:3px;color:#00C8F0;">APEX</span><span style="font-size:20px;font-weight:bold;letter-spacing:3px;color:#D8EAF0;">FX</span></td>
      <td align="right"><span style="font-size:9px;letter-spacing:2px;color:#567080;">{sig.get('timeframe','')} · {sig.get('timestamp','')[:10]}</span></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:22px 28px;">
    <p style="font-size:11px;color:#567080;letter-spacing:2px;margin:0 0 10px;">{STRENGTH_EMOJI.get(sig['strength'],'⚡')} {sig['strength'].upper()} STRENGTH · {star}{strat.upper()}</p>
    <div style="display:inline-block;background:{accent};color:#050A0E;font-size:17px;font-weight:bold;letter-spacing:3px;padding:8px 20px;border-radius:3px;margin-bottom:18px;">{tl}</div>
    <p style="font-size:32px;font-weight:bold;color:#FFFFFF;letter-spacing:2px;margin:0 0 18px;">{pair}</p>
    <table cellpadding="0" cellspacing="0" style="border:1px solid #162230;border-radius:3px;overflow:hidden;margin-bottom:16px;width:100%;">
      <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">Entry</td><td style="color:#D8EAF0;padding:5px 12px;font-size:13px;font-weight:bold;">{sig['entry']}</td></tr>
      <tr style="background:#0F1A22;"><td style="color:#567080;padding:5px 12px;font-size:11px;">TP1 (prior {('high' if 'buy' in sig['type'] else 'low')})</td><td style="color:#00E87A;padding:5px 12px;font-size:11px;">{sig.get('tp1','—')}</td></tr>
      {tp2_row}{sl_rows}
      <tr style="background:#0F1A22;"><td style="color:#567080;padding:5px 12px;font-size:11px;">Risk/Reward</td><td style="color:#00C8F0;padding:5px 12px;font-size:11px;font-weight:bold;">1:{sig.get('risk_reward',0)}</td></tr>
    </table>
    {fib_section}{fvg_section}
    <div style="padding:12px 14px;background:#0F1A22;border-left:3px solid {accent};margin-bottom:20px;font-size:11px;color:#B8D0DC;line-height:1.7;">{sig.get('reason','')}</div>
    <p style="font-size:9px;color:#2A3A45;line-height:1.7;border-top:1px solid #162230;padding-top:14px;">⚠️ This is an automated signal. Apply your own risk management. Forex involves substantial risk of loss. Not financial advice.</p>
  </td></tr>
  <tr><td style="background:#0F1A22;padding:12px 28px;border-top:1px solid #162230;font-size:9px;color:#2A3A45;">APEX FX Signal Platform</td></tr>
  <tr><td style="background:{accent}33;height:2px;"></td></tr>
</table></body></html>"""
    return subject, html


def send_email(to: str, subject: str, html: str) -> bool:
    if not SMTP_USER or not SMTP_PASS or not to: return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"APEX FX Signals <{FROM_EMAIL}>"
        msg["To"] = to
        msg.attach(MIMEText(html,"html"))
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, to, msg.as_string())
        log.info(f"Email sent to {to}")
        return True
    except Exception as e:
        log.error(f"Email error: {e}"); return False


# ─── Combined dispatcher ────────────────────────────────────────────────────

async def dispatch_signal(sig: dict, configs: list):
    tg_text = format_signal_tg(sig)
    for cfg in configs:
        if not _should_send(sig, cfg): continue
        if cfg.get("telegram_chat_id"):
            await send_telegram(tg_text, cfg["telegram_chat_id"])
        if cfg.get("email"):
            subj, html = format_signal_email(sig)
            send_email(cfg["email"], subj, html)
    # Also send to the master config from env
    if TG_CHAT_ID:
        await send_telegram(tg_text)
    if ALERT_EMAIL:
        subj, html = format_signal_email(sig)
        send_email(ALERT_EMAIL, subj, html)


def _should_send(sig: dict, cfg: dict) -> bool:
    lvls = {"low":0,"medium":1,"high":2}
    if lvls.get(sig["strength"],0) < lvls.get(cfg.get("min_strength","low"),0): return False
    if cfg.get("pairs") and sig["pair"] not in cfg["pairs"]: return False
    if cfg.get("signal_types") and sig["type"] not in cfg["signal_types"]: return False
    if cfg.get("strategies") and sig["strategy"] not in cfg["strategies"]: return False
    return True


def format_agreement_tg(sig: dict) -> str:
    """Special high-priority Telegram message for multi-strategy agreement signals."""
    pair   = _pair_display(sig["pair"])
    ag     = sig.get("agreement", {})
    count  = ag.get("count", 0)
    strats = ag.get("strategies", [])
    d      = DIGITS.get(sig["pair"], 5)
    is_buy = sig["type"] in ("buy", "buy_limit")
    arrow  = "↑" if is_buy else "↓"
    color  = "🟢" if is_buy else "🔴"

    strat_list = "\n".join(f"  ✅ {s}" for s in strats)
    tp2_line   = f"\n  TP2:  <code>{sig['tp2']}</code>  (1.618 extension)" if sig.get("tp2") else ""

    sl_block = (
        f"\n  SL Tight:    <code>{sig['sl_tight']}</code>"
        f"\n  SL Standard: <code>{sig['sl_standard']}</code>"
        f"\n  SL Wide:     <code>{sig['sl_wide']}</code>"
    ) if sig.get("sl_tight") != sig.get("sl_standard") else f"\n  SL:   <code>{sig['sl_standard']}</code>"

    fib_line = ""
    if sig.get("fib_levels"):
        fl = sig["fib_levels"]
        fib_line = f"\n📐 Fib: 50%={fl.get('50','?')}  61.8%={fl.get('61.8','?')}  78.6%={fl.get('78.6','?')}"
    fvg_line = ""
    if sig.get("fvg"):
        fvg_line = f"\n🔷 FVG: {sig['fvg'].get('bot','?')} – {sig['fvg'].get('top','?')}"

    return (
        f"🚨🚨 <b>MULTI-STRATEGY AGREEMENT</b> 🚨🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{color} <b>{count} STRATEGIES AGREE: {arrow} {'BUY' if is_buy else 'SELL'}</b>\n"
        f"💱 <b>{pair}</b>  ·  {sig['timeframe']}\n"
        f"\n"
        f"<b>Strategies in agreement:</b>\n{strat_list}\n"
        f"\n"
        f"  Entry:  <code>{sig['entry']}</code>\n"
        f"  TP1:    <code>{sig['tp1']}</code>{tp2_line}{sl_block}\n"
        f"  R:R     <b>1:{sig.get('risk_reward', '—')}</b>\n"
        f"{fib_line}{fvg_line}\n"
        f"\n"
        f"⚡ <i>Multiple independent methods confirm this setup.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>APEX FX · {sig.get('timestamp','')[:19]} UTC</i>"
    )

DIGITS = {"EURUSD":5,"GBPUSD":5,"AUDUSD":5,"USDCAD":5,"GBPJPY":3,"USDJPY":3,"XAUUSD":2}

def format_agreement_email(sig: dict) -> tuple[str, str]:
    """HTML email for agreement signal — more prominent styling."""
    pair   = _pair_display(sig["pair"])
    ag     = sig.get("agreement", {})
    count  = ag.get("count", 0)
    strats = ag.get("strategies", [])
    is_buy = sig["type"] in ("buy", "buy_limit")
    accent = "#00E87A" if is_buy else "#FF3D5A"
    arrow  = "↑ BUY" if is_buy else "↓ SELL"

    strat_rows = "".join(
        f'<tr><td style="padding:4px 12px;color:#00E87A;font-size:11px;">✅ {s}</td></tr>'
        for s in strats
    )
    tp2_row = f'<tr><td style="color:#567080;padding:5px 12px;font-size:11px;">TP2 (1.618)</td><td style="color:#00C8F0;padding:5px 12px;font-size:11px;">{sig["tp2"]}</td></tr>' if sig.get("tp2") else ""
    sl_rows = f"""
        <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">SL Tight</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get('sl_tight','—')}</td></tr>
        <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">SL Standard</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get('sl_standard','—')}</td></tr>
        <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">SL Wide</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get('sl_wide','—')}</td></tr>
    """ if sig.get("sl_tight") != sig.get("sl_standard") else f'<tr><td style="color:#567080;padding:5px 12px;font-size:11px;">Stop Loss</td><td style="color:#FF3D5A;padding:5px 12px;font-size:11px;">{sig.get("sl_standard","—")}</td></tr>'

    subject = f"🚨 AGREEMENT SIGNAL: {count} Strategies → {arrow} {pair} @ {sig['entry']} | {sig['timeframe']}"
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:32px 16px;background:#040C11;font-family:'Courier New',monospace;">
<table width="580" cellpadding="0" cellspacing="0" style="margin:0 auto;background:#0C1820;border:2px solid {accent};border-radius:5px;overflow:hidden;max-width:100%;">
  <tr><td style="background:{accent};height:5px;"></td></tr>
  <tr><td style="padding:22px 28px 16px;border-bottom:1px solid #162230;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><span style="font-size:20px;font-weight:bold;letter-spacing:3px;color:#00C8F0;">APEX</span><span style="font-size:20px;font-weight:bold;letter-spacing:3px;color:#D8EAF0;">FX</span></td>
      <td align="right"><span style="font-size:9px;letter-spacing:2px;color:{accent};">🚨 AGREEMENT SIGNAL</span></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:22px 28px;">
    <p style="font-size:13px;color:{accent};letter-spacing:2px;font-weight:bold;margin:0 0 6px;">⚡ {count} STRATEGIES IN AGREEMENT</p>
    <div style="display:inline-block;background:{accent};color:#050A0E;font-size:20px;font-weight:bold;letter-spacing:3px;padding:10px 22px;border-radius:3px;margin-bottom:16px;">{arrow}</div>
    <p style="font-size:34px;font-weight:bold;color:#FFFFFF;letter-spacing:2px;margin:0 0 6px;">{pair}  <span style="font-size:16px;color:#567080;">{sig['timeframe']}</span></p>
    <p style="font-size:11px;color:#567080;margin:0 0 20px;">{sig.get('timestamp','')[:19]} UTC</p>

    <p style="font-size:9px;color:#567080;letter-spacing:2px;margin:0 0 8px;">STRATEGIES THAT AGREE</p>
    <table cellpadding="0" cellspacing="0" style="border:1px solid #1E3040;border-radius:3px;overflow:hidden;margin-bottom:18px;width:100%;">{strat_rows}</table>

    <p style="font-size:9px;color:#567080;letter-spacing:2px;margin:0 0 8px;">TRADE LEVELS</p>
    <table cellpadding="0" cellspacing="0" style="border:1px solid #162230;border-radius:3px;overflow:hidden;margin-bottom:18px;width:100%;">
      <tr><td style="color:#567080;padding:5px 12px;font-size:11px;">Entry</td><td style="color:#D8EAF0;font-size:14px;font-weight:bold;padding:5px 12px;">{sig['entry']}</td></tr>
      <tr style="background:#0F1A22;"><td style="color:#567080;padding:5px 12px;font-size:11px;">TP1</td><td style="color:#00E87A;padding:5px 12px;font-size:11px;">{sig.get('tp1','—')}</td></tr>
      {tp2_row}{sl_rows}
      <tr style="background:#0F1A22;"><td style="color:#567080;padding:5px 12px;font-size:11px;">Risk/Reward</td><td style="color:#00C8F0;font-weight:bold;padding:5px 12px;font-size:11px;">1:{sig.get('risk_reward','—')}</td></tr>
    </table>

    <div style="padding:12px 14px;background:#0A160E;border:1px solid #1A3525;border-left:4px solid {accent};margin-bottom:20px;font-size:11px;color:#B8D0DC;line-height:1.7;">
      {sig.get('reason','')}
    </div>
    <p style="font-size:9px;color:#2A3A45;line-height:1.7;border-top:1px solid #162230;padding-top:14px;">⚠️ Automated signal. Apply your own risk management. Not financial advice.</p>
  </td></tr>
  <tr><td style="background:#0F1A22;padding:12px 28px;border-top:1px solid #162230;font-size:9px;color:#2A3A45;">APEX FX · dracoprimexr@gmail.com</td></tr>
  <tr><td style="background:{accent};height:3px;"></td></tr>
</table></body></html>"""
    return subject, html


async def dispatch_agreement(sig: dict):
    """
    Dispatch a multi-strategy agreement signal.
    Uses a different, more urgent format than regular signals.
    Always sends regardless of user filter configs — this is priority.
    """
    tg_text = format_agreement_tg(sig)
    email_subj, email_html = format_agreement_email(sig)

    # Always send to the master destinations
    if TG_CHAT_ID:
        await send_telegram(tg_text)
    if ALERT_EMAIL:
        send_email(ALERT_EMAIL, email_subj, email_html)

    # Also send to any user-configured destinations
    log.info(f"Agreement alert dispatched: {sig['pair']}/{sig['timeframe']} {sig['type'].upper()}")


async def dispatch_trade_event(event: str, trade: dict):
    text = format_trade_event_tg(event, trade)
    await send_telegram(text)
    if ALERT_EMAIL:
        subj = f"APEX FX Trade Update: {_pair_display(trade['pair'])} — {event.upper()}"
        html = f"""<html><body style="background:#040C11;padding:24px;font-family:'Courier New',monospace;">
<div style="max-width:480px;margin:0 auto;background:#0C1820;border:1px solid #162230;padding:24px;border-radius:5px;">
<p style="color:#00C8F0;font-size:18px;font-weight:bold;letter-spacing:3px;">APEXFX</p>
<p style="color:#D8EAF0;font-size:15px;white-space:pre-line;">{text.replace('<b>','').replace('</b>','').replace('<code>','').replace('</code>','')}</p>
</div></body></html>"""
        send_email(ALERT_EMAIL, subj, html)
