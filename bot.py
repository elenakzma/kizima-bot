import os
import logging
import anthropic
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import base64
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
user_listings = {}

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', 10000), HealthHandler)
    server.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я KIZIMA ListBot.\n\n"
        "Отправь фото изделия - создам листинги для всех платформ.\n\n"
        "/start - начало\n"
        "/help - помощь"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Как пользоваться:\n\n"
        "1. Отправь фото янтарного изделия\n"
        "2. Выбери платформу\n"
        "3. Редактируй если нужно\n"
        "4. Публикуй в Shopify\n\n"
        "Платформы: Shopify, Amazon, Etsy, eBay"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("Анализирую фото... подожди.")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    response = requests.get(file.file_path)
    image_data = base64.b64encode(response.content).decode("utf-8")
    prompt = """Ты эксперт по e-commerce для бренда KIZIMA - производителя изделий из балтийского янтаря в США.

Создай листинги для 4 платформ. Отвечай ТОЛЬКО в JSON без markdown блоков:

{"product_name": "название", "shopify": {"title": "KIZIMA Made in USA название макс 255 символов", "description": "<p>HTML описание. Упомяни Made in New York Baltic amber luxury gift box American artisans</p>", "tags": ["Baltic amber", "Made in USA", "KIZIMA", "New York", "handmade", "luxury gift"]}, "amazon": {"title": "KIZIMA Made in USA название Only USA Manufacturer макс 200 символов", "bullets": ["MADE IN USA Handcrafted in New York by American artisans", "AUTHENTIC BALTIC AMBER Natural Baltic amber no Chinese materials", "LUXURY GIFT BOX INCLUDED Ready to gift premium packaging", "FAST USA SHIPPING Ships from New York 2-5 business days", "KIZIMA REGISTERED BRAND Only USA manufacturer of Baltic amber products"], "description": "<p>HTML описание для Amazon</p>"}, "etsy": {"title": "KIZIMA Baltic Amber Made in USA New York название макс 140 символов", "description": "Описание простым текстом. handmade Baltic amber New York gift box", "tags": ["baltic amber", "made in usa", "amber jewelry", "new york", "handmade amber", "luxury gift", "kizima", "amber gift", "american made", "baltic amber gift", "amber necklace", "handcrafted", "amber box"]}, "ebay": {"title": "KIZIMA Baltic Amber Made in USA название макс 80 символов", "description": "<p>HTML описание для eBay</p>"}}"""
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                {"type": "text", "text": prompt}
            ]
        }]
    )
    text = message.content[0].text.strip()
    listing = json.loads(text)
    user_listings[user_id] = listing
    keyboard = [
        [InlineKeyboardButton("Shopify", callback_data="show_shopify"),
         InlineKeyboardButton("Amazon", callback_data="show_amazon")],
        [InlineKeyboardButton("Etsy", callback_data="show_etsy"),
         InlineKeyboardButton("eBay", callback_data="show_ebay")],
    ]
    await update.message.reply_text(
        "Листинги готовы: " + listing.get("product_name", "изделие") + "\n\nВыбери платформу:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id not in user_listings:
        await query.message.reply_text("Сначала отправь фото изделия.")
        return
    listing = user_listings[user_id]
    data = query.data
    keyboard = [
        [InlineKeyboardButton("Shopify", callback_data="show_shopify"),
         InlineKeyboardButton("Amazon", callback_data="show_amazon")],
        [InlineKeyboardButton("Etsy", callback_data="show_etsy"),
         InlineKeyboardButton("eBay", callback_data="show_ebay")],
    ]
    text = ""
    if data == "show_shopify":
        s = listing["shopify"]
        text = "SHOPIFY\n\nTitle:\n" + s["title"] + "\n\nTags:\n" + ", ".join(s["tags"]) + "\n\nDescription:\n" + s["description"][:400]
        keyboard.append([InlineKeyboardButton("Опубликовать в Shopify", callback_data="publish_shopify")])
    elif data == "show_amazon":
        a = listing["amazon"]
        bullets = "\n".join(a["bullets"])
        text = "AMAZON\n\nTitle:\n" + a["title"] + "\n\nBullets:\n" + bullets
    elif data == "show_etsy":
        e = listing["etsy"]
        text = "ETSY\n\nTitle:\n" + e["title"] + "\n\nTags:\n" + ", ".join(e["tags"]) + "\n\nDescription:\n" + e["description"][:400]
    elif data == "show_ebay":
        eb = listing["ebay"]
        text = "EBAY\n\nTitle:\n" + eb["title"] + "\n\nDescription:\n" + eb["description"][:400]
    elif data == "publish_shopify":
        await publish_to_shopify(query, listing)
        return
    else:
        return
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def publish_to_shopify(query, listing):
    s = listing["shopify"]
    product_data = {
        "product": {
            "title": s["title"],
            "body_html": s["description"],
            "tags": ", ".join(s["tags"]),
            "status": "draft",
            "vendor": "KIZIMA"
        }
    }
    url = "https://" + SHOPIFY_STORE + "/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    response = requests.post(url, json=product_data, headers=headers)
    if response.status_code == 201:
        product = response.json()["product"]
        await query.message.reply_text("Продукт создан в Shopify!\n\nID: " + str(product["id"]) + "\nСтатус: Draft")
    else:
        await query.message.reply_text("Ошибка Shopify: " + str(response.status_code))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_listings:
        await update.message.reply_text("Отправь фото изделия чтобы начать.")
        return
    listing = user_listings[user_id]
    edit_prompt = "Текущий листинг: " + json.dumps(listing, ensure_ascii=False) + "\n\nПользователь просит: " + update.message.text + "\n\nИзмени только то что просят. Верни ПОЛНЫЙ обновлённый JSON без markdown."
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": edit_prompt}]
    )
    text = message.content[0].text.strip()
    updated = json.loads(text)
    user_listings[user_id] = updated
    keyboard = [
        [InlineKeyboardButton("Shopify", callback_data="show_shopify"),
         InlineKeyboardButton("Amazon", callback_data="show_amazon")],
        [InlineKeyboardButton("Etsy", callback_data="show_etsy"),
         InlineKeyboardButton("eBay", callback_data="show_ebay")],
    ]
    await update.message.reply_text("Листинг обновлён! Выбери платформу:", reply_markup=InlineKeyboardMarkup(keyboard))

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
