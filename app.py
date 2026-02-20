# ============================================================
# OKX Spot Trading Bot - Professional Version
# ============================================================
# المتطلبات: pip install ccxt pandas pandas-ta python-telegram-bot schedule
# ============================================================

import ccxt
import pandas as pd
import pandas_ta as ta
import asyncio
import logging
import time
import json
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError

# ============================================================
# ⚙️ الإعدادات - ضع مفاتيحك الجديدة في متغيرات بيئة أو هنا
# ============================================================
config = {
    # OKX API - ضع مفاتيحك الجديدة هنا بعد الحذف
    "okx_api_key":    "4e945e12-ea6a-426a-8272-7caae6e2a1c0",
    "okx_secret_key": "7E546FB45CB7F47BFF76BF8A0720C823",
    "okx_passphrase": "Abdullaheyas123@",
    
    # Telegram
    "telegram_token": "8520586890:AAHBkefrtNQjv0bPUtpkWG0gijkXU4K84BY",
    "telegram_chat_id": "7825994636",  # chat ID يمكن إبقاؤه
    
    # إعدادات التداول
    "symbol":          "BTC/USDT",     # الزوج المراد تداوله
    "timeframe":       "15m",          # الإطار الزمني
    "capital_ratio":   0.35,           # 35% من الرصيد لكل صفقة
    "take_profit_pct": 0.025,          # هدف الربح 2.5%
    "stop_loss_pct":   0.015,          # وقف الخسارة 1.5%
    "loop_interval":   60,             # ثانية بين كل دورة تحليل
    "min_usdt_balance": 10.0,          # الحد الأدنى للتداول
}

# ============================================================
# 📊 نظام اللوجينج
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# 📡 التليغرام - إرسال الإشعارات
# ============================================================
async def send_telegram(message: str):
    """إرسال رسالة إلى Telegram"""
    try:
        bot = Bot(token=config["telegram_token"])
        await bot.send_message(
            chat_id=config["telegram_chat_id"],
            text=message,
            parse_mode="HTML"
        )
        logger.info(f"Telegram: {message[:50]}...")
    except TelegramError as e:
        logger.error(f"Telegram Error: {e}")


def notify(message: str):
    """مغلف متزامن لإرسال الإشعارات"""
    asyncio.run(send_telegram(message))


# ============================================================
# 🏦 اتصال OKX
# ============================================================
def create_exchange() -> ccxt.okx:
    """إنشاء اتصال مع OKX"""
    exchange = ccxt.okx({
        "apiKey":     config["okx_api_key"],
        "secret":     config["okx_secret_key"],
        "password":   config["okx_passphrase"],
        "enableRateLimit": True,
        "options": {
            "defaultType": "spot",  # ✅ Spot فقط - ممنوع Futures
        }
    })
    return exchange


