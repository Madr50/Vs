import os
import random
import logging
import threading
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template_string
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------------
# CONFIGURATION
# -------------------------------------------

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '7825994636'))
TON_WALLET = os.environ.get('TON_WALLET', '')
PORT = int(os.environ.get("PORT", 5000))

premium_users = set()
premium_expiry = {}

flask_app = Flask(__name__)

# -------------------------------------------
# TREND SCRAPER
# -------------------------------------------

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def get_google_trends():
    try:
        import xml.etree.ElementTree as ET
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        root = ET.fromstring(resp.content)
        out = []
        for item in root.findall('.//item')[:5]:
            title = item.find('title').text
            out.append({"name": title, "platform": "Google", "score": random.randint(75, 99),
                        "category": "Search", "momentum": "🔥 Exploding"})
        return out
    except:
        return []

def get_reddit_trends():
    try:
        url = "https://www.reddit.com/r/all/hot.json?limit=5"
        resp = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=8)
        data = resp.json()
        out = []
        for post in data.get('data', {}).get('children', [])[:5]:
            d = post['data']
            out.append({"name": d.get('title', '')[:55], "platform": "Reddit",
                        "score": random.randint(65, 92), "category": d.get('subreddit', ''),
                        "momentum": "📈 Rising"})
        return out
    except:
        return []

def get_aliexpress_trends():
    items = ["LED Strip Lights", "Mini Projector", "Magnetic Phone Mount",
             "Portable Blender", "Smart Posture Corrector", "UV Sterilizer Box",
             "Wireless Ear Buds", "Car HUD Display", "Resin Art Kit"]
    return [{"name": p, "platform": "AliExpress", "score": random.randint(65, 93),
             "category": "Products", "momentum": "📦 Hot Seller"}
            for p in random.sample(items, 3)]

def demo_trends():
    return [
        {"name": "AI Video Generators", "platform": "Google", "score": 97, "category": "Search", "momentum": "🔥 Exploding"},
        {"name": "Wireless Charging Pads", "platform": "AliExpress", "score": 89, "category": "Products", "momentum": "📦 Hot Seller"},
        {"name": "Sourdough Bread Kits", "platform": "Reddit", "score": 84, "category": "Food", "momentum": "📈 Rising"},
    ]

def get_all_trends(is_premium=False):
    trends = get_google_trends() or demo_trends()[:3]
    if is_premium:
        trends += get_reddit_trends()
        trends += get_aliexpress_trends()
    
    for t in trends:
        t["ai_prediction"] = f"{random.randint(60, 98)}% viral in 48h"
        if is_premium:
            t["recommended_action"] = random.choice(["Create content NOW", "Stock up if selling", "Write article today"])
        else:
            t["recommended_action"] = "Create content NOW"
            
    trends.sort(key=lambda x: x["score"], reverse=True)
    return trends

# -------------------------------------------
# MINI APP HTML
# -------------------------------------------

APP_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>TrendAI</title>
    <style>
        body { background: #06080f; color: white; font-family: sans-serif; text-align: center; padding: 50px; }
    </style>
</head>
<body>
    <h1>TrendAI Mini App</h1>
    <p>The app is running successfully!</p>
</body>
</html>
"""

@flask_app.route('/')
def index():
    return render_template_string(APP_HTML)

@flask_app.route('/api/trends')
def api_trends():
    user_id = request.args.get('user_id', type=int)
    is_prem = user_id in premium_users if user_id else False
    return jsonify(get_all_trends(is_premium=is_prem))

@flask_app.route('/api/status')
def api_status():
    user_id = request.args.get('user_id', type=int)
    return jsonify({"is_premium": user_id in premium_users if user_id else False})

# -------------------------------------------
# TELEGRAM BOT
# -------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    webapp_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/"
    kb = [
        [InlineKeyboardButton("🚀 Open TrendAI", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton("⭐ Go Premium – $5 USDT", callback_data="premium")],
    ]
    await update.message.reply_text(
        f"👋 Welcome {user.first_name} to *TrendAI*!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def premium_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(f"💳 Send $5 USDT to:\n`{TON_WALLET}`", parse_mode="Markdown")

# -------------------------------------------
# MAIN EXECUTION
# -------------------------------------------

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

def main():
    # تشغيل Flask في Thread منفصل
    threading.Thread(target=run_flask, daemon=True).start()
    
    # تشغيل بوت التليجرام
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(premium_cb, pattern="premium"))
    
    print("Bot is polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
