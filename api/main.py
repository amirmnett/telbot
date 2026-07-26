import os
import logging
import sqlite3
import csv
import io
import re
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ================= Configuration & Logging =================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "planner_bot.db"

# ================= Database Setup =================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # اضافه شدن ستون‌های due_time, category, file_id
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
            created_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ================= States for Conversation =================
WAITING_FOR_TASK_TEXT = 1
WAITING_FOR_PRIORITY = 2
WAITING_FOR_TIME = 3

# ================= Keyboards =================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ افزودن وظیفه جدید")],
            [KeyboardButton("📋 لیست وظایف من"), KeyboardButton("📊 آمار عملکرد")],
            [KeyboardButton("🍅 پومودورو (۲۵ دقیقه)"), KeyboardButton("📥 خروجی اکسل (CSV)")],
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ انصراف")]], resize_keyboard=True)

def get_priority_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔴 بالا (High)"), KeyboardButton("🟡 متوسط (Medium)"), KeyboardButton("🟢 پایین (Low)")],
            [KeyboardButton("❌ انصراف")]
        ],
        resize_keyboard=True
    )

def get_time_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⏭ رد کردن (بدون زمان)")], [KeyboardButton("❌ انصراف")]],
        resize_keyboard=True
    )

# ================= Database Helpers =================
def add_task_to_db(user_id, text, priority, due_time, category, file_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (user_id, task_text, priority, due_time, category, file_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, text, priority, due_time, category, file_id, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id

def get_pending_tasks(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, task_text, priority, due_time, file_id, category FROM tasks WHERE user_id = ? AND status = 'pending' ORDER BY id DESC", (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def update_task_status(task_id, status):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    conn.commit()
    conn.close()

def delete_task_from_db(task_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def get_user_stats(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (user_id,))
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'completed'", (user_id,))
    completed = cursor.fetchone()[0]
    conn.close()
    return total, completed, total - completed

def get_all_tasks_for_export(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, task_text, priority, category, status, created_at, due_time FROM tasks WHERE user_id = ?", (user_id,))
    data = cursor.fetchall()
    conn.close()
    return data

# ================= Callbacks (Jobs) =================
async def send_reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        job.chat_id, 
        text=f"⏰ <b>یادآوری وظیفه:</b>\n\n📌 {job.data}\n\n<i>زمان انجام این کار فرا رسیده است!</i>", 
        parse_mode='HTML'
    )

async def pomodoro_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        job.chat_id, 
        text="🍅 <b>زمان پومودورو به پایان رسید!</b>\n\nخسته نباشید. حالا ۵ دقیقه استراحت کنید ☕️", 
        parse_mode='HTML'
    )

# ================= Bot Handlers =================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🔥 <b>به ربات برنامه‌ریز فوق‌حرفه‌ای خوش آمدید!</b>\n\n"
        "از منوی پایین صفحه یکی از گزینه‌ها را انتخاب کنید 👇"
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard(), parse_mode='HTML')

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    if text == "📋 لیست وظایف من":
        tasks = get_pending_tasks(user_id)
        if not tasks:
            await update.message.reply_text("📭 لیست شما خالی است! عالیه.", reply_markup=get_main_keyboard())
            return
        
        for task_id, task_text, priority, due_time, file_id, category in tasks:
            icon = "🔴" if priority == 'high' else "🟡" if priority == 'medium' else "🟢"
            cat_text = f"\n🏷 دسته‌بندی: {category}" if category else ""
            time_text = f"\n⏰ سررسید: {due_time}" if due_time else ""
            
            content = f"{icon} <b>{task_text}</b>{cat_text}{time_text}"
            
            inline_kb = [
                [
                    InlineKeyboardButton("✅ انجام شد", callback_data=f'done_{task_id}'),
                    InlineKeyboardButton("❌ حذف", callback_data=f'del_{task_id}')
                ]
            ]
            
            if file_id:
                inline_kb.append([InlineKeyboardButton("📎 دریافت فایل پیوست", callback_data=f'file_{file_id}')])
                
            await update.message.reply_text(content, reply_markup=InlineKeyboardMarkup(inline_kb), parse_mode='HTML')

    elif text == "📊 آمار عملکرد":
        total, completed, pending = get_user_stats(user_id)
        stats_text = (
            "📊 <b>داشبورد عملکرد شما:</b>\n\n"
            f"🔹 کل وظایف: <b>{total}</b>\n"
            f"✅ انجام شده: <b>{completed}</b>\n"
            f"⏳ باقی‌مانده: <b>{pending}</b>\n\n"
            "<i>روند عالیه، ادامه بده! 🚀</i>"
        )
        await update.message.reply_text(stats_text, reply_markup=get_main_keyboard(), parse_mode='HTML')

    elif text == "🍅 پومودورو (۲۵ دقیقه)":
        context.job_queue.run_once(pomodoro_callback, 25 * 60, chat_id=user_id)
        await update.message.reply_text("🍅 تایمر تمرکز ۲۵ دقیقه‌ای شروع شد! روی کارتان متمرکز شوید، من به شما اطلاع می‌دهم 🤫", reply_markup=get_main_keyboard())

    elif text == "📥 خروجی اکسل (CSV)":
        tasks = get_all_tasks_for_export(user_id)
        if not tasks:
            await update.message.reply_text("داده‌ای برای خروجی وجود ندارد.")
            return
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Task', 'Priority', 'Category', 'Status', 'Created At', 'Due Time'])
        for row in tasks:
            writer.writerow(row)
        
        output.seek(0)
        byte_output = io.BytesIO(output.getvalue().encode('utf-8-sig')) # utf-8-sig for Persian excel support
        byte_output.name = f"Tasks_Report_{datetime.now().strftime('%Y%m%d')}.csv"
        
        await context.bot.send_document(chat_id=user_id, document=byte_output, caption="📊 فایل گزارش وظایف شما")

async def inline_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('done_'):
        task_id = int(query.data.split('_')[1])
        update_task_status(task_id, 'completed')
        await query.edit_message_text("🎉 <b>وظیفه با موفقیت تیک خورد!</b>", parse_mode='HTML')
        
    elif query.data.startswith('del_'):
        task_id = int(query.data.split('_')[1])
        delete_task_from_db(task_id)
        await query.edit_message_text("🗑 <b>وظیفه به طور کامل حذف شد.</b>", parse_mode='HTML')
        
    elif query.data.startswith('file_'):
        file_id = query.data.split('file_')[1]
        await context.bot.send_document(chat_id=query.message.chat_id, document=file_id)

# ================= Add Task Conversation =================
async def start_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 <b>عنوان وظیفه جدید را تایپ کنید:</b>\n\n"
        "<i>💡 نکته: می‌توانید یک فایل/عکس ارسال کنید و عنوان را در کپشن بنویسید. همچنین با استفاده از # می‌توانید دسته‌بندی بسازید (مثل #فریلنسینگ).</i>", 
        reply_markup=get_cancel_keyboard(), 
        parse_mode='HTML'
    )
    return WAITING_FOR_TASK_TEXT

async def receive_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    
    if message.text == "❌ انصراف":
        await update.message.reply_text("عملیات لغو شد 🔙", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    # بررسی فایل پیوست
    file_id = None
    if message.document:
        file_id = message.document.file_id
        text = message.caption or "فایل بدون عنوان"
    elif message.photo:
        file_id = message.photo[-1].file_id
        text = message.caption or "عکس بدون عنوان"
    else:
        text = message.text

    # استخراج هشتگ‌ها به عنوان دسته‌بندی
    hashtags = re.findall(r'#(\w+)', text)
    category = ", ".join(hashtags) if hashtags else None

    context.user_data['temp_task'] = text
    context.user_data['temp_file'] = file_id
    context.user_data['temp_category'] = category

    await update.message.reply_text(
        "🎚 <b>اولویت این کار چقدر است؟</b>",
        reply_markup=get_priority_keyboard(),
        parse_mode='HTML'
    )
    return WAITING_FOR_PRIORITY

async def receive_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "❌ انصراف":
        await update.message.reply_text("عملیات لغو شد 🔙", reply_markup=get_main_keyboard())
        return ConversationHandler.END
        
    priority_map = {"🔴 بالا (High)": "high", "🟡 متوسط (Medium)": "medium", "🟢 پایین (Low)": "low"}
    context.user_data['temp_priority'] = priority_map.get(text, "medium")
    
    await update.message.reply_text(
        "⏰ <b>زمان یادآوری را وارد کنید:</b>\n"
        "فرمت: HH:MM (مثلاً 14:30)\n"
        "اگر یادآور نمی‌خواهید، گزینه رد کردن را بزنید.",
        reply_markup=get_time_keyboard(),
        parse_mode='HTML'
    )
    return WAITING_FOR_TIME

async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    user_id = update.message.from_user.id
    
    if text == "❌ انصراف":
        await update.message.reply_text("عملیات لغو شد 🔙", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    task_text = context.user_data.get('temp_task', 'بدون عنوان')
    priority = context.user_data.get('temp_priority', 'medium')
    file_id = context.user_data.get('temp_file')
    category = context.user_data.get('temp_category')
    due_time_str = None

    if text != "⏭ رد کردن (بدون زمان)":
        try:
            time_obj = datetime.strptime(text, "%H:%M").time()
            now = datetime.now()
            target_time = datetime.combine(now.date(), time_obj)
            
            # اگر زمان گذشته بود، برای فردا تنظیم کن
            if target_time < now:
                target_time += timedelta(days=1)
                
            due_time_str = target_time.strftime("%Y-%m-%d %H:%M")
            
            # تنظیم JobQueue برای یادآوری
            context.job_queue.run_once(
                send_reminder_callback, 
                when=target_time, 
                chat_id=user_id, 
                data=task_text
            )
            
        except ValueError:
            await update.message.reply_text("⚠️ فرمت زمان اشتباه است. لطفاً به شکل 14:30 وارد کنید یا رد کنید.")
            return WAITING_FOR_TIME

    add_task_to_db(user_id, task_text, priority, due_time_str, category, file_id)
    
    msg = f"✅ <b>وظیفه با موفقیت ثبت شد:</b>\n📌 {task_text}"
    if due_time_str:
        msg += f"\n⏰ <i>یادآوری در: {due_time_str}</i>"
        
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='HTML')
    
    # پاکسازی دیتای موقت
    context.user_data.clear()
    return ConversationHandler.END

# ================= Main Execution =================
def main():
    init_db()
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    PORT = int(os.environ.get('PORT', '10000'))
    RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if not TOKEN:
        logger.error("Token missing!")
        return

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ افزودن وظیفه جدید$"), start_add_task)],
        states={
            WAITING_FOR_TASK_TEXT: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.PHOTO, receive_task_text)],
            WAITING_FOR_PRIORITY: [MessageHandler(filters.TEXT, receive_priority)],
            WAITING_FOR_TIME: [MessageHandler(filters.TEXT, receive_time)],
        },
        fallbacks=[CommandHandler('cancel', start_command)],
    )

    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^(📋 لیست وظایف من|📊 آمار عملکرد|🍅 پومودورو \(۲۵ دقیقه\)|📥 خروجی اکسل \(CSV\))$"), handle_main_menu))
    application.add_handler(CallbackQueryHandler(inline_buttons_handler))

    if RENDER_HOSTNAME:
        WEBHOOK_URL = f"https://{RENDER_HOSTNAME}/{TOKEN}"
        application.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=WEBHOOK_URL, url_path=TOKEN, drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    else:
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
