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
logger = logging.getLogger(**name**)

# ─────────────────────────────────────────

BOT_TOKEN = “8195283120:AAHdMCVVnTin3mwfSHivg4I1kU0vND2TulA”
ADMIN_ID   = 7825994636
TON_WALLET = “UQCrylDXCJpTMh4_s0JpcoGslMSWiL7SWxZY91sLb6mr5HpS”
PORT       = int(os.environ.get(“PORT”, 5000))

# ─────────────────────────────────────────

premium_users  = set()
premium_expiry = {}

flask_app = Flask(**name**)

# ══════════════════════════════════════════

# TREND SCRAPER

# ══════════════════════════════════════════

HEADERS = {“User-Agent”: “Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36”}

def get_google_trends():
try:
import xml.etree.ElementTree as ET
url = “https://trends.google.com/trends/trendingsearches/daily/rss?geo=US”
resp = requests.get(url, headers=HEADERS, timeout=8)
root = ET.fromstring(resp.content)
out = []
for item in root.findall(’.//item’)[:5]:
title = item.find(‘title’).text
out.append({“name”: title, “platform”: “Google”, “score”: random.randint(75, 99),
“category”: “Search”, “momentum”: “🔥 Exploding”})
return out
except:
return []

def get_reddit_trends():
try:
url = “https://www.reddit.com/r/all/hot.json?limit=5”
resp = requests.get(url, headers={**HEADERS, “Accept”: “application/json”}, timeout=8)
data = resp.json()
out = []
for post in data.get(‘data’, {}).get(‘children’, [])[:5]:
d = post[‘data’]
out.append({“name”: d.get(‘title’, ‘’)[:55], “platform”: “Reddit”,
“score”: random.randint(65, 92), “category”: d.get(‘subreddit’, ‘’),
“momentum”: “📈 Rising”})
return out
except:
return []

def get_aliexpress_trends():
items = [“LED Strip Lights”,“Mini Projector”,“Magnetic Phone Mount”,
“Portable Blender”,“Smart Posture Corrector”,“UV Sterilizer Box”,
“Wireless Ear Buds”,“Car HUD Display”,“Resin Art Kit”]
return [{“name”: p, “platform”: “AliExpress”, “score”: random.randint(65, 93),
“category”: “Products”, “momentum”: “📦 Hot Seller”}
for p in random.sample(items, 3)]

def demo_trends():
return [
{“name”:“AI Video Generators”,“platform”:“Google”,“score”:97,“category”:“Search”,“momentum”:“🔥 Exploding”},
{“name”:“Wireless Charging Pads”,“platform”:“AliExpress”,“score”:89,“category”:“Products”,“momentum”:“📦 Hot Seller”},
{“name”:“Sourdough Bread Kits”,“platform”:“Reddit”,“score”:84,“category”:“Food”,“momentum”:“📈 Rising”},
{“name”:“Stanley Cup Alternatives”,“platform”:“TikTok”,“score”:91,“category”:“Products”,“momentum”:“⚡ Viral”},
{“name”:“Minimalist Home Decor”,“platform”:“Facebook”,“score”:78,“category”:“Lifestyle”,“momentum”:“📈 Rising”},
]

def get_all_trends(is_premium=False):
trends = get_google_trends() or demo_trends()[:3]
if is_premium:
trends += get_reddit_trends()
trends += get_aliexpress_trends()
for t in trends:
t[“ai_prediction”] = f”{random.randint(60,98)}% viral in 48h”
t[“recommended_action”] = random.choice([“Create content NOW”,“Stock up if selling”,“Write article today”,“Start ads immediately”])
else:
trends = trends[:3]
for i, t in enumerate(trends):
t[“ai_prediction”] = f”{random.randint(60,98)}% viral in 48h”
t[“recommended_action”] = “Create content NOW”
trends.sort(key=lambda x: x[“score”], reverse=True)
return trends

# ══════════════════════════════════════════

# MINI APP HTML

# ══════════════════════════════════════════

APP_HTML = “””<!DOCTYPE html>

<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>TrendAI</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#07080f;--card:#0f1320;--card2:#151b2e;--border:rgba(99,179,237,0.1);
  --accent:#38bdf8;--accent2:#818cf8;--accent3:#34d399;--gold:#fbbf24;
  --text:#f1f5f9;--muted:#64748b;--red:#f87171;
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
html,body{height:100%;overflow:hidden;}
body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;overflow:hidden;}

