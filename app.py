# -*- coding: utf-8 -*-
# NFT Price Watch Bot - @NftPriceWatchBot
# Uses Reservoir.tools API (FREE, no key) + OpenSea scrape fallback
# Render optimized: 0.1 CPU / 512 MB

import os, re, time, logging, asyncio, threading, json
import urllib.request
from datetime import datetime
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
import aiohttp

# ══════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════

BOT_TOKEN      = os.getenv("BOT_TOKEN",  "8583765815:AAHmwizFH5mIHcY6uVF2tLxMX64DV8e22Nw")
ADMIN_ID       = int(os.getenv("ADMIN_ID", "7825994636"))
FREE_LIMIT     = 100
CHECK_INTERVAL = 120   # seconds

# ── Reservoir API (free, 50 req/min, no key needed) ──
RESERVOIR_BASE = "https://api.reservoir.tools"
RESERVOIR_HDRS = {
    "accept":    "application/json",
    "x-api-key": "demo-api-key",   # public demo key always works
}

# ── OpenSea scrape fallback headers ──
SCRAPE_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ══════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════

users_db     = {}
monitors     = {}
_mon_counter = 0

def get_user(uid):
    if uid not in users_db:
        free = (uid == ADMIN_ID) or (len(users_db) < FREE_LIMIT)
        users_db[uid] = {
            "id":       uid,
            "joined":   datetime.now().isoformat(),
            "free":     free,
            "monitors": [],
        }
    return users_db[uid]

def user_is_free(uid):
    return uid == ADMIN_ID or get_user(uid)["free"]

def new_mid():
    global _mon_counter
    _mon_counter += 1
    return "M{:04d}".format(_mon_counter)

def add_monitor(uid, data):
    mid = new_mid()
    monitors[mid] = {
        "id":          mid,
        "uid":         uid,
        "type":        data["type"],
        "slug":        data["slug"],
        "token_id":    data.get("token_id"),
        "name":        data.get("name", data["slug"]),
        "last_floor":  data.get("floor"),
        "last_price":  data.get("price"),
        "check_count": 0,
        "alerts_sent": 0,
        "created":     datetime.now().isoformat(),
        "active":      True,
        "url":         data.get("url", ""),
    }
    get_user(uid)["monitors"].append(mid)
    return mid

def remove_monitor(uid, mid):
    if mid in monitors and monitors[mid]["uid"] == uid:
        monitors[mid]["active"] = False
        mlist = get_user(uid)["monitors"]
        if mid in mlist:
            mlist.remove(mid)
        return True
    return False

def user_monitors(uid):
    return [monitors[m] for m in get_user(uid)["monitors"]
            if m in monitors and monitors[m]["active"]]

# ══════════════════════════════════════════════════
# DATA FETCHERS
# ══════════════════════════════════════════════════

