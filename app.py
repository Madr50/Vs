"""
Twitter Community Bot - Respect RP
Single tweet (max 270 chars) + auto Banner image
"""

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

# دالة لتنظيف المفاتيح من المسافات والعلامات العربية المخفية التي تسبب أعطال
def clean_token(token):
    if not token:
        return ""
    return token.replace('\u200f', '').replace('\u200e', '').strip()

# ========== ضع مفاتيحك هنا مباشرة ==========

TWITTER_BEARER_TOKEN    = clean_token("AAAAAAAAAAAAAAAAAAAAAM427wEAAAAAnl7hYT5DriL%2FDB0wbVqO5qeKL5c%3Dw9q7sytz4F2BHa8bXlBvTIHFNqs4GQot8wmpDKjKRuBTPTJxKw")
TWITTER_CONSUMER_KEY    = clean_token("XouAe27vVWq9ymiaqm36pqWd1")
TWITTER_CONSUMER_SECRET = clean_token("PvC7nOHcITdk7QRglDtJAvsP9SpsnII062WYlfrAH67BoQI96B")

# المفاتيح التي أعطيتني إياها
TWITTER_ACCESS_TOKEN    = clean_token("2025905050636132352-5TeTbFItkXEcLdDaFlvwWeQNDDzBPP")
TWITTER_ACCESS_SECRET   = clean_token("dqysUoQ9pbCCXNVdpyDoZkM2iVIkVIUeGIto1UTt7Qv6g")

GEMINI_API_KEY          = clean_token("AIzaSyBsYZ0zeNY6pMRAuDsz_ulV7HhsNhllVkg")

# ===========================================

COMMUNITY_ID     = "1804198664484569261"
MAX_POSTS        = 200
TOP_POSTS_N      = 15
INTERVAL_DAYS    = 4
TWEET_CHAR_LIMIT = 270

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

@app.route("/")
def health():
    return {"status": "alive", "bot": "Respect RP Bot", "time": datetime.utcnow().isoformat()}, 200

@app.route("/ping")
def ping():
    return "pong", 200

def get_twitter_clients():
    read_client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, wait_on_rate_limit=True)
    write_client = tweepy.Client(
        consumer_key=TWITTER_CONSUMER_KEY,
        consumer_secret=TWITTER_CONSUMER_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_SECRET,
        wait_on_rate_limit=True,
    )
    auth = tweepy.OAuth1UserHandler(
        consumer_key=TWITTER_CONSUMER_KEY,
        consumer_secret=TWITTER_CONSUMER_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_SECRET,
    )
    api_v1 = tweepy.API(auth, wait_on_rate_limit=True)
    return read_client, write_client, api_v1

def get_gemini_model():
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel("gemini-1.5-flash")

def fetch_community_posts(read_client):
    log.info("Fetching community posts...")
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    posts = []
    try:
        query = "community_id:" + COMMUNITY_ID + " -is:retweet"
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
        log.info("Fetched %d posts", len(posts))
        return posts
    except tweepy.TweepyException as e:
        log.error("Twitter API error: %s", e)
        return []
    except Exception as e:
        log.error("Unexpected error: %s", e)
        return []

def filter_top_posts(posts, n=TOP_POSTS_N):
    if not posts:
        return []
    for p in posts:
        p["score"] = (
            p["impressions"] * 1.0
            + p["likes"]    * 5
            + p["replies"]  * 3
            + p["retweets"] * 4
            + p["quotes"]   * 2
        )
    return sorted(posts, key=lambda x: x["score"], reverse=True)[:n]

GEMINI_PROMPT = (
    "anta 3odw fi server Respect GTA V RP.\n"
    "Ekteb tweet wa7ed bas 3an aham 7adath hal osboa3.\n"
    "Al-qawa3ed al-sareema:\n"
    "1. Lahja saudi/khaleji gameriya tabi3iya\n"
    "2. Estkhdm: al-shoghlah, al-hit, al-skwad, al-krrash, al-deal, al-drama\n"
    "3. Ebda bi jomla tashod al-entibah + emoji\n"
    "4. Akhtim bi: #Respect_RP #ريسبكت\n"
    "5. AL-7AD AL-AQSA AL-SAREM: 270 7arf faqat - LA titajaawaz\n"
    "6. Tweet wa7ed kamil faqat bila taqseem\n"
)

def generate_tweet(posts, gemini_model):
    if not posts:
        return None
    log.info("Gemini generating tweet...")

    posts_text_parts = []
    for i, p in enumerate(posts):
        part = (
            "[#" + str(i + 1) + "] "
            + "(" + str(p["likes"]) + " like | "
            + str(p["replies"]) + " reply | "
            + str(p["retweets"]) + " rt)\n"
            + p["text"]
        )
        posts_text_parts.append(part)
    posts_text = "\n---\n".join(posts_text_parts)

    user_prompt = (
        "Top posts from Respect this week:\n\n"
        + posts_text
        + "\n\nEkteb al-tweet al-aan. Max 270 chars."
    )

    full_prompt = GEMINI_PROMPT + "\n\n" + user_prompt

    try:
        response = gemini_model.generate_content(
            full_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=200,
                temperature=0.88,
            ),
        )
        text = response.text.strip()
        if len(text) > TWEET_CHAR_LIMIT:
            cut = text[:TWEET_CHAR_LIMIT]
            last_space = cut.rfind(" ")
            text = (cut[:last_space] if last_space > 0 else cut[:TWEET_CHAR_LIMIT - 3]) + "..."
        log.info("Tweet generated (%d chars)", len(text))
        return text
    except Exception as e:
        log.error("Gemini error: %s", e)
        return None
    finally:
        gc.collect()