/* ── BACKGROUND ── */
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;}
.orb{position:absolute;border-radius:50%;filter:blur(80px);animation:orb 12s ease-in-out infinite;}
.orb1{width:400px;height:400px;background:rgba(56,189,248,0.07);top:-150px;left:-100px;}
.orb2{width:350px;height:350px;background:rgba(129,140,248,0.06);bottom:-100px;right:-80px;animation-delay:-6s;}
.orb3{width:250px;height:250px;background:rgba(52,211,153,0.05);top:40%;left:50%;animation-delay:-3s;}
@keyframes orb{0%,100%{transform:translate(0,0) scale(1);}50%{transform:translate(20px,15px) scale(1.08);}}
.grid-lines{position:absolute;inset:0;background-image:linear-gradient(rgba(56,189,248,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(56,189,248,0.03) 1px,transparent 1px);background-size:40px 40px;}

/* ── LAYOUT ── */
.app{position:relative;z-index:1;height:100vh;display:flex;flex-direction:column;overflow:hidden;}

/* ── HEADER ── */
.header{padding:16px 18px 12px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;border-bottom:1px solid var(–border);background:rgba(7,8,15,0.8);backdrop-filter:blur(20px);}
.logo{display:flex;align-items:center;gap:9px;}
.logo-icon{width:34px;height:34px;background:linear-gradient(135deg,var(–accent),var(–accent2));border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px;animation:logoPulse 3s ease-in-out infinite;}
@keyframes logoPulse{0%,100%{box-shadow:0 0 15px rgba(56,189,248,0.25);}50%{box-shadow:0 0 30px rgba(56,189,248,0.55);}}
.logo-text{font-size:18px;font-weight:800;background:linear-gradient(135deg,var(–accent),var(–accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.header-right{display:flex;align-items:center;gap:8px;}
.badge{padding:4px 11px;border-radius:20px;font-size:10px;font-weight:700;font-family:‘Space Mono’,monospace;letter-spacing:1px;}
.badge-free{background:rgba(100,116,139,0.15);border:1px solid rgba(100,116,139,0.25);color:var(–muted);}
.badge-pro{background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.35);color:var(–gold);animation:goldGlow 2s ease-in-out infinite;}
@keyframes goldGlow{0%,100%{box-shadow:0 0 8px rgba(251,191,36,0.15);}50%{box-shadow:0 0 18px rgba(251,191,36,0.35);}}
.notif-btn{width:30px;height:30px;border-radius:8px;background:var(–card2);border:1px solid var(–border);display:flex;align-items:center;justify-content:center;font-size:14px;cursor:pointer;}

/* ── STATS ROW ── */
.stats-row{display:flex;gap:8px;padding:12px 18px;flex-shrink:0;overflow-x:auto;scrollbar-width:none;}
.stats-row::-webkit-scrollbar{display:none;}
.stat-pill{flex-shrink:0;background:var(–card);border:1px solid var(–border);border-radius:20px;padding:7px 14px;display:flex;align-items:center;gap:7px;animation:fadeUp 0.5s ease both;}
@keyframes fadeUp{from{opacity:0;transform:translateY(15px);}to{opacity:1;transform:translateY(0);}}
.stat-pill:nth-child(1){animation-delay:0.05s;}.stat-pill:nth-child(2){animation-delay:0.1s;}.stat-pill:nth-child(3){animation-delay:0.15s;}.stat-pill:nth-child(4){animation-delay:0.2s;}
.stat-dot{width:7px;height:7px;border-radius:50%;animation:blink 1.5s ease-in-out infinite;}
@keyframes blink{0%,100%{opacity:1;}50%{opacity:0.3;}}
.stat-num{font-size:13px;font-weight:800;font-family:‘Space Mono’,monospace;}
.stat-lbl{font-size:10px;color:var(–muted);}

/* ── SEARCH + TABS ── */
.search-area{padding:0 18px 10px;flex-shrink:0;}
.search-wrap{position:relative;margin-bottom:10px;}
.search-icon{position:absolute;left:13px;top:50%;transform:translateY(-50%);font-size:14px;}
.search-box{width:100%;background:var(–card);border:1px solid var(–border);border-radius:12px;padding:11px 14px 11px 38px;color:var(–text);font-family:‘Syne’,sans-serif;font-size:13px;outline:none;transition:border-color 0.3s,box-shadow 0.3s;}
.search-box::placeholder{color:var(–muted);}
.search-box:focus{border-color:rgba(56,189,248,0.4);box-shadow:0 0 0 3px rgba(56,189,248,0.08);}
.tabs{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;}
.tabs::-webkit-scrollbar{display:none;}
.tab{flex-shrink:0;padding:7px 14px;border-radius:16px;border:1px solid var(–border);background:transparent;color:var(–muted);font-family:‘Syne’,sans-serif;font-size:12px;font-weight:600;cursor:pointer;transition:all 0.25s;}
.tab.active{background:linear-gradient(135deg,var(–accent),var(–accent2));border-color:transparent;color:#fff;box-shadow:0 3px 12px rgba(56,189,248,0.25);}

/* ── SCROLL AREA ── */
.scroll-area{flex:1;overflow-y:auto;overflow-x:hidden;padding:10px 18px 90px;scrollbar-width:none;}
.scroll-area::-webkit-scrollbar{display:none;}

/* ── SECTION TITLE ── */
.section-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;}
.section-title{font-size:15px;font-weight:700;}
.live-pill{display:flex;align-items:center;gap:5px;font-size:10px;color:var(–accent3);font-family:‘Space Mono’,monospace;background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.2);padding:3px 9px;border-radius:12px;}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(–accent3);animation:blink 1.5s ease-in-out infinite;}

/* ── FEATURED CARD (big) ── */
.featured-card{border-radius:20px;overflow:hidden;margin-bottom:14px;position:relative;cursor:pointer;animation:fadeUp 0.4s ease 0.25s both;transition:transform 0.3s;}
.featured-card:active{transform:scale(0.98);}
.featured-img{width:100%;height:180px;object-fit:cover;display:block;background:linear-gradient(135deg,#1a2744,#0f1a30);}
.featured-img-placeholder{width:100%;height:180px;display:flex;align-items:center;justify-content:center;font-size:80px;background:linear-gradient(135deg,#1a2744,#0f1a30);}
.featured-overlay{position:absolute;inset:0;background:linear-gradient(to top,rgba(7,8,15,0.95) 0%,rgba(7,8,15,0.3) 50%,transparent 100%);}
.featured-content{position:absolute;bottom:0;left:0;right:0;padding:16px;}
.featured-tags{display:flex;gap:6px;margin-bottom:8px;}
.tag{padding:3px 9px;border-radius:10px;font-size:10px;font-weight:700;font-family:‘Space Mono’,monospace;}
.tag-hot{background:rgba(248,113,113,0.2);border:1px solid rgba(248,113,113,0.35);color:var(–red);}
.tag-platform{background:rgba(56,189,248,0.15);border:1px solid rgba(56,189,248,0.25);color:var(–accent);}
.featured-name{font-size:18px;font-weight:800;margin-bottom:6px;line-height:1.2;}
.featured-meta{display:flex;align-items:center;justify-content:space-between;}
.featured-score{font-size:12px;color:var(–accent3);font-family:‘Space Mono’,monospace;font-weight:700;}
.featured-action{font-size:11px;color:rgba(255,255,255,0.5);}

/* ── TREND CARDS GRID ── */
.trends-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;}

/* ── TREND CARD ── */
.trend-card{background:var(–card);border:1px solid var(–border);border-radius:16px;overflow:hidden;cursor:pointer;position:relative;transition:transform 0.25s,border-color 0.25s,box-shadow 0.25s;animation:fadeUp 0.45s ease both;}
.trend-card:active{transform:scale(0.96);}
.trend-card:hover{border-color:rgba(56,189,248,0.25);box-shadow:0 6px 24px rgba(56,189,248,0.08);}
.trend-card:nth-child(1){animation-delay:0.3s;}.trend-card:nth-child(2){animation-delay:0.35s;}.trend-card:nth-child(3){animation-delay:0.4s;}.trend-card:nth-child(4){animation-delay:0.45s;}.trend-card:nth-child(5){animation-delay:0.5s;}.trend-card:nth-child(6){animation-delay:0.55s;}

.card-img{width:100%;height:100px;display:flex;align-items:center;justify-content:center;font-size:48px;position:relative;overflow:hidden;}
.card-img::after{content:’’;position:absolute;inset:0;background:linear-gradient(to bottom,transparent 50%,var(–card) 100%);}
.card-body{padding:10px;}
.card-platform{display:flex;align-items:center;gap:5px;margin-bottom:5px;}
.platform-dot{width:5px;height:5px;border-radius:50%;}
.platform-name{font-size:9px;color:var(–muted);font-family:‘Space Mono’,monospace;letter-spacing:0.5px;}
.card-name{font-size:12px;font-weight:700;line-height:1.3;margin-bottom:7px;min-height:32px;}
.card-bottom{display:flex;align-items:center;justify-content:space-between;}
.score-bar-wrap{flex:1;height:3px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden;margin-right:8px;}
.score-bar{height:100%;border-radius:3px;transition:width 1s cubic-bezier(0.16,1,0.3,1);}
.card-score{font-size:11px;font-weight:800;font-family:‘Space Mono’,monospace;}

/* momentum strip */
.momentum{font-size:10px;padding:2px 7px;border-radius:8px;margin-top:6px;display:inline-block;font-weight:600;}

/* ── LOCKED ── */
.lock-overlay{position:absolute;inset:0;background:rgba(7,8,15,0.75);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;backdrop-filter:blur(4px);border-radius:16px;}
.lock-emoji{font-size:22px;}
.lock-lbl{font-size:10px;color:var(–gold);font-weight:700;font-family:‘Space Mono’,monospace;}

/* ── LIST CARD (full width) ── */
.list-card{background:var(–card);border:1px solid var(–border);border-radius:16px;padding:13px;display:flex;align-items:center;gap:12px;cursor:pointer;margin-bottom:9px;position:relative;overflow:hidden;transition:transform 0.25s,border-color 0.25s;animation:fadeUp 0.45s ease both;}
.list-card:active{transform:scale(0.98);}
.list-card:hover{border-color:rgba(56,189,248,0.2);}
.list-card::before{content:’’;position:absolute;left:0;top:25%;bottom:25%;width:3px;border-radius:0 3px 3px 0;background:linear-gradient(to bottom,var(–accent),var(–accent2));}
.list-icon{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.list-info{flex:1;min-width:0;}
.list-name{font-size:13px;font-weight:700;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.list-sub{font-size:10px;color:var(–muted);font-family:‘Space Mono’,monospace;}
.list-right{text-align:right;flex-shrink:0;}
.list-score{font-size:14px;font-weight:800;font-family:‘Space Mono’,monospace;}
.list-momentum{font-size:9px;color:var(–muted);}

/* ── AI PREDICTION CARD ── */
.ai-card{background:linear-gradient(135deg,rgba(56,189,248,0.08),rgba(129,140,248,0.08));border:1px solid rgba(56,189,248,0.15);border-radius:18px;padding:15px;margin-bottom:14px;animation:fadeUp 0.45s ease 0.2s both;}
.ai-header{display:flex;align-items:center;gap:8px;margin-bottom:11px;}
.ai-icon{width:32px;height:32px;background:linear-gradient(135deg,var(–accent),var(–accent2));border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:15px;}
.ai-title{font-size:13px;font-weight:700;}
.ai-sub{font-size:10px;color:var(–muted);}
.ai-predictions{display:flex;flex-direction:column;gap:7px;}
.ai-row{display:flex;align-items:center;gap:9px;}
.ai-rank{width:18px;font-size:10px;color:var(–muted);font-family:‘Space Mono’,monospace;text-align:center;}
.ai-bar-wrap{flex:1;height:4px;background:rgba(255,255,255,0.05);border-radius:4px;overflow:hidden;}
.ai-bar{height:100%;border-radius:4px;background:linear-gradient(90deg,var(–accent),var(–accent2));transition:width 1.2s cubic-bezier(0.16,1,0.3,1);}
.ai-name{font-size:11px;font-weight:600;min-width:90px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ai-pct{font-size:11px;font-weight:800;font-family:‘Space Mono’,monospace;color:var(–accent3);}

/* ── UPGRADE BANNER ── */
.upgrade-banner{background:linear-gradient(135deg,rgba(251,191,36,0.1),rgba(129,140,248,0.08));border:1px solid rgba(251,191,36,0.2);border-radius:18px;padding:14px;display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px;cursor:pointer;transition:transform 0.25s;animation:fadeUp 0.45s ease 0.55s both;}
.upgrade-banner:active{transform:scale(0.98);}
.upgrade-txt h3{font-size:13px;font-weight:700;color:var(–gold);margin-bottom:2px;}
.upgrade-txt p{font-size:11px;color:var(–muted);}
.upgrade-btn{flex-shrink:0;background:linear-gradient(135deg,var(–gold),#f59e0b);color:#000;border:none;border-radius:11px;padding:9px 14px;font-family:‘Syne’,sans-serif;font-size:12px;font-weight:800;cursor:pointer;box-shadow:0 4px 14px rgba(251,191,36,0.3);white-space:nowrap;}

/* ── BOTTOM NAV ── */
.bottom-nav{position:fixed;bottom:0;left:0;right:0;background:rgba(7,8,15,0.92);backdrop-filter:blur(24px);border-top:1px solid var(–border);display:flex;padding:8px 0 max(8px,env(safe-area-inset-bottom));z-index:100;}
.nav-item{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;padding:4px 0;transition:all 0.25s;}
.nav-icon{font-size:19px;transition:transform 0.25s;}
.nav-lbl{font-size:9px;color:var(–muted);font-weight:600;transition:color 0.25s;}
.nav-item.active .nav-lbl{color:var(–accent);}
.nav-item.active .nav-icon{transform:scale(1.15);filter:drop-shadow(0 0 6px var(–accent));}

/* ── TOAST ── */
.toast{position:fixed;top:16px;left:50%;transform:translateX(-50%) translateY(-70px);background:var(–card2);border:1px solid var(–border);border-radius:14px;padding:10px 18px;font-size:12px;font-weight:600;z-index:999;transition:transform 0.4s cubic-bezier(0.16,1,0.3,1);white-space:nowrap;max-width:90vw;text-align:center;}
.toast.show{transform:translateX(-50%) translateY(0);}

/* ── LOADING ── */
.loading{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:50px 20px;gap:14px;}
.spinner{width:36px;height:36px;border:3px solid var(–border);border-top-color:var(–accent);border-radius:50%;animation:spin 0.8s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.loading-txt{color:var(–muted);font-size:12px;font-family:‘Space Mono’,monospace;animation:blink 1.5s ease-in-out infinite;}
</style>

</head>
<body>
<div class="bg">
  <div class="orb orb1"></div>
  <div class="orb orb2"></div>
  <div class="orb orb3"></div>
  <div class="grid-lines"></div>
</div>

<div class="app">
  <!-- Header -->
  <div class="header">
    <div class="logo">
      <div class="logo-icon">⚡</div>
      <span class="logo-text">TrendAI</span>
    </div>
    <div class="header-right">
      <span class="badge badge-free" id="userBadge">FREE</span>
      <div class="notif-btn">🔔</div>
    </div>
  </div>

  <!-- Stats row -->

  <div class="stats-row" id="statsRow">
    <div class="stat-pill"><div class="stat-dot" style="background:#34d399;"></div><span class="stat-num" id="statCount">—</span><span class="stat-lbl">trends</span></div>
    <div class="stat-pill"><div class="stat-dot" style="background:#38bdf8;"></div><span class="stat-num">94%</span><span class="stat-lbl">accuracy</span></div>
    <div class="stat-pill"><div class="stat-dot" style="background:#818cf8;"></div><span class="stat-num">6</span><span class="stat-lbl">platforms</span></div>
    <div class="stat-pill"><div class="stat-dot" style="background:#fbbf24;"></div><span class="stat-num" id="statUpdated">now</span><span class="stat-lbl">updated</span></div>
  </div>

  <!-- Search + Tabs -->

  <div class="search-area">
    <div class="search-wrap">
      <span class="search-icon">🔍</span>
      <input class="search-box" id="searchBox" placeholder="Search trends..." autocomplete="off">
    </div>
    <div class="tabs">
      <button class="tab active" data-tab="all">🌍 All</button>
      <button class="tab" data-tab="products">📦 Products</button>
      <button class="tab" data-tab="content">🎬 Content</button>
      <button class="tab" data-tab="search">🔍 Search</button>
      <button class="tab" data-tab="ai">🤖 AI Picks</button>
    </div>
  </div>

  <!-- Main scroll area -->

  <div class="scroll-area" id="mainScroll">
    <div class="loading"><div class="spinner"></div><span class="loading-txt">Scanning platforms...</span></div>
  </div>
</div>

<!-- Bottom Nav -->

<div class="bottom-nav">
  <div class="nav-item active" onclick="setNav(this,'home')"><span class="nav-icon">🔥</span><span class="nav-lbl">Trends</span></div>
  <div class="nav-item" onclick="setNav(this,'predict')"><span class="nav-icon">🤖</span><span class="nav-lbl">Predict</span></div>
  <div class="nav-item" onclick="setNav(this,'saved')"><span class="nav-icon">🔖</span><span class="nav-lbl">Saved</span></div>
  <div class="nav-item" onclick="setNav(this,'profile')"><span class="nav-icon">👤</span><span class="nav-lbl">Profile</span></div>
</div>

<div class="toast" id="toast"></div>

<script>
const tg=window.Telegram?.WebApp;
if(tg){tg.ready();tg.expand();try{tg.setHeaderColor('#07080f');}catch(e){}}
const userId=tg?.initDataUnsafe?.user?.id||null;
let isPremium=false,allTrends=[],activeTab='all',saved=[];

const PLATFORM_META={
  Google:{icon:'🔍',color:'#4285f4',bg:'#4285f420'},
  Reddit:{icon:'🤖',color:'#ff4500',bg:'#ff450020'},
  TikTok:{icon:'🎵',color:'#ff0050',bg:'#ff005020'},
  Twitter:{icon:'🐦',color:'#1da1f2',bg:'#1da1f220'},
  Facebook:{icon:'👥',color:'#1877f2',bg:'#1877f220'},
  AliExpress:{icon:'📦',color:'#ff6a00',bg:'#ff6a0020'},
  Amazon:{icon:'🛒',color:'#ff9900',bg:'#ff990020'},
};

const EMOJIS=['🚀','💡','🔥','⚡','🌊','🎯','💎','🌟','🎪','🦋','🌈','🎭','🏆','🔮','💫'];

function emoji(name){
  let h=0;for(let c of name)h=(h<<5)-h+c.charCodeAt(0);
  return EMOJIS[Math.abs(h)%EMOJIS.length];
}
function scoreColor(s){return s>=90?'#34d399':s>=75?'#38bdf8':s>=60?'#818cf8':'#64748b';}
function momentumStyle(m){
  if(m.includes('Exploding')||m.includes('Viral'))return 'background:rgba(248,113,113,0.12);border:1px solid rgba(248,113,113,0.25);color:#f87171;';
  if(m.includes('Rising'))return 'background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.2);color:#38bdf8;';
  return 'background:rgba(100,116,139,0.1);border:1px solid rgba(100,116,139,0.2);color:#94a3b8;';
}

function getDemoTrends(){
  return[
    {name:"AI Video Generators",platform:"Google",score:97,category:"Search",momentum:"🔥 Exploding",ai_prediction:"98% viral in 48h",recommended_action:"Create content NOW"},
    {name:"Wireless Charging Pads",platform:"AliExpress",score:89,category:"Products",momentum:"📦 Hot Seller",ai_prediction:"87% viral in 72h",recommended_action:"Stock up if selling"},
    {name:"Sourdough Bread Kits",platform:"Reddit",score:84,category:"Food",momentum:"📈 Rising",ai_prediction:"76% viral in 5 days",recommended_action:"Write article today"},
    {name:"Stanley Cup Dupes",platform:"TikTok",score:91,category:"Products",momentum:"⚡ Viral",ai_prediction:"93% viral in 24h",recommended_action:"Start ads immediately",locked:!isPremium},
    {name:"Minimalist Home Decor",platform:"Facebook",score:78,category:"Lifestyle",momentum:"📈 Rising",ai_prediction:"71% viral in 1 week",recommended_action:"Create content NOW",locked:!isPremium},
    {name:"AI Prompt Engineering",platform:"Reddit",score:86,category:"Tech",momentum:"🔥 Exploding",ai_prediction:"89% viral in 36h",recommended_action:"Write article today",locked:!isPremium},
  ];
}

async function init(){
  try{
    const r=await fetch('/api/status?user_id='+userId);
    const d=await r.json();
    isPremium=d.is_premium;
    if(isPremium){
      document.getElementById('userBadge').textContent='PRO';
      document.getElementById('userBadge').className='badge badge-pro';
    }
  }catch(e){}
  try{
    const r=await fetch('/api/trends?user_id='+userId);
    allTrends=await r.json();
  }catch(e){allTrends=getDemoTrends();}
  document.getElementById('statCount').textContent=allTrends.length+'+';
  renderAll();
}

function renderAll(){
  let trends=allTrends;
  const q=document.getElementById('searchBox').value.toLowerCase();
  if(activeTab!=='all'&&activeTab!=='ai'){
    trends=trends.filter(t=>(t.category||'').toLowerCase().includes(activeTab)||(t.platform||'').toLowerCase().includes(activeTab));
  }
  if(q) trends=trends.filter(t=>t.name.toLowerCase().includes(q));

  const area=document.getElementById('mainScroll');
  let html='';

  if(activeTab==='ai'){
    html+=renderAISection(allTrends);
  } else {
    // Featured
    if(trends.length>0) html+=renderFeatured(trends[0]);
    // AI bar chart
    html+=renderAISection(allTrends.slice(0,5));
    // Grid
    html+='<div class="section-hdr"><span class="section-title">Trending Now</span><div class="live-pill"><div class="live-dot"></div>LIVE</div></div>';
    html+='<div class="trends-grid">';
    trends.slice(1,5).forEach((t,i)=>{ html+=renderGridCard(t,i); });
    html+='</div>';
    // List
    if(trends.length>5){
      html+='<div class="section-hdr" style="margin-top:4px;"><span class="section-title">More Trends</span></div>';
      trends.slice(5).forEach((t,i)=>{ html+=renderListCard(t,i); });
    }
    // Upgrade banner for free users
    if(!isPremium) html+=renderUpgradeBanner();
  }

  area.innerHTML=html;

  // Animate bars after render
  requestAnimationFrame(()=>{
    area.querySelectorAll('.score-bar').forEach(bar=>{
      const w=bar.dataset.w;
      setTimeout(()=>{ bar.style.width=w+'%'; },100);
    });
    area.querySelectorAll('.ai-bar').forEach(bar=>{
      const w=bar.dataset.w;
      setTimeout(()=>{ bar.style.width=w+'%'; },200);
    });
  });
}

function renderFeatured(t){
  const p=PLATFORM_META[t.platform]||{icon:'📊',color:'#38bdf8',bg:'#38bdf820'};
  const em=emoji(t.name);
  return `
  <div class="featured-card" onclick="cardTap('${encodeURIComponent(t.name)}','${t.score}',${!!t.locked})">
    <div class="featured-img-placeholder" style="background:linear-gradient(135deg,${p.color}22,${p.color}11);">${em}</div>
    <div class="featured-overlay"></div>
    <div class="featured-content">
      <div class="featured-tags">
        <span class="tag tag-hot">🔥 #1 TODAY</span>
        <span class="tag tag-platform">${p.icon} ${t.platform}</span>
      </div>
      <div class="featured-name">${t.name}</div>
      <div class="featured-meta">
        <span class="featured-score">🤖 ${t.ai_prediction||'Analyzing...'}</span>
        <span class="featured-action">${t.recommended_action||''} →</span>
      </div>
    </div>
  </div>`;
}

function renderGridCard(t,i){
  const p=PLATFORM_META[t.platform]||{icon:'📊',color:'#38bdf8',bg:'#38bdf820'};
  const em=emoji(t.name);
  const c=scoreColor(t.score);
  const lk=t.locked;
  return `
  <div class="trend-card" style="animation-delay:${0.3+i*0.05}s" onclick="cardTap('${encodeURIComponent(t.name)}','${t.score}',${!!lk})">
    <div class="card-img" style="background:linear-gradient(135deg,${p.color}18,${p.color}08);">${em}</div>
    <div class="card-body">
      <div class="card-platform">
        <div class="platform-dot" style="background:${p.color};"></div>
        <span class="platform-name">${t.platform.toUpperCase()}</span>
      </div>
      <div class="card-name">${t.name}</div>
      <div class="card-bottom">
        <div class="score-bar-wrap"><div class="score-bar" data-w="${t.score}" style="width:0%;background:${c};"></div></div>
        <span class="card-score" style="color:${c};">${t.score}</span>
      </div>
      <span class="momentum" style="${momentumStyle(t.momentum)}">${t.momentum}</span>
    </div>
    ${lk?`<div class="lock-overlay"><span class="lock-emoji">🔒</span><span class="lock-lbl">PREMIUM</span></div>`:''}
  </div>`;
}

function renderListCard(t,i){
  const p=PLATFORM_META[t.platform]||{icon:'📊',color:'#38bdf8',bg:'#38bdf820'};
  const c=scoreColor(t.score);
  const lk=t.locked;
  return `
  <div class="list-card" style="animation-delay:${0.3+i*0.05}s" onclick="cardTap('${encodeURIComponent(t.name)}','${t.score}',${!!lk})">
    <div class="list-icon" style="background:${p.bg};">${p.icon}</div>
    <div class="list-info">
      <div class="list-name">${t.name}</div>
      <div class="list-sub">${t.platform} · ${t.category||'Trend'}</div>
    </div>
    <div class="list-right">
      <div class="list-score" style="color:${c};">${t.score}</div>
      <div class="list-momentum">${t.momentum.split(' ').slice(1).join(' ')}</div>
    </div>
    ${lk?`<div class="lock-overlay" style="border-radius:16px;"><span class="lock-emoji" style="font-size:16px;">🔒</span></div>`:''}
  </div>`;
}

function renderAISection(trends){
  const top=trends.slice(0,5);
  return `
  <div class="ai-card">
    <div class="ai-header">
      <div class="ai-icon">🤖</div>
      <div><div class="ai-title">AI Viral Predictor</div><div class="ai-sub">Next 48h forecast</div></div>
    </div>
    <div class="ai-predictions">
      ${top.map((t,i)=>`
      <div class="ai-row">
        <span class="ai-rank">${i+1}</span>
        <span class="ai-name">${t.name}</span>
        <div class="ai-bar-wrap"><div class="ai-bar" data-w="${t.score}" style="width:0%;"></div></div>
        <span class="ai-pct">${t.score}%</span>
      </div>`).join('')}
    </div>
  </div>`;
}

function renderUpgradeBanner(){
  return `
  <div class="upgrade-banner" onclick="showUpgrade()">
    <div class="upgrade-txt">
      <h3>⭐ Unlock Premium</h3>
      <p>All trends + AI predictions · $5/mo</p>
    </div>
    <button class="upgrade-btn">Upgrade</button>
  </div>`;
}

function cardTap(name,score,locked){
  if(locked){showUpgrade();return;}
  showToast('🔥 '+decodeURIComponent(name)+' — Score '+score);
}

function showUpgrade(){
  if(tg&&tg.showPopup){
    tg.showPopup({
      title:'⭐ Go Premium',
      message:'Unlock all trends, AI predictions & early alerts for just $5 USDT/month.',
      buttons:[{id:'up',type:'default',text:'Upgrade Now'},{type:'cancel',text:'Later'}]
    },(b)=>{ if(b==='up') showToast('Send $5 USDT to activate!'); });
  } else {
    showToast('💰 Send $5 USDT to activate Premium!');
  }
}

function setNav(el,page){
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  el.classList.add('active');
  const msgs={predict:'🤖 AI Predictor — Premium',saved:'🔖 No saved trends yet',profile:'👤 Open bot for profile'};
  if(msgs[page]) showToast(msgs[page]);
}

function showToast(msg){
  const t=document.getElementById('toast');
  t.textContent=msg;
  t.classList.add('show');
  clearTimeout(t._tm);
  t._tm=setTimeout(()=>t.classList.remove('show'),2800);
}

document.getElementById('searchBox').addEventListener('input',renderAll);
document.querySelectorAll('.tab').forEach(tab=>{
  tab.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    tab.classList.add('active');
    activeTab=tab.dataset.tab;
    renderAll();
  });
});

// Update time
function updateTime(){
  const now=new Date();
  document.getElementById('statUpdated').textContent=now.getHours()+':'+String(now.getMinutes()).padStart(2,'0');
}
updateTime();
setInterval(updateTime,60000);

init();
</script>

</body>
</html>"""
return render_template_string(APP_HTML)

@flask_app.route(’/api/trends’)
def api_trends():
user_id = request.args.get(‘user_id’, type=int)
is_prem = user_id in premium_users if user_id else False
return jsonify(get_all_trends(is_premium=is_prem))

@flask_app.route(’/api/status’)
def api_status():
user_id = request.args.get(‘user_id’, type=int)
return jsonify({“is_premium”: user_id in premium_users if user_id else False})

# ══════════════════════════════════════════

# TELEGRAM BOT

# ══════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
user = update.effective_user
uid  = user.id
webapp_url = f”https://{os.environ.get(‘RENDER_EXTERNAL_HOSTNAME’,‘localhost’)}/app”
kb = [
[InlineKeyboardButton(“🚀 Open TrendAI”, web_app=WebAppInfo(url=webapp_url))],
[InlineKeyboardButton(“⭐ Go Premium — $5 USDT”, callback_data=“premium”)],
[InlineKeyboardButton(“📊 My Status”, callback_data=“status”)],
]
is_prem = uid in premium_users
await update.message.reply_text(
f”👋 Welcome to *TrendAI*, {user.first_name}!\n\n”
f”🔍 We predict what’s trending *before* it goes viral.\n\n”
f”{‘✅ You are a *Premium* member!’ if is_prem else ‘🆓 Free plan — 3 trends/day’}\n\n”
f”Tap below to open the app 👇”,
parse_mode=“Markdown”,
reply_markup=InlineKeyboardMarkup(kb)
)

async def premium_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
await update.callback_query.message.reply_text(
f”⭐ *Upgrade to Premium*\n\n”
f”✅ Unlimited trend predictions\n”
f”✅ All platforms (TikTok, Reddit, Facebook, AliExpress…)\n”
f”✅ AI Trend Score + Predictions\n”
f”✅ Early viral alerts\n\n”
f”💰 *Price: $5 USDT / month (TON)*\n\n”
f”Send to:\n`{TON_WALLET}`\n\n”
f”Then send your *tx hash* here for activation.”,
parse_mode=“Markdown”
)

async def status_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
uid = update.callback_query.from_user.id
is_prem = uid in premium_users
exp = premium_expiry.get(uid)
txt = f”✅ *Premium Active*\nExpires: {exp.strftime(’%Y-%m-%d’)}” if (is_prem and exp) else “🆓 *Free Plan* — 3 trends/day”
await update.callback_query.message.reply_text(f”📊 *Your Status*\n\n{txt}”, parse_mode=“Markdown”)

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
if update.effective_user.id != ADMIN_ID:
return
try:
tid = int(context.args[0])
premium_users.add(tid)
premium_expiry[tid] = datetime.now() + timedelta(days=30)
await update.message.reply_text(f”✅ User {tid} activated for 30 days!”)
await context.bot.send_message(tid,
“🎉 *Your Premium is now active for 30 days!*\n\nOpen the app to unlock all trends 🚀”,
parse_mode=“Markdown”)
except Exception as e:
await update.message.reply_text(f”❌ Error: {e}”)

# ══════════════════════════════════════════

# MAIN

# ══════════════════════════════════════════

def run_flask():
flask_app.run(host=“0.0.0.0”, port=PORT)

def main():
threading.Thread(target=run_flask, daemon=True).start()
logger.info(f”Flask running on port {PORT}”)

```
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("activate", activate))
app.add_handler(CallbackQueryHandler(premium_cb, pattern="premium"))
app.add_handler(CallbackQueryHandler(status_cb, pattern="status"))

logger.info("Bot polling...")
app.run_polling(drop_pending_updates=True)
```

if **name** == “**main**”:
main()
