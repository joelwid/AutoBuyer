from fastapi import FastAPI, Request, Form, HTTPException, status
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
import random
import aiosmtplib
from email.message import EmailMessage
from dotenv import load_dotenv

from app.backend.recognize_products import recognize_products
from app.backend.add_to_cart import add_product_to_cart, add_multiple_products_to_cart
# Load environment variables
load_dotenv()

app = FastAPI(title="MyAboabo")



# Security configuration
SECRET_KEY = secrets.token_urlsafe(32)




# Email configuration (configure these with your SMTP settings)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")  # Set your email
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # Set your app password
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)

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

def update_user_password(username: str, new_password: str) -> bool:
    """Update user password in database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        hashed_pw = hash_password(new_password)
        cursor.execute(
            "UPDATE users SET hashed_password = ? WHERE username = ?",
            (hashed_pw, username)
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

def get_all_products() -> List[dict]:
    """Get all products from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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

def add_product_to_db(url: str, name: str, image_url: str = None, price: str = None) -> int:
    """Add a new product to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO products (url, name, image_url, price, added_at) VALUES (?, ?, ?, ?, ?)",
        (url, name, image_url, price, datetime.now().isoformat())
    )
    product_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return product_id

def delete_product_from_db(product_id: int) -> bool:
    """Delete product and its subscriptions from database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
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
                       frequency_preset: str = None) -> int:
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
            frequency_value, frequency_unit, specific_day_type, weekday, monthday, next_buy_date) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (product_id, frequency, 1 if is_active else 0, datetime.now().isoformat(),
         start_date, frequency_type, frequency_value, frequency_unit, 
         specific_day_type, weekday, monthday, next_buy_date)
    )
    subscription_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return subscription_id

def get_all_subscriptions() -> List[dict]:
    """Get all subscriptions with product details"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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

def get_active_subscriptions() -> List[dict]:
    """Get all active subscriptions"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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

def update_subscription_status(subscription_id: int, is_active: bool) -> bool:
    """Update subscription active status"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
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

def delete_subscription_from_db(subscription_id: int) -> bool:
    """Delete a subscription from the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
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
        return sessions[session_token]["username"]
    return None

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    user = get_user_by_username(username)
    if not user:
        return RedirectResponse(url="/login?error=1", status_code=303)
    
    if not verify_password(password, user["hashed_password"]):
        return RedirectResponse(url="/login?error=1", status_code=303)
    
    # Check if 2FA is enabled
    if user["two_factor_enabled"]:
        # Generate and send verification code
        code = create_verification_code(user["id"])
        await send_verification_email(user["email"], code, user["username"])
        
        # Store pending login
        temp_token = secrets.token_urlsafe(32)
        pending_2fa[temp_token] = {
            "user_id": user["id"],
            "created_at": datetime.now()
        }
        
        response = RedirectResponse(url="/verify-2fa", status_code=303)
        response.set_cookie(key="pending_2fa_token", value=temp_token, httponly=True, max_age=600)
        return response
    
    # No 2FA, log in directly
    session_token = secrets.token_urlsafe(32)
    sessions[session_token] = {
        "username": username,
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
async def register(username: str = Form(...), email: str = Form(...), password: str = Form(...), password_confirm: str = Form(...)):
    # Validate inputs
    if get_user_by_username(username):
        return RedirectResponse(url="/register?error=user_exists", status_code=303)
    
    if len(username) < 3:
        return RedirectResponse(url="/register?error=username_short", status_code=303)
    
    if len(password) < 6:
        return RedirectResponse(url="/register?error=password_short", status_code=303)
    
    if password != password_confirm:
        return RedirectResponse(url="/register?error=password_mismatch", status_code=303)
    
    # Validate email format (basic check)
    if "@" not in email or "." not in email:
        return RedirectResponse(url="/register?error=invalid_email", status_code=303)
    
    # Create new user
    if not create_user(username, email, password):
        return RedirectResponse(url="/register?error=email_exists", status_code=303)
    
    # Auto-login after registration
    session_token = secrets.token_urlsafe(32)
    sessions[session_token] = {
        "username": username,
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
    
    user_data = get_user_by_username(user)
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
    
    # Update next buy dates for all subscriptions
    update_all_next_buy_dates()
    
    all_products = get_all_products()
    all_subscriptions = get_all_subscriptions()
    
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
    
    # Add product with already-scraped data
    add_product_to_db(url, title, image_url, price)
    
    return RedirectResponse(url="/", status_code=303)

@app.post("/create-subscription")
async def create_subscription_route(
    request: Request, 
    product_id: int = Form(...), 
    start_date: str = Form(...),
    frequency_type: str = Form(...),
    frequency_preset: Optional[str] = Form(None),
    frequency_value: Optional[int] = Form(None),
    frequency_unit: Optional[str] = Form(None),
    specific_day_type: Optional[str] = Form(None),
    weekday: Optional[int] = Form(None),
    monthday: Optional[int] = Form(None),
    activate: Optional[str] = Form(None)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Build frequency string
    if frequency_type == "preset":
        frequency = frequency_preset
    elif frequency_type == "custom":
        frequency = f"{frequency_value} {frequency_unit}"
    else:
        frequency = "custom"
    
    # Checkbox will send "on" if checked, None if unchecked
    is_active = activate == "on"
    
    create_subscription(
        product_id=product_id,
        frequency=frequency,
        is_active=is_active,
        start_date=start_date,
        frequency_type=frequency_type,
        frequency_value=frequency_value,
        frequency_unit=frequency_unit,
        specific_day_type=specific_day_type if specific_day_type else None,
        weekday=weekday,
        monthday=monthday,
        frequency_preset=frequency_preset
    )
    return RedirectResponse(url="/", status_code=303)

@app.post("/activate-subscription/{subscription_id}")
async def activate_subscription(request: Request, subscription_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    update_subscription_status(subscription_id, True)
    return RedirectResponse(url="/", status_code=303)

@app.post("/deactivate-subscription/{subscription_id}")
async def deactivate_subscription(request: Request, subscription_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    update_subscription_status(subscription_id, False)
    return RedirectResponse(url="/", status_code=303)

@app.delete("/delete-subscription/{subscription_id}")
async def delete_subscription(request: Request, subscription_id: int):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    delete_subscription_from_db(subscription_id)
    return {"success": True}

@app.post("/add-to-cart/{subscription_id}")
async def add_subscription_to_cart(request: Request, subscription_id: int):
    """Add a single subscription product to Digitec cart"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        # Get subscription details
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.url FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.id = ?
        """, (subscription_id,))
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
    
    try:
        # Get all active subscriptions
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.url FROM subscriptions s
            JOIN products p ON s.product_id = p.id
            WHERE s.is_active = 1
        """)
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
    
    delete_product_from_db(product_id)
    return {"success": True}

@app.get("/api/products")
async def get_products(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {"products": get_all_products()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


