from fastapi import FastAPI, Request, Form, HTTPException, status, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, timedelta
import hashlib
import secrets
import sqlite3
import os
import sys
import subprocess
import random
import aiosmtplib
from email.message import EmailMessage
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# from app.backend.recognize_products import recognize_products
# from app.backend.add_to_cart import add_product_to_cart, add_multiple_products_to_cart
from app.backend.emailer import send_email
# from app.backend.recognize_products import recognize_products
# from app.backend.add_to_cart import add_product_to_cart, add_multiple_products_to_cart
from app.backend.recognize_products import recognize_products
from app.backend.add_to_cart import add_product_to_cart, add_multiple_products_to_cart
# Load environment variables
load_dotenv()

app = FastAPI(title="MyAboabo")



# Security configuration
SECRET_KEY = secrets.token_urlsafe(32)

class MailIn(BaseModel):
    to: EmailStr
    subject: str
    text: str
    html: str | None = None

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), "autobuyer.db")

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if users table exists and get its columns
    cursor.execute("PRAGMA table_info(users)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    
    if not existing_columns:
        # Create users table from scratch
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                two_factor_enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        # Migrate existing table
        if 'email' not in existing_columns:
            print("📦 Migrating database: Adding email column...")
            cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
            # Set default email for existing users
            cursor.execute("UPDATE users SET email = username || '@example.com' WHERE email IS NULL")
            
        if 'two_factor_enabled' not in existing_columns:
            print("📦 Migrating database: Adding two_factor_enabled column...")
            cursor.execute("ALTER TABLE users ADD COLUMN two_factor_enabled BOOLEAN DEFAULT 0")
    
    # Create verification codes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    # Create products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            name TEXT NOT NULL,
            image_url TEXT,
            price TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    # Check if products table needs migration for image_url and price
    cursor.execute("PRAGMA table_info(products)")
    product_columns = [col[1] for col in cursor.fetchall()]
    if 'image_url' not in product_columns:
        print("📦 Migrating database: Adding image_url column to products...")
        cursor.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
    if 'price' not in product_columns:
        print("📦 Migrating database: Adding price column to products...")
        cursor.execute("ALTER TABLE products ADD COLUMN price TEXT")
    
    # Create subscriptions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            frequency TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            start_date TEXT,
            frequency_type TEXT,
            frequency_value INTEGER,
            frequency_unit TEXT,
            specific_day_type TEXT,
            weekday INTEGER,
            monthday INTEGER,
            next_buy_date TEXT,
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    # Migration: Add new columns if they don't exist
    cursor.execute("PRAGMA table_info(subscriptions)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'start_date' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN start_date TEXT")
    if 'frequency_type' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN frequency_type TEXT")
    if 'frequency_value' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN frequency_value INTEGER")
    if 'frequency_unit' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN frequency_unit TEXT")
    if 'specific_day_type' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN specific_day_type TEXT")
    if 'weekday' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN weekday INTEGER")
    if 'monthday' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN monthday INTEGER")
    if 'next_buy_date' not in columns:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN next_buy_date TEXT")
    
    # Create default admin user if not exists
    cursor.execute("SELECT * FROM users WHERE username = ?", ("admin",))
    if not cursor.fetchone():
        hashed_pw = hash_password("admin123")
        cursor.execute(
            "INSERT INTO users (username, email, hashed_password, two_factor_enabled) VALUES (?, ?, ?, ?)",
            ("admin", "admin@example.com", hashed_pw, 0)  # 2FA disabled for admin by default
        )
        print("✅ Default admin user created (username: admin, password: admin123)")
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")

def calculate_next_buy_date(start_date_str: str, frequency_type: str, frequency_value: int = None, 
                            frequency_unit: str = None, specific_day_type: str = None, 
                            weekday: int = None, monthday: int = None, frequency_preset: str = None) -> str:
    """Calculate the next buy date based on start date and frequency settings"""
    from datetime import datetime, timedelta
    from dateutil.relativedelta import relativedelta
    import calendar
    
    # Parse start date
    if not start_date_str:
        start_date = datetime.now()
    else:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except:
            start_date = datetime.now()
    
    # If start date is in the future, that's the next buy date
    if start_date.date() > datetime.now().date():
        return start_date.strftime("%Y-%m-%d")
    
    current_date = datetime.now()
    next_date = start_date
    
    # Determine the frequency in days/months/years
    if frequency_type == "preset":
        # Map preset frequencies to increments
        preset_map = {
            "täglich": {"days": 1},
            "wöchentlich": {"weeks": 1},
            "alle 2 Wochen": {"weeks": 2},
            "monatlich": {"months": 1},
            "alle 2 Monate": {"months": 2},
            "vierteljährlich": {"months": 3},
            "halbjährlich": {"months": 6},
            "jährlich": {"years": 1}
        }
        increment = preset_map.get(frequency_preset, {"days": 1})
    elif frequency_type == "custom" and frequency_value and frequency_unit:
        # Build custom increment - support both German and English
        unit_map = {
            "days": "days",
            "weeks": "weeks", 
            "months": "months",
            "years": "years",
            "Tag(e)": "days",
            "Woche(n)": "weeks",
            "Monat(e)": "months",
            "Jahr(e)": "years",
            "tage": "days",
            "wochen": "weeks",
            "monate": "months",
            "jahre": "years"
        }
        increment = {unit_map.get(frequency_unit, "days"): frequency_value}
    else:
        # Default to daily
        increment = {"days": 1}
    
    # Calculate next occurrence after current date
    while next_date <= current_date:
        if "days" in increment:
            next_date += timedelta(days=increment["days"])
        elif "weeks" in increment:
            next_date += timedelta(weeks=increment["weeks"])
        elif "months" in increment:
            next_date += relativedelta(months=increment["months"])
        elif "years" in increment:
            next_date += relativedelta(years=increment["years"])
    
    # Apply specific day constraints if set
    if specific_day_type == "weekday" and weekday is not None:
        # Find next occurrence of the specific weekday
        days_ahead = (weekday - next_date.weekday()) % 7
        if days_ahead == 0 and next_date <= current_date:
            days_ahead = 7
        next_date += timedelta(days=days_ahead)
    elif specific_day_type == "monthday" and monthday is not None:
        # Set to specific day of month
        if monthday == -1:
            # Last day of month
            last_day = calendar.monthrange(next_date.year, next_date.month)[1]
            next_date = next_date.replace(day=last_day)
        else:
            try:
                next_date = next_date.replace(day=min(monthday, calendar.monthrange(next_date.year, next_date.month)[1]))
            except:
                pass
        
        # If we're past this day in the current month, move to next occurrence
        if next_date <= current_date:
            if "months" in increment:
                next_date += relativedelta(months=increment["months"])
            else:
                next_date += relativedelta(months=1)
            
            if monthday == -1:
                last_day = calendar.monthrange(next_date.year, next_date.month)[1]
                next_date = next_date.replace(day=last_day)
            else:
                try:
                    next_date = next_date.replace(day=min(monthday, calendar.monthrange(next_date.year, next_date.month)[1]))
                except:
                    pass
    
    return next_date.strftime("%Y-%m-%d")

def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return hash_password(plain_password) == hashed_password

def get_user_by_username(username: str) -> Optional[dict]:
    """Get user from database by username"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, hashed_password, two_factor_enabled, created_at FROM users WHERE username = ?",
        (username,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "hashed_password": row[3],
            "two_factor_enabled": bool(row[4]),
            "created_at": row[5]
        }
    return None

def get_user_by_email(email: str) -> Optional[dict]:
    """Get user from database by email"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, hashed_password, two_factor_enabled, created_at FROM users WHERE email = ?",
        (email,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "hashed_password": row[3],
            "two_factor_enabled": bool(row[4]),
            "created_at": row[5]
        }
    return None

def get_user_by_id(user_id: int) -> Optional[dict]:
    """Get user from database by ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, hashed_password, two_factor_enabled, created_at FROM users WHERE id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "hashed_password": row[3],
            "two_factor_enabled": bool(row[4]),
            "created_at": row[5]
        }
    return None

def create_user(username: str, email: str, password: str) -> bool:
    """Create a new user in the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        hashed_pw = hash_password(password)
        cursor.execute(
            "INSERT INTO users (username, email, hashed_password, two_factor_enabled) VALUES (?, ?, ?, ?)",
            (username, email, hashed_pw, 1)  # 2FA enabled by default for new users
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

def update_user_password(email: str, new_password: str) -> bool:
    """Update user password in database by email"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        hashed_pw = hash_password(new_password)
        cursor.execute(
            "UPDATE users SET hashed_password = ? WHERE email = ?",
            (hashed_pw, email)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def generate_verification_code() -> str:
    """Generate a 6-digit verification code"""
    return str(random.randint(100000, 999999))

def create_verification_code(user_id: int) -> str:
    """Create and store a verification code for a user"""
    code = generate_verification_code()
    expires_at = datetime.now() + timedelta(minutes=10)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO verification_codes (user_id, code, expires_at) VALUES (?, ?, ?)",
        (user_id, code, expires_at.isoformat())
    )
    conn.commit()
    conn.close()
    
    return code

def verify_code(user_id: int, code: str) -> bool:
    """Verify a code for a user"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT id, expires_at FROM verification_codes 
           WHERE user_id = ? AND code = ? AND used = 0 
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, code)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return False
    
    code_id, expires_at = row
    if datetime.fromisoformat(expires_at) < datetime.now():
        conn.close()
        return False
    
    # Mark code as used
    cursor.execute("UPDATE verification_codes SET used = 1 WHERE id = ?", (code_id,))
    conn.commit()
    conn.close()
    
    return True

async def send_verification_email(email: str, code: str, username: str):
    """Send verification code via email"""
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"⚠️  Email not configured. Verification code for {username}: {code}")
        return
    
    try:
        message = EmailMessage()
        message["From"] = FROM_EMAIL
        message["To"] = email
        message["Subject"] = "AutoBuyer - Verification Code"
        
        message.set_content(f"""
Hello {username},

Your verification code is: {code}

This code will expire in 10 minutes.

If you didn't request this code, please ignore this email.

Best regards,
AutoBuyer Team
        """)
        
        await aiosmtplib.send(
            message,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=True,
        )
        print(f"✅ Verification email sent to {email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        print(f"⚠️  Verification code for {username}: {code}")

def get_all_products(user_id: int = None) -> List[dict]:
    """Get all products from database, optionally filtered by user_id"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if user_id is not None:
        cursor.execute("""
            SELECT p.id, p.url, p.name, p.image_url, p.price, p.added_at,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM subscriptions s 
                       WHERE s.product_id = p.id AND s.is_active = 1 AND s.user_id = ?
                   ) THEN 1 ELSE 0 END as has_active_subscription
            FROM products p
            WHERE p.user_id = ?
            ORDER BY p.added_at DESC
        """, (user_id, user_id))
    else:
        cursor.execute("""
            SELECT p.id, p.url, p.name, p.image_url, p.price, p.added_at,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM subscriptions s 
                       WHERE s.product_id = p.id AND s.is_active = 1
                   ) THEN 1 ELSE 0 END as has_active_subscription
            FROM products p
            ORDER BY p.added_at DESC
        """)
    
    rows = cursor.fetchall()
    conn.close()
    
    products = []
    for row in rows:
        products.append({
            "id": row[0],
            "url": row[1],
            "name": row[2],
            "image_url": row[3],
            "price": row[4],
            "added_at": datetime.fromisoformat(row[5]) if row[5] else datetime.now(),
            "has_active_subscription": bool(row[6])
        })
    return products

def add_product_to_db(url: str, name: str, image_url: str = None, price: str = None, user_id: int = None) -> int:
    """Add a new product to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO products (url, name, image_url, price, added_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
        (url, name, image_url, price, datetime.now().isoformat(), user_id)
    )
    product_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return product_id

