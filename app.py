# ============================================================

# OKX Spot Trading Bot - Scalping V2 (Fast + Smart + Auto-Withdraw)

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

app = Flask(**name**)

@app.route(’/’)
def home():
return “🤖 OKX Scalping Bot V2 - Running! 🚀”

# ============================================================

# ⚙️ Config - ضع المفاتيح في Environment Variables على Render

# ============================================================

config = {
“okx_api_key”:      os.environ.get(“OKX_API_KEY”, “”),
“okx_secret_key”:   os.environ.get(“OKX_SECRET_KEY”, “”),
“okx_passphrase”:   os.environ.get(“OKX_PASSPHRASE”, “”),

```
"telegram_token":   os.environ.get("TELEGRAM_TOKEN", ""),
"telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),

# ── إعدادات التداول ──
"symbol":           "BTC/USDT",
"timeframe":        "1m",           # 1 دقيقة = أسرع سكالبينج
"capital_ratio":    0.30,           # 30% من الرصيد لكل صفقة
"take_profit_pct":  0.006,          # 0.6% هدف ربح سريع
"stop_loss_pct":    0.003,          # 0.3% وقف خسارة (نسبة 1:2)
"fee_rate":         0.001,          # 0.1% رسوم OKX
"loop_interval":    12,             # فحص كل 12 ثانية
"min_usdt_balance": 10.0,
"order_timeout":    20,             # ثواني لانتظار تنفيذ الأوردر
"min_signal_score": 3,              # حد أدنى للإشارة (من 7) - أسرع دخول

# ── السحب التلقائي ──
"auto_withdraw":         True,
"withdraw_threshold":    20.0,      # اسحب إذا الربح تجاوز 20 USDT
"withdraw_address":      os.environ.get("WITHDRAW_ADDRESS", ""),
"withdraw_chain":        os.environ.get("WITHDRAW_CHAIN", "TRC20"),  # TRC20 أو ERC20
"withdraw_currency":     "USDT",
"withdraw_keep_balance": 50.0,      # احتفظ بـ 50 USDT للتداول
```

}

# ============================================================

# 📊 Logging

# ============================================================

logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s [%(levelname)s] %(message)s”
)
logger = logging.getLogger(**name**)

# ============================================================

# 📡 Telegram

# ============================================================

def notify(message: str):
try:
url = f”https://api.telegram.org/bot{config[‘telegram_token’]}/sendMessage”
requests.post(url, json={
“chat_id”: config[“telegram_chat_id”],
“text”: message,
“parse_mode”: “HTML”
}, timeout=10)
except Exception as e:
logger.error(f”Telegram Error: {e}”)

# ============================================================

# 🏦 OKX Connection

# ============================================================

def create_exchange() -> ccxt.okx:
return ccxt.okx({
“apiKey”:          config[“okx_api_key”],
“secret”:          config[“okx_secret_key”],
“password”:        config[“okx_passphrase”],
“enableRateLimit”: True,
“options”:         {“defaultType”: “spot”}
})

# ============================================================

# 📈 جلب البيانات

# ============================================================

