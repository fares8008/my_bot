from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, CallbackContext
import sqlite3
import re

# إعداد تطبيق Flask
app = Flask(__name__)

# إنشاء أو فتح قاعدة البيانات
conn = sqlite3.connect('deposits.db', check_same_thread=False)
cursor = conn.cursor()

# إنشاء جدول العمليات
cursor.execute('''
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'unused',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# إنشاء جدول تتبع المحاولات
cursor.execute('''
CREATE TABLE IF NOT EXISTS user_attempts (
    user_id TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()

# API لاستقبال الرسائل
@app.route('/receive_sms', methods=['POST'])
def receive_sms():
    data = request.json
    transaction_message = data.get('message', '')

    # استخراج المعلومات من الرسالة
    match = re.search(r'تم استلام مبلغ (\d+) ل\.س بنجاح\. رقم العملية هو (\d+)', transaction_message)
    if match:
        amount = int(match.group(1))
        transaction_id = match.group(2)

        # حفظ في قاعدة البيانات
        try:
            cursor.execute('INSERT INTO transactions (transaction_id, amount) VALUES (?, ?)', 
                           (transaction_id, amount))
            conn.commit()
            response = {"status": "success", "message": "Transaction saved."}
        except sqlite3.IntegrityError:
            response = {"status": "error", "message": "Transaction already exists."}
    else:
        response = {"status": "error", "message": "Invalid message format."}

    return jsonify(response)

# تحقق العملية
def check_transaction(user_id, transaction_id, amount):
    # تحقق من المحاولات
    cursor.execute('SELECT attempts FROM user_attempts WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result and result[0] >= 10:
        return "blocked"

    # تحقق من العملية
    cursor.execute('SELECT * FROM transactions WHERE transaction_id = ? AND amount = ? AND status = "unused"', 
                   (transaction_id, amount))
    transaction = cursor.fetchone()

    if transaction:
        # تحديث حالة العملية
        cursor.execute('UPDATE transactions SET status = "used" WHERE transaction_id = ?', (transaction_id,))
        conn.commit()
        return "success"
    else:
        # زيادة عدد المحاولات
        cursor.execute('INSERT OR IGNORE INTO user_attempts (user_id, attempts) VALUES (?, 0)', (user_id,))
        cursor.execute('UPDATE user_attempts SET attempts = attempts + 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        return "failure"

# إعداد بوت Telegram
def start(update: Update, context: CallbackContext):
    update.message.reply_text("مرحبًا! الرجاء إدخال رقم العملية والمبلغ بهذا التنسيق:\nرقم العملية, المبلغ")

def handle_message(update: Update, context: CallbackContext):
    user_id = str(update.message.chat_id)
    text = update.message.text

    try:
        # تحليل المدخلات
        transaction_id, amount = text.split(',')
        amount = int(amount.strip())

        # تحقق العملية
        result = check_transaction(user_id, transaction_id.strip(), amount)
        if result == "success":
            update.message.reply_text("تم تحويل النقاط بنجاح!")
        elif result == "failure":
            update.message.reply_text("البيانات غير صحيحة. حاول مرة أخرى.")
        elif result == "blocked":
            update.message.reply_text("لقد تجاوزت عدد المحاولات المسموح بها لهذا اليوم.")
    except:
        update.message.reply_text("صيغة غير صحيحة. يرجى إرسال البيانات بالتنسيق المطلوب.")

# بدء Telegram Bot
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
updater = Updater(TELEGRAM_TOKEN)
dispatcher = updater.dispatcher

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(filters.text & ~filters.command, handle_message))

# تشغيل Flask و Telegram
def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    from threading import Thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    updater.start_polling()
    updater.idle()
