"""
APEX FX - Signal Engine
14 strategies. Clean, no simulation logic.
Called only when MT5 confirms a candle has closed.
"""
import math, uuid, logging
from datetime import datetime, timezone

log = logging.getLogger("apexfx.engine")

DIGITS = {"EURUSD":5,"GBPUSD":5,"AUDUSD":5,"USDCAD":5,"GBPJPY":3,"USDJPY":3,"XAUUSD":2}
PIPS   = {"EURUSD":1e-4,"GBPUSD":1e-4,"AUDUSD":1e-4,"USDCAD":1e-4,"GBPJPY":0.01,"USDJPY":0.01,"XAUUSD":0.1}

def D(p): return DIGITS.get(p,5)
def P(p): return PIPS.get(p,1e-4)

# ── Indicator helpers ──────────────────────────────────────────────────────

def closes(cd): return [c["close"] for c in cd]
def highs(cd):  return [c["high"]  for c in cd]
def lows(cd):   return [c["low"]   for c in cd]
def opens(cd):  return [c["open"]  for c in cd]

def ema(data, n):
    if len(data) < n: return None
    k = 2/(n+1)
    e = sum(data[:n])/n
    for v in data[n:]: e = v*k + e*(1-k)
    return e

def ema_series(data, n):
    if len(data) < n: return []
    k = 2/(n+1)
    out = [sum(data[:n])/n]
    for v in data[n:]: out.append(v*k + out[-1]*(1-k))
    return out

def rsi(data, n=14):
    if len(data) < n+1: return None
    g = sum(max(data[i]-data[i-1],0) for i in range(1,len(data)))
    l = sum(max(data[i-1]-data[i],0) for i in range(1,len(data)))
    ag = g/n; al = l/n
    return round(100-100/(1+ag/al),2) if al else 100.0

def macd(data):
    if len(data) < 35: return None, None, None
    ef = ema_series(data,12); es = ema_series(data,26)
    ml = [ef[len(ef)-len(es)+i]-es[i] for i in range(len(es))]
    if len(ml) < 9: return None, None, None
    sl = ema_series(ml,9)
    return round(ml[-1],8), round(sl[-1],8), round(ml[-1]-sl[-1],8)

def bollinger(data, n=20, k=2.0):
    if len(data) < n: return None, None, None
    w = data[-n:]; m = sum(w)/n
    sd = math.sqrt(sum((x-m)**2 for x in w)/n)
    return round(m+k*sd,6), round(m,6), round(m-k*sd,6)

def stoch(hs, ls, cs, kp=14):
    if len(cs) < kp: return None, None
    hi = max(hs[-kp:]); lo = min(ls[-kp:])
    k  = round(100*(cs[-1]-lo)/(hi-lo),2) if hi != lo else 50.0
    d  = round(sum([100*(cs[-i]-min(ls[-kp-i+1:-i+1] if i>1 else ls[-kp:]))/(max(hs[-kp-i+1:-i+1] if i>1 else hs[-kp:])-min(ls[-kp-i+1:-i+1] if i>1 else ls[-kp:])) for i in range(1,4)])/3,2) if len(cs)>=kp+3 else k
    return k, d

def atr(cd, n=14):
    hs=highs(cd); ls=lows(cd); cs=closes(cd)
    if len(cs)<n+1: return None
    tr=[max(hs[i]-ls[i],abs(hs[i]-cs[i-1]),abs(ls[i]-cs[i-1])) for i in range(1,len(cs))]
    return round(sum(tr[-n:])/n,6)

def pivot_highs(hs, lb=4):
    return [i for i in range(lb,len(hs)-lb) if hs[i]==max(hs[i-lb:i+lb+1])]

def pivot_lows(ls, lb=4):
    return [i for i in range(lb,len(ls)-lb) if ls[i]==min(ls[i-lb:i+lb+1])]

def find_fvgs(cd, lookback=40):
    out=[]; recent=cd[-lookback:]
    for i in range(1,len(recent)-1):
        c1,c3=recent[i-1],recent[i+1]
        if c3["low"]>c1["high"]:
            out.append({"type":"bull","top":c3["low"],"bot":c1["high"]})
        elif c3["high"]<c1["low"]:
            out.append({"type":"bear","top":c1["low"],"bot":c3["high"]})
    return out

def is_bull_candle(cd):
    if len(cd)<2: return False
    c=cd[-1]; p=cd[-2]
    body=abs(c["close"]-c["open"]); rng=c["high"]-c["low"]
    lw=min(c["close"],c["open"])-c["low"]
    if c["close"]>p["close"] and body>0: return True
    if rng>0 and lw>rng*0.55: return True
    return False