async def _get(session, url, headers, timeout=15):
    async with session.get(
        url, headers=headers,
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as r:
        return r.status, await r.json(content_type=None)

async def fetch_collection_floor(slug):
    # ── Method 1: Reservoir ──
    try:
        url = "{}/collections/v7?slug={}&limit=1".format(RESERVOIR_BASE, slug)
        async with aiohttp.ClientSession() as s:
            status, data = await _get(s, url, RESERVOIR_HDRS)
            if status == 200:
                cols = data.get("collections", [])
                if cols:
                    col   = cols[0]
                    floor = None
                    fp = col.get("floorAsk", {})
                    if fp:
                        floor = fp.get("price", {}).get("amount", {}).get("decimal")
                    if floor is None:
                        floor = col.get("floor_ask_price")
                    
                    return {
                        "ok":    True,
                        "name":  col.get("name", slug),
                        "slug":  slug,
                        "floor": float(floor) if floor is not None else None,
                        "url":   "https://opensea.io/collection/{}".format(slug),
                        "image": col.get("image", ""),
                    }
    except Exception as e:
        logging.debug("Reservoir failed for {}: {}".format(slug, e))

    # ── Method 2: Scrape OpenSea page ──
    try:
        url = "https://opensea.io/collection/{}".format(slug)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=SCRAPE_HDRS,
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    html  = await r.text()
                    floor = _scrape_floor(html)
                    name  = _scrape_name(html) or slug
                    return {
                        "ok":    True,
                        "name":  name,
                        "slug":  slug,
                        "floor": floor,
                        "url":   url,
                    }
                else:
                    return {"ok": False, "error": "HTTP {} from OpenSea".format(r.status)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}

async def fetch_nft_price(contract, token_id):
    try:
        url = "{}/tokens/v7?tokens={}:{}&limit=1".format(RESERVOIR_BASE, contract, token_id)
        async with aiohttp.ClientSession() as s:
            status, data = await _get(s, url, RESERVOIR_HDRS)
            if status == 200:
                tokens = data.get("tokens", [])
                if tokens:
                    t     = tokens[0]
                    token = t.get("token", {})
                    mkt   = t.get("market", {})
                    floor = mkt.get("floorAsk", {}).get("price", {}).get("amount", {}).get("decimal")
                    name  = token.get("name") or "#{} ({})".format(token_id, contract[:8])
                    return {
                        "ok":       True,
                        "name":     name,
                        "price":    float(floor) if floor is not None else None,
                        "url":      "https://opensea.io/assets/ethereum/{}/{}".format(contract, token_id),
                    }
        return {"ok": False, "error": "Token not found or API error"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}

def _scrape_floor(html):
    patterns = [
        r'"floorPrice"\s*:\s*{[^}]*"amount"\s*:\s*"?([\d.]+)"?',
        r'floor.{0,30}?([\d.]+)\s*ETH',
        r'"floor_price"\s*:\s*"?([\d.]+)"?',
    ]
    for p in patterns:
        m = re.search(p, html, re.I | re.S)
        if m:
            try: return float(m.group(1))
            except: pass
    return None

def _scrape_name(html):
    patterns = [r'<title>([^<|]+)', r'"name"\s*:\s*"([^"]{3,60})"']
    for p in patterns:
        m = re.search(p, html, re.I)
        if m:
            name = m.group(1).strip()
            for suffix in [" | OpenSea", " - OpenSea", " Collection"]:
                name = name.replace(suffix, "")
            return name.strip()[:60]
    return None

async def resolve_url(url):
    url = url.strip().rstrip("/")
    m = re.match(r'https?://(?:www\.)?opensea\.io/collection/([^/?#\s]+)', url, re.I)
    if m:
        slug = m.group(1)
        data = await fetch_collection_floor(slug)
        if data.get("ok"): return {"type": "collection", **data}
        return data

    m = re.match(r'https?://(?:www\.)?opensea\.io/assets/(?:ethereum/)?([^/?#\s]+)/([^/?#\s]+)', url, re.I)
    if m:
        contract = m.group(1)
        token_id = m.group(2)
        data = await fetch_nft_price(contract, token_id)
        if data.get("ok"):
            return {"type": "nft", "slug": contract, "token_id": token_id, **data}
        return data

    return {"ok": False, "error": "Please send a valid OpenSea URL"}

# ══════════════════════════════════════════════════
# FORMATTING
# ══════════════════════════════════════════════════

SEP  = "—" * 20
SEP2 = "═" * 20

def fmt_eth(val):
    if val is None: return "N/A"
    return "{:.4f} ETH".format(val)

def pct(old, new):
    if not old or old == 0: return 0.0
    return ((new - old) / old) * 100.0

def build_alert(mon, old_val, new_val, val_type):
    up = new_val > old_val
    change = pct(old_val, new_val)
    icon = "🟢" if up else "🔴"
    trend = "RISING" if up else "FALLING"
    
    return (
        "{icon} *PRICE ALERT*\n"
        "{sep}\n"
        "📦 *{name}*\n"
        "📈 Trend: *{trend}*\n"
        "{sep}\n"
        "Was: `{old}`\n"
        "Now: `{new}`\n"
        "Change: `{sign}{pct:.2f}%`\n"
        "{sep}\n"
        "🔗 [View on OpenSea]({url})"
    ).format(
        icon=icon, sep=SEP, name=mon["name"], trend=trend,
        old=fmt_eth(old_val), new=fmt_eth(new_val),
        sign="+" if up else "", pct=change, url=mon["url"]
    )

def build_welcome(uid):
    u = get_user(uid)
    return (
        "🌊 *NFT Price Watch*\n"
        "Real-time OpenSea Intelligence\n\n"
        "Status: *{}*\n"
        "Community: *{}* watchers\n\n"
        "Paste an OpenSea URL to start tracking!".format(
            "Free" if u["free"] else "Premium", len(users_db)
        )
    )

def build_monitor_card(m):
    val = m.get("last_floor") if m["type"] == "collection" else m.get("last_price")
    return "🆔 `{}` | *{}*\nLast: `{}`".format(m["id"], m["name"][:30], fmt_eth(val))

# ══════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Monitors", callback_data="do_list"),
         InlineKeyboardButton("📊 Stats", callback_data="do_stats")],
        [InlineKeyboardButton("🧹 Clear All", callback_data="ask_clear")]
    ])

