import telebot
from telebot import types
import os, time, requests, threading
from flask import Flask, request
from gradio_client import Client, handle_file

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 8460989245

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
user_states = {}

AUDIOSEP_SPACE = "Luminia/audiosep"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn = types.InlineKeyboardButton("🎵 فصل الغناء عن الموسيقى", callback_data="start_separation")
    markup.add(btn)
    bot.send_message(message.chat.id, "أهلاً بك! 👋\n\nهذا البوت بيفصل صوت الأشخاص عن الموسيقى، ويرجعلك الفيديو بصوت الأشخاص فقط.\n👇 اضغط للبدء:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "start_separation")
def handle_start(call):
    user_states[call.message.chat.id] = "waiting"
    bot.edit_message_text("📤 أرسل الفيديو الآن (الحد الأقصى 50MB):", call.message.chat.id, call.message.message_id)

@bot.message_handler(content_types=['video', 'document'])
def handle_media(message):
    if user_states.get(message.chat.id) != "waiting":
        return

    file_size = 0
    file_id = None
    ext = '.mp4'

    if message.video:
        file_id, file_size = message.video.file_id, message.video.file_size
    elif message.document:
        file_id, file_size = message.document.file_id, message.document.file_size
        ext = os.path.splitext(message.document.file_name or 'file.mp4')[1] or '.mp4'

    if file_size > 50000000:
        bot.reply_to(message, "❌ الملف كبير كتير (أكثر من 50MB).")
        return

    user_states[message.chat.id] = None
    msg = bot.reply_to(message, "⏳ جاري تحميل الفيديو والمعالجة... (قد يستغرق عدة دقائق)")
    threading.Thread(target=process_media, args=(bot, message.chat.id, file_id, ext, msg.message_id)).start()

def process_media(bot, chat_id, file_id, ext, msg_id):
    input_video_path = None
    audio_path = None
    vocals_path = None
    final_video_path = None

    try:
        # 1. تحميل الفيديو من تيليجرام
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        input_video_path = f"input_{chat_id}{ext}"
        with open(input_video_path, 'wb') as f:
            f.write(downloaded_file)

        bot.edit_message_text("🎵 جاري فصل الصوت عن الفيديو...", chat_id, msg_id)

        # 2. استخراج الصوت من الفيديو بجودة عالية (44.1kHz، stereo)
        audio_path = f"audio_{chat_id}.wav"
        os.system(f"ffmpeg -y -i {input_video_path} -vn -acodec pcm_s16le -ar 44100 -ac 2 {audio_path}")

        if not os.path.exists(audio_path):
            bot.edit_message_text("❌ فشل استخراج الصوت من الفيديو.", chat_id, msg_id)
            return

        bot.edit_message_text("🤖 جاري فصل الغناء عن الموسيقى... (قد يستغرق بعض الوقت)", chat_id, msg_id)

        # 3. إرسال الصوت إلى مساحة AudioSep - استخدام "vocals" بدلاً من "speech"
        client = Client(AUDIOSEP_SPACE)

        result = client.predict(
            audio_file_path=handle_file(audio_path),
            text="vocals",
            api_name="/separate"
        )

        # 4. استلام ملف الغناء الناتج
        vocals_data = result[0] if isinstance(result, tuple) else result
        vocals_path = f"vocals_{chat_id}.wav"

        if isinstance(vocals_data, str):
            if vocals_data.startswith('http'):
                r = requests.get(vocals_data)
                with open(vocals_path, 'wb') as f:
                    f.write(r.content)
            else:
                vocals_path = vocals_data

        if not vocals_path or not os.path.exists(vocals_path):
            bot.edit_message_text("❌ فشلت عملية فصل الغناء.", chat_id, msg_id)
            return

        bot.edit_message_text("🎬 جاري دمج صوت الأشخاص مع الفيديو...", chat_id, msg_id)

        # 5. دمج صوت الأشخاص مع الفيديو الأصلي بجودة عالية
        final_video_path = f"final_{chat_id}.mp4"
        os.system(f"ffmpeg -y -i {input_video_path} -i {vocals_path} -c:v copy -c:a aac -b:a 192k -map 0:v:0 -map 1:a:0 -shortest {final_video_path}")

        if not os.path.exists(final_video_path):
            bot.edit_message_text("❌ فشل دمج الصوت مع الفيديو.", chat_id, msg_id)
            return

        bot.edit_message_text("🎉 تمت العملية بنجاح! جاري الإرسال...", chat_id, msg_id)

        # 6. إرسال الفيديو النهائي
        with open(final_video_path, 'rb') as f:
            bot.send_video(chat_id, f, caption="✅ هاد الفيديو بصوت الأشخاص فقط بدون موسيقى! 🎤", timeout=300)

    except Exception as e:
        error_msg = f"❌ صار خطأ: {str(e)[:150]}"
        print(f"Error: {e}")
        bot.edit_message_text(error_msg, chat_id, msg_id)
    finally:
        for path in [input_video_path, audio_path, vocals_path, final_video_path]:
            if path and os.path.exists(path):
                os.remove(path)

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