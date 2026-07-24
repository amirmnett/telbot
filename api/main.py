from fastapi import FastAPI, Request
import httpx
import os

app = FastAPI()

# دریافت توکن از متغیرهای محیطی Render
TOKEN = os.getenv("8376133909:AAH2zXLoZOTdxkEebmUioujWtReLIJDlGSQ")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"

async def send_message(chat_id: int, text: str):
    """ارسال پیام متنی به کاربر"""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

@app.post("/webhook")
async def webhook(request: Request):
    """دریافت پیام از تلگرام و بازگرداندن همان پیام"""
    update = await request.json()
    
    # بررسی وجود پیام متنی در اطلاعات دریافتی
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        user_text = update["message"]["text"]
        
        # ارسال دقیقاً همان متن دریافت شده به کاربر
        await send_message(chat_id, user_text)
        
    return {"status": "ok"}