def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Back", callback_data="back_main")]])

def kb_list(uid):
    rows = []
    for m in user_monitors(uid):
        rows.append([InlineKeyboardButton("🚫 Stop {}".format(m["id"]), callback_data="stop_{}".format(m["id"]))])
    rows.append([InlineKeyboardButton("← Back", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════════
# HANDLERS
# ══════════════════════════════════════════════════

async def cmd_start(u, c):
    uid = u.effective_user.id
    get_user(uid)
    await u.message.reply_text(build_welcome(uid), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

async def cmd_list(u, c):
    uid = u.effective_user.id
    mons = user_monitors(uid)
    if not mons:
        await u.message.reply_text("No active monitors.", reply_markup=kb_back())
        return
    text = "📡 *Active Monitors:*\n\n" + "\n".join(build_monitor_card(m) for m in mons)
    await u.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_list(uid))

async def handle_msg(u, c):
    uid = u.effective_user.id
    text = u.message.text.strip()
    if "opensea.io" not in text.lower(): return

    scanning = await u.message.reply_text("🔍 *Scanning URL...*", parse_mode=ParseMode.MARKDOWN)
    result = await resolve_url(text)

    if not result.get("ok"):
        await scanning.edit_text("❌ Error: {}".format(result.get("error")))
        return

    mid = add_monitor(uid, result)
    await scanning.edit_text("✅ *Monitor Started!*\nID: `{}`\nName: *{}*".format(mid, result["name"]), 
                             parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

async def handle_cb(u, c):
    q = u.callback_query
    uid = q.from_user.id
    await q.answer()

    if q.data == "back_main":
        await q.message.edit_text(build_welcome(uid), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
    elif q.data == "do_list":
        mons = user_monitors(uid)
        text = "📡 *Active Monitors:*\n\n" + "\n".join(build_monitor_card(m) for m in mons) if mons else "No monitors."
        await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_list(uid))
    elif q.data.startswith("stop_"):
        mid = q.data[5:]
        remove_monitor(uid, mid)
        await q.message.edit_text("✅ Monitor `{}` stopped.".format(mid), reply_markup=kb_main())

# ══════════════════════════════════════════════════
# LOOP & BOT
# ══════════════════════════════════════════════════

async def monitor_loop(app):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        for mon in list(monitors.values()):
            if not mon["active"]: continue
            try:
                if mon["type"] == "collection":
                    data = await fetch_collection_floor(mon["slug"])
                    new_val = data.get("floor")
                    old_val = mon.get("last_floor")
                    mon["last_floor"] = new_val
                else:
                    data = await fetch_nft_price(mon["slug"], mon["token_id"])
                    new_val = data.get("price")
                    old_val = mon.get("last_price")
                    mon["last_price"] = new_val

                if old_val and new_val and abs(new_val - old_val) > 0.0001:
                    alert = build_alert(mon, old_val, new_val, mon["type"])
                    await app.bot.send_message(chat_id=mon["uid"], text=alert, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logging.error("Loop error: {}".format(e))

def build_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    return app

# ══════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Bot is Running"

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = build_bot()
    
    async def _main():
        async with bot:
            await bot.initialize()
            await bot.start()
            asyncio.create_task(monitor_loop(bot))
            await bot.updater.start_polling()
            await asyncio.Event().wait()
    loop.run_until_complete(_main())

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)
