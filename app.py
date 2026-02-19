#!/usr/bin/env python3
"""
Elite OKX Spot Trading Bot
Quant-grade scalp/swing signal engine with SMC, RSI Divergence,
Volume Profile, Selenium sentiment scraping, and Telegram alerts.
"""

import os, time, gc, logging, traceback, io, math
from datetime import datetime, timezone

import ccxt
import numpy as np
import pandas as pd
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")          # non-interactive backend – no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import telebot
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ─────────────────────────────────────────────
# 0.  CONFIGURATION
# ─────────────────────────────────────────────
OKX_API_KEY    = "4e945e12-ea6a-426a-8272-7caae6e2a1c0"
OKX_SECRET_KEY = "7E546FB45CB7F47BFF76BF8A0720C823"
OKX_PASSPHRASE = "PLACEHOLDER_FOR_OKX_PASSPHRASE"   # ← replace before deploy

TG_TOKEN   = "8520586890:AAHBkefrtNQjv0bPUtpkWG0gijkXU4K84BY"
TG_CHAT_ID = "7825994636"

TRADE_AMOUNT_USD  = 100          # virtual position size for profit calc
MAX_PRICE_USD     = 1.00         # only coins priced < $1
TIMEFRAME         = "5m"
CANDLE_LIMIT      = 200          # candles pulled per symbol
SCAN_INTERVAL_SEC = 300          # 5 min between full scans
TOP_VOLUME_N      = 30           # how many cheap coins to analyse deeply
CHART_PNG         = "/tmp/signal_chart.png"

# Risk parameters
TP_MULT           = 2.0          # TP = entry ± (ATR * TP_MULT)
SL_MULT           = 1.0          # SL = entry ∓ (ATR * SL_MULT)
MIN_RR            = 1.8          # minimum reward : risk ratio
MIN_SCORE         = 6            # confluence score gate (max ~10)

# ─────────────────────────────────────────────
# 1.  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

# ─────────────────────────────────────────────
# 2.  EXCHANGE
# ─────────────────────────────────────────────
def make_exchange() -> ccxt.okx:
    ex = ccxt.okx({
        "apiKey":     OKX_API_KEY,
        "secret":     OKX_SECRET_KEY,
        "password":   OKX_PASSPHRASE,
        "enableRateLimit": True,
        "options":    {"defaultType": "spot"},
    })
    return ex

# ─────────────────────────────────────────────
# 3.  TELEGRAM
# ─────────────────────────────────────────────
bot = telebot.TeleBot(TG_TOKEN, parse_mode="HTML")

def tg_send_text(msg: str):
    try:
        bot.send_message(TG_CHAT_ID, msg, parse_mode="HTML")
    except Exception as e:
        log.error(f"TG text error: {e}")

def tg_send_photo(path: str, caption: str):
    try:
        with open(path, "rb") as f:
            bot.send_photo(TG_CHAT_ID, f, caption=caption, parse_mode="HTML")
    except Exception as e:
        log.error(f"TG photo error: {e}")

# ─────────────────────────────────────────────
# 4.  SELENIUM (headless Chromium, ultra-low RAM)
# ─────────────────────────────────────────────
def make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-translate")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument("--mute-audio")
    opts.add_argument("--no-first-run")
    opts.add_argument("--safebrowsing-disable-auto-update")
    opts.add_argument("--js-flags=--max-old-space-size=64")
    opts.add_argument("--memory-pressure-off")
    opts.add_argument("--single-process")
    opts.add_argument("--window-size=1024,768")
    prefs = {
        "profile.managed_default_content_settings.images": 2,  # block images
        "profile.default_content_setting_values.notifications": 2,
    }
    opts.add_experimental_option("prefs", prefs)
    # Render/Debian path
    chromium_paths = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
    ]
    binary = next((p for p in chromium_paths if os.path.exists(p)), None)
    if binary:
        opts.binary_location = binary
    driver_paths = [
        "/usr/bin/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
    ]
    driver_bin = next((p for p in driver_paths if os.path.exists(p)), "chromedriver")
    svc = Service(executable_path=driver_bin)
    return webdriver.Chrome(service=svc, options=opts)

