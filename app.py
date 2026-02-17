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
ADMIN_ID = '7825994636' # استبدل هذا بالـ ID الخاص بك لكي لا يستخدمه غيرك

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- متغير لتخزين بيانات المستخدمين المؤقتة ---
user_data = {}

# --- إعدادات كروم لمنصة Render ---
def get_chrome_options():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = os.environ.get("CHROME_BIN")
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--window-size=1366,768")
    # إخفاء رسائل التحكم
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    return chrome_options

# --- سيرفر Flask (لإبقاء البوت حياً) ---
@app.route('/')
def home():
    return "Bot is running with Interactive Mode..."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- منطق السحب (Scraping Logic) ---
def start_scraping_process(chat_id, email, password, target_url):
    driver = None
    try:
        bot.send_message(chat_id, "🚀 تم استلام البيانات! جاري تشغيل المتصفح والدخول...")

        driver = webdriver.Chrome(options=get_chrome_options())
        
        # 1. تسجيل الدخول
        driver.get('https://facebook.com')
        
        # انتظار حقل الإيميل
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'email')))
        
        driver.find_element(By.ID, 'email').send_keys(email)
        driver.find_element(By.ID, 'pass').send_keys(password)
        driver.find_element(By.NAME, 'login').click()
        
        bot.send_message(chat_id, "🔐 جاري التحقق من تسجيل الدخول...")
        time.sleep(5) 

        # التحقق هل دخل فعلاً أم لا (فحص وجود خطأ)
        if "login_attempt" in driver.current_url or "checkpoint" in driver.current_url:
             bot.send_message(chat_id, "❌ فشل تسجيل الدخول! تأكد من الإيميل أو الباسورد، أو أن الحساب لم يطلب تحقق ثنائي.")
             driver.quit()
             return

        # 2. الذهاب للهدف
        bot.send_message(chat_id, "✅ تم الدخول. جاري الذهاب لصفحة الهدف...")
        driver.get(target_url)
        time.sleep(5)

        # 3. استخراج UID
        TARGET_UID = None
        try:
            # محاولة فتح قائمة الخيارات للكشف عن الروابط المخفية
            try:
                driver.find_element(By.XPATH, "//div[@aria-label='See Options']").click()
                time.sleep(1)
            except:
                pass

            # البحث عن رابط الصداقة لاستخراج الـ ID
            links = driver.find_elements(By.TAG_NAME, 'a')
            for link in links:
                href = link.get_attribute('href')
                if href and 'friendship' in href:
                    match = re.search(r'/(\d+)/', href)
                    if not match:
                        match = re.search(r'id=(\d+)', href)
                    
                    if match:
                        TARGET_UID = match.group(1)
                        break
            
            if not TARGET_UID:
                # محاولة أخيرة من الكود المصدري للصفحة
                page_source = driver.page_source
                match = re.search(r'"userID":"(\d+)"', page_source)
                if match:
                    TARGET_UID = match.group(1)

            if not TARGET_UID:
                bot.send_message(chat_id, "❌ لم أتمكن من العثور على ID الحساب. هل الرابط صحيح؟ وهل قائمة الأصدقاء متاحة؟")
                driver.quit()
                return

        except Exception as e:
            bot.send_message(chat_id, f"❌ خطأ أثناء استخراج المعرف: {e}")
            driver.quit()
            return

        bot.send_message(chat_id, f"🆔 تم استخراج المعرف: {TARGET_UID}\n⏳ جاري سحب الأصدقاء الآن...")

        # تجهيز الفلتر
        payload = '{"friends:0":"{\\"name\\":\\"users_friends_of_people\\",\\"args\\":\\"%s\\"}"}' % TARGET_UID.strip()
        encoded_payload = base64.b64encode(payload.encode('utf-8')).decode('utf-8')

        # 4. عملية السحب
        friends = []
        remove_substring = lambda str1, str2: str1.replace(str2, "")

        def check_for_new_elements(last_count):
            current_count = len(driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com')]"))
            return current_count > last_count

        def getFriends(letter):
            driver.get(f"https://www.facebook.com/search/people/?q={letter}&filters={encoded_payload}")
            last_element_count = 0
            retries = 0
            while retries < 3:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
                time.sleep(1.5)
                if not check_for_new_elements(last_element_count):
                    retries += 1
                else:
                    retries = 0
                last_element_count = len(driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com/')]"))

            elements = driver.find_elements(By.XPATH, "//a[contains(@href, 'facebook.com/')]")
            for element in elements:
                link = str(element.get_attribute('href'))
                if 'login_alerts' not in link and 'notifications' not in link and '__tn__=%3C' not in link:
                     clean_link = remove_substring(remove_substring(link, '?__tn__=%3C'), '&__tn__=%3C')
                     friends.append(clean_link)

        # التكرار على الحروف
        for i, l in enumerate(range(97, 123)):
            getFriends(chr(l))
            # تحديث الحالة كل 25% من التقدم
            if i == 5: bot.send_message(chat_id, "20% ...")
            if i == 13: bot.send_message(chat_id, "50% ...")
            if i == 20: bot.send_message(chat_id, "80% ...")

        # 5. الحفظ والإرسال
        unique_friends = list(set(friends))
        filename = f"friends_{TARGET_UID}.txt"
        
        if len(unique_friends) == 0:
             bot.send_message(chat_id, "⚠️ لم يتم العثور على أي أصدقاء. قد تكون القائمة مخفية بالكامل أو الحساب خاص.")
        else:
            with open(filename, 'w') as f:
                for item in unique_friends:
                    f.write("%s\n" % item)
            
            with open(filename, 'rb') as doc:
                bot.send_document(chat_id, doc, caption=f"✅ اكتملت المهمة!\nتم استخراج: {len(unique_friends)} صديق.")
            
            os.remove(filename)

    except Exception as e:
        bot.send_message(chat_id, f"❌ حدث خطأ غير متوقع: {e}")
    finally:
        if driver:
            driver.quit()
        # مسح بيانات المستخدم من الذاكرة
        if chat_id in user_data:
            del user_data[chat_id]

# --- إدارة المحادثة (Conversation Handlers) ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if str(message.chat.id) != ADMIN_ID:
        bot.reply_to(message, "⛔ هذا البوت خاص.")
        return
    
    # تهيئة بيانات المستخدم
    user_data[message.chat.id] = {}
    msg = bot.reply_to(message, "👋 أهلاً بك في بوت السحب المطور.\n\nالخطوة 1: أرسل **الإيميل** الخاص بحساب فيسبوك الذي ستسحب منه:")
    bot.register_next_step_handler(msg, process_email_step)

def process_email_step(message):
    if message.text == '/cancel':
        bot.reply_to(message, "تم الإلغاء.")
        return

    email = message.text
    user_data[message.chat.id]['email'] = email
    
    msg = bot.reply_to(message, "✅ تم حفظ الإيميل.\n\nالخطوة 2: أرسل **كلمة المرور** (سيتم استخدامها مرة واحدة فقط):")
    bot.register_next_step_handler(msg, process_password_step)

def process_password_step(message):
    if message.text == '/cancel':
        bot.reply_to(message, "تم الإلغاء.")
        return

    password = message.text
    user_data[message.chat.id]['password'] = password
    
    # محاولة حذف رسالة الباسورد للأمان (قد لا تعمل في المجموعات حسب الصلاحيات)
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

    msg = bot.reply_to(message, "✅ تم استلام كلمة المرور.\n\nالخطوة 3: أرسل **رابط حساب الضحية**:")
    bot.register_next_step_handler(msg, process_target_step)

def process_target_step(message):
    if message.text == '/cancel':
        bot.reply_to(message, "تم الإلغاء.")
        return

    target_url = message.text
    chat_id = message.chat.id
    
    # استرجاع البيانات المحفوظة
    email = user_data[chat_id].get('email')
    password = user_data[chat_id].get('password')
    
    if not email or not password:
        bot.reply_to(message, "❌ حدث خطأ في البيانات، أعد التشغيل بـ /start")
        return

    bot.reply_to(message, "🔄 جاري المعالجة... يرجى الانتظار ولا ترسل أوامر أخرى.")
    
    # تشغيل العملية في ثريد منفصل
    t = threading.Thread(target=start_scraping_process, args=(chat_id, email, password, target_url))
    t.start()

@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    if message.chat.id in user_data:
        del user_data[message.chat.id]
    bot.reply_to(message, "تم إلغاء العملية الحالية. اضغط /start للبدء من جديد.")

# --- التشغيل ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    print("Bot started...")
    bot.infinity_polling()