def delete_product_from_db(product_id: int, user_id: int = None) -> bool:
    """Delete product and its subscriptions from database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Verify ownership if user_id is provided
        if user_id is not None:
            cursor.execute("SELECT user_id FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            if not row or row[0] != user_id:
                conn.close()
                return False
        
        # Delete associated subscriptions first
        cursor.execute("DELETE FROM subscriptions WHERE product_id = ?", (product_id,))
        # Delete product
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def create_subscription(product_id: int, frequency: str, is_active: bool = True, 
                       start_date: str = None, frequency_type: str = None,
                       frequency_value: int = None, frequency_unit: str = None,
                       specific_day_type: str = None, weekday: int = None, monthday: int = None,
                       frequency_preset: str = None, user_id: int = None) -> int:
    """Create a new subscription for a product"""
    # Calculate next buy date
    next_buy_date = calculate_next_buy_date(
        start_date, frequency_type, frequency_value, frequency_unit,
        specific_day_type, weekday, monthday, frequency_preset
    )
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO subscriptions 
           (product_id, frequency, is_active, created_at, start_date, frequency_type, 
            frequency_value, frequency_unit, specific_day_type, weekday, monthday, next_buy_date, user_id) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (product_id, frequency, 1 if is_active else 0, datetime.now().isoformat(),
         start_date, frequency_type, frequency_value, frequency_unit, 
         specific_day_type, weekday, monthday, next_buy_date, user_id)
    )
    subscription_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return subscription_id

def get_all_subscriptions(user_id: int = None) -> List[dict]:
    """Get all subscriptions with product details, optionally filtered by user_id"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if user_id is not None:
        cursor.execute("""
            SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, s.is_active, s.created_at, s.next_buy_date
            FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.user_id = ?
            ORDER BY s.created_at DESC
        """, (user_id,))
    else:
        cursor.execute("""
            SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, s.is_active, s.created_at, s.next_buy_date
            FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            ORDER BY s.created_at DESC
        """)
    
    rows = cursor.fetchall()
    conn.close()
    
    subscriptions = []
    for row in rows:
        # Format next_buy_date to dd.mm.yyyy
        next_buy_date_formatted = None
        if row[9]:
            try:
                date_obj = datetime.strptime(row[9], "%Y-%m-%d")
                next_buy_date_formatted = date_obj.strftime("%d.%m.%Y")
            except:
                next_buy_date_formatted = row[9]
        
        subscriptions.append({
            "id": row[0],
            "product_id": row[1],
            "product_name": row[2],
            "product_url": row[3],
            "product_image": row[4],
            "product_price": row[5],
            "frequency": row[6],
            "is_active": bool(row[7]),
            "created_at": datetime.fromisoformat(row[8]) if row[8] else datetime.now(),
            "next_buy_date": next_buy_date_formatted
        })
    return subscriptions

