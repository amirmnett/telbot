import logging
import os
from datetime import timedelta
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

# تنظیمات لاگین برای عیب‌یابی
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# تعریف وضعیت‌های مربوط به ConversationHandler
ASK_TITLE, ASK_TIME = range(2)

# یک دیکشنری موقت برای ذخیره رویدادها (در نسخه نهایی حتماً از دیتابیس استفاده کنید)
user_events = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام خوش‌آمدگویی و منوی اصلی"""
    keyboard = [
        [InlineKeyboardButton("➕ افزودن رویداد جدید", callback_data="add_event")],
        [InlineKeyboardButton("📅 مشاهده رویدادهای من", callback_data="view_events")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("سلام! به ربات پلنر خوش آمدید. لطفاً یک گزینه را انتخاب کنید:", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text("لطفاً یک گزینه را انتخاب کنید:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت کلیک روی دکمه‌های شیشه‌ای"""
    query = update.callback_query
    await query.answer()

    if query.data == "add_event":
        await query.edit_message_text("لطفاً عنوان رویداد خود را وارد کنید:")
        return ASK_TITLE
    elif query.data == "view_events":
        user_id = query.from_user.id
        events = user_events.get(user_id, [])
        if not events:
            await query.edit_message_text("شما هیچ رویدادی ثبت نکرده‌اید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data="back_home")]]))
        else:
            text = "رویدادهای شما:\n\n"
            for i, event in enumerate(events, 1):
                text += f"{i}. {event['title']}\n"
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data="back_home")]]))
    elif query.data == "back_home":
        await start(update, context)
        
    return ConversationHandler.END

async def ask_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت عنوان رویداد و درخواست زمان"""
    context.user_data['event_title'] = update.message.text
    await update.message.reply_text("عالی! حالا بگویید چند دقیقه دیگر این رویداد یادآوری شود؟ (مثلاً عدد 5 را برای ۵ دقیقه دیگر وارد کنید)")
    return ASK_TIME

async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت زمان، ذخیره رویداد و تنظیم یادآور"""
    try:
        minutes = int(update.message.text)
        title = context.user_data['event_title']
        user_id = update.message.from_user.id
        
        # ذخیره در حافظه موقت
        if user_id not in user_events:
            user_events[user_id] = []
        user_events[user_id].append({"title": title})

        # تنظیم یادآور (JobQueue)
        chat_id = update.message.chat_id
        context.job_queue.run_once(send_reminder, timedelta(minutes=minutes), chat_id=chat_id, data=title)

        await update.message.reply_text(
            f"✅ رویداد «{title}» با موفقیت ثبت شد و {minutes} دقیقه دیگر به شما یادآوری می‌شود.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت به منو", callback_data="back_home")]])
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("لطفاً فقط یک عدد صحیح برای دقایق وارد کنید.")
        return ASK_TIME

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """تابع ارسال پیام یادآور"""
    job = context.job
    await context.bot.send_message(job.chat_id, text=f"🔔 یادآوری رویداد:\n\nزمان رویداد «{job.data}» فرا رسیده است!")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو عملیات جاری"""
    await update.message.reply_text("عملیات لغو شد.")
    return ConversationHandler.END

def main():
    # توکن ربات خود را اینجا قرار دهید
 TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    # ساخت اپلیکیشن و فعال‌سازی JobQueue
    application = Application.builder().token(TOKEN).build()

    # تنظیمات مکالمه برای گرفتن اطلاعات رویداد
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^add_event$")],
        states={
            ASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_title)],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # افزودن هندلرها به اپلیکیشن
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    # اجرای ربات (Polling)
    application.run_polling()

if __name__ == "__main__":
    main()

