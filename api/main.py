from fastapi import FastAPI, Request
import httpx
import os

app = FastAPI()

# توکن ربات که بعداً در تنظیمات Vercel قرار می‌دهیم
TELEGRAM_BOT_TOKEN = os.getenv(8376133909:AAH2zXLoZOTdxkEebmUioujWtReLIJDlGSQ)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

async def send_message(chat_id: int, text: str):
    """تابع ارسال پیام به کاربر"""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """این نقطه پایانی (Endpoint) پیام‌ها را از تلگرام دریافت می‌کند"""
    update = await request.json()
    
    # بررسی می‌کنیم که آیا پیام متنی ارسال شده است یا خیر
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"]["text"]
        
        # لاجیک اولیه ربات
        if text == "/start":
            reply_text = "سلام! من ربات مدیریت تسک‌های شما هستم. در آینده می‌توانم کارها و تاریخ‌ها را برایت دسته‌بندی کنم."
        else:
            reply_text = f"شما گفتید: {text}\n(این پیام موقت است تا لاجیک دسته‌بندی تسک‌ها را اضافه کنیم)"
            
        await send_message(chat_id, reply_text)
        
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Telegram Bot Backend is Running!"}
