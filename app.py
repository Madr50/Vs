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

# =========================================

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '7825994636'))
TON_WALLET = os.environ.get('TON_WALLET', '')
PORT       = int(os.environ.get("PORT", 5000))

# =========================================

premium_users  = set()
premium_expiry = {}

flask_app = Flask(__name__)

# ==========================================
# TREND SCRAPER
# ==========================================

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
                        "category": "Search", "momentum": "? Exploding"})
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
                        "momentum": "? Rising"})
        return out
    except:
        return []

def get_aliexpress_trends():
    items = ["LED Strip Lights","Mini Projector","Magnetic Phone Mount",
             "Portable Blender","Smart Posture Corrector","UV Sterilizer Box",
             "Wireless Ear Buds","Car HUD Display","Resin Art Kit"]
    return [{"name": p, "platform": "AliExpress", "score": random.randint(65, 93),
             "category": "Products", "momentum": "? Hot Seller"}
            for p in random.sample(items, 3)]

def demo_trends():
    return [
        {"name":"AI Video Generators","platform":"Google","score":97,"category":"Search","momentum":"? Exploding"},
        {"name":"Wireless Charging Pads","platform":"AliExpress","score":89,"category":"Products","momentum":"? Hot Seller"},
        {"name":"Sourdough Bread Kits","platform":"Reddit","score":84,"category":"Food","momentum":"? Rising"},
        {"name":"Stanley Cup Alternatives","platform":"TikTok","score":91,"category":"Products","momentum":"? Viral"},
        {"name":"Minimalist Home Decor","platform":"Facebook","score":78,"category":"Lifestyle","momentum":"? Rising"},
    ]

def get_all_trends(is_premium=False):
    trends = get_google_trends() or demo_trends()[:3]
    if is_premium:
        trends += get_reddit_trends()
        trends += get_aliexpress_trends()
        for t in trends:
            t["ai_prediction"] = f"{random.randint(60,98)}% viral in 48h"
            t["recommended_action"] = random.choice(["Create content NOW","Stock up if selling","Write article today","Start ads immediately"])
    else:
        trends = trends[:3]
        for i, t in enumerate(trends):
            t["ai_prediction"] = f"{random.randint(60,98)}% viral in 48h"
            t["recommended_action"] = "Create content NOW"
    
    trends.sort(key=lambda x: x["score"], reverse=True)
    return trends

# ==========================================
# MINI APP HTML
# ==========================================

APP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>TrendAI</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#06080f;--c1:#0d1425;--c2:#111b30;
  --accent:#38bdf8;--p2:#818cf8;--p3:#34d399;--gold:#fbbf24;--red:#f87171;
  --txt:#f1f5f9;--muted:#64748b;--border:rgba(99,179,237,0.09);
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
html,body{height:100%;overflow:hidden;background:var(--bg);}
body{font-family:'Syne',sans-serif;color:var(--txt);}

