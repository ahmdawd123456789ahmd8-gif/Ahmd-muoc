import telebot
from telebot import types
import os, time, requests, threading
from flask import Flask, request
import replicate

BOT_TOKEN = os.environ.get('BOT_TOKEN')
REPLICATE_API_TOKEN = os.environ.get('REPLICATE_API_TOKEN')
ADMIN_ID = 8460989245

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
user_states = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn = types.InlineKeyboardButton("🎵 فصل الموسيقى عن الفيديو", callback_data="start_separation")
    markup.add(btn)
    bot.send_message(
        message.chat.id,
        "أهلاً بك! 👋\n\n"
        "هذا البوت بيفصل صوت الأشخاص عن الموسيقى.\n"
        "👇 اضغط للبدء:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "start_separation")
def handle_start(call):
    user_states[call.message.chat.id] = "waiting"
    bot.edit_message_text(
        "📤 أرسل الفيديو أو الملف الصوتي الآن (الحد الأقصى 50MB):",
        call.message.chat.id,
        call.message.message_id
    )

@bot.message_handler(content_types=['video', 'audio', 'document'])
def handle_media(message):
    if user_states.get(message.chat.id) != "waiting":
        return

    file_id = None
    file_size = 0
    media_type = "video"

    if message.video:
        file_id = message.video.file_id
        file_size = message.video.file_size or 0
        media_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_size = message.audio.file_size or 0
        media_type = "audio"
    elif message.document:
        file_id = message.document.file_id
        file_size = message.document.file_size or 0
        media_type = "document"

    if not file_id:
        bot.reply_to(message, "⚠️ لم يتم التعرف على الملف.")
        return

    if file_size > 50000000:
        bot.reply_to(message, "❌ الملف كبير كتير (أكثر من 50MB).")
        return

    user_states[message.chat.id] = None
    msg = bot.reply_to(message, "⏳ جاري تحميل الملف والمعالجة... (قد يستغرق عدة دقائق)")
    threading.Thread(
        target=process_media,
        args=(bot, message.chat.id, file_id, media_type, msg.message_id)
    ).start()

def upload_to_fileio(file_path):
    """رفع الملف إلى 0x0.st والحصول على رابط عام"""
    try:
        with open(file_path, 'rb') as f:
            response = requests.post(
                'https://0x0.st',
                files={'file': f},
                timeout=180
            )
        if response.status_code == 200:
            return response.text.strip()
        else:
            print(f"Upload failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"Upload error: {e}")
        return None

def process_media(bot, chat_id, file_id, media_type, msg_id):
    input_path = None
    audio_path = None
    vocals_path = None

    try:
        # 1. تحميل الملف من تيليجرام
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        if media_type == "video":
            input_path = f"input_{chat_id}.mp4"
        else:
            input_path = f"input_{chat_id}.mp3"

        with open(input_path, 'wb') as f:
            f.write(downloaded_file)

        # 2. إذا كان فيديو، نستخرج الصوت
        if media_type == "video":
            bot.edit_message_text("🎵 جاري فصل الصوت عن الفيديو...", chat_id, msg_id)
            audio_path = f"audio_{chat_id}.mp3"
            os.system(f"ffmpeg -y -i {input_path} -vn -acodec libmp3lame -q:a 2 {audio_path}")
            if not os.path.exists(audio_path):
                bot.edit_message_text("❌ فشل استخراج الصوت من الفيديو.", chat_id, msg_id)
                return
        else:
            audio_path = input_path

        # 3. رفع الصوت إلى 0x0.st
        bot.edit_message_text("📤 جاري رفع الملف للمعالجة...", chat_id, msg_id)
        public_url = upload_to_fileio(audio_path)

        if not public_url:
            bot.edit_message_text("❌ فشل رفع الملف.", chat_id, msg_id)
            return

        # 4. إرسال الطلب إلى Replicate
        bot.edit_message_text("🤖 جاري فصل الغناء عن الموسيقى... (قد يستغرق دقيقة أو دقيقتين)", chat_id, msg_id)

        os.environ['REPLICATE_API_TOKEN'] = REPLICATE_API_TOKEN

        output = replicate.run(
            "cjwbw/demucs:25a173108cff36ef9f80f854c162d01df9e6528be175794b81158fa03836d953",
            input={"audio": public_url}
        )

        # 5. النتيجة تحتوي على روابط
        if not output:
            bot.edit_message_text("❌ فشلت المعالجة.", chat_id, msg_id)
            return

        # Replicate يعطي dict فيه: vocals, bass, drums, other
        vocals_url = None
        if isinstance(output, dict):
            vocals_url = output.get('vocals')
        elif isinstance(output, str):
            vocals_url = output

        if not vocals_url:
            bot.edit_message_text("❌ لم يتم العثور على صوت الأشخاص.", chat_id, msg_id)
            return

        # 6. تنزيل ملف vocals
        bot.edit_message_text("📥 جاري تنزيل صوت الأشخاص...", chat_id, msg_id)
        vocals_response = requests.get(vocals_url, timeout=180)
        vocals_path = f"vocals_{chat_id}.wav"

        with open(vocals_path, 'wb') as f:
            f.write(vocals_response.content)

        # 7. إرسال الملف النهائي
        bot.edit_message_text("🎉 تمت العملية! جاري الإرسال...", chat_id, msg_id)

        with open(vocals_path, 'rb') as f:
            bot.send_audio(
                chat_id,
                f,
                caption="✅ هاد صوت الأشخاص بدون موسيقى! 🎤",
                timeout=300
            )

    except Exception as e:
        error_msg = f"❌ صار خطأ: {str(e)[:150]}"
        print(f"Error: {e}")
        try:
            bot.edit_message_text(error_msg, chat_id, msg_id)
        except Exception:
            bot.send_message(chat_id, error_msg)
    finally:
        for path in [input_path, audio_path, vocals_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

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
    RENDER_URL = "https://audio-separator-bot.onrender.com"
    bot.set_webhook(url=f"{RENDER_URL}/{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))