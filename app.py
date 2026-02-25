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

BOT_TOKEN      = os.getenv(“BOT_TOKEN”,  “8583765815:AAHmwizFH5mIHcY6uVF2tLxMX64DV8e22Nw”)
ADMIN_ID       = int(os.getenv(“ADMIN_ID”, “7825994636”))
FREE_LIMIT     = 100
CHECK_INTERVAL = 120   # seconds

# ── Reservoir API (free, 50 req/min, no key needed) ──

RESERVOIR_BASE = “https://api.reservoir.tools”
RESERVOIR_HDRS = {
“accept”:    “application/json”,
“x-api-key”: “demo-api-key”,   # public demo key always works
}

# ── OpenSea scrape fallback headers ──

SCRAPE_HDRS = {
“User-Agent”: (
“Mozilla/5.0 (Windows NT 10.0; Win64; x64) “
“AppleWebKit/537.36 (KHTML, like Gecko) “
“Chrome/120.0.0.0 Safari/537.36”
),
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8”,
“Accept-Language”: “en-US,en;q=0.5”,
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
“id”:       uid,
“joined”:   datetime.now().isoformat(),
“free”:     free,
“monitors”: [],
}
return users_db[uid]

def user_is_free(uid):
return uid == ADMIN_ID or get_user(uid)[“free”]

def new_mid():
global _mon_counter
_mon_counter += 1
return “M{:04d}”.format(_mon_counter)

def add_monitor(uid, data):
mid = new_mid()
monitors[mid] = {
“id”:          mid,
“uid”:         uid,
“type”:        data[“type”],
“slug”:        data[“slug”],
“token_id”:    data.get(“token_id”),
“name”:        data.get(“name”, data[“slug”]),
“last_floor”:  data.get(“floor”),
“last_price”:  data.get(“price”),
“check_count”: 0,
“alerts_sent”: 0,
“created”:     datetime.now().isoformat(),
“active”:      True,
“url”:         data.get(“url”, “”),
}
get_user(uid)[“monitors”].append(mid)
return mid

def remove_monitor(uid, mid):
if mid in monitors and monitors[mid][“uid”] == uid:
monitors[mid][“active”] = False
mlist = get_user(uid)[“monitors”]
if mid in mlist:
mlist.remove(mid)
return True
return False

def user_monitors(uid):
return [monitors[m] for m in get_user(uid)[“monitors”]
if m in monitors and monitors[m][“active”]]

# ══════════════════════════════════════════════════

# DATA FETCHERS  (Reservoir primary, scrape fallback)

# ══════════════════════════════════════════════════

async def _get(session, url, headers, timeout=15):
async with session.get(
url, headers=headers,
timeout=aiohttp.ClientTimeout(total=timeout)
) as r:
return r.status, await r.json(content_type=None)

async def fetch_collection_floor(slug):
“””
Tries in order:
1. Reservoir /collections/v7  (free, no key)
2. OpenSea page scrape         (fallback)
Returns dict with ok, name, floor, url
“””
# ── Method 1: Reservoir ──
try:
url = “{}/collections/v7?slug={}&limit=1”.format(RESERVOIR_BASE, slug)
async with aiohttp.ClientSession() as s:
status, data = await _get(s, url, RESERVOIR_HDRS)
if status == 200:
cols = data.get(“collections”, [])
if cols:
col   = cols[0]
floor = None
# try multiple paths reservoir uses
fp = col.get(“floorAsk”, {})
if fp:
floor = fp.get(“price”, {}).get(“amount”, {}).get(“decimal”)
if floor is None:
floor = col.get(“floor_ask_price”)
if floor is None:
# try stats path
stats = col.get(“volume”, {})
floor = col.get(“floorSale”, {}).get(“1day”)
return {
“ok”:    True,
“name”:  col.get(“name”, slug),
“slug”:  slug,
“floor”: float(floor) if floor is not None else None,
“url”:   “https://opensea.io/collection/{}”.format(slug),
“image”: col.get(“image”, “”),
“supply”: col.get(“tokenCount”),
“owners”: col.get(“ownerCount”),
}
except Exception as e:
logging.debug(“Reservoir failed for {}: {}”.format(slug, e))

```
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
                    "image": "",
                }
            else:
                return {"ok": False, "error": "HTTP {} from OpenSea".format(r.status)}
except Exception as e:
    return {"ok": False, "error": str(e)[:80]}
```