def get_active_subscriptions(user_id: int = None) -> List[dict]:
    """Get all active subscriptions, optionally filtered by user_id"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if user_id is not None:
        cursor.execute("""
            SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, s.created_at
            FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.is_active = 1 AND s.user_id = ?
            ORDER BY s.created_at DESC
        """, (user_id,))
    else:
        cursor.execute("""
            SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, s.created_at
            FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.is_active = 1
            ORDER BY s.created_at DESC
        """)
    
    rows = cursor.fetchall()
    conn.close()
    
    subscriptions = []
    for row in rows:
        subscriptions.append({
            "id": row[0],
            "product_id": row[1],
            "product_name": row[2],
            "product_url": row[3],
            "product_image": row[4],
            "product_price": row[5],
            "frequency": row[6],
            "created_at": datetime.fromisoformat(row[7]) if row[7] else datetime.now()
        })
    return subscriptions

def update_subscription_status(subscription_id: int, is_active: bool, user_id: int = None) -> bool:
    """Update subscription active status"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Verify ownership if user_id is provided
        if user_id is not None:
            cursor.execute("SELECT user_id FROM subscriptions WHERE id = ?", (subscription_id,))
            row = cursor.fetchone()
            if not row or row[0] != user_id:
                conn.close()
                return False
        
        cursor.execute(
            "UPDATE subscriptions SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, subscription_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def update_next_buy_date(subscription_id: int) -> bool:
    """Update the next buy date for a subscription based on current date"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get subscription details
        cursor.execute("""
            SELECT start_date, frequency_type, frequency_value, frequency_unit, 
                   specific_day_type, weekday, monthday, frequency
            FROM subscriptions WHERE id = ?
        """, (subscription_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return False
        
        start_date, frequency_type, frequency_value, frequency_unit, specific_day_type, weekday, monthday, frequency = row
        
        # Extract preset from frequency if it's a preset type
        frequency_preset = frequency if frequency_type == "preset" else None
        
        # Calculate new next buy date
        next_buy_date = calculate_next_buy_date(
            start_date, frequency_type, frequency_value, frequency_unit,
            specific_day_type, weekday, monthday, frequency_preset
        )
        
        # Update the database
        cursor.execute(
            "UPDATE subscriptions SET next_buy_date = ? WHERE id = ?",
            (next_buy_date, subscription_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating next buy date: {e}")
        return False

def update_all_next_buy_dates():
    """Update next buy dates for all subscriptions"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM subscriptions")
    subscription_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    for sub_id in subscription_ids:
        update_next_buy_date(sub_id)

