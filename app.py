“””
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║        🤖  NFT LINK FETCHER BOT  •  @NftGrabberBot          ║
║        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━          ║
║        Built with Python • Flask • Telegram Bot API          ║
║        Render-Optimized  •  0.1 CPU / 512 MB                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
“””

# ════════════════════════════════════════════════════════════════

# IMPORTS

# ════════════════════════════════════════════════════════════════

import os, re, csv, io, json, time, logging, asyncio, threading
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import (
Update, InlineKeyboardButton, InlineKeyboardMarkup,
LabeledPrice
)
from telegram.ext import (
Application, CommandHandler, MessageHandler,
CallbackQueryHandler, ContextTypes,
PreCheckoutQueryHandler, filters
)
from telegram.constants import ParseMode
import aiohttp

# ════════════════════════════════════════════════════════════════

# ⚙️  CONFIGURATION

# ════════════════════════════════════════════════════════════════

BOT_TOKEN   = os.getenv(“BOT_TOKEN”,  “8195283120:AAHdMCVVnTin3mwfSHivg4I1kU0vND2TulA”)
ADMIN_IDS   = [int(x) for x in os.getenv(“ADMIN_IDS”, “7825994636”).split(”,”)]

FREE_FETCHES  = 3
BONUS_FETCHES = 2

# Telegram Stars prices

PRICES = {
“bulk”:      50,
“multi”:     30,
“monitor”:  100,
“metadata”:  40,
“history”:   25,
“export”:    35,
“unlimited”: 150,
}

FEATURE_LABELS = {
“bulk”:      “📦 Bulk Fetch”,
“multi”:     “🌐 Multi-Platform”,
“monitor”:   “📡 Auto Monitor”,
“metadata”:  “🔍 Metadata Extract”,
“history”:   “📜 History Log”,
“export”:    “📤 Export CSV”,
“unlimited”: “⚡ Unlimited 24h”,
}

FEATURE_DESC = {
“bulk”:      “جلب حتى 10 روابط NFT دفعة واحدة”,
“multi”:     “البحث في OpenSea + Blur + Rarible + Magic Eden”,
“monitor”:   “إشعارات فورية عند تغيير السعر أو البيع”,
“metadata”:  “استخراج Traits + Rarity + تاريخ المعاملات”,
“history”:   “حفظ وعرض آخر 20 رابط تم جلبها”,
“export”:    “تصدير السجل الكامل كملف CSV”,
“unlimited”: “محاولات غير محدودة لمدة 24 ساعة كاملة”,
}

# ════════════════════════════════════════════════════════════════

# 🗃️  IN-MEMORY DATABASE

# ════════════════════════════════════════════════════════════════

users_db:    dict = {}
monitors_db: dict = {}   # uid → list[{url, last_price, added_at}]

def get_user(uid: int) -> dict:
if uid not in users_db:
users_db[uid] = {
“id”:            uid,
“fetches_left”:  FREE_FETCHES + BONUS_FETCHES,
“total_fetches”: 0,
“joined”:        datetime.now().isoformat(),
“premium”: {
“bulk”:             False,
“multi_platform”:   False,
“monitor”:          False,
“metadata”:         False,
“history”:          False,
“export”:           False,
“unlimited_until”:  None,
},
“history”: [],    # [(url, result_dict, timestamp)]
“referrals”: 0,
}
return users_db[uid]

def is_unlimited(uid: int) -> bool:
u = get_user(uid)
until = u[“premium”].get(“unlimited_until”)
if until and datetime.fromisoformat(until) > datetime.now():
return True
return False

def has_feat(uid: int, feat: str) -> bool:
if feat == “unlimited”:
return is_unlimited(uid)
return get_user(uid)[“premium”].get(feat, False)

def can_fetch(uid: int) -> bool:
return is_unlimited(uid) or get_user(uid)[“fetches_left”] > 0

def consume(uid: int):
u = get_user(uid)
if not is_unlimited(uid):
u[“fetches_left”] = max(0, u[“fetches_left”] - 1)
u[“total_fetches”] += 1

def save_history(uid: int, url: str, result: dict):
u = get_user(uid)
if has_feat(uid, “history”) or has_feat(uid, “export”):
u[“history”].append((url, result, datetime.now().isoformat()))
if len(u[“history”]) > 500:
u[“history”] = u[“history”][-500:]

