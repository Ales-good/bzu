from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import os
import logging
from datetime import date

from database_mysql import (
    init_db, get_or_create_user, save_bzu_record, 
    get_today_records, get_user_record, get_user_limits,
    get_all_users, update_limits,
    save_plan_record, get_plan_record, get_plan_history,
    get_user_history, update_user_name, get_db
)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

print("🔧 Инициализация БД...")
init_db()
print("✅ БД готова")

TELEGRAM_TOKEN = "8704240954:AAG4AV6Wrt_9aQhn400ljcWTNq80gc0LpWM"
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bzu-production.up.railway.app")
WEBHOOK_URL = f"{WEBAPP_URL}/webhook"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ============ ОЧИСТКА ТЕСТОВЫХ ПОЛЬЗОВАТЕЛЕЙ ============
def cleanup_test_users():
    """Удаляет пользователей с именами 'Гость' и 'Тест' у которых нет активности"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Удаляем пользователей с именами 'Гость' или 'Тест'
        # у которых нет записей БЖУ (все показатели = 0)
        cursor.execute("""
            DELETE FROM users 
            WHERE (first_name = 'Гость' OR first_name = 'Тест' OR first_name IS NULL OR first_name = '')
            AND user_id NOT IN (
                SELECT DISTINCT user_id FROM bzu_records 
                WHERE protein > 0 OR fat > 0 OR carbs > 0 OR fiber > 0 OR calories > 0
            )
        """)
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            print(f"🧹 Удалено {deleted_count} тестовых пользователей")
        return deleted_count
    except Exception as e:
        print(f"❌ Ошибка очистки: {e}")
        return 0

# ============ МОДЕЛИ ============
class BZUData(BaseModel):
    user_id: int
    user_name: Optional[str] = None
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
    user_name: Optional[str] = None
    plan_data: dict
    record_date: Optional[str] = None

# ============ API ============
@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/api/user/{user_id}")
async def get_user(user_id: int, first_name: str = None):
    # Если имя не передано или это "Гость"/"Тест" - не создаем нового пользователя
    if not first_name or first_name in ['Гость', 'Тест', '']:
        # Проверяем, существует ли пользователь
        user = get_or_create_user(user_id, first_name='Гость')
        limits = get_user_limits(user_id)
        today_record = get_user_record(user_id)
        return {
            "user": user,
            "limits": limits,
            "today_record": today_record or {
                "protein": 0, "fat": 0, "carbs": 0, "fiber": 0, "calories": 0
            }
        }
    
    user = get_or_create_user(user_id, first_name=first_name)
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
        # Если имя "Гость" или "Тест" - не обновляем его
        if data.user_name and data.user_name not in ['Гость', 'Тест', '']:
            update_user_name(data.user_id, data.user_name)
        
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
        print(f"❌ Ошибка сохранения: {e}")
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
        
        # Если имя "Гость" или "Тест" - не обновляем его
        if data.user_name and data.user_name not in ['Гость', 'Тест', '']:
            update_user_name(data.user_id, data.user_name)
        
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

@app.get("/api/history/{user_id}")
async def get_history(user_id: int, days: int = 90):
    """Получает историю БЖУ и плана для графиков"""
    bzu_history = get_user_history(user_id, days)
    plan_history = get_plan_history(user_id, days)
    
    plan_dict = {}
    for p in plan_history:
        date_str = p['record_date'].isoformat() if hasattr(p['record_date'], 'isoformat') else str(p['record_date'])
        plan_dict[date_str] = p['plan_data']
    
    dates = []
    calories = []
    protein = []
    fat = []
    carbs = []
    fiber = []
    plan_completed = []
    plan_total = []
    plan_data_list = []
    
    for record in bzu_history:
        date_str = record['record_date']
        dates.append(date_str)
        calories.append(float(record['calories']) if record['calories'] else 0)
        protein.append(float(record['protein']) if record['protein'] else 0)
        fat.append(float(record['fat']) if record['fat'] else 0)
        carbs.append(float(record['carbs']) if record['carbs'] else 0)
        fiber.append(float(record['fiber']) if record['fiber'] else 0)
        
        plan_data = plan_dict.get(date_str, {})
        plan_data_list.append(plan_data)
        
        total_items = len(plan_data)
        completed_items = 0
        for v in plan_data.values():
            if isinstance(v, dict):
                if v.get('done', False) or v.get('count', 0) > 0:
                    completed_items += 1
            elif v:
                completed_items += 1 if v else 0
        
        plan_total.append(total_items)
        plan_completed.append(completed_items)
    
    return {
        "dates": dates,
        "calories": calories,
        "protein": protein,
        "fat": fat,
        "carbs": carbs,
        "fiber": fiber,
        "plan_completed": plan_completed,
        "plan_total": plan_total,
        "plan_data": plan_data_list
    }

# ============ ТЕЛЕГРАМ БОТ ============
bot_app = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие и главное меню"""
    if not update.message:
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    print(f"📩 /start от {user.first_name} (ID: {user.id}) в чате: {chat.type if chat else 'unknown'}")
    
    # В ЛИЧНЫХ СООБЩЕНИЯХ - web_app кнопка
    if chat and chat.type == 'private':
        keyboard = [[
            InlineKeyboardButton(
                "📊 Открыть дневник",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )
        ]]
        
        text = (
            "👋 Привет! Я бот для учета БЖУ.\n\n"
            "📝 Нажми на кнопку ниже, чтобы открыть дневник прямо в Telegram.\n\n"
            "Добавь меня в группу, чтобы сравнивать результаты!\n\n"
            "💡 Команды:\n"
            "/start - Главное меню\n"
            "/stats - Статистика за сегодня\n"
            "/help - Помощь"
        )
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    # В ГРУППАХ - ссылка
    else:
        text = (
            "👋 Привет! Я бот для учета БЖУ в этой группе.\n\n"
            "📝 Открой дневник по ссылке (откроется внутри Telegram):\n"
            f"<a href=\"{WEBAPP_URL}\">📊 Открыть дневник БЖУ</a>\n\n"
            "Там ты сможешь:\n"
            "✅ Вводить свои показатели (БЖУ + калории)\n"
            "📈 Смотреть графики динамики\n"
            "🏆 Отмечать план выполнения\n\n"
            "💡 Команды:\n"
            "/start - Главное меню\n"
            "/stats - Статистика за сегодня\n"
            "/help - Помощь"
        )
        
        await update.message.reply_text(
            text,
            parse_mode='HTML',
            disable_web_page_preview=False
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику за сегодня"""
    records = get_today_records()
    active_records = [r for r in records if r['protein'] + r['fat'] + r['carbs'] + r['fiber'] + r['calories'] > 0]
    
    if not active_records:
        await update.message.reply_text("📭 Сегодня никто не ввел данные!")
        return
    
    message = "📊 <b>Сводка за сегодня</b>\n\n"
    for rec in active_records:
        name = rec['first_name'] or rec['username'] or f"User {rec['user_id']}"
        message += f"👤 <b>{name}</b>\n"
        if rec['protein'] > 0:
            message += f"  🍗 Белки: {rec['protein']:.0f}г\n"
        if rec['fat'] > 0:
            message += f"  🧈 Жиры: {rec['fat']:.0f}г\n"
        if rec['carbs'] > 0:
            message += f"  🍞 Углеводы: {rec['carbs']:.0f}г\n"
        if rec['fiber'] > 0:
            message += f"  🥦 Клетчатка: {rec['fiber']:.0f}г\n"
        if rec['calories'] > 0:
            message += f"  🔥 Калории: {rec['calories']:.0f}ккал\n"
        message += "\n"
    
    await update.message.reply_text(message, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    await update.message.reply_text(
        "🤖 <b>Команды бота:</b>\n\n"
        "/start - Главное меню\n"
        "/stats - Статистика за сегодня\n"
        "/help - Помощь\n\n"
        "📝 Открой дневник по ссылке:\n"
        f"<a href=\"{WEBAPP_URL}\">📊 Открыть дневник БЖУ</a>",
        parse_mode='HTML'
    )

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений в группах"""
    if update.message and update.message.chat.type in ['group', 'supergroup']:
        if update.message.text and f"@{context.bot.username}" in update.message.text:
            await start(update, context)

# Webhook endpoint
@app.post("/webhook")
async def webhook(request: Request):
    """Принимает обновления от Telegram"""
    global bot_app
    if bot_app is None:
        return Response("Bot not initialized", status_code=500)
    
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return Response("OK", status_code=200)
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return Response("Error", status_code=500)

# ============ ЗАПУСК БОТА ============
@app.on_event("startup")
async def startup():
    """Запускает бота при старте сервера"""
    global bot_app
    try:
        print("🤖 Инициализация бота...")
        bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CommandHandler("help", help_command))
        bot_app.add_handler(CommandHandler("stats", stats_command))
        bot_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, handle_group_message))
        
        await bot_app.initialize()
        await bot_app.start()
        
        await bot_app.bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        print(f"✅ Webhook установлен: {WEBHOOK_URL}")
        
        # Очищаем тестовых пользователей при старте
        cleanup_test_users()
        
        print("✅ Бот успешно запущен!")
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")

@app.on_event("shutdown")
async def shutdown():
    """Останавливает бота"""
    global bot_app
    if bot_app:
        await bot_app.stop()
        print("✅ Бот остановлен")

# ============ ЗАПУСК FASTAPI ============
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Сервер запускается на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
