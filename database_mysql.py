import os
import pymysql
from datetime import date
from typing import List, Dict, Optional
import re

def get_db():
    """Подключаемся к MySQL"""
    
    # Пробуем получить MYSQL_URL
    mysql_url = os.getenv("MYSQL_URL")
    
    if mysql_url:
        # Парсим URL
        pattern = r'mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
        match = re.match(pattern, mysql_url)
        if match:
            user, password, host, port, database = match.groups()
            print(f"🔌 Подключение к MySQL: {host}:{port}/{database}")
        else:
            raise Exception(f"❌ Неверный формат MYSQL_URL")
    else:
        # Используем отдельные переменные
        host = os.getenv("MYSQLHOST")
        user = os.getenv("MYSQLUSER")
        password = os.getenv("MYSQLPASSWORD")
        database = os.getenv("MYSQLDATABASE")
        port = int(os.getenv("MYSQLPORT", 3306))
        
        if not all([host, user, password, database]):
            raise Exception("❌ Не найдены переменные для подключения к MySQL!")
        
        print(f"🔌 Подключение к MySQL: {host}:{port}/{database}")
    
    conn = pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=int(port),
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
    
    # Таблица записей БЖУ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bzu_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT,
            record_date DATE,
            protein DECIMAL(10,2) DEFAULT 0,
            fat DECIMAL(10,2) DEFAULT 0,
            carbs DECIMAL(10,2) DEFAULT 0,
            fiber DECIMAL(10,2) DEFAULT 0,
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
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE KEY (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')
    
    conn.commit()
    
    # Проверяем
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    table_names = [list(t.values())[0] for t in tables]
    print(f"✅ Созданы таблицы: {table_names}")
    
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
            INSERT INTO limits (user_id, protein_min, protein_max, fat_min, fat_max, carbs_min, carbs_max, fiber_min, fiber_max)
            VALUES (%s, 150, 200, 70, 80, 80, 100, 10, 20)
        ''', (user_id,))
        
        conn.commit()
        
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
    
    conn.close()
    return user

def get_all_users() -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY first_name")
    users = cursor.fetchall()
    conn.close()
    return users

def save_bzu_record(user_id: int, protein: float, fat: float, carbs: float, fiber: float, record_date: str = None):
    if not record_date:
        record_date = date.today().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO bzu_records (user_id, record_date, protein, fat, carbs, fiber)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            protein = VALUES(protein),
            fat = VALUES(fat),
            carbs = VALUES(carbs),
            fiber = VALUES(fiber),
            updated_at = CURRENT_TIMESTAMP
    ''', (user_id, record_date, protein, fat, carbs, fiber))
    
    conn.commit()
    conn.close()

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
            l.protein_min,
            l.protein_max,
            l.fat_min,
            l.fat_max,
            l.carbs_min,
            l.carbs_max,
            l.fiber_min,
            l.fiber_max
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
        WHERE user_id = %s
    ''', (user_id,))
    
    limits = cursor.fetchone()
    conn.close()
    
    if limits:
        return limits
    else:
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
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            protein_min = VALUES(protein_min),
            protein_max = VALUES(protein_max),
            fat_min = VALUES(fat_min),
            fat_max = VALUES(fat_max),
            carbs_min = VALUES(carbs_min),
            carbs_max = VALUES(carbs_max),
            fiber_min = VALUES(fiber_min),
            fiber_max = VALUES(fiber_max)
    ''', (user_id, protein_min, protein_max, fat_min, fat_max, carbs_min, carbs_max, fiber_min, fiber_max))
    
    conn.commit()
    conn.close()
