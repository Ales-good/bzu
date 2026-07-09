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
import os
import asyncio

from database_mysql import (
    init_db, get_or_create_user, save_bzu_record, 
    get_today_records, get_user_record, get_user_limits,
    get_all_users, update_limits,
    save_plan_record, get_plan_record, get_plan_history
)

# ============ ПРИНУДИТЕЛЬНО СОЗДАЕМ ТАБЛИЦЫ ============
print("🔧 Инициализация БД...")
init_db()
print("✅ БД готова")

# ============ НАСТРОЙКИ ============
TELEGRAM_TOKEN = "8704240954:AAG4AV6Wrt_9aQhn400ljcWTNq80gc0LpWM"
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bzu-production.up.railway.app")

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статика
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============ МОДЕЛИ ============
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

class PlanData(BaseModel):
    user_id: int
    plan_data: dict
    record_date: Optional[str] = None

# ============ API ============
@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
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

def get_status(value, min_val, max_val):
    if value == 0:
        return 'empty'
    elif value < min_val:
        return 'under'
    elif value > max_val:
        return 'over'
    else:
        return 'good'

@app.get("/api/today")
async def get_today():
    records = get_today_records()
    
    for rec in records:
        rec['protein_status'] = get_status(rec['protein'], rec['protein_min'], rec['protein_max'])
        rec['fat_status'] = get_status(rec['fat'], rec['fat_min'], rec['fat_max'])
        rec['carbs_status'] = get_status(rec['carbs'], rec['carbs_min'], rec['carbs_max'])
        rec['fiber_status'] = get_status(rec['fiber'], rec['fiber_min'], rec['fiber_max'])
        
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

@app.get("/api/users")
async def get_users():
    return get_all_users()

@app.post("/api/limits")
async def update_limits_endpoint(data: LimitsData):
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

# ============ API ДЛЯ ПЛАНА ============
@app.post("/api/plan/save")
async def save_plan(data: PlanData):
    """Сохраняет план выполнения"""
    try:
        save_plan_record(data.user_id, data.plan_data, data.record_date)
        return {"status": "success", "message": "План сохранен"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/plan/get/{user_id}")
async def get_plan(user_id: int, record_date: Optional[str] = None):
    """Получает план на дату"""
    plan = get_plan_record(user_id, record_date)
    return {"plan": plan or {}}

@app.get("/api/plan/history/{user_id}")
async def get_plan_history_api(user_id: int, days: int = 30):
    """Получает историю плана"""
    history = get_plan_history(user_id, days)
    return {"history": history}

# ============ ТЕЛЕГРАМ БОТ ============
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает /start и в личке, и в группе"""
    
    if not update.message:
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    print(f"📩 /start от {user.first_name} (ID: {user.id}) в чате: {chat.type if chat else 'unknown'}")
    
    keyboard = [[
        InlineKeyboardButton(
            "📊 Открыть дневник БЖУ",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]]
    
    if chat and chat.type in ['group', 'supergroup']:
        text = (
            "👋 Привет! Я бот для учета БЖУ в этой группе.\n\n"
            "📝 Нажми на кнопку ниже, чтобы открыть дневник.\n"
            "Там ты сможешь:\n"
            "✅ Вводить свои показатели\n"
            "📈 Смотреть график сравнения с участниками\n"
            "🏆 Отмечать план выполнения (массаж, баня, спорт)"
        )
    else:
        text = (
            "👋 Привет! Я бот для учета БЖУ.\n\n"
            "📝 Нажми на кнопку ниже, чтобы открыть дневник.\n"
            "Добавь меня в группу, чтобы сравнивать результаты!"
        )
    
    await update.message.reply_text(
        text,
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
    records = get_today_records()
    
    if not records or all(r['protein'] == 0 and r['fat'] == 0 and r['carbs'] == 0 and r['fiber'] == 0 for r in records):
        await update.message.reply_text("📭 Сегодня никто не ввел данные. Нажми 'Открыть дневник БЖУ'!")
        return
    
    message = "📊 <b>Сводка за сегодня</b>\n\n"
    
    for rec in records:
        name = rec['first_name'] or rec['username'] or f"User {rec['user_id']}"
        total = rec['protein'] + rec['fat'] + rec['carbs'] + rec['fiber']
        if total == 0:
            continue
        
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
    """Запускает Telegram бота с обработкой ошибок"""
    try:
        print(f"🤖 Запуск бота с токеном: {TELEGRAM_TOKEN[:10]}...")
        
        # Создаём новый event loop для этого потока
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Создаём приложение
        bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Добавляем обработчики команд
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CommandHandler("help", help_command))
        bot_app.add_handler(CommandHandler("stats", stats_command))
        
        print("✅ Обработчики команд добавлены")
        print("🤖 Бот запущен и ожидает сообщения...")
        
        # Запускаем polling
        bot_app.run_polling(allowed_updates=["message", "callback_query"])
        
    except Exception as e:
        print(f"❌ ОШИБКА в run_bot(): {e}")
        import traceback
        traceback.print_exc()

# ============ ЗАПУСК БОТА ============
print("🚀 Railway: запускаю бота...")

if not TELEGRAM_TOKEN:
    print("❌ ОШИБКА: TELEGRAM_TOKEN не задан!")
else:
    print(f"✅ TELEGRAM_TOKEN задан: {TELEGRAM_TOKEN[:10]}...")
    print("🔄 Запускаю бота в отдельном потоке...")
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("✅ Бот запущен в отдельном потоке")

# ============ ЗАПУСК ВЕБ-СЕРВЕРА ============
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Сервер запускается на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
