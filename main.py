from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import json
import threading
from datetime import date

from database import (
    init_db, get_or_create_user, save_bzu_record, 
    get_today_records, get_user_record, get_user_limits,
    get_all_users, update_limits
)

# ============ НАСТРОЙКИ ============
TELEGRAM_TOKEN = "ВАШ_ТОКЕН_ОТ_BOTFATHER"
WEBAPP_URL = "https://bzu-production.up.railway.app"

app = FastAPI()

# CORS для разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Раздаем статику
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============ МОДЕЛИ ДАННЫХ ============
class BZUData(BaseModel):
    user_id: int
    protein: float = 0
    fat: float = 0
    carbs: float = 0
    fiber: float = 0
    record_date: Optional[str] = None

class LimitsData(BaseModel):
    user_id: int
    protein_min: float
    protein_max: float
    fat_min: float
    fat_max: float
    carbs_min: float
    carbs_max: float
    fiber_min: float
    fiber_max: float

# ============ API ЭНДПОИНТЫ ============

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    """Получаем или создаем пользователя"""
    user = get_or_create_user(user_id)
    limits = get_user_limits(user_id)
    today_record = get_user_record(user_id)
    
    return {
        "user": user,
        "limits": limits,
        "today_record": today_record or {
            "protein": 0,
            "fat": 0,
            "carbs": 0,
            "fiber": 0
        }
    }

@app.post("/api/save")
async def save_data(data: BZUData):
    """Сохраняем запись БЖУ"""
    try:
        save_bzu_record(
            data.user_id,
            data.protein,
            data.fat,
            data.carbs,
            data.fiber,
            data.record_date
        )
        return {"status": "success", "message": "Данные сохранены"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/today")
async def get_today():
    """Получаем все записи за сегодня"""
    records = get_today_records()
    
    # Добавляем статусы для каждого показателя
    for rec in records:
        # Проверяем, в пределах ли нормы
        rec['protein_status'] = get_status(rec['protein'], rec['protein_min'], rec['protein_max'])
        rec['fat_status'] = get_status(rec['fat'], rec['fat_min'], rec['fat_max'])
        rec['carbs_status'] = get_status(rec['carbs'], rec['carbs_min'], rec['carbs_max'])
        rec['fiber_status'] = get_status(rec['fiber'], rec['fiber_min'], rec['fiber_max'])
        
        # Общий статус
        statuses = [rec['protein_status'], rec['fat_status'], rec['carbs_status'], rec['fiber_status']]
        if all(s == 'good' for s in statuses):
            rec['overall_status'] = 'good'
        elif any(s == 'over' for s in statuses):
            rec['overall_status'] = 'over'
        elif any(s == 'under' for s in statuses):
            rec['overall_status'] = 'under'
        else:
            rec['overall_status'] = 'empty'
    
    return records

def get_status(value, min_val, max_val):
    """Определяем статус показателя"""
    if value == 0:
        return 'empty'
    elif value < min_val:
        return 'under'
    elif value > max_val:
        return 'over'
    else:
        return 'good'

@app.get("/api/users")
async def get_users():
    """Получаем список всех пользователей"""
    return get_all_users()

@app.post("/api/limits")
async def update_limits_endpoint(data: LimitsData):
    """Обновляем лимиты пользователя"""
    try:
        update_limits(
            data.user_id,
            data.protein_min,
            data.protein_max,
            data.fat_min,
            data.fat_max,
            data.carbs_min,
            data.carbs_max,
            data.fiber_min,
            data.fiber_max
        )
        return {"status": "success", "message": "Лимиты обновлены"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ============ ТЕЛЕГРАМ БОТ ============

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляем кнопку с WebApp"""
    keyboard = [[
        InlineKeyboardButton(
            "📊 Открыть дневник БЖУ",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]]
    
    await update.message.reply_text(
        "👋 Привет! Я бот для учета БЖУ.\n\n"
        "📝 Нажми на кнопку ниже, чтобы открыть дневник.\n"
        "Там ты сможешь:\n"
        "✅ Вводить свои показатели\n"
        "📈 Смотреть график сравнения с участниками\n"
        "🎯 Отслеживать выполнение нормы\n\n"
        "📊 Нормы:\n"
        "🍗 Белки: 150-200г\n"
        "🧈 Жиры: 70-80г\n"
        "🍞 Углеводы: 80-100г\n"
        "🥦 Клетчатка: 10-20г",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Команды бота:\n"
        "/start - Открыть главное меню\n"
        "/help - Показать это сообщение\n"
        "/stats - Показать сводку за сегодня в чате\n\n"
        "Для ввода данных используй кнопку 'Открыть дневник БЖУ'"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляем текстовую сводку в чат"""
    records = get_today_records()
    
    if not records or all(r['protein'] == 0 and r['fat'] == 0 and r['carbs'] == 0 and r['fiber'] == 0 for r in records):
        await update.message.reply_text("📭 Сегодня никто не ввел данные. Нажми 'Открыть дневник БЖУ'!")
        return
    
    # Формируем красивое сообщение
    message = "📊 <b>Сводка за сегодня</b>\n\n"
    
    for rec in records:
        name = rec['first_name'] or rec['username'] or f"User {rec['user_id']}"
        
        # Проверяем, вводил ли пользователь что-то
        total = rec['protein'] + rec['fat'] + rec['carbs'] + rec['fiber']
        if total == 0:
            continue
            
        # Эмодзи статуса
        status_emoji = {
            'good': '✅',
            'under': '⬇️',
            'over': '⬆️',
            'empty': '⚪'
        }
            
        message += f"👤 <b>{name}</b>\n"
        message += f"  🍗 Белки: {rec['protein']:.0f}г ({rec['protein_min']:.0f}-{rec['protein_max']:.0f}) {status_emoji.get(rec['protein_status'], '')}\n"
        message += f"  🧈 Жиры: {rec['fat']:.0f}г ({rec['fat_min']:.0f}-{rec['fat_max']:.0f}) {status_emoji.get(rec['fat_status'], '')}\n"
        message += f"  🍞 Углеводы: {rec['carbs']:.0f}г ({rec['carbs_min']:.0f}-{rec['carbs_max']:.0f}) {status_emoji.get(rec['carbs_status'], '')}\n"
        message += f"  🥦 Клетчатка: {rec['fiber']:.0f}г ({rec['fiber_min']:.0f}-{rec['fiber_max']:.0f}) {status_emoji.get(rec['fiber_status'], '')}\n\n"
    
    await update.message.reply_text(message, parse_mode='HTML')

def run_bot():
    """Запускаем Telegram бота в отдельном потоке"""
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("stats", stats_command))
    
    print("🤖 Telegram бот запущен...")
    bot_app.run_polling()

# ============ ЗАПУСК ============

if __name__ == "__main__":
    import os
    
    # ===== ЯВНО СОЗДАЕМ ТАБЛИЦЫ =====
    from database import init_db
    print("🔧 Создаю таблицы...")
    init_db()
    print("✅ Таблицы созданы")
    
    # Инициализируем базу данных
    init_db()
    print("✅ База данных инициализирована")
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Берем порт из переменной окружения (Railway), или 8000 по умолчанию
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Сервер запускается на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
