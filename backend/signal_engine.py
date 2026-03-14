"""
APEX FX - Signal Engine v4
All 14 strategies with exact rules refined through discussion.

Key rule across ALL strategies:
  - The level tells you WHERE to watch
  - The confirmation candle tells you WHEN to enter
  - No confirmation candle = no signal, regardless of how perfect the setup looks

Order types used correctly:
  - BUY LIMIT / SELL LIMIT  → reversal strategies (fib, S/R, S&D, FVG, Bollinger reversion)
  - BUY STOP  / SELL STOP   → breakout strategies (trendline, scalp, ORB, BB breakout)
  - BUY / SELL at market    → confirmed setups (RSI+MACD, EMA cross, Stochastic, Confluence, Carry)
"""

import math, uuid, logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("apexfx.engine")

# ════════════════════════════════════════════════════════════════════════════
# PAIR METADATA
# ════════════════════════════════════════════════════════════════════════════
DIGITS = {"EURUSD":5,"GBPUSD":5,"AUDUSD":5,"USDCAD":5,"GBPJPY":3,"USDJPY":3,"XAUUSD":2}
PIPS   = {"EURUSD":1e-4,"GBPUSD":1e-4,"AUDUSD":1e-4,"USDCAD":1e-4,"GBPJPY":0.01,"USDJPY":0.01,"XAUUSD":0.1}

def D(p): return DIGITS.get(p, 5)
def P(p): return PIPS.get(p, 1e-4)

# ════════════════════════════════════════════════════════════════════════════
# INDICATOR LIBRARY
# ════════════════════════════════════════════════════════════════════════════
def C(cd): return [c["close"] for c in cd]
def H(cd): return [c["high"]  for c in cd]
def L(cd): return [c["low"]   for c in cd]
def O(cd): return [c["open"]  for c in cd]

def ema_s(data, n):
    if len(data) < n: return []
    k = 2/(n+1); r = [sum(data[:n])/n]
    for p in data[n:]: r.append(p*k + r[-1]*(1-k))
    return r

def ema_v(data, n):
    s = ema_s(data, n); return s[-1] if s else None

def rsi(data, n=14):
    if len(data) < n+1: return None
    g = [max(data[i]-data[i-1], 0) for i in range(1, len(data))]
    lo= [max(data[i-1]-data[i], 0) for i in range(1, len(data))]
    ag = sum(g[-n:])/n; al = sum(lo[-n:])/n
    return round(100 - 100/(1+ag/al), 2) if al else 100.0

def macd(data, f=12, s=26, sig=9):
    if len(data) < s+sig+5: return None, None, None
    ef = ema_s(data, f); es = ema_s(data, s)
    ml = [ef[len(ef)-len(es)+i] - es[i] for i in range(len(es))]
    if len(ml) < sig: return None, None, None
    sl = ema_s(ml, sig)
    if not sl: return None, None, None
    return round(ml[-1],8), round(sl[-1],8), round(ml[-1]-sl[-1],8)

def bollinger(data, n=20, k=2.0):
    if len(data) < n: return None, None, None
    w = data[-n:]; m = sum(w)/n
    sd = math.sqrt(sum((x-m)**2 for x in w)/n)
    return round(m+k*sd,6), round(m,6), round(m-k*sd,6)

def stoch(hs, ls, cs, kp=14, dp=3):
    if len(cs) < kp+dp: return None, None
    kv = []
    for i in range(kp-1, len(cs)):
        hi = max(hs[i-kp+1:i+1]); lo = min(ls[i-kp+1:i+1])
        kv.append(100*(cs[i]-lo)/(hi-lo) if hi != lo else 50.0)
    if len(kv) < dp: return None, None
    return round(kv[-1], 2), round(sum(kv[-dp:])/dp, 2)

def atr(hs, ls, cs, n=14):
    if len(cs) < n+1: return None
    tr = [max(hs[i]-ls[i], abs(hs[i]-cs[i-1]), abs(ls[i]-cs[i-1])) for i in range(1, len(cs))]
    return round(sum(tr[-n:])/n, 6)

def pivot_highs(hs, lb=4):
    return [i for i in range(lb, len(hs)-lb) if hs[i] == max(hs[i-lb:i+lb+1])]

def pivot_lows(ls, lb=4):
    return [i for i in range(lb, len(ls)-lb) if ls[i] == min(ls[i-lb:i+lb+1])]

def swing_hi(hs, n=20): return max(hs[-n:]) if len(hs) >= n else max(hs)
def swing_lo(ls, n=20): return min(ls[-n:]) if len(ls) >= n else min(ls)

# ── FIB tools ────────────────────────────────────────────────────────────────
def fib_levels(hi, lo):
    """0% = hi (new high), 100% = lo (swing low). Retracement goes from hi downward."""
    r = hi - lo
    return {
        "0":    hi,
        "23.6": hi - 0.236*r,
        "38.2": hi - 0.382*r,
        "50":   hi - 0.5*r,
        "61.8": hi - 0.618*r,
        "78.6": hi - 0.786*r,
        "88.6": hi - 0.886*r,
        "100":  lo,
        "127.2": hi + 0.272*r,
        "161.8": hi + 0.618*r,
    }

# ── FVG tools ────────────────────────────────────────────────────────────────
def find_fvgs(candles, lookback=60):
    """3-candle imbalance. Bullish: c3.low > c1.high. Bearish: c3.high < c1.low."""
    out = []
    recent = candles[-lookback:]
    for i in range(1, len(recent)-1):
        c1, c3 = recent[i-1], recent[i+1]
        if c3["low"] > c1["high"]:
            out.append({"type":"bull","top":c3["low"],"bot":c1["high"],"mid":(c3["low"]+c1["high"])/2,"i":i})
        elif c3["high"] < c1["low"]:
            out.append({"type":"bear","top":c1["low"],"bot":c3["high"],"mid":(c1["low"]+c3["high"])/2,"i":i})
    return out

def fvg_overlaps(fvg, lo, hi): return fvg["bot"] <= hi and fvg["top"] >= lo
def price_in_fvg(price, fvg):
    buf = (fvg["top"]-fvg["bot"])*0.3
    return fvg["bot"]-buf <= price <= fvg["top"]+buf

# ── Candle confirmation ───────────────────────────────────────────────────────
def is_bullish_confirm(candles):
    """
    True if the last closed candle shows a bullish confirmation:
    - Bullish engulfing
    - Hammer / pin bar (long lower wick)
    - Wick rejection closing above mid of range
    - Simple bullish close (close > open)
    """
    if len(candles) < 2: return False
    c0 = candles[-1]; c1 = candles[-2]
    o0, h0, l0, c_0 = c0["open"], c0["high"], c0["low"], c0["close"]
    o1, h1, l1, c_1 = c1["open"], c1["high"], c1["low"], c1["close"]
    body0 = abs(c_0 - o0); rng0 = h0 - l0
    lw0 = min(c_0, o0) - l0   # lower wick
    uw0 = h0 - max(c_0, o0)   # upper wick

    # Bullish engulfing
    if c_1 < o1 and c_0 > o0 and body0 > abs(c_1-o1)*1.1 and o0 <= c_1 and c_0 >= o1:
        return True
    # Hammer / pin bar — long lower wick
    if rng0 > 0 and lw0 > rng0*0.55 and uw0 < rng0*0.35:
        return True
    # Simple bullish close
    if c_0 > o0:
        return True
    return False

def is_bearish_confirm(candles):
    """True if last closed candle shows bearish confirmation."""
    if len(candles) < 2: return False
    c0 = candles[-1]; c1 = candles[-2]
    o0, h0, l0, c_0 = c0["open"], c0["high"], c0["low"], c0["close"]
    o1, h1, l1, c_1 = c1["open"], c1["high"], c1["low"], c1["close"]
    body0 = abs(c_0 - o0); rng0 = h0 - l0
    lw0 = min(c_0, o0) - l0
    uw0 = h0 - max(c_0, o0)

    # Bearish engulfing
    if c_1 > o1 and c_0 < o0 and body0 > abs(c_1-o1)*1.1 and o0 >= c_1 and c_0 <= o1:
        return True
    # Shooting star / pin bar — long upper wick
    if rng0 > 0 and uw0 > rng0*0.55 and lw0 < rng0*0.35:
        return True
    # Simple bearish close
    if c_0 < o0:
        return True
    return False

