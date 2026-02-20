# ============================================================
# OKX Spot Trading Bot - Scalping Version (Enhanced)
# ============================================================

import os
import ccxt
import pandas as pd
import ta
import logging
import time
import threading
import requests
from datetime import datetime
from flask import Flask

# ============================================================
# 🌐 Flask Server
# ============================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 OKX Trading Bot (Scalping Mode) is Running! 🚀"

# ============================================================
# ⚙️ Config - الإعدادات مع المفاتيح المدمجة
# ============================================================
config = {
    "okx_api_key":      "4e945e12-ea6a-426a-8272-7caae6e2a1c0",
    "okx_secret_key":   "7E546FB45CB7F47BFF76BF8A0720C823",
    "okx_passphrase":   "Abdullaheyas123@",
    
    "telegram_token":   "8520586890:AAHBkefrtNQjv0bPUtpkWG0gijkXU4K84BY",
    "telegram_chat_id": "7825994636",

    "symbol":           "BTC/USDT",
    "timeframe":        "3m",           # 3 دقائق للسكالبينج الحاد
    "capital_ratio":    0.30,           # 30% من الرصيد لكل صفقة
    "take_profit_pct":  0.008,          # 0.8% هدف ربح
    "stop_loss_pct":    0.004,          # 0.4% وقف خسارة - نسبة 1:2
    "fee_rate":         0.001,          # 0.1% رسوم OKX per side
    "loop_interval":    20,             # فحص كل 20 ثانية
    "min_usdt_balance": 10.0,
    "order_timeout":    30,             # ثوانٍ لانتظار تنفيذ الأوردر
    "min_signal_score": 4,              # حد أدنى للإشارة 
}

