import logging
from datetime import datetime
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Load configuration (use environment variables for sensitive data)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("No Telegram bot token provided. Please set the TELEGRAM_BOT_TOKEN environment variable.")

ADMIN_ROLE = "Admin"

# Database connection
conn = sqlite3.connect('breaks.db', check_same_thread=False)
cursor = conn.cursor()

# Create breaks table if it doesn't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS breaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    fine_paid BOOLEAN DEFAULT 0
)
''')
conn.commit()

# Health check server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_health_check():
    server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
    server.serve_forever()

# Start health check server in a separate thread
health_check_thread = threading.Thread(target=run_health_check)
health_check_thread.daemon = True
health_check_thread.start()

# Telegram bot commands
async def start_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute('SELECT * FROM breaks WHERE user_id = ? AND end_time IS NULL', (user_id,))
    if cursor.fetchone():
        await update.message.reply_text("You are already on a break. Please return first.")
        return

    start_time = datetime.now()
    cursor.execute('INSERT INTO breaks (user_id, start_time) VALUES (?, ?)', (user_id, start_time))
    conn.commit()
    await update.message.reply_text(f"You are going on a break. Please return when you're back.")

async def end_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute('SELECT id, start_time FROM breaks WHERE user_id = ? AND end_time IS NULL', (user_id,))
    break_record = cursor.fetchone()
    if not break_record:
        await update.message.reply_text("You are not currently on a break.")
        return

    break_id, start_time = break_record
    end_time = datetime.now()
    fine_paid = False

    # Calculate if fine is applicable
    if (end_time - datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S.%f')).total_seconds() > 3600:  # 1 hour
        fine_paid = False  # Admin needs to verify

    cursor.execute('UPDATE breaks SET end_time = ?, fine_paid = ? WHERE id = ?', (end_time, fine_paid, break_id))
    conn.commit()
    await update.message.reply_text(f"You have returned from break.")

async def break_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute('SELECT start_time, end_time, fine_paid FROM breaks WHERE user_id = ?', (user_id,))
    breaks = cursor.fetchall()
    if not breaks:
        await update.message.reply_text("No break history found.")
        return

    history_message = "Break History:\n"
    for start, end, fine_paid in breaks:
        history_message += f"Start: {start}, End: {end}, Fine Paid: {'Yes' if fine_paid else 'No'}\n"
    await update.message.reply_text(history_message)

async def verify_late_return(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = context.args[0] if context.args else None
    if not user_id:
        await update.message.reply_text("Please provide a user ID.")
        return

    cursor.execute('UPDATE breaks SET fine_paid = 1 WHERE user_id = ? AND fine_paid = 0', (user_id,))
    conn.commit()
    await update.message.reply_text(f"Late returns for user {user_id} have been verified and fines waived.")

async def break_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute('SELECT user_id, COUNT(*) as breaks, SUM(fine_paid) as fines_paid FROM breaks GROUP BY user_id')
    report = cursor.fetchall()
    report_message = "Break Report:\n"
    for user_id, breaks, fines_paid in report:
        report_message += f"User ID: {user_id}, Breaks: {breaks}, Fines Paid: {fines_paid}\n"
    await update.message.reply_text(report_message)

# Build the bot
application = ApplicationBuilder().token(TOKEN).build()

# Add command handlers
application.add_handler(CommandHandler("break", start_break))
application.add_handler(CommandHandler("return", end_break))
application.add_handler(CommandHandler("history", break_history))
application.add_handler(CommandHandler("verify", verify_late_return))
application.add_handler(CommandHandler("report", break_report))

# Start the bot
application.run_polling()
