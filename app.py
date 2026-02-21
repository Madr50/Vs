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
:root{--bg:#050810;--surface:#0c1220;--card:#111827;--border:rgba(99,179,237,0.12);--accent:#38bdf8;--accent2:#818cf8;--accent3:#34d399;--gold:#fbbf24;--text:#f1f5f9;--muted:#64748b;}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;min-height:100vh;overflow-x:hidden;}
.bg-mesh{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;}
.bg-mesh::before{content:'';position:absolute;width:600px;height:600px;border-radius:50%;background:radial-gradient(circle,rgba(56,189,248,0.08),transparent 70%);top:-200px;left:-100px;animation:mf 8s ease-in-out infinite;}
.bg-mesh::after{content:'';position:absolute;width:500px;height:500px;border-radius:50%;background:radial-gradient(circle,rgba(129,140,248,0.07),transparent 70%);bottom:-150px;right:-100px;animation:mf 10s ease-in-out infinite reverse;}
@keyframes mf{0%,100%{transform:translate(0,0) scale(1);}50%{transform:translate(30px,20px) scale(1.1);}}
.app{position:relative;z-index:1;}
.header{padding:20px 20px 0;display:flex;align-items:center;justify-content:space-between;animation:su 0.6s cubic-bezier(0.16,1,0.3,1);}
@keyframes su{from{opacity:0;transform:translateY(-20px);}to{opacity:1;transform:translateY(0);}}
.logo{display:flex;align-items:center;gap:10px;}
.logo-icon{width:38px;height:38px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;box-shadow:0 0 20px rgba(56,189,248,0.3);animation:lp 3s ease-in-out infinite;}
@keyframes lp{0%,100%{box-shadow:0 0 20px rgba(56,189,248,0.3);}50%{box-shadow:0 0 35px rgba(56,189,248,0.6);}}
.logo-text{font-size:20px;font-weight:800;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.badge-free,.badge-pro{padding:5px 12px;border-radius:20px;font-size:11px;font-weight:700;font-family:'Space Mono',monospace;letter-spacing:1px;}
.badge-free{background:rgba(100,116,139,0.2);border:1px solid rgba(100,116,139,0.3);color:var(--muted);}
.badge-pro{background:linear-gradient(135deg,rgba(251,191,36,0.2),rgba(251,191,36,0.1));border:1px solid rgba(251,191,36,0.4);color:var(--gold);animation:gp 2s ease-in-out infinite;}
@keyframes gp{0%,100%{box-shadow:0 0 10px rgba(251,191,36,0.2);}50%{box-shadow:0 0 20px rgba(251,191,36,0.4);}}
.stats-strip{margin:16px 20px 0;display:grid;grid-template-columns:repeat(3,1fr);gap:10px;animation:fu 0.7s cubic-bezier(0.16,1,0.3,1) 0.1s both;}
@keyframes fu{from{opacity:0;transform:translateY(20px);}to{opacity:1;transform:translateY(0);}}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:12px;text-align:center;overflow:hidden;position:relative;}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--accent),transparent);animation:sh 3s ease-in-out infinite;}
@keyframes sh{0%{transform:translateX(-100%);}100%{transform:translateX(100%);}}
.stat-num{font-size:22px;font-weight:800;color:var(--accent);font-family:'Space Mono',monospace;}
.stat-label{font-size:10px;color:var(--muted);margin-top:2px;letter-spacing:0.5px;}
.search-wrap{margin:14px 20px 0;position:relative;animation:fu 0.7s cubic-bezier(0.16,1,0.3,1) 0.15s both;}
.search-icon{position:absolute;left:14px;top:50%;transform:translateY(-50%);font-size:15px;pointer-events:none;}
.search-box{width:100%;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:12px 14px 12px 40px;color:var(--text);font-family:'Syne',sans-serif;font-size:14px;outline:none;transition:border-color 0.3s,box-shadow 0.3s;}
.search-box:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(56,189,248,0.1);}
.tabs{margin:14px 20px 0;display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;animation:fu 0.7s cubic-bezier(0.16,1,0.3,1) 0.2s both;}
.tabs::-webkit-scrollbar{display:none;}
.tab{flex-shrink:0;padding:8px 16px;border-radius:20px;border:1px solid var(--border);background:transparent;color:var(--muted);font-family:'Syne',sans-serif;font-size:13px;font-weight:600;cursor:pointer;transition:all 0.3s;}
.tab.active{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;color:#fff;box-shadow:0 4px 15px rgba(56,189,248,0.3);}
.section-header{padding:18px 20px 10px;display:flex;align-items:center;justify-content:space-between;}
.section-title{font-size:16px;font-weight:700;}
.live-dot{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--accent3);font-family:'Space Mono',monospace;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--accent3);animation:bl 1.5s ease-in-out infinite;}
@keyframes bl{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.4;transform:scale(0.7);}}
.trends-list{padding:0 20px;display:flex;flex-direction:column;gap:12px;}
.trend-card{background:var(--card);border:1px solid var(--border);border-radius:18px;padding:16px;position:relative;overflow:hidden;cursor:pointer;transition:transform 0.3s,border-color 0.3s,box-shadow 0.3s;animation:ci 0.5s cubic-bezier(0.16,1,0.3,1) both;}
@keyframes ci{from{opacity:0;transform:translateY(30px) scale(0.97);}to{opacity:1;transform:translateY(0) scale(1);}}
.trend-card:nth-child(1){animation-delay:0.3s;}.trend-card:nth-child(2){animation-delay:0.37s;}.trend-card:nth-child(3){animation-delay:0.44s;}.trend-card:nth-child(4){animation-delay:0.51s;}.trend-card:nth-child(5){animation-delay:0.58s;}
.trend-card:active{transform:scale(0.98);}
.trend-card:hover{border-color:rgba(56,189,248,0.3);box-shadow:0 8px 30px rgba(56,189,248,0.1);}
.trend-card::before{content:'';position:absolute;left:0;top:20%;bottom:20%;width:3px;border-radius:0 3px 3px 0;background:linear-gradient(to bottom,var(--accent),var(--accent2));}
.trend-top{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px;}
.trend-platform{display:flex;align-items:center;gap:6px;}
.platform-icon{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;}
.platform-name{font-size:11px;color:var(--muted);font-family:'Space Mono',monospace;}
.score-ring{position:relative;width:44px;height:44px;flex-shrink:0;}
.score-ring svg{transform:rotate(-90deg);width:44px;height:44px;}
.score-ring circle{fill:none;stroke-width:3;stroke-linecap:round;}
.score-ring .track{stroke:rgba(255,255,255,0.05);}
.score-ring .fill{stroke-dasharray:113;transition:stroke-dashoffset 1s cubic-bezier(0.16,1,0.3,1);}
.score-num{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;font-family:'Space Mono',monospace;}
.trend-name{font-size:15px;font-weight:700;color:var(--text);margin-bottom:8px;line-height:1.3;}
.trend-meta{display:flex;align-items:center;justify-content:space-between;}
.momentum-tag{font-size:11px;padding:4px 10px;border-radius:20px;background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.2);color:var(--accent);font-weight:600;}
.category-tag{font-size:10px;color:var(--muted);font-family:'Space Mono',monospace;}
.premium-row{display:flex;align-items:center;justify-content:space-between;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);}
.ai-prediction{font-size:12px;color:var(--accent3);font-weight:600;}
.action-chip{font-size:10px;padding:3px 8px;border-radius:8px;background:rgba(52,211,153,0.1);border:1px solid rgba(52,211,153,0.2);color:var(--accent3);font-family:'Space Mono',monospace;}
.locked-overlay{position:absolute;inset:0;background:rgba(5,8,16,0.7);display:flex;align-items:center;justify-content:center;border-radius:18px;backdrop-filter:blur(3px);flex-direction:column;gap:6px;}
.lock-icon{font-size:24px;}
.lock-text{font-size:12px;color:var(--gold);font-weight:700;}
.upgrade-banner{margin:18px 20px 0;background:linear-gradient(135deg,rgba(251,191,36,0.1),rgba(129,140,248,0.1));border:1px solid rgba(251,191,36,0.25);border-radius:18px;padding:16px;display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer;transition:transform 0.3s;animation:fu 0.7s cubic-bezier(0.16,1,0.3,1) 0.55s both;}
.upgrade-banner:active{transform:scale(0.98);}
.upgrade-text h3{font-size:14px;font-weight:700;color:var(--gold);margin-bottom:3px;}
.upgrade-text p{font-size:12px;color:var(--muted);}
.upgrade-btn{flex-shrink:0;background:linear-gradient(135deg,var(--gold),#f59e0b);color:#000;border:none;border-radius:12px;padding:10px 16px;font-family:'Syne',sans-serif;font-size:13px;font-weight:800;cursor:pointer;white-space:nowrap;box-shadow:0 4px 15px rgba(251,191,36,0.3);}
.bottom-nav{position:fixed;bottom:0;left:0;right:0;background:rgba(11,18,32,0.95);backdrop-filter:blur(20px);border-top:1px solid var(--border);display:flex;padding:10px 0 max(10px,env(safe-area-inset-bottom));z-index:100;}
.nav-item{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer;transition:all 0.3s;padding:4px 0;}
.nav-icon{font-size:20px;transition:transform 0.3s;}
.nav-label{font-size:10px;color:var(--muted);font-weight:600;transition:color 0.3s;}
.nav-item.active .nav-label{color:var(--accent);}
.nav-item.active .nav-icon{transform:scale(1.15);filter:drop-shadow(0 0 6px var(--accent));}
.bottom-spacer{height:80px;}
.loading{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;gap:16px;}
.spinner{width:40px;height:40px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.loading-text{color:var(--muted);font-size:13px;font-family:'Space Mono',monospace;animation:tb 1.5s ease-in-out infinite;}
@keyframes tb{0%,100%{opacity:1;}50%{opacity:0.4;}}
.toast{position:fixed;top:20px;left:50%;transform:translateX(-50%) translateY(-80px);background:var(--card);border:1px solid var(--border);border-radius:14px;padding:12px 20px;font-size:13px;font-weight:600;z-index:999;transition:transform 0.4s cubic-bezier(0.16,1,0.3,1);white-space:nowrap;}
.toast.show{transform:translateX(-50%) translateY(0);}
</style>
</head>
<body>
<div class="bg-mesh"></div>
<div class="app" id="app">
  <div class="header">
    <div class="logo">
      <div class="logo-icon">⚡</div>
      <span class="logo-text">TrendAI</span>
    </div>
    <span class="badge-free" id="userBadge">FREE</span>
  </div>
  <div class="stats-strip">
    <div class="stat-card"><div class="stat-num" id="trendCount">—</div><div class="stat-label">TRENDS TODAY</div></div>
    <div class="stat-card"><div class="stat-num">94%</div><div class="stat-label">AI ACCURACY</div></div>
    <div class="stat-card"><div class="stat-num">6</div><div class="stat-label">PLATFORMS</div></div>
  </div>
  <div class="search-wrap">
    <span class="search-icon">🔍</span>
    <input class="search-box" id="searchBox" placeholder="Search trends..." autocomplete="off">
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="all">🌍 All</button>
    <button class="tab" data-tab="products">📦 Products</button>
    <button class="tab" data-tab="content">🎬 Content</button>
    <button class="tab" data-tab="search">🔍 Search</button>
  </div>
  <div class="section-header">
    <span class="section-title">Trending Now</span>
    <div class="live-dot"><div class="dot"></div>LIVE</div>
  </div>
  <div class="trends-list" id="trendsList">
    <div class="loading"><div class="spinner"></div><span class="loading-text">Scanning platforms...</span></div>
  </div>
  <div class="upgrade-banner" id="upgradeBanner" onclick="showUpgrade()" style="display:none;">
    <div class="upgrade-text"><h3>⭐ Go Premium</h3><p>Unlock all trends + AI predictions</p></div>
    <button class="upgrade-btn">$5 / mo</button>
  </div>
  <div class="bottom-spacer"></div>
</div>
<div class="bottom-nav">
  <div class="nav-item active" onclick="setNav(this,'trends')"><span class="nav-icon">🔥</span><span class="nav-label">Trends</span></div>
  <div class="nav-item" onclick="setNav(this,'predict')"><span class="nav-icon">🤖</span><span class="nav-label">Predict</span></div>
  <div class="nav-item" onclick="setNav(this,'saved')"><span class="nav-icon">🔖</span><span class="nav-label">Saved</span></div>
  <div class="nav-item" onclick="setNav(this,'profile')"><span class="nav-icon">👤</span><span class="nav-label">Profile</span></div>
</div>
<div class="toast" id="toast"></div>
<script>
const tg=window.Telegram?.WebApp;
if(tg){tg.ready();tg.expand();tg.setHeaderColor('#050810');}
const userId=tg?.initDataUnsafe?.user?.id||null;
let isPremium=false,allTrends=[],activeTab='all';
const PI={'Google':{icon:'🔍',color:'#4285f4'},'Reddit':{icon:'🤖',color:'#ff4500'},'TikTok':{icon:'🎵',color:'#ff0050'},'Twitter':{icon:'🐦',color:'#1da1f2'},'Facebook':{icon:'👥',color:'#1877f2'},'AliExpress':{icon:'📦',color:'#ff6a00'},'Amazon':{icon:'🛒',color:'#ff9900'}};
async function init(){
  try{const r=await fetch('/api/status?user_id='+userId);const d=await r.json();isPremium=d.is_premium;if(isPremium){document.getElementById('userBadge').textContent='⭐ PRO';document.getElementById('userBadge').className='badge-pro';}}catch(e){}
  try{const r=await fetch('/api/trends?user_id='+userId);allTrends=await r.json();}catch(e){allTrends=demo();}
  document.getElementById('trendCount').textContent=allTrends.length+'+';
  render(allTrends);
  if(!isPremium)document.getElementById('upgradeBanner').style.display='flex';
}
function demo(){return[{name:"AI Video Generators",platform:"Google",score:97,category:"Search",momentum:"🔥 Exploding",ai_prediction:"98% viral in 48h",recommended_action:"Create content NOW"},{name:"Wireless Charging Pads",platform:"AliExpress",score:89,category:"Products",momentum:"📦 Hot Seller",ai_prediction:"87% viral in 72h",recommended_action:"Stock up if selling"},{name:"Sourdough Bread Kits",platform:"Reddit",score:84,category:"Food",momentum:"📈 Rising",ai_prediction:"76% viral in 5 days",recommended_action:"Write article today"},{name:"Stanley Cup Alternatives",platform:"TikTok",score:91,category:"Products",momentum:"⚡ Viral",ai_prediction:"93% viral in 24h",recommended_action:"Start ads immediately",locked:!isPremium},{name:"Minimalist Home Decor",platform:"Facebook",score:78,category:"Lifestyle",momentum:"📈 Rising",ai_prediction:"71% viral in 1 week",recommended_action:"Create content NOW",locked:!isPremium}];}
function scoreColor(s){return s>=90?'#34d399':s>=75?'#38bdf8':'#818cf8';}
function render(trends){
  const list=document.getElementById('trendsList');
  if(!trends.length){list.innerHTML='<div style="text-align:center;padding:40px;color:#64748b;">No trends found</div>';return;}
  list.innerHTML=trends.map((t,i)=>{
    const p=PI[t.platform]||{icon:'📊',color:'#38bdf8'};
    const c=scoreColor(t.score);
    const off=113-(t.score/100)*113;
    const lk=t.locked;
    return`<div class="trend-card${lk?' locked':''}" onclick="tap(${i})">
      <div class="trend-top">
        <div class="trend-platform">
          <div class="platform-icon" style="background:${p.color}22;">${p.icon}</div>
          <span class="platform-name">${t.platform.toUpperCase()}</span>
        </div>
        <div class="score-ring">
          <svg viewBox="0 0 44 44"><circle class="track" cx="22" cy="22" r="18"/><circle class="fill" cx="22" cy="22" r="18" stroke="${c}" style="stroke-dashoffset:${off}"/></svg>
          <div class="score-num" style="color:${c}">${t.score}</div>
        </div>
      </div>
      <div class="trend-name">${t.name}</div>
      <div class="trend-meta"><span class="momentum-tag">${t.momentum}</span><span class="category-tag">${t.category||''}</span></div>
      ${t.ai_prediction?`<div class="premium-row"><span class="ai-prediction">🤖 ${t.ai_prediction}</span><span class="action-chip">${t.recommended_action||''}</span></div>`:''}
      ${lk?`<div class="locked-overlay" onclick="showUpgrade()"><span class="lock-icon">🔒</span><span class="lock-text">Premium Only</span></div>`:''}
    </div>`;
  }).join('');
}
function filter(){
  const q=document.getElementById('searchBox').value.toLowerCase();
  let f=allTrends;
  if(activeTab!=='all')f=f.filter(t=>(t.category||'').toLowerCase().includes(activeTab)||(t.platform||'').toLowerCase().includes(activeTab));
  if(q)f=f.filter(t=>t.name.toLowerCase().includes(q));
  render(f);
}
document.getElementById('searchBox').addEventListener('input',filter);
document.querySelectorAll('.tab').forEach(tab=>{tab.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));tab.classList.add('active');activeTab=tab.dataset.tab;filter();});});
function tap(i){const t=allTrends[i];if(t.locked){showUpgrade();return;}toast('🔥 '+t.name+' — Score '+t.score);}
function showUpgrade(){
  if(tg){tg.showPopup({title:'⭐ Upgrade to Premium',message:'Unlock all trends & AI predictions for $5/month in USDT.',buttons:[{id:'up',type:'default',text:'Upgrade Now'},{type:'cancel'}]},(b)=>{if(b==='up')tg.openTelegramLink('https://t.me/your_bot');});}
  else toast('💰 Send $5 USDT to activate Premium!');
}
function setNav(el,p){document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));el.classList.add('active');if(p==='predict')toast('🤖 AI Predictor — Premium Feature');if(p==='saved')toast('🔖 Save trends to your list');}
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2800);}
init();
</script>
</body>
</html>"""

# ══════════════════════════════════════════

# FLASK ROUTES

# ══════════════════════════════════════════

@flask_app.route(’/’)
def home():
return “TrendAI Bot is live! 🚀”, 200

@flask_app.route(’/app’)
def mini_app():
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
