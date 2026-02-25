# -*- coding: utf-8 -*-
# NFT Price Monitor Bot - @NftPriceWatchBot
# OpenSea NFT & Collection price monitor with premium UI
# Flask + Telegram Bot API + Render optimized

import os
import re
import time
import json
import logging
import asyncio
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
import aiohttp

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────

BOT_TOKEN  = os.getenv("BOT_TOKEN",  "8583765815:AAHmwizFH5mIHcY6uVF2tLxMX64DV8e22Nw")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "7825994636"))
FREE_LIMIT = 100   # first N users get free access
CHECK_INTERVAL = 120  # seconds between price checks

# OpenSea API - free tier, no key needed for basic data
OPENSEA_API = "https://api.opensea.io/api/v2"
OPENSEA_HEADERS = {
    "accept": "application/json",
    "x-api-key": os.getenv("OPENSEA_API_KEY", ""),
}

# ─────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────

users_db   = {}   # uid -> {joined, free, monitors}
monitors   = {}   # monitor_id -> monitor_data
_mon_counter = 0

def get_user(uid: int) -> dict:
    if uid not in users_db:
        is_free = (uid == ADMIN_ID) or (len(users_db) < FREE_LIMIT)
        users_db[uid] = {
            "id":       uid,
            "joined":   datetime.now().isoformat(),
            "free":     is_free,
            "monitors": [],   # list of monitor_ids
        }
    return users_db[uid]

def is_free(uid: int) -> bool:
    u = get_user(uid)
    return u["free"] or uid == ADMIN_ID

def new_monitor_id() -> str:
    global _mon_counter
    _mon_counter += 1
    return "M{:04d}".format(_mon_counter)

def add_monitor(uid: int, data: dict) -> str:
    mid = new_monitor_id()
    monitors[mid] = {
        "id":          mid,
        "uid":         uid,
        "type":        data["type"],       # "nft" or "collection"
        "slug":        data["slug"],       # collection slug
        "token_id":    data.get("token_id"),
        "name":        data.get("name", data["slug"]),
        "last_price":  None,
        "last_floor":  None,
        "check_count": 0,
        "alerts_sent": 0,
        "created":     datetime.now().isoformat(),
        "active":      True,
        "url":         data.get("url", ""),
        "image":       data.get("image", ""),
    }
    get_user(uid)["monitors"].append(mid)
    return mid

def remove_monitor(uid: int, mid: str) -> bool:
    if mid in monitors and monitors[mid]["uid"] == uid:
        monitors[mid]["active"] = False
        if mid in get_user(uid)["monitors"]:
            get_user(uid)["monitors"].remove(mid)
        return True
    return False

def user_monitors(uid: int) -> list:
    return [monitors[m] for m in get_user(uid)["monitors"] if m in monitors and monitors[m]["active"]]

# ─────────────────────────────────────────
# OPENSEA API FETCHER
# ─────────────────────────────────────────

async def fetch_collection(slug: str) -> dict:
    """Fetch collection floor price and stats from OpenSea."""
    url = "{}/collections/{}".format(OPENSEA_API, slug)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=OPENSEA_HEADERS,
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    data = await r.json()
                    return {
                        "ok":    True,
                        "name":  data.get("name", slug),
                        "slug":  slug,
                        "image": data.get("image_url", ""),
                        "floor": _extract_floor(data),
                        "total_supply": data.get("total_supply"),
                        "owners": data.get("num_owners"),
                        "volume_24h": _safe_get(data, "stats", "one_day_volume"),
                        "url":   "https://opensea.io/collection/{}".format(slug),
                    }
                else:
                    return {"ok": False, "error": "HTTP {}".format(r.status)}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:60]}

