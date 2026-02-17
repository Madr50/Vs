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

# --- 1. إعدادات البوت ---
BOT_TOKEN = '8345512854:AAGTrsdBKd90oxhBK83ZkFVSR0qh52ZYDto' 
ADMIN_ID = '7825994636' 

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
user_data = {}

# --- 2. إعدادات الكروم ---
def get_chrome_options():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = os.environ.get("CHROME_BIN")
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--window-size=1366,768")
    return chrome_options

# --- 3. السيرفر الوهمي ---
@app.route('/')
def home():
    return "Bot is running..."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- 4. وظيفة السحب (نفس الوظيفة السابقة) ---
def start_scraping_process(chat_id, email, password, target_url):
    driver = None
    try:
        bot.send_message(chat_id, "⚙️ جاري تشغيل المتصفح...")
        driver = webdriver.Chrome(options=get_chrome_options())
        
        driver.get('https://facebook.com')
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'email')))
        
        driver.find_element(By.ID, 'email').send_keys(email)
        driver.find_element(By.ID, 'pass').send_keys(password)
        driver.find_element(By.NAME, 'login').click()
        
        bot.send_message(chat_id, "جاري التحقق من الدخول...")
        time.sleep(5)

        # التحقق من الدخول
        if "login_attempt" in driver.current_url or "checkpoint" in driver.current_url:
             bot.send_message(chat_id, "❌ فشل الدخول. تأكد من صحة البيانات.")
             driver.quit()
             return

        bot.send_message(chat_id, "✅ تم الدخول! جاري الذهاب للهدف...")
        driver.get(target_url)
        time.sleep(5)

        # استخراج المعرف
        TARGET_UID = None
        try:
            links = driver.find_elements(By.TAG_NAME, 'a')
            for link in links:
                href = str(link.get_attribute('href'))
                if 'friendship' in href or 'pb_friends_tl' in href:
                    match = re.search(r'/(\d+)/', href)
                    if not match: match = re.search(r'id=(\d+)', href)
                    if match:
                        TARGET_UID = match.group(1)
                        break
            
            if not TARGET_UID:
                # محاولة احتياطية من الكود المصدري
                match = re.search(r'"userID":"(\d+)"', driver.page_source)
                if match: TARGET_UID = match.group(1)

        except Exception as e:
            print(f"Error finding UID: {e}")

        if not TARGET_UID:
            bot.send_message(chat_id, "⚠️ لم أستطع استخراج المعرف (ID). سأحاول الاستمرار...")
            match = re.search(r'id=(\d+)', target_url)
            if match: TARGET_UID = match.group(1)
            else:
                bot.send_message(chat_id, "❌ فشلت العملية: لا يوجد ID.")
                driver.quit()
                return

        bot.send_message(chat_id, f"🆔 ID: {TARGET_UID}. جاري السحب...")

        payload = '{"friends:0":"{\\"name\\":\\"users_friends_of_people\\",\\"args\\":\\"%s\\"}"}' % TARGET_UID.strip()
        encoded_payload = base64.b64encode(payload.encode('utf-8')).decode('utf-8')

        friends = []
        def check_new(last): return len(driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com')]")) > last

        for i, code in enumerate(range(97, 123)):
            driver.get(f"https://www.facebook.com/search/people/?q={chr(code)}&filters={encoded_payload}")
            last = 0
            for _ in range(3):
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
                time.sleep(2)
                if check_new(last): 
                    last = len(driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com')]"))
                else: break
            
            elements = driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com')]")
            for el in elements:
                try:
                    href = el.get_attribute('href')
                    if 'facebook.com' in href and 'sk=friends' not in href and 'login' not in href:
                         friends.append(href.replace('?__tn__=%3C', '').replace('&__tn__=%3C', ''))
                except: pass
            
            if i % 5 == 0: bot.send_message(chat_id, f"تم {chr(code)}...")

        unique = list(set(friends))
        if not unique:
            bot.send_message(chat_id, "⚠️ لم يتم العثور على أصدقاء.")
        else:
            with open(f"{TARGET_UID}.txt", 'w') as f:
                for line in unique: f.write(f"{line}\n")
            with open(f"{TARGET_UID}.txt", 'rb') as f:
                bot.send_document(chat_id, f, caption=f"تم! العدد: {len(unique)}")
            os.remove(f"{TARGET_UID}.txt")

    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ: {e}")
    finally:
        if driver: driver.quit()

# --- 5. خطوات المحادثة (هنا كان الخطأ وتم إصلاحه) ---

@bot.message_handler(commands=['start'])
def step_1_welcome(message):
    print("DEBUG: Received /start") # للتأكد من السجلات
    user_data[message.chat.id] = {}
    msg = bot.send_message(message.chat.id, "1️⃣ أرسل الإيميل:")
    bot.register_next_step_handler(msg, step_2_email)

def step_2_email(message):
    print(f"DEBUG: Email received from {message.chat.id}")
    user_data[message.chat.id]['email'] = message.text
    msg = bot.send_message(message.chat.id, "2️⃣ أرسل الباسورد:")
    bot.register_next_step_handler(msg, step_3_password)

def step_3_password(message):
    print(f"DEBUG: Password received from {message.chat.id}")
    # تخزين الباسورد
    user_data[message.chat.id]['password'] = message.text
    
    # **تعديل هام: لن نقوم بحذف الرسالة لتجنب الأخطاء حالياً**
    
    msg = bot.send_message(message.chat.id, "✅ تم حفظ الباسورد.\n3️⃣ الآن أرسل رابط الحساب الهدف:")
    bot.register_next_step_handler(msg, step_4_target)

def step_4_target(message):
    print(f"DEBUG: Link received from {message.chat.id}")
    target_url = message.text
    chat_id = message.chat.id
    
    email = user_data[chat_id].get('email')
    password = user_data[chat_id].get('password')
    
    bot.send_message(chat_id, "جاري البدء، انتظر قليلاً...")
    threading.Thread(target=start_scraping_process, args=(chat_id, email, password, target_url)).start()

# --- 6. التشغيل ---
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    print("Bot Started Successfully...")
    bot.infinity_polling()
