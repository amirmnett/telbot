import os
import logging
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

# تنظیمات لاگین
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# حافظه موقت برای ذخیره تسک‌ها (در نسخه نهایی به دیتابیس متصل شود)
user_tasks = {}

# تعریف وضعیت‌ها برای ConversationHandler
WAITING_FOR_TASK = 1

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال پیام خوش‌آمدگویی و منوی اصلی"""
    keyboard = [
        [InlineKeyboardButton("➕ افزودن وظیفه جدید", callback_data='add_task')],
        [InlineKeyboardButton("📋 لیست وظایف من", callback_data='list_tasks')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = "سلام! به ربات برنامه‌ریز شخصی خود خوش آمدید. 📅\n\nلطفاً از منوی زیر انتخاب کنید:"
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # 🔴 این خط بسیار مهم است و حالت لودینگ دکمه را متوقف می‌کند
    await query.answer()
    
    data = query.data
    
    if data == 'add_task':
        await query.edit_message_text(text="لطفاً عنوان وظیفه جدید را وارد کنید:")
        return WAITING_FOR_TASK
        
    elif data == 'list_tasks':
        # کدهای مربوط به نمایش لیست
        await query.edit_message_text(text="لیست وظایف شما:")
        return ConversationHandler.END

        
        keyboard = []
        for i, task in enumerate(tasks):
            # دکمه‌ای برای مارک کردن تسک به عنوان انجام شده
            keyboard.append([InlineKeyboardButton(f"✅ انجام شد: {task}", callback_data=f'done_{i}')])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data='main_menu')])
        
        await query.edit_message_text("📋 لیست وظایف فعلی شما (برای حذف روی آن‌ها کلیک کنید):", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    elif query.data.startswith('done_'):
        task_index = int(query.data.split('_')[1])
        tasks = user_tasks.get(user_id, [])
        if 0 <= task_index < len(tasks):
            completed_task = tasks.pop(task_index)
            await query.answer(f"تسک '{completed_task}' با موفقیت انجام و حذف شد!", show_alert=True)
        
        # بازگشت به منوی اصلی پس از انجام کار
        await start_command(update, context)
        return ConversationHandler.END

    elif query.data == 'main_menu':
        await start_command(update, context)
        return ConversationHandler.END

async def receive_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت متن تسک و ذخیره آن"""
    user_id = update.message.from_user.id
    task_text = update.message.text

    if user_id not in user_tasks:
        user_tasks[user_id] = []
    
    user_tasks[user_id].append(task_text)
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data='main_menu')]]
    await update.message.reply_text(
        f"✅ وظیفه با موفقیت ثبت شد:\n«{task_text}»",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """انصراف از افزودن تسک"""
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data='main_menu')]]
    await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

def main():
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    PORT = int(os.environ.get('PORT', '10000'))
    RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if not TOKEN:
        logger.error("توکن ربات در متغیرهای محیطی یافت نشد!")
        return

    application = Application.builder().token(TOKEN).build()

    # تنظیم سیستم مکالمه (Conversation) برای افزودن تسک
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^add_task$')],
        states={
            WAITING_FOR_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    # افزودن هندلرها به اپلیکیشن
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(conv_handler)
    # هندلر برای سایر دکمه‌ها (لیست، انجام تسک، بازگشت)
    application.add_handler(CallbackQueryHandler(button_handler))

    # منطق دیپلوی وب‌هوک و پولینگ
    if RENDER_HOSTNAME:
        # استفاده از توکن در مسیر برای امنیت بیشتر و جلوگیری از تداخل با Health Check های رندر
        WEBHOOK_URL = f"https://{RENDER_HOSTNAME}/{TOKEN}"
        logger.info(f"Starting Webhook on {WEBHOOK_URL} (Port: {PORT})")
        
    application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            url_path=TOKEN,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES  # 👈 این خط اضافه می‌شود
        )
    else:
        logger.info("Starting Polling mode (Local)...")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES  # 👈 این خط اضافه می‌شود
        )

if __name__ == '__main__':
    main()
