import os
import logging
import sqlite3
import csv
import io
import re
import asyncio
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

# ۳. امنیت: دریافت آیدی ادمین از متغیرهای محیطی
ADMIN_ID = os.environ.get("ADMIN_ID")
ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else None
# ایجاد یک فیلتر سفارشی برای ادمین
admin_filter = filters.User(user_id=ADMIN_ID) if ADMIN_ID else filters.ALL

# ================= Database Setup =================
def init_db():
    # ۵. استفاده از Context Manager برای مدیریت بهینه اتصال دیتابیس
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
                created_at TIMESTAMP
            )
        ''')
        conn.commit()

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

# ================= Database Helpers (Sync methods wrapped for Async) =================
# ۲ و ۵. پیاده‌سازی Context Manager و توابع هم‌گام برای استفاده با asyncio.to_thread
def _add_task_to_db(user_id, text, priority, due_time, category, file_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (user_id, task_text, priority, due_time, category, file_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, text, priority, due_time, category, file_id, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
        return cursor.lastrowid

def _get_pending_tasks(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, task_text, priority, due_time, file_id, category FROM tasks WHERE user_id = ? AND status = 'pending' ORDER BY id DESC", (user_id,))
        return cursor.fetchall()

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

def _get_user_stats(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (user_id,))
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'completed'", (user_id,))
        completed = cursor.fetchone()[0]
        return total, completed, total - completed

def _get_all_tasks_for_export(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, task_text, priority, category, status, created_at, due_time FROM tasks WHERE user_id = ?", (user_id,))
        return cursor.fetchall()

def _get_task_file_id(task_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_id FROM tasks WHERE id = ?", (task_id,))
        res = cursor.fetchone()
        return res[0] if res else None

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

# ۱. بازیابی یادآورها هنگام استارت ربات (Critical Fix)
async def post_init(application: Application):
    logger.info("در حال بازیابی یادآورها از دیتابیس...")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, task_text, due_time, user_id FROM tasks WHERE status = 'pending' AND due_time IS NOT NULL")
        tasks = cursor.fetchall()

    now = datetime.now()
    restored_count = 0
    for task_id, task_text, due_time_str, user_id in tasks:
        try:
            due_time = datetime.strptime(due_time_str, "%Y-%m-%d %H:%M")
            if due_time > now:
                application.job_queue.run_once(
                    send_reminder_callback, 
                    when=due_time, 
                    chat_id=user_id, 
                    data=task_text
                )
                restored_count += 1
        except Exception as e:
            logger.error(f"خطا در بازیابی یادآور تسک {task_id}: {e}")
            
    logger.info(f"تعداد {restored_count} یادآور با موفقیت بازیابی و زمان‌بندی شد.")

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
        # اجرای دیتابیس به صورت غیرهمگام (Async)
        tasks = await asyncio.to_thread(_get_pending_tasks, user_id)
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
        total, completed, pending = await asyncio.to_thread(_get_user_stats, user_id)
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
        tasks = await asyncio.to_thread(_get_all_tasks_for_export, user_id)
        if not tasks:
            await update.message.reply_text("داده‌ای برای خروجی وجود ندارد.")
            return
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Task', 'Priority', 'Category', 'Status', 'Created At', 'Due Time'])
        for row in tasks:
            writer.writerow(row)
        
        output.seek(0)
        byte_output = io.BytesIO(output.getvalue().encode('utf-8-sig'))
        byte_output.name = f"Tasks_Report_{datetime.now().strftime('%Y%m%d')}.csv"
        
        await context.bot.send_document(chat_id=user_id, document=byte_output, caption="📊 فایل گزارش وظایف شما")

async def inline_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('done_') or query.data.startswith('del_'):
        action, task_id_str = query.data.split('_')
        task_id = int(task_id_str)
        
        # ۴. دریافت آیدی فایل برای حفظ دکمه شیشه‌ای پیوست
        file_id = await asyncio.to_thread(_get_task_file_id, task_id)
        reply_markup = None
        if file_id:
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("📎 دریافت فایل پیوست", callback_data=f'file_{file_id}')]])

        if action == 'done':
            await asyncio.to_thread(_update_task_status, task_id, 'completed')
            await query.edit_message_text("🎉 <b>وظیفه با موفقیت تیک خورد!</b>", reply_markup=reply_markup, parse_mode='HTML')
        elif action == 'del':
            await asyncio.to_thread(_delete_task_from_db, task_id)
            await query.edit_message_text("🗑 <b>وظیفه به طور کامل حذف شد.</b>", reply_markup=reply_markup, parse_mode='HTML')
            
    elif query.data.startswith('file_'):
        file_id = query.data.split('file_')[1]
        await context.bot.send_document(chat_id=query.message.chat_id, document=file_id)

# ================= Add Task Conversation =================
async def start_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 <b>عنوان وظیفه جدید را تایپ کنید:</b>\n\n"
        "<i>💡 نکته: می‌توانید یک فایل/عکس ارسال کنید و عنوان را در کپشن بنویسید. همچنین با استفاده از # می‌توانید دسته‌بندی بسازید.</i>", 
        reply_markup=get_cancel_keyboard(), 
        parse_mode='HTML'
    )
    return WAITING_FOR_TASK_TEXT

async def receive_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    
    if message.text == "❌ انصراف":
        await update.message.reply_text("عملیات لغو شد 🔙", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    file_id = None
    if message.document:
        file_id = message.document.file_id
        text = message.caption or "فایل بدون عنوان"
    elif message.photo:
        file_id = message.photo[-1].file_id
        text = message.caption or "عکس بدون عنوان"
    else:
        text = message.text

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
            
            if target_time < now:
                target_time += timedelta(days=1)
                
            due_time_str = target_time.strftime("%Y-%m-%d %H:%M")
            
            context.job_queue.run_once(
                send_reminder_callback, 
                when=target_time, 
                chat_id=user_id, 
                data=task_text
            )
            
        except ValueError:
            await update.message.reply_text("⚠️ فرمت زمان اشتباه است. لطفاً به شکل 14:30 وارد کنید یا رد کنید.")
            return WAITING_FOR_TIME

    # ذخیره در دیتابیس به صورت Async
    await asyncio.to_thread(_add_task_to_db, user_id, task_text, priority, due_time_str, category, file_id)
    
    msg = f"✅ <b>وظیفه با موفقیت ثبت شد:</b>\n📌 {task_text}"
    if due_time_str:
        msg += f"\n⏰ <i>یادآوری در: {due_time_str}</i>"
        
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='HTML')
    
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

    # ثبت post_init برای بازیابی یادآورها
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        # اعمال فیلتر ادمین روی نقاط ورود
        entry_points=[MessageHandler(filters.Regex("^➕ افزودن وظیفه جدید$") & admin_filter, start_add_task)],
        states={
            WAITING_FOR_TASK_TEXT: [MessageHandler((filters.TEXT | filters.Document.ALL | filters.PHOTO) & admin_filter, receive_task_text)],
            WAITING_FOR_PRIORITY: [MessageHandler(filters.TEXT & admin_filter, receive_priority)],
            WAITING_FOR_TIME: [MessageHandler(filters.TEXT & admin_filter, receive_time)],
        },
        fallbacks=[CommandHandler('cancel', start_command)],
    )

    # اعمال فیلتر ادمین روی هندلرها
    application.add_handler(CommandHandler('start', start_command, filters=admin_filter))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^(📋 لیست وظایف من|📊 آمار عملکرد|🍅 پومودورو \(۲۵ دقیقه\)|📥 خروجی اکسل \(CSV\))$") & admin_filter, handle_main_menu))
    application.add_handler(CallbackQueryHandler(inline_buttons_handler))

    if RENDER_HOSTNAME:
        WEBHOOK_URL = f"https://{RENDER_HOSTNAME}/{TOKEN}"
        application.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=WEBHOOK_URL, url_path=TOKEN, drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    else:
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
