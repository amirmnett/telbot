# استفاده از تصویر پایه پایتون
FROM python:3.11-slim

# تنظیم دایرکتوری کاری
WORKDIR /app

# نصب ffmpeg و پیش‌نیازهای سیستمی
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# کپی کردن فایل نیازمندی‌ها و نصب آن‌ها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کردن کل کدهای پروژه
COPY . .

# اجرای ربات
CMD ["python", "main.py"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
