“””
Twitter Community Bot - Respect | ريسبكت
بوست واحد بحد 270 حرف + صورة Banner تلقائية
“””

import os
import io
import time
import logging
import gc
import threading
import textwrap
from datetime import datetime, timedelta, timezone

import tweepy
import google.generativeai as genai
import schedule
from PIL import Image, ImageDraw, ImageFont
from flask import Flask
from dotenv import load_dotenv

# ──────────────────────────────────────────────

load_dotenv()

TWITTER_BEARER_TOKEN    = os.getenv(“TWITTER_BEARER_TOKEN”)
TWITTER_CONSUMER_KEY    = os.getenv(“TWITTER_CONSUMER_KEY”)
TWITTER_CONSUMER_SECRET = os.getenv(“TWITTER_CONSUMER_SECRET”)
TWITTER_ACCESS_TOKEN    = os.getenv(“TWITTER_ACCESS_TOKEN”)
TWITTER_ACCESS_SECRET   = os.getenv(“TWITTER_ACCESS_SECRET”)
GEMINI_API_KEY          = os.getenv(“GEMINI_API_KEY”)

COMMUNITY_ID      = “1804198664484569261”
MAX_POSTS         = 200
TOP_POSTS_N       = 15
INTERVAL_DAYS     = 4
TWEET_CHAR_LIMIT  = 270   # حد التغريدة الواحدة

# ──────────────────────────────────────────────

logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s | %(levelname)s | %(message)s”,
datefmt=”%Y-%m-%d %H:%M:%S”,
)
log = logging.getLogger(**name**)

# ──────────────────────────────────────────────

# Flask

# ──────────────────────────────────────────────

app = Flask(**name**)

@app.route(”/”)
def health():
return {“status”: “alive”, “bot”: “Respect RP Bot”, “time”: datetime.utcnow().isoformat()}, 200

@app.route(”/ping”)
def ping():
return “pong”, 200

# ──────────────────────────────────────────────

# Twitter Clients

# ──────────────────────────────────────────────

def get_twitter_clients():
read_client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, wait_on_rate_limit=True)

```
write_client = tweepy.Client(
    consumer_key=TWITTER_CONSUMER_KEY,
    consumer_secret=TWITTER_CONSUMER_SECRET,
    access_token=TWITTER_ACCESS_TOKEN,
    access_token_secret=TWITTER_ACCESS_SECRET,
    wait_on_rate_limit=True,
)

# v1 API لرفع الصور
auth = tweepy.OAuth1UserHandler(
    consumer_key=TWITTER_CONSUMER_KEY,
    consumer_secret=TWITTER_CONSUMER_SECRET,
    access_token=TWITTER_ACCESS_TOKEN,
    access_token_secret=TWITTER_ACCESS_SECRET,
)
api_v1 = tweepy.API(auth, wait_on_rate_limit=True)

return read_client, write_client, api_v1
```

def get_gemini_model():
genai.configure(api_key=GEMINI_API_KEY)
return genai.GenerativeModel(“gemini-1.5-flash”)

# ──────────────────────────────────────────────

# جلب البوستات

# ──────────────────────────────────────────────

def fetch_community_posts(read_client):
log.info(“🔍 جاري جلب البوستات…”)
one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
posts = []

```
try:
    query = f"community_id:{COMMUNITY_ID} -is:retweet"
    paginator = tweepy.Paginator(
        read_client.search_recent_tweets,
        query=query,
        tweet_fields=["public_metrics", "created_at", "text"],
        max_results=100,
        start_time=one_week_ago,
    ).flatten(limit=MAX_POSTS)

    for tweet in paginator:
        if tweet.created_at and tweet.created_at >= one_week_ago:
            m = tweet.public_metrics or {}
            posts.append({
                "text":        tweet.text,
                "likes":       m.get("like_count", 0),
                "replies":     m.get("reply_count", 0),
                "retweets":    m.get("retweet_count", 0),
                "impressions": m.get("impression_count", 0),
                "quotes":      m.get("quote_count", 0),
            })

    log.info(f"✅ تم جلب {len(posts)} بوست")
    return posts

except tweepy.TweepyException as e:
    log.error(f"خطأ Twitter API: {e}")
    return []
except Exception as e:
    log.error(f"خطأ: {e}")
    return []
```

# ──────────────────────────────────────────────

# فلترة الأفضل

# ──────────────────────────────────────────────

def filter_top_posts(posts, n=TOP_POSTS_N):
if not posts:
return []
for p in posts:
p[“score”] = (
p[“impressions”] * 1.0 +
p[“likes”]       * 5 +
p[“replies”]     * 3 +
p[“retweets”]    * 4 +
p[“quotes”]      * 2
)
return sorted(posts, key=lambda x: x[“score”], reverse=True)[:n]

# ──────────────────────────────────────────────

# Gemini - توليد تغريدة واحدة