def fetch_ohlcv(exchange: ccxt.okx, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
try:
ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
df = pd.DataFrame(ohlcv, columns=[“timestamp”, “open”, “high”, “low”, “close”, “volume”])
df[“timestamp”] = pd.to_datetime(df[“timestamp”], unit=“ms”)
df.set_index(“timestamp”, inplace=True)
return df
except Exception as e:
logger.error(f”Error fetching OHLCV: {e}”)
return pd.DataFrame()

# ============================================================

# 📊 المؤشرات - مع fix للـ NaN

# ============================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
# RSI
df[“rsi”]  = ta.momentum.RSIIndicator(df[“close”], window=14).rsi()
df[“rsi7”] = ta.momentum.RSIIndicator(df[“close”], window=7).rsi()

```
# MACD سريع للسكالبينج
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

# ATR
df["atr"] = ta.volatility.AverageTrueRange(
    df["high"], df["low"], df["close"], window=14
).average_true_range()

# Stochastic
stoch = ta.momentum.StochasticOscillator(
    df["high"], df["low"], df["close"], window=14, smooth_window=3
)
df["stoch_k"] = stoch.stoch()
df["stoch_d"] = stoch.stoch_signal()

# Volume
df["vol_sma"] = ta.trend.SMAIndicator(df["volume"], window=20).sma_indicator()
df["vol_ratio"] = df["volume"] / df["vol_sma"]

# Momentum
df["momentum"] = df["close"].pct_change(3) * 100

# ✅ FIX: إزالة NaN تماماً قبل الاستخدام
df = df.ffill().bfill()

return df
```

# ============================================================

# 🎯 إشارة الشراء - سريعة ومضمونة

# ============================================================

def check_buy_signal(df: pd.DataFrame) -> dict:
if df.empty or len(df) < 60:
return {“signal”: False, “score”: 0, “reason”: “بيانات غير كافية”}

```
# ✅ FIX: تطهير NaN
df = df.dropna()
if len(df) < 10:
    return {"signal": False, "score": 0, "reason": "NaN كثيرة"}

curr  = df.iloc[-1]
prev  = df.iloc[-2]
prev2 = df.iloc[-3]

score   = 0
reasons = []

# ── 1. RSI: زخم صاعد من منطقة مناسبة ──
if 28 < curr["rsi"] < 60 and curr["rsi"] > prev["rsi"]:
    score += 1
    reasons.append(f"RSI↑{curr['rsi']:.0f}")

if curr["rsi7"] > prev["rsi7"] and curr["rsi7"] < 65:
    score += 1
    reasons.append(f"RSI7↑{curr['rsi7']:.0f}")

# ── 2. MACD: تقاطع أو تحسن متتالي ──
macd_cross    = prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"]
macd_improving= curr["macd_hist"] > prev["macd_hist"] > prev2["macd_hist"]

if macd_cross:
    score += 2
    reasons.append("MACD✅✅")
elif macd_improving and curr["macd_hist"] > 0:
    score += 1
    reasons.append("MACD↑")

# ── 3. EMA: ترتيب صاعد ──
if curr["ema8"] > curr["ema21"] and curr["close"] > curr["ema8"]:
    score += 1
    reasons.append("EMA✅")

# ── 4. Stochastic: تقاطع صاعد من القاع ──
stoch_cross = prev["stoch_k"] < prev["stoch_d"] and curr["stoch_k"] > curr["stoch_d"]
if stoch_cross and curr["stoch_k"] < 65:
    score += 1
    reasons.append(f"Stoch✅{curr['stoch_k']:.0f}")
elif curr["stoch_k"] > prev["stoch_k"] and curr["stoch_k"] < 50:
    score += 1
    reasons.append("Stoch↑")

# ── 5. حجم: تأكيد الحركة ──
if curr["vol_ratio"] > 1.2:
    score += 1
    reasons.append(f"Vol×{curr['vol_ratio']:.1f}")

# ── 6. الشمعة الحالية خضراء ──
if curr["close"] > curr["open"]:
    score += 1
    reasons.append("شمعة↑")

# ── فلتر: تذبذب عالي جداً = خطر ──
atr_pct = (curr["atr"] / curr["close"]) * 100
if atr_pct > 1.8:
    score = max(0, score - 2)
    reasons.append("⚠️ATR عالي")
elif atr_pct < 0.03:
    score = max(0, score - 1)
    reasons.append("⚠️ATR منخفض")

# لوق تفصيلي لكل دورة
logger.info(
    f"Score:{score}/7 | RSI:{curr['rsi']:.1f} | RSI7:{curr['rsi7']:.1f} | "
    f"MACD_H:{curr['macd_hist']:.2f} | Stoch:{curr['stoch_k']:.1f} | "
    f"Vol:{curr['vol_ratio']:.2f} | ATR%:{atr_pct:.3f}"
)

return {
    "signal":        score >= config["min_signal_score"],
    "score":         score,
    "current_price": float(curr["close"]),
    "atr":           float(curr["atr"]),
    "reason":        f"{score}/7 | " + " | ".join(reasons)
}
```

# ============================================================

# 🔴 إشارة البيع

# ============================================================

def check_sell_signal(df: pd.DataFrame, entry_price: float) -> dict:
if df.empty:
return {“signal”: False}

```
df   = df.dropna()
curr = df.iloc[-1]
prev = df.iloc[-2]

score = 0
if curr["rsi"] > 68: score += 2
elif curr["rsi"] > 62: score += 1

if prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]:
    score += 2

if curr["close"] < curr["ema8"]: score += 1

if curr["stoch_k"] > 78 and curr["stoch_k"] < prev["stoch_k"]:
    score += 1

if curr["close"] < curr["open"] and curr["vol_ratio"] > 1.4:
    score += 1

return {
    "signal":        score >= 3,
    "score":         score,
    "current_price": float(curr["close"])
}
```

# ============================================================

# 💰 Balance & Orders

# ============================================================

def get_spot_balance(exchange: ccxt.okx, currency: str = “USDT”) -> float:
try:
balance = exchange.fetch_balance({“type”: “spot”})
return float(balance.get(currency, {}).get(“free”, 0))
except Exception as e:
logger.error(f”Balance Error: {e}”)
return 0.0

def calculate_position_size(balance: float, price: float, ratio: float) -> float:
usdt_to_use = balance * ratio
return round(usdt_to_use / price, 6)

def place_buy_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
try:
limit_price = round(price * 1.0005, 2)
order = exchange.create_order(
symbol=symbol, type=“limit”, side=“buy”,
amount=quantity, price=limit_price,
params={“tdMode”: “cash”}
)
logger.info(f”BUY order placed: {order[‘id’]} | {limit_price} × {quantity}”)
return order
except Exception as e:
logger.error(f”Buy Order Error: {e}”)
return {}

def place_sell_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
try:
limit_price = round(price * 0.9995, 2)
order = exchange.create_order(
symbol=symbol, type=“limit”, side=“sell”,
amount=quantity, price=limit_price,
params={“tdMode”: “cash”}
)
logger.info(f”SELL order placed: {order[‘id’]} | {limit_price} × {quantity}”)
return order
except Exception as e:
logger.error(f”Sell Order Error: {e}”)
return {}

def wait_for_order_fill(exchange: ccxt.okx, order_id: str, symbol: str, timeout: int = 20) -> dict | None:
start = time.time()
while time.time() - start < timeout:
try:
order = exchange.fetch_order(order_id, symbol)
if order[“status”] in (“closed”, “filled”):
logger.info(f”Order {order_id} FILLED @ {order.get(‘average’)}”)
return order
elif order[“status”] == “canceled”:
return None
except Exception as e:
logger.error(f”fetch_order error: {e}”)
time.sleep(2)

```
# انتهت المهلة - نلغي
logger.warning(f"Order {order_id} TIMEOUT - canceling")
try:
    exchange.cancel_order(order_id, symbol)
except Exception:
    pass
return None
```

# ============================================================

# 💸 السحب التلقائي

# ============================================================

def auto_withdraw(exchange: ccxt.okx, total_pnl: float):
if not config[“auto_withdraw”]:
return
if not config[“withdraw_address”]:
logger.warning(“No withdraw address set - skipping”)
return
if total_pnl < config[“withdraw_threshold”]:
return

```
try:
    balance = get_spot_balance(exchange, "USDT")
    amount_to_withdraw = balance - config["withdraw_keep_balance"]

    if amount_to_withdraw < 5:
        logger.info(f"Withdraw skipped - amount too small: {amount_to_withdraw:.2f}")
        return

    amount_to_withdraw = round(amount_to_withdraw, 2)

    result = exchange.withdraw(
        code     = config["withdraw_currency"],
        amount   = amount_to_withdraw,
        address  = config["withdraw_address"],
        params   = {
            "chain": config["withdraw_chain"],
            "fee":   "1"  # رسوم السحب (اضبطها حسب OKX)
        }
    )

    msg = (
        f"💸 <b>سحب تلقائي!</b>\n"
        f"المبلغ: {amount_to_withdraw} USDT\n"
        f"الشبكة: {config['withdraw_chain']}\n"
        f"العنوان: ...{config['withdraw_address'][-6:]}\n"
        f"ID: {result.get('id', 'N/A')}"
    )
    notify(msg)
    logger.info(f"Withdraw submitted: {amount_to_withdraw} USDT")

except Exception as e:
    logger.error(f"Withdraw Error: {e}")
    notify(f"⚠️ خطأ في السحب التلقائي: {e}")
```

# ============================================================

# 📋 TradeTracker - تتبع مع P&L صحيح

# ============================================================

class TradeTracker:
def **init**(self):
self.open_trade    = None
self.trade_history = []
self.total_pnl     = 0.0
self.total_fees    = 0.0
self.wins          = 0
self.losses        = 0
self.withdraw_done = 0.0  # مجموع ما تم سحبه

```
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
    logger.info(f"TRADE OPEN: entry={entry_price} qty={quantity} TP={take_profit} SL={stop_loss}")

def close(self, exit_price) -> dict:
    if not self.open_trade:
        return {}

    t          = self.open_trade
    gross_pnl  = (exit_price - t["entry_price"]) * t["quantity"]
    exit_fee   = exit_price * t["quantity"] * config["fee_rate"]
    total_fees = t["entry_fee"] + exit_fee
    net_pnl    = gross_pnl - total_fees
    pct_return = ((exit_price - t["entry_price"]) / t["entry_price"]) * 100

    result = {
        **t,
        "exit_price": exit_price,
        "gross_pnl":  round(gross_pnl, 4),
        "fees":       round(total_fees, 4),
        "net_pnl":    round(net_pnl, 4),
        "pct_return": round(pct_return, 3),
        "closed_at":  datetime.utcnow().isoformat()
    }

    self.trade_history.append(result)
    self.total_pnl  += net_pnl
    self.total_fees += total_fees
    if net_pnl > 0: self.wins += 1
    else:           self.losses += 1
    self.open_trade = None

    logger.info(
        f"TRADE CLOSE: exit={exit_price} gross={gross_pnl:.4f} "
        f"fees={total_fees:.4f} net={net_pnl:.4f}"
    )
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
    total = self.wins + self.losses
    wr    = (self.wins / total * 100) if total > 0 else 0
    return (
        f"📊 <b>إحصائيات</b>\n"
        f"الصفقات: {total} | ✅{self.wins} | ❌{self.losses}\n"
        f"معدل النجاح: {wr:.1f}%\n"
        f"صافي الربح: {self.total_pnl:+.4f} USDT\n"
        f"الرسوم المدفوعة: {self.total_fees:.4f} USDT\n"
        f"المسحوب: {self.withdraw_done:.2f} USDT"
    )
```

# ============================================================

# 🔄 الحلقة الرئيسية

# ============================================================

def run_bot():
exchange = create_exchange()
tracker  = TradeTracker()
symbol   = config[“symbol”]

```
notify(
    f"⚡ <b>تم تشغيل نظام السكالبينج V2</b>\n"
    f"الزوج: {symbol} | الفريم: {config['timeframe']}\n"
    f"TP: {config['take_profit_pct']*100:.1f}% | SL: {config['stop_loss_pct']*100:.1f}%\n"
    f"نقاط الدخول المطلوبة: {config['min_signal_score']}/7\n"
    f"السحب التلقائي: {'✅ مفعّل' if config['auto_withdraw'] else '❌ معطّل'}"
)

stats_counter   = 0
withdraw_counter= 0

while True:
    try:
        df = fetch_ohlcv(exchange, symbol, config["timeframe"], limit=300)
        if df.empty:
            time.sleep(config["loop_interval"])
            continue

        df = calculate_indicators(df)
        current_price = float(df["close"].iloc[-1])

        # ─────────────────────────────────────────────
        # 🔒 صفقة مفتوحة: تحقق TP/SL أو إشارة بيع
        # ─────────────────────────────────────────────
        if tracker.open_trade:
            tp_sl = tracker.check_tp_sl(current_price)

            if tp_sl:
                order = place_sell_order(exchange, symbol, tracker.open_trade["quantity"], current_price)
                if order:
                    filled = wait_for_order_fill(exchange, order["id"], symbol, config["order_timeout"])
                    exit_price = float(filled["average"] or filled["price"]) if filled else current_price
                else:
                    exit_price = current_price

                result    = tracker.close(exit_price)
                emoji     = "🟢" if result["net_pnl"] > 0 else "🔴"
                reason_ar = "🎯 الهدف" if tp_sl == "take_profit" else "🛑 وقف الخسارة"

                notify(
                    f"{emoji} <b>صفقة مغلقة - {reason_ar}</b>\n"
                    f"سعر الخروج: {exit_price:,.2f}\n"
                    f"ربح إجمالي: {result['gross_pnl']:+.4f} USDT\n"
                    f"الرسوم: -{result['fees']:.4f} USDT\n"
                    f"<b>صافي: {result['net_pnl']:+.4f} USDT ({result['pct_return']:+.3f}%)</b>\n"
                    f"إجمالي الربح: {tracker.total_pnl:+.4f} USDT"
                )

                # تحقق من السحب التلقائي
                withdraw_counter += 1
                if withdraw_counter % 3 == 0:  # تحقق كل 3 صفقات
                    auto_withdraw(exchange, tracker.total_pnl)

            else:
                sell = check_sell_signal(df, tracker.open_trade["entry_price"])
                if sell["signal"]:
                    order = place_sell_order(exchange, symbol, tracker.open_trade["quantity"], current_price)
                    if order:
                        filled = wait_for_order_fill(exchange, order["id"], symbol, config["order_timeout"])
                        exit_price = float(filled["average"] or filled["price"]) if filled else current_price
                        result = tracker.close(exit_price)
                        emoji  = "🟢" if result["net_pnl"] > 0 else "🔴"

                        notify(
                            f"{emoji} <b>بيع بإشارة تقنية</b>\n"
                            f"سعر الخروج: {exit_price:,.2f}\n"
                            f"الرسوم: -{result['fees']:.4f} USDT\n"
                            f"<b>صافي: {result['net_pnl']:+.4f} USDT ({result['pct_return']:+.3f}%)</b>"
                        )

        # ─────────────────────────────────────────────
        # 🟢 لا يوجد صفقة: ابحث عن إشارة شراء
        # ─────────────────────────────────────────────
        else:
            buy = check_buy_signal(df)

            if buy["signal"]:
                balance = get_spot_balance(exchange)
                logger.info(f"💰 Balance: {balance:.2f} USDT | Signal: {buy['score']}/7")

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
                                    f"🟢 <b>صفقة سكالبينج!</b>\n"
                                    f"🎯 الإشارة: {buy['score']}/7\n"
                                    f"سعر الدخول: {actual_entry:,.2f}\n"
                                    f"الكمية: {actual_qty} BTC\n"
                                    f"💰 TP: {tp:,.2f} (+{config['take_profit_pct']*100:.1f}%)\n"
                                    f"🛑 SL: {sl:,.2f} (-{config['stop_loss_pct']*100:.1f}%)\n"
                                    f"📌 {buy['reason']}"
                                )
                            else:
                                notify("⚠️ الأوردر لم يُنفَّذ - تم إلغاؤه")
                else:
                    logger.warning(f"Insufficient balance: {balance:.2f} USDT")

        # إرسال إحصائيات كل 100 دورة
        stats_counter += 1
        if stats_counter % 100 == 0:
            notify(tracker.stats_summary())

    except Exception as e:
        logger.error(f"Main Loop Error: {e}", exc_info=True)
        time.sleep(30)

    time.sleep(config["loop_interval"])
```

# ============================================================

# 🚀 نقطة التشغيل

# ============================================================

if **name** == “**main**”:
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

```
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
```
