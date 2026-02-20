# ============================================================
# OKX Spot Trading Bot - Lightweight Version (No Numba)
# ============================================================

import os
import ccxt
import pandas as pd
import ta  # استخدام المكتبة الخفيفة بدلاً من pandas-ta
import asyncio
import logging
import time
import threading
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
from flask import Flask

# ============================================================
# 🌐 إعداد سيرفر Flask
# ============================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 OKX Trading Bot is Running Smoothly! 🚀"

# ============================================================
# ⚙️ الإعدادات والمفاتيح
# ============================================================
config = {
    "okx_api_key":    "4e945e12-ea6a-426a-8272-7caae6e2a1c0",
    "okx_secret_key": "7E546FB45CB7F47BFF76BF8A0720C823",
    "okx_passphrase": "Abdullaheyas123@",
    
    "telegram_token": "8520586890:AAHBkefrtNQjv0bPUtpkWG0gijkXU4K84BY",
    "telegram_chat_id": "7825994636",  
    
    "symbol":          "BTC/USDT",     
    "timeframe":       "15m",          
    "capital_ratio":   0.35,           
    "take_profit_pct": 0.025,          
    "stop_loss_pct":   0.015,          
    "loop_interval":   60,             
    "min_usdt_balance": 10.0,          
}

# ============================================================
# 📊 نظام اللوجينج
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================
# 📡 التليغرام - إرسال الإشعارات 
# ============================================================
async def send_telegram(message: str):
    try:
        bot = Bot(token=config["telegram_token"])
        await bot.send_message(
            chat_id=config["telegram_chat_id"],
            text=message,
            parse_mode="HTML"
        )
    except TelegramError as e:
        logger.error(f"Telegram Error: {e}")

def notify(message: str):
    asyncio.run(send_telegram(message))

# ============================================================
# 🏦 اتصال OKX
# ============================================================
def create_exchange() -> ccxt.okx:
    return ccxt.okx({
        "apiKey":     config["okx_api_key"],
        "secret":     config["okx_secret_key"],
        "password":   config["okx_passphrase"],
        "enableRateLimit": True,
        "options": {"defaultType": "spot"}
    })