async def fetch_nft_item(slug: str, token_id: str) -> dict:
    """Fetch a single NFT listing price."""
    url = "{}/listings/collection/{}/nfts/{}/best".format(OPENSEA_API, slug, token_id)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=OPENSEA_HEADERS,
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    data = await r.json()
                    price_eth = _parse_listing_price(data)
                    # Also get NFT details
                    nft_url = "{}/chain/ethereum/contract/{}/nfts/{}".format(
                        OPENSEA_API, slug, token_id)
                    return {
                        "ok":       True,
                        "price":    price_eth,
                        "currency": "ETH",
                        "url": "https://opensea.io/assets/ethereum/{}/{}".format(slug, token_id),
                    }
                elif r.status == 404:
                    return {"ok": False, "error": "NFT not found"}
                else:
                    return {"ok": False, "error": "HTTP {}".format(r.status)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:60]}

async def resolve_opensea_url(url: str) -> dict:
    """
    Parse an OpenSea URL and return type + identifiers.
    """
    url = url.strip().rstrip("/")

    # Collection URL
    m = re.match(r'https?://opensea\.io/collection/([^/?#]+)', url)
    if m:
        slug = m.group(1)
        data = await fetch_collection(slug)
        if data["ok"]:
            return {"type": "collection", "slug": slug, **data}
        return {"ok": False, "error": data.get("error", "Not found")}

    # NFT URL (assets/ethereum/CONTRACT/TOKEN_ID)
    m = re.match(r'https?://opensea\.io/assets/(?:ethereum/)?([^/?#]+)/([^/?#]+)', url)
    if m:
        contract = m.group(1)
        token_id = m.group(2)
        # Try to get collection info
        col_data = await fetch_nft_item(contract, token_id)
        return {
            "type":     "nft",
            "slug":     contract,
            "token_id": token_id,
            "name":     "NFT #{} ({})".format(token_id, contract[:10]),
            "url":      url,
            **col_data,
        }

    return {"ok": False, "error": "Invalid OpenSea URL"}

def _extract_floor(data: dict) -> float | None:
    try:
        stats = data.get("stats", {})
        floor = stats.get("floor_price") or data.get("floor_price")
        if floor is not None:
            return float(floor)
        # Try payment_tokens path
        fees = data.get("fees", [])
        return None
    except Exception:
        return None