def is_bear_candle(cd):
    if len(cd)<2: return False
    c=cd[-1]; p=cd[-2]
    body=abs(c["close"]-c["open"]); rng=c["high"]-c["low"]
    uw=c["high"]-max(c["close"],c["open"])
    if c["close"]<p["close"] and body>0: return True
    if rng>0 and uw>rng*0.55: return True
    return False

def fib_levels(hi, lo):
    r=hi-lo
    return {"0":hi,"23.6":hi-0.236*r,"38.2":hi-0.382*r,"50":hi-0.5*r,
            "61.8":hi-0.618*r,"78.6":hi-0.786*r,"100":lo,"161.8":hi+0.618*r}

def make_sig(pair,tf,stype,entry,tp1,sl,strategy,reason,strength,
             tp2=None,sl_tight=None,sl_wide=None,fib=None,fvg=None,inds=None):
    d=D(pair)
    rr=round(abs(tp1-entry)/abs(entry-sl),2) if abs(entry-sl)>0 else 0
    s={
        "id":str(uuid.uuid4())[:8],"pair":pair,"tf":tf,"type":stype,
        "entry":round(entry,d),"tp1":round(tp1,d),
        "tp2":round(tp2,d) if tp2 else None,
        "sl_tight":round(sl_tight,d) if sl_tight else round(sl,d),
        "sl_standard":round(sl,d),
        "sl_wide":round(sl_wide,d) if sl_wide else round(sl,d),
        "strategy":strategy,"reason":reason,"strength":strength,
        "risk_reward":rr,"indicators":inds or {},
        "ts":datetime.now(timezone.utc).isoformat(),
    }
    if fib: s["fib_levels"]={k:round(v,d) for k,v in fib.items()}
    if fvg: s["fvg"]={k:round(v,d) if isinstance(v,float) else v for k,v in fvg.items()}
    return s

# ── Cooldown tracker ───────────────────────────────────────────────────────
_cd: dict = {}
CD = 900  # 15 minutes per pair/tf/strategy

def _ok(pair,tf,name):
    from time import time
    key=f"{pair}:{tf}:{name}"
    if time()-_cd.get(key,0)<CD: return False
    _cd[key]=time(); return True

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 1 — FIB GOLDEN ZONE + FVG
# ════════════════════════════════════════════════════════════════════════════
def strat_fib(pair,tf,cd):
    if len(cd)<40: return None
    c=closes(cd); h=highs(cd); l=lows(cd)
    price=c[-1]; pip=P(pair); d=D(pair)
    av=atr(cd) or pip*20
    ph=pivot_highs(h,4); pl=pivot_lows(l,4)
    if len(ph)<2 or len(pl)<1: return None

    # ── BULLISH ──
    nhi=ph[-1]; new_hi=h[nhi]
    prior=[i for i in ph if i<nhi]
    if prior:
        btw=[i for i in pl if i>prior[-1] and i<nhi]
        if btw:
            sw_i=min(btw,key=lambda i:l[i]); sw_lo=l[sw_i]
            move=new_hi-sw_lo
            if move>=pip*25 and price<new_hi:
                pb=(new_hi-price)/move
                if 0.25<=pb<=0.95 and price>sw_lo-pip*2:
                    fb=fib_levels(new_hi,sw_lo)
                    f50=fb["50"]; f618=fb["61.8"]; f786=fb["78.6"]
                    gz_lo=min(f50,f618); gz_hi=max(f50,f618)
                    fvgs=[f for f in find_fvgs(cd) if f["type"]=="bull"]
                    fvg_gz=next((f for f in fvgs if f["bot"]<=gz_hi and f["top"]>=gz_lo),None)
                    at_gz=gz_lo<=price<=gz_hi
                    at_dz=fb["78.6"]<=price<=f618

                    if at_gz and c[-1]>=f618 and is_bull_candle(cd):
                        sl=f786-av*0.3
                        reason=f"Fib golden zone {f50:.{d}f}-{f618:.{d}f} — bullish candle confirms. TP={new_hi:.{d}f}."
                        if fvg_gz: reason=f"Golden zone + FVG ({fvg_gz['bot']:.{d}f}-{fvg_gz['top']:.{d}f}) confluence. TP={new_hi:.{d}f}."
                        return make_sig(pair,tf,"buy_limit",f618,new_hi,sl,
                            "Fib Golden Zone + FVG",reason,"high",
                            tp2=fb["161.8"],sl_tight=f618-av*0.2,sl_wide=sw_lo-av*0.3,
                            fib=fb,fvg=fvg_gz)

                    if 0.25<=pb<0.48 and price>gz_hi:
                        return make_sig(pair,tf,"buy_limit",f618,new_hi,f786-av*0.3,
                            "Fib Golden Zone + FVG",
                            f"Pullback {pb*100:.0f}% — BUY LIMIT at 61.8% ({f618:.{d}f}). TP={new_hi:.{d}f}.",
                            "medium",tp2=fb["161.8"],sl_tight=f618-av*0.2,sl_wide=sw_lo-av*0.3,fib=fb)

    # ── BEARISH (mirror) ──
    nli=pl[-1]; new_lo=l[nli]
    prior_l=[i for i in pl if i<nli]
    if prior_l:
        btw=[i for i in ph if i>prior_l[-1] and i<nli]
        if btw:
            sw_i=max(btw,key=lambda i:h[i]); sw_hi=h[sw_i]
            move=sw_hi-new_lo
            if move>=pip*25 and price>new_lo:
                pb=(price-new_lo)/move
                if 0.25<=pb<=0.95 and price<sw_hi+pip*2:
                    fb=fib_levels(sw_hi,new_lo)
                    f50b=new_lo+0.5*move; f618b=new_lo+0.618*move; f786b=new_lo+0.786*move
                    at_gz=min(f50b,f618b)<=price<=max(f50b,f618b)
                    if at_gz and c[-1]<=f618b and is_bear_candle(cd):
                        return make_sig(pair,tf,"sell_limit",f618b,new_lo,f786b+av*0.3,
                            "Fib Golden Zone + FVG",
                            f"Bearish golden zone {f50b:.{d}f}-{f618b:.{d}f}. TP={new_lo:.{d}f}.",
                            "high",tp2=new_lo-0.618*move,sl_tight=f618b+av*0.2,sl_wide=sw_hi+av*0.3)
                    if 0.25<=pb<0.48 and price<min(f50b,f618b):
                        return make_sig(pair,tf,"sell_limit",f618b,new_lo,f786b+av*0.3,
                            "Fib Golden Zone + FVG",
                            f"Bearish pullback {pb*100:.0f}% — SELL LIMIT at 61.8% ({f618b:.{d}f}).",
                            "medium",sl_tight=f618b+av*0.2,sl_wide=sw_hi+av*0.3)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 2 — ICT FVG
