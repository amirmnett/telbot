import os
import logging
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task_text TEXT,
            priority TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ================= States for Conversation =================
WAITING_FOR_TASK_TEXT = 1
WAITING_FOR_PRIORITY = 2

# ================= Keyboards =================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ افزودن وظیفه جدید")],
            [KeyboardButton("📋 لیست وظایف من"), KeyboardButton("📊 آمار عملکرد")],
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

# ================= Database Helpers =================
def add_task_to_db(user_id, text, priority):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (user_id, task_text, priority, created_at) VALUES (?, ?, ?, ?)",
        (user_id, text, priority, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    conn.close()

def get_pending_tasks(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, task_text, priority, created_at FROM tasks WHERE user_id = ? AND status = 'pending' ORDER BY id DESC", (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def mark_task_done(task_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
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
        
        text_content = "📋 <b>وظایف در انتظار شما:</b>\n\n"
        inline_kb = []
        
        for task_id, task_text, priority, created_at in tasks:
            icon = "🔴" if priority == 'high' else "🟡" if priority == 'medium' else "🟢"
            time_str = str(created_at).split()[-1] # استخراج ساعت
            
            text_content += f"{icon} <b>{task_text}</b> <i>(⏰ ثبت: {time_str})</i>\n"
            inline_kb.append([InlineKeyboardButton(f"✅ انجام شد: {task_text[:15]}...", callback_data=f'done_{task_id}')])
            
        await update.message.reply_text(text_content, reply_markup=InlineKeyboardMarkup(inline_kb), parse_mode='HTML')

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

async def inline_buttons_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندل کردن دکمه‌های شیشه‌ای انجام وظیفه"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('done_'):
        task_id = int(query.data.split('_')[1])
        mark_task_done(task_id)
        await query.edit_message_text(f"🎉 <b>وظیفه با موفقیت تیک خورد و به لیست انجام‌شده‌ها رفت!</b>", parse_mode='HTML')

# ================= Add Task Conversation =================
async def start_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 <b>عنوان وظیفه جدید را تایپ کنید:</b>", 
        reply_markup=get_cancel_keyboard(), 
        parse_mode='HTML'
    )
    return WAITING_FOR_TASK_TEXT

async def receive_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "❌ انصراف":
        await update.message.reply_text("عملیات لغو شد 🔙", reply_markup=get_main_keyboard())
        return ConversationHandler.END
        
    context.user_data['temp_task'] = text
    await update.message.reply_text(
        "🎚 <b>اولویت این کار چقدر است؟</b>\nاز کیبورد پایین انتخاب کنید:",
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
    priority = priority_map.get(text, "medium")
    
    user_id = update.message.from_user.id
    task_text = context.user_data.get('temp_task', 'بدون عنوان')
    
    add_task_to_db(user_id, task_text, priority)
    
    await update.message.reply_text(
        f"✅ <b>وظیفه ثبت شد:</b>\n📌 {task_text}",
        reply_markup=get_main_keyboard(),
        parse_mode='HTML'
    )
    context.user_data.pop('temp_task', None)
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
            WAITING_FOR_TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_text)],
            WAITING_FOR_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_priority)],
        },
        fallbacks=[CommandHandler('cancel', start_command)],
    )

    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex("^(📋 لیست وظایف من|📊 آمار عملکرد)$"), handle_main_menu))
    application.add_handler(CallbackQueryHandler(inline_buttons_handler))

    if RENDER_HOSTNAME:
        WEBHOOK_URL = f"https://{RENDER_HOSTNAME}/{TOKEN}"
        application.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=WEBHOOK_URL, url_path=TOKEN, drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    else:
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
