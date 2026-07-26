import os
import logging
from telegram.ext import Application
# ... سایر ایمپورت‌های شما ...

# تنظیمات لاگین (اختیاری ولی برای دیباگ در Render مفید است)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def main():
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    # Render پورت را به صورت خودکار در متغیر محیطی PORT قرار می‌دهد
    PORT = int(os.environ.get('PORT', '10000'))
    
    # Render آدرس دامنه شما را به صورت خودکار در این متغیر قرار می‌دهد
    RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if not TOKEN:
        logging.error("توکن ربات در متغیرهای محیطی یافت نشد!")
        return

    application = Application.builder().token(TOKEN).build()

    # ---------------------------------------------------------
    # هندلرهای خود را اینجا اضافه کنید (ConversationHandler و غیره)
    # application.add_handler(...)
    # ---------------------------------------------------------

    # اگر کد روی Render در حال اجرا باشد (دامنه وجود داشته باشد)، از Webhook استفاده می‌کند
    if RENDER_HOSTNAME:
        WEBHOOK_URL = f"https://{RENDER_HOSTNAME}"
        logging.info(f"Starting Webhook on {WEBHOOK_URL} (Port: {PORT})")
        
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            # این مسیر را می‌توانید خالی بگذارید تا تلگرام آپدیت‌ها را به روت بفرستد
            url_path="" 
        )
    # اگر کد را روی سیستم شخصی خودتان (لوکال) اجرا کنید، از Polling استفاده می‌کند
    else:
        logging.info("Starting Polling mode (Local)...")
        application.run_polling()

if __name__ == '__main__':
    main()
