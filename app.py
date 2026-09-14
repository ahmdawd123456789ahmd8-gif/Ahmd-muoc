import telebot
from telebot import types
import os, time, requests, threading
from flask import Flask, request

BOT_TOKEN = "8782692723:AAGSY03vhqb0UboHnhqwcRl5E79C6FezMdE"
ADMIN_ID = 8460989245

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
user_states = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn = types.InlineKeyboardButton("🎵 فصل الغناء عن الموسيقى", callback_data="start_separation")
    markup.add(btn)
    bot.send_message(message.chat.id, "أهلاً بك! 👋\n\nهذا البوت بيفصل صوت المغني عن الموسيقى.\n👇 اضغط للبدء:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "start_separation")
def handle_start(call):
    user_states[call.message.chat.id] = "waiting"
    bot.edit_message_text("📤 أرسل الفيديو أو الملف الصوتي الآن (الحد الأقصى 50MB):", call.message.chat.id, call.message.message_id)

@bot.message_handler(content_types=['video', 'document', 'audio'])
def handle_media(message):
    if user_states.get(message.chat.id) != "waiting":
        return

    file_size = 0
    file_id = None
    if message.video:
        file_id, file_size = message.video.file_id, message.video.file_size
    elif message.audio:
        file_id, file_size = message.audio.file_id, message.audio.file_size
    elif message.document:
        file_id, file_size = message.document.file_id, message.document.file_size

    if file_size > 50000000:
        bot.reply_to(message, "❌ الملف كبير كتير (أكثر من 50MB).")
        return

    user_states[message.chat.id] = None
    msg = bot.reply_to(message, "⏳ جاري التحميل والمعالجة... (قد يستغرق عدة دقائق)")
    threading.Thread(target=process_media, args=(bot, message.chat.id, file_id, msg.message_id)).start()

def process_media(bot, chat_id, file_id, msg_id):
    input_path = None
    output_path = None
    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        input_path = f"input_{chat_id}.mp4"
        with open(input_path, 'wb') as f:
            f.write(downloaded_file)

        url = "https://cleverutils.com/api/v1/tools/vocal-remover"
        with open(input_path, 'rb') as f:
            response = requests.post(url, files={'file': f})

        if response.status_code != 200:
            bot.edit_message_text("❌ فشل الاتصال بالخدمة.", chat_id, msg_id)
            return

        result = response.json()
        job_id = result.get('job_id')
        if not job_id:
            bot.edit_message_text("❌ ما في job_id من الخدمة.", chat_id, msg_id)
            return

        output_url = None
        for i in range(30):
            time.sleep(2)
            check = requests.get(f"https://cleverutils.com/api/v1/jobs/{job_id}")
            if check.status_code == 200:
                data = check.json()
                if data.get('status') == 'completed' or data.get('output_url'):
                    output_url = data.get('output_url')
                    break

        if not output_url:
            bot.edit_message_text("❌ ما وصلت النتيجة من الخدمة.", chat_id, msg_id)
            return

        output_response = requests.get(output_url)
        if output_response.status_code == 200:
            output_path = f"vocals_{chat_id}.mp3"
            with open(output_path, 'wb') as f:
                f.write(output_response.content)
            with open(output_path, 'rb') as f:
                bot.send_audio(chat_id, f, caption="✅ هاد صوت المغني بدون موسيقى! 🎤")
            bot.edit_message_text("تم! ✅", chat_id, msg_id)
        else:
            bot.edit_message_text("❌ فشل تحميل الملف الناتج.", chat_id, msg_id)

    except Exception as e:
        bot.edit_message_text(f"❌ صار خطأ: {str(e)[:100]}", chat_id, msg_id)
    finally:
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
        if output_path and os.path.exists(output_path):
            os.remove(output_path)

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    bot.remove_webhook()
    RENDER_URL = "https://your-app-name.onrender.com"
    bot.set_webhook(url=f"{RENDER_URL}/{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
