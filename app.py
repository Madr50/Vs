"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         OKX SPOT TRADING BOT — Ultra-Lightweight Sniper Edition              ║
║         Target: Render Free Tier (0.1 CPU / 512 MB RAM)                      ║
║         Strategy: RSI Oversold + EMA Cross + Volume Surge + ATR SL/TP        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Standard library ──────────────────────────────────────────────────────────

import gc
import io
import logging
import time
from datetime import datetime

# ── Third-party ───────────────────────────────────────────────────────────────

import ccxt
import matplotlib
matplotlib.use("Agg")  # Headless backend — MUST be set before any other mpl import
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import telebot

# ═════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

API_KEY        = "4e945e12-ea6a-426a-8272-7caae6e2a1c0"
API_SECRET     = "7E546FB45CB7F47BFF76BF8A0720C823"
API_PASSPHRASE = "Abdullaheyas123@"

TELEGRAM_TOKEN   = "8520586890:AAHBkefrtNQjv0bPUtpkWG0gijkXU4K84BY"
TELEGRAM_CHAT_ID = "7825994636"

# ── Scanning ──────────────────────────────────────────────────────────────────

TIMEFRAME     = "15m"          # 5m or 15m
CANDLE_LIMIT  = 100            # keep RAM low
MAX_PRICE     = 1.00           # only sub-$1 coins
MAX_PAIRS     = 60             # cap pairs scanned per cycle
SCAN_SLEEP    = 60             # seconds between cycles

# ── Indicator parameters ──────────────────────────────────────────────────────

RSI_PERIOD       = 14
RSI_OVERSOLD     = 33          # strict threshold
EMA_FAST         = 9
EMA_SLOW         = 21
ATR_PERIOD       = 14
ATR_SL_MULT      = 1.5         # SL  = entry − ATR × multiplier
ATR_TP_MULT      = 3.0         # TP  = entry + ATR × multiplier
MIN_RR           = 1.8         # minimum reward-to-risk to fire a signal
VOL_SURGE_MULT   = 1.3         # last candle volume > N × rolling average

# ═════════════════════════════════════════════════════════════════════════════
# CLIENTS
# ═════════════════════════════════════════════════════════════════════════════

exchange = ccxt.okx(
    {
        "apiKey":   API_KEY,
        "secret":   API_SECRET,
        "password": API_PASSPHRASE,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    }
)

tg = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")