/* BG */
.bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;}
.orb{position:absolute;border-radius:50%;filter:blur(70px);animation:orbF 14s ease-in-out infinite;}
.o1{width:500px;height:500px;background:rgba(56,189,248,0.06);top:-200px;left:-150px;}
.o2{width:400px;height:400px;background:rgba(129,140,248,0.05);bottom:-150px;right:-100px;animation-delay:-7s;}
.o3{width:300px;height:300px;background:rgba(52,211,153,0.04);top:35%;left:40%;animation-delay:-3.5s;}
@keyframes orbF{0%,100%{transform:translate(0,0) scale(1);}50%{transform:translate(25px,18px) scale(1.07);}}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(56,189,248,0.025) 1px,transparent 1px),linear-gradient(90deg,rgba(56,189,248,0.025) 1px,transparent 1px);background-size:44px 44px;}
.grain{position:absolute;inset:0;opacity:0.018;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");}

/* LAYOUT */
.app{position:relative;z-index:1;height:100vh;display:flex;flex-direction:column;overflow:hidden;}

/* HEADER */
.hdr{flex-shrink:0;padding:14px 18px 12px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);background:rgba(6,8,15,0.85);backdrop-filter:blur(24px);}
.logo{display:flex;align-items:center;gap:9px;}
.logo-box{width:33px;height:33px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--p2));display:flex;align-items:center;justify-content:center;font-size:15px;animation:lGlow 3s ease-in-out infinite;}
@keyframes lGlow{0%,100%{box-shadow:0 0 12px rgba(56,189,248,0.3);}50%{box-shadow:0 0 28px rgba(56,189,248,0.6),0 0 50px rgba(56,189,248,0.15);}}
.logo-txt{font-size:17px;font-weight:800;background:linear-gradient(135deg,var(--accent),var(--p2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.hdr-r{display:flex;align-items:center;gap:7px;}
.badge{padding:4px 10px;border-radius:20px;font-size:10px;font-weight:700;font-family:'Space Mono',monospace;letter-spacing:1px;}
.bf{background:rgba(100,116,139,0.12);border:1px solid rgba(100,116,139,0.2);color:var(--muted);}
.bp{background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.3);color:var(--gold);animation:gGlow 2s ease-in-out infinite;}
@keyframes gGlow{0%,100%{box-shadow:0 0 6px rgba(251,191,36,0.1);}50%{box-shadow:0 0 16px rgba(251,191,36,0.3);}}
.ico-btn{width:29px;height:29px;background:var(--c1);border:1px solid var(--border);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:13px;cursor:pointer;transition:background 0.2s;}
.ico-btn:active{background:var(--c2);}

/* STATS PILLS */
.stats{flex-shrink:0;display:flex;gap:7px;padding:10px 18px;overflow-x:auto;scrollbar-width:none;}
.stats::-webkit-scrollbar{display:none;}
.spill{flex-shrink:0;background:var(--c1);border:1px solid var(--border);border-radius:18px;padding:6px 12px;display:flex;align-items:center;gap:6px;animation:fU 0.5s ease both;}
@keyframes fU{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:translateY(0);}}
.spill:nth-child(1){animation-delay:0.05s;}.spill:nth-child(2){animation-delay:0.1s;}.spill:nth-child(3){animation-delay:0.15s;}.spill:nth-child(4){animation-delay:0.2s;}
.sdot{width:6px;height:6px;border-radius:50%;animation:bl 1.8s ease-in-out infinite;}
@keyframes bl{0%,100%{opacity:1;}50%{opacity:0.25;}}
.snum{font-size:12px;font-weight:800;font-family:'Space Mono',monospace;}
.slbl{font-size:9px;color:var(--muted);}

/* SEARCH + TABS */
.search-area{flex-shrink:0;padding:0 18px 10px;}
.sw{position:relative;margin-bottom:9px;}
.si{position:absolute;left:12px;top:50%;transform:translateY(-50%);font-size:13px;}
.sb{width:100%;background:var(--c1);border:1px solid var(--border);border-radius:11px;padding:10px 12px 10px 34px;color:var(--txt);font-family:'Syne',sans-serif;font-size:13px;outline:none;transition:border-color 0.25s,box-shadow 0.25s;}
.sb::placeholder{color:var(--muted);}
.sb:focus{border-color:rgba(56,189,248,0.35);box-shadow:0 0 0 3px rgba(56,189,248,0.07);}
.tabs{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;}
.tabs::-webkit-scrollbar{display:none;}
.tab{flex-shrink:0;padding:6px 13px;border-radius:14px;border:1px solid var(--border);background:transparent;color:var(--muted);font-family:'Syne',sans-serif;font-size:11px;font-weight:700;cursor:pointer;transition:all 0.22s;}
.tab.active{background:linear-gradient(135deg,var(--accent),var(--p2));border-color:transparent;color:#fff;box-shadow:0 3px 14px rgba(56,189,248,0.28);}

/* SCROLL */
.scroll{flex:1;overflow-y:auto;overflow-x:hidden;padding:10px 18px 95px;scrollbar-width:none;}
.scroll::-webkit-scrollbar{display:none;}

/* SECTION HDR */
.shdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px;margin-top:4px;}
.stitle{font-size:14px;font-weight:700;}
.live-tag{display:flex;align-items:center;gap:5px;font-size:9px;color:var(--p3);font-family:'Space Mono',monospace;background:rgba(52,211,153,0.07);border:1px solid rgba(52,211,153,0.18);padding:3px 9px;border-radius:10px;}
.ldot{width:5px;height:5px;border-radius:50%;background:var(--p3);animation:bl 1.5s ease-in-out infinite;}

/* NFT CARD GRID */
.nft-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:13px;}
.nft-card{background:var(--c1);border:1px solid var(--border);border-radius:18px;overflow:hidden;cursor:pointer;position:relative;
animation:cardIn 0.55s cubic-bezier(0.16,1,0.3,1) both;
transition:transform 0.28s cubic-bezier(0.34,1.56,0.64,1),box-shadow 0.28s,border-color 0.28s;}
.nft-card:nth-child(1){animation-delay:0.28s;}.nft-card:nth-child(2){animation-delay:0.33s;}
.nft-card:nth-child(3){animation-delay:0.38s;}.nft-card:nth-child(4){animation-delay:0.43s;}
.nft-card:nth-child(5){animation-delay:0.48s;}.nft-card:nth-child(6){animation-delay:0.53s;}
@keyframes cardIn{from{opacity:0;transform:translateY(28px) scale(0.94);}to{opacity:1;transform:translateY(0) scale(1);}}
.nft-card:active{transform:scale(0.94) rotate(-0.5deg);}
.nft-card:hover{border-color:rgba(56,189,248,0.22);box-shadow:0 8px 32px rgba(56,189,248,0.08);}

