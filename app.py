# -*- coding: utf-8 -*-

# NFT Link Fetcher Bot - @NftGrabberBot

# Single file: Telegram Bot + Flask Keep-Alive

import os
import re
import csv
import io
import time
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import (
Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.ext import (
Application, CommandHandler, MessageHandler,
CallbackQueryHandler, ContextTypes,
PreCheckoutQueryHandler, filters
)
from telegram.constants import ParseMode
import aiohttp

# ==============================================================

# CONFIG

# ==============================================================

BOT_TOKEN = os.getenv(“BOT_TOKEN”, “8195283120:AAHdMCVVnTin3mwfSHivg4I1kU0vND2TulA”)
ADMIN_IDS = [int(x) for x in os.getenv(“ADMIN_IDS”, “7825994636”).split(”,”)]

FREE_FETCHES = 3
BONUS_FETCHES = 2

PRICES = {
“bulk”: 50,
“multi”: 30,
“monitor”: 100,
“metadata”: 40,
“history”: 25,
“export”: 35,
“unlimited”: 150,
}

FEATURE_LABELS = {
“bulk”:      “Bulk Fetch”,
“multi”:     “Multi-Platform”,
“monitor”:   “Auto Monitor”,
“metadata”:  “Metadata Extract”,
“history”:   “History Log”,
“export”:    “Export CSV”,
“unlimited”: “Unlimited 24h”,
}

FEATURE_ICONS = {
“bulk”:      “\U0001f4e6”,
“multi”:     “\U0001f310”,
“monitor”:   “\U0001f4e1”,
“metadata”:  “\U0001f50d”,
“history”:   “\U0001f4dc”,
“export”:    “\U0001f4e4”,
“unlimited”: “\u26a1”,
}

FEATURE_DESC = {
“bulk”:      “Fetch up to 10 NFT links at once”,
“multi”:     “Search OpenSea + Blur + Rarible + Magic Eden”,
“monitor”:   “Instant alerts when NFT price changes”,
“metadata”:  “Extract Traits, Rarity, transaction history”,
“history”:   “Save and view last 20 fetched links”,
“export”:    “Export full history as CSV file”,
“unlimited”: “Unlimited fetches for 24 hours”,
}

# ==============================================================

# DATABASE (in-memory)

# ==============================================================

users_db = {}
monitors_db = {}

def get_user(uid):
if uid not in users_db:
users_db[uid] = {
“id”: uid,
“fetches_left”: FREE_FETCHES + BONUS_FETCHES,
“total_fetches”: 0,
“joined”: datetime.now().isoformat(),
“premium”: {
“bulk”: False,
“multi_platform”: False,
“monitor”: False,
“metadata”: False,
“history”: False,
“export”: False,
“unlimited_until”: None,
},
“history”: [],
}
return users_db[uid]

def is_unlimited(uid):
u = get_user(uid)
until = u[“premium”].get(“unlimited_until”)
if until and datetime.fromisoformat(until) > datetime.now():
return True
return False

def has_feat(uid, feat):
if feat == “unlimited”:
return is_unlimited(uid)
return get_user(uid)[“premium”].get(feat, False)

def can_fetch(uid):
return is_unlimited(uid) or get_user(uid)[“fetches_left”] > 0

def consume(uid):
u = get_user(uid)
if not is_unlimited(uid):
u[“fetches_left”] = max(0, u[“fetches_left”] - 1)
u[“total_fetches”] += 1

def save_history(uid, url, result):
u = get_user(uid)
if has_feat(uid, “history”) or has_feat(uid, “export”):
u[“history”].append((url, result, datetime.now().isoformat()))
if len(u[“history”]) > 500:
u[“history”] = u[“history”][-500:]

# ==============================================================

# NFT FETCHER ENGINE

# ==============================================================

PLATFORMS = {
“opensea”: “opensea.io”,
“blur”: “blur.io”,
“rarible”: “rarible.com”,
“magiceden”: “magiceden.io”,
“looksrare”: “looksrare.org”,
}

def detect_platform(url):
for name, domain in PLATFORMS.items():
if domain in url.lower():
return name.capitalize()
return “Unknown”

def ex_meta(html, prop):
patterns = [
r’property=[”']og:’ + prop + r’[”'][^>]+content=[”'](.*?)[”']’,
r’name=[”']+’ + prop + r’[”'][^>]+content=[”'](.*?)[”']’,
r’<title>(.*?)</title>’,
]
for pat in patterns:
m = re.search(pat, html, re.I | re.S)
if m:
return re.sub(r’<[^>]+>’, ‘’, m.group(1)).strip()[:200]
return None

def ex_price(html):
m = re.search(r’(\d+.?\d{0,6})\s*(ETH|SOL|MATIC|BTC|USDC)’, html, re.I)
return “{} {}”.format(m.group(1), m.group(2).upper()) if m else None

def ex_traits(html):
raw = re.findall(r’“trait_type”\s*:\s*”([^”]+)”.*?“value”\s*:\s*”([^”]+)”’, html)
return [”{}: {}”.format(k, v) for k, v in raw[:8]]

def ex_rarity(html):
m = re.search(r’(?:rarity|rank)[^0-9]{0,20}(\d+)’, html, re.I)
return “Rank #{}”.format(m.group(1)) if m else None

async def fetch_nft(url, multi=False, metadata=False):
r = {
“url”: url,
“platform”: detect_platform(url),
“title”: None,
“collection”: None,
“price”: None,
“image”: None,
“rarity”: None,
“traits”: [],
“last_sale”: None,
“cross”: {} if multi else None,
“fetched”: datetime.now().strftime(”%Y-%m-%d %H:%M”),
“error”: None,
}
try:
hdrs = {“User-Agent”: “Mozilla/5.0 (compatible; NFTBot/2.0)”}
async with aiohttp.ClientSession() as s:
async with s.get(url, headers=hdrs, timeout=aiohttp.ClientTimeout(total=12)) as resp:
if resp.status == 200:
html = await resp.text()
r[“title”] = ex_meta(html, “title”)
r[“collection”] = ex_meta(html, “site_name”)
r[“image”] = ex_meta(html, “image”)
r[“price”] = ex_price(html)
if metadata:
r[“traits”] = ex_traits(html)
r[“rarity”] = ex_rarity(html)
sale = re.search(
r’(?:last.sale|sold.for)[^0-9]{0,30}(\d+.?\d*\s*(?:ETH|SOL))’,
html, re.I)
r[“last_sale”] = sale.group(1) if sale else None
if multi and r[“title”]:
slug = re.sub(r’[^a-z0-9]’, ‘-’, r[“title”].lower())[:40]
r[“cross”] = {
“OpenSea”: “https://opensea.io/assets/ethereum/{}”.format(slug),
“Blur”: “https://blur.io/asset/{}”.format(slug),
“Rarible”: “https://rarible.com/token/{}”.format(slug),
“MagicEden”: “https://magiceden.io/item-details/{}”.format(slug),
}
else:
r[“error”] = “HTTP {}”.format(resp.status)
except asyncio.TimeoutError:
r[“error”] = “Timeout (12s)”
except Exception as e:
r[“error”] = str(e)[:80]
return r

# ==============================================================

# KEYBOARDS

# ==============================================================

def kb_main():
return InlineKeyboardMarkup([
[
InlineKeyboardButton(”\U0001f517 Fetch NFT”, callback_data=“info_fetch”),
InlineKeyboardButton(”\U0001f48e My Account”, callback_data=“do_status”),
],
[
InlineKeyboardButton(”\U0001f6d2 Shop”, callback_data=“do_shop”),
InlineKeyboardButton(”\U0001f4dc History”, callback_data=“do_history”),
],
[
InlineKeyboardButton(”\U0001f4e1 Monitor NFT”, callback_data=“info_monitor”),
InlineKeyboardButton(”\U0001f4e4 Export CSV”, callback_data=“do_export”),
],
[
InlineKeyboardButton(”\U0001f4ca Stats”, callback_data=“do_stats”),
InlineKeyboardButton(”\u2139\ufe0f Help”, callback_data=“do_help”),
],
])

def kb_shop():
rows = []
for key in FEATURE_LABELS:
icon = FEATURE_ICONS[key]
label = FEATURE_LABELS[key]
price = PRICES[key]
rows.append([InlineKeyboardButton(
“{} {}  –  {} \u2b50”.format(icon, label, price),
callback_data=“buy_{}”.format(key)
)])
rows.append([InlineKeyboardButton(”\u25c0\ufe0f Back”, callback_data=“back_main”)])
return InlineKeyboardMarkup(rows)

def kb_back():
return InlineKeyboardMarkup([[
InlineKeyboardButton(”\u25c0\ufe0f Main Menu”, callback_data=“back_main”)
]])

def kb_buy(key):
return InlineKeyboardMarkup([
[InlineKeyboardButton(
“\u2705 Buy Now – {} \u2b50”.format(PRICES[key]),
callback_data=“buy_{}”.format(key)
)],
[InlineKeyboardButton(”\u25c0\ufe0f Back”, callback_data=“do_shop”)],
])

# ==============================================================

# TEXT BUILDERS

# ==============================================================

SEP = “-” * 32

def txt_welcome(uid):
total = FREE_FETCHES + BONUS_FETCHES
return (
“\U0001f1f7\U0001f1fa *NFT Link Fetcher Bot*\n”
“{}\n”
“\U0001f381 *Welcome Bonus:* `{}` free fetches\n”
“   {} basic + {} gift \U0001f380\n\n”
“\U0001f525 *What this bot does:*\n”
“- Fetch NFT links from major platforms\n”
“- Extract full data (price, traits, rarity)\n”
“- Monitor NFTs and get instant alerts\n”
“- Support for OpenSea / Blur / Rarible / Magic Eden\n\n”
“\u2b50 *Premium features via Telegram Stars*\n”
“{}\n”
“Send an NFT link directly or choose below:”
).format(SEP, total, FREE_FETCHES, BONUS_FETCHES, SEP)

def txt_help(uid):
u = get_user(uid)
return (
“\U0001f4d6 *Full Usage Guide*\n”
“{}\n”
“*Commands:*\n\n”
“\U0001f517 `/fetch <url>` – Fetch one NFT link\n”
“\U0001f4e6 `/bulk <url1> <url2> ...` – Fetch up to 10 `(\u2b50 Bulk)`\n”
“\U0001f4e1 `/monitor <url>` – Monitor NFT `(\u2b50 Monitor)`\n”
“\U0001f6d1 `/unmonitor <url>` – Stop monitoring\n”
“\U0001f4dc `/history` – Last 20 fetched links `(\u2b50 History)`\n”
“\U0001f4e4 `/export` – Export as CSV `(\u2b50 Export)`\n”
“\U0001f48e `/status` – Your account and features\n”
“\U0001f6d2 `/shop` – Telegram Stars store\n”
“\U0001f4ca `/stats` – Personal statistics\n”
“{}\n”
“\U0001f4a1 *Tip:* Send a link directly without any command!\n”
“\U0001f39f *Fetches left:* `{}`\n”
“{}”
).format(SEP, SEP, u[“fetches_left”], SEP)

def txt_status(uid):
u = get_user(uid)
p = u[“premium”]
fmap = [
(“bulk”, “\U0001f4e6”, “Bulk Fetch”),
(“multi_platform”, “\U0001f310”, “Multi-Platform”),
(“monitor”, “\U0001f4e1”, “Auto Monitor”),
(“metadata”, “\U0001f50d”, “Metadata Extract”),
(“history”, “\U0001f4dc”, “History Log”),
(“export”, “\U0001f4e4”, “Export CSV”),
]
feats = “\n”.join(
“  {} {} {}”.format(”\u2705” if p.get(k) else “\u274c”, icon, name)
for k, icon, name in fmap
)
ulim = “”
if p.get(“unlimited_until”):
until = datetime.fromisoformat(p[“unlimited_until”])
if until > datetime.now():
hrs = int((until - datetime.now()).total_seconds() // 3600)
ulim = “\n\u26a1 *Unlimited* active – `{}` hours left”.format(hrs)

```
return (
    "\U0001f48e *Your Account*\n"
    "{}\n"
    "\U0001f464 ID: `{}`\n"
    "\U0001f4c5 Joined: `{}`\n"
    "\U0001f522 Total fetches: `{}`\n"
    "\U0001f39f Fetches left: `{}`{}\n"
    "{}\n"
    "*Active Features:*\n"
    "{}\n"
    "{}"
).format(SEP, uid, u["joined"][:10], u["total_fetches"], u["fetches_left"],
         ulim, SEP, feats, SEP)
```

def txt_shop():
lines = []
for key in FEATURE_LABELS:
icon = FEATURE_ICONS[key]
label = FEATURE_LABELS[key]
price = PRICES[key]
desc = FEATURE_DESC[key]
lines.append(”{} *{}* – `{} \u2b50`\n   *{}*\n”.format(icon, label, price, desc))
return (
“\U0001f6d2 *Feature Shop – Telegram Stars*\n”
“{}\n”
“{}”
“{}\n”
“Tap a feature to purchase:”
).format(SEP, “\n”.join(lines), SEP)

def txt_result(r, fetches_left, metadata):
title = (r.get(“title”) or “–”)[:60]
coll = (r.get(“collection”) or “–”)[:50]
price = r.get(“price”) or “Not found”
plat = r.get(“platform”) or “–”
err = “\n\u26a0\ufe0f *{}* “.format(r[“error”]) if r.get(“error”) else “”

```
text = (
    "\u2705 *NFT Link Fetched*{}\n"
    "{}\n"
    "\U0001f3f7 *Title:* {}\n"
    "\U0001f3db *Collection:* {}\n"
    "\U0001f310 *Platform:* {}\n"
    "\U0001f4b0 *Price:* `{}`\n"
    "\U0001f517 *Link:* `{}`\n"
    "\U0001f550 *Fetched:* `{}`"
).format(err, SEP, title, coll, plat, price, r["url"][:80], r["fetched"])

if metadata:
    rarity = r.get("rarity") or "--"
    last_sale = r.get("last_sale") or "--"
    traits = r.get("traits") or []
    text += "\n{}\n\U0001f50d *Metadata:*\n   \U0001f3b2 Rarity: `{}`\n   \U0001f4b8 Last Sale: `{}`".format(
        SEP, rarity, last_sale)
    if traits:
        text += "\n   \U0001f3a8 *Traits:*\n" + "\n".join("   - `{}`".format(t) for t in traits[:6])

cross = r.get("cross")
if cross:
    text += "\n{}\n\U0001f310 *Cross-Platform Links:*\n".format(SEP)
    for name, link in cross.items():
        text += "   - [{}]({})\n".format(name, link)

text += "\n{}\n\U0001f39f *Fetches left:* `{}`".format(SEP, fetches_left)
return text
```

def txt_stats(uid):
u = get_user(uid)
hist = u.get(“history”, [])
mons = len(monitors_db.get(uid, []))
platforms = {}
prices_found = 0
for _, res, _ in hist:
p = res.get(“platform”, “Unknown”)
platforms[p] = platforms.get(p, 0) + 1
if res.get(“price”):
prices_found += 1
plat_lines = “\n”.join(
“   - {}: `{}`”.format(k, v)
for k, v in sorted(platforms.items(), key=lambda x: -x[1])
)
return (
“\U0001f4ca *Your Stats*\n”
“{}\n”
“\U0001f522 Total fetches: `{}`\n”
“\U0001f4c1 Saved in history: `{}`\n”
“\U0001f4e1 Active monitors: `{}`\n”
“\U0001f4b0 Links with price found: `{}`\n”
“{}\n”
“*Platforms breakdown:*\n”
“{}\n”
“{}”
).format(SEP, u[“total_fetches”], len(hist), mons, prices_found,
SEP, plat_lines or “   No history yet”, SEP)

# ==============================================================

# COMMAND HANDLERS

# ==============================================================

async def cmd_start(u, c):
get_user(u.effective_user.id)
await u.message.reply_text(
txt_welcome(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN,
reply_markup=kb_main()
)

async def cmd_help(u, c):
t = u.message
await t.reply_text(txt_help(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_status(u, c):
t = u.message
await t.reply_text(txt_status(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_shop(u, c):
t = u.message
await t.reply_text(txt_shop(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_shop())

async def cmd_stats(u, c):
t = u.message
await t.reply_text(txt_stats(u.effective_user.id),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_fetch(u, c):
uid = u.effective_user.id
if not c.args:
await u.message.reply_text(
“\u26a0\ufe0f Send an NFT link:\n`/fetch https://opensea.io/assets/...`”,
parse_mode=ParseMode.MARKDOWN)
return
await do_fetch(u.message, uid, c.args[0])

async def cmd_bulk(u, c):
uid = u.effective_user.id
if not has_feat(uid, “bulk”):
await u.message.reply_text(
“\u274c *Bulk Fetch* not active\n\nActivate from shop for `50 \u2b50`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“bulk”))
return
urls = (c.args or [])[:10]
if not urls:
await u.message.reply_text(
“\u26a0\ufe0f Send NFT links after command (up to 10)”,
parse_mode=ParseMode.MARKDOWN)
return
msg = await u.message.reply_text(
“\u23f3 Processing `{}` links…”.format(len(urls)),
parse_mode=ParseMode.MARKDOWN)
results = []
for url in urls:
if not can_fetch(uid):
break
r = await fetch_nft(url, multi=has_feat(uid, “multi”), metadata=has_feat(uid, “metadata”))
consume(uid)
save_history(uid, url, r)
results.append(r)
text = “\u2705 *Fetched {} links:*\n\n”.format(len(results))
for i, r in enumerate(results, 1):
st = “\u2705” if not r[“error”] else “\u274c”
ttl = (r[“title”] or “–”)[:40]
prc = r[“price”] or “–”
text += “`{}.` {} *{}*\n   \U0001f4b0 `{}` | \U0001f310 {}\n\n”.format(
i, st, ttl, prc, r[“platform”])
await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_monitor(u, c):
uid = u.effective_user.id
if not has_feat(uid, “monitor”):
await u.message.reply_text(
“\u274c *Auto Monitor* not active\n\nActivate from shop for `100 \u2b50`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“monitor”))
return
if not c.args:
await u.message.reply_text(
“\u26a0\ufe0f Send NFT link:\n`/monitor <url>`”,
parse_mode=ParseMode.MARKDOWN)
return
url = c.args[0]
if uid not in monitors_db:
monitors_db[uid] = []
if any(m[“url”] == url for m in monitors_db[uid]):
await u.message.reply_text(”\u2139\ufe0f This link is already being monitored!”,
parse_mode=ParseMode.MARKDOWN)
return
monitors_db[uid].append({“url”: url, “last_price”: None, “added”: datetime.now().isoformat()})
await u.message.reply_text(
“\U0001f4e1 *Monitor Added!*\n\n\U0001f517 `{}`\n\n\u2705 You will get instant alerts when price changes.”.format(url[:80]),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_unmonitor(u, c):
uid = u.effective_user.id
if not c.args:
await u.message.reply_text(
“\u26a0\ufe0f Send NFT link:\n`/unmonitor <url>`”,
parse_mode=ParseMode.MARKDOWN)
return
url = c.args[0]
if uid in monitors_db:
before = len(monitors_db[uid])
monitors_db[uid] = [m for m in monitors_db[uid] if m[“url”] != url]
if len(monitors_db[uid]) < before:
await u.message.reply_text(”\U0001f6d1 Monitor removed successfully.”,
parse_mode=ParseMode.MARKDOWN)
return
await u.message.reply_text(”\u274c Link not found in your monitor list.”,
parse_mode=ParseMode.MARKDOWN)

async def cmd_history(u, c):
uid = u.effective_user.id
msg = u.message
if not has_feat(uid, “history”):
await msg.reply_text(
“\u274c *History Log* not active\n\nActivate from shop for `25 \u2b50`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“history”))
return
hist = get_user(uid)[“history”][-20:]
if not hist:
await msg.reply_text(”\U0001f4ed History is empty.”, parse_mode=ParseMode.MARKDOWN)
return
text = “\U0001f4dc *Last 20 fetched links:*\n\n”
for i, (url, r, ts) in enumerate(reversed(hist), 1):
ttl = (r.get(“title”) or “–”)[:35]
prc = r.get(“price”) or “–”
text += “`{}.` *{}*\n   \U0001f4b0 `{}` | \U0001f550 `{}`\n   \U0001f517 `{}...`\n\n”.format(
i, ttl, prc, ts[:16], url[:55])
await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_export(u, c):
uid = u.effective_user.id
msg = u.message
if not has_feat(uid, “export”):
await msg.reply_text(
“\u274c *Export CSV* not active\n\nActivate from shop for `35 \u2b50`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“export”))
return
hist = get_user(uid)[“history”]
if not hist:
await msg.reply_text(”\U0001f4ed No history to export.”, parse_mode=ParseMode.MARKDOWN)
return
out = io.StringIO()
w = csv.writer(out)
w.writerow([”#”, “URL”, “Title”, “Platform”, “Price”, “Collection”, “Rarity”, “Timestamp”])
for i, (url, r, ts) in enumerate(hist, 1):
w.writerow([i, url, r.get(“title”, “”), r.get(“platform”, “”),
r.get(“price”, “”), r.get(“collection”, “”), r.get(“rarity”, “”), ts])
out.seek(0)
fname = “nft_history_{}*{}.csv”.format(uid, datetime.now().strftime(”%Y%m%d*%H%M%S”))
await msg.reply_document(
document=out.getvalue().encode(“utf-8-sig”),
filename=fname,
caption=”\U0001f4e4 *Exported {} links successfully!*”.format(len(hist)),
parse_mode=ParseMode.MARKDOWN)

# ==============================================================

# CORE FETCH

# ==============================================================

async def do_fetch(msg, uid, url):
if not can_fetch(uid):
await msg.reply_text(
“\U0001f6ab *No fetches left!*\n\nBuy *Unlimited 24h* for `150 \u2b50`.”,
parse_mode=ParseMode.MARKDOWN,
reply_markup=InlineKeyboardMarkup([[
InlineKeyboardButton(”\U0001f6d2 Buy Now”, callback_data=“buy_unlimited”)
]]))
return
m = await msg.reply_text(”\u23f3 *Fetching…*”, parse_mode=ParseMode.MARKDOWN)
r = await fetch_nft(url, multi=has_feat(uid, “multi”), metadata=has_feat(uid, “metadata”))
consume(uid)
save_history(uid, url, r)
text = txt_result(r, get_user(uid)[“fetches_left”], has_feat(uid, “metadata”))
await m.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

# ==============================================================

# MESSAGE HANDLER

# ==============================================================

async def handle_msg(u, c):
uid = u.effective_user.id
text = u.message.text.strip()
if text.startswith(“http”) and any(d in text for d in PLATFORMS.values()):
await do_fetch(u.message, uid, text)
else:
await u.message.reply_text(
“Send an NFT link directly or choose from the menu:”,
reply_markup=kb_main())

# ==============================================================

# CALLBACK QUERY HANDLER

# ==============================================================

async def handle_cb(u, c):
q = u.callback_query
uid = q.from_user.id
d = q.data
await q.answer()

```
async def edit(text, kb=None):
    await q.message.edit_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb or kb_back())

if d == "back_main":
    await q.message.edit_text(
        "\U0001f3e0 *Main Menu* -- Choose an option:",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
elif d == "do_status":
    await edit(txt_status(uid))
elif d == "do_shop":
    await edit(txt_shop(), kb_shop())
elif d == "do_help":
    await edit(txt_help(uid))
elif d == "do_stats":
    await edit(txt_stats(uid))
elif d == "info_fetch":
    await edit(
        "\U0001f517 *Fetch NFT Link*\n\nSend the link directly or use:\n`/fetch https://opensea.io/assets/...`")
elif d == "info_monitor":
    await edit(
        "\U0001f4e1 *Auto Monitor*\n\nSend:\n`/monitor https://opensea.io/assets/...`")
elif d == "do_history":
    await cmd_history_cb(q, c)
elif d == "do_export":
    await cmd_export_cb(q, c)
elif d.startswith("buy_"):
    feat = d[4:]
    icon = FEATURE_ICONS.get(feat, "")
    label = "{} {}".format(icon, FEATURE_LABELS.get(feat, feat))
    await c.bot.send_invoice(
        chat_id=uid,
        title=label,
        description=FEATURE_DESC.get(feat, ""),
        payload="feat_{}_{}".format(feat, uid),
        currency="XTR",
        prices=[LabeledPrice(label=label, amount=PRICES.get(feat, 50))],
        provider_token="",
    )
```

async def cmd_history_cb(q, c):
uid = q.from_user.id
if not has_feat(uid, “history”):
await q.message.edit_text(
“\u274c *History Log* not active\n\nActivate from shop for `25 \u2b50`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“history”))
return
hist = get_user(uid)[“history”][-20:]
if not hist:
await q.message.edit_text(”\U0001f4ed History is empty.”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())
return
text = “\U0001f4dc *Last 20 fetched links:*\n\n”
for i, (url, r, ts) in enumerate(reversed(hist), 1):
ttl = (r.get(“title”) or “–”)[:35]
prc = r.get(“price”) or “–”
text += “`{}.` *{}*\n   \U0001f4b0 `{}` | \U0001f550 `{}`\n   \U0001f517 `{}...`\n\n”.format(
i, ttl, prc, ts[:16], url[:55])
await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_export_cb(q, c):
uid = q.from_user.id
if not has_feat(uid, “export”):
await q.message.edit_text(
“\u274c *Export CSV* not active\n\nActivate from shop for `35 \u2b50`”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_buy(“export”))
return
hist = get_user(uid)[“history”]
if not hist:
await q.message.edit_text(”\U0001f4ed No history to export.”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())
return
out = io.StringIO()
w = csv.writer(out)
w.writerow([”#”, “URL”, “Title”, “Platform”, “Price”, “Collection”, “Rarity”, “Timestamp”])
for i, (url, r, ts) in enumerate(hist, 1):
w.writerow([i, url, r.get(“title”, “”), r.get(“platform”, “”),
r.get(“price”, “”), r.get(“collection”, “”), r.get(“rarity”, “”), ts])
out.seek(0)
fname = “nft_history_{}*{}.csv”.format(uid, datetime.now().strftime(”%Y%m%d*%H%M%S”))
await q.message.reply_document(
document=out.getvalue().encode(“utf-8-sig”),
filename=fname,
caption=”\U0001f4e4 *Exported {} links!*”.format(len(hist)),
parse_mode=ParseMode.MARKDOWN)

# ==============================================================

# PAYMENT HANDLERS

# ==============================================================

async def pre_checkout(u, c):
await u.pre_checkout_query.answer(ok=True)

async def payment_done(u, c):
uid = u.effective_user.id
payload = u.message.successful_payment.invoice_payload
user = get_user(uid)
feat_map = {
“feat_bulk”: “bulk”,
“feat_multi”: “multi_platform”,
“feat_monitor”: “monitor”,
“feat_metadata”: “metadata”,
“feat_history”: “history”,
“feat_export”: “export”,
“feat_unlimited”: “unlimited”,
}
for key, feat in feat_map.items():
if payload.startswith(key):
if feat == “unlimited”:
user[“premium”][“unlimited_until”] = (
datetime.now() + timedelta(hours=24)).isoformat()
else:
user[“premium”][feat] = True
icon = FEATURE_ICONS.get(key.replace(“feat_”, “”), “”)
label = FEATURE_LABELS.get(key.replace(“feat_”, “”), feat)
await u.message.reply_text(
“\U0001f389 *{} {} activated successfully!*\n\n\u2705 You can use the feature now.”.format(icon, label),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
return

# ==============================================================

# ADMIN COMMANDS

# ==============================================================

async def cmd_admin(u, c):
if u.effective_user.id not in ADMIN_IDS:
return
total = len(users_db)
fetches = sum(x[“total_fetches”] for x in users_db.values())
premium = sum(1 for x in users_db.values() if any(v for k, v in x[“premium”].items() if k != “unlimited_until”))
mons = sum(len(v) for v in monitors_db.values())
await u.message.reply_text(
“\U0001f451 *Admin Panel*\n”
“{}\n”
“\U0001f465 Total users: `{}`\n”
“\U0001f522 Total fetches: `{}`\n”
“\U0001f48e Premium users: `{}`\n”
“\U0001f4e1 Active monitors: `{}`\n”
“{}”.format(SEP, total, fetches, premium, mons, SEP),
parse_mode=ParseMode.MARKDOWN)

async def cmd_give(u, c):
if u.effective_user.id not in ADMIN_IDS:
return
if len(c.args) < 2:
await u.message.reply_text(
“\u26a0\ufe0f `/give <uid> <feature>`”, parse_mode=ParseMode.MARKDOWN)
return
tuid = int(c.args[0])
feat = c.args[1]
usr = get_user(tuid)
if feat in usr[“premium”]:
usr[“premium”][feat] = True
await u.message.reply_text(
“\u2705 Activated `{}` for user `{}`”.format(feat, tuid),
parse_mode=ParseMode.MARKDOWN)
else:
await u.message.reply_text(
“\u274c Unknown feature: `{}`”.format(feat), parse_mode=ParseMode.MARKDOWN)

async def cmd_broadcast(u, c):
if u.effective_user.id not in ADMIN_IDS:
return
if not c.args:
await u.message.reply_text(
“\u26a0\ufe0f `/broadcast <message>`”, parse_mode=ParseMode.MARKDOWN)
return
text = “ “.join(c.args)
sent = 0
for uid in list(users_db.keys()):
try:
await c.bot.send_message(
uid,
“\U0001f4e2 *Announcement:*\n\n{}”.format(text),
parse_mode=ParseMode.MARKDOWN)
sent += 1
except Exception:
pass
await u.message.reply_text(
“\u2705 Sent to `{}` users.”.format(sent), parse_mode=ParseMode.MARKDOWN)

# ==============================================================

# BACKGROUND MONITOR LOOP

# ==============================================================

async def monitor_loop(app):
while True:
await asyncio.sleep(300)
for uid, items in list(monitors_db.items()):
for item in items:
try:
r = await fetch_nft(item[“url”])
new_price = r.get(“price”)
old_price = item.get(“last_price”)
if new_price and new_price != old_price:
item[“last_price”] = new_price
title = (r.get(“title”) or item[“url”][:40])[:50]
change = “\U0001f4c8 Price went up” if old_price else “\U0001f514 First price detected”
await app.bot.send_message(
uid,
“\U0001f4e1 *NFT Monitor Alert!*\n\n”
“\U0001f3f7 *{}*\n”
“{}: `{}` -> `{}`\n”
“\U0001f517 {}”.format(title, change, old_price or “–”, new_price, item[“url”][:60]),
parse_mode=ParseMode.MARKDOWN)
except Exception:
pass

# ==============================================================

# BUILD BOT

# ==============================================================

def build_bot():
app = Application.builder().token(BOT_TOKEN).build()

```
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("help", cmd_help))
app.add_handler(CommandHandler("status", cmd_status))
app.add_handler(CommandHandler("shop", cmd_shop))
app.add_handler(CommandHandler("fetch", cmd_fetch))
app.add_handler(CommandHandler("bulk", cmd_bulk))
app.add_handler(CommandHandler("monitor", cmd_monitor))
app.add_handler(CommandHandler("unmonitor", cmd_unmonitor))
app.add_handler(CommandHandler("history", cmd_history))
app.add_handler(CommandHandler("export", cmd_export))
app.add_handler(CommandHandler("stats", cmd_stats))
app.add_handler(CommandHandler("admin", cmd_admin))
app.add_handler(CommandHandler("give", cmd_give))
app.add_handler(CommandHandler("broadcast", cmd_broadcast))
app.add_handler(PreCheckoutQueryHandler(pre_checkout))
app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_done))
app.add_handler(CallbackQueryHandler(handle_cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

return app
```

# ==============================================================

# FLASK KEEP-ALIVE

# ==============================================================

flask_app = Flask(**name**)
_start_time = datetime.now()

@flask_app.route(”/”)
def home():
up = str(datetime.now() - _start_time).split(”.”)[0]
return jsonify({
“status”: “online”,
“bot”: “NFT Link Fetcher Bot”,
“uptime”: up,
“users”: len(users_db),
“timestamp”: datetime.now().isoformat(),
})

@flask_app.route(”/health”)
def health():
return jsonify({“status”: “ok”}), 200

@flask_app.route(”/ping”)
def ping():
return “pong”, 200

# ==============================================================

# SELF PING (keeps Render free tier alive)

# ==============================================================

def self_ping():
import urllib.request
url = os.getenv(“RENDER_EXTERNAL_URL”, “http://localhost:8080”) + “/ping”
while True:
time.sleep(14 * 60)
try:
urllib.request.urlopen(url, timeout=10)
logging.info(“Self-ping OK -> {}”.format(url))
except Exception as e:
logging.warning(“Self-ping failed: {}”.format(e))

# ==============================================================

# BOT THREAD

# ==============================================================

def run_bot_thread():
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
bot_app = build_bot()

```
async def main():
    async with bot_app:
        await bot_app.initialize()
        await bot_app.start()
        asyncio.create_task(monitor_loop(bot_app))
        await bot_app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

loop.run_until_complete(main())
```

# ==============================================================

# ENTRY POINT

# ==============================================================

if **name** == “**main**”:
logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s | %(levelname)s | %(name)s | %(message)s”
)
logging.getLogger(“httpx”).setLevel(logging.WARNING)

```
t_bot = threading.Thread(target=run_bot_thread, daemon=True, name="BotThread")
t_bot.start()
logging.info("Bot thread launched")

t_ping = threading.Thread(target=self_ping, daemon=True, name="PingThread")
t_ping.start()
logging.info("Self-ping thread launched")

port = int(os.getenv("PORT", 8080))
logging.info("Flask running on port {}".format(port))
flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
```
