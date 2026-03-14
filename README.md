# APEX FX — Signal Platform
### 14 Strategies · 7 Pairs · M15/H1/H4 · Free Forever

---

## What It Does
Monitors forex markets 24/7 (even when your PC is off) and sends instant **Telegram messages + emails** when a trading signal fires.

**Signals include:** pair, timeframe, direction (BUY/SELL/BUY LIMIT/SELL LIMIT), entry price, TP1, TP2, 3 SL options, risk/reward ratio, and the reason behind the signal.

**Trade management alerts:** move SL to break-even (when 1:1 hit), TP1 hit, TP2 hit, SL hit.

**Journal:** every signal logged, tap WIN/LOSS to track your results.

---

## 14 Strategies

| # | Strategy | Type |
|---|----------|------|
| ⭐ | **Fibonacci Golden Zone + FVG** | Fib retracement to golden zone (50–61.8%), FVG detection inside the zone |
| 2 | ICT Fair Value Gap | BOS detection + FVG rebalancing (ICT method) |
| 3 | Supply & Demand Zones | Sam Seiden institutional zone method |
| 4 | Candlestick Patterns | 16 patterns: Engulfing, Pin Bar, Hammer, Morning/Evening Star, Doji, Harami, Marubozu, Three Soldiers/Crows, Shooting Star |
| 5 | RSI + MACD | RSI oversold/overbought + MACD histogram crossover |
| 6 | EMA 50/200 Cross | Golden Cross / Death Cross + pullback entries |
| 7 | Bollinger Breakout | Band breakout + mean reversion limits |
| 8 | S/R Bounce | Pivot-based support/resistance levels |
| 9 | Stochastic | %K/%D cross in oversold/overbought zones |
| 10 | Trendline Breakout | Descending/ascending trendline breaks |
| 11 | Multi-Confluence | Signals only when 4+/5 indicators agree |
| 12 | Carry Momentum | EMA 20/50/100 stack trend continuation |
| 13 | Scalp Breakout | Tight consolidation expansion |
| 14 | ORB | London + New York opening range breakout |

---

## Pairs & Timeframes
**EUR/USD · GBP/USD · USD/JPY · AUD/USD · USD/CAD · GBP/JPY · XAU/USD**
Each scanned on **M15, H1, H4** every candle close.

---

## Free Deployment (20 minutes, no credit card)

### Step 1 — Get the code on GitHub
1. Go to **github.com** → sign up free → click **+** → **New repository**
2. Name it `apexfx` → click **Create repository**
3. Click **uploading an existing file** → drag and drop the entire `apexfx` folder
4. Click **Commit changes**

### Step 2 — Deploy on Render (free hosting)
1. Go to **render.com** → sign up free (use your GitHub account)
2. Click **New +** → **Web Service**
3. Connect your GitHub account → select the `apexfx` repository
4. Render auto-detects the `render.yaml` file — click **Apply**
5. Your app deploys. Takes ~2 minutes.
6. Copy your app URL (e.g. `https://apexfx.onrender.com`) — **bookmark this**

### Step 3 — Telegram Bot (5 minutes)
1. Open Telegram → search **@BotFather** → send `/newbot`
2. Follow the prompts → it gives you a **Bot Token** (looks like `123456:ABCdef...`)
3. Message your new bot (search its username) — send any message
4. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Find `"chat"` → `"id"` in the response — that's your **Chat ID**

### Step 4 — Gmail App Password (3 minutes)
1. Go to **myaccount.google.com** → Security → 2-Step Verification (enable if not on)
2. Go back to Security → **App Passwords**
3. Select app: Mail → device: Other → type "APEXFX" → click Generate
4. Copy the **16-character password**

### Step 5 — Add credentials to Render
1. In Render, go to your `apexfx` service → **Environment**
2. Add these variables one by one:

| Variable | Value |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from Step 3 |
| `TELEGRAM_CHAT_ID` | Your chat ID from Step 3 |
| `SMTP_USER` | Your Gmail address |
| `SMTP_PASS` | The 16-char app password from Step 4 |
| `ALERT_EMAIL` | Your Gmail address |
| `TWELVE_DATA_API_KEY` | *(optional)* From twelvedata.com free signup |

3. Click **Save Changes** → Render restarts automatically

### Step 6 — Keep it awake (free)
Render's free tier sleeps after 15 minutes of no traffic. Fix it:
1. Go to **uptimerobot.com** → sign up free
2. Click **Add New Monitor** → HTTP(s)
3. URL: `https://your-app-name.onrender.com/api/health`
4. Interval: **5 minutes**
5. Click **Create Monitor**

Done. Your platform now runs 24/7, even when your PC is off.

---

## Running Locally (optional)
```bash
cd backend
pip install -r requirements.txt
cp ../deploy/.env.example .env  # fill in your credentials
uvicorn main:app --reload
```
Open: http://localhost:8000

---

## Project Structure
```
apexfx/
├── backend/
│   ├── main.py           # FastAPI server + WebSocket
│   ├── price_feed.py     # Twelve Data API + simulation
│   ├── signal_engine.py  # All 14 strategies
│   ├── alerts.py         # Telegram + email formatting + dispatch
│   ├── trade_tracker.py  # BE/TP1/TP2/SL monitoring
│   ├── database.py       # SQLite journal + signal history
│   └── requirements.txt
├── frontend/
│   └── index.html        # Full dashboard (works standalone too)
└── deploy/
    ├── render.yaml       # One-click Render deploy config
    └── .env.example      # All credentials documented
```

---

## Disclaimer
Algorithmic signals for informational purposes only. Apply your own risk management. Forex involves substantial risk. Not financial advice.