/* NFT ART AREA */
.nft-art{width:100%;height:110px;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;}
.nft-emoji{font-size:52px;display:block;animation:float 4s ease-in-out infinite;filter:drop-shadow(0 8px 20px rgba(0,0,0,0.4));}
@keyframes float{0%,100%{transform:translateY(0) rotate(0deg) scale(1);}25%{transform:translateY(-6px) rotate(1.5deg) scale(1.04);}75%{transform:translateY(-3px) rotate(-1deg) scale(1.02);}}
.nft-card:nth-child(2) .nft-emoji{animation-delay:-1.3s;}
.nft-card:nth-child(3) .nft-emoji{animation-delay:-2.6s;}
.nft-card:nth-child(4) .nft-emoji{animation-delay:-0.7s;}
.nft-card:nth-child(5) .nft-emoji{animation-delay:-1.9s;}
.nft-card:nth-child(6) .nft-emoji{animation-delay:-3.2s;}

/* shimmer sweep on art */
.nft-art::after{content:'';position:absolute;inset:0;background:linear-gradient(105deg,transparent 40%,rgba(255,255,255,0.04) 50%,transparent 60%);animation:sweep 3.5s ease-in-out infinite;}
@keyframes sweep{0%{transform:translateX(-100%);}60%,100%{transform:translateX(200%);}}

/* corner glow */
.nft-glow{position:absolute;width:60px;height:60px;border-radius:50%;filter:blur(20px);opacity:0.35;top:-10px;right:-10px;animation:glowP 3s ease-in-out infinite alternate;}
@keyframes glowP{from{opacity:0.2;transform:scale(0.9);}to{opacity:0.5;transform:scale(1.1);}}

/* rank badge */
.rank-badge{position:absolute;top:8px;left:8px;background:rgba(0,0,0,0.55);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:2px 7px;font-size:9px;font-family:'Space Mono',monospace;font-weight:700;color:rgba(255,255,255,0.7);}

/* platform badge */
.plat-badge{position:absolute;top:8px;right:8px;width:22px;height:22px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:11px;background:rgba(0,0,0,0.5);backdrop-filter:blur(8px);}

/* NFT BODY */
.nft-body{padding:10px;}
.nft-name{font-size:11px;font-weight:700;line-height:1.3;margin-bottom:7px;min-height:28px;word-break:break-word;}
.nft-footer{display:flex;align-items:center;justify-content:space-between;}
.score-track{flex:1;height:3px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;margin-right:7px;}
.score-fill{height:100%;border-radius:3px;width:0%;transition:width 1.1s cubic-bezier(0.16,1,0.3,1);}
.nft-score{font-size:11px;font-weight:800;font-family:'Space Mono',monospace;}
.nft-tag{margin-top:6px;font-size:9px;padding:2px 7px;border-radius:7px;display:inline-block;font-weight:700;}