# ============================================================
# 📈 جلب البيانات وحساب المؤشرات (معدل للمكتبة الخفيفة)
# ============================================================
def fetch_ohlcv(exchange: ccxt.okx, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        logger.error(f"Error fetching OHLCV: {e}")
        return pd.DataFrame()

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    
    # MACD
    macd = ta.trend.MACD(df["close"], window_fast=12, window_slow=26, window_sign=9)
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    # EMA
    df["ema20"] = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    
    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_mid"]   = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()

    # ATR
    df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
    
    # Volume SMA
    df["vol_sma"] = ta.trend.SMAIndicator(df["volume"], window=20).sma_indicator()
    
    return df

# ============================================================
# 🎯 استراتيجية الدخول والخروج
# ============================================================
def check_buy_signal(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 51:
        return {"signal": False, "reason": "بيانات غير كافية"}
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    rsi_ok = 40 < curr["rsi"] < 62
    macd_cross_up = (prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"] and curr["macd_hist"] > 0)
    macd_strong = (curr["macd"] > curr["macd_signal"] and curr["macd_hist"] > prev["macd_hist"] and curr["macd"] < 0)
    macd_ok = macd_cross_up or macd_strong
    
    ema_ok = (curr["close"] > curr["ema20"] and curr["ema20"] > curr["ema50"])
    bb_ok = curr["bb_mid"] <= curr["close"] <= curr["bb_upper"]
    vol_ok = curr["volume"] > curr["vol_sma"] * 1.2
    
    conditions_met = sum([rsi_ok, macd_ok, ema_ok, bb_ok, vol_ok])
    all_ok = conditions_met >= 4
    
    return {
        "signal": all_ok, 
        "current_price": curr["close"],
        "reason": f"{conditions_met}/5 شروط متحققة"
    }

def check_sell_signal(df: pd.DataFrame, entry_price: float) -> dict:
    if df.empty:
        return {"signal": False}
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    rsi_overbought  = curr["rsi"] > 70
    macd_cross_down = (prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"])
    price_below_ema = curr["close"] < curr["ema20"]
    
    sell_conditions = sum([rsi_overbought, macd_cross_down, price_below_ema])
    return {"signal": sell_conditions >= 2, "current_price": curr["close"]}

# ============================================================
# 💰 إدارة التداول
# ============================================================
def get_spot_balance(exchange: ccxt.okx, currency: str = "USDT") -> float:
    try:
        balance = exchange.fetch_balance({"type": "spot"})
        return float(balance.get(currency, {}).get("free", 0))
    except Exception as e:
        logger.error(f"Balance Error: {e}")
        return 0.0

def calculate_position_size(balance: float, price: float, ratio: float = 0.35) -> float:
    return round((balance * ratio) / price, 6)

def place_buy_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
    try:
        limit_price = round(price * 1.001, 2)
        return exchange.create_order(symbol=symbol, type="limit", side="buy", amount=quantity, price=limit_price, params={"tdMode": "cash"})
    except Exception as e:
        logger.error(f"Buy Order Error: {e}")
        return {}

def place_sell_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
    try:
        limit_price = round(price * 0.999, 2)
        return exchange.create_order(symbol=symbol, type="limit", side="sell", amount=quantity, price=limit_price, params={"tdMode": "cash"})
    except Exception as e:
        logger.error(f"Sell Order Error: {e}")
        return {}

class TradeTracker:
    def __init__(self):
        self.open_trade  = None
        self.trade_history = []
        self.total_pnl   = 0.0
    
    def open(self, symbol, entry_price, quantity, take_profit, stop_loss):
        self.open_trade = {
            "symbol": symbol, "entry_price": entry_price, "quantity": quantity,
            "take_profit": take_profit, "stop_loss": stop_loss
        }
    
    def close(self, exit_price):
        if not self.open_trade: return 0.0
        pnl = (exit_price - self.open_trade["entry_price"]) * self.open_trade["quantity"]
        self.trade_history.append({**self.open_trade, "pnl_usdt": round(pnl, 4)})
        self.total_pnl += pnl
        self.open_trade = None
        return pnl
    
    def check_tp_sl(self, current_price: float) -> str | None:
        if not self.open_trade: return None
        if current_price >= self.open_trade["take_profit"]: return "take_profit"
        if current_price <= self.open_trade["stop_loss"]: return "stop_loss"
        return None

# ============================================================
# 🔄 الحلقة الرئيسية للبوت
# ============================================================
def run_bot():
    exchange = create_exchange()
    tracker  = TradeTracker()
    symbol   = config["symbol"]
    
    notify(f"🤖 <b>تم التشغيل بنجاح</b>\nالزوج: {symbol}\nاستراتيجية: Spot")
    
    while True:
        try:
            df = fetch_ohlcv(exchange, symbol, config["timeframe"], limit=200)
            if df.empty:
                time.sleep(config["loop_interval"])
                continue
            
            df = calculate_indicators(df)
            current_price = df["close"].iloc[-1]
            
            if tracker.open_trade:
                tp_sl = tracker.check_tp_sl(current_price)
                if tp_sl:
                    pnl = tracker.close(current_price)
                    reason_ar = "هدف الربح ✅" if tp_sl == "take_profit" else "وقف الخسارة 🛑"
                    notify(f"{'🟢' if pnl > 0 else '🔴'} <b>صفقة مغلقة - {reason_ar}</b>\nالربح/الخسارة: {pnl:+.4f} USDT")
                else:
                    sell_signal = check_sell_signal(df, tracker.open_trade["entry_price"])
                    if sell_signal["signal"]:
                        order = place_sell_order(exchange, symbol, tracker.open_trade["quantity"], current_price)
                        if order:
                            pnl = tracker.close(current_price)
                            notify(f"🔵 <b>بيع بإشارة تقنية</b>\nالربح/الخسارة: {pnl:+.4f} USDT")
            
            elif not tracker.open_trade:
                buy_signal = check_buy_signal(df)
                if buy_signal["signal"]:
                    balance = get_spot_balance(exchange)
                    if balance >= config["min_usdt_balance"]:
                        qty = calculate_position_size(balance, current_price, config["capital_ratio"])
                        tp = round(current_price * (1 + config["take_profit_pct"]), 4)
                        sl = round(current_price * (1 - config["stop_loss_pct"]), 4)
                        order = place_buy_order(exchange, symbol, qty, current_price)
                        if order:
                            tracker.open(symbol, current_price, qty, tp, sl)
                            notify(f"🟢 <b>صفقة شراء جديدة!</b>\nسعر الدخول: {current_price}\nTP: {tp} | SL: {sl}")
                
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(30)
        
        time.sleep(config["loop_interval"])

# ============================================================
# 🚀 نقطة التشغيل
# ============================================================
if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True 
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