# ════════════════════════════════════════════════════════════════

# 🕸️  NFT FETCHER ENGINE

# ════════════════════════════════════════════════════════════════

PLATFORMS = {
“opensea”:   “opensea.io”,
“blur”:      “blur.io”,
“rarible”:   “rarible.com”,
“magiceden”: “magiceden.io”,
“looksrare”: “looksrare.org”,
}

def detect_platform(url: str) -> str:
for name, domain in PLATFORMS.items():
if domain in url.lower():
return name.capitalize()
return “Unknown”

def ex_meta(html: str, prop: str) -> str | None:
for pat in [
rf’property=[”']og:{prop}[”'][^>]+content=[”'](.*?)[”']’,
rf’name=[”'{prop}”][^>]+content=[”'](.*?)[”']’,
rf’<title>(.*?)</title>’,
]:
m = re.search(pat, html, re.I | re.S)
if m:
return re.sub(r’<[^>]+>’, ‘’, m.group(1)).strip()[:200]
return None

def ex_price(html: str) -> str | None:
m = re.search(r’(\d+.?\d{0,6})\s*(ETH|SOL|MATIC|BTC|USDC)’, html, re.I)
return f”{m.group(1)} {m.group(2).upper()}” if m else None

def ex_traits(html: str) -> list:
raw = re.findall(r’“trait_type”\s*:\s*”([^”]+)”.*?“value”\s*:\s*”([^”]+)”’, html)
return [f”{k}: {v}” for k, v in raw[:8]]

def ex_rarity(html: str) -> str | None:
m = re.search(r’(?:rarity|rank)[^0-9]{0,20}(\d+)’, html, re.I)
return f”Rank #{m.group(1)}” if m else None

async def fetch_nft(url: str, multi: bool = False, metadata: bool = False) -> dict:
r = {
“url”:       url,
“platform”:  detect_platform(url),
“title”:     None, “collection”: None,
“price”:     None, “image”:      None,
“rarity”:    None, “traits”:     [],
“last_sale”: None,
“cross”:     {} if multi else None,
“fetched”:   datetime.now().strftime(”%Y-%m-%d %H:%M”),
“error”:     None,
}
try:
hdrs = {“User-Agent”: “Mozilla/5.0 (compatible; NFTBot/2.0; +https://t.me/NftGrabberBot)”}
async with aiohttp.ClientSession() as s:
async with s.get(url, headers=hdrs, timeout=aiohttp.ClientTimeout(total=12)) as resp:
if resp.status == 200:
html = await resp.text()
r[“title”]      = ex_meta(html, “title”)
r[“collection”] = ex_meta(html, “site_name”)
r[“image”]      = ex_meta(html, “image”)
r[“price”]      = ex_price(html)
if metadata:
r[“traits”] = ex_traits(html)
r[“rarity”] = ex_rarity(html)
sale = re.search(r’(?:last.sale|sold.for)[^0-9]{0,30}(\d+.?\d*\s*(?:ETH|SOL))’, html, re.I)
r[“last_sale”] = sale.group(1) if sale else None
if multi and r[“title”]:
slug = re.sub(r’[^a-z0-9]’, ‘-’, r[“title”].lower())[:40]
r[“cross”] = {
“OpenSea”:   f”https://opensea.io/assets/ethereum/{slug}”,
“Blur”:      f”https://blur.io/asset/{slug}”,
“Rarible”:   f”https://rarible.com/token/{slug}”,
“MagicEden”: f”https://magiceden.io/item-details/{slug}”,
}
else:
r[“error”] = f”HTTP {resp.status}”
except asyncio.TimeoutError:
r[“error”] = “Timeout (12s)”
except Exception as e:
r[“error”] = str(e)[:80]
return r

# ════════════════════════════════════════════════════════════════

# 🎨  KEYBOARDS

# ════════════════════════════════════════════════════════════════

def kb_main() -> InlineKeyboardMarkup:
return InlineKeyboardMarkup([
[InlineKeyboardButton(“🔗 جلب NFT”,        callback_data=“info_fetch”),
InlineKeyboardButton(“💎 حسابي”,          callback_data=“do_status”)],
[InlineKeyboardButton(“🛒 المتجر”,          callback_data=“do_shop”),
InlineKeyboardButton(“📜 السجل”,          callback_data=“do_history”)],
[InlineKeyboardButton(“📡 مراقبة NFT”,      callback_data=“info_monitor”),
InlineKeyboardButton(“📤 تصدير CSV”,       callback_data=“do_export”)],
[InlineKeyboardButton(“📊 الإحصائيات”,      callback_data=“do_stats”),
InlineKeyboardButton(“ℹ️ المساعدة”,        callback_data=“do_help”)],
])

def kb_shop() -> InlineKeyboardMarkup:
rows = []
for key, label in FEATURE_LABELS.items():
rows.append([InlineKeyboardButton(
f”{label}  –  {PRICES[key]} ⭐”,
callback_data=f”buy_{key}”
)])
rows.append([InlineKeyboardButton(“◀️ رجوع”, callback_data=“back_main”)])
return InlineKeyboardMarkup(rows)

def kb_back() -> InlineKeyboardMarkup:
return InlineKeyboardMarkup([[InlineKeyboardButton(“◀️ القائمة الرئيسية”, callback_data=“back_main”)]])

def kb_buy(key: str) -> InlineKeyboardMarkup:
return InlineKeyboardMarkup([
[InlineKeyboardButton(f”✅ اشترِ الآن – {PRICES[key]} ⭐”, callback_data=f”buy_{key}”)],
[InlineKeyboardButton(“◀️ رجوع”, callback_data=“do_shop”)],
])

# ════════════════════════════════════════════════════════════════

# 📝  TEXT BUILDERS

# ════════════════════════════════════════════════════════════════

BANNER = “🇷🇺 *NFT Link Fetcher Bot*”

def txt_welcome(uid: int) -> str:
u = get_user(uid)
return f”””
{BANNER}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎁 *بونص الترحيب* – `{FREE_FETCHES + BONUS_FETCHES}` محاولة مجانية
├─ {FREE_FETCHES} أساسية  +  {BONUS_FETCHES} هدية 🎀

🔥 *ما يقدمه البوت:*
• جلب روابط NFT من أكبر المنصات
• استخراج البيانات الكاملة (السعر، Traits، Rarity)
• مراقبة NFT وإشعارات فورية
• دعم OpenSea / Blur / Rarible / Magic Eden / LooksRare

⭐ *مزايا متقدمة بـ Telegram Stars*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
أرسل رابط NFT مباشرةً أو اضغط زر أدناه 👇
“””

def txt_help(uid: int) -> str:
u = get_user(uid)
return f”””
📖 *دليل الاستخدام الكامل*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
*الأوامر:*

🔗 `/fetch <url>` – جلب رابط NFT واحد
📦 `/bulk <url1> <url2> ...` – جلب حتى 10 روابط `(⭐ Bulk)`
📡 `/monitor <url>` – مراقبة NFT `(⭐ Monitor)`
🛑 `/unmonitor <url>` – إيقاف مراقبة NFT
📜 `/history` – سجل آخر 20 رابط `(⭐ History)`
📤 `/export` – تصدير CSV `(⭐ Export)`
💎 `/status` – حالة حسابك والمزايا
🛒 `/shop` – متجر Telegram Stars
📊 `/stats` – إحصائياتك الشخصية
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 *نصيحة:* أرسل الرابط مباشرةً بدون أمر!
🎟 *محاولات متبقية:* `{u['fetches_left']}`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
“””

def txt_status(uid: int) -> str:
u = get_user(uid)
p = u[“premium”]
fmap = {
“bulk”:           (“📦”, “Bulk Fetch”),
“multi_platform”: (“🌐”, “Multi-Platform”),
“monitor”:        (“📡”, “Auto Monitor”),
“metadata”:       (“🔍”, “Metadata Extract”),
“history”:        (“📜”, “History Log”),
“export”:         (“📤”, “Export CSV”),
}
feats = “\n”.join(
f”  {‘✅’ if p.get(k) else ‘❌’} {icon} {name}”
for k, (icon, name) in fmap.items()
)
ulim = “”
if p.get(“unlimited_until”):
until = datetime.fromisoformat(p[“unlimited_until”])
if until > datetime.now():
hrs = int((until - datetime.now()).total_seconds() // 3600)
ulim = f”\n⚡ *Unlimited* نشط – يبقى `{hrs}` ساعة”

```
return f"""
```

💎 *حالة حسابك*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 المعرّف: `{uid}`
📅 انضممت: `{u['joined'][:10]}`
🔢 إجمالي عمليات الجلب: `{u['total_fetches']}`
🎟 محاولات متبقية: `{u['fetches_left']}`{ulim}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
*المزايا المفعّلة:*
{feats}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
“””

def txt_shop() -> str:
lines = []
for key, label in FEATURE_LABELS.items():
lines.append(f”{label} – `{PRICES[key]} ⭐`\n   *{FEATURE_DESC[key]}*\n”)
return f”””
🛒 *متجر المزايا – Telegram Stars*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{’’.join(lines)}━━━━━━━━━━━━━━━━━━━━━━━━━━━━
اضغط على الميزة للشراء 👇
“””

def txt_result(r: dict, fetches_left: int, metadata: bool) -> str:
title   = (r.get(“title”)      or “–”)[:60]
coll    = (r.get(“collection”) or “–”)[:50]
price   = r.get(“price”)   or “غير محدد”
plat    = r.get(“platform”) or “–”
err     = f”\n⚠️ *{r[‘error’]}*” if r.get(“error”) else “”

```
text = f"""
```

✅ *تم جلب رابط NFT*{err}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏷 *العنوان:* {title}
🏛 *المجموعة:* {coll}
🌐 *المنصة:* {plat}
💰 *السعر:* `{price}`
🔗 *الرابط:* `{r['url'][:80]}`
🕐 *وقت الجلب:* `{r['fetched']}`”””

```
if metadata:
    rarity    = r.get("rarity")    or "--"
    last_sale = r.get("last_sale") or "--"
    traits    = r.get("traits")    or []
    text += f"""
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 *Metadata:*
🎲 Rarity: `{rarity}`
💸 Last Sale: `{last_sale}`”””
if traits:
text += “\n   🎨 *Traits:*\n” + “\n”.join(f”   • `{t}`” for t in traits[:6])

```
cross = r.get("cross")
if cross:
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🌐 *روابط متعددة المنصات:*\n"
    for name, link in cross.items():
        text += f"   • [{name}]({link})\n"

text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🎟 *محاولات متبقية:* `{fetches_left}`"
return text
```

def txt_stats(uid: int) -> str:
u    = get_user(uid)
hist = u.get(“history”, [])
mons = len(monitors_db.get(uid, []))

```
platforms = {}
prices_found = 0
for _, res, _ in hist:
    p = res.get("platform", "Unknown")
    platforms[p] = platforms.get(p, 0) + 1
    if res.get("price"):
        prices_found += 1

plat_lines = "\n".join(f"   • {k}: `{v}`" for k, v in sorted(platforms.items(), key=lambda x: -x[1]))

return f"""
```

📊 *إحصائياتك الشخصية*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔢 إجمالي عمليات الجلب: `{u['total_fetches']}`
📁 مخزّن في السجل: `{len(hist)}`
📡 مراقبات نشطة: `{mons}`
💰 روابط وجد لها سعر: `{prices_found}`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
*توزيع المنصات:*
{plat_lines or ’   لا يوجد سجل بعد’}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
“””

# ════════════════════════════════════════════════════════════════

# 🤖  COMMAND HANDLERS

# ════════════════════════════════════════════════════════════════

async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
get_user(u.effective_user.id)
await u.message.reply_text(txt_welcome(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

async def cmd_help(u: Update, c: ContextTypes.DEFAULT_TYPE):
t = u.message or u.callback_query.message
await t.reply_text(txt_help(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_status(u: Update, c: ContextTypes.DEFAULT_TYPE):
t = u.message or u.callback_query.message
await t.reply_text(txt_status(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_shop(u: Update, c: ContextTypes.DEFAULT_TYPE):
t = u.message or u.callback_query.message
await t.reply_text(txt_shop(),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_shop())

async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
t = u.message or u.callback_query.message
await t.reply_text(txt_stats(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_fetch(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid = u.effective_user.id
if not c.args:
await u.message.reply_text(
“⚠️ أرسل رابط NFT:\n`/fetch https://opensea.io/assets/...`”,
parse_mode=ParseMode.MARKDOWN)
return
await do_fetch(u.message, uid, c.args[0])

async def cmd_bulk(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid = u.effective_user.id
if not has_feat(uid, “bulk”):
await u.message.reply_text(
“❌ *Bulk Fetch* غير مفعّل\n\nفعّله من المتجر مقابل `50 ⭐`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“bulk”))
return
urls = (c.args or [])[:10]
if not urls:
await u.message.reply_text(“⚠️ أرسل روابط NFT بعد الأمر (حتى 10)”, parse_mode=ParseMode.MARKDOWN)
return
msg = await u.message.reply_text(f”⏳ جاري معالجة `{len(urls)}` رابط…”, parse_mode=ParseMode.MARKDOWN)
results = []
for url in urls:
if not can_fetch(uid): break
r = await fetch_nft(url, multi=has_feat(uid, “multi”), metadata=has_feat(uid, “metadata”))
consume(uid); save_history(uid, url, r); results.append(r)
text = f”✅ *تم جلب {len(results)} رابط:*\n\n”
for i, r in enumerate(results, 1):
st  = “✅” if not r[“error”] else “❌”
ttl = (r[“title”] or “–”)[:40]
prc = r[“price”] or “–”
text += f”`{i}.` {st} *{ttl}*\n   💰 `{prc}` | 🌐 {r[‘platform’]}\n\n”
await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_monitor(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid = u.effective_user.id
if not has_feat(uid, “monitor”):
await u.message.reply_text(
“❌ *Auto Monitor* غير مفعّل\n\nفعّله من المتجر مقابل `100 ⭐`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“monitor”))
return
if not c.args:
await u.message.reply_text(“⚠️ أرسل رابط NFT:\n`/monitor <url>`”, parse_mode=ParseMode.MARKDOWN)
return
url = c.args[0]
if uid not in monitors_db: monitors_db[uid] = []
if any(m[“url”] == url for m in monitors_db[uid]):
await u.message.reply_text(“ℹ️ هذا الرابط مراقَب بالفعل!”, parse_mode=ParseMode.MARKDOWN)
return
monitors_db[uid].append({“url”: url, “last_price”: None, “added”: datetime.now().isoformat()})
await u.message.reply_text(
f”📡 *تمت إضافة المراقبة!*\n\n🔗 `{url[:80]}`\n\n✅ ستصلك إشعارات فورية عند تغيير السعر.”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_unmonitor(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid = u.effective_user.id
if not c.args:
await u.message.reply_text(“⚠️ أرسل رابط NFT:\n`/unmonitor <url>`”, parse_mode=ParseMode.MARKDOWN)
return
url = c.args[0]
if uid in monitors_db:
before = len(monitors_db[uid])
monitors_db[uid] = [m for m in monitors_db[uid] if m[“url”] != url]
if len(monitors_db[uid]) < before:
await u.message.reply_text(“🛑 تم إيقاف المراقبة بنجاح.”, parse_mode=ParseMode.MARKDOWN)
return
await u.message.reply_text(“❌ الرابط غير موجود في قائمة المراقبة.”, parse_mode=ParseMode.MARKDOWN)

async def cmd_history(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid = u.effective_user.id
msg = u.message or (u.callback_query.message if u.callback_query else None)
if not has_feat(uid, “history”):
await msg.reply_text(
“❌ *History Log* غير مفعّل\n\nفعّله من المتجر مقابل `25 ⭐`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“history”))
return
hist = get_user(uid)[“history”][-20:]
if not hist:
await msg.reply_text(“📭 السجل فارغ حتى الآن.”, parse_mode=ParseMode.MARKDOWN)
return
text = “📜 *آخر 20 رابط تم جلبها:*\n\n”
for i, (url, r, ts) in enumerate(reversed(hist), 1):
ttl = (r.get(“title”) or “–”)[:35]
prc = r.get(“price”) or “–”
text += f”`{i}.` *{ttl}*\n   💰 `{prc}` | 🕐 `{ts[:16]}`\n   🔗 `{url[:55]}...`\n\n”
await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_export(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid = u.effective_user.id
msg = u.message or (u.callback_query.message if u.callback_query else None)
if not has_feat(uid, “export”):
await msg.reply_text(
“❌ *Export CSV* غير مفعّل\n\nفعّله من المتجر مقابل `35 ⭐`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“export”))
return
hist = get_user(uid)[“history”]
if not hist:
await msg.reply_text(“📭 لا يوجد سجل للتصدير.”, parse_mode=ParseMode.MARKDOWN)
return
out = io.StringIO()
w = csv.writer(out)
w.writerow([”#”, “URL”, “Title”, “Platform”, “Price”, “Collection”, “Rarity”, “Timestamp”])
for i, (url, r, ts) in enumerate(hist, 1):
w.writerow([i, url, r.get(“title”,””), r.get(“platform”,””),
r.get(“price”,””), r.get(“collection”,””), r.get(“rarity”,””), ts])
out.seek(0)
fname = f”nft_history_{uid}*{datetime.now().strftime(’%Y%m%d*%H%M%S’)}.csv”
await msg.reply_document(
document=out.getvalue().encode(“utf-8-sig”), filename=fname,
caption=f”📤 *تم تصدير {len(hist)} رابط بنجاح!*”,
parse_mode=ParseMode.MARKDOWN)

# ════════════════════════════════════════════════════════════════

# 🔗  CORE FETCH

# ════════════════════════════════════════════════════════════════

async def do_fetch(msg, uid: int, url: str):
if not can_fetch(uid):
await msg.reply_text(
“🚫 *انتهت محاولاتك المجانية!*\n\nاشترِ *Unlimited 24h* بـ `150 ⭐` لمحاولات غير محدودة.”,
parse_mode=ParseMode.MARKDOWN,
reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(“🛒 اشترِ الآن”, callback_data=“buy_unlimited”)]]))
return
m = await msg.reply_text(“⏳ *جاري الجلب…*”, parse_mode=ParseMode.MARKDOWN)
r = await fetch_nft(url, multi=has_feat(uid, “multi”), metadata=has_feat(uid, “metadata”))
consume(uid)
save_history(uid, url, r)
text = txt_result(r, get_user(uid)[“fetches_left”], has_feat(uid, “metadata”))
await m.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

# ════════════════════════════════════════════════════════════════

# 💬  MESSAGE HANDLER (رابط مباشر بدون أمر)

# ════════════════════════════════════════════════════════════════

async def handle_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid  = u.effective_user.id
text = u.message.text.strip()
if text.startswith(“http”) and any(d in text for d in PLATFORMS.values()):
await do_fetch(u.message, uid, text)
else:
await u.message.reply_text(
“💬 أرسل رابط NFT مباشرةً أو اختر من القائمة 👇”,
reply_markup=kb_main())

# ════════════════════════════════════════════════════════════════

# 🔘  CALLBACK QUERY HANDLER

# ════════════════════════════════════════════════════════════════

async def handle_cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
q   = u.callback_query
uid = q.from_user.id
d   = q.data
await q.answer()

```
async def edit(text, kb=None):
    await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN,
                              reply_markup=kb or kb_back())

if d == "back_main":
    await q.message.edit_text("🏠 *القائمة الرئيسية* -- اختر ما تريد:",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
elif d == "do_status":  await edit(txt_status(uid))
elif d == "do_shop":    await edit(txt_shop(), kb_shop())
elif d == "do_help":    await edit(txt_help(uid))
elif d == "do_stats":   await edit(txt_stats(uid))
elif d == "info_fetch":
    await edit("🔗 *جلب رابط NFT*\n\nأرسل الرابط مباشرةً أو:\n`/fetch https://opensea.io/assets/...`")
elif d == "info_monitor":
    await edit("📡 *Auto Monitor*\n\nأرسل:\n`/monitor https://opensea.io/assets/...`")
elif d == "do_history":
    class FU:
        message = q.message
        effective_user = q.from_user
        callback_query = q
    await cmd_history(FU(), c)
elif d == "do_export":
    class FU:
        message = q.message
        effective_user = q.from_user
        callback_query = q
    await cmd_export(FU(), c)
elif d.startswith("buy_"):
    feat = d[4:]
    await c.bot.send_invoice(
        chat_id=uid,
        title=FEATURE_LABELS.get(feat, feat),
        description=FEATURE_DESC.get(feat, ""),
        payload=f"feat_{feat}_{uid}",
        currency="XTR",
        prices=[LabeledPrice(label=FEATURE_LABELS.get(feat, feat), amount=PRICES.get(feat, 50))],
        provider_token="",
    )
```

# ════════════════════════════════════════════════════════════════

# 💳  PAYMENT HANDLERS

# ════════════════════════════════════════════════════════════════

async def pre_checkout(u: Update, c: ContextTypes.DEFAULT_TYPE):
await u.pre_checkout_query.answer(ok=True)

async def payment_done(u: Update, c: ContextTypes.DEFAULT_TYPE):
uid     = u.effective_user.id
payload = u.message.successful_payment.invoice_payload
user    = get_user(uid)

```
feat_map = {
    "feat_bulk":      "bulk",
    "feat_multi":     "multi_platform",
    "feat_monitor":   "monitor",
    "feat_metadata":  "metadata",
    "feat_history":   "history",
    "feat_export":    "export",
    "feat_unlimited": "unlimited",
}
for key, feat in feat_map.items():
    if payload.startswith(key):
        if feat == "unlimited":
            user["premium"]["unlimited_until"] = (datetime.now() + timedelta(hours=24)).isoformat()
        else:
            user["premium"][feat] = True
        label = FEATURE_LABELS.get(key.replace("feat_", ""), feat)
        await u.message.reply_text(
            f"🎉 *تم تفعيل {label} بنجاح!*\n\n✅ يمكنك استخدام الميزة الآن.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
        return
```

# ════════════════════════════════════════════════════════════════

# 👑  ADMIN COMMANDS

# ════════════════════════════════════════════════════════════════

async def cmd_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
if u.effective_user.id not in ADMIN_IDS: return
total   = len(users_db)
fetches = sum(x[“total_fetches”] for x in users_db.values())
premium = sum(1 for x in users_db.values() if any(x[“premium”].values()))
mons    = sum(len(v) for v in monitors_db.values())
await u.message.reply_text(f”””
👑 *لوحة الأدمن*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👥 إجمالي المستخدمين: `{total}`
🔢 إجمالي عمليات الجلب: `{fetches}`
💎 مستخدمو البريميوم: `{premium}`
📡 مراقبات نشطة: `{mons}`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
“””, parse_mode=ParseMode.MARKDOWN)

async def cmd_give(u: Update, c: ContextTypes.DEFAULT_TYPE):
“””/give <uid> <feature>”””
if u.effective_user.id not in ADMIN_IDS: return
if len(c.args) < 2:
await u.message.reply_text(“⚠️ `/give <uid> <feature>`”, parse_mode=ParseMode.MARKDOWN)
return
tuid = int(c.args[0]); feat = c.args[1]; usr = get_user(tuid)
if feat in usr[“premium”]:
usr[“premium”][feat] = True
await u.message.reply_text(f”✅ فعّلت `{feat}` للمستخدم `{tuid}`”, parse_mode=ParseMode.MARKDOWN)
else:
await u.message.reply_text(f”❌ ميزة غير معروفة: `{feat}`”, parse_mode=ParseMode.MARKDOWN)

async def cmd_broadcast(u: Update, c: ContextTypes.DEFAULT_TYPE):
“””/broadcast <message>”””
if u.effective_user.id not in ADMIN_IDS: return
if not c.args:
await u.message.reply_text(“⚠️ `/broadcast <رسالة>`”, parse_mode=ParseMode.MARKDOWN)
return
text = “ “.join(c.args)
sent = 0
for uid in list(users_db.keys()):
try:
await c.bot.send_message(uid, f”📢 *إعلان من الإدارة:*\n\n{text}”,
parse_mode=ParseMode.MARKDOWN)
sent += 1
except Exception:
pass
await u.message.reply_text(f”✅ تم الإرسال لـ `{sent}` مستخدم.”, parse_mode=ParseMode.MARKDOWN)

# ════════════════════════════════════════════════════════════════

# 📡  BACKGROUND MONITOR LOOP

# ════════════════════════════════════════════════════════════════

async def monitor_loop(app: Application):
“”“يشتغل كل 5 دقائق ويفحص تغيير أسعار NFT المراقبة”””
while True:
await asyncio.sleep(300)  # 5 دقائق
for uid, items in list(monitors_db.items()):
for item in items:
try:
r = await fetch_nft(item[“url”])
new_price = r.get(“price”)
old_price = item.get(“last_price”)
if new_price and new_price != old_price:
item[“last_price”] = new_price
title = (r.get(“title”) or item[“url”][:40])[:50]
change = “📈 ارتفع” if old_price else “🔔 أول سعر مرصود”
await app.bot.send_message(
uid,
f”📡 *تنبيه مراقبة NFT!*\n\n”
f”🏷 *{title}*\n”
f”{change}: `{old_price or '--'}` → `{new_price}`\n”
f”🔗 {item[‘url’][:60]}”,
parse_mode=ParseMode.MARKDOWN,
)
except Exception:
pass

# ════════════════════════════════════════════════════════════════

# 🏗️  BUILD BOT APP

# ════════════════════════════════════════════════════════════════

def build_bot() -> Application:
app = Application.builder().token(BOT_TOKEN).build()

```
app.add_handler(CommandHandler("start",      cmd_start))
app.add_handler(CommandHandler("help",       cmd_help))
app.add_handler(CommandHandler("status",     cmd_status))
app.add_handler(CommandHandler("shop",       cmd_shop))
app.add_handler(CommandHandler("fetch",      cmd_fetch))
app.add_handler(CommandHandler("bulk",       cmd_bulk))
app.add_handler(CommandHandler("monitor",    cmd_monitor))
app.add_handler(CommandHandler("unmonitor",  cmd_unmonitor))
app.add_handler(CommandHandler("history",    cmd_history))
app.add_handler(CommandHandler("export",     cmd_export))
app.add_handler(CommandHandler("stats",      cmd_stats))
app.add_handler(CommandHandler("admin",      cmd_admin))
app.add_handler(CommandHandler("give",       cmd_give))
app.add_handler(CommandHandler("broadcast",  cmd_broadcast))

app.add_handler(PreCheckoutQueryHandler(pre_checkout))
app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_done))
app.add_handler(CallbackQueryHandler(handle_cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

return app
```

# ════════════════════════════════════════════════════════════════

# 🌐  FLASK KEEP-ALIVE SERVER

# ════════════════════════════════════════════════════════════════

flask_app = Flask(**name**)
_start_time = datetime.now()

@flask_app.route(”/”)
def home():
up = str(datetime.now() - _start_time).split(”.”)[0]
return jsonify({“status”: “🟢 online”, “bot”: “NFT Link Fetcher Bot”,
“uptime”: up, “users”: len(users_db),
“timestamp”: datetime.now().isoformat()})

@flask_app.route(”/health”)
def health():
return jsonify({“status”: “ok”}), 200

@flask_app.route(”/ping”)
def ping():
return “pong”, 200

# ════════════════════════════════════════════════════════════════

# 🚀  LAUNCH

# ════════════════════════════════════════════════════════════════

def self_ping():
“”“Render Free يوقف الخدمة بعد 15 دقيقة – نرسل ping كل 14 دقيقة”””
import urllib.request
url = os.getenv(“RENDER_EXTERNAL_URL”, “http://localhost:8080”) + “/ping”
while True:
time.sleep(14 * 60)
try:
urllib.request.urlopen(url, timeout=10)
logging.info(f”🏓 Self-ping OK → {url}”)
except Exception as e:
logging.warning(f”⚠️ Self-ping failed: {e}”)

def run_bot_thread():
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
bot_app = build_bot()

```
async def main():
    async with bot_app:
        await bot_app.initialize()
        await bot_app.start()
        # شغّل monitor في الخلفية
        asyncio.create_task(monitor_loop(bot_app))
        await bot_app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()   # انتظر إلى الأبد

loop.run_until_complete(main())
```

if **name** == “**main**”:
logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s | %(levelname)s | %(name)s | %(message)s”
)
logging.getLogger(“httpx”).setLevel(logging.WARNING)

```
# Thread 1: Telegram Bot + Monitor Loop
t_bot = threading.Thread(target=run_bot_thread, daemon=True, name="BotThread")
t_bot.start()
logging.info("✅ Bot thread launched")

# Thread 2: Self-Ping
t_ping = threading.Thread(target=self_ping, daemon=True, name="PingThread")
t_ping.start()
logging.info("✅ Self-ping thread launched")

# Main: Flask
port = int(os.getenv("PORT", 8080))
logging.info(f"✅ Flask running on port {port}")
flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
```