# ──────────────────────────────────────────────

SYSTEM_PROMPT = f”””
أنت عضو قديم في سيرفر “Respect | ريسبكت” للحياة الواقعية على GTA V.
اكتب تغريدة واحدة فقط عن أبرز حدث صار في السيرفر هذا الأسبوع.

القواعد الصارمة:

1. لهجة سعودية/خليجية جيمرية طبيعية 100٪
1. استخدم: “الشغلة”، “الهيت”، “السكواد”، “الكراش”، “الديل”، “الدراما”
1. ابدأ بجملة تشد الانتباه + إيموجي 🔥
1. اختم بـ: #Respect_RP #ريسبكت
1. ⚠️ الحد الأقصى الصارم: {TWEET_CHAR_LIMIT} حرف فقط — لا تتجاوزه أبداً
1. لا threads — تغريدة واحدة كاملة
1. ركّز على حدث واحد بأسلوب مشوّق ومختصر
   “””

def generate_tweet(posts, gemini_model):
if not posts:
return None

```
log.info("🤖 Gemini يكتب التغريدة...")

posts_text = "\n---\n".join([
    f"[#{i+1}] ({p['likes']}❤️ {p['replies']}💬 {p['retweets']}🔁)\n{p['text']}"
    for i, p in enumerate(posts)
])

user_prompt = f"""
```

البوستات الأكثر تفاعلاً في Respect هذا الأسبوع:

{posts_text}

اكتب التغريدة الآن. تذكّر: الحد الأقصى {TWEET_CHAR_LIMIT} حرف بالضبط.
“””

```
try:
    response = gemini_model.generate_content(
        [SYSTEM_PROMPT, user_prompt],
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=200,
            temperature=0.88,
        )
    )
    text = response.text.strip()

    # قطع أي تجاوز بأمان
    if len(text) > TWEET_CHAR_LIMIT:
        cut = text[:TWEET_CHAR_LIMIT]
        last_space = cut.rfind(" ")
        text = (cut[:last_space] if last_space > 0 else cut[:TWEET_CHAR_LIMIT - 3]) + "..."

    log.info(f"✅ التغريدة ({len(text)} حرف): {text[:60]}...")
    return text

except Exception as e:
    log.error(f"خطأ Gemini: {e}")
    return None
finally:
    gc.collect()
```

# ──────────────────────────────────────────────

# توليد صورة Banner

# ──────────────────────────────────────────────

def generate_banner(tweet_text: str) -> bytes | None:
“””
صورة 1200×675 (نسبة 16:9 - مثالية لتويتر)
خلفية داكنة + نص التغريدة + شعار السيرفر
“””
try:
W, H = 1200, 675

```
    # ألوان
    BG      = (8, 8, 18)
    ACCENT  = (190, 25, 40)       # أحمر Respect
    WHITE   = (235, 235, 245)
    GRAY    = (130, 130, 145)
    GLOW    = (40, 10, 15)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # خلفية gradient يدوية (طبقات أفقية)
    for y in range(H):
        ratio = y / H
        r = int(8  + ratio * 12)
        g = int(8  + ratio * 5)
        b = int(18 + ratio * 8)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # شريط علوي
    draw.rectangle([(0, 0), (W, 10)], fill=ACCENT)
    # شريط سفلي
    draw.rectangle([(0, H - 10), (W, H)], fill=ACCENT)
    # شريط جانبي أيسر
    draw.rectangle([(50, 10), (56, H - 10)], fill=ACCENT)

    # توهج خلف النص (مستطيل شبه شفاف)
    draw.rectangle([(70, 70), (W - 70, H - 70)], fill=(15, 8, 12))

    # تحميل الخطوط
    try:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
        font_body_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
        header_font, body_font, small_font = None, None, None
        for fp in font_paths:
            if os.path.exists(fp):
                header_font = ImageFont.truetype(fp, 42)
                break
        for fp in font_body_paths:
            if os.path.exists(fp):
                body_font = ImageFont.truetype(fp, 30)
                small_font = ImageFont.truetype(fp, 22)
                break
        if not header_font:
            header_font = body_font = small_font = ImageFont.load_default()
    except Exception:
        header_font = body_font = small_font = ImageFont.load_default()

    # اسم السيرفر
    draw.text((80, 22), "Respect | ريسبكت", font=header_font, fill=ACCENT)
    draw.text((82, 24), "Respect | ريسبكت", font=header_font, fill=ACCENT)  # glow effect

    # عنوان فرعي
    draw.text((82, 75), "ملخص الأسبوع  •  Weekly Recap", font=small_font, fill=GRAY)

    # خط فاصل
    draw.rectangle([(80, 105), (W - 80, 108)], fill=(60, 20, 25))

    # نص التغريدة - تقطيع ذكي
    wrapped_lines = textwrap.wrap(tweet_text, width=42)
    y_text = 125
    line_height = 42
    for line in wrapped_lines[:8]:  # حد 8 سطور
        draw.text((80, y_text), line, font=body_font, fill=WHITE)
        y_text += line_height

    # التاريخ
    date_str = datetime.now().strftime("%Y/%m/%d")
    draw.text((80, H - 52), f"🕹️  {date_str}  |  #Respect_RP", font=small_font, fill=GRAY)

    # نجوم زخرفية في الزاوية
    for x, y in [(W - 80, 30), (W - 120, 55), (W - 60, 58)]:
        draw.ellipse([(x-3, y-3), (x+3, y+3)], fill=ACCENT)

    # تصدير
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    result = buffer.read()
    log.info(f"🖼️ Banner: {len(result)//1024} KB")
    return result

except Exception as e:
    log.error(f"خطأ توليد الصورة: {e}")
    return None
finally:
    gc.collect()
```

