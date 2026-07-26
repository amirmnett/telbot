import os
import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ================= Configuration & Logging =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= Database Setup =================
DB_NAME = "planner_bot.db"

def init_db():
    """ایجاد دیتابیس و جداول در صورت عدم وجود"""
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

# ================= Database Helpers =================
def add_task_to_db(user_id, text, priority):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (user_id, task_text, priority, created_at) VALUES (?, ?, ?, ?)",
        (user_id, text, priority, datetime.now())
    )
    conn.commit()
    conn.close()

def get_pending_tasks(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, task_text, priority FROM tasks WHERE user_id = ? AND status = 'pending'", (user_id,))
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
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش منوی اصلی ربات"""
    keyboard = [
        [InlineKeyboardButton("➕ افزودن وظیفه جدید", callback_data='add_task')],
        [InlineKeyboardButton("📋 لیست وظایف من", callback_data='list_tasks')],
        [InlineKeyboardButton("📊 آمار عملکرد من", callback_data='show_stats')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "👋 <b>سلام! به ربات برنامه‌ریز شخصی خود خوش آمدید.</b>\n\n"
        "این ربات به شما کمک می‌کند کارهای روزمره خود را به صورت ساختاریافته مدیریت کنید. 🎯\n\n"
        "👇 <i>لطفاً از منوی زیر یک گزینه را انتخاب کنید:</i>"
    )
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت کلیک روی دکمه‌های شیشه‌ای"""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    await query.answer() # پایان حالت Loading
    
    if data == 'add_task':
        cancel_keyboard = [[InlineKeyboardButton("🔙 انصراف", callback_data='main_menu')]]
        await query.edit_message_text(
            "📝 <b>لطفاً عنوان وظیفه جدید خود را تایپ کنید و بفرستید:</b>",
            reply_markup=InlineKeyboardMarkup(cancel_keyboard),
            parse_mode='HTML'
        )
        return WAITING_FOR_TASK_TEXT
        
    elif data == 'list_tasks':
        tasks = get_pending_tasks(user_id)
        
        if not tasks:
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')]]
            await query.edit_message_text("📭 <b>لیست وظایف شما خالی است!</b>\nمی‌توانید استراحت کنید.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return ConversationHandler.END

        keyboard = []
        text_content = "📋 <b>لیست وظایف فعلی شما:</b>\n(برای انجام شدن هر تسک روی دکمه آن کلیک کنید)\n\n"
        
        for task_id, task_text, priority in tasks:
            icon = "🔴" if priority == 'high' else "🟡" if priority == 'medium' else "🟢"
            keyboard.append([InlineKeyboardButton(f"✅ انجام: {task_text[:20]}...", callback_data=f'done_{task_id}')])
            text_content += f"{icon} <b>{task_text}</b>\n"
            
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')])
        
        await query.edit_message_text(text_content, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ConversationHandler.END

    elif data == 'show_stats':
        total, completed, pending = get_user_stats(user_id)
        stats_text = (
            "📊 <b>آمار عملکرد شما تا این لحظه:</b>\n\n"
            f"🔹 <b>کل وظایف ثبت شده:</b> {total}\n"
            f"✅ <b>وظایف انجام شده:</b> {completed}\n"
            f"⏳ <b>وظایف در انتظار:</b> {pending}\n\n"
            "<i>به برنامه‌ریزی ادامه بده! 🚀</i>"
        )
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')]]
        await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ConversationHandler.END

    elif data.startswith('done_'):
        task_id = int(data.split('_')[1])
        mark_task_done(task_id)
        await query.answer("🎉 عالی! این وظیفه با موفقیت انجام شد.", show_alert=True)
        # فراخوانی مجدد لیست برای رفرش شدن صفحه
        query.data = 'list_tasks'
        await button_handler(update, context)
        return ConversationHandler.END

    elif data == 'main_menu':
        await start_command(update, context)
        return ConversationHandler.END

async def receive_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت متن و درخواست اولویت"""
    context.user_data['temp_task'] = update.message.text
    
    keyboard = [
        [
            InlineKeyboardButton("🔴 بالا", callback_data='pri_high'),
            InlineKeyboardButton("🟡 متوسط", callback_data='pri_medium'),
            InlineKeyboardButton("🟢 پایین", callback_data='pri_low')
        ],
        [InlineKeyboardButton("🔙 انصراف", callback_data='main_menu')]
    ]
    
    await update.message.reply_text(
        "🎚 <b>لطفاً میزان اهمیت و اولویت این وظیفه را مشخص کنید:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return WAITING_FOR_PRIORITY

async def receive_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت اولویت، ذخیره در دیتابیس و پایان عملیات"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'main_menu':
        await start_command(update, context)
        return ConversationHandler.END
        
    priority_map = {'pri_high': 'high', 'pri_medium': 'medium', 'pri_low': 'low'}
    priority = priority_map.get(query.data, 'medium')
    
    user_id = query.from_user.id
    task_text = context.user_data.get('temp_task', 'بدون عنوان')
    
    add_task_to_db(user_id, task_text, priority)
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data='main_menu')]]
    await query.edit_message_text(
        f"✅ <b>وظیفه با موفقیت ثبت شد!</b>\n\n📌 عنوان: {task_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    
    context.user_data.pop('temp_task', None)
    return ConversationHandler.END

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """انصراف کلی با کامند /cancel"""
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data='main_menu')]]
    await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

# ================= Main Execution =================
def main():
    init_db() # آماده‌سازی دیتابیس در شروع برنامه
    
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    PORT = int(os.environ.get('PORT', '10000'))
    RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if not TOKEN:
        logger.error("توکن ربات در متغیرهای محیطی یافت نشد!")
        return

    application = Application.builder().token(TOKEN).build()

    # سیستم فرم‌ساز برای افزودن وظیفه
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^add_task$')],
        states={
            WAITING_FOR_TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_text)],
            WAITING_FOR_PRIORITY: [CallbackQueryHandler(receive_priority, pattern='^pri_.*|^main_menu$')],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)],
        allow_reentry=True
    )

    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    if RENDER_HOSTNAME:
        WEBHOOK_URL = f"https://{RENDER_HOSTNAME}/{TOKEN}"
        logger.info(f"Starting Webhook on {WEBHOOK_URL}")
        
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            url_path=TOKEN,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    else:
        logger.info("Starting Polling mode (Local)...")
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