# ============================================================
# 📈 جلب البيانات وحساب المؤشرات
# ============================================================
def fetch_ohlcv(exchange: ccxt.okx, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    """جلب بيانات الشموع من OKX"""
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
    """
    حساب المؤشرات الفنية:
    - RSI: مؤشر القوة النسبية
    - MACD: تقاطعات الزخم
    - EMA 20 / EMA 50: المتوسطات المتحركة
    - Bollinger Bands: نطاقات بولينجر
    - ATR: متوسط المدى الحقيقي لقياس التقلب
    - Volume SMA: متوسط الحجم
    """
    # RSI
    df["rsi"] = ta.rsi(df["close"], length=14)
    
    # MACD
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["macd"]        = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"]   = macd["MACDh_12_26_9"]
    
    # EMA
    df["ema20"] = ta.ema(df["close"], length=20)
    df["ema50"] = ta.ema(df["close"], length=50)
    
    # Bollinger Bands
    bb = ta.bbands(df["close"], length=20, std=2)
    df["bb_upper"] = bb["BBU_20_2.0"]
    df["bb_mid"]   = bb["BBM_20_2.0"]
    df["bb_lower"] = bb["BBL_20_2.0"]
    
    # ATR (لقياس التقلب)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    
    # Volume SMA
    df["vol_sma"] = ta.sma(df["volume"], length=20)
    
    return df


# ============================================================
# 🎯 استراتيجية الدخول - شروط صارمة ومتعددة
# ============================================================
def check_buy_signal(df: pd.DataFrame) -> dict:
    """
    التحقق من شروط الشراء - يجب تحقق الشروط مجتمعة:
    
    ✅ شرط 1: RSI في منطقة التشبع البيعي أو صاعد (30-55)
    ✅ شرط 2: MACD يتقاطع صعوداً فوق خط الإشارة
    ✅ شرط 3: السعر فوق EMA20 التي هي فوق EMA50 (اتجاه صاعد)
    ✅ شرط 4: السعر قريب أو فوق الباند الوسطى
    ✅ شرط 5: حجم التداول أعلى من المتوسط (تأكيد القوة)
    """
    if df.empty or len(df) < 51:
        return {"signal": False, "reason": "بيانات غير كافية"}
    
    # آخر شمعتين للتحقق من التقاطع
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    signals = {}
    
    # شرط 1: RSI (نريده بين 40-60 - منطقة آمنة ليست متطرفة)
    rsi_ok = 40 < curr["rsi"] < 62
    signals["rsi"] = f"RSI={curr['rsi']:.1f} {'✅' if rsi_ok else '❌'}"
    
    # شرط 2: تقاطع MACD صعودي
    macd_cross_up = (
        prev["macd"] < prev["macd_signal"] and
        curr["macd"] > curr["macd_signal"] and
        curr["macd_hist"] > 0
    )
    # أو: MACD فوق الإشارة والهيستوغرام يتحسن
    macd_strong = (
        curr["macd"] > curr["macd_signal"] and
        curr["macd_hist"] > prev["macd_hist"] and
        curr["macd"] < 0  # MACD سالب يعني مبكر في الدورة
    )
    macd_ok = macd_cross_up or macd_strong
    signals["macd"] = f"MACD Cross={'✅' if macd_ok else '❌'}"
    
    # شرط 3: EMA - الاتجاه العام صاعد
    ema_ok = (
        curr["close"] > curr["ema20"] and
        curr["ema20"] > curr["ema50"]
    )
    signals["ema"] = f"EMA Trend={'✅' if ema_ok else '❌'}"
    
    # شرط 4: السعر بين الباند الوسطى والعلوي (منطقة القوة)
    bb_ok = curr["bb_mid"] <= curr["close"] <= curr["bb_upper"]
    signals["bb"] = f"BB Position={'✅' if bb_ok else '❌'}"
    
    # شرط 5: حجم التداول قوي
    vol_ok = curr["volume"] > curr["vol_sma"] * 1.2
    signals["volume"] = f"Volume={'✅' if vol_ok else '❌'}"
    
    # ✅ يجب تحقق 4 شروط على الأقل من 5 للدخول
    conditions_met = sum([rsi_ok, macd_ok, ema_ok, bb_ok, vol_ok])
    all_ok = conditions_met >= 4
    
    return {
        "signal": all_ok,
        "conditions_met": conditions_met,
        "signals": signals,
        "current_price": curr["close"],
        "atr": curr["atr"],
        "reason": f"{conditions_met}/5 شروط متحققة"
    }


def check_sell_signal(df: pd.DataFrame, entry_price: float) -> dict:
    """
    التحقق من شروط البيع / الخروج:
    - RSI فوق 70 (تشبع شرائي)
    - MACD يتقاطع هبوطاً
    - السعر دون EMA20
    """
    if df.empty:
        return {"signal": False}
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    # إشارات البيع
    rsi_overbought  = curr["rsi"] > 70
    macd_cross_down = (prev["macd"] > prev["macd_signal"] and 
                       curr["macd"] < curr["macd_signal"])
    price_below_ema = curr["close"] < curr["ema20"]
    
    sell_conditions = sum([rsi_overbought, macd_cross_down, price_below_ema])
    
    return {
        "signal": sell_conditions >= 2,
        "reason": f"إشارات بيع: RSI={'✅' if rsi_overbought else '❌'} "
                  f"MACD={'✅' if macd_cross_down else '❌'} "
                  f"EMA={'✅' if price_below_ema else '❌'}",
        "current_price": curr["close"]
    }


# ============================================================
# 💰 إدارة رأس المال والتنفيذ
# ============================================================
def get_spot_balance(exchange: ccxt.okx, currency: str = "USDT") -> float:
    """جلب الرصيد المتاح في حساب Spot"""
    try:
        balance = exchange.fetch_balance({"type": "spot"})
        return float(balance.get(currency, {}).get("free", 0))
    except Exception as e:
        logger.error(f"Balance Error: {e}")
        return 0.0


def calculate_position_size(balance: float, price: float, ratio: float = 0.35) -> float:
    """
    حساب حجم الصفقة:
    - يستخدم 35% فقط من الرصيد المتاح
    - يحسب الكمية بالعملة المراد شراؤها
    """
    usdt_to_use = balance * ratio
    quantity    = usdt_to_use / price
    return round(quantity, 6)


def place_buy_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
    """
    تنفيذ أمر الشراء:
    - Limit Order للحصول على سعر أفضل
    - مع هامش 0.1% أعلى من السعر الحالي لضمان التنفيذ
    """
    try:
        # نستخدم Limit Order بسعر أعلى قليلاً لضمان التنفيذ السريع
        limit_price = round(price * 1.001, 2)
        
        order = exchange.create_order(
            symbol   = symbol,
            type     = "limit",
            side     = "buy",
            amount   = quantity,
            price    = limit_price,
            params   = {"tdMode": "cash"}  # Spot cash فقط
        )
        logger.info(f"Buy Order Placed: {order['id']}")
        return order
    except Exception as e:
        logger.error(f"Buy Order Error: {e}")
        return {}


def place_sell_order(exchange: ccxt.okx, symbol: str, quantity: float, price: float) -> dict:
    """تنفيذ أمر البيع"""
    try:
        limit_price = round(price * 0.999, 2)  # أقل قليلاً لضمان التنفيذ
        
        order = exchange.create_order(
            symbol = symbol,
            type   = "limit",
            side   = "sell",
            amount = quantity,
            price  = limit_price,
            params = {"tdMode": "cash"}
        )
        logger.info(f"Sell Order Placed: {order['id']}")
        return order
    except Exception as e:
        logger.error(f"Sell Order Error: {e}")
        return {}


# ============================================================
# 📊 تتبع الصفقات والأرباح
# ============================================================
class TradeTracker:
    """تتبع الصفقات المفتوحة والمغلقة"""
    
    def __init__(self):
        self.open_trade  = None  # الصفقة المفتوحة الحالية
        self.trade_history = []  # سجل الصفقات
        self.total_pnl   = 0.0
    
    def open(self, symbol, entry_price, quantity, take_profit, stop_loss):
        self.open_trade = {
            "symbol":       symbol,
            "entry_price":  entry_price,
            "quantity":     quantity,
            "take_profit":  take_profit,
            "stop_loss":    stop_loss,
            "entry_time":   datetime.now(),
            "usdt_invested": entry_price * quantity
        }
        logger.info(f"Trade Opened: {self.open_trade}")
    
    def close(self, exit_price, reason: str):
        if not self.open_trade:
            return 0.0
        
        pnl = (exit_price - self.open_trade["entry_price"]) * self.open_trade["quantity"]
        pnl_pct = ((exit_price / self.open_trade["entry_price"]) - 1) * 100
        
        closed = {
            **self.open_trade,
            "exit_price": exit_price,
            "exit_time":  datetime.now(),
            "pnl_usdt":   round(pnl, 4),
            "pnl_pct":    round(pnl_pct, 2),
            "reason":     reason
        }
        self.trade_history.append(closed)
        self.total_pnl += pnl
        self.open_trade = None
        
        return pnl
    
    def check_tp_sl(self, current_price: float) -> str | None:
        """التحقق من وصول السعر لـ TP أو SL"""
        if not self.open_trade:
            return None
        if current_price >= self.open_trade["take_profit"]:
            return "take_profit"
        if current_price <= self.open_trade["stop_loss"]:
            return "stop_loss"
        return None
    
    def get_report(self) -> str:
        """تقرير الأداء"""
        total_trades = len(self.trade_history)
        wins  = sum(1 for t in self.trade_history if t["pnl_usdt"] > 0)
        loses = total_trades - wins
        
        return (
            f"📊 <b>تقرير الأداء</b>\n"
            f"إجمالي الصفقات: {total_trades}\n"
            f"رابحة: {wins} | خاسرة: {loses}\n"
            f"نسبة الفوز: {(wins/total_trades*100):.1f}%" if total_trades > 0 else "لا توجد صفقات بعد\n"
            f"إجمالي الربح/الخسارة: {self.total_pnl:.4f} USDT"
        )


# ============================================================
# 🔄 الحلقة الرئيسية - Main Trading Loop
# ============================================================
def run_bot():
    """تشغيل البوت - الحلقة الرئيسية"""
    logger.info("🚀 بدء تشغيل البوت...")
    
    # إنشاء الاتصالات
    exchange = create_exchange()
    tracker  = TradeTracker()
    
    symbol   = config["symbol"]
    
    # إشعار البدء
    notify(
        f"🤖 <b>البوت يعمل الآن</b>\n"
        f"الزوج: {symbol}\n"
        f"الإطار الزمني: {config['timeframe']}\n"
        f"نسبة رأس المال: {config['capital_ratio']*100:.0f}%\n"
        f"هدف الربح: {config['take_profit_pct']*100:.1f}%\n"
        f"وقف الخسارة: {config['stop_loss_pct']*100:.1f}%"
    )
    
    cycle = 0
    
    while True:
        try:
            cycle += 1
            logger.info(f"\n{'='*50}\nدورة #{cycle} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # ── جلب البيانات والمؤشرات ──────────────────────────
            df = fetch_ohlcv(exchange, symbol, config["timeframe"], limit=200)
            if df.empty:
                time.sleep(config["loop_interval"])
                continue
            
            df = calculate_indicators(df)
            current_price = df["close"].iloc[-1]
            logger.info(f"السعر الحالي: {current_price}")
            
            # ── التحقق من TP/SL أولاً ───────────────────────────
            if tracker.open_trade:
                tp_sl = tracker.check_tp_sl(current_price)
                
                if tp_sl:
                    pnl = tracker.close(current_price, tp_sl)
                    emoji = "🟢" if pnl > 0 else "🔴"
                    reason_ar = "هدف الربح ✅" if tp_sl == "take_profit" else "وقف الخسارة 🛑"
                    
                    notify(
                        f"{emoji} <b>صفقة مغلقة - {reason_ar}</b>\n"
                        f"الزوج: {symbol}\n"
                        f"سعر الإغلاق: {current_price}\n"
                        f"الربح/الخسارة: {pnl:+.4f} USDT\n"
                        f"إجمالي الأرباح: {tracker.total_pnl:+.4f} USDT"
                    )
                    logger.info(f"Trade Closed: {tp_sl}, PnL: {pnl}")
                
                else:
                    # التحقق من إشارة بيع تقنية
                    sell_signal = check_sell_signal(df, tracker.open_trade["entry_price"])
                    if sell_signal["signal"]:
                        # بيع بناء على المؤشرات
                        sell_qty = tracker.open_trade["quantity"]
                        order    = place_sell_order(exchange, symbol, sell_qty, current_price)
                        
                        if order:
                            pnl = tracker.close(current_price, "إشارة تقنية")
                            notify(
                                f"🔵 <b>بيع بإشارة تقنية</b>\n"
                                f"السبب: {sell_signal['reason']}\n"
                                f"الربح/الخسارة: {pnl:+.4f} USDT"
                            )
                    else:
                        # تقرير مرحلي لصفقة مفتوحة
                        unrealized = (current_price - tracker.open_trade["entry_price"]) * tracker.open_trade["quantity"]
                        logger.info(
                            f"صفقة مفتوحة | دخل: {tracker.open_trade['entry_price']} | "
                            f"حالي: {current_price} | PnL: {unrealized:+.4f} USDT"
                        )
            
            # ── البحث عن فرص شراء ───────────────────────────────
            elif not tracker.open_trade:
                buy_signal = check_buy_signal(df)
                logger.info(f"إشارة الشراء: {buy_signal['reason']}")
                
                if buy_signal["signal"]:
                    # التحقق من الرصيد
                    balance = get_spot_balance(exchange)
                    logger.info(f"الرصيد المتاح: {balance} USDT")
                    
                    if balance < config["min_usdt_balance"]:
                        logger.warning("رصيد غير كافٍ للتداول")
                        continue
                    
                    # حساب الكمية ومستويات TP/SL
                    quantity    = calculate_position_size(balance, current_price, config["capital_ratio"])
                    take_profit = round(current_price * (1 + config["take_profit_pct"]), 4)
                    stop_loss   = round(current_price * (1 - config["stop_loss_pct"]), 4)
                    
                    # تنفيذ الشراء
                    order = place_buy_order(exchange, symbol, quantity, current_price)
                    
                    if order:
                        tracker.open(symbol, current_price, quantity, take_profit, stop_loss)
                        
                        signals_text = "\n".join([f"  {v}" for v in buy_signal["signals"].values()])
                        notify(
                            f"🟢 <b>صفقة شراء جديدة!</b>\n"
                            f"الزوج: {symbol}\n"
                            f"سعر الدخول: {current_price}\n"
                            f"الكمية: {quantity}\n"
                            f"القيمة: {current_price * quantity:.2f} USDT\n"
                            f"هدف الربح (TP): {take_profit}\n"
                            f"وقف الخسارة (SL): {stop_loss}\n"
                            f"المؤشرات:\n{signals_text}\n"
                            f"الشروط: {buy_signal['conditions_met']}/5"
                        )
            
            # ── تقرير كل 24 ساعة (1440 دورة بدقيقة) ─────────────
            if cycle % 1440 == 0:
                notify(tracker.get_report())
            
        except ccxt.NetworkError as e:
            logger.error(f"Network Error: {e}")
            time.sleep(30)
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange Error: {e}")
            time.sleep(60)
        except KeyboardInterrupt:
            logger.info("إيقاف البوت...")
            notify("⛔ تم إيقاف البوت يدوياً\n" + tracker.get_report())
            break
        except Exception as e:
            logger.error(f"Unexpected Error: {e}", exc_info=True)
            time.sleep(30)
        
        # الانتظار قبل الدورة التالية
        time.sleep(config["loop_interval"])


# ============================================================
# 🚀 نقطة التشغيل
# ============================================================
if __name__ == "__main__":
    run_bot()
