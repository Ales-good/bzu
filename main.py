from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import threading
import os
import time
import asyncio
from datetime import date

from database_mysql import (
    init_db, get_or_create_user, save_bzu_record, 
    get_today_records, get_user_record, get_user_limits,
    get_all_users, update_limits,
    save_plan_record, get_plan_record, get_plan_history,
    get_user_history, update_user_name
)

print("🔧 Инициализация БД...")
init_db()
print("✅ БД готова")

TELEGRAM_TOKEN = "8704240954:AAG4AV6Wrt_9aQhn400ljcWTNq80gc0LpWM"
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bzu-production.up.railway.app")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ============ МОДЕЛИ ============
class BZUData(BaseModel):
    user_id: int
    protein: float = 0
    fat: float = 0
    carbs: float = 0
    fiber: float = 0
    calories: float = 0
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
    calories_min: float
    calories_max: float

class PlanData(BaseModel):
    user_id: int
    plan_data: dict
    record_date: Optional[str] = None

# ============ API ============
@app.get("/")
async def index():
    response = FileResponse("static/index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/api/user/{user_id}")
async def get_user(user_id: int, first_name: str = None):
    print(f"🔍 Запрос пользователя: user_id={user_id}, first_name={first_name}")
    
    user = get_or_create_user(user_id, first_name=first_name)
    print(f"✅ Пользователь получен/создан: {user}")
    
    if first_name and user.get('first_name') != first_name:
        update_user_name(user_id, first_name)
        user['first_name'] = first_name
    
    limits = get_user_limits(user_id)
    today_record = get_user_record(user_id)
    
    return {
        "user": user,
        "limits": limits,
        "today_record": today_record or {
            "protein": 0, "fat": 0, "carbs": 0, "fiber": 0, "calories": 0
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
            data.calories,
            data.record_date
        )
        return {"status": "success", "message": "Данные сохранены"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/today")
async def get_today():
    records = get_today_records()
    for rec in records:
        rec['protein_status'] = get_status(rec['protein'], rec['protein_min'], rec['protein_max'])
        rec['fat_status'] = get_status(rec['fat'], rec['fat_min'], rec['fat_max'])
        rec['carbs_status'] = get_status(rec['carbs'], rec['carbs_min'], rec['carbs_max'])
        rec['fiber_status'] = get_status(rec['fiber'], rec['fiber_min'], rec['fiber_max'])
        rec['calories_status'] = get_status(rec['calories'], rec['calories_min'], rec['calories_max'])
        
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
    if value is None:
        value = 0
    if min_val is None:
        min_val = 0
    if max_val is None:
        max_val = 1
    
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
    return get_all_users()

@app.post("/api/limits")
async def update_limits_endpoint(data: LimitsData):
    try:
        update_limits(
            data.user_id,
            data.protein_min, data.protein_max,
            data.fat_min, data.fat_max,
            data.carbs_min, data.carbs_max,
            data.fiber_min, data.fiber_max,
            data.calories_min, data.calories_max
        )
        return {"status": "success", "message": "Лимиты обновлены"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/plan/save")
async def save_plan(data: PlanData):
    try:
        print(f"📥 Сохраняем план для user_id={data.user_id}")
        
        user = get_or_create_user(data.user_id)
        if not user:
            raise HTTPException(status_code=400, detail="Пользователь не найден")
        
        print(f"📊 Данные: {data.plan_data}")
        save_plan_record(data.user_id, data.plan_data, data.record_date)
        return {"status": "success", "message": "План сохранен"}
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/plan/get/{user_id}")
async def get_plan(user_id: int, record_date: Optional[str] = None):
    plan = get_plan_record(user_id, record_date)
    return {"plan": plan or {}}

@app.get("/api/plan/history/{user_id}")
async def get_plan_history_api(user_id: int, days: int = 30):
    history = get_plan_history(user_id, days)
    return {"history": history}

@app.get("/api/history/{user_id}")
async def get_history(user_id: int, days: int = 90):
    bzu_history = get_user_history(user_id, days)
    plan_history = get_plan_history(user_id, days)
    
    plan_dict = {p['record_date']: p['plan_data'] for p in plan_history}
    
    dates = []
    calories = []
    plan_completed = []
    plan_total = []
    
    for record in bzu_history:
        date_str = record['record_date'].isoformat() if hasattr(record['record_date'], 'isoformat') else record['record_date']
        dates.append(date_str)
        calories.append(float(record['calories']) if record['calories'] else 0)
        
        plan_data = plan_dict.get(date_str, {})
        total_items = len(plan_data)
        completed_items = sum(1 for v in plan_data.values() if v.get('done', False) or v.get('count', 0) > 0)
        
        plan_total.append(total_items)
        plan_completed.append(completed_items)
    
    return {
        "dates": dates,
        "calories": calories,
        "plan_completed": plan_completed,
        "plan_total": plan_total
    }

# ============ ТЕЛЕГРАМ БОТ ============
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "✅ Вводить свои показатели (БЖУ + калории)\n"
            "📈 Смотреть графики динамики\n"
            "🏆 Отмечать план выполнения"
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
        "/help - Помощь\n"
        "/stats - Сводка за сегодня"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = get_today_records()
    if not records or all(r['protein'] == 0 and r['fat'] == 0 and r['carbs'] == 0 for r in records):
        await update.message.reply_text("📭 Сегодня никто не ввел данные!")
        return
    
    message = "📊 <b>Сводка за сегодня</b>\n\n"
    for rec in records:
        name = rec['first_name'] or rec['username'] or f"User {rec['user_id']}"
        total = rec['protein'] + rec['fat'] + rec['carbs']
        if total == 0:
            continue
        message += f"👤 <b>{name}</b>\n"
        message += f"  🍗 Белки: {rec['protein']:.0f}г ({rec['protein_min']:.0f}-{rec['protein_max']:.0f})\n"
        message += f"  🧈 Жиры: {rec['fat']:.0f}г ({rec['fat_min']:.0f}-{rec['fat_max']:.0f})\n"
        message += f"  🍞 Углеводы: {rec['carbs']:.0f}г ({rec['carbs_min']:.0f}-{rec['carbs_max']:.0f})\n"
        message += f"  🔥 Калории: {rec['calories']:.0f}ккал ({rec['calories_min']:.0f}-{rec['calories_max']:.0f})\n\n"
    
    await update.message.reply_text(message, parse_mode='HTML')

# ============ ЗАПУСК ============
if __name__ == "__main__":
    print("🚀 Запуск приложения...")
    
    if not TELEGRAM_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_TOKEN не задан!")
        exit(1)
    
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("stats", stats_command))
    
    print("✅ Обработчики команд добавлены")
    print("🤖 Запуск Telegram бота...")
    
    def run_bot_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            bot_app.run_polling(
                allowed_updates=["message", "callback_query"],
                stop_signals=[]
            )
        except Exception as e:
            print(f"❌ Ошибка в боте: {e}")
    
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    print("✅ Бот запущен в фоновом потоке")
    
    time.sleep(0.5)
    
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Сервер запускается на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