def scrape_fear_greed() -> dict:
    """
    Scrape the Crypto Fear & Greed index from alternative.me.
    Returns {"value": int, "label": str} or None on failure.
    Lightweight JSON endpoint – no Selenium needed here.
    """
    try:
        r = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=10
        )
        d = r.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception as e:
        log.warning(f"Fear/Greed scrape failed: {e}")
        return {"value": 50, "label": "Neutral"}

def scrape_coinglass_sentiment(driver: webdriver.Chrome, symbol_base: str) -> float:
    """
    Attempt to get long/short ratio from CoinGlass for the base asset.
    Returns float in range [-1, 1]:
        +1 = extreme longs (bearish contrarian signal)
        -1 = extreme shorts (bullish contrarian signal)
        0  = neutral / failed to parse
    NOTE: CoinGlass DOM changes frequently; this is best-effort.
    """
    score = 0.0
    try:
        url = f"https://www.coinglass.com/LongShort"
        driver.get(url)
        wait = WebDriverWait(driver, 8)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        time.sleep(2)
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 3:
                text = cells[0].text.upper()
                if symbol_base.upper() in text:
                    long_pct_text = cells[1].text.replace("%", "").strip()
                    try:
                        long_pct = float(long_pct_text)
                        # >60% longs = crowd is long = bearish contrarian
                        # <40% longs = crowd is short = bullish contrarian
                        score = (long_pct - 50) / 50   # normalised to [-1,1]
                    except ValueError:
                        pass
                    break
    except (TimeoutException, WebDriverException) as e:
        log.warning(f"CoinGlass scrape timeout/error for {symbol_base}: {e}")
    except Exception as e:
        log.warning(f"CoinGlass scrape unexpected: {e}")
    return score

