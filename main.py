import os
import logging
import sqlite3
import re
import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import jdatetime
import speech_recognition as sr
from pydub import AudioSegment

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler,
)

# جایگزینی aiohttp با FastAPI برای هماهنگی با uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# ================= Configuration & Logging =================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "planner_bot.db"
ADMIN_ID = os.environ.get("ADMIN_ID")
ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else None
admin_filter = filters.User(user_id=ADMIN_ID) if ADMIN_ID else filters.ALL

WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-render-app.onrender.com/static/index.html")

# ================= States for Conversation =================
WAITING_FOR_TASK_TEXT = 1
WAITING_FOR_PRIORITY = 2
WAITING_FOR_TIME = 3
WAITING_FOR_RECURRENCE = 4

# ================= Database Setup =================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_text TEXT,
                priority TEXT,
                due_time TIMESTAMP,
                category TEXT,
                file_id TEXT,
                status TEXT DEFAULT 'pending',
                recurrence TEXT DEFAULT 'none',
                created_at TIMESTAMP
            )
        ''')
        try:
            cursor.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'none'")
        except sqlite3.OperationalError:
            pass
        conn.commit()

# ================= Keyboards =================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ افزودن وظیفه جدید"), KeyboardButton("🌐 مینی‌اپ (Mini App)", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton("📋 لیست وظایف من"), KeyboardButton("🗂 دسته‌بندی‌ها")],
            [KeyboardButton("🍅 پومودورو (۲۵ دقیقه)"), KeyboardButton("📊 آمار عملکرد")],
            [KeyboardButton("📥 خروجی اکسل (CSV)")],
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ انصراف")]], resize_keyboard=True)

def get_priority_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔴 بالا"), KeyboardButton("🟡 متوسط"), KeyboardButton("🟢 پایین")],
            [KeyboardButton("❌ انصراف")]
        ],
        resize_keyboard=True
    )

def get_time_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("⏭ رد کردن (بدون زمان)")], [KeyboardButton("❌ انصراف")]], resize_keyboard=True)

def get_recurrence_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("تکرار روزانه 🔄"), KeyboardButton("بدون تکرار ⏹")],
            [KeyboardButton("❌ انصراف")]
        ],
        resize_keyboard=True
    )

# ================= Database Helpers =================
def _add_task_to_db(user_id, text, priority, due_time, category, file_id, recurrence='none'):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        created_at = jdatetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute(
            "INSERT INTO tasks (user_id, task_text, priority, due_time, category, file_id, recurrence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, text, priority, due_time, category, file_id, recurrence, created_at)
        )
        conn.commit()
        return cursor.lastrowid

def _get_pending_tasks(user_id, category_filter=None):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        if category_filter:
            cursor.execute("SELECT id, task_text, priority, due_time, file_id, category FROM tasks WHERE user_id = ? AND status = 'pending' AND category LIKE ? ORDER BY id DESC", (user_id, f"%{category_filter}%"))
        else:
            cursor.execute("SELECT id, task_text, priority, due_time, file_id, category FROM tasks WHERE user_id = ? AND status = 'pending' ORDER BY id DESC", (user_id,))
        return cursor.fetchall()

def _get_task_by_id(task_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return cursor.fetchone()

def _update_task_status(task_id, status):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        conn.commit()

def _delete_task_from_db(task_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

def _get_categories(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM tasks WHERE user_id = ? AND status = 'pending' AND category IS NOT NULL", (user_id,))
        rows = cursor.fetchall()
        categories = set()
        for row in rows:
            if row[0]:
                for cat in row[0].split(','):
                    categories.add(cat.strip())
        return list(categories)

# ================= Tasks Rendering Helper =================
async def render_tasks(update, context, tasks):
    if not tasks:
        await update.message.reply_text("📭 لیستی برای نمایش وجود ندارد.", reply_markup=get_main_keyboard())
        return
    
    for task_id, task_text, priority, due_time, file_id, category in tasks:
        icon = "🔴" if priority == 'high' else "🟡" if priority == 'medium' else "🟢"
        cat_text = f"\n🏷 دسته‌بندی: {category}" if category else ""
        
        time_text = ""
        if due_time:
            try:
                dt_obj = datetime.strptime(due_time, "%Y-%m-%d %H:%M")
                jdt = jdatetime.datetime.fromgregorian(datetime=dt_obj)
                time_text = f"\n⏰ سررسید: {jdt.strftime('%Y/%m/%d %H:%M')}"
            except:
                time_text = f"\n⏰ سررسید: {due_time}"

        content = f"{icon} <b>{task_text}</b>{cat_text}{time_text}"
        inline_kb = [[InlineKeyboardButton("✅ انجام شد", callback_data=f'done_{task_id}'), InlineKeyboardButton("❌ حذف", callback_data=f'del_{task_id}')]]
        if file_id:
            inline_kb.append([InlineKeyboardButton("📎 دریافت فایل پیوست", callback_data=f'file_{file_id}')])
            
        await update.message.reply_text(content, reply_markup=InlineKeyboardMarkup(inline_kb), parse_mode='HTML')

# ================= Bot Handlers =================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>سلام! به ربات مدیریت وظایف خوش آمدید.</b>\n\nبرای شروع یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=get_main_keyboard(),
        parse_mode='HTML'
    )

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    if text == "📋 لیست وظایف من":
        tasks = await asyncio.to_thread(_get_pending_tasks, user_id)
        await render_tasks(update, context, tasks)

    elif text == "🗂 دسته‌بندی‌ها":
        categories = await asyncio.to_thread(_get_categories, user_id)
        if not categories:
            await update.message.reply_text("هیچ دسته‌بندی (هشتگ) فعالی یافت نشد.")
            return
        
        kb = [[InlineKeyboardButton(cat, callback_data=f'cat_{cat}')] for cat in categories]
        await update.message.reply_text("🗂 یک دسته‌بندی را برای فیلتر انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))

async def inline_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith('cat_'):
        category = data.split('cat_')[1]
        tasks = await asyncio.to_thread(_get_pending_tasks, query.from_user.id, category)
        await query.message.delete()
        await render_tasks(query, context, tasks)
        return

    if data.startswith('done_') or data.startswith('del_'):
        action, task_id_str = data.split('_')
        task_id = int(task_id_str)
        task = await asyncio.to_thread(_get_task_by_id, task_id)
        
        if not task:
            await query.edit_message_text("تسک یافت نشد.")
            return

        file_id = task[6]
        recurrence = task[8]
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("📎 دریافت پیوست", callback_data=f'file_{file_id}')]]) if file_id else None

        if action == 'done':
            await asyncio.to_thread(_update_task_status, task_id, 'completed')
            if recurrence == 'daily':
                new_due = None
                if task[4]:
                    dt_obj = datetime.strptime(task[4], "%Y-%m-%d %H:%M") + timedelta(days=1)
                    new_due = dt_obj.strftime("%Y-%m-%d %H:%M")
                await asyncio.to_thread(_add_task_to_db, task[1], task[2], task[3], new_due, task[5], task[6], recurrence)
                await query.edit_message_text("🎉 <b>وظیفه تیک خورد و برای فردا مجدداً ساخته شد! 🔄</b>", reply_markup=reply_markup, parse_mode='HTML')
            else:
                await query.edit_message_text("🎉 <b>وظیفه با موفقیت تیک خورد!</b>", reply_markup=reply_markup, parse_mode='HTML')
                
        elif action == 'del':
            await asyncio.to_thread(_delete_task_from_db, task_id)
            await query.edit_message_text("🗑 <b>وظیفه حذف شد.</b>", reply_markup=reply_markup, parse_mode='HTML')
            
    elif data.startswith('file_'):
        file_id = data.split('file_')[1]
        await context.bot.send_document(chat_id=query.message.chat_id, document=file_id)

# ================= Add Task Conversation =================
async def start_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 <b>عنوان وظیفه را تایپ کنید یا ویس (Voice) بفرستید:</b>\n\n<i>💡 ویس شما با هوش مصنوعی تبدیل به متن می‌شود.</i>", 
        reply_markup=get_cancel_keyboard(), parse_mode='HTML'
    )
    return WAITING_FOR_TASK_TEXT

def _process_voice_sync(ogg_path, wav_path):
    audio = AudioSegment.from_ogg(ogg_path)
    audio.export(wav_path, format="wav")
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)
        return recognizer.recognize_google(audio_data, language="fa-IR")

async def receive_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    if message.text == "❌ انصراف":
        await update.message.reply_text("لغو شد 🔙", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    text, file_id = "", None

    if message.voice:
        msg = await message.reply_text("⏳ در حال پردازش صوت به متن...")
        ogg_path, wav_path = f"voice_{message.message_id}.ogg", f"voice_{message.message_id}.wav"
        try:
            voice_file = await context.bot.get_file(message.voice.file_id)
            await voice_file.download_to_drive(ogg_path)
            text = await asyncio.to_thread(_process_voice_sync, ogg_path, wav_path)
            await msg.delete()
            await message.reply_text(f"🗣 متن استخراج شده:\n{text}")
        except Exception as e:
            await msg.edit_text(f"خطا در پردازش صوت: لطفاً واضح‌تر صحبت کنید یا پیام متنی بفرستید.")
            return WAITING_FOR_TASK_TEXT
        finally:
            if os.path.exists(ogg_path): os.remove(ogg_path)
            if os.path.exists(wav_path): os.remove(wav_path)
    else:
        if message.document:
            file_id = message.document.file_id
            text = message.caption or "فایل بدون عنوان"
        elif message.photo:
            file_id = message.photo[-1].file_id
            text = message.caption or "عکس بدون عنوان"
        else:
            text = message.text

    hashtags = re.findall(r'#(\w+)', text)
    context.user_data.update({'temp_task': text, 'temp_file': file_id, 'temp_category': ", ".join(hashtags) if hashtags else None})
    await update.message.reply_text("🎚 <b>اولویت این کار چقدر است؟</b>", reply_markup=get_priority_keyboard(), parse_mode='HTML')
    return WAITING_FOR_PRIORITY

async def receive_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "❌ انصراف": return ConversationHandler.END
    context.user_data['temp_priority'] = {"🔴 بالا": "high", "🟡 متوسط": "medium", "🟢 پایین": "low"}.get(update.message.text, "medium")
    await update.message.reply_text("⏰ <b>زمان یادآوری (HH:MM):</b>", reply_markup=get_time_keyboard(), parse_mode='HTML')
    return WAITING_FOR_TIME

async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "❌ انصراف": return ConversationHandler.END
    due_time_str = None
    if text != "⏭ رد کردن (بدون زمان)":
        try:
            time_obj = datetime.strptime(text, "%H:%M").time()
            now = datetime.now()
            target_time = datetime.combine(now.date(), time_obj)
            if target_time < now: target_time += timedelta(days=1)
            due_time_str = target_time.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text("⚠️ فرمت زمان اشتباه است.")
            return WAITING_FOR_TIME
    context.user_data['temp_due_time'] = due_time_str
    await update.message.reply_text("🔄 <b>آیا این وظیفه تکرارشونده است؟</b>", reply_markup=get_recurrence_keyboard(), parse_mode='HTML')
    return WAITING_FOR_RECURRENCE

async def receive_recurrence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "❌ انصراف": return ConversationHandler.END
    ud = context.user_data
    await asyncio.to_thread(
        _add_task_to_db, update.message.from_user.id, ud['temp_task'], ud['temp_priority'], 
        ud.get('temp_due_time'), ud['temp_category'], ud['temp_file'], "daily" if "روزانه" in update.message.text else "none"
    )
    await update.message.reply_text(f"✅ <b>وظیفه ثبت شد:</b>\n📌 {ud['temp_task']}", reply_markup=get_main_keyboard(), parse_mode='HTML')
    context.user_data.clear()
    return ConversationHandler.END

# ================= FastAPI & Bot Initialization =================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ptb_app = None

if TOKEN:
    ptb_app = Application.builder().token(TOKEN).build()
    ptb_app.add_handler(CommandHandler("start", start_command, filters=admin_filter))
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ افزودن وظیفه جدید$") & admin_filter, start_add_task)],
        states={
            WAITING_FOR_TASK_TEXT: [MessageHandler((filters.TEXT | filters.VOICE | filters.Document.ALL | filters.PHOTO) & admin_filter, receive_task_text)],
            WAITING_FOR_PRIORITY: [MessageHandler(filters.TEXT & admin_filter, receive_priority)],
            WAITING_FOR_TIME: [MessageHandler(filters.TEXT & admin_filter, receive_time)],
            WAITING_FOR_RECURRENCE: [MessageHandler(filters.TEXT & admin_filter, receive_recurrence)]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: u.message.reply_text("لغو شد", reply_markup=get_main_keyboard()))],
    )
    ptb_app.add_handler(conv_handler)
    ptb_app.add_handler(MessageHandler(filters.Regex("^(📋 لیست وظایف من|🗂 دسته‌بندی‌ها|📊 آمار عملکرد|🍅 پومودورو \(۲۵ دقیقه\)|📥 خروجی اکسل \(CSV\))$") & admin_filter, handle_main_menu))
    ptb_app.add_handler(CallbackQueryHandler(inline_buttons_handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # هنگام شروع سرور
    init_db()
    if ptb_app:
        await ptb_app.initialize()
        await ptb_app.start()
        await ptb_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot started successfully!")
    yield
    # هنگام خاموش شدن سرور
    if ptb_app:
        await ptb_app.updater.stop()
        await ptb_app.stop()
        await ptb_app.shutdown()

# متغیر app که uvicorn به دنبال آن است
app = FastAPI(lifespan=lifespan)

# سرو کردن فایل‌های استاتیک مینی‌اپ (اگر پوشه static وجود داشته باشد)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def health_check():
    """مسیر Health Check برای جلوگیری از خطای Render"""
    return {"status": "success", "message": "Bot & FastAPI Server are running!"}
