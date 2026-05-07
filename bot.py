import os
import logging
import anthropic
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import base64
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

user_listings = {}

PLATFORM_RULES = {
    "shopify": {"title_max": 255, "has_bullets": False, "has_tags": True},
    "amazon": {"title_max": 200, "has_bullets": True, "has_tags": False},
    "etsy": {"title_max": 140, "has_bullets": False, "has_tags": True, "tags_max": 13},
    "ebay": {"title_max": 80, "has_bullets": False, "has_tags": False},
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я KIZIMA® ListBot.\n\n"
        "📸 Отправь фото изделия — я создам листинги для всех платформ.\n\n"
        "Команды:\n"
        "/start — начало\n"
        "/help — помощь"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Как пользоваться:\n\n"
        "1. Отправь фото янтарного изделия\n"
        "2. Выбери платформу\n"
        "3. Редактируй если нужно\n"
        "4. Публикуй в Shopify одной кнопкой\n\n"
        "Поддерживаемые платформы:\n"
        "🛍 Shopify\n"
        "📦 Amazon\n"
        "🎨 Etsy\n"
        "🏪 eBay"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("🔍 Анализирую фото... подожди немного.")
    
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_url = file.file_path
    
    response = requests.get(file_url)
    image_data = base64.b64encode(response.content).decode("utf-8")
    
    prompt = """Ты эксперт по e-commerce для бренда KIZIMA® — единственного производителя изделий из балтийского янтаря в США (Нью-Йорк).

Создай листинги для этого изделия из янтаря для 4 платформ. Отвечай ТОЛЬКО в JSON формате:

{
  "product_name": "название изделия",
  "shopify": {
    "title": "KIZIMA® Made in USA [название] | [описание] (макс 255 символов)",
    "description": "HTML описание с тегами <p>, <ul>, <li>. Упомяни: Made in New York, Baltic amber, luxury gift box включена, American artisans",
    "tags": ["Baltic amber", "Made in USA", "KIZIMA", "New York", "handmade", "luxury gift"]
  },
  "amazon": {
    "title": "KIZIMA® Made in USA [название] — Only USA Manufacturer (макс 200 символов)",
    "bullets": [
      "✅ MADE IN USA — Handcrafted in our New York workshop by American artisans",
      "🌊 AUTHENTIC BALTIC AMBER — Natural Baltic amber, no Chinese materials",
      "🎁 LUXURY GIFT BOX INCLUDED — Ready to gift, premium packaging",
      "⚡ FAST USA SHIPPING — Ships from New York, 2-5 business days",
      "🏆 KIZIMA® REGISTERED BRAND — Only USA manufacturer of Baltic amber products"
    ],
    "description": "Полное HTML описание для Amazon"
  },
  "etsy": {
    "title": "KIZIMA® [название] Baltic Amber Made in USA New York (макс 140 символов)",
    "description": "Описание простым текстом без HTML. Упомяни handmade, Baltic amber, New York, gift box",
    "tags": ["baltic amber", "made in usa", "amber jewelry", "new york", "handmade amber", "luxury gift", "kizima", "amber gift", "american made", "baltic amber gift", "amber necklace", "handcrafted", "amber jewelry box"]
  },
  "ebay": {
    "title": "KIZIMA® Baltic Amber Made in USA [название] (макс 80 символов)",
    "description": "HTML описание для eBay"
  }
}"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )
    
    text = message.content[0].text
    text_clean = text.replace("```json", "").replace("```", "").strip()
    listing = json.loads(text_clean)
    user_listings[user_id] = listing
    
    keyboard = [
        [InlineKeyboardButton("🛍 Shopify", callback_data="show_shopify"),
         InlineKeyboardButton("📦 Amazon", callback_data="show_amazon")],
        [InlineKeyboardButton("🎨 Etsy", callback_data="show_etsy"),
         InlineKeyboardButton("🏪 eBay", callback_data="show_ebay")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Листинги готовы для: *{listing.get('product_name', 'изделие')}*\n\nВыбери платформу для просмотра:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if user_id not in user_listings:
        await query.message.reply_text("❌ Сначала отправь фото изделия.")
        return
    
    listing = user_listings[user_id]
    data = query.data
    
    if data == "show_shopify":
        s = listing["shopify"]
        text = f"🛍 *SHOPIFY*\n\n*Title:*\n{s['title']}\n\n*Tags:*\n{', '.join(s['tags'])}\n\n*Description:*\n{s['description'][:500]}..."
        keyboard = [[InlineKeyboardButton("🚀 Опубликовать в Shopify", callback_data="publish_shopify")]]
        
    elif data == "show_amazon":
        a = listing["amazon"]
        bullets = "\n".join(a["bullets"])
        text = f"📦 *AMAZON*\n\n*Title:*\n{a['title']}\n\n*Bullets:*\n{bullets}"
        keyboard = []
        
    elif data == "show_etsy":
        e = listing["etsy"]
        text = f"🎨 *ETSY*\n\n*Title:*\n{e['title']}\n\n*Tags:*\n{', '.join(e['tags'])}\n\n*Description:*\n{e['description'][:500]}..."
        keyboard = []
        
    elif data == "show_ebay":
        eb = listing["ebay"]
        text = f"🏪 *EBAY*\n\n*Title:*\n{eb['title']}\n\n*Description:*\n{eb['description'][:500]}..."
        keyboard = []
        
    elif data == "publish_shopify":
        await publish_to_shopify(query, listing)
        return
    
    keyboard.append([
        InlineKeyboardButton("🛍 Shopify", callback_data="show_shopify"),
        InlineKeyboardButton("📦 Amazon", callback_data="show_amazon"),
    ])
    keyboard.append([
        InlineKeyboardButton("🎨 Etsy", callback_data="show_etsy"),
        InlineKeyboardButton("🏪 eBay", callback_data="show_ebay"),
    ])
    
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def publish_to_shopify(query, listing):
    s = listing["shopify"]
    
    product_data = {
        "product": {
            "title": s["title"],
            "body_html": s["description"],
            "tags": ", ".join(s["tags"]),
            "status": "draft",
            "vendor": "KIZIMA®"
        }
    }
    
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=product_data, headers=headers)
    
    if response.status_code == 201:
        product = response.json()["product"]
        product_id = product["id"]
        await query.message.reply_text(
            f"✅ Продукт создан в Shopify!\n\n"
            f"ID: {product_id}\n"
            f"Статус: Draft (черновик)\n\n"
            f"Открой Shopify Admin чтобы добавить фото и опубликовать."
        )
    else:
        await query.message.reply_text(f"❌ Ошибка Shopify: {response.status_code}\n{response.text}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.lower()
    
    if user_id not in user_listings:
        await update.message.reply_text("📸 Отправь фото изделия чтобы начать.")
        return
    
    listing = user_listings[user_id]
    
    edit_prompt = f"""Текущий листинг: {json.dumps(listing, ensure_ascii=False)}
    
Пользователь просит: {update.message.text}

Измени только то что просят. Верни ПОЛНЫЙ обновлённый JSON в том же формате."""
    
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": edit_prompt}]
    )
    
    text_resp = message.content[0].text
    text_clean = text_resp.replace("```json", "").replace("```", "").strip()
    updated = json.loads(text_clean)
    user_listings[user_id] = updated
    
    keyboard = [
        [InlineKeyboardButton("🛍 Shopify", callback_data="show_shopify"),
         InlineKeyboardButton("📦 Amazon", callback_data="show_amazon")],
        [InlineKeyboardButton("🎨 Etsy", callback_data="show_etsy"),
         InlineKeyboardButton("🏪 eBay", callback_data="show_ebay")],
    ]
    
    await update.message.reply_text(
        "✅ Листинг обновлён! Выбери платформу для просмотра:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
