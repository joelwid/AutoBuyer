from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
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

# Load environment variables
load_dotenv()

app = FastAPI(title="AutoBuyer")

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
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 0,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
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
    cursor.execute(
        "SELECT id, url, name, added_at, is_active FROM products ORDER BY added_at DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    
    products = []
    for row in rows:
        products.append({
            "id": row[0],
            "url": row[1],
            "name": row[2],
            "added_at": datetime.fromisoformat(row[3]) if row[3] else datetime.now(),
            "is_active": bool(row[4])
        })
    return products

def add_product_to_db(url: str, name: str) -> int:
    """Add a new product to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO products (url, name, added_at, is_active) VALUES (?, ?, ?, ?)",
        (url, name, datetime.now().isoformat(), False)
    )
    product_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return product_id

def update_product_status(product_id: int, is_active: bool) -> bool:
    """Update product active status"""
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

def delete_product_from_db(product_id: int) -> bool:
    """Delete product from database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

# Initialize database on startup
init_db()

# Session storage (replace with Redis or database later)
sessions = {}
pending_2fa = {}  # Temporary storage for pending 2FA logins

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

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
    
    all_products = get_all_products()
    active_products = [p for p in all_products if p["is_active"]]
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_products": active_products,
        "all_products": all_products,
        "username": user
    })

@app.post("/add-product")
async def add_product(request: Request, url: str = Form(...), name: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    add_product_to_db(url, name)
    return RedirectResponse(url="/", status_code=303)

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