async def fetch_nft_price(contract, token_id):
“””
Tries Reservoir /tokens/v7 for single NFT price.
“””
try:
url = “{}/tokens/v7?tokens={}:{}&limit=1”.format(
RESERVOIR_BASE, contract, token_id)
async with aiohttp.ClientSession() as s:
status, data = await _get(s, url, RESERVOIR_HDRS)
if status == 200:
tokens = data.get(“tokens”, [])
if tokens:
t     = tokens[0]
token = t.get(“token”, {})
mkt   = t.get(“market”, {})
floor = mkt.get(“floorAsk”, {}).get(“price”, {}).get(“amount”, {}).get(“decimal”)
name  = token.get(“name”) or “#{} ({})”.format(token_id, contract[:8])
return {
“ok”:       True,
“name”:     name,
“price”:    float(floor) if floor is not None else None,
“url”:      “https://opensea.io/assets/ethereum/{}/{}”.format(contract, token_id),
“image”:    token.get(“image”, “”),
}
return {“ok”: False, “error”: “Token not found”}
return {“ok”: False, “error”: “HTTP {}”.format(status)}
except Exception as e:
return {“ok”: False, “error”: str(e)[:80]}

def _scrape_floor(html):
“”“Extract floor price from OpenSea HTML.”””
patterns = [
r’“floorPrice”\s*:\s*{[^}]*“amount”\s*:\s*”?([\d.]+)”?’,
r’floor.{0,30}?([\d]+.[\d]+)\s*ETH’,
r’“floor_price”\s*:\s*”?([\d.]+)”?’,
r’(\d+.\d+)\s*ETH.*?[Ff]loor’,
]
for p in patterns:
m = re.search(p, html, re.I | re.S)
if m:
try:
return float(m.group(1))
except Exception:
pass
# Try JSON-LD / next data
m = re.search(r’**NEXT_DATA**.*?“floorPrice”[^:]*:\s*”?([\d.]+)’, html, re.S)
if m:
try:
return float(m.group(1))
except Exception:
pass
return None

def _scrape_name(html):
patterns = [
r’<title>([^<|]+)’,
r’“name”\s*:\s*”([^”]{3,60})”’,
r’<h1[^>]*>([^<]{3,60})</h1>’,
]
for p in patterns:
m = re.search(p, html, re.I)
if m:
name = m.group(1).strip()
# Clean up common suffixes
for suffix in [” | OpenSea”, “ - OpenSea”, “ Collection”]:
name = name.replace(suffix, “”)
return name.strip()[:60]
return None

async def resolve_url(url):
“”“Parse URL and fetch initial data.”””
url = url.strip().rstrip(”/”)

```
# Collection: opensea.io/collection/SLUG
m = re.match(r'https?://(?:www\.)?opensea\.io/collection/([^/?#\s]+)', url, re.I)
if m:
    slug = m.group(1)
    data = await fetch_collection_floor(slug)
    if data.get("ok"):
        return {"type": "collection", **data}
    return data

# NFT: opensea.io/assets/ethereum/CONTRACT/TOKEN_ID
m = re.match(
    r'https?://(?:www\.)?opensea\.io/assets/(?:ethereum/)?([^/?#\s]+)/([^/?#\s]+)',
    url, re.I)
if m:
    contract = m.group(1)
    token_id = m.group(2)
    data = await fetch_nft_price(contract, token_id)
    if data.get("ok"):
        return {
            "type":     "nft",
            "slug":     contract,
            "token_id": token_id,
            **data,
        }
    return data

# Raw slug? Try as collection
if re.match(r'^[a-z0-9\-_]+$', url.lower()) and len(url) < 80:
    data = await fetch_collection_floor(url)
    if data.get("ok"):
        return {"type": "collection", **data}

return {"ok": False, "error": "Please send a valid OpenSea URL"}
```

# ══════════════════════════════════════════════════

# FORMATTING

# ══════════════════════════════════════════════════

SEP  = “\u2500” * 28
SEP2 = “\u2501” * 28

def fmt_eth(val):
if val is None:
return “N/A”
if val == 0:
return “0 ETH”
if val < 0.0001:
return “{:.8f} ETH”.format(val)
if val < 0.01:
return “{:.5f} ETH”.format(val)
if val < 1:
return “{:.4f} ETH”.format(val)
return “{:.3f} ETH”.format(val)

def pct(old, new):
if not old or old == 0:
return 0.0
return ((new - old) / old) * 100.0

