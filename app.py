"""
🔍 FOREX SCANNER - Scalping Edition (5m / 15m)
تحليل فني متكامل مع تيليجرام و Flask وفحص مستمر
"""

import yfinance as yf
import pandas as pd
import numpy as np
import ta
from colorama import Fore, Style, init
from tabulate import tabulate
from datetime import datetime
import warnings
import telebot
import os
import threading
import time
from flask import Flask

warnings.filterwarnings('ignore')
init(autoreset=True)

# =====================================================
# إعدادات التيليجرام
# =====================================================
TELEGRAM_TOKEN = "8520586890:AAHBkefrtNQjv0bPUtpkWG0gijkXU4K84BY"
TELEGRAM_CHAT_ID = "7825994636"
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")

# =====================================================
# أزواج العملات المراد سكانها
# =====================================================
PAIRS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X",
    "USDCAD=X", "USDCHF=X", "NZDUSD=X", "EURJPY=X",
    "GBPJPY=X", "EURGBP=X", "AUDJPY=X", "EURAUD=X"
]

PAIR_NAMES = {
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY", "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD", "USDCHF=X": "USD/CHF",
    "NZDUSD=X": "NZD/USD", "EURJPY=X": "EUR/JPY",
    "GBPJPY=X": "GBP/JPY", "EURGBP=X": "EUR/GBP",
    "AUDJPY=X": "AUD/JPY", "EURAUD=X": "EUR/AUD"
}

# ذاكرة ذكية لتجنب تكرار نفس الإشارة لنفس الشمعة
last_alerts = {}

# =====================================================
# دالة تحميل البيانات
# =====================================================
def get_data(pair, period="1mo", interval="15m"):
    try:
        df = yf.download(pair, period=period, interval=interval, progress=False)
        if df.empty or len(df) < 50:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.dropna(inplace=True)
        return df
    except:
        return None

# =====================================================
# حساب المؤشرات الفنية
# =====================================================
def add_indicators(df):
    close = df['Close']
    high  = df['High']
    low   = df['Low']

    # RSI
    df['RSI'] = ta.momentum.RSIIndicator(close, window=14).rsi()

    # MACD
    macd = ta.trend.MACD(close)
    df['MACD']        = macd.macd()
    df['MACD_signal'] = macd.macd_signal()
    df['MACD_hist']   = macd.macd_diff()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df['BB_upper'] = bb.bollinger_hband()
    df['BB_lower'] = bb.bollinger_lband()
    
    # EMA
    df['EMA_20']  = ta.trend.EMAIndicator(close, window=20).ema_indicator()
    df['EMA_50']  = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    df['EMA_200'] = ta.trend.EMAIndicator(close, window=200).ema_indicator()

    # Stochastic
    stoch = ta.momentum.StochasticOscillator(high, low, close)
    df['STOCH_K'] = stoch.stoch()
    df['STOCH_D'] = stoch.stoch_signal()

    # ATR
    df['ATR'] = ta.volatility.AverageTrueRange(high, low, close).average_true_range()

    # ADX
    adx = ta.trend.ADXIndicator(high, low, close)
    df['ADX']    = adx.adx()
    df['ADX_pos'] = adx.adx_pos()
    df['ADX_neg'] = adx.adx_neg()

    return df

