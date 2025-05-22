import os
os.environ["PATH"] += os.pathsep + os.path.dirname(os.path.realpath(__file__))

import time
import logging
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import speech_recognition as sr
import subprocess
import wave
from dotenv import load_dotenv

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

if not TOKEN:
    raise ValueError("Токен не найден")

def is_valid_wav(path):
    try:
        with wave.open(path, 'r') as f:
            return f.getnchannels() == 1 and f.getsampwidth() == 2 and f.getframerate() == 48000
    except:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙 Отправьте голосовое сообщение или видео-кружочек для расшифровки!")

def convert_audio(input_path, output_path):
    command = [
        os.path.join(os.path.dirname(__file__), 'ffmpeg'),  # Используем локальный ffmpeg
        '-i', input_path,
        '-vn', '-acodec', 'pcm_s16le',
        '-ar', '48000',
        '-ac', '1',
        '-y', output_path
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        logger.error(f"FFmpeg error: {result.stderr.decode('utf-8')}")
    return os.path.exists(output_path) and is_valid_wav(output_path)

async def handle_voice_or_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    file_type = "voice" if message.voice else "video_note"
    status_msg = None
    laugh_patterns = ['ха', 'хе', 'хи', 'хо', 'xа']
    
    try:
        status_msg = await message.reply_text("⏳ Обработка аудио...")
        
        file = await message.effective_attachment.get_file()
        file_path = f"{file.file_id}.{file_type}"
        await file.download_to_drive(file_path)

        if os.path.getsize(file_path) < 100:
            await message.reply_text("❌ Файл повреждён")
            return

        if file_type == "video_note":
            mp4_path = f"{file.file_id}.mp4"
            os.rename(file_path, mp4_path)
            file_path = mp4_path

        wav_path = f"{file.file_id}.wav"
        if not convert_audio(file_path, wav_path):
            await message.reply_text("❌ Ошибка конвертации")
            return

        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 3.0
        recognizer.energy_threshold = 350
        recognizer.dynamic_energy_threshold = True

        with sr.AudioFile(wav_path) as source:
            await status_msg.edit_text("🔍 Распознавание речи...")
            
            text_chunks = []
            chunk_duration = 60
            total_duration = 600
            
            for i in range(0, total_duration, chunk_duration):
                audio_chunk = recognizer.record(
                    source, 
                    duration=chunk_duration,
                    offset=i
                )
                try:
                    chunk_text = recognizer.recognize_google(
                        audio_chunk,
                        language="ru-RU",
                        show_all=False
                    )
                    text_chunks.append(chunk_text)
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as e:
                    logger.error(f"Google API error: {e}")
                    continue

            full_text = " ".join(text_chunks)
            logger.info(f"Raw recognized text: {full_text}")

            processed_text = full_text
            has_laugh = any(
                re.search(
                    r'\b{}(?:хa|he|hi|хо)?\b'.format(pattern), 
                    processed_text, 
                    re.IGNORECASE
                ) 
                for pattern in laugh_patterns
            )
            
            max_length = 4000
            chunks = [processed_text[i:i+max_length] for i in range(0, len(processed_text), max_length)]
            
            await status_msg.edit_text("✅ Обработка завершена")
            
            for chunk in chunks:
                formatted_text = f"<blockquote>{chunk}</blockquote>"
                if has_laugh:
                    formatted_text += "\n\n🤭 Обнаружен смех в сообщении!"
                
                await message.reply_text(
                    formatted_text,
                    reply_to_message_id=message.message_id,
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        await message.reply_text(f"⚠️ Ошибка: {str(e)}")
    finally:
        for path in [file_path, wav_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    logger.error(f"Error deleting {path}: {e}")
        if status_msg:
            try:
                await status_msg.delete()
            except Exception as e:
                logger.error(f"Error deleting status message: {e}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE, handle_voice_or_video))
    app.run_polling()

if __name__ == "__main__":
    main()