def _safe_get(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d

def _parse_listing_price(data: dict) -> float | None:
    try:
        listings = data.get("listings", [])
        if listings:
            p = listings[0].get("price", {})
            current = p.get("current", {})
            value = current.get("value")
            decimals = current.get("decimals", 18)
            if value:
                return float(value) / (10 ** decimals)
        # direct
        price = data.get("price", {})
        current = price.get("current", {})
        value = current.get("value")
        decimals = current.get("decimals", 18)
        if value:
            return float(value) / (10 ** decimals)
    except Exception:
        pass
    return None

def fmt_eth(val: float | None) -> str:
    if val is None:
        return "N/A"
    if val < 0.001:
        return "{:.6f} ETH".format(val)
    if val < 0.01:
        return "{:.4f} ETH".format(val)
    return "{:.3f} ETH".format(val)

def pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return ((new - old) / old) * 100

# ─────────────────────────────────────────
# BEAUTIFUL MESSAGE BUILDERS
# ─────────────────────────────────────────

DIVIDER    = "\u2500" * 26
BOLD_DIV   = "\u2501" * 26

def build_alert_message(mon: dict, old_val: float, new_val: float, val_type: str) -> str:
    """Build a stunning price alert message."""
    change   = pct_change(old_val, new_val)
    is_up    = new_val > old_val
    diff     = new_val - old_val

    # Direction visuals
    if is_up:
        direction_icon  = "\U0001f7e2"   # green circle
        arrow           = "\U0001f4c8"   # chart up
        trend_bar       = "\u25b2 UP"
        change_sign     = "+"
        vibe            = _pick_up_vibe(change)
    else:
        direction_icon  = "\U0001f534"   # red circle
        arrow           = "\U0001f4c9"   # chart down
        trend_bar       = "\u25bc DOWN"
        change_sign     = ""
        vibe            = _pick_down_vibe(change)

    label = "Floor Price" if val_type == "floor" else "Listing Price"
    name  = mon.get("name", mon["slug"])
    ts    = datetime.now().strftime("%H:%M:%S")
    url   = mon.get("url", "")

    msg = (
        "{} {} *PRICE ALERT*\n"
        "{}\n"
        "\U0001f3f7  *{}*\n"
        "{}\n"
        "{} *{}* {}\n"
        "{}\n"
        "   \U0001f4b8  *Was:* `{}`\n"
        "   \U0001f4b0  *Now:* `{}`\n"
        "   \U0001f522  *Change:* `{}{:.2f}%`\n"
        "   \U0001f4b1  *Delta:* `{}{}`\n"
        "{}\n"
        "   \U0001f4ac  {}\n"
        "{}\n"
        "\U0001f517  [View on OpenSea]({})\n"
        "\u23f0  `{}`   \u2022   Monitor ID: `{}`"
    ).format(
        direction_icon, arrow,
        DIVIDER,
        name,
        BOLD_DIV,
        direction_icon, trend_bar, label,
        DIVIDER,
        fmt_eth(old_val),
        fmt_eth(new_val),
        change_sign, abs(change),
        "+" if is_up else "-", fmt_eth(abs(diff)),
        DIVIDER,
        vibe,
        DIVIDER,
        url,
        ts, mon["id"],
    )
    return msg

def _pick_up_vibe(pct: float) -> str:
    if pct > 50:   return "\U0001f525 Massive surge! The market is on fire."
    if pct > 20:   return "\U0001f680 Strong momentum! Significant uptick detected."
    if pct > 10:   return "\u2b06\ufe0f Solid climb. Healthy price action."
    if pct > 5:    return "\U0001f4c8 Moving up steadily. Bullish signal."
    return "\U0001f7e1 Slight increase. Keep watching."

def _pick_down_vibe(pct: float) -> str:
    pct = abs(pct)
    if pct > 50:   return "\U0001f4a5 Heavy drop! Consider your position carefully."
    if pct > 20:   return "\u26a0\ufe0f Significant dip. High volatility zone."
    if pct > 10:   return "\u2b07\ufe0f Notable decline. Monitor closely."
    if pct > 5:    return "\U0001f4c9 Sliding down. Bearish pressure building."
    return "\U0001f7e1 Minor dip. Could be noise. Stay alert."

def build_monitor_card(mon: dict) -> str:
    mtype = "Collection \U0001f5c2\ufe0f" if mon["type"] == "collection" else "Single NFT \U0001f4e6"
    floor = fmt_eth(mon.get("last_floor") or mon.get("last_price"))
    checks = mon.get("check_count", 0)
    alerts = mon.get("alerts_sent", 0)
    created = mon["created"][:10]

    return (
        "\U0001f4e1 `{}` \u2022 {}\n"
        "   \U0001f3f7  *{}*\n"
        "   \U0001f4ca  Last: `{}`\n"
        "   \U0001f504  Checks: `{}` \u2022 Alerts: `{}`\n"
        "   \U0001f4c5  Since: `{}`"
    ).format(
        mon["id"], mtype, mon["name"], floor, checks, alerts, created
    )

def build_welcome(uid: int) -> str:
    u = get_user(uid)
    free_badge = "\u2705 Free Access" if u["free"] else "\U0001f512 Premium Only"
    total_users = len(users_db)
    return (
        "\U0001f30a *NFT Price Watch*\n"
        "*Real-time OpenSea price intelligence*\n\n"
        "{}\n\n"
        "\u25a1  Monitor *collections* or *single NFTs*\n"
        "\u25a1  Instant alerts on any price move\n"
        "\u25a1  Smart trend analysis with every ping\n"
        "\u25a1  Zero noise \u2014 only real changes trigger alerts\n\n"
        "{}\n"
        "   \U0001f464  User `#{}`\n"
        "   \U0001f3ab  Status: *{}*\n"
        "   \U0001f465  Community: `{}` watchers\n"
        "{}\n\n"
        "Paste an *OpenSea URL* to start watching \U0001f447"
    ).format(
        BOLD_DIV,
        DIVIDER,
        uid, free_badge, total_users,
        DIVIDER,
    )

def build_help() -> str:
    return (
        "\U0001f4d6 *Commands*\n"
        "{}\n\n"
        "\U0001f4e5  *Add monitor:*\n"
        "   Just paste any OpenSea URL\n"
        "   *opensea.io/collection/SLUG*\n"
        "   *opensea.io/assets/ethereum/...*\n\n"
        "\U0001f4cb  `/list` \u2014 View all active monitors\n\n"
        "\U0001f6d1  `/stop <ID>` \u2014 Stop a monitor\n"
        "   *Example: /stop M0001*\n\n"
        "\U0001f9f9  `/clear` \u2014 Stop all monitors\n\n"
        "\U0001f4ca  `/stats` \u2014 Your statistics\n\n"
        "{}\n"
        "\u23f1\ufe0f  Price checks every *{}s*\n"
        "\U0001f514  Alerts fire only on *real changes*"
    ).format(DIVIDER, DIVIDER, CHECK_INTERVAL)

# ─────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────

def kb_main():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001f4cb  My Monitors", callback_data="do_list"),
            InlineKeyboardButton("\U0001f4ca  Stats",       callback_data="do_stats"),
        ],
        [
            InlineKeyboardButton("\u2139\ufe0f  Help",    callback_data="do_help"),
            InlineKeyboardButton("\U0001f9f9  Clear All", callback_data="ask_clear"),
        ],
    ])