# =====================================================
# منطق تحليل الإشارة
# =====================================================
def analyze_signal(df):
    df = add_indicators(df)
    df.dropna(inplace=True)

    if len(df) < 10:
        return None

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    close = float(last['Close'])
    atr   = float(last['ATR'])

    buy_score  = 0
    sell_score = 0
    reasons    = []

    # --- RSI ---
    rsi = float(last['RSI'])
    if rsi < 35:
        buy_score += 2
        reasons.append(f"RSI={rsi:.1f} (تشبع بيعي)")
    elif rsi > 65:
        sell_score += 2
        reasons.append(f"RSI={rsi:.1f} (تشبع شرائي)")

    # --- MACD ---
    if float(last['MACD']) > float(last['MACD_signal']) and float(prev['MACD']) <= float(prev['MACD_signal']):
        buy_score += 2
        reasons.append("MACD تقاطع صاعد ✅")
    elif float(last['MACD']) < float(last['MACD_signal']) and float(prev['MACD']) >= float(prev['MACD_signal']):
        sell_score += 2
        reasons.append("MACD تقاطع هابط ✅")

    # --- EMA Trend ---
    ema20  = float(last['EMA_20'])
    ema50  = float(last['EMA_50'])
    ema200 = float(last['EMA_200'])

    if close > ema200:
        buy_score += 1
        if ema20 > ema50:
            buy_score += 1
            reasons.append("السعر فوق EMA200 + EMA20 فوق EMA50 📈")
    else:
        sell_score += 1
        if ema20 < ema50:
            sell_score += 1
            reasons.append("السعر تحت EMA200 + EMA20 تحت EMA50 📉")

    # --- Bollinger Bands ---
    bb_lower = float(last['BB_lower'])
    bb_upper = float(last['BB_upper'])
    if close <= bb_lower:
        buy_score += 2
        reasons.append("السعر عند حد BB السفلي (ارتداد محتمل)")
    elif close >= bb_upper:
        sell_score += 2
        reasons.append("السعر عند حد BB العلوي (ارتداد محتمل)")

    # --- Stochastic ---
    stoch_k = float(last['STOCH_K'])
    stoch_d = float(last['STOCH_D'])
    if stoch_k < 25 and stoch_k > stoch_d:
        buy_score += 1
        reasons.append(f"Stochastic={stoch_k:.1f} منطقة تشبع بيعي مع تقاطع")
    elif stoch_k > 75 and stoch_k < stoch_d:
        sell_score += 1
        reasons.append(f"Stochastic={stoch_k:.1f} منطقة تشبع شرائي مع تقاطع")

    # --- ADX (قوة الترند) ---
    adx = float(last['ADX'])
    adx_pos = float(last['ADX_pos'])
    adx_neg = float(last['ADX_neg'])
    trend_strength = "قوي" if adx > 25 else "ضعيف"
    if adx > 20:
        if adx_pos > adx_neg:
            buy_score += 1
        else:
            sell_score += 1

    # --- تحديد الإشارة ---
    total = buy_score + sell_score
    if total == 0:
        return None

    if buy_score > sell_score and buy_score >= 5:
        signal    = "BUY"
        strength  = min(100, int((buy_score / 10) * 100))
        entry     = close
        sl        = round(close - 1.5 * atr, 5)
        tp1       = round(close + 1.5 * atr, 5)
        tp2       = round(close + 3.0 * atr, 5)
        tp3       = round(close + 4.5 * atr, 5)
    elif sell_score > buy_score and sell_score >= 5:
        signal    = "SELL"
        strength  = min(100, int((sell_score / 10) * 100))
        entry     = close
        sl        = round(close + 1.5 * atr, 5)
        tp1       = round(close - 1.5 * atr, 5)
        tp2       = round(close - 3.0 * atr, 5)
        tp3       = round(close - 4.5 * atr, 5)
    else:
        return None

    rr_ratio = round((abs(tp1 - entry)) / (abs(sl - entry)), 2) if sl != entry else 0

    return {
        "signal":    signal,
        "strength":  strength,
        "entry":     entry,
        "sl":        sl,
        "tp1":       tp1,
        "tp2":       tp2,
        "tp3":       tp3,
        "rr":        rr_ratio,
        "rsi":       round(rsi, 1),
        "adx":       round(adx, 1),
        "trend":     trend_strength,
        "reasons":   reasons,
        "atr":       round(atr, 5)
    }