# ── Signal builder ────────────────────────────────────────────────────────────
def sig(pair, tf, stype, entry, tp1, sl_std, strategy, reason, strength, inds,
        tp2=None, sl_tight=None, sl_wide=None, fib=None, fvg=None):
    d = D(pair)
    rr = round(abs(tp1-entry)/abs(entry-sl_std), 2) if abs(entry-sl_std) > 0 else 0
    s = {
        "id": str(uuid.uuid4())[:8],
        "pair": pair, "timeframe": tf, "type": stype,
        "entry": round(entry,d), "tp1": round(tp1,d),
        "tp2": round(tp2,d) if tp2 else None,
        "sl_tight":    round(sl_tight,d)  if sl_tight  else round(sl_std,d),
        "sl_standard": round(sl_std,d),
        "sl_wide":     round(sl_wide,d)   if sl_wide   else round(sl_std,d),
        "strategy": strategy, "reason": reason, "strength": strength,
        "risk_reward": rr, "indicators": inds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fib: s["fib_levels"] = {k: round(v,d) for k,v in fib.items()}
    if fvg: s["fvg"] = {k: round(v,d) if isinstance(v,float) else v for k,v in fvg.items()}
    return s

# ════════════════════════════════════════════════════════════════════════════
# ⭐ STRATEGY 1 — FIB GOLDEN ZONE + FVG
# Exact rules:
#   - BOS required: H1→L1→H2 (new high closes above H1)
#   - Pullback >= 25% of H2-L1 move before watching
#   - Golden zone 50-61.8%: confirmation candle required, candle must CLOSE above 61.8%
#   - If FVG above golden zone: ICT conditions met + confirmation candle, SL below FVG
#   - If FVG overlaps golden zone: watch for reaction candle at combined level
#   - If price closes BELOW 61.8%: no signal, wait for deep zone
#   - If price closes BELOW L1: full invalidation
#   - Deep zone 61.8-78.6%: last chance, SL below L1
#   - TP1 = H2, TP2 = 1.618 extension
#   - BEARISH: exact mirror
# ════════════════════════════════════════════════════════════════════════════
def strat_fib_fvg(pair, tf, candles):
    if len(candles) < 60: return None
    c = C(candles); h = H(candles); l = L(candles)
    price = c[-1]; pip = P(pair); d = D(pair)
    av = atr(h, l, c) or pip*20

    ph = pivot_highs(h, 4); pl = pivot_lows(l, 4)
    if len(ph) < 2 or len(pl) < 1: return None

    # ── BULLISH SETUP ──────────────────────────────────────────────────────
    new_hi_i = ph[-1]; new_hi = h[new_hi_i]
    prior_ph = [i for i in ph if i < new_hi_i]
    if prior_ph:
        btw_lo = [i for i in pl if i > prior_ph[-1] and i < new_hi_i]
        if btw_lo:
            sw_lo_i = min(btw_lo, key=lambda i: l[i]); sw_lo = l[sw_lo_i]
            move = new_hi - sw_lo

            # Minimum move size
            if move >= pip*25 and price < new_hi:
                pb_pct = (new_hi - price) / move

                # Must have pulled back at least 25%
                if pb_pct >= 0.25:
                    fibs = fib_levels(new_hi, sw_lo)
                    f50 = fibs["50"]; f618 = fibs["61.8"]
                    f786 = fibs["78.6"]; f100 = fibs["100"]
                    ext1618 = fibs["161.8"]

                    gz_lo = min(f50, f618); gz_hi = max(f50, f618)
                    dz_lo = min(f618, f786); dz_hi = max(f618, f786)

                    # Full invalidation: price closed below L1
                    if price < f100 - pip*2:
                        return None

                    # Price closed below golden zone (61.8%) — no signal
                    last_close = c[-1]
                    if last_close < f618 and last_close > dz_lo:
                        return None  # closed below gz, not yet in deep zone

                    fvgs = find_fvgs(candles, 60)
                    bull_fvgs = [f for f in fvgs if f["type"] == "bull"]

                    # FVGs above golden zone
                    fvg_above = next((f for f in reversed(bull_fvgs)
                                     if f["bot"] > gz_hi), None)
                    # FVGs overlapping golden zone
                    fvg_in_gz = next((f for f in reversed(bull_fvgs)
                                      if fvg_overlaps(f, gz_lo, gz_hi)), None)
                    # FVGs in deep zone
                    fvg_in_dz = next((f for f in reversed(bull_fvgs)
                                      if fvg_overlaps(f, dz_lo, dz_hi)), None)

                    at_gz = gz_lo <= price <= gz_hi
                    at_dz = dz_lo <= price <= dz_hi
                    above_gz = price > gz_hi and pb_pct < 0.48

                    inds = {
                        "New_High": round(new_hi, d), "Swing_Low": round(sw_lo, d),
                        "Fib_50%": round(f50, d), "Fib_61.8%": round(f618, d),
                        "Fib_78.6%": round(f786, d), "Pullback_%": round(pb_pct*100, 1),
                        "FVG_in_GZ": f"{fvg_in_gz['bot']:.{d}f}-{fvg_in_gz['top']:.{d}f}" if fvg_in_gz else "None",
                    }

                    # CASE A: Price in golden zone, FVG overlapping, confirmation candle
                    if at_gz and fvg_in_gz and is_bullish_confirm(candles):
                        sl_t = fvg_in_gz["bot"] - av*0.25
                        return sig(pair, tf, "buy_limit", f618, new_hi, f786-av*0.4,
                            "Fib Golden Zone + FVG",
                            f"Golden zone ({f50:.{d}f}-{f618:.{d}f}) + FVG overlap "
                            f"({fvg_in_gz['bot']:.{d}f}-{fvg_in_gz['top']:.{d}f}). "
                            f"Confirmation candle. SL below FVG. TP1={new_hi:.{d}f}.",
                            "high", inds, tp2=ext1618,
                            sl_tight=sl_t, sl_wide=sw_lo-av*0.5, fib=fibs, fvg=fvg_in_gz)

                    # CASE B: Price in golden zone, no FVG, confirmation candle
                    # Candle must close ABOVE 61.8% (not below it)
                    if at_gz and not fvg_in_gz and is_bullish_confirm(candles) and c[-1] >= f618:
                        return sig(pair, tf, "buy_limit", f618, new_hi, f786-av*0.4,
                            "Fib Golden Zone + FVG",
                            f"Fibonacci golden zone ({f50:.{d}f}-{f618:.{d}f}) — no FVG. "
                            f"Bullish confirmation candle closes above 61.8%. TP1={new_hi:.{d}f}.",
                            "high", inds, tp2=ext1618,
                            sl_tight=f618-av*0.3, sl_wide=sw_lo-av*0.5, fib=fibs)

                    # CASE C: FVG above golden zone — ICT conditions needed + confirmation
                    if fvg_above and price_in_fvg(price, fvg_above) and is_bullish_confirm(candles):
                        # Check BOS is valid (price is still below new_hi, above golden zone)
                        if price > gz_hi:
                            sl_t = fvg_above["bot"] - av*0.2
                            return sig(pair, tf, "buy_limit", fvg_above["bot"], new_hi, fvg_above["bot"]-av*0.5,
                                "Fib Golden Zone + FVG",
                                f"FVG ({fvg_above['bot']:.{d}f}-{fvg_above['top']:.{d}f}) above golden zone. "
                                f"ICT conditions met. Confirmation candle. SL just below FVG. TP1={new_hi:.{d}f}.",
                                "high", inds, tp2=ext1618,
                                sl_tight=sl_t, sl_wide=sw_lo-av*0.5, fib=fibs, fvg=fvg_above)

                    # CASE D: Approaching golden zone — BUY LIMIT at 61.8%
                    if above_gz and 0.25 <= pb_pct < 0.48:
                        fvg_note = ""
                        fvg_data = None
                        if fvg_in_gz:
                            fvg_note = f" FVG at {fvg_in_gz['bot']:.{d}f}-{fvg_in_gz['top']:.{d}f} in zone — watch reaction."
                            fvg_data = fvg_in_gz
                        return sig(pair, tf, "buy_limit", f618, new_hi, f786-av*0.4,
                            "Fib Golden Zone + FVG",
                            f"Pullback {pb_pct*100:.0f}% from new high. "
                            f"BUY LIMIT set at 61.8% ({f618:.{d}f}).{fvg_note} TP1={new_hi:.{d}f}.",
                            "medium", inds, tp2=ext1618,
                            sl_tight=f618-av*0.3, sl_wide=sw_lo-av*0.5, fib=fibs, fvg=fvg_data)

                    # CASE E: Deep zone 61.8-78.6% — last chance
                    if at_dz and is_bullish_confirm(candles) and c[-1] >= dz_lo:
                        fvg_data = fvg_in_dz
                        sl_t = fvg_in_dz["bot"]-av*0.2 if fvg_in_dz else dz_lo-av*0.3
                        return sig(pair, tf, "buy_limit", price, new_hi, sw_lo-av*0.5,
                            "Fib Golden Zone + FVG",
                            f"DEEP golden zone ({f618:.{d}f}-{f786:.{d}f}) — last support before "
                            f"invalidation. Bullish candle. SL below swing low ({sw_lo:.{d}f}).",
                            "medium", inds, tp2=ext1618,
                            sl_tight=sl_t, sl_wide=sw_lo-av*0.8, fib=fibs, fvg=fvg_data)

    # ── BEARISH SETUP (exact mirror) ────────────────────────────────────────
    new_lo_i = pl[-1] if pl else None
    if new_lo_i is not None:
        new_lo = l[new_lo_i]
        prior_pl = [i for i in pl if i < new_lo_i]
        if prior_pl:
            btw_hi = [i for i in ph if i > prior_pl[-1] and i < new_lo_i]
            if btw_hi:
                sw_hi_i = max(btw_hi, key=lambda i: h[i]); sw_hi = h[sw_hi_i]
                move = sw_hi - new_lo
                if move >= pip*25 and price > new_lo:
                    pb_pct = (price - new_lo) / move
                    if pb_pct >= 0.25:
                        rng = sw_hi - new_lo
                        f50b  = new_lo + 0.5*rng;  f618b = new_lo + 0.618*rng
                        f786b = new_lo + 0.786*rng; ext1618b = new_lo - 0.618*rng
                        gz_lo = min(f50b, f618b); gz_hi = max(f50b, f618b)
                        dz_lo = min(f618b, f786b); dz_hi = max(f618b, f786b)

                        # Full invalidation: price closed above sw_hi
                        if price > sw_hi + pip*2: return None
                        # Price closed above golden zone — no signal
                        if c[-1] > f618b and c[-1] < dz_hi: return None

                        fvgs = find_fvgs(candles, 60)
                        bear_fvgs = [f for f in fvgs if f["type"] == "bear"]
                        fvg_in_gz = next((f for f in reversed(bear_fvgs)
                                          if fvg_overlaps(f, gz_lo, gz_hi)), None)
                        fvg_above = next((f for f in reversed(bear_fvgs)
                                          if f["top"] < gz_lo), None)
                        at_gz = gz_lo <= price <= gz_hi
                        at_dz = dz_lo <= price <= dz_hi
                        below_gz = price < gz_lo and pb_pct < 0.48

                        inds = {
                            "New_Low": round(new_lo, d), "Swing_High": round(sw_hi, d),
                            "Fib_50%": round(f50b, d), "Fib_61.8%": round(f618b, d),
                            "Pullback_%": round(pb_pct*100, 1),
                        }

                        if at_gz and fvg_in_gz and is_bearish_confirm(candles):
                            return sig(pair, tf, "sell_limit", f618b, new_lo, f786b+av*0.4,
                                "Fib Golden Zone + FVG",
                                f"Bearish golden zone ({f50b:.{d}f}-{f618b:.{d}f}) + FVG. "
                                f"Bearish candle. SL above FVG. TP1={new_lo:.{d}f}.",
                                "high", inds, tp2=ext1618b,
                                sl_tight=fvg_in_gz["top"]+av*0.2, sl_wide=sw_hi+av*0.5, fvg=fvg_in_gz)

                        if at_gz and not fvg_in_gz and is_bearish_confirm(candles) and c[-1] <= f618b:
                            return sig(pair, tf, "sell_limit", f618b, new_lo, f786b+av*0.4,
                                "Fib Golden Zone + FVG",
                                f"Bearish golden zone ({f50b:.{d}f}-{f618b:.{d}f}). "
                                f"Bearish confirmation candle. TP1={new_lo:.{d}f}.",
                                "high", inds, tp2=ext1618b,
                                sl_tight=f618b+av*0.3, sl_wide=sw_hi+av*0.5)

                        if below_gz and 0.25 <= pb_pct < 0.48:
                            return sig(pair, tf, "sell_limit", f618b, new_lo, f786b+av*0.4,
                                "Fib Golden Zone + FVG",
                                f"Bearish pullback {pb_pct*100:.0f}%. SELL LIMIT at 61.8% ({f618b:.{d}f}). TP1={new_lo:.{d}f}.",
                                "medium", inds, tp2=ext1618b,
                                sl_tight=f618b+av*0.3, sl_wide=sw_hi+av*0.5)

                        if at_dz and is_bearish_confirm(candles) and c[-1] <= dz_hi:
                            return sig(pair, tf, "sell_limit", price, new_lo, sw_hi+av*0.5,
                                "Fib Golden Zone + FVG",
                                f"Bearish DEEP zone ({f618b:.{d}f}-{f786b:.{d}f}). Last resistance. SL above swing high.",
                                "medium", inds, tp2=ext1618b, sl_tight=dz_hi+av*0.2, sl_wide=sw_hi+av*0.8)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 2 — ICT FVG
# Rules:
#   - BOS required FIRST (price closes above prior swing high for bull / below for bear)
#   - FVG must have formed during the impulse that caused the BOS
#   - Price retraces into FVG
#   - Confirmation candle inside FVG
#   - SL below FVG bottom (bull) / above FVG top (bear)
#   - FVG already fully filled = no signal
# ════════════════════════════════════════════════════════════════════════════
def strat_ict_fvg(pair, tf, candles):
    if len(candles) < 30: return None
    c = C(candles); h = H(candles); l = L(candles)
    price = c[-1]; pip = P(pair); d = D(pair)
    av = atr(h, l, c) or pip*20
    fvgs = find_fvgs(candles, 50)
    rsh = swing_hi(h, 20); rsl = swing_lo(l, 20)

    # BOS: price just closed above recent swing high
    bos_bull = c[-1] > rsh and c[-2] <= rsh
    # BOS: price just closed below recent swing low
    bos_bear = c[-1] < rsl and c[-2] >= rsl

    if bos_bull:
        # Find bullish FVGs from the last 15 candles (impulse that caused BOS)
        recent_bull_fvgs = [f for f in fvgs if f["type"] == "bull" and f["i"] > len(candles[-50:])-15]
        for fvg in reversed(recent_bull_fvgs):
            if price_in_fvg(price, fvg) and is_bullish_confirm(candles):
                inds = {"FVG_Top":round(fvg["top"],d),"FVG_Bot":round(fvg["bot"],d),"BOS":round(rsh,d)}
                return sig(pair, tf, "buy_limit", price, rsh+av*2, fvg["bot"]-av*0.5,
                    "ICT FVG",
                    f"BOS above {rsh:.{d}f}. Price retracing into bullish FVG "
                    f"({fvg['bot']:.{d}f}-{fvg['top']:.{d}f}). Confirmation candle. TP=prior high.",
                    "high", inds, sl_tight=fvg["bot"]-av*0.2, sl_wide=fvg["bot"]-av*1.0, fvg=fvg)

    if bos_bear:
        recent_bear_fvgs = [f for f in fvgs if f["type"] == "bear" and f["i"] > len(candles[-50:])-15]
        for fvg in reversed(recent_bear_fvgs):
            if price_in_fvg(price, fvg) and is_bearish_confirm(candles):
                inds = {"FVG_Top":round(fvg["top"],d),"FVG_Bot":round(fvg["bot"],d),"BOS":round(rsl,d)}
                return sig(pair, tf, "sell_limit", price, rsl-av*2, fvg["top"]+av*0.5,
                    "ICT FVG",
                    f"Bearish BOS below {rsl:.{d}f}. Price retracing into bearish FVG "
                    f"({fvg['bot']:.{d}f}-{fvg['top']:.{d}f}). Confirmation candle.",
                    "high", inds, sl_tight=fvg["top"]+av*0.2, sl_wide=fvg["top"]+av*1.0, fvg=fvg)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 3 — SUPPLY & DEMAND ZONES
# Rules:
#   - Identify base candle before impulse move (small tight candle)
#   - Strong impulsive move away (body > 1.5x ATR, body/range > 60%)
#   - Price returns to base zone
#   - First or second test only (not 3+)
#   - Confirmation candle required
#   - Next opposing zone check: must have 1:2 R:R minimum
#   - Price closes THROUGH zone = zone dead, no signal
# ════════════════════════════════════════════════════════════════════════════
def strat_supply_demand(pair, tf, candles):
    if len(candles) < 50: return None
    c = C(candles); h = H(candles); l = L(candles); o = O(candles)
    price = c[-1]; pip = P(pair); d = D(pair)
    av = atr(h, l, c) or pip*20

    demand, supply = [], []
    # Track how many times each zone has been tested
    for i in range(2, len(candles)-3):
        body = abs(c[i]-o[i]); rng = h[i]-l[i]
        is_imp = body > av*1.5 and (rng == 0 or body/rng > 0.6)
        if is_imp and c[i] > o[i]:   # bullish impulse → demand zone
            bi = i-1; zt = max(c[bi],o[bi]); zb = min(c[bi],o[bi])
            if zt-zb >= pip*3:
                # Count how many times price has revisited this zone
                tests = sum(1 for j in range(i+1, len(candles)) if zb-av*0.3 <= c[j] <= zt+av*0.3)
                if tests <= 2:  # only first/second test
                    demand.append({"top":zt,"bot":zb,"target":max(h[i:i+3]),"tests":tests})
        if is_imp and c[i] < o[i]:   # bearish impulse → supply zone
            bi = i-1; zt = max(c[bi],o[bi]); zb = min(c[bi],o[bi])
            if zt-zb >= pip*3:
                tests = sum(1 for j in range(i+1, len(candles)) if zb-av*0.3 <= c[j] <= zt+av*0.3)
                if tests <= 2:
                    supply.append({"top":zt,"bot":zb,"target":min(l[i:i+3]),"tests":tests})

    for z in demand[-5:]:
        if z["bot"] <= price <= z["top"] + av*0.3:
            if is_bullish_confirm(candles):
                tp = z["target"] + av
                # R:R check — TP must be at least 2x the SL distance
                sl = z["bot"] - av*0.8
                if tp-price >= (price-sl)*1.8:
                    inds = {"Zone":f"{z['bot']:.{d}f}-{z['top']:.{d}f}","Tests":z["tests"],"Type":"Demand"}
                    return sig(pair, tf, "buy_limit", price, tp, sl,
                        "Supply & Demand",
                        f"Demand zone ({z['bot']:.{d}f}-{z['top']:.{d}f}), test #{z['tests']+1}. "
                        f"Institutional buy origin. Confirmation candle confirmed.",
                        "high" if z["tests"] == 0 else "medium", inds,
                        sl_tight=z["bot"]-av*0.3, sl_wide=z["bot"]-av*1.2)

    for z in supply[-5:]:
        if z["bot"]-av*0.3 <= price <= z["top"]:
            if is_bearish_confirm(candles):
                tp = z["target"] - av
                sl = z["top"] + av*0.8
                if price-tp >= (sl-price)*1.8:
                    inds = {"Zone":f"{z['bot']:.{d}f}-{z['top']:.{d}f}","Tests":z["tests"],"Type":"Supply"}
                    return sig(pair, tf, "sell_limit", price, tp, sl,
                        "Supply & Demand",
                        f"Supply zone ({z['bot']:.{d}f}-{z['top']:.{d}f}), test #{z['tests']+1}. "
                        f"Institutional sell origin. Confirmation candle.",
                        "high" if z["tests"] == 0 else "medium", inds,
                        sl_tight=z["top"]+av*0.3, sl_wide=z["top"]+av*1.2)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 4 — CANDLESTICK PATTERNS
# 16 patterns. Rules:
#   - Pattern must form AT a key level (S/R, EMA, round number, fib zone)
#   - Candle must be FULLY CLOSED — no forming candles
#   - Pattern size must be significant relative to recent ATR
#   - Higher timeframe = stronger signal
#   - Goes with higher timeframe trend where possible
# ════════════════════════════════════════════════════════════════════════════
def strat_candle_patterns(pair, tf, candles):
    if len(candles) < 5: return None
    c = C(candles); h = H(candles); l = L(candles); o = O(candles)
    price = c[-1]; pip = P(pair); d = D(pair)
    av = atr(h, l, c) or pip*20
    r = rsi(c); e50 = ema_v(c, 50)
    trend_up = price > e50 if e50 else None

    c0=candles[-1]; c1=candles[-2]; c2=candles[-3] if len(candles)>2 else c1
    o0,h0,l0,c_0 = c0["open"],c0["high"],c0["low"],c0["close"]
    o1,h1,l1,c_1 = c1["open"],c1["high"],c1["low"],c1["close"]
    o2,h2,l2,c_2 = c2["open"],c2["high"],c2["low"],c2["close"]
    body0=abs(c_0-o0); rng0=h0-l0
    body1=abs(c_1-o1); rng1=h1-l1
    lw0=min(c_0,o0)-l0; uw0=h0-max(c_0,o0)
    bull0=c_0>o0; bear0=c_0<o0
    bull1=c_1>o1; bear1=c_1<o1

    # Pattern must be at a key level — check EMA proximity or S/R
    at_key = False
    if e50 and abs(price-e50) < av*0.8: at_key = True
    ph = pivot_highs(h); pl = pivot_lows(l)
    for i in ph[-3:]:
        if abs(price-h[i]) < av*0.7: at_key = True
    for i in pl[-3:]:
        if abs(price-l[i]) < av*0.7: at_key = True
    # Round numbers
    for mult in [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]:
        nearest = round(price/mult)*mult
        if abs(price-nearest) < av*0.5: at_key = True

    def make(stype, strength, name, reason):
        is_buy = stype in ("buy","buy_limit")
        tp = price+av*2 if is_buy else price-av*2
        sl = price-av*1.2 if is_buy else price+av*1.2
        inds = {"Pattern":name,"RSI":r,"EMA_50":round(e50,d) if e50 else None,"ATR":round(av,d),"At_Key_Level":at_key}
        return sig(pair, tf, stype, price, tp, sl, "Candle Patterns", reason, strength, inds)

    # ── REVERSAL PATTERNS ────────────────────────────────────────────────────
    # Bullish engulfing — body must be larger than prior body
    if bear1 and bull0 and body0 > body1*1.1 and o0 <= c_1 and c_0 >= o1 and body0 > av*0.4:
        return make("buy","high","Bullish Engulfing",
            f"Bullish engulfing — prior bearish body fully consumed. RSI={r}. {'At key level.' if at_key else 'Standalone.'}")

    # Bearish engulfing
    if bull1 and bear0 and body0 > body1*1.1 and o0 >= c_1 and c_0 <= o1 and body0 > av*0.4:
        return make("sell","high","Bearish Engulfing",
            f"Bearish engulfing — prior bullish body fully consumed. RSI={r}.")

    # Hammer — long lower wick at least 2x body, small upper wick
    if lw0 > body0*2 and uw0 < body0*0.5 and rng0 > pip*5 and (r is None or r < 55):
        return make("buy","high","Hammer",
            f"Hammer — lower wick ({lw0:.{d}f}) = buyers rejected sellers. RSI={r}.")

    # Shooting star
    if uw0 > body0*2 and lw0 < body0*0.5 and rng0 > pip*5 and (r is None or r > 45):
        return make("sell","high","Shooting Star",
            f"Shooting star — upper wick ({uw0:.{d}f}) = sellers rejected buyers. RSI={r}.")

    # Bullish pin bar — wick > 60% of range
    if lw0 > rng0*0.58 and body0 < rng0*0.35 and rng0 > av*0.5 and (r is None or r < 50):
        return make("buy","high","Bullish Pin Bar",
            f"Bullish pin bar — strong rejection of lows. RSI={r}.")

    # Bearish pin bar
    if uw0 > rng0*0.58 and body0 < rng0*0.35 and rng0 > av*0.5 and (r is None or r > 50):
        return make("sell","high","Bearish Pin Bar",
            f"Bearish pin bar — strong rejection of highs. RSI={r}.")

    # Morning star (3 candles)
    if len(candles) >= 3:
        bear2 = o2 > c_2; small1 = body1 < av*0.4
        bull_close = c_0 > o0 and c_0 > o2 + (c_2-o2)*0.5
        if bear2 and small1 and bull_close and (r is None or r < 55):
            return make("buy","high","Morning Star",
                f"Morning star — 3-candle bullish reversal. RSI={r}.")

    # Evening star
    if len(candles) >= 3:
        bull2 = c_2 > o2; small1 = body1 < av*0.4
        bear_close = c_0 < o0 and c_0 < c_2 - (c_2-o2)*0.5
        if bull2 and small1 and bear_close and (r is None or r > 45):
            return make("sell","high","Evening Star",
                f"Evening star — 3-candle bearish reversal. RSI={r}.")

    # Bullish harami
    if bear1 and bull0 and body0 < body1*0.6 and o0 > c_1 and c_0 < o1 and (r is None or r < 55):
        return make("buy","medium","Bullish Harami",
            f"Bullish harami — small candle inside prior bearish. Momentum slowing. RSI={r}.")

    # Bearish harami
    if bull1 and bear0 and body0 < body1*0.6 and o0 < c_1 and c_0 > o1 and (r is None or r > 45):
        return make("sell","medium","Bearish Harami",
            f"Bearish harami — small candle inside prior bullish. Momentum slowing. RSI={r}.")

    # Doji at extreme RSI
    if body0 < rng0*0.08 and rng0 > av*0.5 and r:
        if r < 30:
            return make("buy","medium","Doji (Oversold)",
                f"Doji at oversold RSI={r} — indecision after downmove. Reversal likely.")
        if r > 70:
            return make("sell","medium","Doji (Overbought)",
                f"Doji at overbought RSI={r} — indecision after upmove. Reversal likely.")

    # ── CONTINUATION PATTERNS ────────────────────────────────────────────────
    # Three white soldiers
    if len(candles) >= 3:
        if all(c[-i] > o[-i] and abs(c[-i]-o[-i]) > av*0.7 for i in range(1,4)) and c[-1]>c[-2]>c[-3]:
            return make("buy","medium","Three White Soldiers",
                "Three consecutive strong bullish candles — sustained buying pressure.")

    # Three black crows
    if len(candles) >= 3:
        if all(c[-i] < o[-i] and abs(c[-i]-o[-i]) > av*0.7 for i in range(1,4)) and c[-1]<c[-2]<c[-3]:
            return make("sell","medium","Three Black Crows",
                "Three consecutive strong bearish candles — sustained selling pressure.")

    # Bullish marubozu (trend confirmation)
    if bull0 and body0 > rng0*0.88 and rng0 > av*1.1 and trend_up:
        return make("buy","medium","Bullish Marubozu",
            "Full-body bullish candle, no wicks — pure buying momentum. Trend continues.")

    # Bearish marubozu
    if bear0 and body0 > rng0*0.88 and rng0 > av*1.1 and trend_up is False:
        return make("sell","medium","Bearish Marubozu",
            "Full-body bearish candle, no wicks — pure selling momentum. Trend continues.")

    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 5 — RSI + MACD
# Rules:
#   - BUY: RSI < 32 AND MACD histogram just crossed above zero (both simultaneously)
#   - SELL: RSI > 68 AND MACD histogram just crossed below zero
#   - BUY LIMIT: RSI 33-43 approaching oversold, MACD turning
#   - SELL LIMIT: RSI 58-67 approaching overbought
#   - Strong trend: RSI can stay extreme — need MACD crossover confirmation
#   - Works best in RANGING markets
# ════════════════════════════════════════════════════════════════════════════
def strat_rsi_macd(pair, tf, candles):
    c = C(candles)
    if len(c) < 40: return None
    r = rsi(c); mv, ms, mh = macd(c); pmh = macd(c[:-1])[2]
    if r is None or mh is None or pmh is None: return None
    pip = P(pair); d = D(pair); price = c[-1]
    av = atr(H(candles), L(candles), c) or pip*20
    inds = {"RSI":r, "MACD_Hist":round(mh,6), "MACD_Val":round(mv,6)}

    # BUY: RSI oversold + MACD histogram just crossed above zero
    if r < 32 and mh > 0 and pmh <= 0:
        return sig(pair, tf, "buy", price, price+av*2.2, price-av*1.2,
            "RSI + MACD", f"RSI={r} oversold + MACD histogram bullish crossover. Both conditions met simultaneously.",
            "high", inds, sl_tight=price-av*0.8, sl_wide=price-av*1.8)

    # SELL: RSI overbought + MACD histogram just crossed below zero
    if r > 68 and mh < 0 and pmh >= 0:
        return sig(pair, tf, "sell", price, price-av*2.2, price+av*1.2,
            "RSI + MACD", f"RSI={r} overbought + MACD histogram bearish crossover.",
            "high", inds, sl_tight=price+av*0.8, sl_wide=price+av*1.8)

    # BUY LIMIT: RSI approaching oversold, MACD turning positive
    if 33 <= r <= 43 and mh > 0 and mv < 0:
        return sig(pair, tf, "buy_limit", price-av*0.5, price+av*2.5, price-av*1.5,
            "RSI + MACD", f"RSI={r} nearing oversold — BUY LIMIT at pullback. MACD histogram positive.",
            "medium", inds)

    # SELL LIMIT: RSI approaching overbought
    if 58 <= r <= 67 and mh < 0 and mv > 0:
        return sig(pair, tf, "sell_limit", price+av*0.5, price-av*2.5, price+av*1.5,
            "RSI + MACD", f"RSI={r} nearing overbought — SELL LIMIT at retest.",
            "medium", inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 6 — EMA 50/200 CROSS
# Rules:
#   - Golden Cross (EMA50 crosses above EMA200): BUY at market
#   - Death Cross (EMA50 crosses below EMA200): SELL at market
#   - Pullback to EMA50 in bullish trend: BUY LIMIT (better entry)
#   - Pullback to EMA50 in bearish trend: SELL LIMIT
#   - False cross (crosses back immediately in ranging market): avoid
#   - H1/H4/D1 only for cross signals — M15 crosses less reliable
# ════════════════════════════════════════════════════════════════════════════
def strat_ema_cross(pair, tf, candles):
    c = C(candles)
    if len(c) < 210: return None
    e50 = ema_s(c, 50); e200 = ema_s(c, 200)
    if len(e50) < 3 or len(e200) < 3: return None
    pip = P(pair); d = D(pair); price = c[-1]
    av = atr(H(candles), L(candles), c) or pip*20
    e50n,e50p = e50[-1],e50[-2]; e200n,e200p = e200[-1],e200[-2]
    inds = {"EMA_50":round(e50n,d),"EMA_200":round(e200n,d),"Separation":round(e50n-e200n,d)}

    # Check it's not a false cross (EMAs not too close together = not ranging)
    separation = abs(e50n - e200n)
    if separation < pip*2: return None  # too close, likely ranging

    # Golden Cross: EMA50 crossed above EMA200 this candle
    if e50p < e200p and e50n > e200n:
        return sig(pair, tf, "buy", price, price+av*3, price-av*1.5,
            "EMA 50/200 Cross", "Golden Cross — EMA 50 crossed above EMA 200. Bulls in control.",
            "high", inds, sl_tight=price-av*1.0, sl_wide=price-av*2.2)

    # Death Cross
    if e50p > e200p and e50n < e200n:
        return sig(pair, tf, "sell", price, price-av*3, price+av*1.5,
            "EMA 50/200 Cross", "Death Cross — EMA 50 crossed below EMA 200. Bears in control.",
            "high", inds, sl_tight=price+av*1.0, sl_wide=price+av*2.2)

    # Pullback to EMA50 in uptrend — BUY LIMIT (better entry than the cross)
    if e50n > e200n and 0 < price-e50n < av*0.6:
        if is_bullish_confirm(candles):
            return sig(pair, tf, "buy_limit", e50n+pip*3, e50n+av*2.5, e50n-av,
                "EMA 50/200 Cross",
                f"Bullish trend confirmed (EMA50 > EMA200). BUY LIMIT on pullback to EMA50 ({e50n:.{d}f}). Better R:R than cross entry.",
                "medium", inds, sl_tight=e50n-av*0.4, sl_wide=e50n-av*1.5)

    # Pullback to EMA50 in downtrend — SELL LIMIT
    if e50n < e200n and 0 < e50n-price < av*0.6:
        if is_bearish_confirm(candles):
            return sig(pair, tf, "sell_limit", e50n-pip*3, e50n-av*2.5, e50n+av,
                "EMA 50/200 Cross",
                f"Bearish trend confirmed (EMA50 < EMA200). SELL LIMIT on retest of EMA50 ({e50n:.{d}f}).",
                "medium", inds, sl_tight=e50n+av*0.4, sl_wide=e50n+av*1.5)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 7 — BOLLINGER BANDS
# Two sub-strategies:
# A) Mean Reversion (ranging market): BUY LIMIT at lower band, SELL LIMIT at upper band
# B) Breakout (squeeze): BUY STOP above upper band, SELL STOP below lower band
# Rules:
#   - Mean reversion: bands must be relatively flat (not widening fast)
#   - Breakout: bands must be genuinely narrow (squeeze)
#   - Breakout candle must close outside band (not just wick)
#   - False breakout: price closes back inside band = exit
#   - TP for reversion = middle band; TP for breakout = band height projected
# ════════════════════════════════════════════════════════════════════════════
def strat_bollinger(pair, tf, candles):
    c = C(candles)
    if len(c) < 25: return None
    up, mb, lo = bollinger(c)
    if up is None: return None
    pip = P(pair); d = D(pair); price = c[-1]; prev = c[-2]
    av = atr(H(candles), L(candles), c) or pip*20
    bw = (up - lo) / mb  # bandwidth — measure of volatility

    # Previous bandwidth for squeeze detection
    up_p, mb_p, lo_p = bollinger(c[:-1]) if len(c) > 20 else (None, None, None)
    bw_prev = (up_p-lo_p)/mb_p if up_p else bw
    is_squeeze = bw < bw_prev * 0.85 and bw < 0.015  # bands narrowing

    inds = {"BB_Up":round(up,d),"BB_Mid":round(mb,d),"BB_Lo":round(lo,d),
            "BW%":round(bw*100,2),"Squeeze":is_squeeze}

    # SUB-STRATEGY B: Breakout (BUY STOP / SELL STOP)
    if is_squeeze:
        band_height = up - lo
        if prev < up <= price:  # close above upper band
            tp = price + band_height
            return sig(pair, tf, "buy_stop", price, tp, up-av*0.3,
                "Bollinger Breakout",
                f"BB squeeze breakout above upper band ({up:.{d}f}). Band height={band_height:.{d}f}. BUY STOP.",
                "high", inds)
        if prev > lo >= price:  # close below lower band
            tp = price - band_height
            return sig(pair, tf, "sell_stop", price, tp, lo+av*0.3,
                "Bollinger Breakout",
                f"BB squeeze breakdown below lower band ({lo:.{d}f}). SELL STOP.",
                "high", inds)

    # SUB-STRATEGY A: Mean reversion (bands not expanding rapidly)
    if bw > 0.004:  # bands must have some width to trade reversion
        # BUY LIMIT at lower band — price touching lower band
        if abs(price - lo) < av*0.4 and price > lo and is_bullish_confirm(candles):
            return sig(pair, tf, "buy_limit", lo+pip*2, mb, lo-av*0.8,
                "Bollinger Breakout",
                f"Mean reversion: price at lower BB ({lo:.{d}f}). Confirmation candle. TP=middle band ({mb:.{d}f}).",
                "medium", inds, sl_tight=lo-av*0.3)

        # SELL LIMIT at upper band
        if abs(price - up) < av*0.4 and price < up and is_bearish_confirm(candles):
            return sig(pair, tf, "sell_limit", up-pip*2, mb, up+av*0.8,
                "Bollinger Breakout",
                f"Mean reversion: price at upper BB ({up:.{d}f}). Confirmation candle. TP=middle band ({mb:.{d}f}).",
                "medium", inds, sl_tight=up+av*0.3)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 8 — SUPPORT & RESISTANCE BOUNCE
# Rules:
#   - Level must have been tested at least twice (minimum 2 touches)
#   - Not more than 4-5 times (exhausted)
#   - Confirmation candle required
#   - Role reversal: old resistance → new support and vice versa
#   - R:R check: enough space to next opposing level (min 1:2)
#   - Price closing THROUGH level = level broken, no signal
# ════════════════════════════════════════════════════════════════════════════
def strat_sr_bounce(pair, tf, candles):
    c = C(candles); h = H(candles); l = L(candles)
    if len(c) < 55: return None
    ph = pivot_highs(h, 4); pl = pivot_lows(l, 4)
    pip = P(pair); d = D(pair); price = c[-1]
    av = atr(h, l, c) or pip*20; r = rsi(c)
    zone = av*0.7

    inds = {"RSI":r,"ATR":round(av,d)}

    # Count how many times price has touched each level
    def count_tests(level, candles_list, tolerance):
        return sum(1 for candle in candles_list if abs(candle["close"]-level) < tolerance or abs(candle["low"]-level) < tolerance or abs(candle["high"]-level) < tolerance)

    # Support bounce — buy
    for idx in pl[-5:]:
        sup = l[idx]
        if abs(price-sup) < zone and price > sup:
            tests = count_tests(sup, candles[-50:], av*0.5)
            if 2 <= tests <= 5:  # tested enough but not exhausted
                if is_bullish_confirm(candles) and (r is None or r < 55):
                    # Find next resistance for TP
                    next_res = min((h[i] for i in ph if h[i] > price+av), default=price+av*3)
                    sl = sup - av*0.8
                    if next_res - price >= (price - sl) * 1.8:  # R:R check
                        inds["Level"] = round(sup,d); inds["Tests"] = tests
                        return sig(pair, tf, "buy_limit", price, next_res, sl,
                            "S/R Bounce",
                            f"Support bounce at {sup:.{d}f} (test #{tests}). Confirmation candle. RSI={r}.",
                            "high" if (r and r < 35) else "medium", inds,
                            sl_tight=sup-av*0.3, sl_wide=sup-av*1.3)

    # Resistance rejection — sell
    for idx in ph[-5:]:
        res = h[idx]
        if abs(price-res) < zone and price < res:
            tests = count_tests(res, candles[-50:], av*0.5)
            if 2 <= tests <= 5:
                if is_bearish_confirm(candles) and (r is None or r > 45):
                    next_sup = max((l[i] for i in pl if l[i] < price-av), default=price-av*3)
                    sl = res + av*0.8
                    if price - next_sup >= (sl - price) * 1.8:
                        inds["Level"] = round(res,d); inds["Tests"] = tests
                        return sig(pair, tf, "sell_limit", price, next_sup, sl,
                            "S/R Bounce",
                            f"Resistance rejection at {res:.{d}f} (test #{tests}). Confirmation candle. RSI={r}.",
                            "high" if (r and r > 65) else "medium", inds,
                            sl_tight=res+av*0.3, sl_wide=res+av*1.3)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 9 — STOCHASTIC OSCILLATOR
# Rules:
#   - %K must cross %D in the extreme zone (below 20 for buy, above 80 for sell)
#   - Cross between 20-80 = ignore completely
#   - Cross must be decisive — lines clearly moving apart
#   - Strong trend: Stochastic can stay extreme — check EMA trend filter
#   - Best at key levels (support, demand zone, fib)
# ════════════════════════════════════════════════════════════════════════════
def strat_stoch(pair, tf, candles):
    c = C(candles); h = H(candles); l = L(candles)
    if len(c) < 25: return None
    k, dv = stoch(h, l, c); kp, dp = stoch(h[:-1], l[:-1], c[:-1])
    if k is None or kp is None: return None
    e50 = ema_v(c, 50); e200 = ema_v(c, 200)
    pip = P(pair); d = D(pair); price = c[-1]
    av = atr(h, l, c) or pip*20
    trend_up = price > e50 if e50 else True

    # Cross must be decisive — lines spreading apart
    cross_strength = abs(k - dv)
    if cross_strength < 2: return None  # too weak a cross

    inds = {"Stoch_K":k,"Stoch_D":dv,"EMA_50":round(e50,d) if e50 else None}

    # Bullish cross in oversold zone (<20) — with trend filter
    if kp < dp and k > dv and k < 20 and trend_up:
        return sig(pair, tf, "buy", price, price+av*2, price-av*1.2,
            "Stochastic",
            f"%K({k}) crossed %D({dv}) in oversold zone. Trend bullish. Decisive cross.",
            "high", inds, sl_tight=price-av*0.8, sl_wide=price-av*1.8)

    # Bearish cross in overbought zone (>80) — with trend filter
    if kp > dp and k < dv and k > 80 and not trend_up:
        return sig(pair, tf, "sell", price, price-av*2, price+av*1.2,
            "Stochastic",
            f"%K({k}) crossed %D({dv}) in overbought zone. Trend bearish. Decisive cross.",
            "high", inds, sl_tight=price+av*0.8, sl_wide=price+av*1.8)

    # Also fire if cross is in extreme zone even without perfect trend alignment (medium strength)
    if kp < dp and k > dv and k < 25 and e50 and e200:
        if e50 > e200:  # at least medium term bullish
            return sig(pair, tf, "buy", price, price+av*1.8, price-av*1.2,
                "Stochastic",
                f"%K({k}) crossed %D({dv}) oversold. EMA trend supports.",
                "medium", inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 10 — TRENDLINE BREAKOUT
# Rules:
#   - Trendline must have at least 3 touches (minimum 2 to draw, 3 to confirm)
#   - BUY STOP for bullish break (descending trendline broken)
#   - SELL STOP for bearish break (ascending trendline broken)
#   - Breakout candle must be decisive (not just a wick)
#   - Retest of broken trendline = best entry
#   - Price closes back through trendline = false breakout
# ════════════════════════════════════════════════════════════════════════════
def strat_trendline(pair, tf, candles):
    if len(candles) < 40: return None
    c = C(candles); h = H(candles); l = L(candles)
    pip = P(pair); d = D(pair); price = c[-1]; prev = c[-2]
    av = atr(h, l, c) or pip*20; r = rsi(c)
    ph = pivot_highs(h, 4); pl = pivot_lows(l, 4)
    if len(ph) < 2 or len(pl) < 2: return None

    # Descending trendline (lower highs) → bullish breakout
    ph1, ph2 = ph[-2], ph[-1]
    if ph2 > ph1:
        slope = (h[ph2]-h[ph1])/(ph2-ph1)
        tl_now = h[ph2] + slope*(len(c)-1-ph2)
        # Count touches (times price came within av*0.5 of the trendline)
        touches = sum(1 for i in range(ph1, ph2) if abs(h[i]-( h[ph1]+slope*(i-ph1))) < av*0.6)
        if touches >= 1:  # at least 3 total (ph1, ph2, + touches)
            # Breakout: price closes above trendline this candle
            if prev < tl_now <= price and r and r < 68:
                inds = {"Trendline":round(tl_now,d),"RSI":r,"Touches":touches+2}
                return sig(pair, tf, "buy_stop", price, price+av*2.5, tl_now-av,
                    "Trendline Breakout",
                    f"Price closed above descending trendline ({tl_now:.{d}f}). RSI={r}. "
                    f"{touches+2} touches confirmed. BUY STOP.",
                    "high", inds, sl_tight=tl_now-av*0.4, sl_wide=tl_now-av*1.5)

    # Ascending trendline (higher lows) → bearish breakout
    pl1, pl2 = pl[-2], pl[-1]
    if pl2 > pl1:
        slope = (l[pl2]-l[pl1])/(pl2-pl1)
        tl_now = l[pl2] + slope*(len(c)-1-pl2)
        touches = sum(1 for i in range(pl1, pl2) if abs(l[i]-(l[pl1]+slope*(i-pl1))) < av*0.6)
        if touches >= 1:
            if prev > tl_now >= price and r and r > 32:
                inds = {"Trendline":round(tl_now,d),"RSI":r,"Touches":touches+2}
                return sig(pair, tf, "sell_stop", price, price-av*2.5, tl_now+av,
                    "Trendline Breakout",
                    f"Price closed below ascending trendline ({tl_now:.{d}f}). RSI={r}. "
                    f"{touches+2} touches confirmed. SELL STOP.",
                    "high", inds, sl_tight=tl_now+av*0.4, sl_wide=tl_now+av*1.5)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 11 — MULTI-CONFLUENCE
# Rules:
#   - Score each of 5 indicators independently
#   - Signal only fires at score 4 or 5
#   - EMA score is the most important — 4/5 with EMA > 4/5 without EMA
#   - Score must be maintained at time of entry
# ════════════════════════════════════════════════════════════════════════════
def strat_confluence(pair, tf, candles):
    c = C(candles); h = H(candles); l = L(candles)
    if len(c) < 60: return None
    r = rsi(c) or 50; _, _, mh = macd(c); e50 = ema_v(c,50); e200 = ema_v(c,200)
    k, _ = stoch(h, l, c); _, mb, _ = bollinger(c)
    av = atr(h, l, c) or P(pair)*20
    if None in (mh, e50, e200, k, mb): return None
    pip = P(pair); d = D(pair); price = c[-1]

    bull = sum([r<40, mh>0, e50>e200, k<40, price<mb])
    bear = sum([r>60, mh<0, e50<e200, k>60, price>mb])

    # EMA must be part of the agreement for full strength
    ema_bull = e50 > e200; ema_bear = e50 < e200

    inds = {
        "RSI":r,"MACD_Hist":round(mh,7),
        "EMA_50":round(e50,d),"EMA_200":round(e200,d),
        "Stoch_K":k,"Bull_Score":bull,"Bear_Score":bear,
        "EMA_Agrees": ema_bull if bull >= 4 else ema_bear
    }

    if bull >= 4:
        strength = "high" if (bull == 5 or (bull == 4 and ema_bull)) else "medium"
        return sig(pair, tf, "buy", price, price+av*3, price-av*1.5,
            "Multi-Confluence",
            f"HIGH CONVICTION BUY — {bull}/5 indicators bullish. "
            f"RSI={r}, MACD={'↑' if mh>0 else '↓'}, EMA={'✓' if ema_bull else '✗'}.",
            strength, inds, sl_tight=price-av*1.0, sl_wide=price-av*2.2)

    if bear >= 4:
        strength = "high" if (bear == 5 or (bear == 4 and ema_bear)) else "medium"
        return sig(pair, tf, "sell", price, price-av*3, price+av*1.5,
            "Multi-Confluence",
            f"HIGH CONVICTION SELL — {bear}/5 indicators bearish. "
            f"RSI={r}, MACD={'↓' if mh<0 else '↑'}, EMA={'✓' if ema_bear else '✗'}.",
            strength, inds, sl_tight=price+av*1.0, sl_wide=price+av*2.2)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 12 — CARRY MOMENTUM
# Rules:
#   - H4 TIMEFRAME ONLY
#   - EMA 20 > 50 > 100 (bull) or 20 < 50 < 100 (bear) — all three stacked
#   - Price on correct side of all three EMAs
#   - RSI not at extreme (40-68 for buy, 32-60 for sell)
#   - EMA stack breaks = exit signal
# ════════════════════════════════════════════════════════════════════════════
def strat_carry(pair, tf, candles):
    # H4 ONLY
    if tf != "H4": return None
    if pair not in ("AUDUSD","GBPUSD","EURUSD","GBPJPY","USDJPY"): return None
    c = C(candles)
    if len(c) < 100: return None
    e20=ema_v(c,20); e50=ema_v(c,50); e100=ema_v(c,100)
    if not all([e20,e50,e100]): return None
    pip = P(pair); d = D(pair); price = c[-1]
    av = atr(H(candles),L(candles),c) or pip*20; r = rsi(c)
    inds = {"EMA_20":round(e20,d),"EMA_50":round(e50,d),"EMA_100":round(e100,d),"RSI":r}

    # Bull stack: EMA 20 > 50 > 100, price above all three, RSI not overbought
    if e20>e50>e100 and price>e20 and r and 40<r<68:
        return sig(pair, tf, "buy", price, price+av*2.5, price-av*1.2,
            "Carry Momentum",
            f"H4: EMA 20({e20:.{d}f}) > 50({e50:.{d}f}) > 100({e100:.{d}f}). Bullish EMA stack. Trend continuation.",
            "medium", inds, sl_tight=price-av*0.8, sl_wide=e50-av*0.5)

    # Bear stack: EMA 20 < 50 < 100
    if e20<e50<e100 and price<e20 and r and 32<r<60:
        return sig(pair, tf, "sell", price, price-av*2.5, price+av*1.2,
            "Carry Momentum",
            f"H4: EMA 20({e20:.{d}f}) < 50({e50:.{d}f}) < 100({e100:.{d}f}). Bearish EMA stack. Trend continuation.",
            "medium", inds, sl_tight=price+av*0.8, sl_wide=e50+av*0.5)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 13 — SCALP BREAKOUT
# Rules:
#   - M15 and H1 ONLY
#   - Tight consolidation (at least 5-8 candles, ATR significantly reduced)
#   - BUY STOP above consolidation high, SELL STOP below low
#   - Breakout candle must be significantly larger than consolidation candles
#   - Price closes back inside = false breakout, signal invalid
#   - Major news imminent = avoid
# ════════════════════════════════════════════════════════════════════════════
def strat_scalp(pair, tf, candles):
    # M15 and H1 only
    if tf not in ("M15","H1"): return None
    if len(candles) < 20: return None
    c = C(candles); h = H(candles); l = L(candles)
    pip = P(pair); d = D(pair); price = c[-1]
    av14 = atr(h,l,c,14) or pip*15
    # Last 8 candles for consolidation
    h8=h[-9:-1]; l8=l[-9:-1]; c8=c[-9:-1]
    if len(c8) < 2: return None
    av8 = atr(h8,l8,c8,min(6,len(c8)-1)) or pip*10
    # Consolidation: recent ATR must be at least 35% smaller than normal ATR
    if av8 > av14 * 0.65: return None
    ch = max(h8); cl = min(l8); r = rsi(c)
    # Breakout candle must be at least 2x the consolidation ATR
    last_rng = h[-1]-l[-1]
    if last_rng < av8*1.8: return None
    inds = {"Cons_Hi":round(ch,d),"Cons_Lo":round(cl,d),"ATR_Normal":round(av14,d),"ATR_Cons":round(av8,d),"RSI":r}

    if price > ch and c[-1] > c[-2]:
        return sig(pair, tf, "buy_stop", price, price+av14*1.5, ch-pip*3,
            "Scalp Breakout",
            f"Tight consolidation ({av8/av14*100:.0f}% of normal ATR) breakout above {ch:.{d}f}. BUY STOP. Momentum scalp.",
            "medium", inds, sl_tight=ch-pip*2, sl_wide=cl-pip*2)

    if price < cl and c[-1] < c[-2]:
        return sig(pair, tf, "sell_stop", price, price-av14*1.5, cl+pip*3,
            "Scalp Breakout",
            f"Tight consolidation breakdown below {cl:.{d}f}. SELL STOP. Momentum scalp.",
            "medium", inds, sl_tight=cl+pip*2, sl_wide=ch+pip*2)
    return None


# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 14 — OPENING RANGE BREAKOUT (ORB)
# Rules:
#   - M15 ONLY
#   - London session: 08:00-09:00 GMT range
#   - New York session: 13:00-14:00 GMT range
#   - BUY STOP above range high, SELL STOP below range low
#   - Signal must be taken within 3 hours of session open
#   - Opening range too wide (60+ pips) = skip
#   - Price closes back inside range = false breakout
# ════════════════════════════════════════════════════════════════════════════
def strat_orb(pair, tf, candles):
    if tf != "M15": return None
    if len(candles) < 10: return None
    now = datetime.now(timezone.utc); hour = now.hour
    # Only active during valid session windows
    if hour not in (8,9,10,13,14,15): return None
    c = C(candles); h = H(candles); l = L(candles)
    pip = P(pair); d = D(pair); price = c[-1]
    av = atr(h,l,c) or pip*20
    # Opening range = first 4 M15 candles of the session (1 hour)
    orh = max(h[-8:-4]); orl = min(l[-8:-4])
    range_size = orh - orl
    # Skip if range is too wide (60+ pips for majors)
    if range_size > pip*60: return None
    # Skip if range is too small
    if range_size < pip*8: return None

    sess = "London" if hour < 12 else "New York"
    inds = {"OR_High":round(orh,d),"OR_Low":round(orl,d),"Range_Pips":round(range_size/pip,1),"Session":sess}

    if price > orh and c[-1] > c[-2]:
        tp = price + range_size  # project range size upward
        return sig(pair, tf, "buy_stop", price, tp, orh-av*0.5,
            "ORB",
            f"{sess} opening range breakout above {orh:.{d}f}. Range={range_size/pip:.1f} pips. BUY STOP.",
            "medium", inds, sl_tight=orh-pip*2, sl_wide=orl-pip*2)

    if price < orl and c[-1] < c[-2]:
        tp = price - range_size
        return sig(pair, tf, "sell_stop", price, tp, orl+av*0.5,
            "ORB",
            f"{sess} opening range breakdown below {orl:.{d}f}. Range={range_size/pip:.1f} pips. SELL STOP.",
            "medium", inds, sl_tight=orl+pip*2, sl_wide=orh+pip*2)
    return None


# ════════════════════════════════════════════════════════════════════════════
# ENGINE
# ════════════════════════════════════════════════════════════════════════════
ALL_STRATS = [
    strat_fib_fvg, strat_ict_fvg, strat_supply_demand, strat_candle_patterns,
    strat_rsi_macd, strat_ema_cross, strat_bollinger, strat_sr_bounce,
    strat_stoch, strat_trendline, strat_confluence,
    strat_carry, strat_scalp, strat_orb,
]
STRAT_NAMES = [
    "Fib Golden Zone + FVG","ICT FVG","Supply & Demand","Candle Patterns",
    "RSI + MACD","EMA 50/200 Cross","Bollinger Breakout","S/R Bounce",
    "Stochastic","Trendline Breakout","Multi-Confluence",
    "Carry Momentum","Scalp Breakout","ORB",
]
TIMEFRAMES  = ["M15","H1","H4"]
PAIRS_LIST  = ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","GBPJPY","XAUUSD"]

_cooldown: dict = {}
AGREE_CD:  dict = {}
CD = 900          # 15-min cooldown per pair+tf+strategy
AGREE_THRESHOLD = 3
AGREE_COOLDOWN  = 3600


def build_agreement_signal(pair, tf, direction, agreeing):
    best = max(agreeing, key=lambda s: s.get("risk_reward",0))
    strat_names = [s["strategy"] for s in agreeing]
    is_long = direction == "buy"
    d = D(pair)
    entries = [s["entry"] for s in agreeing]
    tp1s = [s["tp1"] for s in agreeing if s.get("tp1")]
    sls  = [s.get("sl_standard", s.get("sl", best["entry"])) for s in agreeing]
    entry = round(sum(entries)/len(entries), d)
    tp1   = round(max(tp1s) if is_long else min(tp1s), d) if tp1s else best["tp1"]
    sl    = round(min(sls) if is_long else max(sls), d)
    rr    = round(abs(tp1-entry)/abs(entry-sl), 2) if abs(entry-sl) > 0 else 0
    return {
        "id": str(uuid.uuid4())[:8], "pair": pair, "timeframe": tf,
        "type": direction, "entry": entry, "tp1": tp1, "tp2": best.get("tp2"),
        "sl_tight": best.get("sl_tight",sl), "sl_standard": sl, "sl_wide": best.get("sl_wide",sl),
        "strategy": "⚡ MULTI-STRATEGY AGREEMENT",
        "reason": f"{len(agreeing)} strategies independently agree: {', '.join(strat_names)}. Multiple methods confirm this setup.",
        "strength": "high", "risk_reward": rr,
        "agreement": {"count":len(agreeing),"strategies":strat_names,"direction":direction},
        "indicators": best.get("indicators",{}),
        "fib_levels": best.get("fib_levels"),
        "fvg": best.get("fvg"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_agreement": True,
    }


class SignalEngine:
    def evaluate(self, candles_by_pair: dict) -> tuple:
        from time import time
        now = time()
        regular: list = []
        agreements: list = []

        for pair in PAIRS_LIST:
            for tf in TIMEFRAMES:
                cd = candles_by_pair.get(pair,{}).get(tf,[])
                if len(cd) < 30: continue
                this_candle: list = []

                for fn, name in zip(ALL_STRATS, STRAT_NAMES):
                    key = f"{pair}:{tf}:{name}"
                    if now - _cooldown.get(key,0) < CD: continue
                    try:
                        s = fn(pair, tf, cd)
                        if s:
                            regular.append(s)
                            this_candle.append(s)
                            _cooldown[key] = now
                            log.info(f"[{s['strength'].upper()}] {pair}/{tf} {s['type'].upper()} | {name}")
                    except Exception as e:
                        log.error(f"{name}/{pair}/{tf}: {e}")

                # Check agreements
                if len(this_candle) >= AGREE_THRESHOLD:
                    for direction in ("buy","sell"):
                        group = [s for s in this_candle if s["type"] in
                                 (("buy","buy_limit","buy_stop") if direction=="buy"
                                  else ("sell","sell_limit","sell_stop"))]
                        if len(group) >= AGREE_THRESHOLD:
                            akey = f"{pair}:{tf}:{direction}:agree"
                            if now - AGREE_CD.get(akey,0) < AGREE_COOLDOWN: continue
                            ag = build_agreement_signal(pair, tf, direction, group)
                            agreements.append(ag)
                            AGREE_CD[akey] = now
                            log.info(f"🔥 AGREEMENT [{len(group)}] {pair}/{tf} {direction.upper()} — {[s['strategy'] for s in group]}")

        return regular, agreements
