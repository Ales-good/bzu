import os
import pymysql
from datetime import date, timedelta
from typing import List, Dict, Optional
import json
import re

def get_db():
    """Подключаемся к MySQL (прямое подключение)"""
    host = "mysql.railway.internal"
    user = "root"
    password = "ZblKDXodWUWBsbvhprKbKLXEzkEgYOfC"
    database = "railway"
    port = 3306
    
    print(f"🔌 Подключение к MySQL: {host}:{port}/{database}")
    
    conn = pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=10
    )
    return conn

def init_db():
    """Создаем таблицы в MySQL"""
    print("🔧 Создаю таблицы в MySQL...")
    conn = get_db()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    
    # Таблица записей БЖУ (добавлено поле calories)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bzu_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            record_date DATE,
            protein DECIMAL(10,2) DEFAULT 0,
            fat DECIMAL(10,2) DEFAULT 0,
            carbs DECIMAL(10,2) DEFAULT 0,
            fiber DECIMAL(10,2) DEFAULT 0,
            calories DECIMAL(10,2) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE KEY (user_id, record_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    
    # Таблица лимитов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS limits (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            protein_min DECIMAL(10,2) DEFAULT 150,
            protein_max DECIMAL(10,2) DEFAULT 200,
            fat_min DECIMAL(10,2) DEFAULT 70,
            fat_max DECIMAL(10,2) DEFAULT 80,
            carbs_min DECIMAL(10,2) DEFAULT 80,
            carbs_max DECIMAL(10,2) DEFAULT 100,
            fiber_min DECIMAL(10,2) DEFAULT 10,
            fiber_max DECIMAL(10,2) DEFAULT 20,
            calories_min DECIMAL(10,2) DEFAULT 2000,
            calories_max DECIMAL(10,2) DEFAULT 2500,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE KEY (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    
    # Таблица для плана
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plan_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            record_date DATE,
            plan_data JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE KEY (user_id, record_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    
    conn.commit()
    
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    table_names = [list(t.values())[0] for t in tables]
    print(f"✅ Созданы таблицы: {table_names}")
    
    conn.close()

# ============ ПОЛЬЗОВАТЕЛИ ============

def update_user_name(user_id: int, first_name: str):
    """Обновляет имя пользователя"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE users SET first_name = %s WHERE user_id = %s
        ''', (first_name, user_id))
        conn.commit()
        print(f"✅ Обновлено имя пользователя {user_id}: {first_name}")
    except Exception as e:
        print(f"❌ Ошибка обновления имени: {e}")
    finally:
        conn.close()
    
def get_or_create_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> Dict:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (%s, %s, %s, %s)
        ''', (user_id, username, first_name, last_name))
        
        cursor.execute('''
            INSERT INTO limits (user_id, protein_min, protein_max, fat_min, fat_max, carbs_min, carbs_max, fiber_min, fiber_max, calories_min, calories_max)
            VALUES (%s, 150, 200, 70, 80, 80, 100, 10, 20, 2000, 2500)
        ''', (user_id,))
        
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        print(f"✅ Создан новый пользователь: {user_id} - {first_name}")
    else:
        # Если пользователь существует, но имя не совпадает - обновляем
        if first_name and user.get('first_name') != first_name:
            update_user_name(user_id, first_name)
            user['first_name'] = first_name
    
    conn.close()
    return user

def get_all_users() -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY first_name")
    users = cursor.fetchall()
    conn.close()
    return users

# ============ БЖУ ============

def save_bzu_record(user_id: int, protein: float, fat: float, carbs: float, fiber: float, calories: float, record_date: str = None):
    if not record_date:
        record_date = date.today().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO bzu_records (user_id, record_date, protein, fat, carbs, fiber, calories)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            protein = VALUES(protein),
            fat = VALUES(fat),
            carbs = VALUES(carbs),
            fiber = VALUES(fiber),
            calories = VALUES(calories),
            updated_at = CURRENT_TIMESTAMP
    ''', (user_id, record_date, protein, fat, carbs, fiber, calories))
    
    conn.commit()
    conn.close()
    print(f"✅ Сохранена запись БЖУ для user_id={user_id} на {record_date}")

def get_today_records() -> List[Dict]:
    today = date.today().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            u.user_id,
            u.first_name,
            u.username,
            COALESCE(b.protein, 0) as protein,
            COALESCE(b.fat, 0) as fat,
            COALESCE(b.carbs, 0) as carbs,
            COALESCE(b.fiber, 0) as fiber,
            COALESCE(b.calories, 0) as calories,
            l.protein_min,
            l.protein_max,
            l.fat_min,
            l.fat_max,
            l.carbs_min,
            l.carbs_max,
            l.fiber_min,
            l.fiber_max,
            l.calories_min,
            l.calories_max
        FROM users u
        LEFT JOIN bzu_records b ON u.user_id = b.user_id AND b.record_date = %s
        LEFT JOIN limits l ON u.user_id = l.user_id
        ORDER BY u.first_name
    ''', (today,))
    
    records = cursor.fetchall()
    conn.close()
    return records

def get_user_record(user_id: int, record_date: str = None) -> Optional[Dict]:
    if not record_date:
        record_date = date.today().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM bzu_records 
        WHERE user_id = %s AND record_date = %s
    ''', (user_id, record_date))
    
    record = cursor.fetchone()
    conn.close()
    return record

def get_user_history(user_id: int, days: int = 90) -> List[Dict]:
    """Получает историю БЖУ за N дней"""
    conn = get_db()
    cursor = conn.cursor()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    
    cursor.execute('''
        SELECT record_date, protein, fat, carbs, fiber, calories
        FROM bzu_records
        WHERE user_id = %s AND record_date >= %s
        ORDER BY record_date ASC
    ''', (user_id, start_date))
    
    records = cursor.fetchall()
    conn.close()
    return records

# ============ ЛИМИТЫ ============

def get_user_limits(user_id: int) -> Dict:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            protein_min, protein_max,
            fat_min, fat_max,
            carbs_min, carbs_max,
            fiber_min, fiber_max,
            calories_min, calories_max
        FROM limits
        WHERE user_id = %s
    ''', (user_id,))
    
    limits = cursor.fetchone()
    conn.close()
    
    if limits:
        return limits
    else:
        return {
            'protein_min': 150, 'protein_max': 200,
            'fat_min': 70, 'fat_max': 80,
            'carbs_min': 80, 'carbs_max': 100,
            'fiber_min': 10, 'fiber_max': 20,
            'calories_min': 2000, 'calories_max': 2500
        }

def update_limits(user_id: int, 
                  protein_min: float, protein_max: float,
                  fat_min: float, fat_max: float,
                  carbs_min: float, carbs_max: float,
                  fiber_min: float, fiber_max: float,
                  calories_min: float, calories_max: float):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO limits (
            user_id, 
            protein_min, protein_max,
            fat_min, fat_max,
            carbs_min, carbs_max,
            fiber_min, fiber_max,
            calories_min, calories_max
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            protein_min = VALUES(protein_min),
            protein_max = VALUES(protein_max),
            fat_min = VALUES(fat_min),
            fat_max = VALUES(fat_max),
            carbs_min = VALUES(carbs_min),
            carbs_max = VALUES(carbs_max),
            fiber_min = VALUES(fiber_min),
            fiber_max = VALUES(fiber_max),
            calories_min = VALUES(calories_min),
            calories_max = VALUES(calories_max)
    ''', (user_id, protein_min, protein_max, fat_min, fat_max, carbs_min, carbs_max, fiber_min, fiber_max, calories_min, calories_max))
    
    conn.commit()
    conn.close()

# ============ ПЛАН ============

def save_plan_record(user_id: int, plan_data: dict, record_date: str = None):
    if not record_date:
        record_date = date.today().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    plan_json = json.dumps(plan_data, ensure_ascii=False)
    
    cursor.execute('''
        INSERT INTO plan_records (user_id, record_date, plan_data)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            plan_data = VALUES(plan_data),
            updated_at = CURRENT_TIMESTAMP
    ''', (user_id, record_date, plan_json))
    
    conn.commit()
    conn.close()
    print(f"✅ Сохранен план для user_id={user_id} на {record_date}")

def get_plan_record(user_id: int, record_date: str = None) -> Optional[Dict]:
    if not record_date:
        record_date = date.today().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT plan_data FROM plan_records
        WHERE user_id = %s AND record_date = %s
    ''', (user_id, record_date))
    
    record = cursor.fetchone()
    conn.close()
    
    if record and record.get('plan_data'):
        try:
            return json.loads(record['plan_data'])
        except:
            return {}
    return None

def get_plan_history(user_id: int, days: int = 90) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    
    cursor.execute('''
        SELECT record_date, plan_data 
        FROM plan_records
        WHERE user_id = %s AND record_date >= %s
        ORDER BY record_date ASC
    ''', (user_id, start_date))
    
    records = cursor.fetchall()
    conn.close()
    
    result = []
    for rec in records:
        rec_dict = dict(rec)
        try:
            rec_dict['plan_data'] = json.loads(rec_dict['plan_data'])
        except:
            rec_dict['plan_data'] = {}
        result.append(rec_dict)
    
    return result
