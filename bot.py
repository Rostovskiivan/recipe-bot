import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv
import requests

# Загрузка переменных
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("SPOONACULAR_API_KEY")

# Инициализация БД
conn = sqlite3.connect('recipes.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS favorites
                  (user_id INTEGER, recipe_id INTEGER, title TEXT, image_url TEXT, PRIMARY KEY (user_id, recipe_id))''')
conn.commit()

# --- Функции для Spoonacular API ---
def search_recipes(ingredients: list):
    """Поиск рецептов по ингредиентам"""
    url = "https://api.spoonacular.com/recipes/findByIngredients"
    params = {
        "ingredients": ",".join(ingredients),
        "apiKey": API_KEY,
        "number": 5,
        "ignorePantry": True
    }
    response = requests.get(url, params=params).json()
    return response

def get_recipe_details(recipe_id: int):
    """Получение деталей рецепта с фото"""
    url = f"https://api.spoonacular.com/recipes/{recipe_id}/information"
    params = {"apiKey": API_KEY}
    return requests.get(url, params=params).json()

# --- Обработчики Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍🍳 Привет! Я бот-шеф. Отправь мне ингредиенты (через запятую), и я найду рецепты!\n"
        "Пример: курица, рис, лук\n\n"
        "Также доступны команды:\n"
        "/favorites – ваши сохранённые рецепты",
        parse_mode="Markdown"
    )

async def handle_ingredients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ingredients = [x.strip() for x in update.message.text.split(",")]
    recipes = search_recipes(ingredients)
    
    if not recipes:
        await update.message.reply_text("😢 Рецептов не найдено. Попробуйте другие ингредиенты.")
        return
    
    context.user_data["recipes"] = recipes  # Сохраняем для callback
    
    # Создаем кнопки с превью фото
    buttons = []
    for recipe in recipes:
        buttons.append([
            InlineKeyboardButton(
                text=recipe["title"],
                callback_data=f"recipe_{recipe['id']}"
            )
        ])
    
    await update.message.reply_text(
        "🔍 Вот что я нашел:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def show_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    recipe_id = int(query.data.split("_")[1])
    details = get_recipe_details(recipe_id)
    
    # Формируем сообщение с фото
    caption = (
        f"🍲 {details['title']}\n\n"
        f"⏳ Время готовки: {details['readyInMinutes']} мин\n"
        f"📝 Ингредиенты:\n" + "\n".join([f"- {ing['original']}" for ing in details['extendedIngredients']]) + "\n\n"
        f"🔪 Инструкции:\n{details['instructions'] or 'Инструкции не указаны.'}"
    )
    
    # Кнопки "Сохранить" и "Назад"
    keyboard = [
        [InlineKeyboardButton("💾 Сохранить", callback_data=f"save_{recipe_id}")],
        [InlineKeyboardButton("⬅ Назад", callback_data="back_to_list")]
    ]
    
    # Отправляем фото + текст
    if details.get("image"):
        await query.message.reply_photo(
            photo=details["image"],
            caption=caption,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.message.reply_text(caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def save_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    recipe_id = int(query.data.split("_")[1])
    
    # Находим рецепт в кеше
    recipe = next((r for r in context.user_data["recipes"] if r["id"] == recipe_id), None)
    if not recipe:
        await query.answer("Ошибка: рецепт не найден.")
        return
    
    # Сохраняем в БД (с фото)
    cursor.execute(
        "INSERT OR IGNORE INTO favorites VALUES (?, ?, ?, ?)",
        (user_id, recipe_id, recipe["title"], recipe.get("image"))
    )
    conn.commit()
    await query.answer("✅ Рецепт сохранён в избранное!")

async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает сохранённые рецепты"""
    user_id = update.effective_user.id
    cursor.execute("SELECT recipe_id, title, image_url FROM favorites WHERE user_id = ?", (user_id,))
    favorites = cursor.fetchall()
    
    if not favorites:
        await update.message.reply_text("😢 У вас нет сохранённых рецептов.")
        return
    
    # Отправляем список с кнопками
    buttons = []
    for fav in favorites:
        recipe_id, title, image_url = fav
        buttons.append([InlineKeyboardButton(title, callback_data=f"fav_{recipe_id}")])
    
    await update.message.reply_text(
        "⭐ Ваши сохранённые рецепты:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def show_favorite_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает один избранный рецепт"""
    query = update.callback_query
    recipe_id = int(query.data.split("_")[1])
    
    # Получаем данные из БД
    cursor.execute("SELECT title, image_url FROM favorites WHERE recipe_id = ?", (recipe_id,))
    title, image_url = cursor.fetchone()
    
    # Получаем актуальные детали через API
    details = get_recipe_details(recipe_id)
    
    # Формируем сообщение
    caption = (
        f"⭐ {title}\n\n"
        f"⏳ Время готовки: {details['readyInMinutes']} мин\n"
        f"📝 Ингредиенты:\n" + "\n".join([f"- {ing['original']}" for ing in details['extendedIngredients']]) + "\n\n"
        f"🔪 Инструкции:\n{details['instructions'] or 'Инструкции не указаны.'}"
    )
    
    # Кнопка "Удалить"
    keyboard = [[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{recipe_id}")]]
    
    # Отправляем фото (если есть)
    if image_url:
        await query.message.reply_photo(
            photo=image_url,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.message.reply_text(caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет рецепт из избранного"""
    query = update.callback_query
    user_id = query.from_user.id
    recipe_id = int(query.data.split("_")[1])
    
    cursor.execute("DELETE FROM favorites WHERE user_id = ? AND recipe_id = ?", (user_id, recipe_id))
    conn.commit()
    await query.answer("🗑 Рецепт удалён!")
    await query.message.delete()

# --- Запуск ---
if _name_ == "_main_":
    app = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("favorites", show_favorites))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ingredients))
    
    # Обработчики callback-кнопок
    app.add_handler(CallbackQueryHandler(show_recipe, pattern="^recipe_"))
    app.add_handler(CallbackQueryHandler(save_recipe, pattern="^save_"))
    app.add_handler(CallbackQueryHandler(show_favorite_recipe, pattern="^fav_"))
    app.add_handler(CallbackQueryHandler(delete_favorite, pattern="^delete_"))
    app.add_handler(CallbackQueryHandler(handle_ingredients, pattern="^back_to_list"))
    
    print("Бот запущен! 🚀")
    app.run_polling()