# ──────────────────────────────────────────────

# رفع الصورة

# ──────────────────────────────────────────────

def upload_image(api_v1, img_bytes: bytes) -> str | None:
try:
media = api_v1.media_upload(
filename=“respect_weekly.png”,
file=io.BytesIO(img_bytes),
)
log.info(f”✅ صورة مرفوعة: {media.media_id}”)
return str(media.media_id)
except Exception as e:
log.error(f”فشل رفع الصورة: {e}”)
return None

# ──────────────────────────────────────────────

# نشر التغريدة النهائية

# ──────────────────────────────────────────────

def publish_tweet(tweet_text: str, write_client, api_v1) -> bool:
if not tweet_text:
return False

```
# ضمان الحد النهائي
if len(tweet_text) > TWEET_CHAR_LIMIT:
    tweet_text = tweet_text[:TWEET_CHAR_LIMIT - 3].rsplit(" ", 1)[0] + "..."

log.info(f"📤 نشر تغريدة ({len(tweet_text)} حرف)...")

# توليد الصورة
img_bytes = generate_banner(tweet_text)
media_id  = None
if img_bytes:
    media_id = upload_image(api_v1, img_bytes)
    del img_bytes
    gc.collect()

# النشر
try:
    kwargs = {"text": tweet_text}
    if media_id:
        kwargs["media_ids"] = [media_id]

    resp = write_client.create_tweet(**kwargs)
    tid  = resp.data["id"]
    log.info(f"🎉 نُشرت! https://x.com/i/web/status/{tid}")
    return True

except tweepy.TweepyException as e:
    log.error(f"فشل النشر: {e}")
    return False
except Exception as e:
    log.error(f"خطأ: {e}")
    return False
```

# ──────────────────────────────────────────────

# الدورة الكاملة

# ──────────────────────────────────────────────

def run_cycle():
log.info(”=” * 55)
log.info(“🚀 دورة جديدة بدأت”)
log.info(f”⏰ {datetime.now().strftime(’%Y-%m-%d %H:%M:%S’)}”)
log.info(”=” * 55)

```
try:
    read_client, write_client, api_v1 = get_twitter_clients()
    gemini_model = get_gemini_model()

    posts = fetch_community_posts(read_client)
    if not posts:
        log.warning("⚠️ لا بوستات")
        return

    top = filter_top_posts(posts)
    del posts; gc.collect()

    tweet_text = generate_tweet(top, gemini_model)
    del top, gemini_model; gc.collect()

    if not tweet_text:
        log.warning("⚠️ فشل التوليد")
        return

    publish_tweet(tweet_text, write_client, api_v1)
    del tweet_text, read_client, write_client, api_v1; gc.collect()

except Exception as e:
    log.error(f"❌ {e}")

log.info("✅ الدورة انتهت | القادمة بعد 4 أيام")
```

# ──────────────────────────────────────────────

# Scheduler

# ──────────────────────────────────────────────

def run_scheduler():
log.info(“⚡ أول دورة فورية…”)
run_cycle()

```
schedule.every(INTERVAL_DAYS).days.do(run_cycle)
log.info(f"📅 جدولة: كل {INTERVAL_DAYS} أيام")

while True:
    schedule.run_pending()
    time.sleep(60)
```

# ──────────────────────────────────────────────

# Main

# ──────────────────────────────────────────────

def main():
log.info(“🤖 Respect RP Bot يبدأ…”)

```
missing = [v for v in [
    "TWITTER_BEARER_TOKEN", "TWITTER_CONSUMER_KEY", "TWITTER_CONSUMER_SECRET",
    "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET", "GEMINI_API_KEY"
] if not os.getenv(v)]

if missing:
    log.critical(f"❌ متغيرات مفقودة: {missing}")
    raise SystemExit(1)

threading.Thread(target=run_scheduler, daemon=True, name="BotThread").start()
log.info("✅ Bot thread شغّال")

port = int(os.getenv("PORT", 10000))
app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
```

if **name** == “**main**”:
main()
