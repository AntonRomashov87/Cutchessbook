import os
import logging
import asyncio
import aiohttp
import random
import json
import re
import requests
import fitz  # PyMuPDF
import schedule
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask, request

# =======================
# ===== Логування =======
# =======================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =======================
# ===== Flask ===========
# =======================
app = Flask(__name__)

# =======================
# ===== Змінні ==========
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # наприклад "-1001234567890"
TRIGGER_SECRET = os.getenv("TRIGGER_SECRET", "mysecret")

PDF_URL = os.getenv("PDF_URL")
PDF_FILE = "chess_book.pdf"
PDF_OUTPUT_FOLDER = "pdf_pages"
PDF_INDEX_FILE = "last_pdf_page.txt"

PUZZLES_URL = "https://raw.githubusercontent.com/AntonRomashov87/Chess_puzzles/main/puzzles.json"

PTB_APP = None

# =======================
# ===== Функції =========
# =======================
def escape_markdown_v2(text: str) -> str:
    escape_chars = r"[_*\[\]()~`>#\+\-=|{}.!]"
    return re.sub(f'({escape_chars})', r'\\\1', text)

def get_keyboard(state: str = "start", puzzle_index: int = None):
    if state == "puzzle_sent":
        keyboard = [
            [InlineKeyboardButton("💡 Показати розв'язок", callback_data=f"sol_{puzzle_index}")],
            [InlineKeyboardButton("♟️ Нова задача", callback_data="new_puzzle")]
        ]
    else:
        keyboard = [[InlineKeyboardButton("♟️ Отримати задачу", callback_data="new_puzzle")]]
    return InlineKeyboardMarkup(keyboard)

async def load_puzzles() -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PUZZLES_URL) as resp:
                resp.raise_for_status()
                data = await resp.json()
                if isinstance(data, list):
                    logger.info(f"Завантажено {len(data)} задач")
                    return data
                else:
                    logger.error("JSON має неправильну структуру.")
                    return []
    except Exception as e:
        logger.error(f"Помилка при завантаженні puzzles.json: {e}")
        return []

# =======================
# ===== Команди бота =====
# =======================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        escape_markdown_v2("Привіт! Я шаховий бот 🤖♟\nНатисни кнопку, щоб отримати свою першу задачу:"),
        reply_markup=get_keyboard(state="start"),
        parse_mode='MarkdownV2'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    puzzles_list = context.bot_data.get('puzzles', [])

    if action == "new_puzzle":
        if not puzzles_list:
            await query.edit_message_text(
                text=escape_markdown_v2("⚠️ Не вдалося завантажити задачі. Спробуйте пізніше."),
                reply_markup=get_keyboard(state="start"), parse_mode='MarkdownV2'
            )
            return
        puzzle_index, puzzle = random.choice(list(enumerate(puzzles_list)))
        title = escape_markdown_v2(puzzle.get('title', 'Задача'))
        url = escape_markdown_v2(puzzle.get('url', ''))
        msg = f"♟️ *{title}*\n{url}"
        await query.edit_message_text(
            text=msg, reply_markup=get_keyboard(state="puzzle_sent", puzzle_index=puzzle_index), parse_mode='MarkdownV2'
        )
    elif action.startswith("sol_"):
        try:
            puzzle_index = int(action.split("_")[1])
            puzzle = puzzles_list[puzzle_index]
            title = escape_markdown_v2(puzzle.get('title', 'Задача'))
            url = escape_markdown_v2(puzzle.get('url', ''))
            solution = escape_markdown_v2(puzzle.get('solution', 'Розв\'язок не знайдено.'))
            msg = f"♟️ *{title}*\n{url}\n\n💡 *Розв'язок:* {solution}"
            await query.edit_message_text(
                text=msg, reply_markup=get_keyboard(state="start"), parse_mode='MarkdownV2'
            )
        except (IndexError, ValueError):
            await query.edit_message_text(
                text=escape_markdown_v2("⚠️ Помилка: не вдалося знайти цю задачу. Будь ласка, отримайте нову."),
                reply_markup=get_keyboard(state="start"), parse_mode='MarkdownV2'
            )

async def send_puzzle_now(chat_id: str):
    if not PTB_APP:
        logger.error("Бот не ініціалізований для відправки задачі.")
        return
    puzzles_list = PTB_APP.bot_data.get('puzzles', [])
    if not puzzles_list:
        logger.error("Список задач порожній, не можу відправити.")
        return
    puzzle = random.choice(puzzles_list)
    title = escape_markdown_v2(puzzle.get('title', 'Задача'))
    url = escape_markdown_v2(puzzle.get('url', ''))
    msg = f"♟️ *Щоденна задача*\n\n*{title}*\n{url}"
    try:
        await PTB_APP.bot.send_message(chat_id=chat_id, text=msg, parse_mode='MarkdownV2')
        logger.info(f"Задачу успішно відправлено в чат {chat_id}")
    except Exception as e:
        logger.error(f"Не вдалося відправити задачу в чат {chat_id}: {e}")

