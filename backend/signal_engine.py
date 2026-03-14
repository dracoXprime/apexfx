"""
APEX FX - Signal Engine v3
14 strategies across M15 / H1 / H4 per pair.

 1. Fibonacci Golden Zone + FVG
 2. ICT Fair Value Gap (BOS + rebalance)
 3. Supply & Demand Zones (Sam Seiden)
 4. Candlestick Patterns (Engulfing, Pin Bar, Hammer, Morning/Evening Star,
                          Doji, Shooting Star, Harami, Marubozu, Three Soldiers/Crows)
 5. RSI + MACD Crossover
 6. EMA 50/200 Golden/Death Cross
 7. Bollinger Band Breakout & Mean Reversion
 8. Support & Resistance Bounce
 9. Stochastic Oscillator Cross
10. Trendline Breakout
11. Multi-Indicator Confluence (4+/5)
12. Carry Trade Momentum
13. Scalp Breakout (consolidation expansion)
14. Opening Range Breakout
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

def D(pair): return DIGITS.get(pair,5)
def P(pair): return PIPS.get(pair,1e-4)

# ════════════════════════════════════════════════════════════════════════════
# INDICATOR HELPERS
# ════════════════════════════════════════════════════════════════════════════
def C(cd): return [c["close"] for c in cd]
def H(cd): return [c["high"]  for c in cd]
def L(cd): return [c["low"]   for c in cd]
def O(cd): return [c["open"]  for c in cd]

def ema_s(data, n):
    if len(data)<n: return []
    k=2/(n+1); r=[sum(data[:n])/n]
    for p in data[n:]: r.append(p*k+r[-1]*(1-k))
    return r

def ema_v(data, n):
    s=ema_s(data,n); return s[-1] if s else None

def sma(data, n):
    if len(data)<n: return None
    return sum(data[-n:])/n

def rsi(data, n=14):
    if len(data)<n+1: return None
    g=[max(data[i]-data[i-1],0) for i in range(1,len(data))]
    lo=[max(data[i-1]-data[i],0) for i in range(1,len(data))]
    ag=sum(g[-n:])/n; al=sum(lo[-n:])/n
    return round(100-100/(1+ag/al),2) if al else 100.0

def macd(data, f=12, s=26, sig=9):
    if len(data)<s+sig+5: return None,None,None
    ef=ema_s(data,f); es=ema_s(data,s)
    ml=[ef[len(ef)-len(es)+i]-es[i] for i in range(len(es))]
    if len(ml)<sig: return None,None,None
    sl=ema_s(ml,sig)
    if not sl: return None,None,None
    return round(ml[-1],8),round(sl[-1],8),round(ml[-1]-sl[-1],8)

def bollinger(data, n=20, k=2.0):
    if len(data)<n: return None,None,None
    w=data[-n:]; m=sum(w)/n; sd=math.sqrt(sum((x-m)**2 for x in w)/n)
    return round(m+k*sd,6),round(m,6),round(m-k*sd,6)

def stoch(hs,ls,cs,kp=14,dp=3):
    if len(cs)<kp+dp: return None,None
    kv=[]
    for i in range(kp-1,len(cs)):
        hi=max(hs[i-kp+1:i+1]); lo=min(ls[i-kp+1:i+1])
        kv.append(100*(cs[i]-lo)/(hi-lo) if hi!=lo else 50.0)
    if len(kv)<dp: return None,None
    return round(kv[-1],2),round(sum(kv[-dp:])/dp,2)

def atr(hs,ls,cs,n=14):
    if len(cs)<n+1: return None
    tr=[max(hs[i]-ls[i],abs(hs[i]-cs[i-1]),abs(ls[i]-cs[i-1])) for i in range(1,len(cs))]
    return round(sum(tr[-n:])/n,6)

def pivot_highs(hs,lb=4):
    return [i for i in range(lb,len(hs)-lb) if hs[i]==max(hs[i-lb:i+lb+1])]

def pivot_lows(ls,lb=4):
    return [i for i in range(lb,len(ls)-lb) if ls[i]==min(ls[i-lb:i+lb+1])]

def swing_hi(hs,n=20): return max(hs[-n:]) if len(hs)>=n else max(hs)
def swing_lo(ls,n=20): return min(ls[-n:]) if len(ls)>=n else min(ls)

# ════════════════════════════════════════════════════════════════════════════
# FIB TOOLS
# ════════════════════════════════════════════════════════════════════════════
FIB = {"0":0,"23.6":0.236,"38.2":0.382,"50":0.5,"61.8":0.618,"78.6":0.786,"88.6":0.886,"100":1.0,"127.2":1.272,"161.8":1.618}

def fib_levels(hi, lo):
    """0% = hi, 100% = lo. Retracement goes from hi downward."""
    rng=hi-lo
    return {k: round(hi-v*rng,8) for k,v in FIB.items()}

# ════════════════════════════════════════════════════════════════════════════
# FVG TOOLS
# ════════════════════════════════════════════════════════════════════════════
def find_fvgs(candles, lookback=50):
    out=[]
    recent=candles[-lookback:]
    for i in range(1,len(recent)-1):
        c1,c3=recent[i-1],recent[i+1]
        if c3["low"]>c1["high"]:
            out.append({"type":"bull","top":c3["low"],"bot":c1["high"],"mid":(c3["low"]+c1["high"])/2,"i":i})
        elif c3["high"]<c1["low"]:
            out.append({"type":"bear","top":c1["low"],"bot":c3["high"],"mid":(c1["low"]+c3["high"])/2,"i":i})
    return out

def touches_fvg(price, fvg):
    buf=(fvg["top"]-fvg["bot"])*0.3
    return fvg["bot"]-buf<=price<=fvg["top"]+buf

def fvg_in_zone(fvg, zlo, zhi):
    return fvg["bot"]<=zhi and fvg["top"]>=zlo

# ════════════════════════════════════════════════════════════════════════════
# SIGNAL BUILDER
# ════════════════════════════════════════════════════════════════════════════
def sig(pair, tf, stype, entry, tp1, sl_standard, strategy, reason, strength, inds,
        tp2=None, sl_tight=None, sl_wide=None, fib=None, fvg=None):
    d=D(pair)
    rr=round(abs(tp1-entry)/abs(entry-sl_standard),2) if abs(entry-sl_standard)>0 else 0
    s={
        "id": str(uuid.uuid4())[:8],
        "pair": pair, "timeframe": tf, "type": stype,
        "entry": round(entry,d), "tp1": round(tp1,d),
        "tp2": round(tp2,d) if tp2 else None,
        "sl_tight": round(sl_tight,d) if sl_tight else round(sl_standard,d),
        "sl_standard": round(sl_standard,d),
        "sl_wide": round(sl_wide,d) if sl_wide else round(sl_standard,d),
        "strategy": strategy, "reason": reason, "strength": strength,
        "risk_reward": rr, "indicators": inds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fib: s["fib_levels"]={k:round(v,d) for k,v in fib.items()}
    if fvg: s["fvg"]={k:round(v,d) if isinstance(v,float) else v for k,v in fvg.items()}
    return s

# ════════════════════════════════════════════════════════════════════════════
# 1. FIBONACCI GOLDEN ZONE + FVG
# ════════════════════════════════════════════════════════════════════════════
def strat_fib_fvg(pair, tf, candles):
    if len(candles)<60: return None
    c=C(candles); h=H(candles); l=L(candles)
    price=c[-1]; pip=P(pair); d=D(pair)
    av=atr(h,l,c) or pip*20

    ph=pivot_highs(h,4); pl=pivot_lows(l,4)
    if len(ph)<2 or len(pl)<1: return None

    # ── BULLISH: new higher high, price pulling back ──
    new_hi_i=ph[-1]; new_hi=h[new_hi_i]
    prior_ph=[i for i in ph if i<new_hi_i]
    btw_lo=[i for i in pl if (prior_ph and i>prior_ph[-1]) and i<new_hi_i]
    if btw_lo:
        sw_lo_i=min(btw_lo,key=lambda i:l[i]); sw_lo=l[sw_lo_i]
        move=new_hi-sw_lo
        if move>=pip*25 and price<new_hi:
            pb_pct=(new_hi-price)/move
            if pb_pct>=0.25:
                fibs=fib_levels(new_hi,sw_lo)
                f50=fibs["50"]; f618=fibs["61.8"]; f786=fibs["78.6"]
                gz_lo=min(f50,f618); gz_hi=max(f50,f618)
                dz_lo=min(f618,f786); dz_hi=max(f618,f786)
                # fib extension targets
                ext1272=new_hi+(new_hi-sw_lo)*0.272
                ext1618=new_hi+(new_hi-sw_lo)*0.618

                fvgs=find_fvgs(candles,60)
                bull_fvgs=[f for f in fvgs if f["type"]=="bull"]
                fvg_zone=next((f for f in bull_fvgs if fvg_in_zone(f,gz_lo,gz_hi) or fvg_in_zone(f,dz_lo,dz_hi)),None)

                at_gz=gz_lo<=price<=gz_hi; at_dz=dz_lo<=price<=dz_hi
                above_gz=price>gz_hi and pb_pct<0.48
                bull_candle=c[-1]>c[-2]
                fvg_react=fvg_zone and touches_fvg(price,fvg_zone) and bull_candle
                fvg_broke=fvg_zone and price<fvg_zone["bot"] and bull_candle

                inds={"New_High":round(new_hi,d),"Swing_Low":round(sw_lo,d),"Fib_50":round(f50,d),"Fib_61.8":round(f618,d),"Fib_78.6":round(f786,d),"Pullback%":round(pb_pct*100,1),"FVG":f"{fvg_zone['bot']:.{d}f}–{fvg_zone['top']:.{d}f}" if fvg_zone else "None"}

                if at_gz and not fvg_zone and bull_candle:
                    return sig(pair,tf,"buy",price,new_hi,f786-av*0.5,"Fib Golden Zone + FVG",
                        f"Golden zone ({f50:.{d}f}–{f618:.{d}f}) — no FVG blocking. Bullish candle confirmed. TP1=prior high, TP2=1.618 ext.","high",inds,
                        tp2=ext1618,sl_tight=f618-av*0.3,sl_wide=sw_lo-av*0.5,fib=fibs)

                if (at_gz or at_dz) and fvg_react:
                    return sig(pair,tf,"buy",price,new_hi,fvg_zone["bot"]-av*0.25,"Fib Golden Zone + FVG",
                        f"Golden zone + FVG ({fvg_zone['bot']:.{d}f}–{fvg_zone['top']:.{d}f}) — price reacting. SL below FVG. TP1=prior high.","high",inds,
                        tp2=ext1618,sl_tight=fvg_zone["bot"]-av*0.2,sl_wide=sw_lo-av*0.5,fib=fibs,fvg=fvg_zone)

                if (at_gz or at_dz) and fvg_broke:
                    return sig(pair,tf,"buy",price,new_hi,price-av*1.2,"Fib Golden Zone + FVG",
                        f"FVG ({fvg_zone['bot']:.{d}f}–{fvg_zone['top']:.{d}f}) broken — continuation to prior high expected.","high",inds,
                        tp2=ext1618,sl_wide=sw_lo-av*0.5,fib=fibs,fvg=fvg_zone)

                if above_gz and 0.25<=pb_pct<0.48:
                    note=f" ⚠ FVG at {fvg_zone['bot']:.{d}f}–{fvg_zone['top']:.{d}f} in zone." if fvg_zone else ""
                    return sig(pair,tf,"buy_limit",f618,new_hi,f786-av*0.5,"Fib Golden Zone + FVG",
                        f"Pullback {pb_pct*100:.0f}% — set BUY LIMIT at 61.8% ({f618:.{d}f}).{note} TP1=prior high.","medium",inds,
                        tp2=ext1618,sl_wide=sw_lo-av*0.5,fib=fibs,fvg=fvg_zone)

                if at_dz and bull_candle:
                    return sig(pair,tf,"buy",price,new_hi,sw_lo-av*0.5,"Fib Golden Zone + FVG",
                        f"Deep zone ({f618:.{d}f}–{f786:.{d}f}) — last support. Bullish candle. TP1=prior high.","medium",inds,
                        tp2=ext1618,sl_wide=sw_lo-av*0.8,fib=fibs,fvg=fvg_zone)

    # ── BEARISH: new lower low, price retracing up ──
    new_lo_i=pl[-1] if pl else None
    if new_lo_i:
        new_lo=l[new_lo_i]
        prior_pl_i=[i for i in pl if i<new_lo_i]
        btw_hi=[i for i in ph if (prior_pl_i and i>prior_pl_i[-1]) and i<new_lo_i]
        if btw_hi:
            sw_hi_i=max(btw_hi,key=lambda i:h[i]); sw_hi=h[sw_hi_i]
            move=sw_hi-new_lo
            if move>=pip*25 and price>new_lo:
                pb_pct=(price-new_lo)/move
                if pb_pct>=0.25:
                    fibs=fib_levels(sw_hi,new_lo)  # redrawn from sw_hi to new_lo
                    # For bearish: fib from new_lo (0%) up to sw_hi (100%)
                    rng=sw_hi-new_lo
                    f50b=round(new_lo+0.5*rng,d); f618b=round(new_lo+0.618*rng,d); f786b=round(new_lo+0.786*rng,d)
                    gz_lo=min(f50b,f618b); gz_hi=max(f50b,f618b)
                    ext1618=new_lo-(sw_hi-new_lo)*0.618
                    fvgs=find_fvgs(candles,60)
                    bear_fvgs=[f for f in fvgs if f["type"]=="bear"]
                    fvg_zone=next((f for f in bear_fvgs if fvg_in_zone(f,gz_lo,gz_hi)),None)
                    at_gz=gz_lo<=price<=gz_hi; bear_candle=c[-1]<c[-2]
                    inds={"New_Low":round(new_lo,d),"Swing_High":round(sw_hi,d),"Fib_50":round(f50b,d),"Fib_61.8":round(f618b,d),"Pullback%":round(pb_pct*100,1),"FVG":f"{fvg_zone['bot']:.{d}f}–{fvg_zone['top']:.{d}f}" if fvg_zone else "None"}
                    if at_gz and bear_candle:
                        return sig(pair,tf,"sell",price,new_lo,f786b+av*0.5,"Fib Golden Zone + FVG",
                            f"Bearish: retracing to golden zone ({f50b:.{d}f}–{f618b:.{d}f}) after new low. Bearish candle. TP1=prior low.","high",inds,
                            tp2=ext1618,sl_tight=f618b+av*0.3,sl_wide=sw_hi+av*0.5,fvg=fvg_zone)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 2. ICT FAIR VALUE GAP
# ════════════════════════════════════════════════════════════════════════════
def strat_ict_fvg(pair, tf, candles):
    if len(candles)<30: return None
    c=C(candles); h=H(candles); l=L(candles)
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(h,l,c) or pip*20
    fvgs=find_fvgs(candles,40)
    rsh=swing_hi(h,20); rsl=swing_lo(l,20)
    bos_bull=price>rsh and c[-2]<=rsh
    bos_bear=price<rsl and c[-2]>=rsl

    if bos_bull:
        for f in reversed([x for x in fvgs if x["type"]=="bull" and x["i"]>len(fvgs)-15]):
            if touches_fvg(price,f):
                inds={"FVG_Top":round(f["top"],d),"FVG_Bot":round(f["bot"],d),"BOS":round(rsh,d)}
                return sig(pair,tf,"buy",price,rsh+av*2,f["bot"]-av*0.5,"ICT FVG",
                    f"BOS above {rsh:.{d}f} → retracing into bullish FVG ({f['bot']:.{d}f}–{f['top']:.{d}f}). Institutional rebalancing.","high",inds,fvg=f)

    if bos_bear:
        for f in reversed([x for x in fvgs if x["type"]=="bear" and x["i"]>len(fvgs)-15]):
            if touches_fvg(price,f):
                inds={"FVG_Top":round(f["top"],d),"FVG_Bot":round(f["bot"],d),"BOS":round(rsl,d)}
                return sig(pair,tf,"sell",price,rsl-av*2,f["top"]+av*0.5,"ICT FVG",
                    f"Bearish BOS below {rsl:.{d}f} → retracing into bearish FVG ({f['bot']:.{d}f}–{f['top']:.{d}f}).","high",inds,fvg=f)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 3. SUPPLY & DEMAND ZONES
# ════════════════════════════════════════════════════════════════════════════
def strat_supply_demand(pair, tf, candles):
    if len(candles)<50: return None
    c=C(candles); h=H(candles); l=L(candles); o=O(candles)
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(h,l,c) or pip*20
    demand,supply=[],[]
    for i in range(2,len(candles)-2):
        body=abs(c[i]-o[i]); rng=h[i]-l[i]
        if body>av*1.5 and (rng==0 or body/rng>0.6):
            bi=i-1; zt=max(c[bi],o[bi]); zb=min(c[bi],o[bi])
            if zt-zb>=pip*3:
                if c[i]>o[i]: demand.append({"top":zt,"bot":zb,"target":h[i]})
                else:          supply.append({"top":zt,"bot":zb,"target":l[i]})
    for z in demand[-5:]:
        if z["bot"]<=price<=z["top"]+av*0.4:
            inds={"Zone":f"{z['bot']:.{d}f}–{z['top']:.{d}f}","Type":"Demand"}
            return sig(pair,tf,"buy",price,z["target"]+av,z["bot"]-av*0.8,"Supply & Demand",
                f"Demand zone ({z['bot']:.{d}f}–{z['top']:.{d}f}) — institutional buying origin. High-probability reversal.","high",inds)
    for z in supply[-5:]:
        if z["bot"]-av*0.4<=price<=z["top"]:
            inds={"Zone":f"{z['bot']:.{d}f}–{z['top']:.{d}f}","Type":"Supply"}
            return sig(pair,tf,"sell",price,z["target"]-av,z["top"]+av*0.8,"Supply & Demand",
                f"Supply zone ({z['bot']:.{d}f}–{z['top']:.{d}f}) — institutional selling origin.","high",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 4. CANDLESTICK PATTERNS
# ════════════════════════════════════════════════════════════════════════════
def strat_candle_patterns(pair, tf, candles):
    if len(candles)<5: return None
    c=C(candles); h=H(candles); l=L(candles); o=O(candles)
    price=c[-1]; pip=P(pair); d=D(pair)
    av=atr(h,l,c) or pip*20
    r=rsi(c)

    c0,c1,c2=candles[-1],candles[-2],candles[-3]
    body0=abs(c[-1]-o[-1]); rng0=h[-1]-l[-1]
    body1=abs(c[-2]-o[-2]); rng1=h[-2]-l[-2]
    bull0=c[-1]>o[-1]; bear0=c[-1]<o[-1]
    bull1=c[-2]>o[-2]; bear1=c[-2]<o[-2]
    uw0=h[-1]-max(c[-1],o[-1]); lw0=min(c[-1],o[-1])-l[-1]
    uw1=h[-2]-max(c[-2],o[-2]); lw1=min(c[-2],o[-2])-l[-2]

    e50=ema_v(c,50); trend_up=price>e50 if e50 else None

    def make(stype,strength,name,reason):
        is_buy=stype in("buy","buy_limit")
        tp=price+av*2 if is_buy else price-av*2
        sl=price-av*1.2 if is_buy else price+av*1.2
        inds={"Pattern":name,"RSI":r,"EMA_50":round(e50,d) if e50 else None}
        return sig(pair,tf,stype,price,tp,sl,"Candle Patterns",reason,strength,inds)

    # ── Bullish engulfing ──
    if bear1 and bull0 and body0>body1*1.2 and o[-1]<=c[-2] and c[-1]>=o[-2] and (r is None or r<60):
        return make("buy","high","Bullish Engulfing",f"Bullish engulfing candle — prior bearish body fully consumed. RSI={r}.")

    # ── Bearish engulfing ──
    if bull1 and bear0 and body0>body1*1.2 and o[-1]>=c[-2] and c[-1]<=o[-2] and (r is None or r>40):
        return make("sell","high","Bearish Engulfing",f"Bearish engulfing — prior bullish body fully consumed. RSI={r}.")

    # ── Hammer (bullish reversal at low) ──
    if lw0>body0*2 and uw0<body0*0.5 and rng0>pip*5 and (r is None or r<50):
        return make("buy","high","Hammer",f"Hammer candle — long lower wick ({lw0:.{d}f}) = buying pressure rejected sellers. RSI={r}.")

    # ── Shooting star (bearish reversal at high) ──
    if uw0>body0*2 and lw0<body0*0.5 and rng0>pip*5 and (r is None or r>50):
        return make("sell","high","Shooting Star",f"Shooting star — long upper wick ({uw0:.{d}f}) = selling pressure rejected buyers. RSI={r}.")

    # ── Pin bar bullish ──
    if lw0>rng0*0.6 and body0<rng0*0.35 and (r is None or r<45):
        return make("buy","high","Bullish Pin Bar",f"Bullish pin bar — wick {lw0:.{d}f} represents strong rejection of lows. RSI={r}.")

    # ── Pin bar bearish ──
    if uw0>rng0*0.6 and body0<rng0*0.35 and (r is None or r>55):
        return make("sell","high","Bearish Pin Bar",f"Bearish pin bar — wick {uw0:.{d}f} represents strong rejection of highs. RSI={r}.")

    # ── Morning star (3-candle bullish reversal) ──
    if len(candles)>=3:
        bear2=o[-3]>c[-3]; small1=abs(c[-2]-o[-2])<av*0.4; bull_close=c[-1]>o[-1] and c[-1]>o[-3]+(c[-3]-o[-3])*0.5
        if bear2 and small1 and bull_close and (r is None or r<50):
            return make("buy","high","Morning Star",f"Morning star pattern — 3-candle bullish reversal confirmed. RSI={r}.")

    # ── Evening star (3-candle bearish reversal) ──
    if len(candles)>=3:
        bull2=c[-3]>o[-3]; small1=abs(c[-2]-o[-2])<av*0.4; bear_close=c[-1]<o[-1] and c[-1]<c[-3]-(c[-3]-o[-3])*0.5
        if bull2 and small1 and bear_close and (r is None or r>50):
            return make("sell","high","Evening Star",f"Evening star pattern — 3-candle bearish reversal confirmed. RSI={r}.")

    # ── Bullish Marubozu (strong momentum) ──
    if bull0 and body0>rng0*0.9 and rng0>av*1.2 and trend_up:
        return make("buy","medium","Bullish Marubozu",f"Marubozu — full-bodied bullish candle with almost no wicks. Strong momentum.")

    # ── Bearish Marubozu ──
    if bear0 and body0>rng0*0.9 and rng0>av*1.2 and trend_up is False:
        return make("sell","medium","Bearish Marubozu",f"Marubozu — full-bodied bearish candle with almost no wicks. Strong momentum.")

    # ── Three white soldiers ──
    if len(candles)>=3:
        if all(c[-i]>o[-i] and abs(c[-i]-o[-i])>av*0.8 for i in range(1,4)) and c[-1]>c[-2]>c[-3]:
            return make("buy","medium","Three White Soldiers",f"Three consecutive strong bullish candles — sustained buying pressure.")

    # ── Three black crows ──
    if len(candles)>=3:
        if all(c[-i]<o[-i] and abs(c[-i]-o[-i])>av*0.8 for i in range(1,4)) and c[-1]<c[-2]<c[-3]:
            return make("sell","medium","Three Black Crows",f"Three consecutive strong bearish candles — sustained selling pressure.")

    # ── Doji at extreme (indecision at key level) ──
    if body0<rng0*0.1 and rng0>av*0.5 and r:
        if r<30:
            return make("buy","medium","Doji (Oversold)",f"Doji at oversold level (RSI={r}) — indecision after downmove, reversal likely.")
        if r>70:
            return make("sell","medium","Doji (Overbought)",f"Doji at overbought level (RSI={r}) — indecision after upmove, reversal likely.")

    # ── Bullish Harami ──
    if bear1 and bull0 and body0<body1*0.6 and o[-1]>c[-2] and c[-1]<o[-2] and (r is None or r<50):
        return make("buy","medium","Bullish Harami",f"Bullish harami — small candle inside prior bearish candle. Momentum shift. RSI={r}.")

    # ── Bearish Harami ──
    if bull1 and bear0 and body0<body1*0.6 and o[-1]<c[-2] and c[-1]>o[-2] and (r is None or r>50):
        return make("sell","medium","Bearish Harami",f"Bearish harami — small candle inside prior bullish candle. Momentum shift. RSI={r}.")

    return None


# ════════════════════════════════════════════════════════════════════════════
# 5. RSI + MACD
# ════════════════════════════════════════════════════════════════════════════
def strat_rsi_macd(pair, tf, candles):
    c=C(candles)
    if len(c)<40: return None
    r=rsi(c); mv,ms,mh=macd(c); pmh=macd(c[:-1])[2]
    if r is None or mh is None or pmh is None: return None
    pip=P(pair); d=D(pair); price=c[-1]; av=atr(H(candles),L(candles),c) or pip*20
    inds={"RSI":r,"MACD_Hist":round(mh,6)}
    if r<32 and mh>0 and pmh<=0:
        return sig(pair,tf,"buy",price,price+av*2.2,price-av*1.2,"RSI + MACD",f"RSI={r} oversold + MACD bullish histogram crossover.","high",inds,sl_tight=price-av*0.8,sl_wide=price-av*1.8)
    if r>68 and mh<0 and pmh>=0:
        return sig(pair,tf,"sell",price,price-av*2.2,price+av*1.2,"RSI + MACD",f"RSI={r} overbought + MACD bearish histogram crossover.","high",inds,sl_tight=price+av*0.8,sl_wide=price+av*1.8)
    if 33<=r<=43 and mh>0 and mv<0:
        return sig(pair,tf,"buy_limit",price-av*0.5,price+av*2.5,price-av*1.5,"RSI + MACD",f"RSI={r} nearing oversold — limit at pullback.","medium",inds)
    if 58<=r<=67 and mh<0 and mv>0:
        return sig(pair,tf,"sell_limit",price+av*0.5,price-av*2.5,price+av*1.5,"RSI + MACD",f"RSI={r} nearing overbought — limit at retest.","medium",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 6. EMA 50/200 CROSS
# ════════════════════════════════════════════════════════════════════════════
def strat_ema_cross(pair, tf, candles):
    c=C(candles)
    if len(c)<210: return None
    e50=ema_s(c,50); e200=ema_s(c,200)
    if len(e50)<2 or len(e200)<2: return None
    pip=P(pair); d=D(pair); price=c[-1]; av=atr(H(candles),L(candles),c) or pip*20
    inds={"EMA_50":round(e50[-1],d),"EMA_200":round(e200[-1],d)}
    if e50[-2]<e200[-2] and e50[-1]>e200[-1]:
        return sig(pair,tf,"buy",price,price+av*3,price-av*1.5,"EMA 50/200 Cross","Golden Cross — EMA 50 crossed above EMA 200.","high",inds)
    if e50[-2]>e200[-2] and e50[-1]<e200[-1]:
        return sig(pair,tf,"sell",price,price-av*3,price+av*1.5,"EMA 50/200 Cross","Death Cross — EMA 50 crossed below EMA 200.","high",inds)
    if e50[-1]>e200[-1] and 0<price-e50[-1]<av*0.5:
        return sig(pair,tf,"buy_limit",e50[-1]+P(pair)*3,e50[-1]+av*2.5,e50[-1]-av,"EMA 50/200 Cross","Bullish trend — limit buy on pullback to EMA 50.","medium",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 7. BOLLINGER BANDS
# ════════════════════════════════════════════════════════════════════════════
def strat_bollinger(pair, tf, candles):
    c=C(candles)
    if len(c)<25: return None
    up,mb,lo=bollinger(c)
    if up is None: return None
    pip=P(pair); d=D(pair); price=c[-1]; prev=c[-2]; av=atr(H(candles),L(candles),c) or pip*20
    bw=(up-lo)/mb
    inds={"BB_Up":round(up,d),"BB_Mid":round(mb,d),"BB_Lo":round(lo,d),"BW%":round(bw*100,2)}
    if prev<up<=price and bw>0.005:
        return sig(pair,tf,"buy",price,price+(up-mb)*1.5,mb,"Bollinger Breakout",f"Price broke above upper BB ({up:.{d}f}). Momentum breakout.","high",inds)
    if prev>lo>=price and bw>0.005:
        return sig(pair,tf,"sell",price,price-(mb-lo)*1.5,mb,"Bollinger Breakout",f"Price broke below lower BB ({lo:.{d}f}). Momentum breakdown.","high",inds)
    if abs(price-lo)<av*0.3 and price>lo:
        return sig(pair,tf,"buy_limit",lo+P(pair)*2,mb,lo-av*0.8,"Bollinger Breakout",f"Limit buy at lower BB ({lo:.{d}f}) — mean reversion.","medium",inds)
    if abs(price-up)<av*0.3 and price<up:
        return sig(pair,tf,"sell_limit",up-P(pair)*2,mb,up+av*0.8,"Bollinger Breakout",f"Limit sell at upper BB ({up:.{d}f}) — mean reversion.","medium",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 8. SUPPORT & RESISTANCE BOUNCE
# ════════════════════════════════════════════════════════════════════════════
def strat_sr_bounce(pair, tf, candles):
    c=C(candles); h=H(candles); l=L(candles)
    if len(c)<55: return None
    ph=pivot_highs(h); pl=pivot_lows(l)
    pip=P(pair); d=D(pair); price=c[-1]; av=atr(h,l,c) or pip*20; r=rsi(c)
    inds={"RSI":r,"ATR":round(av,d)}
    for i in pl[-4:]:
        sup=l[i]
        if abs(price-sup)<av*0.6 and price>sup and (r is None or r<52):
            return sig(pair,tf,"buy",price,price+av*2,sup-av*0.8,"S/R Bounce",f"Bouncing off support {sup:.{d}f}. RSI={r}.","high" if r and r<35 else "medium",inds)
    for i in ph[-4:]:
        res=h[i]
        if abs(price-res)<av*0.6 and price<res and (r is None or r>48):
            return sig(pair,tf,"sell",price,price-av*2,res+av*0.8,"S/R Bounce",f"Rejected at resistance {res:.{d}f}. RSI={r}.","high" if r and r>65 else "medium",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 9. STOCHASTIC
# ════════════════════════════════════════════════════════════════════════════
def strat_stoch(pair, tf, candles):
    c=C(candles); h=H(candles); l=L(candles)
    if len(c)<25: return None
    k,dv=stoch(h,l,c); kp,dp=stoch(h[:-1],l[:-1],c[:-1])
    e50=ema_v(c,50)
    if k is None or kp is None: return None
    pip=P(pair); d=D(pair); price=c[-1]; av=atr(h,l,c) or pip*20
    trend_up=price>e50 if e50 else True
    inds={"Stoch_K":k,"Stoch_D":dv}
    if kp<dp and k>dv and k<30 and trend_up:
        return sig(pair,tf,"buy",price,price+av*2,price-av*1.2,"Stochastic",f"%K({k}) crossed %D({dv}) in oversold zone — bullish.","high",inds)
    if kp>dp and k<dv and k>70 and not trend_up:
        return sig(pair,tf,"sell",price,price-av*2,price+av*1.2,"Stochastic",f"%K({k}) crossed %D({dv}) in overbought zone — bearish.","high",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 10. TRENDLINE BREAKOUT
# ════════════════════════════════════════════════════════════════════════════
def strat_trendline(pair, tf, candles):
    if len(candles)<40: return None
    c=C(candles); h=H(candles); l=L(candles)
    pip=P(pair); d=D(pair); price=c[-1]; prev=c[-2]; av=atr(h,l,c) or pip*20; r=rsi(c)
    ph=pivot_highs(h); pl=pivot_lows(l)
    if len(ph)<2 or len(pl)<2: return None
    ph1,ph2=ph[-2],ph[-1]
    if ph2>ph1:
        slope=(h[ph2]-h[ph1])/(ph2-ph1); tl=h[ph2]+slope*(len(c)-1-ph2)
        if prev<tl<=price and r and r<65:
            inds={"Trendline":round(tl,d),"RSI":r}
            return sig(pair,tf,"buy",price,price+av*2.5,tl-av,"Trendline Breakout",f"Closed above descending trendline ({tl:.{d}f}). RSI={r}.","high",inds)
    pl1,pl2=pl[-2],pl[-1]
    if pl2>pl1:
        slope=(l[pl2]-l[pl1])/(pl2-pl1); tl=l[pl2]+slope*(len(c)-1-pl2)
        if prev>tl>=price and r and r>35:
            inds={"Trendline":round(tl,d),"RSI":r}
            return sig(pair,tf,"sell",price,price-av*2.5,tl+av,"Trendline Breakout",f"Closed below ascending trendline ({tl:.{d}f}). RSI={r}.","high",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 11. MULTI-CONFLUENCE
# ════════════════════════════════════════════════════════════════════════════
def strat_confluence(pair, tf, candles):
    c=C(candles); h=H(candles); l=L(candles)
    if len(c)<60: return None
    r=rsi(c) or 50; _,_,mh=macd(c); e50=ema_v(c,50); e200=ema_v(c,200)
    k,_=stoch(h,l,c); _,mb,_=bollinger(c)
    av=atr(h,l,c) or P(pair)*20
    if None in (mh,e50,e200,k,mb): return None
    pip=P(pair); d=D(pair); price=c[-1]
    bull=sum([r<40, mh>0, e50>e200, k<40, price<mb])
    bear=sum([r>60, mh<0, e50<e200, k>60, price>mb])
    inds={"RSI":r,"MACD_Hist":round(mh,7),"EMA":f"{round(e50,d)}/{round(e200,d)}","Bull":bull,"Bear":bear}
    if bull>=4:
        return sig(pair,tf,"buy",price,price+av*3,price-av*1.5,"Multi-Confluence",f"HIGH CONVICTION BUY — {bull}/5 indicators bullish.","high",inds,sl_tight=price-av*1,sl_wide=price-av*2.2)
    if bear>=4:
        return sig(pair,tf,"sell",price,price-av*3,price+av*1.5,"Multi-Confluence",f"HIGH CONVICTION SELL — {bear}/5 indicators bearish.","high",inds,sl_tight=price+av*1,sl_wide=price+av*2.2)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 12. CARRY MOMENTUM
# ════════════════════════════════════════════════════════════════════════════
def strat_carry(pair, tf, candles):
    if pair not in ("AUDUSD","GBPUSD","EURUSD","GBPJPY"): return None
    c=C(candles)
    if len(c)<100: return None
    e20=ema_v(c,20); e50=ema_v(c,50); e100=ema_v(c,100)
    if not all([e20,e50,e100]): return None
    pip=P(pair); d=D(pair); price=c[-1]; av=atr(H(candles),L(candles),c) or pip*20; r=rsi(c)
    inds={"EMA_20":round(e20,d),"EMA_50":round(e50,d),"EMA_100":round(e100,d),"RSI":r}
    if e20>e50>e100 and price>e20 and r and 40<r<68:
        return sig(pair,tf,"buy",price,price+av*2.5,price-av*1.2,"Carry Momentum","EMA 20>50>100 bullish stack — trend continuation.","medium",inds)
    if e20<e50<e100 and price<e20 and r and 32<r<60:
        return sig(pair,tf,"sell",price,price-av*2.5,price+av*1.2,"Carry Momentum","EMA 20<50<100 bearish stack — trend continuation.","medium",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 13. SCALP BREAKOUT
# ════════════════════════════════════════════════════════════════════════════
def strat_scalp(pair, tf, candles):
    if len(candles)<20: return None
    c=C(candles); h=H(candles); l=L(candles)
    pip=P(pair); d=D(pair); price=c[-1]
    av14=atr(h,l,c,14) or pip*15
    h8=h[-9:-1]; l8=l[-9:-1]; c8=c[-9:-1]
    if len(c8)<2: return None
    av8=atr(h8,l8,c8,min(6,len(c8)-1)) or pip*10
    if av8>av14*0.65: return None
    ch=max(h8); cl=min(l8); r=rsi(c)
    if h[-1]-l[-1]<av8*2: return None
    inds={"Cons_Hi":round(ch,d),"Cons_Lo":round(cl,d),"ATR":round(av14,d),"RSI":r}
    if price>ch and c[-1]>c[-2]:
        return sig(pair,tf,"buy",price,price+av14*1.5,ch-pip*3,"Scalp Breakout",f"Consolidation breakout above {ch:.{d}f}. Momentum scalp.","medium",inds)
    if price<cl and c[-1]<c[-2]:
        return sig(pair,tf,"sell",price,price-av14*1.5,cl+pip*3,"Scalp Breakout",f"Consolidation breakdown below {cl:.{d}f}. Momentum scalp.","medium",inds)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 14. OPENING RANGE BREAKOUT
# ════════════════════════════════════════════════════════════════════════════
def strat_orb(pair, tf, candles):
    """London open (07:00–08:00 UTC) and NY open (13:00–14:00 UTC) range breakouts."""
    if len(candles)<10 or tf!="M15": return None
    now=datetime.now(timezone.utc); hour=now.hour
    # Only relevant around session opens
    if hour not in (8,9,13,14): return None
    c=C(candles); h=H(candles); l=L(candles)
    pip=P(pair); d=D(pair); price=c[-1]; av=atr(h,l,c) or pip*20
    # First 4 M15 candles of the session = opening range
    orh=max(h[-8:-4]); orl=min(l[-8:-4])
    if orh-orl<pip*5: return None
    inds={"OR_High":round(orh,d),"OR_Low":round(orl,d),"Session":"London" if hour<12 else "New York"}
    if price>orh and c[-1]>c[-2]:
        return sig(pair,tf,"buy",price,price+av*2,orh-av*0.5,"ORB",f"{'London' if hour<12 else 'NY'} open range breakout above {orh:.{d}f}.","medium",inds)
    if price<orl and c[-1]<c[-2]:
        return sig(pair,tf,"sell",price,price-av*2,orl+av*0.5,"ORB",f"{'London' if hour<12 else 'NY'} open range breakdown below {orl:.{d}f}.","medium",inds)
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
TIMEFRAMES = ["M15","H1","H4"]
PAIRS_LIST = ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","GBPJPY","XAUUSD"]

_cd: dict = {}        # cooldown: pair+tf+strategy -> last fire time
_agree_cd: dict = {} # cooldown: pair+tf+direction -> last agreement alert
CD       = 900        # 15-min cooldown per strategy signal
AGREE_CD = 3600       # 1-hour cooldown per agreement alert (avoid spam)
AGREE_THRESHOLD = 3   # how many strategies must agree to trigger the alert


def build_agreement_signal(pair: str, tf: str, direction: str, agreeing: list[dict]) -> dict:
    """
    Build a special high-priority signal when 3+ strategies independently
    agree on the same pair, timeframe, and direction within the same candle.
    Uses the best entry/TP/SL from the agreeing signals (highest R:R).
    """
    best = max(agreeing, key=lambda s: s.get("risk_reward", 0))
    strat_names = [s["strategy"] for s in agreeing]
    is_long = direction == "buy"
    d = D(pair)

    # Collect all TP1s and SLs — use best entry, widest TP, tightest SL
    entries = [s["entry"] for s in agreeing]
    tp1s    = [s["tp1"]   for s in agreeing if s.get("tp1")]
    sls_std = [s.get("sl_standard", s.get("sl", best["entry"])) for s in agreeing]

    entry     = round(sum(entries) / len(entries), d)  # average entry
    tp1       = round(max(tp1s) if is_long else min(tp1s), d) if tp1s else best["tp1"]
    sl        = round(min(sls_std) if is_long else max(sls_std), d)
    tp2       = best.get("tp2")
    rr        = round(abs(tp1 - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0

    return {
        "id":           str(uuid.uuid4())[:8],
        "pair":         pair,
        "timeframe":    tf,
        "type":         direction,
        "entry":        entry,
        "tp1":          tp1,
        "tp2":          tp2,
        "sl_tight":     best.get("sl_tight", sl),
        "sl_standard":  sl,
        "sl_wide":      best.get("sl_wide", sl),
        "strategy":     "⚡ MULTI-STRATEGY AGREEMENT",
        "reason": (
            f"{len(agreeing)} strategies independently agree: "
            f"{', '.join(strat_names)}. "
            f"This is a high-conviction setup — multiple methods confirm the same direction."
        ),
        "strength":     "high",
        "risk_reward":  rr,
        "agreement": {
            "count":      len(agreeing),
            "strategies": strat_names,
            "direction":  direction,
        },
        "indicators":   best.get("indicators", {}),
        "fib_levels":   best.get("fib_levels"),
        "fvg":          best.get("fvg"),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "is_agreement": True,   # flag so frontend/alerts treat it specially
    }


class SignalEngine:
    def evaluate(self, candles_by_pair: dict) -> tuple[list, list]:
        """
        Returns (regular_signals, agreement_signals).
        agreement_signals are fired separately so they can get priority alerts.
        """
        from time import time
        now = time()
        regular_signals: list[dict] = []
        agreement_signals: list[dict] = []

        for pair in PAIRS_LIST:
            for tf in TIMEFRAMES:
                cd = candles_by_pair.get(pair, {}).get(tf, [])
                if len(cd) < 30:
                    continue

                # ── Run every strategy, collect all that fire this candle ──
                this_candle_signals: list[dict] = []

                for fn, name in zip(ALL_STRATS, STRAT_NAMES):
                    key = f"{pair}:{tf}:{name}"
                    if now - _cd.get(key, 0) < CD:
                        continue
                    try:
                        s = fn(pair, tf, cd)
                        if s:
                            regular_signals.append(s)
                            this_candle_signals.append(s)
                            _cd[key] = now
                            log.info(
                                f"SIGNAL [{s['strength'].upper()}] "
                                f"{pair}/{tf} {s['type'].upper()} | {name}"
                            )
                    except Exception as e:
                        log.error(f"{name}/{pair}/{tf}: {e}")

                # ── Check for multi-strategy agreement ──
                if len(this_candle_signals) < AGREE_THRESHOLD:
                    continue

                # Group by direction (buy-side vs sell-side)
                buy_signals  = [s for s in this_candle_signals if s["type"] in ("buy", "buy_limit")]
                sell_signals = [s for s in this_candle_signals if s["type"] in ("sell", "sell_limit")]

                for direction, group in (("buy", buy_signals), ("sell", sell_signals)):
                    if len(group) < AGREE_THRESHOLD:
                        continue

                    agree_key = f"{pair}:{tf}:{direction}:agreement"
                    if now - _agree_cd.get(agree_key, 0) < AGREE_CD:
                        continue

                    agreement = build_agreement_signal(pair, tf, direction, group)
                    agreement_signals.append(agreement)
                    _agree_cd[agree_key] = now

                    log.info(
                        f"🔥 AGREEMENT [{len(group)} strategies] "
                        f"{pair}/{tf} {direction.upper()} — "
                        f"{[s['strategy'] for s in group]}"
                    )

        return regular_signals, agreement_signals