def vibe_up(p):
if p > 100: return “\U0001f4a5 EXPLOSIVE pump! Insane surge detected.”
if p > 50:  return “\U0001f525 Massive rally! Market is on fire right now.”
if p > 20:  return “\U0001f680 Strong momentum! Bulls are in control.”
if p > 10:  return “\U0001f4c8 Solid climb. Healthy price discovery.”
if p > 5:   return “\U0001f7e2 Moving up steadily. Bullish signal.”
return           “\U0001f7e1 Slight uptick. Holding the line.”

def vibe_down(p):
p = abs(p)
if p > 50:  return “\U0001f4a5 Massive dump! High caution advised.”
if p > 20:  return “\u26a0\ufe0f Sharp decline. Volatility spike detected.”
if p > 10:  return “\U0001f4c9 Notable dip. Bears pushing hard.”
if p > 5:   return “\U0001f534 Sliding down. Monitor closely.”
return           “\U0001f7e1 Minor dip. Could be market noise.”

def build_alert(mon, old_val, new_val, val_type):
up      = new_val > old_val
change  = pct(old_val, new_val)
diff    = abs(new_val - old_val)
sign    = “+” if up else “-”
icon    = “\U0001f7e2” if up else “\U0001f534”
arrow   = “\U0001f4c8” if up else “\U0001f4c9”
trend   = “\u25b2  RISING” if up else “\u25bc  FALLING”
label   = “Floor Price” if val_type == “floor” else “Listing Price”
mood    = vibe_up(change) if up else vibe_down(change)
name    = mon.get(“name”, mon[“slug”])[:40]
ts      = datetime.now().strftime(”%d %b  %H:%M:%S”)
url     = mon.get(“url”, “https://opensea.io”)
mid     = mon[“id”]

```
return (
    "{icon} {arrow}  *PRICE ALERT*\n"
    "`{sep}`\n"
    "\U0001f3f7  *{name}*\n"
    "`{sep2}`\n"
    "{icon}  *{trend}*  \u2014  _{label}_\n"
    "`{sep}`\n"
    "\n"
    "   \U0001f4b8  Was:       *{old}*\n"
    "   \U0001f4b0  Now:       *{new}*\n"
    "   \U0001f4ca  Change:    *{sign}{pct:.2f}%*\n"
    "   \U0001f4b1  Delta:     *{sign}{diff}*\n"
    "\n"
    "`{sep}`\n"
    "   \U0001f4ac  {mood}\n"
    "`{sep}`\n"
    "\n"
    "\u23f0  `{ts}`\n"
    "\U0001f194  Monitor `{mid}`  \u2022  [OpenSea \U0001f517]({url})"
).format(
    icon=icon, arrow=arrow, trend=trend, label=label,
    sep=SEP, sep2=SEP2,
    name=name,
    old=fmt_eth(old_val), new=fmt_eth(new_val),
    sign=sign, pct=abs(change), diff=fmt_eth(diff),
    mood=mood, ts=ts, mid=mid, url=url,
)
```

def build_welcome(uid):
u      = get_user(uid)
badge  = “\u2705 Free Access” if u[“free”] else “\U0001f512 Premium”
count  = len(users_db)
mons   = len(user_monitors(uid))
return (
“\U0001f30a  *NFT Price Watch*\n”
“*Real-time OpenSea Intelligence*\n\n”
“`{sep2}`\n”
“\u25b8  Track *collections* or *single NFTs*\n”
“\u25b8  Instant alerts on every price move\n”
“\u25b8  Smart market sentiment with each ping\n”
“\u25b8  Powered by Reservoir \u2014 zero noise\n”
“`{sep}`\n”
“   \U0001f3ab  Status:     *{badge}*\n”
“   \U0001f4e1  Monitors:   *{mons}* active\n”
“   \U0001f465  Community:  *{count}* watchers\n”
“`{sep}`\n\n”
“\U0001f447  Paste an *OpenSea URL* to start watching”
).format(sep=SEP, sep2=SEP2, badge=badge, mons=mons, count=count)

def build_help():
return (
“\U0001f4d6  *How to use*\n”
“`{sep}`\n\n”
“\U0001f4e5  *Start monitoring:*\n”
“Just paste any OpenSea link:\n”
“   `opensea.io/collection/SLUG`\n”
“   `opensea.io/assets/ethereum/.../ID`\n\n”
“\U0001f4cb  `/list` \u2014 All active monitors\n\n”
“\U0001f6d1  `/stop M0001` \u2014 Stop one monitor\n\n”
“\U0001f9f9  `/clear` \u2014 Stop everything\n\n”
“\U0001f4ca  `/stats` \u2014 Your dashboard\n\n”
“`{sep}`\n”
“\u23f1\ufe0f  Checks every *{interval}s*\n”
“\U0001f514  Alerts only on *real* price changes\n”
“\U0001f4a1  Tolerance: *0.0001 ETH* minimum shift”
).format(sep=SEP, interval=CHECK_INTERVAL)

def build_monitor_card(m):
mtype  = “Collection” if m[“type”] == “collection” else “NFT”
val    = m.get(“last_floor”) if m[“type”] == “collection” else m.get(“last_price”)
icon   = “\U0001f5c2\ufe0f” if m[“type”] == “collection” else “\U0001f4e6”
return (
“{icon}  `{mid}` \u2014 *{name}*\n”
“   \U0001f4ca  {mtype}  \u2022  Last: *{val}*\n”
“   \U0001f504  Checks: `{checks}`  \u2022  Alerts: `{alerts}`”
).format(
icon=icon, mid=m[“id”], name=m[“name”][:35],
mtype=mtype, val=fmt_eth(val),
checks=m[“check_count”], alerts=m[“alerts_sent”],
)

# ══════════════════════════════════════════════════

# KEYBOARDS

# ══════════════════════════════════════════════════

def kb_main():
return InlineKeyboardMarkup([
[
InlineKeyboardButton(”\U0001f4cb  Monitors”, callback_data=“do_list”),
InlineKeyboardButton(”\U0001f4ca  Stats”,    callback_data=“do_stats”),
],
[
InlineKeyboardButton(”\U0001f4d6  Help”,      callback_data=“do_help”),
InlineKeyboardButton(”\U0001f9f9  Clear All”, callback_data=“ask_clear”),
],
])

def kb_back():
return InlineKeyboardMarkup([[
InlineKeyboardButton(”\u2190  Back”, callback_data=“back_main”)
]])

def kb_confirm_clear():
return InlineKeyboardMarkup([[
InlineKeyboardButton(”\u26a0\ufe0f  Yes, stop all”, callback_data=“do_clear”),
InlineKeyboardButton(”\u274c  Cancel”,              callback_data=“back_main”),
]])

def kb_list(uid):
rows = []
for m in user_monitors(uid):
icon = “\U0001f5c2\ufe0f” if m[“type”] == “collection” else “\U0001f4e6”
rows.append([InlineKeyboardButton(
“\U0001f6d1  {}  {}  {}”.format(m[“id”], icon, m[“name”][:20]),
callback_data=“stop_{}”.format(m[“id”])
)])
rows.append([InlineKeyboardButton(”\u2190  Back”, callback_data=“back_main”)])
return InlineKeyboardMarkup(rows)

def kb_monitor_actions(mid, url=“https://opensea.io”):
return InlineKeyboardMarkup([[
InlineKeyboardButton(”\U0001f6d1  Stop {}”.format(mid), callback_data=“stop_{}”.format(mid)),
InlineKeyboardButton(”\U0001f4cb  My List”,              callback_data=“do_list”),
]])

def kb_alert_actions(mid, url):
return InlineKeyboardMarkup([[
InlineKeyboardButton(”\U0001f517  OpenSea”, url=url),
InlineKeyboardButton(”\U0001f6d1  Stop {}”.format(mid), callback_data=“stop_{}”.format(mid)),
]])

# ══════════════════════════════════════════════════

# COMMAND HANDLERS

# ══════════════════════════════════════════════════

async def cmd_start(u, c):
uid = u.effective_user.id
get_user(uid)
await u.message.reply_text(
build_welcome(uid), parse_mode=ParseMode.MARKDOWN,
reply_markup=kb_main(), disable_web_page_preview=True)

async def cmd_help(u, c):
await u.message.reply_text(
build_help(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_list(u, c):
uid  = u.effective_user.id
mons = user_monitors(uid)
await _reply_list(u.message, uid, mons)

async def _reply_list(msg, uid, mons):
if not mons:
await msg.reply_text(
“\U0001f4ed  *No active monitors*\n\nPaste an OpenSea URL to start.”,
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())
return
lines = “\n\n”.join(build_monitor_card(m) for m in mons)
text  = (
“\U0001f4e1  *Active Monitors*  \u2014  *{}*\n”
“`{}`\n\n{}\n\n`{}`\n”
“Tap \U0001f6d1 below to stop any monitor:”
).format(len(mons), SEP2, lines, SEP)
await msg.reply_text(
text, parse_mode=ParseMode.MARKDOWN,
reply_markup=kb_list(uid), disable_web_page_preview=True)

async def cmd_stop(u, c):
uid = u.effective_user.id
if not c.args:
await u.message.reply_text(
“\u26a0\ufe0f  Usage: `/stop M0001`”, parse_mode=ParseMode.MARKDOWN)
return
mid = c.args[0].upper()
if remove_monitor(uid, mid):
await u.message.reply_text(
“\U0001f6d1  *Monitor `{}` stopped.*”.format(mid),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
else:
await u.message.reply_text(
“\u274c  Monitor `{}` not found.”.format(mid),
parse_mode=ParseMode.MARKDOWN)

async def cmd_clear(u, c):
uid  = u.effective_user.id
mons = user_monitors(uid)
for m in mons:
remove_monitor(uid, m[“id”])
await u.message.reply_text(
“\U0001f9f9  *All {} monitors cleared.*”.format(len(mons)),
parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())

async def cmd_stats(u, c):
uid  = u.effective_user.id
mons = user_monitors(uid)
ud   = get_user(uid)
text = (
“\U0001f4ca  *Dashboard*\n”
“`{sep}`\n”
“   \U0001f4e1  Active:      *{active}*\n”
“   \U0001f514  Alerts:      *{alerts}*\n”
“   \U0001f504  Checks:      *{checks}*\n”
“   \U0001f4c5  Since:       *{since}*\n”
“   \U0001f3ab  Status:      *{status}*\n”
“`{sep}`”
).format(
sep=SEP,
active=len(mons),
alerts=sum(m[“alerts_sent”] for m in mons),
checks=sum(m[“check_count”] for m in mons),
since=ud[“joined”][:10],
status=“Free \u2705” if user_is_free(uid) else “Premium \U0001f512”,
)
await u.message.reply_text(
text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def cmd_admin(u, c):
if u.effective_user.id != ADMIN_ID:
return
active_mons  = len([m for m in monitors.values() if m[“active”]])
total_alerts = sum(m[“alerts_sent”] for m in monitors.values())
text = (
“\U0001f451  *Admin Panel*\n”
“`{sep}`\n”
“   \U0001f465  Users:       *{users}*\n”
“   \U0001f4e1  Monitors:    *{mons}*\n”
“   \U0001f514  Alerts sent: *{alerts}*\n”
“   \U0001f39f  Free left:   *{free}*\n”
“`{sep}`”
).format(
sep=SEP, users=len(users_db),
mons=active_mons, alerts=total_alerts,
free=max(0, FREE_LIMIT - len(users_db)),
)
await u.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ══════════════════════════════════════════════════

# MESSAGE HANDLER  (URL paste)

# ══════════════════════════════════════════════════

async def handle_msg(u, c):
uid  = u.effective_user.id
text = u.message.text.strip()

```
if not user_is_free(uid):
    await u.message.reply_text(
        "\U0001f512  *Access restricted.*\n\n"
        "Free access is limited to the first {} users.".format(FREE_LIMIT),
        parse_mode=ParseMode.MARKDOWN)
    return

if "opensea.io" not in text.lower():
    await u.message.reply_text(
        "\U0001f447  Paste an OpenSea link to start.\n\n"
        "Examples:\n"
        "`https://opensea.io/collection/pudgypenguins`\n"
        "`https://opensea.io/assets/ethereum/0x.../123`",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main())
    return

mons = user_monitors(uid)
if len(mons) >= 10:
    await u.message.reply_text(
        "\u26a0\ufe0f  *Limit reached* (10 monitors max)\n\nStop one with `/stop <ID>`",
        parse_mode=ParseMode.MARKDOWN)
    return

scanning = await u.message.reply_text(
    "\U0001f50d  *Scanning...*\nFetching live data from Reservoir + OpenSea...",
    parse_mode=ParseMode.MARKDOWN)

result = await resolve_url(text)

if not result.get("ok"):
    await scanning.edit_text(
        "\u274c  *Could not fetch data*\n\n"
        "_{}_\n\n"
        "\U0001f4a1  *Tip:* Make sure the URL is a valid OpenSea collection or NFT page.\n"
        "Example: `https://opensea.io/collection/pudgypenguins`".format(
            result.get("error", "Unknown error")),
        parse_mode=ParseMode.MARKDOWN)
    return

mid = add_monitor(uid, result)
mon = monitors[mid]

mtype = "Collection \U0001f5c2\ufe0f" if result["type"] == "collection" else "NFT \U0001f4e6"
val   = mon.get("last_floor") if result["type"] == "collection" else mon.get("last_price")
plabel = "Floor" if result["type"] == "collection" else "Price"

await scanning.edit_text(
    "\u2705  *Monitor Started!*\n"
    "`{sep}`\n"
    "\U0001f3f7  *{name}*\n"
    "   \U0001f4e6  Type:     {mtype}\n"
    "   \U0001f4b0  {plabel}:    *{val}*\n"
    "   \u23f1\ufe0f  Interval: *every {interval}s*\n"
    "   \U0001f194  ID:       `{mid}`\n"
    "`{sep}`\n"
    "\U0001f514  You will be notified of *every price change*.\n"
    "Stop anytime: `/stop {mid}`".format(
        sep=SEP, name=mon["name"], mtype=mtype,
        plabel=plabel, val=fmt_eth(val),
        interval=CHECK_INTERVAL, mid=mid,
    ),
    parse_mode=ParseMode.MARKDOWN,
    reply_markup=kb_monitor_actions(mid, mon["url"]),
    disable_web_page_preview=True,
)
```

# ══════════════════════════════════════════════════

# CALLBACK HANDLER

# ══════════════════════════════════════════════════

async def handle_cb(u, c):
q   = u.callback_query
uid = q.from_user.id
d   = q.data
await q.answer()

```
async def edit(text, kb=None, preview=True):
    await q.message.edit_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb or kb_back(),
        disable_web_page_preview=preview)

if d == "back_main":
    await q.message.edit_text(
        build_welcome(uid), parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(), disable_web_page_preview=True)
elif d == "do_list":
    mons = user_monitors(uid)
    await _reply_list(q.message, uid, mons)
elif d == "do_help":
    await edit(build_help())
elif d == "do_stats":
    mons = user_monitors(uid)
    ud   = get_user(uid)
    text = (
        "\U0001f4ca  *Dashboard*\n"
        "`{sep}`\n"
        "   \U0001f4e1  Active:      *{active}*\n"
        "   \U0001f514  Alerts:      *{alerts}*\n"
        "   \U0001f504  Checks:      *{checks}*\n"
        "   \U0001f4c5  Since:       *{since}*\n"
        "   \U0001f3ab  Status:      *{status}*\n"
        "`{sep}`"
    ).format(
        sep=SEP, active=len(mons),
        alerts=sum(m["alerts_sent"] for m in mons),
        checks=sum(m["check_count"] for m in mons),
        since=ud["joined"][:10],
        status="Free \u2705" if user_is_free(uid) else "Premium \U0001f512",
    )
    await edit(text)
elif d == "ask_clear":
    await edit(
        "\u26a0\ufe0f  *Stop all monitors?*\n\n"
        "This will remove ALL active monitors immediately.",
        kb_confirm_clear())
elif d == "do_clear":
    mons = user_monitors(uid)
    n    = len(mons)
    for m in mons:
        remove_monitor(uid, m["id"])
    await edit("\U0001f9f9  *Cleared {} monitors.*".format(n), kb_main())
elif d.startswith("stop_"):
    mid = d[5:]
    if remove_monitor(uid, mid):
        await edit(
            "\U0001f6d1  *Monitor `{}` stopped.*\n\nNo more alerts for this one.".format(mid),
            kb_main())
    else:
        await edit("\u274c  Monitor not found or already stopped.", kb_main())
```

# ══════════════════════════════════════════════════

# MONITOR LOOP

# ══════════════════════════════════════════════════

async def monitor_loop(app):
logging.info(“Monitor loop started (interval={}s)”.format(CHECK_INTERVAL))
while True:
await asyncio.sleep(CHECK_INTERVAL)
active = [m for m in monitors.values() if m[“active”]]
logging.info(“Checking {} active monitors”.format(len(active)))

```
    for mon in active:
        try:
            await _check(app, mon)
        except Exception as e:
            logging.warning("Check error [{}]: {}".format(mon["id"], e))
        await asyncio.sleep(2)   # gentle rate limiting
```

async def _check(app, mon):
mid = mon[“id”]
mon[“check_count”] += 1

```
if mon["type"] == "collection":
    data    = await fetch_collection_floor(mon["slug"])
    new_val = data.get("floor") if data.get("ok") else None
    old_val = mon.get("last_floor")
    vtype   = "floor"
else:
    data    = await fetch_nft_price(mon["slug"], mon.get("token_id", ""))
    new_val = data.get("price") if data.get("ok") else None
    old_val = mon.get("last_price")
    vtype   = "price"

if new_val is None:
    logging.debug("[{}] No price returned".format(mid))
    return

# Update stored
if vtype == "floor":
    mon["last_floor"] = new_val
else:
    mon["last_price"] = new_val

# First baseline — no alert
if old_val is None:
    logging.info("[{}] Baseline set: {}".format(mid, fmt_eth(new_val)))
    return

# Ignore noise
if abs(new_val - old_val) < 0.0001:
    return

# PRICE CHANGED — send beautiful alert
mon["alerts_sent"] += 1
alert = build_alert(mon, old_val, new_val, vtype)
try:
    await app.bot.send_message(
        chat_id=mon["uid"],
        text=alert,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
        reply_markup=kb_alert_actions(mid, mon.get("url", "https://opensea.io")),
    )
    logging.info("[{}] Alert #{} sent: {} -> {}".format(
        mid, mon["alerts_sent"], fmt_eth(old_val), fmt_eth(new_val)))
except Exception as e:
    logging.warning("[{}] Alert send failed: {}".format(mid, e))
```

# ══════════════════════════════════════════════════

# BOT BUILD

# ══════════════════════════════════════════════════

def build_bot():
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler(“start”,  cmd_start))
app.add_handler(CommandHandler(“help”,   cmd_help))
app.add_handler(CommandHandler(“list”,   cmd_list))
app.add_handler(CommandHandler(“stop”,   cmd_stop))
app.add_handler(CommandHandler(“clear”,  cmd_clear))
app.add_handler(CommandHandler(“stats”,  cmd_stats))
app.add_handler(CommandHandler(“admin”,  cmd_admin))
app.add_handler(CallbackQueryHandler(handle_cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
return app

# ══════════════════════════════════════════════════

# FLASK

# ══════════════════════════════════════════════════

flask_app  = Flask(**name**)
_boot      = datetime.now()

@flask_app.route(”/”)
def home():
return jsonify({
“status”:   “online”,
“bot”:      “NFT Price Watch”,
“uptime”:   str(datetime.now() - _boot).split(”.”)[0],
“users”:    len(users_db),
“monitors”: len([m for m in monitors.values() if m[“active”]]),
})

@flask_app.route(”/health”)
def health():
return jsonify({“ok”: True}), 200

@flask_app.route(”/ping”)
def ping():
return “pong”, 200

# ══════════════════════════════════════════════════

# SELF-PING  (Render free tier keep-alive)

# ══════════════════════════════════════════════════

def self_ping():
base = os.getenv(“RENDER_EXTERNAL_URL”, “http://localhost:8080”)
url  = base.rstrip(”/”) + “/ping”
while True:
time.sleep(840)   # 14 min
try:
urllib.request.urlopen(url, timeout=10)
logging.info(“Self-ping OK”)
except Exception as e:
logging.warning(“Self-ping failed: {}”.format(e))

# ══════════════════════════════════════════════════

# BOT THREAD

# ══════════════════════════════════════════════════

def run_bot():
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
bot  = build_bot()

```
async def _main():
    async with bot:
        await bot.initialize()
        await bot.start()
        asyncio.create_task(monitor_loop(bot))
        await bot.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

loop.run_until_complete(_main())
```

# ══════════════════════════════════════════════════

# ENTRY

# ══════════════════════════════════════════════════

if **name** == “**main**”:
logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s  %(levelname)-8s  %(message)s”,
)
logging.getLogger(“httpx”).setLevel(logging.WARNING)
logging.getLogger(“aiohttp”).setLevel(logging.WARNING)

```
threading.Thread(target=run_bot,   daemon=True, name="Bot").start()
threading.Thread(target=self_ping, daemon=True, name="Ping").start()

port = int(os.getenv("PORT", 8080))
logging.info("Flask on :{} | Bot starting...".format(port))
flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
```