# =======================
# ===== PDF ============
# =======================
async def download_and_convert_pdf():
    os.makedirs(PDF_OUTPUT_FOLDER, exist_ok=True)
    if not os.path.exists(PDF_FILE):
        r = requests.get(PDF_URL)
        with open(PDF_FILE, "wb") as f:
            f.write(r.content)
        logger.info("✅ PDF завантажено")
    if not os.listdir(PDF_OUTPUT_FOLDER):
        doc = fitz.open(PDF_FILE)
        for i in range(len(doc)):
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            pix.save(f"{PDF_OUTPUT_FOLDER}/page_{i+1}.png")
        logger.info(f"✅ Конвертовано {len(doc)} сторінок PDF")

def get_last_index(file_name):
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            return int(f.read())
    return -1

def save_last_index(file_name, i):
    with open(file_name, "w") as f:
        f.write(str(i))

async def send_next_page(chat_id: str):
    if not PTB_APP:
        logger.error("Бот не ініціалізований")
        return
    pages = sorted(os.listdir(PDF_OUTPUT_FOLDER))
    if not pages:
        logger.error("Сторінки не знайдено")
        return
    last = get_last_index(PDF_INDEX_FILE)
    next_index = last + 1
    if next_index < len(pages):
        file_path = os.path.join(PDF_OUTPUT_FOLDER, pages[next_index])
        caption = f"📖 Сторінка {next_index+1}"
        try:
            await PTB_APP.bot.send_photo(chat_id=chat_id, photo=open(file_path, "rb"), caption=caption)
            save_last_index(PDF_INDEX_FILE, next_index)
            logger.info(f"✅ Опубліковано сторінку {next_index+1}")
        except Exception as e:
            logger.error(f"Не вдалося відправити сторінку: {e}")
    else:
        logger.info("✅ Усі сторінки вже опубліковані")

# =======================
# ===== Планувальник =====
# =======================
def schedule_pages():
    schedule.every().tuesday.at("10:00").do(lambda: asyncio.create_task(send_next_page(CHAT_ID)))
    schedule.every().thursday.at("10:00").do(lambda: asyncio.create_task(send_next_page(CHAT_ID)))
    schedule.every().saturday.at("10:00").do(lambda: asyncio.create_task(send_next_page(CHAT_ID)))
    logger.info("⏳ Планувальник сторінок запущено")

async def run_schedule():
    while True:
        schedule.run_pending()
        await asyncio.sleep(30)

# =======================
# ===== Flask Routes =====
# =======================
@app.route("/webhook", methods=["POST"])
async def webhook():
    if PTB_APP:
        try:
            update_data = request.get_json()
            update = Update.de_json(update_data, PTB_APP.bot)
            await PTB_APP.process_update(update)
            return '', 200
        except Exception as e:
            logger.error(f"Помилка при обробці оновлення: {e}")
            return 'Error processing update', 500
    return 'Bot not initialized', 500

@app.route("/", methods=["GET"])
def index():
    return "Шаховий бот працює через Webhook!", 200

@app.route("/trigger-puzzle/<secret>", methods=["POST"])
async def trigger_puzzle_sending(secret: str):
    if secret != TRIGGER_SECRET:
        return "Invalid secret", 403
    asyncio.create_task(send_puzzle_now(CHAT_ID))
    asyncio.create_task(send_next_page(CHAT_ID))
    logger.info("Ручна відправка сторінки та задачі активована")
    return "Triggered", 200

# =======================
# ===== Setup Bot =======
# =======================
async def setup_bot():
    global PTB_APP
    PTB_APP = Application.builder().token(BOT_TOKEN).build()
    puzzles_data = await load_puzzles()
    PTB_APP.bot_data['puzzles'] = puzzles_data
    await PTB_APP.initialize()
    PTB_APP.add_handler(CommandHandler("start", start_command))
    PTB_APP.add_handler(CallbackQueryHandler(button_handler))
    await download_and_convert_pdf()
    schedule_pages()
    asyncio.create_task(run_schedule())

    # Вебхук
    webhook_url = os.getenv("PUBLIC_URL")
    if webhook_url:
        try:
            await PTB_APP.bot.set_webhook(f"{webhook_url}/webhook", drop_pending_updates=True)
            logger.info(f"Webhook встановлено: {webhook_url}/webhook")
        except Exception as e:
            logger.error(f"Помилка встановлення webhook: {e}")

if __name__ == "__main__":
    asyncio.run(setup_bot())
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
