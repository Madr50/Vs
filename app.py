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

# --- 3. دالة مساعدة لإرسال لقطة شاشة ---
def send_screenshot(driver, chat_id, caption=""):
    try:
        filename = f"shot_{chat_id}_{int(time.time())}.png"
        driver.save_screenshot(filename)
        with open(filename, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=caption)
        os.remove(filename) # حذف الصورة بعد الإرسال لتوفير المساحة
    except Exception as e:
        print(f"Failed to send screenshot: {e}")

# --- 4. السيرفر الوهمي ---
@app.route('/')
def home():
    return "Bot is running..."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- 5. وظيفة السحب (الرئيسية) ---
def start_scraping_process(chat_id, email, password, target_url):
    driver = None
    try:
        bot.send_message(chat_id, "⚙️ جاري تشغيل المتصفح...")
        driver = webdriver.Chrome(options=get_chrome_options())
        
        # 1. تسجيل الدخول
        driver.get('https://facebook.com')
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'email')))
        
        driver.find_element(By.ID, 'email').send_keys(email)
        driver.find_element(By.ID, 'pass').send_keys(password)
        driver.find_element(By.NAME, 'login').click()
        
        bot.send_message(chat_id, "جاري التحقق من الدخول...")
        time.sleep(5)

        # 📸 لقطة شاشة بعد محاولة الدخول
        send_screenshot(driver, chat_id, "📸 حالة المتصفح بعد تسجيل الدخول")

        if "login_attempt" in driver.current_url or "checkpoint" in driver.current_url:
             bot.send_message(chat_id, "❌ فشل الدخول. (انظر للصورة أعلاه للتأكد).")
             driver.quit()
             return

        bot.send_message(chat_id, "✅ تم الدخول! جاري الذهاب للهدف...")
        driver.get(target_url)
        time.sleep(5)

        # 📸 لقطة شاشة عند فتح بروفايل الضحية
        send_screenshot(driver, chat_id, "📸 أنا الآن في صفحة الهدف")

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
                match = re.search(r'"userID":"(\d+)"', driver.page_source)
                if match: TARGET_UID = match.group(1)
            
            if not TARGET_UID:
                # محاولة استخراج من الرابط المباشر
                match = re.search(r'id=(\d+)', target_url)
                if match: TARGET_UID = match.group(1)

        except Exception as e:
            print(f"Error finding UID: {e}")

        if not TARGET_UID:
            bot.send_message(chat_id, "❌ لم أجد ID الحساب. هل الرابط صحيح؟")
            driver.quit()
            return

        bot.send_message(chat_id, f"🆔 ID: {TARGET_UID}. جاري بدء البحث...")

        payload = '{"friends:0":"{\\"name\\":\\"users_friends_of_people\\",\\"args\\":\\"%s\\"}"}' % TARGET_UID.strip()
        encoded_payload = base64.b64encode(payload.encode('utf-8')).decode('utf-8')

        friends = []
        def check_new(last): return len(driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com')]")) > last

        # حلقة البحث (A to Z)
        for i, code in enumerate(range(97, 123)):
            char = chr(code)
            search_url = f"https://www.facebook.com/search/people/?q={char}&filters={encoded_payload}"
            driver.get(search_url)
            
            # 📸 لقطة شاشة كل 3 حروف لطمأنة المستخدم
            if i % 3 == 0:
                send_screenshot(driver, chat_id, f"📸 أبحث الآن في حرف '{char}'... (النتائج الظاهرة)")

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
                         link = href.split('?')[0]
                         if link not in friends:
                             friends.append(link)
                except: pass
            
            if i % 5 == 0: bot.send_message(chat_id, f"✅ تم الانتهاء من حرف {char}...")

        unique = list(set(friends))
        if not unique:
            # صورة نهائية ليرى المستخدم لماذا لا توجد نتائج
            send_screenshot(driver, chat_id, "📸 صورة نهائية للبحث (لم يتم العثور على نتائج)")
            bot.send_message(chat_id, "⚠️ انتهى البحث ولم أجد نتائج.")
        else:
            with open(f"{TARGET_UID}.txt", 'w') as f:
                for line in unique: f.write(f"{line}\n")
            with open(f"{TARGET_UID}.txt", 'rb') as f:
                bot.send_document(chat_id, f, caption=f"🎉 تمت المهمة!\nالعدد: {len(unique)}")
            os.remove(f"{TARGET_UID}.txt")

    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ: {e}")
        try:
            # محاولة إرسال صورة عند حدوث خطأ
            send_screenshot(driver, chat_id, "📸 لقطة الشاشة عند حدوث الخطأ")
        except: pass
    finally:
        if driver: driver.quit()

# --- 6. خطوات المحادثة ---

@bot.message_handler(commands=['start'])
def step_1_welcome(message):
    user_data[message.chat.id] = {}
    msg = bot.send_message(message.chat.id, "1️⃣ أرسل الإيميل:")
    bot.register_next_step_handler(msg, step_2_email)

def step_2_email(message):
    user_data[message.chat.id]['email'] = message.text
    msg = bot.send_message(message.chat.id, "2️⃣ أرسل الباسورد:")
    bot.register_next_step_handler(msg, step_3_password)

def step_3_password(message):
    user_data[message.chat.id]['password'] = message.text
    msg = bot.send_message(message.chat.id, "✅ تم الحفظ.\n3️⃣ الآن أرسل رابط الحساب الهدف:")
    bot.register_next_step_handler(msg, step_4_target)

def step_4_target(message):
    target_url = message.text
    chat_id = message.chat.id
    email = user_data[chat_id].get('email')
    password = user_data[chat_id].get('password')
    
    bot.send_message(chat_id, "🚀 سأبدأ الآن بإرسال صور لك لترى ماذا يحدث...")
    threading.Thread(target=start_scraping_process, args=(chat_id, email, password, target_url)).start()

# --- 7. التشغيل ---
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.infinity_polling()