def kb_back():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2190  Back", callback_data="back_main")
    ]])

def kb_confirm_clear():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u26a0\ufe0f  Yes, stop all", callback_data="do_clear"),
            InlineKeyboardButton("\u274c  Cancel",              callback_data="back_main"),
        ]
    ])

def kb_monitor_list(uid: int):
    mons = user_monitors(uid)
    rows = []
    for m in mons:
        rows.append([InlineKeyboardButton(
            "\U0001f6d1  Stop {}  \u2014  {}".format(m["id"], m["name"][:25]),
            callback_data="stop_{}".format(m["id"])
        )])
    rows.append([InlineKeyboardButton("\u2190  Back", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

# ─────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────

async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    get_user(uid)
    await u.message.reply_text(
        build_welcome(uid),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(),
        disable_web_page_preview=True,
    )

async def cmd_help(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        build_help(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_back(),
    )

async def cmd_list(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid  = u.effective_user.id
    mons = user_monitors(uid)
    await _send_list(u.message, uid, mons)

async def _send_list(msg, uid: int, mons: list):
    if not mons:
        await msg.reply_text(
            "\U0001f4ed *No active monitors*\n\nPaste an OpenSea URL to start watching.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back(),
        )
        return

    text = "\U0001f4e1 *Active Monitors* \u2014 {}\n{}\n\n".format(len(mons), BOLD_DIV)
    for m in mons:
        text += build_monitor_card(m) + "\n\n"
    text += DIVIDER + "\nTap *Stop* to remove any monitor:"

    await msg.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_monitor_list(uid),
        disable_web_page_preview=True,
    )

async def cmd_stop(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid  = u.effective_user.id
    args = c.args
    if not args:
        await u.message.reply_text(
            "\u26a0\ufe0f Usage: `/stop <ID>`\nExample: `/stop M0001`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    mid = args[0].upper()
    if remove_monitor(uid, mid):
        await u.message.reply_text(
            "\U0001f6d1 *Monitor `{}` stopped.*\n\nNo more alerts for this one.".format(mid),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(),
        )
    else:
        await u.message.reply_text(
            "\u274c Monitor `{}` not found or not yours.".format(mid),
            parse_mode=ParseMode.MARKDOWN,
        )

async def cmd_clear(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid  = u.effective_user.id
    mons = user_monitors(uid)
    for m in mons:
        remove_monitor(uid, m["id"])
    await u.message.reply_text(
        "\U0001f9f9 *All monitors cleared.*\n\nYou have `0` active monitors now.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(),
    )

async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid  = u.effective_user.id
    mons = user_monitors(uid)
    total_alerts = sum(m.get("alerts_sent", 0) for m in mons)
    total_checks = sum(m.get("check_count", 0) for m in mons)
    u_data = get_user(uid)

    text = (
        "\U0001f4ca *Your Stats*\n"
        "{}\n"
        "   \U0001f4e1  Active monitors: `{}`\n"
        "   \U0001f514  Alerts received: `{}`\n"
        "   \U0001f504  Total checks: `{}`\n"
        "   \U0001f4c5  Member since: `{}`\n"
        "   \U0001f3ab  Status: *{}*\n"
        "{}"
    ).format(
        DIVIDER,
        len(mons), total_alerts, total_checks,
        u_data["joined"][:10],
        "Free \u2705" if is_free(uid) else "Premium",
        DIVIDER,
    )
    await u.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

# ─────────────────────────────────────────
# MESSAGE HANDLER (URL paste)
# ─────────────────────────────────────────

async def handle_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid  = u.effective_user.id
    text = u.message.text.strip()

    if not is_free(uid):
        await u.message.reply_text(
            "\U0001f512 *Access restricted.*\n\nThis bot is currently free for the first {} users only.".format(FREE_LIMIT),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if "opensea.io" not in text:
        await u.message.reply_text(
            "\U0001f449 Paste an *OpenSea URL* to start monitoring.\n\n"
            "Supported:\n"
            "  `opensea.io/collection/SLUG`\n"
            "  `opensea.io/assets/ethereum/...`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(),
        )
        return

    # Check monitor limit
    mons = user_monitors(uid)
    if len(mons) >= 10:
        await u.message.reply_text(
            "\u26a0\ufe0f *Monitor limit reached* (10 max)\n\nStop one first: `/stop <ID>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await u.message.reply_text(
        "\U0001f50d *Scanning OpenSea...*\n\nFetching data for this URL...",
        parse_mode=ParseMode.MARKDOWN,
    )

    result = await resolve_opensea_url(text)

    if not result.get("ok"):
        await msg.edit_text(
            "\u274c *Could not fetch data*\n\n_{}_\n\nMake sure it's a valid OpenSea URL.".format(
                result.get("error", "Unknown error")),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    mid = add_monitor(uid, result)
    mon = monitors[mid]

    # Set initial price
    if result["type"] == "collection":
        mon["last_floor"] = result.get("floor")
        price_line = "\U0001f4b0 *Floor:* `{}`".format(fmt_eth(mon["last_floor"]))
    else:
        mon["last_price"] = result.get("price")
        price_line = "\U0001f4b0 *Price:* `{}`".format(fmt_eth(mon["last_price"]))

    mtype_label = "Collection \U0001f5c2\ufe0f" if result["type"] == "collection" else "NFT \U0001f4e6"

    await msg.edit_text(
        "\u2705 *Monitor Started!*\n"
        "{}\n"
        "\U0001f3f7  *{}*\n"
        "\U0001f4e1  Type: {}\n"
        "{}\n"
        "   {}\n"
        "   \u23f1\ufe0f  Checking every *{}s*\n"
        "   \U0001f194  Monitor ID: `{}`\n"
        "{}\n"
        "\U0001f514 You will be notified of *any price change*.\n"
        "To stop: `/stop {}`".format(
            DIVIDER, mon["name"], mtype_label,
            DIVIDER, price_line, CHECK_INTERVAL, mid,
            DIVIDER, mid,
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("\U0001f6d1  Stop {}".format(mid), callback_data="stop_{}".format(mid)),
            InlineKeyboardButton("\U0001f4cb  My List", callback_data="do_list"),
        ]]),
        disable_web_page_preview=True,
    )

# ─────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────

async def handle_cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q   = u.callback_query
    uid = q.from_user.id
    d   = q.data
    await q.answer()

    async def edit(text, kb=None):
        await q.message.edit_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb or kb_back(),
            disable_web_page_preview=True,
        )

    if d == "back_main":
        await q.message.edit_text(
            build_welcome(uid), parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(), disable_web_page_preview=True,
        )
    elif d == "do_list":
        mons = user_monitors(uid)
        await _send_list(q.message, uid, mons)
    elif d == "do_help":
        await edit(build_help())
    elif d == "do_stats":
        await cmd_stats_from_cb(q, c)
    elif d == "ask_clear":
        await edit(
            "\u26a0\ufe0f *Stop all monitors?*\n\nThis will remove *all* your active monitors. Cannot be undone.",
            kb_confirm_clear()
        )
    elif d == "do_clear":
        mons = user_monitors(uid)
        for m in mons:
            remove_monitor(uid, m["id"])
        await edit("\U0001f9f9 *All monitors cleared.*\n\n`0` active monitors.", kb_main())
    elif d.startswith("stop_"):
        mid = d[5:]
        if remove_monitor(uid, mid):
            await edit(
                "\U0001f6d1 *Monitor `{}` stopped.*\n\nNo more alerts for this one.".format(mid),
                kb_main()
            )
        else:
            await edit("\u274c Monitor not found.", kb_main())

async def cmd_stats_from_cb(q, c):
    uid  = q.from_user.id
    mons = user_monitors(uid)
    total_alerts = sum(m.get("alerts_sent", 0) for m in mons)
    total_checks = sum(m.get("check_count", 0) for m in mons)
    u_data = get_user(uid)
    text = (
        "\U0001f4ca *Your Stats*\n"
        "{}\n"
        "   \U0001f4e1  Active monitors: `{}`\n"
        "   \U0001f514  Alerts received: `{}`\n"
        "   \U0001f504  Total checks: `{}`\n"
        "   \U0001f4c5  Member since: `{}`\n"
        "   \U0001f3ab  Status: *{}*\n"
        "{}"
    ).format(
        DIVIDER, len(mons), total_alerts, total_checks,
        u_data["joined"][:10],
        "Free \u2705" if is_free(uid) else "Premium",
        DIVIDER,
    )
    await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

# ─────────────────────────────────────────
# ADMIN COMMANDS
# ─────────────────────────────────────────

async def cmd_admin(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id != ADMIN_ID:
        return
    total_mons = sum(len(v) for v in [user_monitors(uid) for uid in users_db])
    active_mons = len([m for m in monitors.values() if m["active"]])
    total_alerts = sum(m.get("alerts_sent", 0) for m in monitors.values())
    text = (
        "\U0001f451 *Admin Panel*\n"
        "{}\n"
        "   \U0001f465  Users: `{}`\n"
        "   \U0001f4e1  Active monitors: `{}`\n"
        "   \U0001f514  Total alerts sent: `{}`\n"
        "   \U0001f39f  Free slots left: `{}`\n"
        "{}"
    ).format(
        DIVIDER,
        len(users_db),
        active_mons,
        total_alerts,
        max(0, FREE_LIMIT - len(users_db)),
        DIVIDER,
    )
    await u.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────────────────────
# PRICE MONITOR LOOP
# ─────────────────────────────────────────

async def price_monitor_loop(app: Application):
    """
    Main loop: checks all active monitors every CHECK_INTERVAL seconds.
    Sends beautiful alert messages on price changes.
    """
    logging.info("Price monitor loop started")
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        active = [m for m in monitors.values() if m["active"]]

        for mon in active:
            try:
                await _check_monitor(app, mon)
            except Exception as e:
                logging.warning("Monitor {} error: {}".format(mon["id"], e))
            await asyncio.sleep(1)  # rate limit between checks

async def _check_monitor(app: Application, mon: dict):
    uid  = mon["uid"]
    mid  = mon["id"]
    mon["check_count"] += 1

    if mon["type"] == "collection":
        data = await fetch_collection(mon["slug"])
        if not data.get("ok"):
            return
        new_val  = data.get("floor")
        old_val  = mon.get("last_floor")
        val_type = "floor"
    else:
        data = await fetch_nft_item(mon["slug"], mon.get("token_id", ""))
        if not data.get("ok"):
            return
        new_val  = data.get("price")
        old_val  = mon.get("last_price")
        val_type = "price"

    if new_val is None:
        return

    # Update stored value
    if val_type == "floor":
        mon["last_floor"] = new_val
    else:
        mon["last_price"] = new_val

    # No previous value = first check, set baseline silently
    if old_val is None:
        logging.info("Monitor {} baseline set: {} ETH".format(mid, new_val))
        return

    # Check if changed (allow 0.001 ETH tolerance)
    if abs(new_val - old_val) < 0.0001:
        return

    # Price changed! Send alert
    mon["alerts_sent"] += 1
    alert_text = build_alert_message(mon, old_val, new_val, val_type)

    try:
        await app.bot.send_message(
            chat_id=uid,
            text=alert_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "\U0001f517  View on OpenSea",
                    url=mon.get("url", "https://opensea.io")
                ),
                InlineKeyboardButton(
                    "\U0001f6d1  Stop {}".format(mid),
                    callback_data="stop_{}".format(mid)
                ),
            ]]),
        )
        logging.info("Alert sent for monitor {}: {} -> {} ETH".format(mid, old_val, new_val))
    except Exception as e:
        logging.warning("Failed to send alert for {}: {}".format(mid, e))

# ─────────────────────────────────────────
# BOT BUILD
# ─────────────────────────────────────────

def build_bot() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("clear",  cmd_clear))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("admin",  cmd_admin))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    return app

# ─────────────────────────────────────────
# FLASK KEEP-ALIVE
# ─────────────────────────────────────────

flask_app  = Flask(__name__)
_boot_time = datetime.now()

@flask_app.route("/")
def home():
    up = str(datetime.now() - _boot_time).split(".")[0]
    active_mons = len([m for m in monitors.values() if m["active"]])
    return jsonify({
        "status":   "online",
        "bot":      "NFT Price Watch",
        "uptime":   up,
        "users":    len(users_db),
        "monitors": active_mons,
    })

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@flask_app.route("/ping")
def ping():
    return "pong", 200

# ─────────────────────────────────────────
# SELF-PING (Render free tier stay-alive)
# ─────────────────────────────────────────

def self_ping():
    base = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8080")
    url  = base.rstrip("/") + "/ping"
    while True:
        time.sleep(14 * 60)
        try:
            urllib.request.urlopen(url, timeout=10)
            logging.info("Self-ping OK")
        except Exception as e:
            logging.warning("Self-ping failed: {}".format(e))

# ─────────────────────────────────────────
# BOT THREAD
# ─────────────────────────────────────────

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_app = build_bot()

    async def main():
        async with bot_app:
            await bot_app.initialize()
            await bot_app.start()
            asyncio.create_task(price_monitor_loop(bot_app))
            await bot_app.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()

    loop.run_until_complete(main())

# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    threading.Thread(target=run_bot,    daemon=True, name="Bot").start()
    threading.Thread(target=self_ping,  daemon=True, name="Ping").start()

    port = int(os.getenv("PORT", 8080))
    logging.info("Flask on port {}".format(port))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