/* FEATURED BANNER */
.feat{border-radius:20px;overflow:hidden;margin-bottom:13px;position:relative;cursor:pointer;animation:fU 0.45s ease 0.22s both;transition:transform 0.28s cubic-bezier(0.34,1.56,0.64,1);}
.feat:active{transform:scale(0.97);}
.feat-art{width:100%;height:160px;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;}
.feat-emoji{font-size:90px;animation:float 5s ease-in-out infinite;filter:drop-shadow(0 12px 30px rgba(0,0,0,0.5));}
.feat-overlay{position:absolute;inset:0;background:linear-gradient(to top,rgba(6,8,15,0.97) 0%,rgba(6,8,15,0.25) 55%,transparent 100%);}
.feat-content{position:absolute;bottom:0;left:0;right:0;padding:14px 15px;}
.feat-tags{display:flex;gap:5px;margin-bottom:7px;}
.ftag{padding:2px 8px;border-radius:8px;font-size:9px;font-weight:700;font-family:'Space Mono',monospace;}
.ftag-hot{background:rgba(248,113,113,0.18);border:1px solid rgba(248,113,113,0.3);color:var(--red);}
.ftag-plat{background:rgba(56,189,248,0.12);border:1px solid rgba(56,189,248,0.22);color:var(--accent);}
.feat-name{font-size:17px;font-weight:800;margin-bottom:5px;line-height:1.2;}
.feat-meta{display:flex;align-items:center;justify-content:space-between;}
.feat-pred{font-size:11px;color:var(--p3);font-weight:700;font-family:'Space Mono',monospace;}
.feat-cta{font-size:10px;color:rgba(255,255,255,0.4);}

/* AI BARS CARD */
.ai-card{background:linear-gradient(135deg,rgba(56,189,248,0.06),rgba(129,140,248,0.06));border:1px solid rgba(56,189,248,0.12);border-radius:18px;padding:14px;margin-bottom:13px;animation:fU 0.45s ease 0.18s both;}
.ai-hdr{display:flex;align-items:center;gap:8px;margin-bottom:12px;}
.ai-ico{width:30px;height:30px;background:linear-gradient(135deg,var(--accent),var(--p2));border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;animation:lGlow 3s ease-in-out infinite;}
.ai-ttl{font-size:12px;font-weight:700;}
.ai-sub{font-size:9px;color:var(--muted);}
.ai-rows{display:flex;flex-direction:column;gap:8px;}
.ai-row{display:flex;align-items:center;gap:8px;}
.ai-rank{width:16px;font-size:9px;color:var(--muted);font-family:'Space Mono',monospace;text-align:center;flex-shrink:0;}
.ai-name{font-size:10px;font-weight:700;min-width:80px;max-width:80px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0;}
.ai-track{flex:1;height:4px;background:rgba(255,255,255,0.04);border-radius:4px;overflow:hidden;}
.ai-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--accent),var(--p2));width:0%;transition:width 1.3s cubic-bezier(0.16,1,0.3,1);}
.ai-pct{font-size:10px;font-weight:800;font-family:'Space Mono',monospace;color:var(--p3);min-width:28px;text-align:right;flex-shrink:0;}