# =====================================================
# إرسال إلى تيليجرام
# =====================================================
def send_telegram_alert(pair_name, result, timeframe):
    icon = "🟢 BUY" if result['signal'] == "BUY" else "🔴 SELL"
    stars = "⭐" * (result['strength'] // 20)
    
    reasons_text = "\n".join([f"• {r}" for r in result['reasons']])
    
    msg = (
        f"{icon} <b>{pair_name}</b> | {timeframe} Scalp\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💪 <b>قوة الإشارة:</b> {result['strength']}% {stars}\n\n"
        f"📍 <b>سعر الدخول:</b> <code>{result['entry']:.5f}</code>\n"
        f"🛑 <b>وقف الخسارة:</b> <code>{result['sl']:.5f}</code>\n"
        f"🎯 <b>هدف (TP1):</b> <code>{result['tp1']:.5f}</code>\n"
        f"🎯 <b>هدف (TP2):</b> <code>{result['tp2']:.5f}</code>\n"
        f"⚖️ <b>نسبة R:R:</b> <code>1:{result['rr']}</code>\n\n"
        f"📊 <b>مؤشرات:</b>\n"
        f"RSI: {result['rsi']} | ADX: {result['adx']} ({result['trend']})\n\n"
        f"📋 <b>أسباب الإشارة:</b>\n{reasons_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    )
    
    try:
        bot.send_message(TELEGRAM_CHAT_ID, msg)
    except Exception as e:
        print(f"⚠️ فشل الإرسال إلى تيليجرام: {e}")

# =====================================================
# تشغيل السكانر الأساسي
# =====================================================
def run_scanner(timeframe="15m"):
    tf_map = {
        "5m":  ("5d", "5m"),
        "15m": ("1mo", "15m"),
        "1h":  ("3mo", "1h"),
    }
    period, interval = tf_map.get(timeframe, ("1mo", "15m"))

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔍 فحص السوق على فريم {timeframe}...")

    for pair in PAIRS:
        name = PAIR_NAMES.get(pair, pair)
        df = get_data(pair, period=period, interval=interval)
        if df is None:
            continue
        
        # التقاط توقيت آخر شمعة
        last_candle_time = df.index[-1]

        # التحقق: هل أرسلنا إشارة لهذه الشمعة مسبقاً؟
        if pair in last_alerts and last_alerts[pair] == last_candle_time:
            continue # تخطي لأننا أرسلنا إشارة لهذه الشمعة بالفعل
        
        result = analyze_signal(df)
        if result:
            send_telegram_alert(name, result, timeframe)
            # حفظ توقيت الشمعة لعدم تكرار الإشارة
            last_alerts[pair] = last_candle_time
            print(f"✅ تم إرسال إشارة {name} بنجاح.")

# =====================================================
# الحلقة التكرارية (Loop) لتشغيل البوت باستمرار
# =====================================================
def start_bot_loop():
    # ⚙️ إعدادات الفريم ووقت الفحص:
    # لتغييره لـ 5 دقائق، غير القيمة إلى "5m"
    tf = "15m" 
    
    # وقت الانتظار بين كل فحص (بالثواني). 300 ثانية تعني 5 دقائق.
    sleep_time = 300 
    
    bot.send_message(TELEGRAM_CHAT_ID, f"🤖 <b>Scalping Bot is LIVE!</b>\nجاري فحص السوق باستمرار على فريم {tf}...")
    
    while True:
        try:
            run_scanner(timeframe=tf)
        except Exception as e:
            print(f"Error during scan: {e}")
            
        time.sleep(sleep_time)

# =====================================================
# DUMMY WEB SERVER (TO KEEP RENDER ALIVE)
# =====================================================
app = Flask(__name__)

@app.route('/')
def alive():
    return "Scalping Scanner is running perfectly!"

def run_dummy_server():
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# =====================================================
# نقطة التشغيل
# =====================================================
if __name__ == "__main__":
    # تشغيل السيرفر الوهمي
    server_thread = threading.Thread(target=run_dummy_server)
    server_thread.daemon = True
    server_thread.start()
    
    # تشغيل حلقة البوت الأساسية
    start_bot_loop()
