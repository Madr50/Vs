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

# --- 1. إعدادات البوت والتحكم ---
BOT_TOKEN = '8345512854:AAGTrsdBKd90oxhBK83ZkFVSR0qh52ZYDto' 
ADMIN_ID = '7825994636' 

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
user_data = {}

# --- 2. إعدادات المتصفح المحسنة لتقليل الضغط ---
def get_chrome_options():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = os.environ.get("CHROME_BIN")
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--window-size=1024,768") # تصغير الشاشة لتقليل الرام
    chrome_options.add_argument("--disable-gpu")
    # تعطيل الصور لتسريع التحميل وتجنب الـ Timeout
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    return chrome_options

# --- 3. دوال مساعدة للإرسال ---
def send_live_shot(driver, chat_id, caption):
    try:
        tmp_name = f"live_{int(time.time())}.png"
        driver.save_screenshot(tmp_name)
        with open(tmp_name, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=caption)
        os.remove(tmp_name)
    except:
        pass

def screenshot_timer_worker(driver, chat_id, stop_event):
    while not stop_event.is_set():
        time.sleep(180) # إرسال صورة كل 3 دقائق بدلاً من 2 لتقليل الضغط
        if stop_event.is_set(): break
        send_live_shot(driver, chat_id, "⏰ تحديث دوري: حالة المتصفح الحالية.")

# --- 4. السيرفر الوهمي (Keep Alive) ---
@app.route('/')
def home(): return "Bot is Active"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- 5. وظيفة السحب (النسخة الصامدة ضد الـ Timeout) ---
def start_scraping_process(chat_id, email, password, target_url):
    driver = None
    stop_event = threading.Event()
    try:
        bot.send_message(chat_id, "⚙️ جاري التشغيل... سأبذل جهدي لتجاوز ضغط السيرفر.")
        driver = webdriver.Chrome(options=get_chrome_options())
        
        # ضبط مهلة التحميل القصوى (3 دقائق)
        driver.set_page_load_timeout(180) 
        
        timer_thread = threading.Thread(target=screenshot_timer_worker, args=(driver, chat_id, stop_event))
        timer_thread.start()

        # الخطوة 1: تسجيل الدخول
        driver.get('https://facebook.com')
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, 'email')))
        driver.find_element(By.ID, 'email').send_keys(email)
        driver.find_element(By.ID, 'pass').send_keys(password)
        driver.find_element(By.NAME, 'login').click()
        
        time.sleep(10)
        send_live_shot(driver, chat_id, "📸 محاولة تسجيل الدخول")

        if "checkpoint" in driver.current_url or "login_attempt" in driver.current_url:
            bot.send_message(chat_id, "❌ فشل الدخول.")
            stop_event.set()
            driver.quit()
            return

        # الخطوة 2: استخراج الـ ID
        driver.get(target_url)
        time.sleep(7)
        page_source = driver.page_source
        TARGET_UID = None
        match = re.search(r'"userID":"(\d+)"', page_source) or re.search(r'id=(\d+)', target_url)
        if match: TARGET_UID = match.group(1)

        if not TARGET_UID:
            bot.send_message(chat_id, "❌ تعذر استخراج الـ ID.")
            stop_event.set()
            driver.quit()
            return

        bot.send_message(chat_id, f"🆔 المعرف: {TARGET_UID}\n⏳ بدأت عملية السحب (A-Z).")

        # الخطوة 3: السحب بالحروف مع نظام حماية من التوقف
        payload = '{"friends:0":"{\\"name\\":\\"users_friends_of_people\\",\\"args\\":\\"%s\\"}"}' % TARGET_UID.strip()
        encoded_payload = base64.b64encode(payload.encode('utf-8')).decode('utf-8')
        friends_list = []

        for i, char_code in enumerate(range(97, 123)):
            char = chr(char_code)
            try:
                # محاولة تحميل الصفحة بحد أقصى دقيقتين للحرف الواحد
                driver.get(f"https://www.facebook.com/search/people/?q={char}&filters={encoded_payload}")
                time.sleep(4)
                
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
                time.sleep(3)
                
                elements = driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com')]")
                for el in elements:
                    href = el.get_attribute('href')
                    if href and 'facebook.com' in href:
                        clean = href.split('?')[0].split('&')[0]
                        if clean not in friends_list: friends_list.append(clean)
                
                if i % 5 == 0: bot.send_message(chat_id, f"✅ فحصت حرف {char}...")
            except Exception as e:
                # إذا حدث Timeout لحرف معين، ننتظر قليلاً ونكمل للحرف الذي يليه
                print(f"Timeout on char {char}: {e}")
                time.sleep(5)
                continue

        stop_event.set()
        if friends_list:
            fname = f"result_{TARGET_UID}.txt"
            with open(fname, 'w') as f:
                for line in set(friends_list): f.write(f"{line}\n")
            with open(fname, 'rb') as doc:
                bot.send_document(chat_id, doc, caption=f"🎉 العدد المستخرج: {len(set(friends_list))}")
            os.remove(fname)
        else:
            bot.send_message(chat_id, "⚠️ لم يتم العثور على نتائج.")

    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ عام: {str(e)}")
    finally:
        stop_event.set()
        if driver: driver.quit()

# --- 6. تسلسل الأوامر ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    if str(message.chat.id) != ADMIN_ID: return
    user_data[message.chat.id] = {}
    m = bot.send_message(message.chat.id, "1️⃣ أرسل الإيميل:")
    bot.register_next_step_handler(m, get_mail)

def get_mail(message):
    user_data[message.chat.id]['email'] = message.text
    m = bot.send_message(message.chat.id, "2️⃣ أرسل الباسورد:")
    bot.register_next_step_handler(m, get_pass)

def get_pass(message):
    user_data[message.chat.id]['password'] = message.text
    m = bot.send_message(message.chat.id, "3️⃣ أرسل رابط حساب الهدف:")
    bot.register_next_step_handler(m, get_target)

def get_target(message):
    cid = message.chat.id
    threading.Thread(target=start_scraping_process, args=(cid, user_data[cid]['email'], user_data[cid]['password'], message.text)).start()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.infinity_polling()