# ════════════════════════════════════════════════════════════════════════════
def strat_ict(pair,tf,cd):
    if len(cd)<25: return None
    c=closes(cd); h=highs(cd); l=lows(cd)
    price=c[-1]; pip=P(pair); d=D(pair)
    av=atr(cd) or pip*20
    rsh=max(h[-20:]); rsl=min(l[-20:])
    bos_bull=c[-1]>rsh and c[-2]<=rsh
    bos_bear=c[-1]<rsl and c[-2]>=rsl
    fvgs=find_fvgs(cd,30)
    if bos_bull:
        for f in reversed([x for x in fvgs if x["type"]=="bull"]):
            if f["bot"]<=price<=f["top"] and is_bull_candle(cd):
                return make_sig(pair,tf,"buy_limit",price,rsh+av*2,f["bot"]-av*0.5,
                    "ICT FVG",f"BOS above {rsh:.{d}f}. Price in bullish FVG ({f['bot']:.{d}f}-{f['top']:.{d}f}). Confirmation candle.","high",
                    sl_tight=f["bot"]-av*0.2,sl_wide=f["bot"]-av*1.0,fvg=f)
    if bos_bear:
        for f in reversed([x for x in fvgs if x["type"]=="bear"]):
            if f["bot"]<=price<=f["top"] and is_bear_candle(cd):
                return make_sig(pair,tf,"sell_limit",price,rsl-av*2,f["top"]+av*0.5,
                    "ICT FVG",f"Bearish BOS below {rsl:.{d}f}. Price in bearish FVG. Confirmation candle.","high",
                    sl_tight=f["top"]+av*0.2,sl_wide=f["top"]+av*1.0,fvg=f)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 3 — SUPPLY & DEMAND