# ============================================================
# 📊 Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================
# 📡 Telegram (Sync - بدون asyncio مشاكل)
# ============================================================
def notify(message: str):
    try:
        url = f"https://api.telegram.org/bot{config['telegram_token']}/sendMessage"
        requests.post(url, json={
            "chat_id": config["telegram_chat_id"],
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        logger.error(f"Telegram Error: {e}")

# ============================================================
# 🏦 OKX Connection
# ============================================================
def create_exchange() -> ccxt.okx:
    return ccxt.okx({
        "apiKey":          config["okx_api_key"],
        "secret":          config["okx_secret_key"],
        "password":        config["okx_passphrase"],
        "enableRateLimit": True,
        "options":         {"defaultType": "spot"}
    })

# ============================================================
# 📈 جلب البيانات
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

# ============================================================
# 📊 المؤشرات - قوية ومتعددة للسكالبينج
# ============================================================
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # RSI - فترات متعددة
    df["rsi"]   = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    df["rsi7"]  = ta.momentum.RSIIndicator(df["close"], window=7).rsi()

    # MACD
    macd = ta.trend.MACD(df["close"], window_fast=8, window_slow=21, window_sign=5)
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    # EMAs
    df["ema8"]  = ta.trend.EMAIndicator(df["close"], window=8).ema_indicator()
    df["ema21"] = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
    df["ema55"] = ta.trend.EMAIndicator(df["close"], window=55).ema_indicator()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_mid"]   = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]  

    # ATR لقياس التذبذب
    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range()

    # Stochastic RSI للتأكيد
    stoch = ta.momentum.StochasticOscillator(df["high"], df["low"], df["close"], window=14, smooth_window=3)
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    # حجم المعاملات
    df["vol_sma20"] = ta.trend.SMAIndicator(df["volume"], window=20).sma_indicator()
    df["vol_ratio"] = df["volume"] / df["vol_sma20"]

    # Momentum
    df["momentum"] = df["close"].pct_change(3) * 100  

    return df

# ============================================================
# 🎯 استراتيجية السكالبينج - دخول قوي ومحكم
# ============================================================
def check_buy_signal(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 60:
        return {"signal": False, "score": 0, "reason": "بيانات غير كافية"}

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    score = 0
    reasons = []

    # 1. RSI
    if 30 < curr["rsi"] < 55 and curr["rsi"] > prev["rsi"]:
        score += 1
        reasons.append("RSI صاعد ✅")
    if curr["rsi7"] > prev["rsi7"] and curr["rsi7"] < 60:
        score += 1
        reasons.append("RSI7 زخم ✅")

    # 2. MACD
    macd_cross = (prev["macd"] < prev["macd_signal"]) and (curr["macd"] > curr["macd_signal"])
    macd_improving = curr["macd_hist"] > prev["macd_hist"] > prev2["macd_hist"]

    if macd_cross:
        score += 2  
        reasons.append("MACD تقاطع صاعد ✅✅")
    elif macd_improving and curr["macd_hist"] > 0:
        score += 1
        reasons.append("MACD هيستوجرام متصاعد ✅")

    # 3. EMA Stack
    if curr["ema8"] > curr["ema21"] and curr["close"] > curr["ema8"]:
        score += 1
        reasons.append("EMA Stack صاعد ✅")
    if curr["close"] > curr["ema55"]:
        score += 1
        reasons.append("فوق EMA55 ✅")

    # 4. Bollinger
    near_lower = curr["close"] <= curr["bb_mid"] * 1.005
    bb_squeeze = curr["bb_width"] < df["bb_width"].rolling(20).mean().iloc[-1] * 0.8

    if near_lower and curr["close"] > prev["close"]:
        score += 1
        reasons.append("ارتداد من BB السفلي ✅")
    if bb_squeeze:
        score += 1
        reasons.append("BB انضغاط (تحرك قادم) ✅")

    # 5. Stochastic
    stoch_cross = (prev["stoch_k"] < prev["stoch_d"]) and (curr["stoch_k"] > curr["stoch_d"])
    if stoch_cross and curr["stoch_k"] < 60:
        score += 1
        reasons.append("Stochastic تقاطع صاعد ✅")
    elif curr["stoch_k"] > prev["stoch_k"] and curr["stoch_k"] < 50:
        score += 1
        reasons.append("Stochastic صاعد من القاع ✅")

    # 6. Volume
    if curr["vol_ratio"] > 1.3:
        score += 1
        reasons.append(f"حجم عالي x{curr['vol_ratio']:.1f} ✅")

    # 7. Momentum
    if curr["momentum"] > 0.1:
        score += 1
        reasons.append(f"زخم {curr['momentum']:.2f}% ✅")

    # فلتر التذبذب
    atr_pct = (curr["atr"] / curr["close"]) * 100
    if atr_pct > 1.5:   
        score = max(0, score - 2)
        reasons.append("⚠️ تذبذب عالي جداً")
    elif atr_pct < 0.05:  
        score = max(0, score - 1)
        reasons.append("⚠️ تذبذب منخفض جداً")

    min_score = config["min_signal_score"]
    signal = score >= min_score

    return {
        "signal":        signal,
        "score":         score,
        "current_price": curr["close"],
        "atr":           curr["atr"],
        "reason":        f"النقاط: {score}/10 | " + " | ".join(reasons)
    }

def check_sell_signal(df: pd.DataFrame, entry_price: float) -> dict:
    if df.empty:
        return {"signal": False}

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    if curr["rsi"] > 70: score += 2
    elif curr["rsi"] > 65: score += 1

    if prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]:
        score += 2

    if curr["close"] < curr["ema8"]: score += 1

    if curr["stoch_k"] > 80 and curr["stoch_k"] < prev["stoch_k"]:
        score += 1

    if curr["close"] < curr["open"] and curr["vol_ratio"] > 1.5:
        score += 1

    return {
        "signal":        score >= 3,
        "score":         score,
        "current_price": curr["close"]
    }

# ============================================================
# 💰 Balance & Orders
# ============================================================
def get_spot_balance(exchange: ccxt.okx, currency: str = "USDT") -> float:
    try:
        balance = exchange.fetch_balance({"type": "spot"})
        return float(balance.get(currency, {}).get("free", 0))
    except Exception as e:
        logger.error(f"Balance Error: {e}")
        return 0.0

def calculate_position_size(balance: float, price: float, ratio: float) -> float:
    usdt_to_use = balance * ratio
    qty = usdt_to_use / price
    return round(qty, 6)

def place_buy_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
    try:
        limit_price = round(price * 1.0005, 2)  
        order = exchange.create_order(
            symbol=symbol, type="limit", side="buy",
            amount=quantity, price=limit_price,
            params={"tdMode": "cash"}
        )
        logger.info(f"Buy Order placed: {order['id']} | price: {limit_price} | qty: {quantity}")
        return order
    except Exception as e:
        logger.error(f"Buy Order Error: {e}")
        return {}

def place_sell_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
    try:
        limit_price = round(price * 0.9995, 2)  
        order = exchange.create_order(
            symbol=symbol, type="limit", side="sell",
            amount=quantity, price=limit_price,
            params={"tdMode": "cash"}
        )
        logger.info(f"Sell Order placed: {order['id']} | price: {limit_price} | qty: {quantity}")
        return order
    except Exception as e:
        logger.error(f"Sell Order Error: {e}")
        return {}

def wait_for_order_fill(exchange: ccxt.okx, order_id: str, symbol: str, timeout: int = 30) -> dict | None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            order = exchange.fetch_order(order_id, symbol)
            if order["status"] in ("closed", "filled"):
                logger.info(f"Order {order_id} FILLED at avg price {order.get('average', order.get('price'))}")
                return order
            elif order["status"] == "canceled":
                logger.warning(f"Order {order_id} was CANCELED")
                return None
        except Exception as e:
            logger.error(f"fetch_order error: {e}")
        time.sleep(3)

    logger.warning(f"Order {order_id} timeout - canceling")
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        logger.error(f"Cancel order error: {e}")
    return None

# ============================================================
# 📋 TradeTracker 
# ============================================================
class TradeTracker:
    def __init__(self):
        self.open_trade    = None
        self.trade_history = []
        self.total_pnl     = 0.0
        self.total_fees    = 0.0
        self.wins          = 0
        self.losses        = 0

    def open(self, symbol, entry_price, quantity, take_profit, stop_loss):
        entry_fee = entry_price * quantity * config["fee_rate"]
        self.open_trade = {
            "symbol":      symbol,
            "entry_price": entry_price,
            "quantity":    quantity,
            "take_profit": take_profit,
            "stop_loss":   stop_loss,
            "entry_fee":   entry_fee,
            "opened_at":   datetime.utcnow().isoformat()
        }
        logger.info(f"Trade opened: entry={entry_price} qty={quantity} TP={take_profit} SL={stop_loss}")

    def close(self, exit_price) -> dict:
        if not self.open_trade:
            return {}

        t = self.open_trade
        gross_pnl  = (exit_price - t["entry_price"]) * t["quantity"]
        exit_fee   = exit_price * t["quantity"] * config["fee_rate"]
        total_fees = t["entry_fee"] + exit_fee
        net_pnl    = gross_pnl - total_fees

        pct_return = ((exit_price - t["entry_price"]) / t["entry_price"]) * 100

        result = {
            **t,
            "exit_price":  exit_price,
            "gross_pnl":   round(gross_pnl, 4),
            "fees":        round(total_fees, 4),
            "net_pnl":     round(net_pnl, 4),
            "pct_return":  round(pct_return, 3),
            "closed_at":   datetime.utcnow().isoformat()
        }

        self.trade_history.append(result)
        self.total_pnl   += net_pnl
        self.total_fees  += total_fees

        if net_pnl > 0:
            self.wins += 1
        else:
            self.losses += 1

        self.open_trade = None
        logger.info(f"Trade closed: exit={exit_price} gross={gross_pnl:.4f} fees={total_fees:.4f} net={net_pnl:.4f}")
        return result

    def check_tp_sl(self, current_price: float) -> str | None:
        if not self.open_trade:
            return None
        if current_price >= self.open_trade["take_profit"]:
            return "take_profit"
        if current_price <= self.open_trade["stop_loss"]:
            return "stop_loss"
        return None

    def stats_summary(self) -> str:
        total_trades = self.wins + self.losses
        win_rate = (self.wins / total_trades * 100) if total_trades > 0 else 0
        return (
            f"📊 <b>إحصائيات التداول</b>\n"
            f"الصفقات: {total_trades} | ✅ ربح: {self.wins} | ❌ خسارة: {self.losses}\n"
            f"معدل النجاح: {win_rate:.1f}%\n"
            f"صافي الربح: {self.total_pnl:+.4f} USDT\n"
            f"إجمالي الرسوم: {self.total_fees:.4f} USDT"
        )

# ============================================================
# 🔄 الحلقة الرئيسية
# ============================================================
def run_bot():
    exchange = create_exchange()
    tracker  = TradeTracker()
    symbol   = config["symbol"]

    notify(
        f"⚡ <b>تم تشغيل نظام السكالبينج المحسّن</b>\n"
        f"الزوج: {symbol} | الفريم: {config['timeframe']}\n"
        f"TP: {config['take_profit_pct']*100:.1f}% | SL: {config['stop_loss_pct']*100:.1f}%\n"
        f"نقاط الدخول المطلوبة: {config['min_signal_score']}/10"
    )

    stats_counter = 0

    while True:
        try:
            df = fetch_ohlcv(exchange, symbol, config["timeframe"], limit=200)
            if df.empty:
                time.sleep(config["loop_interval"])
                continue

            df = calculate_indicators(df)
            current_price = float(df["close"].iloc[-1])

            if tracker.open_trade:
                tp_sl = tracker.check_tp_sl(current_price)

                if tp_sl:
                    order = place_sell_order(exchange, symbol, tracker.open_trade["quantity"], current_price)
                    if order:
                        filled = wait_for_order_fill(exchange, order["id"], symbol, config["order_timeout"])
                        exit_price = float(filled["average"] or filled["price"]) if filled else current_price
                    else:
                        exit_price = current_price

                    result = tracker.close(exit_price)
                    emoji = "🟢" if result["net_pnl"] > 0 else "🔴"
                    reason_ar = "🎯 الهدف" if tp_sl == "take_profit" else "🛑 وقف الخسارة"

                    notify(
                        f"{emoji} <b>صفقة مغلقة - {reason_ar}</b>\n"
                        f"سعر الخروج: {exit_price:,.2f}\n"
                        f"ربح إجمالي: {result['gross_pnl']:+.4f} USDT\n"
                        f"الرسوم: -{result['fees']:.4f} USDT\n"
                        f"<b>صافي الربح: {result['net_pnl']:+.4f} USDT ({result['pct_return']:+.3f}%)</b>"
                    )

                else:
                    sell = check_sell_signal(df, tracker.open_trade["entry_price"])
                    if sell["signal"]:
                        order = place_sell_order(exchange, symbol, tracker.open_trade["quantity"], current_price)
                        if order:
                            filled = wait_for_order_fill(exchange, order["id"], symbol, config["order_timeout"])
                            exit_price = float(filled["average"] or filled["price"]) if filled else current_price
                            result = tracker.close(exit_price)
                            emoji = "🟢" if result["net_pnl"] > 0 else "🔴"
                            notify(
                                f"{emoji} <b>بيع بإشارة تقنية</b>\n"
                                f"سعر الخروج: {exit_price:,.2f}\n"
                                f"ربح إجمالي: {result['gross_pnl']:+.4f} USDT\n"
                                f"الرسوم: -{result['fees']:.4f} USDT\n"
                                f"<b>صافي الربح: {result['net_pnl']:+.4f} USDT ({result['pct_return']:+.3f}%)</b>"
                            )

            else:
                buy = check_buy_signal(df)
                logger.info(f"Price: {current_price:,.2f} | Signal Score: {buy['score']}/10")

                if buy["signal"]:
                    balance = get_spot_balance(exchange)
                    if balance >= config["min_usdt_balance"]:
                        qty = calculate_position_size(balance, current_price, config["capital_ratio"])

                        if qty > 0:
                            order = place_buy_order(exchange, symbol, qty, current_price)
                            if order:
                                filled = wait_for_order_fill(exchange, order["id"], symbol, config["order_timeout"])

                                if filled:
                                    actual_entry = float(filled["average"] or filled["price"])
                                    actual_qty   = float(filled["filled"])

                                    tp = round(actual_entry * (1 + config["take_profit_pct"]), 2)
                                    sl = round(actual_entry * (1 - config["stop_loss_pct"]), 2)
                                    tracker.open(symbol, actual_entry, actual_qty, tp, sl)

                                    notify(
                                        f"🟢 <b>صفقة سكالبينج جديدة!</b>\n"
                                        f"🎯 الإشارة: {buy['score']}/10\n"
                                        f"سعر الدخول: {actual_entry:,.2f}\n"
                                        f"الكمية: {actual_qty} BTC\n"
                                        f"💰 TP: {tp:,.2f} (+{config['take_profit_pct']*100:.1f}%)\n"
                                        f"🛑 SL: {sl:,.2f} (-{config['stop_loss_pct']*100:.1f}%)\n"
                                        f"📌 {buy['reason']}"
                                    )
                                else:
                                    notify("⚠️ الأوردر لم يُنفَّذ خلال المهلة المحددة وتم إلغاؤه")
                    else:
                        logger.warning(f"Insufficient balance: {balance:.2f} USDT")

            stats_counter += 1
            if stats_counter % 50 == 0:
                notify(tracker.stats_summary())

        except Exception as e:
            logger.error(f"Main Loop Error: {e}", exc_info=True)
            time.sleep(30)

        time.sleep(config["loop_interval"])

# ============================================================
# 🚀 نقطة التشغيل
# ============================================================
if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