def generate_banner(tweet_text):
    try:
        W, H   = 1200, 675
        BG     = (8, 8, 18)
        ACCENT = (190, 25, 40)
        WHITE  = (235, 235, 245)
        GRAY   = (130, 130, 145)

        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        for y in range(H):
            ratio = y / H
            r = int(8  + ratio * 12)
            g = int(8  + ratio * 5)
            b = int(18 + ratio * 8)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        draw.rectangle([(0, 0), (W, 10)],       fill=ACCENT)
        draw.rectangle([(0, H - 10), (W, H)],   fill=ACCENT)
        draw.rectangle([(50, 10), (56, H - 10)], fill=ACCENT)
        draw.rectangle([(70, 70), (W - 70, H - 70)], fill=(15, 8, 12))

        font_bold = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        font_reg = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]

        header_font = None
        body_font   = None
        small_font  = None

        for fp in font_bold:
            if os.path.exists(fp):
                header_font = ImageFont.truetype(fp, 42)
                break
        for fp in font_reg:
            if os.path.exists(fp):
                body_font  = ImageFont.truetype(fp, 30)
                small_font = ImageFont.truetype(fp, 22)
                break

        if not header_font:
            header_font = ImageFont.load_default()
        if not body_font:
            body_font = ImageFont.load_default()
        if not small_font:
            small_font = ImageFont.load_default()

        draw.text((80, 22), "Respect | ريسبكت", font=header_font, fill=ACCENT)
        draw.text((80, 75), "Weekly Recap", font=small_font, fill=GRAY)
        draw.rectangle([(80, 105), (W - 80, 108)], fill=(60, 20, 25))

        wrapped_lines = textwrap.wrap(tweet_text, width=42)
        y_text = 125
        for line in wrapped_lines[:8]:
            draw.text((80, y_text), line, font=body_font, fill=WHITE)
            y_text += 42

        date_str = datetime.now().strftime("%Y/%m/%d")
        draw.text((80, H - 52), date_str + "  |  #Respect_RP", font=small_font, fill=GRAY)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)
        result = buffer.read()
        log.info("Banner: %d KB", len(result) // 1024)
        return result
    except Exception as e:
        log.error("Banner error: %s", e)
        return None
    finally:
        gc.collect()

def upload_image(api_v1, img_bytes):
    try:
        media = api_v1.media_upload(
            filename="respect_weekly.png",
            file=io.BytesIO(img_bytes),
        )
        log.info("Image uploaded: %s", media.media_id)
        return str(media.media_id)
    except Exception as e:
        log.error("Upload failed: %s", e)
        return None

def publish_tweet(tweet_text, write_client, api_v1):
    if not tweet_text:
        return False

    if len(tweet_text) > TWEET_CHAR_LIMIT:
        cut = tweet_text[:TWEET_CHAR_LIMIT - 3]
        last_space = cut.rfind(" ")
        tweet_text = (cut[:last_space] if last_space > 0 else cut) + "..."

    log.info("Publishing tweet (%d chars)...", len(tweet_text))

    img_bytes = generate_banner(tweet_text)
    media_id  = None
    if img_bytes:
        media_id = upload_image(api_v1, img_bytes)
        del img_bytes
        gc.collect()

    try:
        kwargs = {"text": tweet_text}
        if media_id:
            kwargs["media_ids"] = [media_id]
        resp = write_client.create_tweet(**kwargs)
        tid  = resp.data["id"]
        log.info("Published! https://x.com/i/web/status/%s", tid)
        return True
    except tweepy.TweepyException as e:
        log.error("Publish failed: %s", e)
        return False
    except Exception as e:
        log.error("Error: %s", e)
        return False

def run_cycle():
    log.info("=" * 55)
    log.info("New cycle started - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 55)
    try:
        read_client, write_client, api_v1 = get_twitter_clients()
        gemini_model = get_gemini_model()

        posts = fetch_community_posts(read_client)
        if not posts:
            log.warning("No posts found")
            return

        top = filter_top_posts(posts)
        del posts
        gc.collect()

        tweet_text = generate_tweet(top, gemini_model)
        del top, gemini_model
        gc.collect()

        if not tweet_text:
            log.warning("Tweet generation failed")
            return

        publish_tweet(tweet_text, write_client, api_v1)
        del tweet_text, read_client, write_client, api_v1
        gc.collect()

    except Exception as e:
        log.error("Cycle error: %s", e)

    log.info("Cycle done | Next in %d days", INTERVAL_DAYS)

def run_scheduler():
    log.info("Running first cycle immediately...")
    run_cycle()
    schedule.every(INTERVAL_DAYS).days.do(run_cycle)
    log.info("Scheduled every %d days", INTERVAL_DAYS)
    while True:
        schedule.run_pending()
        time.sleep(60)

def main():
    log.info("Respect RP Bot starting...")
    
    # تم إزالة شرط التحقق من متغيرات البيئة لأننا وضعنا المفاتيح يدوياً في الأعلى
    
    threading.Thread(target=run_scheduler, daemon=True, name="BotThread").start()
    log.info("Bot thread started")

    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