# ════════════════════════════════════════════════════════════════════════════
def strat_sd(pair,tf,cd):
    if len(cd)<40: return None
    c=closes(cd); h=highs(cd); l=lows(cd); o=opens(cd)
    price=c[-1]; pip=P(pair); d=D(pair)
    av=atr(cd) or pip*20
    demand=[]; supply=[]
    for i in range(2,len(cd)-3):
        body=abs(c[i]-o[i]); rng=h[i]-l[i]
        if body>av*1.5 and (rng==0 or body/rng>0.6):
            bi=i-1; zt=max(c[bi],o[bi]); zb=min(c[bi],o[bi])
            if zt-zb>=pip*3:
                tests=sum(1 for j in range(i+1,len(cd)) if zb-av*0.3<=c[j]<=zt+av*0.3)
                if c[i]>o[i] and tests<=2: demand.append({"top":zt,"bot":zb,"target":max(h[i:i+3]),"tests":tests})
                if c[i]<o[i] and tests<=2: supply.append({"top":zt,"bot":zb,"target":min(l[i:i+3]),"tests":tests})
    for z in demand[-4:]:
        if z["bot"]<=price<=z["top"]+av*0.3 and is_bull_candle(cd):
            sl=z["bot"]-av*0.8; tp=z["target"]+av
            if tp-price>=(price-sl)*1.8:
                return make_sig(pair,tf,"buy_limit",price,tp,sl,"Supply & Demand",
                    f"Demand zone ({z['bot']:.{d}f}-{z['top']:.{d}f}) test #{z['tests']+1}.",
                    "high" if z["tests"]==0 else "medium",sl_tight=z["bot"]-av*0.3,sl_wide=z["bot"]-av*1.2)
    for z in supply[-4:]:
        if z["bot"]-av*0.3<=price<=z["top"] and is_bear_candle(cd):
            sl=z["top"]+av*0.8; tp=z["target"]-av
            if price-tp>=(sl-price)*1.8:
                return make_sig(pair,tf,"sell_limit",price,tp,sl,"Supply & Demand",
                    f"Supply zone ({z['bot']:.{d}f}-{z['top']:.{d}f}) test #{z['tests']+1}.",
                    "high" if z["tests"]==0 else "medium",sl_tight=z["top"]+av*0.3,sl_wide=z["top"]+av*1.2)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 4 — CANDLESTICK PATTERNS