# ─────────────────────────────────────────────
# 5.  TECHNICAL INDICATORS
# ─────────────────────────────────────────────
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds RSI, ATR, EMA20/50/200, VWAP (session), Bollinger Bands,
    Volume Z-score, MACD, and rolling pivot highs/lows.
    """
    c = df["close"].values
    h = df["high"].values
    lo = df["low"].values
    v = df["volume"].values
    n = len(df)

    # ── RSI ──────────────────────────────────────
    def _rsi(src, period=14):
        deltas = np.diff(src)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_g  = np.full(len(src), np.nan)
        avg_l  = np.full(len(src), np.nan)
        avg_g[period] = gains[:period].mean()
        avg_l[period] = losses[:period].mean()
        for i in range(period + 1, len(src)):
            avg_g[i] = (avg_g[i-1] * (period-1) + gains[i-1]) / period
            avg_l[i] = (avg_l[i-1] * (period-1) + losses[i-1]) / period
        rs  = np.where(avg_l == 0, np.inf, avg_g / avg_l)
        rsi = 100 - (100 / (1 + rs))
        rsi[:period] = np.nan
        return rsi

    df["rsi"] = _rsi(c)

    # ── ATR ──────────────────────────────────────
    def _atr(h, lo, c, period=14):
        tr = np.maximum(h[1:] - lo[1:],
             np.maximum(np.abs(h[1:] - c[:-1]),
                        np.abs(lo[1:] - c[:-1])))
        atr = np.full(n, np.nan)
        atr[period] = tr[:period].mean()
        for i in range(period+1, n):
            atr[i] = (atr[i-1] * (period-1) + tr[i-1]) / period
        return atr

    df["atr"] = _atr(h, lo, c)

    # ── EMA ──────────────────────────────────────
    def _ema(src, period):
        k   = 2 / (period + 1)
        ema = np.full(len(src), np.nan)
        start = period - 1
        ema[start] = src[:period].mean()
        for i in range(start+1, len(src)):
            ema[i] = src[i] * k + ema[i-1] * (1 - k)
        return ema

    df["ema20"]  = _ema(c, 20)
    df["ema50"]  = _ema(c, 50)
    df["ema200"] = _ema(c, 200)

    # ── MACD ─────────────────────────────────────
    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    macd_line   = ema12 - ema26
    signal_line = _ema(np.where(np.isnan(macd_line), 0, macd_line), 9)
    df["macd"]       = macd_line
    df["macd_sig"]   = signal_line
    df["macd_hist"]  = macd_line - signal_line

    # ── Bollinger Bands ───────────────────────────
    period_bb = 20
    rolling_mean = pd.Series(c).rolling(period_bb).mean().values
    rolling_std  = pd.Series(c).rolling(period_bb).std(ddof=0).values
    df["bb_mid"]  = rolling_mean
    df["bb_up"]   = rolling_mean + 2 * rolling_std
    df["bb_low"]  = rolling_mean - 2 * rolling_std
    df["bb_pct"]  = (c - df["bb_low"].values) / (df["bb_up"].values - df["bb_low"].values + 1e-12)

    # ── VWAP (rolling 50-bar session approximation) ──
    tp        = (h + lo + c) / 3
    cum_vol   = pd.Series(v).rolling(50).sum().values
    cum_tpvol = pd.Series(tp * v).rolling(50).sum().values
    df["vwap"] = cum_tpvol / (cum_vol + 1e-12)

    # ── Volume Z-score ────────────────────────────
    v_roll_mean = pd.Series(v).rolling(20).mean().values
    v_roll_std  = pd.Series(v).rolling(20).std(ddof=0).values
    df["vol_z"]  = (v - v_roll_mean) / (v_roll_std + 1e-12)

    # ── Pivot Swing Highs / Lows (5-bar) ─────────
    sw_h = [np.nan] * n
    sw_l = [np.nan] * n
    for i in range(5, n - 5):
        if h[i] == max(h[i-5:i+6]):
            sw_h[i] = h[i]
        if lo[i] == min(lo[i-5:i+6]):
            sw_l[i] = lo[i]
    df["swing_high"] = sw_h
    df["swing_low"]  = sw_l

    return df

# ─────────────────────────────────────────────
# 6.  SMC DETECTION
# ─────────────────────────────────────────────
def detect_order_blocks(df: pd.DataFrame) -> list:
    """
    Bearish OB: last down-candle before a strong up-move.
    Bullish OB: last up-candle before a strong down-move.
    Returns list of {"type": "bull"|"bear", "top": float, "bot": float, "idx": int}
    """
    obs = []
    atr = df["atr"].iloc[-1]
    for i in range(5, len(df) - 5):
        # Bullish OB
        if (df["close"].iloc[i] < df["open"].iloc[i] and      # down candle
            df["close"].iloc[i+1] > df["open"].iloc[i+1] and  # followed by up
            (df["close"].iloc[i+1] - df["open"].iloc[i+1]) > atr):  # strong
            obs.append({
                "type": "bull",
                "top":  df["open"].iloc[i],
                "bot":  df["close"].iloc[i],
                "idx":  i,
            })
        # Bearish OB
        if (df["close"].iloc[i] > df["open"].iloc[i] and
            df["close"].iloc[i+1] < df["open"].iloc[i+1] and
            (df["open"].iloc[i+1] - df["close"].iloc[i+1]) > atr):
            obs.append({
                "type": "bear",
                "top":  df["close"].iloc[i],
                "bot":  df["open"].iloc[i],
                "idx":  i,
            })
    return obs[-10:]  # keep only recent

def detect_liquidity_sweep(df: pd.DataFrame) -> dict:
    """
    Checks last 5 candles for a wick that swept a recent pivot high/low
    then closed back inside range → liquidity grab.
    """
    result = {"bull_sweep": False, "bear_sweep": False}
    sw_lows  = df["swing_low"].dropna()
    sw_highs = df["swing_high"].dropna()
    if sw_lows.empty or sw_highs.empty:
        return result

    recent_low  = sw_lows.iloc[-1]
    recent_high = sw_highs.iloc[-1]
    last5 = df.tail(5)

    for _, row in last5.iterrows():
        # Wick below recent swing low, closed above → bullish sweep
        if row["low"] < recent_low and row["close"] > recent_low:
            result["bull_sweep"] = True
        # Wick above recent swing high, closed below → bearish sweep
        if row["high"] > recent_high and row["close"] < recent_high:
            result["bear_sweep"] = True
    return result

def detect_rsi_divergence(df: pd.DataFrame) -> dict:
    """
    Bullish divergence : price makes lower low, RSI makes higher low.
    Bearish divergence : price makes higher high, RSI makes lower high.
    Looks at last 50 bars.
    """
    out = {"bull_div": False, "bear_div": False}
    w = df.tail(50).copy()
    lows  = w["swing_low"].dropna()
    highs = w["swing_high"].dropna()
    rsi   = w["rsi"]

    if len(lows) >= 2:
        i1, i2 = lows.index[-2], lows.index[-1]
        if lows[i2] < lows[i1] and rsi[i2] > rsi[i1]:
            out["bull_div"] = True

    if len(highs) >= 2:
        i1, i2 = highs.index[-2], highs.index[-1]
        if highs[i2] > highs[i1] and rsi[i2] < rsi[i1]:
            out["bear_div"] = True

    return out

def volume_profile_poc(df: pd.DataFrame, bins: int = 30) -> float:
    """
    Point of Control: price level with the most volume (rough histogram).
    """
    lo = df["low"].min()
    hi = df["high"].max()
    if hi == lo:
        return df["close"].iloc[-1]
    edges  = np.linspace(lo, hi, bins + 1)
    vols   = np.zeros(bins)
    for _, row in df.iterrows():
        for b in range(bins):
            if row["low"] <= edges[b+1] and row["high"] >= edges[b]:
                overlap = (min(row["high"], edges[b+1]) - max(row["low"], edges[b]))
                if overlap > 0:
                    span = row["high"] - row["low"] + 1e-12
                    vols[b] += row["volume"] * (overlap / span)
    poc_idx = int(np.argmax(vols))
    return float((edges[poc_idx] + edges[poc_idx+1]) / 2)

# ─────────────────────────────────────────────
# 7.  SIGNAL SCORING ENGINE
# ─────────────────────────────────────────────
def score_signal(df: pd.DataFrame,
                 obs: list,
                 sweep: dict,
                 divs: dict,
                 poc: float,
                 fear_greed: dict,
                 ls_ratio_score: float) -> dict:
    """
    Returns {"direction": "LONG"|"SHORT"|None, "score": int, "reasons": list,
             "entry": float, "tp": float, "sl": float}
    Max score ≈ 10.
    """
    last    = df.iloc[-1]
    atr     = last["atr"]
    rsi     = last["rsi"]
    close   = last["close"]
    reasons = []
    bull_pts = 0
    bear_pts = 0

    if np.isnan(atr) or atr == 0:
        return {"direction": None, "score": 0, "reasons": [], "entry": 0, "tp": 0, "sl": 0}

    # 1) Trend via EMA stack ──────────────────────
    if last["ema20"] > last["ema50"] > last["ema200"]:
        bull_pts += 1; reasons.append("✅ EMA bullish stack")
    elif last["ema20"] < last["ema50"] < last["ema200"]:
        bear_pts += 1; reasons.append("✅ EMA bearish stack")

    # 2) Price vs VWAP ────────────────────────────
    if close > last["vwap"]:
        bull_pts += 1; reasons.append("✅ Price above VWAP")
    else:
        bear_pts += 1; reasons.append("✅ Price below VWAP")

    # 3) RSI extreme ──────────────────────────────
    if rsi < 35:
        bull_pts += 1; reasons.append(f"✅ RSI oversold ({rsi:.1f})")
    elif rsi > 65:
        bear_pts += 1; reasons.append(f"✅ RSI overbought ({rsi:.1f})")

    # 4) RSI Divergence ───────────────────────────
    if divs["bull_div"]:
        bull_pts += 2; reasons.append("✅ Bullish RSI divergence")
    if divs["bear_div"]:
        bear_pts += 2; reasons.append("✅ Bearish RSI divergence")

    # 5) Liquidity sweep ──────────────────────────
    if sweep["bull_sweep"]:
        bull_pts += 2; reasons.append("✅ Bullish liquidity sweep")
    if sweep["bear_sweep"]:
        bear_pts += 2; reasons.append("✅ Bearish liquidity sweep")

    # 6) MACD momentum ────────────────────────────
    if last["macd_hist"] > 0 and df["macd_hist"].iloc[-2] < 0:
        bull_pts += 1; reasons.append("✅ MACD bullish crossover")
    elif last["macd_hist"] < 0 and df["macd_hist"].iloc[-2] > 0:
        bear_pts += 1; reasons.append("✅ MACD bearish crossover")

    # 7) Bollinger position ───────────────────────
    if last["bb_pct"] < 0.1:
        bull_pts += 1; reasons.append("✅ Price at lower Bollinger Band")
    elif last["bb_pct"] > 0.9:
        bear_pts += 1; reasons.append("✅ Price at upper Bollinger Band")

    # 8) Volume spike ─────────────────────────────
    if last["vol_z"] > 2.0:
        reasons.append(f"✅ Volume spike (z={last['vol_z']:.1f})")
        # adds to whichever direction leads
        if bull_pts >= bear_pts:
            bull_pts += 1
        else:
            bear_pts += 1

    # 9) Order Block confluence ───────────────────
    for ob in obs:
        if ob["type"] == "bull" and ob["bot"] <= close <= ob["top"] * 1.02:
            bull_pts += 1; reasons.append(f"✅ Price in Bullish OB zone ({ob['bot']:.6f}-{ob['top']:.6f})")
            break
        if ob["type"] == "bear" and ob["bot"] * 0.98 <= close <= ob["top"]:
            bear_pts += 1; reasons.append(f"✅ Price in Bearish OB zone ({ob['bot']:.6f}-{ob['top']:.6f})")
            break

    # 10) PoC magnetism ───────────────────────────
    poc_proximity = abs(close - poc) / (atr + 1e-12)
    if poc_proximity < 1.0:
        reasons.append(f"✅ Near Volume PoC ({poc:.6f})")
        if bull_pts >= bear_pts:
            bull_pts += 1
        else:
            bear_pts += 1

    # 11) Fear & Greed (contrarian) ───────────────
    fg = fear_greed["value"]
    if fg < 25:   # extreme fear → bullish
        bull_pts += 1; reasons.append(f"✅ Extreme Fear (FG={fg}) – contrarian long")
    elif fg > 75: # extreme greed → bearish
        bear_pts += 1; reasons.append(f"✅ Extreme Greed (FG={fg}) – contrarian short")

    # 12) Long/Short ratio (contrarian) ──────────
    if ls_ratio_score > 0.3:   # crowd is very long → bearish
        bear_pts += 1; reasons.append(f"✅ Crowd very long – contrarian short")
    elif ls_ratio_score < -0.3: # crowd is very short → bullish
        bull_pts += 1; reasons.append(f"✅ Crowd very short – contrarian long")

    # ── Decision ──────────────────────────────────
    direction = None
    score     = 0
    entry = tp = sl = 0.0

    if bull_pts > bear_pts and bull_pts >= MIN_SCORE:
        direction = "LONG"
        score     = bull_pts
        entry     = close
        tp        = entry + TP_MULT * atr
        sl        = entry - SL_MULT * atr
    elif bear_pts > bull_pts and bear_pts >= MIN_SCORE:
        direction = "SHORT"
        score     = bear_pts
        entry     = close
        tp        = entry - TP_MULT * atr
        sl        = entry + SL_MULT * atr

    # R:R gate
    if direction:
        risk   = abs(entry - sl)
        reward = abs(tp - entry)
        if risk == 0 or (reward / risk) < MIN_RR:
            direction = None   # reject low-quality setup

    return {
        "direction": direction,
        "score":     score,
        "reasons":   reasons,
        "entry":     entry,
        "tp":        tp,
        "sl":        sl,
    }

# ─────────────────────────────────────────────
# 8.  CHART
# ─────────────────────────────────────────────
def draw_chart(df: pd.DataFrame, sig: dict, symbol: str):
    """
    Saves candlestick chart with Entry / TP / SL lines to CHART_PNG.
    Uses the last 80 candles to keep the plot readable and RAM-light.
    """
    try:
        plot_df = df.tail(80).copy()
        plot_df.index = pd.DatetimeIndex(plot_df.index)
        plot_df = plot_df[["open", "high", "low", "close", "volume"]]

        entry = sig["entry"]
        tp    = sig["tp"]
        sl    = sig["sl"]

        hlines_vals   = [entry, tp, sl]
        hlines_colors = ["blue", "green", "red"]
        hlines_styles = ["--", "-", "-"]
        hlines_widths = [1.2, 1.5, 1.5]

        hlines = dict(
            hlines=hlines_vals,
            colors=hlines_colors,
            linestyle=hlines_styles,
            linewidths=hlines_widths,
        )

        # EMA lines
        ep20  = df["ema20"].tail(80).values
        ep50  = df["ema50"].tail(80).values
        ap20  = mpf.make_addplot(ep20,  color="orange",  width=0.8, label="EMA20")
        ap50  = mpf.make_addplot(ep50,  color="purple",  width=0.8, label="EMA50")
        ap_bb_up  = mpf.make_addplot(df["bb_up"].tail(80).values,  color="gray", width=0.5, linestyle="--")
        ap_bb_low = mpf.make_addplot(df["bb_low"].tail(80).values, color="gray", width=0.5, linestyle="--")

        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            facecolor="#0d1117",
            edgecolor="#30363d",
            figcolor="#0d1117",
        )

        fig, axes = mpf.plot(
            plot_df,
            type="candle",
            style=style,
            title=f"\n{symbol}  |  {TIMEFRAME}  |  {sig['direction']}  (score={sig['score']})",
            volume=True,
            hlines=hlines,
            addplot=[ap20, ap50, ap_bb_up, ap_bb_low],
            returnfig=True,
            figsize=(12, 7),
            tight_layout=True,
        )

        ax = axes[0]
        ax.annotate(f"Entry {entry:.6f}",  xy=(1.002, entry), xycoords=("axes fraction","data"), color="blue",  fontsize=7, va="center")
        ax.annotate(f"TP    {tp:.6f}",    xy=(1.002, tp),    xycoords=("axes fraction","data"), color="green", fontsize=7, va="center")
        ax.annotate(f"SL    {sl:.6f}",    xy=(1.002, sl),    xycoords=("axes fraction","data"), color="red",   fontsize=7, va="center")

        legend_patches = [
            mpatches.Patch(color="blue",  label=f"Entry  {entry:.6f}"),
            mpatches.Patch(color="green", label=f"TP     {tp:.6f}"),
            mpatches.Patch(color="red",   label=f"SL     {sl:.6f}"),
        ]
        ax.legend(handles=legend_patches, loc="upper left", fontsize=7,
                  facecolor="#161b22", edgecolor="#30363d", labelcolor="white")

        fig.savefig(CHART_PNG, dpi=100, bbox_inches="tight", facecolor="#0d1117")
        plt.close("all")
        gc.collect()
        return True
    except Exception as e:
        log.error(f"Chart error: {e}")
        plt.close("all")
        gc.collect()
        return False

# ─────────────────────────────────────────────
# 9.  TELEGRAM ALERT
# ─────────────────────────────────────────────
def send_alert(symbol: str, sig: dict, fear_greed: dict):
    entry  = sig["entry"]
    tp     = sig["tp"]
    sl     = sig["sl"]
    direct = sig["direction"]

    pct_profit = abs(tp - entry) / entry * 100
    usd_profit = TRADE_AMOUNT_USD * (pct_profit / 100)
    pct_risk   = abs(sl - entry) / entry * 100
    rr         = pct_profit / (pct_risk + 1e-9)
    emoji      = "🟢" if direct == "LONG" else "🔴"

    reasons_text = "\n".join(f"  {r}" for r in sig["reasons"])

    msg = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>🚨 NEW SIGNAL DETECTED</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"\n"
        f"🪙 <b>Pair:</b>  <code>{symbol}</code>\n"
        f"{emoji} <b>Direction:</b>  <code>{direct}</code>\n"
        f"⏱️ <b>Trade Type:</b>  Fast Scalp ({TIMEFRAME})\n"
        f"\n"
        f"🟢 <b>Entry Price:</b>  <code>${entry:.8f}</code>\n"
        f"🎯 <b>Take Profit:</b>  <code>${tp:.8f}</code>\n"
        f"🛑 <b>Stop Loss:</b>    <code>${sl:.8f}</code>\n"
        f"\n"
        f"📈 <b>Expected Profit:</b>  <code>{pct_profit:.2f}%</code>\n"
        f"💵 <b>Profit on $100:</b>   <code>${usd_profit:.2f} USD</code>\n"
        f"⚠️ <b>Risk:</b>             <code>{pct_risk:.2f}%</code>\n"
        f"⚖️ <b>R:R Ratio:</b>        <code>{rr:.2f}</code>\n"
        f"🧠 <b>Confluence Score:</b> <code>{sig['score']}</code>\n"
        f"\n"
        f"😱 <b>Fear & Greed:</b>  <code>{fear_greed['value']} – {fear_greed['label']}</code>\n"
        f"\n"
        f"<b>📋 Signal Reasons:</b>\n{reasons_text}\n"
        f"\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"⚡ Bot by Elite Quant Engine"
    )

    caption = f"{emoji} {symbol} {direct} | TP: ${tp:.8f} | SL: ${sl:.8f}"

    if os.path.exists(CHART_PNG):
        tg_send_photo(CHART_PNG, caption)
    tg_send_text(msg)

# ─────────────────────────────────────────────
# 10.  MARKET SCAN
# ─────────────────────────────────────────────
def get_cheap_usdt_pairs(ex: ccxt.okx) -> list:
    """
    Fetch tickers, filter USDT spot pairs with price < $1.
    Sort by 24h quoteVolume descending, return top N.
    """
    log.info("Fetching tickers …")
    tickers = ex.fetch_tickers()
    pairs   = []
    for sym, t in tickers.items():
        if not sym.endswith("/USDT"):
            continue
        if t.get("last") is None or t["last"] <= 0:
            continue
        if t["last"] >= MAX_PRICE_USD:
            continue
        qv = t.get("quoteVolume") or 0
        pairs.append((sym, qv))
    pairs.sort(key=lambda x: x[1], reverse=True)
    selected = [p[0] for p in pairs[:TOP_VOLUME_N]]
    log.info(f"Found {len(selected)} cheap USDT pairs (top {TOP_VOLUME_N} by volume)")
    return selected

def fetch_ohlcv(ex: ccxt.okx, symbol: str) -> pd.DataFrame | None:
    try:
        raw = ex.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
        if len(raw) < 100:
            return None
        df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df.set_index("ts", inplace=True)
        df = df.astype(float)
        return df
    except Exception as e:
        log.warning(f"OHLCV fetch failed for {symbol}: {e}")
        return None

# ─────────────────────────────────────────────
# 11.  MAIN LOOP
# ─────────────────────────────────────────────
def main():
    log.info("🚀  Elite OKX Trading Bot starting …")
    tg_send_text("🤖 <b>OKX Scalp Bot Online</b> – scanning market every 5 minutes …")

    ex     = make_exchange()
    driver = None
    alerted_this_cycle: set = set()

    while True:
        cycle_start = time.time()
        log.info("═" * 50)
        log.info("NEW SCAN CYCLE")
        log.info("═" * 50)

        try:
            # ── Selenium driver (create fresh each cycle to avoid RAM leak) ──
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            driver = None
            try:
                driver = make_driver()
                log.info("Selenium driver ready")
            except Exception as e:
                log.warning(f"Selenium init failed: {e} – will skip web scraping this cycle")

            # ── Macro sentiment ─────────────────────────────────────────────
            fear_greed = scrape_fear_greed()
            log.info(f"Fear & Greed: {fear_greed['value']} ({fear_greed['label']})")

            # ── Market scan ──────────────────────────────────────────────────
            symbols = get_cheap_usdt_pairs(ex)
            alerted_this_cycle.clear()

            for symbol in symbols:
                if symbol in alerted_this_cycle:
                    continue

                try:
                    df = fetch_ohlcv(ex, symbol)
                    if df is None:
                        continue

                    df = compute_indicators(df)

                    # Check last candle has valid indicators
                    if df["rsi"].isna().iloc[-1] or df["atr"].isna().iloc[-1]:
                        continue

                    obs    = detect_order_blocks(df)
                    sweep  = detect_liquidity_sweep(df)
                    divs   = detect_rsi_divergence(df)
                    poc    = volume_profile_poc(df)

                    # Selenium scrape (symbol base e.g. "BTC" from "BTC/USDT")
                    base   = symbol.split("/")[0]
                    ls_score = 0.0
                    if driver:
                        ls_score = scrape_coinglass_sentiment(driver, base)

                    sig = score_signal(df, obs, sweep, divs, poc, fear_greed, ls_score)

                    if sig["direction"]:
                        log.info(f"✨ SIGNAL: {symbol} {sig['direction']} score={sig['score']}")
                        drew = draw_chart(df, sig, symbol)
                        send_alert(symbol, sig, fear_greed)
                        alerted_this_cycle.add(symbol)
                    else:
                        log.debug(f"  {symbol}: no signal (bull={0}, score={sig['score']})")

                    # ── Free memory aggressively ─────────────────────────────
                    del df, obs, sweep, divs, poc, sig
                    gc.collect()

                except ccxt.RateLimitExceeded:
                    log.warning("Rate limit hit – sleeping 30s")
                    time.sleep(30)
                except ccxt.NetworkError as e:
                    log.warning(f"Network error on {symbol}: {e}")
                    time.sleep(5)
                except Exception as e:
                    log.error(f"Error processing {symbol}: {e}")
                    log.debug(traceback.format_exc())

                time.sleep(0.3)   # gentle pacing between symbols

        except Exception as e:
            log.error(f"Outer loop error: {e}")
            log.debug(traceback.format_exc())
        finally:
            try:
                if driver:
                    driver.quit()
                    driver = None
            except Exception:
                pass
            gc.collect()

        elapsed = time.time() - cycle_start
        sleep_t = max(10, SCAN_INTERVAL_SEC - elapsed)
        log.info(f"Cycle done in {elapsed:.0f}s. Next scan in {sleep_t:.0f}s …")
        time.sleep(sleep_t)

# ─────────────────────────────────────────────
if __name__ == "__main__":
    main()