/* UPGRADE BANNER */
.upg{background:linear-gradient(135deg,rgba(251,191,36,0.09),rgba(129,140,248,0.07));border:1px solid rgba(251,191,36,0.18);border-radius:18px;padding:13px;display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:13px;cursor:pointer;transition:transform 0.25s cubic-bezier(0.34,1.56,0.64,1);animation:fU 0.45s ease 0.5s both;}
.upg:active{transform:scale(0.97);}
.upg-txt h3{font-size:12px;font-weight:700;color:var(--gold);margin-bottom:2px;}
.upg-txt p{font-size:10px;color:var(--muted);}
.upg-btn{flex-shrink:0;background:linear-gradient(135deg,var(--gold),#f59e0b);color:#000;border:none;border-radius:10px;padding:8px 13px;font-family:'Syne',sans-serif;font-size:11px;font-weight:800;cursor:pointer;box-shadow:0 3px 12px rgba(251,191,36,0.28);white-space:nowrap;transition:transform 0.2s;}
.upg-btn:active{transform:scale(0.95);}

/* LOCK OVERLAY */
.lock{position:absolute;inset:0;border-radius:18px;background:rgba(6,8,15,0.72);backdrop-filter:blur(5px);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;}
.lock-e{font-size:20px;animation:lockPulse 2s ease-in-out infinite;}
@keyframes lockPulse{0%,100%{transform:scale(1);}50%{transform:scale(1.12) rotate(-3deg);}}
.lock-l{font-size:9px;color:var(--gold);font-weight:700;font-family:'Space Mono',monospace;letter-spacing:1px;}

/* BOTTOM NAV */
.bnav{position:fixed;bottom:0;left:0;right:0;background:rgba(6,8,15,0.93);backdrop-filter:blur(28px);border-top:1px solid var(--border);display:flex;padding:8px 0 max(8px,env(safe-area-inset-bottom));z-index:100;}
.ni{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;padding:4px 0;transition:all 0.22s;}
.ni-ico{font-size:18px;transition:transform 0.22s;}
.ni-lbl{font-size:9px;color:var(--muted);font-weight:700;transition:color 0.22s;}
.ni.active .ni-lbl{color:var(--accent);}
.ni.active .ni-ico{transform:scale(1.18);filter:drop-shadow(0 0 7px var(--accent));}

/* TOAST */
.toast{position:fixed;top:14px;left:50%;transform:translateX(-50%) translateY(-65px);background:rgba(13,20,37,0.95);border:1px solid var(--border);border-radius:13px;padding:9px 16px;font-size:11px;font-weight:700;z-index:999;transition:transform 0.38s cubic-bezier(0.16,1,0.3,1);white-space:nowrap;max-width:88vw;text-align:center;backdrop-filter:blur(16px);}
.toast.show{transform:translateX(-50%) translateY(0);}

/* LOADING */
.loader{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:55px 20px;gap:13px;}
.spin{width:34px;height:34px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spinA 0.75s linear infinite;}
@keyframes spinA{to{transform:rotate(360deg);}}
.spin-txt{color:var(--muted);font-size:11px;font-family:'Space Mono',monospace;animation:bl 1.5s ease-in-out infinite;}
</style>
</head>
<body>
<div class="bg">
  <div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>
  <div class="grid"></div><div class="grain"></div>
</div>

<div class="app">
  <div class="hdr">
    <div class="logo">
      <div class="logo-box">&#x26A1;</div>
      <span class="logo-txt">TrendAI</span>
    </div>
    <div class="hdr-r">
      <span class="badge bf" id="userBadge">FREE</span>
      <div class="ico-btn">&#x1F514;</div>
    </div>
  </div>

  <div class="stats" id="statsRow">
    <div class="spill"><div class="sdot" style="background:#34d399;"></div><span class="snum" id="sCount">--</span><span class="slbl">trends</span></div>
    <div class="spill"><div class="sdot" style="background:#38bdf8;animation-delay:-0.5s;"></div><span class="snum">94%</span><span class="slbl">accuracy</span></div>
    <div class="spill"><div class="sdot" style="background:#818cf8;animation-delay:-1s;"></div><span class="snum">6</span><span class="slbl">platforms</span></div>
    <div class="spill"><div class="sdot" style="background:#fbbf24;animation-delay:-1.5s;"></div><span class="snum" id="sTime">now</span><span class="slbl">updated</span></div>
  </div>

  <div class="search-area">
    <div class="sw">
      <span class="si">&#x1F50D;</span>
      <input class="sb" id="searchBox" placeholder="Search trends..." autocomplete="off">
    </div>
    <div class="tabs">
      <button class="tab active" data-tab="all">&#x1F30D; All</button>
      <button class="tab" data-tab="products">&#x1F4E6; Products</button>
      <button class="tab" data-tab="content">&#x1F3AC; Content</button>
      <button class="tab" data-tab="search">&#x1F50D; Search</button>
      <button class="tab" data-tab="ai">&#x1F916; AI Picks</button>
    </div>
  </div>

  <div class="scroll" id="mainScroll">
    <div class="loader"><div class="spin"></div><span class="spin-txt">Scanning platforms...</span></div>
  </div>
</div>

<div class="bnav">
  <div class="ni active" onclick="setNav(this,'home')"><span class="ni-ico">&#x1F525;</span><span class="ni-lbl">Trends</span></div>
  <div class="ni" onclick="setNav(this,'predict')"><span class="ni-ico">&#x1F916;</span><span class="ni-lbl">Predict</span></div>
  <div class="ni" onclick="setNav(this,'saved')"><span class="ni-ico">&#x1F516;</span><span class="ni-lbl">Saved</span></div>
  <div class="ni" onclick="setNav(this,'profile')"><span class="ni-ico">&#x1F464;</span><span class="ni-lbl">Profile</span></div>
</div>

<div class="toast" id="toast"></div>

<script>
var tg=window.Telegram&&window.Telegram.WebApp;
if(tg){tg.ready();tg.expand();try{tg.setHeaderColor('#06080f');}catch(e){}}
var userId=tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user?tg.initDataUnsafe.user.id:null;
var isPremium=false,allTrends=[],activeTab='all';

var PM={
  Google:{i:'&#x1F50D;',c:'#4285f4'},Reddit:{i:'&#x1F916;',c:'#ff4500'},
  TikTok:{i:'&#x1F3B5;',c:'#ff0050'},Twitter:{i:'&#x1F426;',c:'#1da1f2'},
  Facebook:{i:'&#x1F465;',c:'#1877f2'},AliExpress:{i:'&#x1F4E6;',c:'#ff6a00'},
  Amazon:{i:'&#x1F6D2;',c:'#ff9900'}
};

var ARTS=['&#x1F680;','&#x1F4A1;','&#x1F525;','&#x26A1;','&#x1F30A;','&#x1F3AF;','&#x1F48E;','&#x1F31F;','&#x1F3AA;','&#x1F98B;','&#x1F308;','&#x1F3AD;','&#x1F3C6;','&#x1F52E;','&#x1F4AB;','&#x1F9E0;','&#x1F31A;','&#x1F9F2;','&#x26A1;','&#x1F4F8;'];

function getArt(name){var h=0;for(var i=0;i<name.length;i++){h=(h<<5)-h+name.charCodeAt(i);}return ARTS[Math.abs(h)%ARTS.length];}
function sColor(s){return s>=90?'#34d399':s>=75?'#38bdf8':s>=60?'#818cf8':'#64748b';}
function mStyle(m){
  if(m.indexOf('Exploding')>-1||m.indexOf('Viral')>-1)return 'background:rgba(248,113,113,0.12);border:1px solid rgba(248,113,113,0.25);color:#f87171;';
  if(m.indexOf('Rising')>-1)return 'background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.2);color:#38bdf8;';
  return 'background:rgba(100,116,139,0.1);border:1px solid rgba(100,116,139,0.2);color:#94a3b8;';
}

function demo(){
  return[
    {name:'AI Video Generators',platform:'Google',score:97,category:'Search',momentum:'&#x1F525; Exploding',ai_prediction:'98% viral in 48h',recommended_action:'Create content NOW'},
    {name:'Wireless Charging Pads',platform:'AliExpress',score:89,category:'Products',momentum:'&#x1F4E6; Hot Seller',ai_prediction:'87% viral in 72h',recommended_action:'Stock up if selling'},
    {name:'Sourdough Bread Kits',platform:'Reddit',score:84,category:'Food',momentum:'&#x1F4C8; Rising',ai_prediction:'76% viral in 5 days',recommended_action:'Write article today'},
    {name:'Stanley Cup Dupes',platform:'TikTok',score:91,category:'Products',momentum:'&#x26A1; Viral',ai_prediction:'93% viral in 24h',recommended_action:'Start ads immediately',locked:true},
    {name:'Minimalist Home Decor',platform:'Facebook',score:78,category:'Lifestyle',momentum:'&#x1F4C8; Rising',ai_prediction:'71% viral in 1 week',recommended_action:'Create content NOW',locked:true},
    {name:'AI Prompt Engineering',platform:'Reddit',score:86,category:'Tech',momentum:'&#x1F525; Exploding',ai_prediction:'89% viral in 36h',recommended_action:'Write article today',locked:true},
  ];
}

async function init(){
  try{var r=await fetch('/api/status?user_id='+userId);var d=await r.json();isPremium=d.is_premium;
    if(isPremium){document.getElementById('userBadge').textContent='PRO';document.getElementById('userBadge').className='badge bp';}}catch(e){}
  try{var r2=await fetch('/api/trends?user_id='+userId);allTrends=await r2.json();}catch(e){allTrends=demo();}
  if(!isPremium){allTrends.forEach(function(t,i){if(i>=3)t.locked=true;});}
  document.getElementById('sCount').textContent=allTrends.length+'+';
  renderAll();
}

function renderAll(){
  var trends=allTrends.slice();
  var q=document.getElementById('searchBox').value.toLowerCase();
  if(activeTab!=='all'&&activeTab!=='ai'){
    trends=trends.filter(function(t){return ((t.category||'').toLowerCase().indexOf(activeTab)>-1)||((t.platform||'').toLowerCase().indexOf(activeTab)>-1);});
  }
  if(q){trends=trends.filter(function(t){return t.name.toLowerCase().indexOf(q)>-1;});}

  var area=document.getElementById('mainScroll');
  var html='';

  if(activeTab==='ai'){
    html+=mkAI(allTrends);
    if(!isPremium)html+=mkUpg();
  } else {
    if(trends.length>0)html+=mkFeat(trends[0]);
    html+=mkAI(allTrends.slice(0,5));
    html+='<div class="shdr"><span class="stitle">Trending Now</span><div class="live-tag"><div class="ldot"></div>LIVE</div></div>';
    html+='<div class="nft-grid">';
    var slice=trends.slice(1,7);
    for(var i=0;i<slice.length;i++){html+=mkNFT(slice[i],i+1);}
    html+='</div>';
    if(!isPremium)html+=mkUpg();
  }

  area.innerHTML=html;

  requestAnimationFrame(function(){
    var fills=area.querySelectorAll('.score-fill,.ai-fill');
    for(var i=0;i<fills.length;i++){
      (function(el){setTimeout(function(){el.style.width=el.dataset.w+'%';},120);})(fills[i]);
    }
  });
}

function mkFeat(t){
  var p=PM[t.platform]||{i:'&#x1F4CA;',c:'#38bdf8'};
  var art=getArt(t.name);
  var c=sColor(t.score);
  return '<div class="feat" onclick="tap(\''+encodeURIComponent(t.name)+'\','+t.score+','+(!!t.locked)+')">'
    +'<div class="feat-art" style="background:linear-gradient(135deg,'+p.c+'1a,'+p.c+'0d);">'
    +'<span class="feat-emoji">'+art+'</span>'
    +'<div class="feat-overlay"></div>'
    +'</div>'
    +'<div class="feat-content">'
    +'<div class="feat-tags"><span class="ftag ftag-hot">&#x1F525; #1 TODAY</span><span class="ftag ftag-plat">'+p.i+' '+t.platform+'</span></div>'
    +'<div class="feat-name">'+t.name+'</div>'
    +'<div class="feat-meta"><span class="feat-pred">&#x1F916; '+(t.ai_prediction||'Analyzing...')+'</span><span class="feat-cta">'+(t.recommended_action||'')+' &rarr;</span></div>'
    +'</div>'
    +'</div>';
}

function mkNFT(t,rank){
  var p=PM[t.platform]||{i:'&#x1F4CA;',c:'#38bdf8'};
  var art=getArt(t.name);
  var c=sColor(t.score);
  var lk=t.locked;
  return '<div class="nft-card" onclick="tap(\''+encodeURIComponent(t.name)+'\','+t.score+','+!!lk+')">'
    +'<div class="nft-art" style="background:linear-gradient(145deg,'+p.c+'15,'+p.c+'07);">'
    +'<div class="nft-glow" style="background:'+p.c+';"></div>'
    +'<span class="nft-emoji">'+art+'</span>'
    +'<div class="rank-badge">#'+rank+'</div>'
    +'<div class="plat-badge">'+p.i+'</div>'
    +'</div>'
    +'<div class="nft-body">'
    +'<div class="nft-name">'+t.name+'</div>'
    +'<div class="nft-footer">'
    +'<div class="score-track"><div class="score-fill" data-w="'+t.score+'" style="background:'+c+';width:0%;"></div></div>'
    +'<span class="nft-score" style="color:'+c+';">'+t.score+'</span>'
    +'</div>'
    +'<span class="nft-tag" style="'+mStyle(t.momentum)+'">'+t.momentum+'</span>'
    +'</div>'
    +(lk?'<div class="lock"><span class="lock-e">&#x1F512;</span><span class="lock-l">PREMIUM</span></div>':'')
    +'</div>';
}

function mkAI(trends){
  var top=trends.slice(0,5);
  var rows=top.map(function(t,i){
    return '<div class="ai-row">'
      +'<span class="ai-rank">'+(i+1)+'</span>'
      +'<span class="ai-name">'+t.name+'</span>'
      +'<div class="ai-track"><div class="ai-fill" data-w="'+t.score+'" style="width:0%;"></div></div>'
      +'<span class="ai-pct">'+t.score+'%</span>'
      +'</div>';
  }).join('');
  return '<div class="ai-card">'
    +'<div class="ai-hdr"><div class="ai-ico">&#x1F916;</div><div><div class="ai-ttl">AI Viral Predictor</div><div class="ai-sub">Next 48h forecast</div></div></div>'
    +'<div class="ai-rows">'+rows+'</div>'
    +'</div>';
}

function mkUpg(){
  return '<div class="upg" onclick="showUpg()">'
    +'<div class="upg-txt"><h3>&#x2B50; Go Premium</h3><p>All trends + AI alerts &middot; $5/mo USDT</p></div>'
    +'<button class="upg-btn">Upgrade</button>'
    +'</div>';
}

function tap(name,score,locked){
  if(locked){showUpg();return;}
  showToast('&#x1F525; '+decodeURIComponent(name)+' -- Score '+score);
}

function showUpg(){
  if(tg&&tg.showPopup){
    tg.showPopup({title:'&#x2B50; Go Premium',message:'Unlock all trends, AI predictions & early alerts for just $5 USDT/month.',buttons:[{id:'up',type:'default',text:'Upgrade Now'},{type:'cancel',text:'Later'}]},function(b){if(b==='up')showToast('Send $5 USDT to activate!');});
  } else {
    showToast('&#x1F4B0; Send $5 USDT to activate Premium!');
  }
}

function setNav(el,page){
  document.querySelectorAll('.ni').forEach(function(n){n.classList.remove('active');});
  el.classList.add('active');
  var msgs={predict:'&#x1F916; AI Predictor -- Premium only',saved:'&#x1F516; No saved trends yet',profile:'&#x1F464; Open bot to view profile'};
  if(msgs[page])showToast(msgs[page]);
}

function showToast(msg){
  var t=document.getElementById('toast');
  t.innerHTML=msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t=setTimeout(function(){t.classList.remove('show');},2800);
}

document.getElementById('searchBox').addEventListener('input',renderAll);
document.querySelectorAll('.tab').forEach(function(tab){
  tab.addEventListener('click',function(){
    document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active');});
    tab.classList.add('active');
    activeTab=tab.dataset.tab;
    renderAll();
  });
});

function tickTime(){
  var n=new Date();
  document.getElementById('sTime').textContent=n.getHours()+':'+(n.getMinutes()<10?'0':'')+n.getMinutes();
}
tickTime();
setInterval(tickTime,60000);
init();
</script>
</body>
</html>"""

@flask_app.route('/')
@flask_app.route('/app')
def serve_app():
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

# ==========================================
# TELEGRAM BOT
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid  = user.id
    webapp_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME','localhost')}/app"
    kb = [
        [InlineKeyboardButton("? Open TrendAI", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton("? Go Premium – $5 USDT", callback_data="premium")],
        [InlineKeyboardButton("? My Status", callback_data="status")],
    ]
    is_prem = uid in premium_users
    await update.message.reply_text(
        f"? Welcome to *TrendAI*, {user.first_name}!\n\n"
        f"? We predict what's trending *before* it goes viral.\n\n"
        f"{'? You are a *Premium* member!' if is_prem else '? Free plan – 3 trends/day'}\n\n"
        f"Tap below to open the app ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def premium_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        f"? *Upgrade to Premium*\n\n"
        f"? Unlimited trend predictions\n"
        f"? All platforms (TikTok, Reddit, Facebook, AliExpress...)\n"
        f"? AI Trend Score + Predictions\n"
        f"? Early viral alerts\n\n"
        f"? *Price: $5 USDT / month (TON)*\n\n"
        f"Send to:\n`{TON_WALLET}`\n\n"
        f"Then send your *tx hash* here for activation.",
        parse_mode="Markdown"
    )

async def status_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.callback_query.from_user.id
    is_prem = uid in premium_users
    exp = premium_expiry.get(uid)
    txt = f"? *Premium Active*\nExpires: {exp.strftime('%Y-%m-%d')}" if (is_prem and exp) else "? *Free Plan* – 3 trends/day"
    await update.callback_query.message.reply_text(f"? *Your Status*\n\n{txt}", parse_mode="Markdown")

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        tid = int(context.args[0])
        premium_users.add(tid)
        premium_expiry[tid] = datetime.now() + timedelta(days=30)
        await update.message.reply_text(f"? User {tid} activated for 30 days!")
        await context.bot.send_message(tid,
            "? *Your Premium is now active for 30 days!*\n\nOpen the app to unlock all trends ?",
            parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"? Error: {e}")

# ==========================================
# MAIN
# ==========================================

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info(f"Flask running on port {PORT}")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CallbackQueryHandler(premium_cb, pattern="premium"))
    app.add_handler(CallbackQueryHandler(status_cb, pattern="status"))

    logger.info("Bot polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