# ════════════════════════════════════════════════════════════════════════════
def strat_candles(pair,tf,cd):
    if len(cd)<4: return None
    c=closes(cd); h=highs(cd); l=lows(cd); o=opens(cd)
    price=c[-1]; pip=P(pair); d=D(pair)
    av=atr(cd) or pip*20; r=rsi(c); e50=ema(c,50)
    c0=cd[-1]; c1=cd[-2]; c2=cd[-3]
    o0,h0,l0,c_0=c0["open"],c0["high"],c0["low"],c0["close"]
    o1,h1,l1,c_1=c1["open"],c1["high"],c1["low"],c1["close"]
    o2,h2,l2,c_2=c2["open"],c2["high"],c2["low"],c2["close"]
    body0=abs(c_0-o0); rng0=h0-l0
    body1=abs(c_1-o1)
    lw0=min(c_0,o0)-l0; uw0=h0-max(c_0,o0)
    bull0=c_0>o0; bear0=c_0<o0
    bull1=c_1>o1; bear1=c_1<o1

    at_key=False
    if e50 and abs(price-e50)<av*0.8: at_key=True
    for i in pivot_highs(h)[-3:]:
        if abs(price-h[i])<av*0.7: at_key=True
    for i in pivot_lows(l)[-3:]:
        if abs(price-l[i])<av*0.7: at_key=True

    def mk(stype,strength,name,reason):
        is_buy=stype in("buy","buy_limit")
        tp=price+av*2 if is_buy else price-av*2
        sl=price-av*1.2 if is_buy else price+av*1.2
        return make_sig(pair,tf,stype,price,tp,sl,"Candle Patterns",reason,strength,
            inds={"Pattern":name,"RSI":r,"At_Key":at_key})

    if bear1 and bull0 and body0>body1*1.1 and o0<=c_1 and c_0>=o1 and body0>av*0.4 and (r is None or r<65):
        return mk("buy","high","Bullish Engulfing",f"Bullish engulfing at {'key level' if at_key else 'price'}. RSI={r}.")
    if bull1 and bear0 and body0>body1*1.1 and o0>=c_1 and c_0<=o1 and body0>av*0.4 and (r is None or r>35):
        return mk("sell","high","Bearish Engulfing",f"Bearish engulfing. RSI={r}.")
    if lw0>body0*2 and uw0<body0*0.5 and rng0>pip*5 and (r is None or r<50):
        return mk("buy","high","Hammer",f"Hammer — buyers rejected sellers. RSI={r}.")
    if uw0>body0*2 and lw0<body0*0.5 and rng0>pip*5 and (r is None or r>50):
        return mk("sell","high","Shooting Star",f"Shooting star — sellers rejected buyers. RSI={r}.")
    if lw0>rng0*0.58 and body0<rng0*0.35 and rng0>av*0.5 and (r is None or r<50):
        return mk("buy","high","Bullish Pin Bar",f"Bullish pin bar rejection. RSI={r}.")
    if uw0>rng0*0.58 and body0<rng0*0.35 and rng0>av*0.5 and (r is None or r>50):
        return mk("sell","high","Bearish Pin Bar",f"Bearish pin bar rejection. RSI={r}.")
    # Morning star
    bear2=o2>c_2; small1=body1<av*0.4; bull_close=c_0>o0 and c_0>o2+(c_2-o2)*0.5
    if bear2 and small1 and bull_close and (r is None or r<55):
        return mk("buy","high","Morning Star",f"Morning star 3-candle reversal. RSI={r}.")
    # Evening star
    bull2=c_2>o2; bear_close=c_0<o0 and c_0<c_2-(c_2-o2)*0.5
    if bull2 and small1 and bear_close and (r is None or r>45):
        return mk("sell","high","Evening Star",f"Evening star 3-candle reversal. RSI={r}.")
    if bear1 and bull0 and body0<body1*0.6 and o0>c_1 and c_0<o1 and (r is None or r<55):
        return mk("buy","medium","Bullish Harami",f"Bullish harami — momentum slowing. RSI={r}.")
    if bull1 and bear0 and body0<body1*0.6 and o0<c_1 and c_0>o1 and (r is None or r>45):
        return mk("sell","medium","Bearish Harami",f"Bearish harami — momentum slowing. RSI={r}.")
    if r and r<30 and body0<rng0*0.1 and rng0>av*0.5:
        return mk("buy","medium","Doji Oversold",f"Doji at RSI={r} oversold.")
    if r and r>70 and body0<rng0*0.1 and rng0>av*0.5:
        return mk("sell","medium","Doji Overbought",f"Doji at RSI={r} overbought.")
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 5 — RSI + MACD
# ════════════════════════════════════════════════════════════════════════════
def strat_rsimacd(pair,tf,cd):
    c=closes(cd)
    if len(c)<40: return None
    r=rsi(c); mv,ms,mh=macd(c); pmh=macd(c[:-1])[2]
    if None in (r,mh,pmh): return None
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20
    inds={"RSI":r,"MACD_Hist":round(mh,6)}
    if r<32 and mh>0 and pmh<=0:
        return make_sig(pair,tf,"buy",price,price+av*2.2,price-av*1.2,
            "RSI + MACD",f"RSI={r} oversold + MACD histogram bullish cross.","high",inds=inds)
    if r>68 and mh<0 and pmh>=0:
        return make_sig(pair,tf,"sell",price,price-av*2.2,price+av*1.2,
            "RSI + MACD",f"RSI={r} overbought + MACD histogram bearish cross.","high",inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 6 — EMA 50/200 CROSS
# ════════════════════════════════════════════════════════════════════════════
def strat_ema(pair,tf,cd):
    c=closes(cd)
    if len(c)<210: return None
    es=ema_series(c,50); el=ema_series(c,200)
    if len(es)<3 or len(el)<3: return None
    e50n,e50p=es[-1],es[-2]; e200n,e200p=el[-1],el[-2]
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20
    sep=abs(e50n-e200n)
    if sep<pip*2: return None
    inds={"EMA_50":round(e50n,d),"EMA_200":round(e200n,d)}
    if e50p<e200p and e50n>e200n:
        return make_sig(pair,tf,"buy",price,price+av*3,price-av*1.5,
            "EMA 50/200 Cross","Golden Cross — EMA 50 crossed above EMA 200.","high",inds=inds)
    if e50p>e200p and e50n<e200n:
        return make_sig(pair,tf,"sell",price,price-av*3,price+av*1.5,
            "EMA 50/200 Cross","Death Cross — EMA 50 crossed below EMA 200.","high",inds=inds)
    if e50n>e200n and 0<price-e50n<av*0.6 and is_bull_candle(cd):
        return make_sig(pair,tf,"buy_limit",e50n,e50n+av*2.5,e50n-av,
            "EMA 50/200 Cross",f"Bullish trend — BUY LIMIT pullback to EMA50 ({e50n:.{d}f}).","medium",inds=inds)
    if e50n<e200n and 0<e50n-price<av*0.6 and is_bear_candle(cd):
        return make_sig(pair,tf,"sell_limit",e50n,e50n-av*2.5,e50n+av,
            "EMA 50/200 Cross",f"Bearish trend — SELL LIMIT retest of EMA50 ({e50n:.{d}f}).","medium",inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 7 — BOLLINGER BANDS
# ════════════════════════════════════════════════════════════════════════════
def strat_bb(pair,tf,cd):
    c=closes(cd)
    if len(c)<25: return None
    up,mb,lo=bollinger(c)
    if up is None: return None
    price=c[-1]; prev=c[-2]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20
    bw=(up-lo)/mb
    up_p,mb_p,lo_p=bollinger(c[:-1])
    bw_prev=(up_p-lo_p)/mb_p if up_p else bw
    squeeze=bw<bw_prev*0.85 and bw<0.015
    inds={"BB_Up":round(up,d),"BB_Mid":round(mb,d),"BB_Lo":round(lo,d),"Squeeze":squeeze}
    if squeeze:
        bh=up-lo
        if prev<up<=price:
            return make_sig(pair,tf,"buy_stop",price,price+bh,up-av*0.3,
                "Bollinger Breakout",f"BB squeeze breakout above {up:.{d}f}.","high",inds=inds)
        if prev>lo>=price:
            return make_sig(pair,tf,"sell_stop",price,price-bh,lo+av*0.3,
                "Bollinger Breakout",f"BB squeeze breakdown below {lo:.{d}f}.","high",inds=inds)
    if bw>0.004:
        if abs(price-lo)<av*0.4 and price>lo and is_bull_candle(cd):
            return make_sig(pair,tf,"buy_limit",lo,mb,lo-av*0.8,
                "Bollinger Breakout",f"Mean reversion from lower BB ({lo:.{d}f}). TP=mid ({mb:.{d}f}).","medium",inds=inds)
        if abs(price-up)<av*0.4 and price<up and is_bear_candle(cd):
            return make_sig(pair,tf,"sell_limit",up,mb,up+av*0.8,
                "Bollinger Breakout",f"Mean reversion from upper BB ({up:.{d}f}). TP=mid ({mb:.{d}f}).","medium",inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 8 — SUPPORT & RESISTANCE
# ════════════════════════════════════════════════════════════════════════════
def strat_sr(pair,tf,cd):
    c=closes(cd); h=highs(cd); l=lows(cd)
    if len(c)<50: return None
    ph=pivot_highs(h,4); pl=pivot_lows(l,4)
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20; r=rsi(c)
    zone=av*0.7
    def tests(level):
        return sum(1 for cd2 in cd[-40:] if abs(cd2["close"]-level)<av*0.5)
    for i in pl[-5:]:
        sup=l[i]
        if abs(price-sup)<zone and price>sup:
            t=tests(sup)
            if 2<=t<=5 and is_bull_candle(cd) and (r is None or r<55):
                nr=min((h[i] for i in ph if h[i]>price+av),default=price+av*3)
                sl=sup-av*0.8
                if nr-price>=(price-sl)*1.8:
                    return make_sig(pair,tf,"buy_limit",price,nr,sl,
                        "S/R Bounce",f"Support bounce at {sup:.{d}f} (test #{t}). RSI={r}.",
                        "high" if (r and r<35) else "medium",sl_tight=sup-av*0.3,sl_wide=sup-av*1.3)
    for i in ph[-5:]:
        res=h[i]
        if abs(price-res)<zone and price<res:
            t=tests(res)
            if 2<=t<=5 and is_bear_candle(cd) and (r is None or r>45):
                ns=max((l[i] for i in pl if l[i]<price-av),default=price-av*3)
                sl=res+av*0.8
                if price-ns>=(sl-price)*1.8:
                    return make_sig(pair,tf,"sell_limit",price,ns,sl,
                        "S/R Bounce",f"Resistance rejection at {res:.{d}f} (test #{t}). RSI={r}.",
                        "high" if (r and r>65) else "medium",sl_tight=res+av*0.3,sl_wide=res+av*1.3)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 9 — STOCHASTIC
# ════════════════════════════════════════════════════════════════════════════
def strat_stoch(pair,tf,cd):
    c=closes(cd); h=highs(cd); l=lows(cd)
    if len(c)<25: return None
    k,dv=stoch(h,l,c)
    if k is None: return None
    kp,dp=stoch(h[:-1],l[:-1],c[:-1])
    if kp is None: return None
    e50=ema(c,50); price=c[-1]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20
    trend_up=price>e50 if e50 else True
    cross_str=abs(k-dv)
    if cross_str<2: return None
    inds={"Stoch_K":k,"Stoch_D":dv}
    if kp<dp and k>dv and k<20 and trend_up:
        return make_sig(pair,tf,"buy",price,price+av*2,price-av*1.2,
            "Stochastic",f"%K({k}) crossed %D({dv}) in oversold zone. Trend bullish.","high",inds=inds)
    if kp>dp and k<dv and k>80 and not trend_up:
        return make_sig(pair,tf,"sell",price,price-av*2,price+av*1.2,
            "Stochastic",f"%K({k}) crossed %D({dv}) in overbought zone. Trend bearish.","high",inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 10 — TRENDLINE BREAKOUT
# ════════════════════════════════════════════════════════════════════════════
def strat_trendline(pair,tf,cd):
    if len(cd)<35: return None
    c=closes(cd); h=highs(cd); l=lows(cd)
    price=c[-1]; prev=c[-2]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20; r=rsi(c)
    ph=pivot_highs(h,4); pl=pivot_lows(l,4)
    if len(ph)<2 or len(pl)<2: return None
    # Descending trendline → bull breakout
    ph1,ph2=ph[-2],ph[-1]
    if ph2>ph1:
        slope=(h[ph2]-h[ph1])/(ph2-ph1)
        tl=h[ph2]+slope*(len(c)-1-ph2)
        touches=sum(1 for i in range(ph1,ph2) if abs(h[i]-(h[ph1]+slope*(i-ph1)))<av*0.6)
        if touches>=1 and prev<tl<=price and (r is None or r<68):
            return make_sig(pair,tf,"buy_stop",price,price+av*2.5,tl-av,
                "Trendline Breakout",f"Broke above descending trendline ({tl:.{d}f}). RSI={r}.","high",
                sl_tight=tl-av*0.4,sl_wide=tl-av*1.5)
    # Ascending trendline → bear breakout
    pl1,pl2=pl[-2],pl[-1]
    if pl2>pl1:
        slope=(l[pl2]-l[pl1])/(pl2-pl1)
        tl=l[pl2]+slope*(len(c)-1-pl2)
        touches=sum(1 for i in range(pl1,pl2) if abs(l[i]-(l[pl1]+slope*(i-pl1)))<av*0.6)
        if touches>=1 and prev>tl>=price and (r is None or r>32):
            return make_sig(pair,tf,"sell_stop",price,price-av*2.5,tl+av,
                "Trendline Breakout",f"Broke below ascending trendline ({tl:.{d}f}). RSI={r}.","high",
                sl_tight=tl+av*0.4,sl_wide=tl+av*1.5)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 11 — MULTI-CONFLUENCE
# ════════════════════════════════════════════════════════════════════════════
def strat_confluence(pair,tf,cd):
    c=closes(cd); h=highs(cd); l=lows(cd)
    if len(c)<60: return None
    r=rsi(c) or 50; _,_,mh=macd(c); e50=ema(c,50); e200=ema(c,200)
    kv,_=stoch(h,l,c); _,mb,_=bollinger(c)
    if None in (mh,e50,e200,kv,mb): return None
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20
    bull=sum([r<40, mh>0, e50>e200, kv<40, price<mb])
    bear=sum([r>60, mh<0, e50<e200, kv>60, price>mb])
    inds={"RSI":r,"MACD":round(mh,7),"Bull":bull,"Bear":bear}
    if bull>=4:
        s="high" if (bull==5 or (bull==4 and e50>e200)) else "medium"
        return make_sig(pair,tf,"buy",price,price+av*3,price-av*1.5,
            "Multi-Confluence",f"{bull}/5 indicators bullish. RSI={r}.","high" if bull==5 else s,inds=inds)
    if bear>=4:
        s="high" if (bear==5 or (bear==4 and e50<e200)) else "medium"
        return make_sig(pair,tf,"sell",price,price-av*3,price+av*1.5,
            "Multi-Confluence",f"{bear}/5 indicators bearish. RSI={r}.","high" if bear==5 else s,inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 12 — CARRY MOMENTUM (H4 only)
# ════════════════════════════════════════════════════════════════════════════
def strat_carry(pair,tf,cd):
    if tf!="H4": return None
    if pair not in ("AUDUSD","GBPUSD","EURUSD","GBPJPY","USDJPY"): return None
    c=closes(cd)
    if len(c)<100: return None
    e20=ema(c,20); e50=ema(c,50); e100=ema(c,100)
    if not all([e20,e50,e100]): return None
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20; r=rsi(c)
    inds={"EMA_20":round(e20,d),"EMA_50":round(e50,d),"EMA_100":round(e100,d),"RSI":r}
    if e20>e50>e100 and price>e20 and r and 40<r<68:
        return make_sig(pair,tf,"buy",price,price+av*2.5,price-av*1.2,
            "Carry Momentum",f"H4 EMA stack bullish. RSI={r}.","medium",inds=inds)
    if e20<e50<e100 and price<e20 and r and 32<r<60:
        return make_sig(pair,tf,"sell",price,price-av*2.5,price+av*1.2,
            "Carry Momentum",f"H4 EMA stack bearish. RSI={r}.","medium",inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 13 — SCALP BREAKOUT (M15/H1 only)
# ════════════════════════════════════════════════════════════════════════════
def strat_scalp(pair,tf,cd):
    if tf not in ("M15","H1"): return None
    if len(cd)<20: return None
    c=closes(cd); h=highs(cd); l=lows(cd)
    price=c[-1]; pip=P(pair); d=D(pair)
    av14=atr(cd,14) or pip*15
    h8=h[-9:-1]; l8=l[-9:-1]; c8=c[-9:-1]
    if len(c8)<6: return None
    av8=atr(cd[-9:-1],min(6,len(cd[-9:-1])-1)) or pip*10
    if av8>av14*0.65: return None
    ch=max(h8); cl=min(l8)
    last_rng=h[-1]-l[-1]
    if last_rng<av8*1.8: return None
    inds={"Cons_Hi":round(ch,d),"Cons_Lo":round(cl,d)}
    if price>ch and c[-1]>c[-2]:
        return make_sig(pair,tf,"buy_stop",price,price+av14*1.5,ch-pip*3,
            "Scalp Breakout",f"Consolidation breakout above {ch:.{d}f}. BUY STOP.","medium",inds=inds)
    if price<cl and c[-1]<c[-2]:
        return make_sig(pair,tf,"sell_stop",price,price-av14*1.5,cl+pip*3,
            "Scalp Breakout",f"Consolidation breakdown below {cl:.{d}f}. SELL STOP.","medium",inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 14 — ORB (M15 only)
# ════════════════════════════════════════════════════════════════════════════
def strat_orb(pair,tf,cd):
    if tf!="M15": return None
    if len(cd)<10: return None
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc); hour=now.hour
    if hour not in (8,9,10,13,14,15): return None
    c=closes(cd); h=highs(cd); l=lows(cd)
    price=c[-1]; pip=P(pair); d=D(pair); av=atr(cd) or pip*20
    orh=max(h[-8:-4]); orl=min(l[-8:-4])
    rs=orh-orl
    if rs>pip*60 or rs<pip*8: return None
    sess="London" if hour<12 else "New York"
    inds={"OR_Hi":round(orh,d),"OR_Lo":round(orl,d),"Range_pips":round(rs/pip,1)}
    if price>orh and c[-1]>c[-2]:
        return make_sig(pair,tf,"buy_stop",price,price+rs,orh-av*0.5,
            "ORB",f"{sess} opening range breakout above {orh:.{d}f}. BUY STOP.","medium",inds=inds)
    if price<orl and c[-1]<c[-2]:
        return make_sig(pair,tf,"sell_stop",price,price-rs,orl+av*0.5,
            "ORB",f"{sess} opening range breakdown below {orl:.{d}f}. SELL STOP.","medium",inds=inds)
    return None

# ════════════════════════════════════════════════════════════════════════════
# ENGINE
# ════════════════════════════════════════════════════════════════════════════
STRATS = [
    ("Fib Golden Zone + FVG", strat_fib),
    ("ICT FVG",               strat_ict),
    ("Supply & Demand",       strat_sd),
    ("Candle Patterns",       strat_candles),
    ("RSI + MACD",            strat_rsimacd),
    ("EMA 50/200 Cross",      strat_ema),
    ("Bollinger Breakout",    strat_bb),
    ("S/R Bounce",            strat_sr),
    ("Stochastic",            strat_stoch),
    ("Trendline Breakout",    strat_trendline),
    ("Multi-Confluence",      strat_confluence),
    ("Carry Momentum",        strat_carry),
    ("Scalp Breakout",        strat_scalp),
    ("ORB",                   strat_orb),
]

class SignalEngine:

    def evaluate_pair(self, pair: str, tf: str, all_candles: dict) -> list:
        """
        Called when MT5 confirms a candle closed on pair/tf.
        Runs all 14 strategies on that pair/tf.
        Returns filtered, non-conflicting signals.
        """
        cd = all_candles.get(pair, {}).get(tf, [])
        if len(cd) < 25:
            log.warning(f"Not enough candles for {pair}/{tf}: {len(cd)}")
            return []

        raw = []
        for name, fn in STRATS:
            if not _ok(pair, tf, name):
                continue
            try:
                s = fn(pair, tf, cd)
                if s:
                    raw.append(s)
                    log.info(f"Signal: [{s['strength'].upper()}] {pair}/{tf} {s['type'].upper()} | {name}")
            except Exception as e:
                log.error(f"{name}/{pair}/{tf}: {e}")

        return self._filter(raw)

    def _filter(self, signals: list) -> list:
        """
        Remove conflicting signals — if BUY and SELL fire on same
        pair+tf, keep only the higher conviction one.
        """
        groups: dict = {}
        for s in signals:
            key = f"{s['pair']}:{s['tf']}"
            groups.setdefault(key, []).append(s)

        result = []
        for group in groups.values():
            if len(group) == 1:
                result.append(group[0])
                continue
            buys  = [s for s in group if "buy"  in s["type"]]
            sells = [s for s in group if "sell" in s["type"]]
            if buys and sells:
                # Conflict — keep higher R:R side
                best_buy  = max(buys,  key=lambda s: s.get("risk_reward", 0))
                best_sell = max(sells, key=lambda s: s.get("risk_reward", 0))
                rsi_val = (best_buy.get("indicators",{}).get("RSI") or
                           best_sell.get("indicators",{}).get("RSI"))
                if rsi_val:
                    result.append(best_buy if rsi_val < 50 else best_sell)
                else:
                    result.append(best_buy if best_buy.get("risk_reward",0) >=
                                  best_sell.get("risk_reward",0) else best_sell)
            else:
                result.extend(buys or sells)

        return result
