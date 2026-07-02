import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional
import json

DB_NAME = "bzu.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Создаем таблицы"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица записей БЖУ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bzu_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            record_date DATE,
            protein REAL DEFAULT 0,
            fat REAL DEFAULT 0,
            carbs REAL DEFAULT 0,
            fiber REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            UNIQUE(user_id, record_date)
        )
    ''')
    
    # Таблица лимитов с диапазонами
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            protein_min REAL DEFAULT 150,
            protein_max REAL DEFAULT 200,
            fat_min REAL DEFAULT 70,
            fat_max REAL DEFAULT 80,
            carbs_min REAL DEFAULT 80,
            carbs_max REAL DEFAULT 100,
            fiber_min REAL DEFAULT 10,
            fiber_max REAL DEFAULT 20,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            UNIQUE(user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ============ CRUD ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ============

def get_or_create_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> Dict:
    conn = get_db()
    cursor = conn.cursor()
    
    # Проверяем, есть ли пользователь
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))
        conn.commit()
        
        # Создаем лимиты по умолчанию с новыми диапазонами
        cursor.execute('''
            INSERT INTO limits (user_id, protein_min, protein_max, fat_min, fat_max, carbs_min, carbs_max, fiber_min, fiber_max)
            VALUES (?, 150, 200, 70, 80, 80, 100, 10, 20)
        ''', (user_id,))
        conn.commit()
        
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
    
    conn.close()
    return dict(user)

def get_all_users() -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY first_name")
    users = cursor.fetchall()
    conn.close()
    return [dict(user) for user in users]

# ============ CRUD ДЛЯ ЗАПИСЕЙ БЖУ ============

def save_bzu_record(user_id: int, protein: float, fat: float, carbs: float, fiber: float, record_date: str = None):
    if not record_date:
        record_date = date.today().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO bzu_records (user_id, record_date, protein, fat, carbs, fiber)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, record_date) DO UPDATE SET
            protein = excluded.protein,
            fat = excluded.fat,
            carbs = excluded.carbs,
            fiber = excluded.fiber,
            updated_at = CURRENT_TIMESTAMP
    ''', (user_id, record_date, protein, fat, carbs, fiber))
    
    conn.commit()
    conn.close()

def get_today_records() -> List[Dict]:
    """Получаем записи всех пользователей за сегодня"""
    today = date.today().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            u.user_id,
            u.first_name,
            u.username,
            b.protein,
            b.fat,
            b.carbs,
            b.fiber,
            l.protein_min,
            l.protein_max,
            l.fat_min,
            l.fat_max,
            l.carbs_min,
            l.carbs_max,
            l.fiber_min,
            l.fiber_max
        FROM users u
        LEFT JOIN bzu_records b ON u.user_id = b.user_id AND b.record_date = ?
        LEFT JOIN limits l ON u.user_id = l.user_id
        ORDER BY u.first_name
    ''', (today,))
    
    records = cursor.fetchall()
    conn.close()
    
    result = []
    for rec in records:
        rec_dict = dict(rec)
        # Если нет записи за сегодня, ставим 0
        for field in ['protein', 'fat', 'carbs', 'fiber']:
            if rec_dict[field] is None:
                rec_dict[field] = 0
        result.append(rec_dict)
    
    return result

def get_user_record(user_id: int, record_date: str = None) -> Optional[Dict]:
    if not record_date:
        record_date = date.today().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM bzu_records 
        WHERE user_id = ? AND record_date = ?
    ''', (user_id, record_date))
    
    record = cursor.fetchone()
    conn.close()
    return dict(record) if record else None

# ============ ЛИМИТЫ ============

def get_user_limits(user_id: int) -> Dict:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            protein_min, protein_max,
            fat_min, fat_max,
            carbs_min, carbs_max,
            fiber_min, fiber_max
        FROM limits
        WHERE user_id = ?
    ''', (user_id,))
    
    limits = cursor.fetchone()
    conn.close()
    
    if limits:
        return dict(limits)
    else:
        # Дефолтные лимиты с новыми диапазонами
        return {
            'protein_min': 150,
            'protein_max': 200,
            'fat_min': 70,
            'fat_max': 80,
            'carbs_min': 80,
            'carbs_max': 100,
            'fiber_min': 10,
            'fiber_max': 20
        }

def update_limits(user_id: int, 
                  protein_min: float, protein_max: float,
                  fat_min: float, fat_max: float,
                  carbs_min: float, carbs_max: float,
                  fiber_min: float, fiber_max: float):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO limits (
            user_id, 
            protein_min, protein_max,
            fat_min, fat_max,
            carbs_min, carbs_max,
            fiber_min, fiber_max
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            protein_min = excluded.protein_min,
            protein_max = excluded.protein_max,
            fat_min = excluded.fat_min,
            fat_max = excluded.fat_max,
            carbs_min = excluded.carbs_min,
            carbs_max = excluded.carbs_max,
            fiber_min = excluded.fiber_min,
            fiber_max = excluded.fiber_max
    ''', (user_id, protein_min, protein_max, fat_min, fat_max, carbs_min, carbs_max, fiber_min, fiber_max))
    
    conn.commit()
    conn.close()