def delete_subscription_from_db(subscription_id: int, user_id: int = None) -> bool:
    """Delete a subscription from the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Verify ownership if user_id is provided
        if user_id is not None:
            cursor.execute("SELECT user_id FROM subscriptions WHERE id = ?", (subscription_id,))
            row = cursor.fetchone()
            if not row or row[0] != user_id:
                conn.close()
                return False
        
        cursor.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def get_subscription_by_id(subscription_id: int, user_id: int = None) -> Optional[dict]:
    """Get a subscription by ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if user_id is not None:
        cursor.execute("""
            SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, 
                   s.is_active, s.created_at, s.next_buy_date, s.start_date, s.frequency_type,
                   s.frequency_value, s.frequency_unit, s.specific_day_type, s.weekday, s.monthday
            FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.id = ? AND s.user_id = ?
        """, (subscription_id, user_id))
    else:
        cursor.execute("""
            SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, 
                   s.is_active, s.created_at, s.next_buy_date, s.start_date, s.frequency_type,
                   s.frequency_value, s.frequency_unit, s.specific_day_type, s.weekday, s.monthday
            FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.id = ?
        """, (subscription_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        next_buy_date_formatted = None
        if row[9]:
            try:
                date_obj = datetime.strptime(row[9], "%Y-%m-%d")
                next_buy_date_formatted = date_obj.strftime("%d.%m.%Y")
            except:
                next_buy_date_formatted = row[9]
        
        # Format created_at as string for JSON serialization
        created_at_str = row[8] if row[8] else datetime.now().isoformat()
        
        return {
            "id": row[0],
            "product_id": row[1],
            "product_name": row[2],
            "product_url": row[3],
            "product_image": row[4],
            "product_price": row[5],
            "frequency": row[6],
            "is_active": bool(row[7]),
            "created_at": created_at_str,
            "next_buy_date": next_buy_date_formatted,
            "start_date": row[10],
            "frequency_type": row[11],
            "frequency_value": row[12],
            "frequency_unit": row[13],
            "specific_day_type": row[14],
            "weekday": row[15],
            "monthday": row[16]
        }
    return None

def update_subscription(subscription_id: int, frequency: str, start_date: str = None,
                       is_active: bool = True, user_id: int = None) -> bool:
    """Update an existing subscription"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Verify ownership if user_id is provided
        if user_id is not None:
            cursor.execute("SELECT user_id FROM subscriptions WHERE id = ?", (subscription_id,))
            row = cursor.fetchone()
            if not row or row[0] != user_id:
                conn.close()
                return False
        
        # Calculate next buy date
        next_buy_date = calculate_next_buy_date(
            start_date, "preset", None, None, None, None, None, frequency
        )
        
        cursor.execute("""
            UPDATE subscriptions 
            SET frequency = ?, start_date = ?, is_active = ?, next_buy_date = ?,
                frequency_type = ?
            WHERE id = ?
        """, (frequency, start_date, 1 if is_active else 0, next_buy_date, "preset", subscription_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating subscription: {e}")
        return False

def update_product_status(product_id: int, is_active: bool) -> bool:
    """Update product active status - DEPRECATED, use subscriptions instead"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE products SET is_active = ? WHERE id = ?",
            (is_active, product_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

        return False

# Initialize database on startup
init_db()

# Initialize APScheduler for daily email job
scheduler = BackgroundScheduler()

def run_email_job():
    """Function to run the email_job.py script"""
    try:
        # Get the path to email_job.py
        app_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(app_dir)
        email_job_path = os.path.join(project_root, "email_job.py")
        
        print(f"Running email job at {datetime.now()}")
        
        # Run the email_job.py script
        result = subprocess.run(
            [sys.executable, email_job_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=project_root
        )
        
        if result.returncode == 0:
            print(f"✅ Email job completed successfully")
            print(result.stdout)
        else:
            print(f"❌ Email job failed with error:")
            print(result.stderr)
            
    except Exception as e:
        print(f"❌ Error running email job: {str(e)}")

# Schedule the email job to run daily at 9:00 AM
scheduler.add_job(
    run_email_job,
    trigger=CronTrigger(hour=9, minute=0),  # Run at 9:00 AM every day
    id='daily_email_job',
    name='Send daily subscription reminder emails',
    replace_existing=True
)

# Start the scheduler
scheduler.start()
print("✅ Scheduler started - Email job will run daily at 9:00 AM")

# Session storage (replace with Redis or database later)
sessions = {}
pending_2fa = {}  # Temporary storage for pending 2FA logins

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

def translate_frequency_to_german(frequency_str: str) -> str:
    """Translate frequency string to German"""
    if not frequency_str:
        return frequency_str
    
    # Translation mappings - order matters! Check plurals first
    translations = [
        (' years', ' Jahre'),
        (' year', ' Jahr'),
        (' months', ' Monate'),
        (' month', ' Monat'),
        (' weeks', ' Wochen'),
        (' week', ' Woche'),
        (' days', ' Tage'),
        (' day', ' Tag')
    ]
    
    # Replace English terms with German
    result = frequency_str
    for eng, ger in translations:
        result = result.replace(eng, ger)
    
    return result

# Add custom filter to Jinja2
templates.env.filters['german_frequency'] = translate_frequency_to_german

class Product(BaseModel):
    id: int
    url: str
    name: str
    added_at: datetime
    is_active: bool = False

def get_current_user(request: Request) -> Optional[str]:
    session_token = request.cookies.get("session_token")
    if session_token and session_token in sessions:
        return sessions[session_token]["email"]
    return None

def get_current_user_id(request: Request) -> Optional[int]:
    """Get the current user's ID from the session"""
    email = get_current_user(request)
    if email:
        user = get_user_by_email(email)
        if user:
            return user["id"]
    return None

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    user = get_user_by_email(email)
    if not user:
        return RedirectResponse(url="/login?error=1", status_code=303)
    
    if not verify_password(password, user["hashed_password"]):
        return RedirectResponse(url="/login?error=1", status_code=303)
    
    # Log in directly without 2FA
    session_token = secrets.token_urlsafe(32)
    sessions[session_token] = {
        "email": email,
        "created_at": datetime.now()
    }
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    return response

@app.get("/verify-2fa", response_class=HTMLResponse)
async def verify_2fa_page(request: Request):
    pending_token = request.cookies.get("pending_2fa_token")
    if not pending_token or pending_token not in pending_2fa:
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("verify_2fa.html", {"request": request})

@app.post("/verify-2fa")
async def verify_2fa(request: Request, code: str = Form(...)):
    pending_token = request.cookies.get("pending_2fa_token")
    
    if not pending_token or pending_token not in pending_2fa:
        return RedirectResponse(url="/login?error=1", status_code=303)
    
    pending_info = pending_2fa[pending_token]
    user = get_user_by_id(pending_info["user_id"])
    
    if not user:
        return RedirectResponse(url="/login?error=1", status_code=303)
    
    # Verify the code
    if not verify_code(user["id"], code):
        return RedirectResponse(url="/verify-2fa?error=invalid_code", status_code=303)
    
    # Code is valid, create session
    session_token = secrets.token_urlsafe(32)
    sessions[session_token] = {
        "username": user["username"],
        "created_at": datetime.now()
    }
    
    # Clean up pending 2FA
    del pending_2fa[pending_token]
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    response.delete_cookie(key="pending_2fa_token")
    return response

@app.get("/logout")
async def logout(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token in sessions:
        del sessions[session_token]
    
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session_token")
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(email: str = Form(...), password: str = Form(...), password_confirm: str = Form(...)):
    # Validate inputs
    if get_user_by_email(email):
        return RedirectResponse(url="/register?error=email_exists", status_code=303)
    
    # Validate email format (basic check)
    if "@" not in email or "." not in email:
        return RedirectResponse(url="/register?error=invalid_email", status_code=303)
    
    if len(password) < 6:
        return RedirectResponse(url="/register?error=password_short", status_code=303)
    
    if password != password_confirm:
        return RedirectResponse(url="/register?error=password_mismatch", status_code=303)
    
    # Create new user - use email as username too
    if not create_user(email, email, password):
        return RedirectResponse(url="/register?error=email_exists", status_code=303)
    
    # Auto-login after registration
    session_token = secrets.token_urlsafe(32)
    sessions[session_token] = {
        "email": email,
        "created_at": datetime.now()
    }
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
    return response

@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("change_password.html", {"request": request, "username": user})

@app.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_data = get_user_by_email(user)
    if not user_data:
        return RedirectResponse(url="/login", status_code=303)
    
    # Verify current password
    if not verify_password(current_password, user_data["hashed_password"]):
        return RedirectResponse(url="/change-password?error=wrong_password", status_code=303)
    
    # Validate new password
    if len(new_password) < 6:
        return RedirectResponse(url="/change-password?error=password_short", status_code=303)
    
    if new_password != new_password_confirm:
        return RedirectResponse(url="/change-password?error=password_mismatch", status_code=303)
    
    # Update password
    if not update_user_password(user, new_password):
        return RedirectResponse(url="/change-password?error=update_failed", status_code=303)
    
    return RedirectResponse(url="/change-password?success=1", status_code=303)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = get_current_user_id(request)
    
    # Update next buy dates for all subscriptions
    update_all_next_buy_dates()
    
    all_products = get_all_products(user_id)
    all_subscriptions = get_all_subscriptions(user_id)
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "all_products": all_products,
        "all_subscriptions": all_subscriptions,
        "username": user
    })

@app.post("/preview-product")
async def preview_product(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)
    
    try:
        data = await request.json()
        url = data.get("url")
        
        if not url:
            return JSONResponse({"success": False, "error": "URL is required"})
        
        # Scrape product data from URL
        product_data = recognize_products(url)
        
        if product_data:
            return JSONResponse({
                "success": True,
                "title": product_data.get("title", "Unknown Product"),
                "image_url": product_data.get("image_url"),
                "price": product_data.get("price")
            })
        else:
            return JSONResponse({"success": False, "error": "Could not load product data"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/add-product")
async def add_product(request: Request, url: str = Form(...), title: str = Form(...), image_url: str = Form(None), price: str = Form(None)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = get_current_user_id(request)
    
    # Add product with already-scraped data
    add_product_to_db(url, title, image_url, price, user_id)
    
    return RedirectResponse(url="/", status_code=303)

@app.post("/create-subscription")
async def create_subscription_route(
    request: Request, 
    product_id: int = Form(...), 
    start_date: str = Form(...),
    frequency: str = Form(...),
    activate: Optional[str] = Form(None)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = get_current_user_id(request)
    
    # Checkbox will send "on" if checked, None if unchecked
    is_active = activate == "on"
    
    create_subscription(
        product_id=product_id,
        frequency=frequency,
        is_active=is_active,
        start_date=start_date,
        frequency_type="preset",
        frequency_value=None,
        frequency_unit=None,
        specific_day_type=None,
        weekday=None,
        monthday=None,
        frequency_preset=frequency,
        user_id=user_id
    )
    return RedirectResponse(url="/", status_code=303)

@app.post("/activate-subscription/{subscription_id}")
async def activate_subscription(request: Request, subscription_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = get_current_user_id(request)
    update_subscription_status(subscription_id, True, user_id)
    return RedirectResponse(url="/", status_code=303)

@app.post("/deactivate-subscription/{subscription_id}")
async def deactivate_subscription(request: Request, subscription_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = get_current_user_id(request)
    update_subscription_status(subscription_id, False, user_id)
    return RedirectResponse(url="/", status_code=303)

@app.delete("/delete-subscription/{subscription_id}")
async def delete_subscription(request: Request, subscription_id: int):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = get_current_user_id(request)
    success = delete_subscription_from_db(subscription_id, user_id)
    if not success:
        raise HTTPException(status_code=403, detail="Not authorized to delete this subscription")
    return {"success": True}

@app.get("/get-subscription/{subscription_id}")
async def get_subscription(request: Request, subscription_id: int):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = get_current_user_id(request)
    subscription = get_subscription_by_id(subscription_id, user_id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    return JSONResponse(subscription)

@app.post("/update-subscription/{subscription_id}")
async def update_subscription_route(
    request: Request,
    subscription_id: int,
    frequency: str = Form(...),
    start_date: str = Form(...),
    activate: Optional[str] = Form(None)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = get_current_user_id(request)
    is_active = activate == "on"
    
    success = update_subscription(subscription_id, frequency, start_date, is_active, user_id)
    
    if not success:
        raise HTTPException(status_code=403, detail="Not authorized to update this subscription")
    
    return RedirectResponse(url="/", status_code=303)

@app.post("/add-to-cart/{subscription_id}")
async def add_subscription_to_cart(request: Request, subscription_id: int):
    """Add a single subscription product to Digitec cart"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = get_current_user_id(request)
    
    try:
        # Get subscription details - verify ownership
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.url FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.id = ? AND s.user_id = ?
        """, (subscription_id, user_id))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return JSONResponse({"success": False, "message": "Abo nicht gefunden"}, status_code=404)
        
        product_url = row[0]
        
        # Get Digitec credentials from environment or database
        # For now, using environment variables
        digitec_email = os.getenv("DIGITEC_EMAIL")
        digitec_password = os.getenv("DIGITEC_PASSWORD")
        
        # Add to cart
        result = add_product_to_cart(product_url, digitec_email, digitec_password)
        
        return JSONResponse(result)
        
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@app.post("/add-all-active-to-cart")
async def add_all_active_subscriptions_to_cart(request: Request):
    """Add all active subscriptions to Digitec cart"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = get_current_user_id(request)
    
    try:
        # Get all active subscriptions for this user
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.url FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.is_active = 1 AND s.user_id = ?
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return JSONResponse({"success": False, "message": "Keine aktiven Abos gefunden"})
        
        product_urls = [row[0] for row in rows]
        
        # Get Digitec credentials
        digitec_email = os.getenv("DIGITEC_EMAIL")
        digitec_password = os.getenv("DIGITEC_PASSWORD")
        
        # Add all to cart
        result = add_multiple_products_to_cart(product_urls, digitec_email, digitec_password)
        
        return JSONResponse(result)
        
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@app.post("/activate/{product_id}")
async def activate_product(request: Request, product_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    update_product_status(product_id, True)
    return RedirectResponse(url="/", status_code=303)

@app.post("/deactivate/{product_id}")
async def deactivate_product(request: Request, product_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    update_product_status(product_id, False)
    return RedirectResponse(url="/", status_code=303)

@app.delete("/delete/{product_id}")
async def delete_product(request: Request, product_id: int):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = get_current_user_id(request)
    success = delete_product_from_db(product_id, user_id)
    if not success:
        raise HTTPException(status_code=403, detail="Not authorized to delete this product")
    return {"success": True}

@app.get("/api/products")
async def get_products(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {"products": get_all_products()}


@app.post("/send")
def send_mail(payload: MailIn, bg: BackgroundTasks):
    # send in background to keep API snappy
    bg.add_task(send_email, payload.to, payload.subject, payload.text, payload.html)
    return {"status": "queued"}

@app.post("/send-subscription-email")
async def send_subscription_email_route(request: Request):
    """Run the email_job.py script to send emails to users with subscriptions due tomorrow"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        # Get the path to email_job.py
        # __file__ is the path to main.py in the app directory
        current_file = os.path.abspath(__file__)  # C:\...\AutoBuyer\app\main.py
        app_dir = os.path.dirname(current_file)    # C:\...\AutoBuyer\app
        project_root = os.path.dirname(app_dir)     # C:\...\AutoBuyer
        email_job_path = os.path.join(project_root, "email_job.py")
        
        # Debug logging
        print(f"Current file: {current_file}")
        print(f"App dir: {app_dir}")
        print(f"Project root: {project_root}")
        print(f"Email job path: {email_job_path}")
        print(f"File exists: {os.path.exists(email_job_path)}")
        
        # Check if file exists
        if not os.path.exists(email_job_path):
            return JSONResponse({
                "success": False,
                "message": f"email_job.py nicht gefunden: {email_job_path}"
            })
        
        print(f"Running email job manually at {datetime.now()}")
        
        # Run the email_job.py script using the same Python interpreter
        result = subprocess.run(
            [sys.executable, email_job_path],
            capture_output=True,
            text=True,
            timeout=60,  # 60 second timeout
            cwd=project_root  # Set working directory to project root
        )
        
        if result.returncode == 0:
            # Parse output to get summary
            output = result.stdout
            return JSONResponse({
                "success": True,
                "message": "E-Mails erfolgreich versendet",
                "output": output
            })
        else:
            return JSONResponse({
                "success": False,
                "message": f"Fehler beim Versenden: {result.stderr}",
                "output": result.stdout
            })
    except subprocess.TimeoutExpired:
        return JSONResponse({
            "success": False,
            "message": "Zeitüberschreitung beim Versenden der E-Mails"
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "message": f"Fehler: {str(e)}"
        })

@app.get("/email-preview", response_class=HTMLResponse)
async def email_preview(request: Request):
    """Generate an email preview with all active user subscriptions"""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    user_id = get_current_user_id(request)
    
    # Get all active subscriptions for the user
    subscriptions = get_active_subscriptions(user_id)
    
    # Read the email template
    template_path = os.path.join(os.path.dirname(__file__), "templates", "E-Mail-Template.html")
    with open(template_path, 'r', encoding='utf-8') as f:
        email_html = f.read()
    
    # Replace year placeholder
    from datetime import datetime
    current_year = datetime.now().year
    email_html = email_html.replace('{{Jahr}}', str(current_year))
    
    # Replace logo with correct path (logo in static folder)
    # Use absolute URL for email compatibility
    logo_url = request.url_for('static', path='Logo_rot.png')
    email_html = email_html.replace('https://via.placeholder.com/120/FFFFFF/8C1736?text=LOGO', str(logo_url))
    
    # Remove the tip paragraph
    import re
    tip_pattern = r'<p class="text" style="margin:16px 0 0 0; font-size:13px; opacity:\.8;">.*?</p>'
    email_html = re.sub(tip_pattern, '', email_html, flags=re.DOTALL)
    
    # Generate table rows for subscriptions
    if subscriptions:
        # Build table rows HTML
        table_rows = ""
        for sub in subscriptions:
            # Default values if data is missing
            title = sub.get('product_name', 'Unbekanntes Produkt')
            image_url = sub.get('product_image') or 'https://via.placeholder.com/64/FFFFFF/8C1736?text=IMG'
            price = sub.get('product_price', 'N/A')
            if price and price != 'N/A':
                price = f"CHF {price}"
            product_url = sub.get('product_url', '#')
            
            row_html = f"""
                  <tr>
                    <td class="table-pad" style="padding:12px 14px; border-bottom:1px solid #EAC5D3;">
                      <p class="text" style="margin:0; font-family:'Poppins', Arial, Helvetica, sans-serif;">{title}</p>
                    </td>
                    <td class="table-pad" style="padding:12px 14px; border-bottom:1px solid #EAC5D3;">
                      <img class="img-64" src="{image_url}" width="64" height="64" alt="{title} Bild" style="border-radius:8px; background:#FFFFFF;">
                    </td>
                    <td class="table-pad" style="padding:12px 14px; border-bottom:1px solid #EAC5D3;">
                      <p class="text" style="margin:0; font-family:'Poppins', Arial, Helvetica, sans-serif;">{price}</p>
                    </td>
                    <td class="table-pad" style="padding:12px 14px; border-bottom:1px solid #EAC5D3;">
                      <a href="{product_url}" target="_blank" rel="noopener" class="btn">jetzt bestellen</a>
                    </td>
                  </tr>"""
            table_rows += row_html
        
        # Find the placeholder rows in template and replace them
        # The template has example rows between <!-- ZEILEN -> and <!-- /ZEILEN -->
        import re
        pattern = r'<!-- ZEILEN -> Dupliziere/ersetze ab hier pro Bestellung -->.*?<!-- /ZEILEN -->'
        replacement = f'<!-- ZEILEN -> Dupliziere/ersetze ab hier pro Bestellung -->\n{table_rows}\n                  <!-- /ZEILEN -->'
        email_html = re.sub(pattern, replacement, email_html, flags=re.DOTALL)
    
    # Replace unsubscribe URL placeholder
    email_html = email_html.replace('{{UNSUBSCRIBE_URL}}', '#')
    
    # Return the rendered HTML
    return HTMLResponse(content=email_html)


# Shutdown event to stop the scheduler
@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    print("✅ Scheduler stopped")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