# ═════════════════════════════════════════════════════════════════════════════
# PURE-PANDAS INDICATOR HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_l = loss.ewm(com=period - 1, min_periods=period).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c  = c.shift(1)
    tr = pd.concat(
        [h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()

def _macd(close: pd.Series):
    """Returns (macd_line, signal_line)."""
    fast   = _ema(close, 12)
    slow   = _ema(close, 26)
    macd   = fast - slow
    signal = _ema(macd, 9)
    return macd, signal

# ═════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═════════════════════════════════════════════════════════════════════════════

def fetch_ohlcv(symbol: str) -> pd.DataFrame | None:
    """Fetch OHLCV candles and return a clean DataFrame, or None on failure."""
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
    except Exception as exc:
        log.debug("fetch_ohlcv(%s) error: %s", symbol, exc)
        return None

    if not raw or len(raw) < EMA_SLOW + ATR_PERIOD + 5:
        return None

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df.astype(float)
    return df

# ═════════════════════════════════════════════════════════════════════════════
# SIGNAL ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def analyse(df: pd.DataFrame):
    """
    Compute all indicators and evaluate confluence.
    Returns a dict with trade details, or None if no valid signal.
    """
    close = df["close"]

    # ── Indicators ────────────────────────────────────────────────────────────
    rsi       = _rsi(close, RSI_PERIOD)
    ema_fast  = _ema(close, EMA_FAST)
    ema_slow  = _ema(close, EMA_SLOW)
    atr       = _atr(df, ATR_PERIOD)
    macd, sig = _macd(close)

    # ── Last two candles ──────────────────────────────────────────────────────
    last, prev = df.iloc[-1], df.iloc[-2]

    rsi_now  = rsi.iloc[-1]
    ema_f_n, ema_f_p = ema_fast.iloc[-1], ema_fast.iloc[-2]
    ema_s_n, ema_s_p = ema_slow.iloc[-1], ema_slow.iloc[-2]
    macd_n,  sig_n   = macd.iloc[-1],     sig.iloc[-1]
    macd_p,  sig_p   = macd.iloc[-2],     sig.iloc[-2]
    atr_val  = atr.iloc[-1]
    entry    = last["close"]

    # ── Guard against zero / NaN ──────────────────────────────────────────────
    if any(pd.isna([rsi_now, atr_val, macd_n, sig_n])):
        return None
    if atr_val == 0 or entry == 0:
        return None

    # ── Volume surge ──────────────────────────────────────────────────────────
    vol_avg   = df["volume"].iloc[-20:-1].mean()
    vol_surge = (last["volume"] > vol_avg * VOL_SURGE_MULT) if vol_avg > 0 else False

    # ── EMA golden cross (fast crosses above slow) ────────────────────────────
    ema_cross = (ema_f_p <= ema_s_p) and (ema_f_n > ema_s_n)
    ema_above = ema_f_n > ema_s_n        # fast already above slow

    # ── MACD cross above signal ───────────────────────────────────────────────
    macd_cross = (macd_p <= sig_p) and (macd_n > sig_n)

    # ── Bullish body ──────────────────────────────────────────────────────────
    bullish_body = last["close"] > last["open"]

    # ══════════════════════════════════════════════════════════════════════════
    #  CONFLUENCE GATE — ALL conditions must pass
    # ══════════════════════════════════════════════════════════════════════════
    cond_rsi    = rsi_now < RSI_OVERSOLD
    cond_trend  = ema_cross or (ema_above and macd_cross)
    cond_vol    = vol_surge
    cond_candle = bullish_body

    if not (cond_rsi and cond_trend and cond_vol and cond_candle):
        return None

    # ── SL / TP ───────────────────────────────────────────────────────────────
    sl = round(entry - ATR_SL_MULT * atr_val, 8)
    tp = round(entry + ATR_TP_MULT * atr_val, 8)

    if sl >= entry or tp <= entry or sl <= 0:
        return None

    risk   = entry - sl
    reward = tp - entry
    rr     = round(reward / risk, 2)

    if rr < MIN_RR:
        return None

    profit_pct = round((reward / entry) * 100, 2)

    return {
        "entry":      entry,
        "tp":         tp,
        "sl":         sl,
        "rr":         rr,
        "profit_pct": profit_pct,
        "rsi":        round(rsi_now, 1),
        "atr":        atr_val,
    }

# ═════════════════════════════════════════════════════════════════════════════
# CHARTING
# ═════════════════════════════════════════════════════════════════════════════

def build_chart(df: pd.DataFrame, symbol: str, entry: float, tp: float, sl: float) -> io.BytesIO:
    """
    Build a minimal mplfinance candlestick chart with Entry / TP / SL
    horizontal lines. Returns an in-memory PNG buffer.
    """
    plot_df = df[["open", "high", "low", "close", "volume"]].iloc[-60:].copy()

    hlines = dict(
        hlines=[entry, tp, sl],
        colors=["#00BFFF", "#00FF88", "#FF4444"],
        linestyle="--",
        linewidths=(1.2, 1.2, 1.2),
    )

    mc    = mpf.make_marketcolors(up="#00FF88", down="#FF4444", inherit=True)
    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mc,
        gridstyle=":",
        gridcolor="#2a2a2a",
    )

    buf = io.BytesIO()
    fig, _ = mpf.plot(
        plot_df,
        type="candle",
        style=style,
        title=f"\n{symbol}  |  {TIMEFRAME}  |  Sniper Entry",
        ylabel="Price (USDT)",
        volume=True,
        hlines=hlines,
        figsize=(10, 6),
        returnfig=True,
        warn_too_much_data=200,
    )

    import matplotlib.patches as mpatches
    patches = [
        mpatches.Patch(color="#00BFFF", label=f"Entry  {entry}"),
        mpatches.Patch(color="#00FF88", label=f"TP     {tp}"),
        mpatches.Patch(color="#FF4444", label=f"SL     {sl}"),
    ]
    fig.axes[0].legend(
        handles=patches, loc="upper left",
        fontsize=8, facecolor="#1a1a2e", labelcolor="white", framealpha=0.8,
    )

    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    buf.seek(0)

    plt.close("all")
    del fig, plot_df
    gc.collect()

    return buf

# ═════════════════════════════════════════════════════════════════════════════
# TELEGRAM DISPATCH
# ═════════════════════════════════════════════════════════════════════════════

def send_signal(symbol: str, sig: dict, chart_buf: io.BytesIO) -> None:
    """Send the trade signal text + chart to Telegram."""
    caption = (
        f"🎯 <b>SNIPER ENTRY DETECTED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair:</b>    <code>{symbol}</code>\n"
        f"🟢 <b>Entry:</b>   <code>{sig['entry']}</code>\n"
        f"🎯 <b>TP:</b>      <code>{sig['tp']}</code>\n"
        f"🛑 <b>SL:</b>      <code>{sig['sl']}</code>\n"
        f"📈 <b>Profit:</b>  <code>{sig['profit_pct']}%</code>\n"
        f"⚖️ <b>R:R:</b>     <code>1 : {sig['rr']}</code>\n"
        f"📊 <b>RSI:</b>     <code>{sig['rsi']}</code>\n"
        f"⏱️ <b>Type:</b>    Fast Scalp\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )

    try:
        tg.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=chart_buf,
            caption=caption,
        )
        log.info("✅  Signal sent → %s  |  TP %.6f  |  SL %.6f  |  RR 1:%.2f",
                 symbol, sig["tp"], sig["sl"], sig["rr"])
    except Exception as exc:
        log.warning("Telegram send_photo failed: %s", exc)
        try:
            tg.send_message(TELEGRAM_CHAT_ID, caption)
        except Exception as exc2:
            log.error("Telegram send_message also failed: %s", exc2)

# ═════════════════════════════════════════════════════════════════════════════
# PAIR SCANNER
# ═════════════════════════════════════════════════════════════════════════════

def get_target_pairs() -> list[str]:
    """Return USDT spot pairs under MAX_PRICE."""
    try:
        tickers = exchange.fetch_tickers()
    except Exception as exc:
        log.warning("fetch_tickers failed: %s", exc)
        return []

    candidates = []
    for symbol, t in tickers.items():
        if not symbol.endswith("/USDT"):
            continue
        last = t.get("last") or 0
        vol  = t.get("quoteVolume") or 0
        if 0 < last < MAX_PRICE and vol > 0:
            candidates.append((symbol, vol))

    candidates.sort(key=lambda x: x[1], reverse=True)
    pairs = [s for s, _ in candidates[:MAX_PAIRS]]
    log.info("🔍  Scanning %d pairs (price < $%.2f)", len(pairs), MAX_PRICE)
    return pairs

# ═════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("🤖  OKX Sniper Bot started")

    try:
        tg.send_message(
            TELEGRAM_CHAT_ID,
            "🤖 <b>OKX Sniper Bot is LIVE</b>\n"
            f"Scanning sub-$1 USDT pairs on {TIMEFRAME} every {SCAN_SLEEP}s.\n"
            "Waiting for high-confluence setups… 🎯",
        )
    except Exception as exc:
        log.warning("Startup ping failed: %s", exc)

    alerted_this_cycle: set[str] = set()

    while True:
        cycle_start = time.time()

        if not alerted_this_cycle:
            log.info("♻️  Alert dedup cache cleared")
        alerted_this_cycle = set()

        pairs = get_target_pairs()

        for symbol in pairs:
            if symbol in alerted_this_cycle:
                continue

            df = fetch_ohlcv(symbol)
            if df is None:
                continue

            try:
                result = analyse(df)
            except Exception as exc:
                log.debug("analyse(%s) exception: %s", symbol, exc)
                result = None

            if result is None:
                del df
                gc.collect()
                continue

            try:
                chart = build_chart(df, symbol, result["entry"], result["tp"], result["sl"])
            except Exception as exc:
                log.warning("build_chart(%s) failed: %s", symbol, exc)
                plt.close("all")
                del df
                gc.collect()
                continue

            send_signal(symbol, result, chart)
            alerted_this_cycle.add(symbol)

            del df, chart, result
            gc.collect()

            time.sleep(0.5)

        elapsed = time.time() - cycle_start
        sleep_for = max(0, SCAN_SLEEP - elapsed)
        log.info(
            "✅  Cycle complete in %.1fs | signals sent: %d | sleeping %.0fs",
            elapsed, len(alerted_this_cycle), sleep_for,
        )
        time.sleep(sleep_for)

if __name__ == "__main__":
    main()
