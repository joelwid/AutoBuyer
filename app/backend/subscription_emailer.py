"""
Subscription email sending functionality
Handles generating and sending subscription reminder emails
"""

import os
import re
import sqlite3
from datetime import datetime
from typing import List, Optional
from .emailer import send_email

# Database path - will be set from main.py
DB_PATH = None

def set_db_path(path: str):
    """Set the database path"""
    global DB_PATH
    DB_PATH = path

def get_active_subscriptions(user_id: int) -> List[dict]:
    """Get all active subscriptions for a user"""
    if not DB_PATH:
        raise RuntimeError("Database path not set")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, s.created_at
        FROM subscriptions s
        JOIN products p ON s.product_id = p.id
        WHERE s.is_active = 1 AND s.user_id = ?
        ORDER BY s.created_at DESC
    """, (user_id,))
    
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

def get_subscriptions_due_date(user_id: int, target_date: datetime) -> List[dict]:
    """Get subscriptions for a user that are due on a specific date"""
    if not DB_PATH:
        raise RuntimeError("Database path not set")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT s.id, s.product_id, p.name, p.url, p.image_url, p.price, s.frequency, s.created_at
        FROM subscriptions s
        JOIN products p ON s.product_id = p.id
        WHERE s.is_active = 1 AND s.user_id = ?
        ORDER BY s.created_at DESC
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    from datetime import timedelta
    
    def get_next_buy_date(created_at: datetime, frequency: int) -> datetime:
        """Calculate next buy date for a subscription"""
        days_since_creation = (datetime.now() - created_at).days
        days_until_next = frequency - (days_since_creation % frequency)
        next_buy_date = datetime.now() + timedelta(days=days_until_next)
        return next_buy_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    subscriptions = []
    target_date_normalized = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    for row in rows:
        try:
            created_at = datetime.fromisoformat(row[7]) if row[7] else datetime.now()
            frequency = int(row[6]) if isinstance(row[6], (int, str)) and str(row[6]).isdigit() else None
            
            if frequency:
                next_buy = get_next_buy_date(created_at, frequency)
                
                # Check if this subscription is due on the target date
                if next_buy.date() == target_date_normalized.date():
                    subscriptions.append({
                        "id": row[0],
                        "product_id": row[1],
                        "product_name": row[2],
                        "product_url": row[3],
                        "product_image": row[4],
                        "product_price": row[5],
                        "frequency": row[6],
                        "created_at": created_at
                    })
        except (ValueError, TypeError) as e:
            print(f"Error processing subscription {row[0]}: {e}")
            continue
    
    return subscriptions

def generate_subscription_email_html(subscriptions: List[dict], base_url: str, template_path: str) -> str:
    """Generate HTML email from template with subscription data"""
    
    # Read the email template
    with open(template_path, 'r', encoding='utf-8') as f:
        email_html = f.read()
    
    # Replace year placeholder
    current_year = datetime.now().year
    email_html = email_html.replace('{{Jahr}}', str(current_year))
    
    # Replace logo with absolute URL
    logo_url = f"{base_url}/static/Logo_rot.png"
    email_html = email_html.replace('https://via.placeholder.com/120/FFFFFF/8C1736?text=LOGO', logo_url)
    
    # Remove the tip paragraph
    tip_pattern = r'<p class="text" style="margin:16px 0 0 0; font-size:13px; opacity:\.8;">.*?</p>'
    email_html = re.sub(tip_pattern, '', email_html, flags=re.DOTALL)
    
    # Generate table rows for subscriptions
    table_rows = ""
    for sub in subscriptions:
        # Default values if data is missing
        title = sub.get('product_name', 'Unbekanntes Produkt')
        image_url = sub.get('product_image')
        
        # Make image URLs absolute
        if image_url and not image_url.startswith('http'):
            image_url = f"{base_url}{image_url}" if image_url.startswith('/') else f"{base_url}/{image_url}"
        elif not image_url:
            image_url = 'https://via.placeholder.com/64/FFFFFF/8C1736?text=IMG'
        
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
    pattern = r'<!-- ZEILEN -> Dupliziere/ersetze ab hier pro Bestellung -->.*?<!-- /ZEILEN -->'
    replacement = f'<!-- ZEILEN -> Dupliziere/ersetze ab hier pro Bestellung -->\n{table_rows}\n                  <!-- /ZEILEN -->'
    email_html = re.sub(pattern, replacement, email_html, flags=re.DOTALL)
    
    # Replace unsubscribe URL placeholder
    email_html = email_html.replace('{{UNSUBSCRIBE_URL}}', '#')
    
    return email_html

def send_subscription_reminder_email(user_email: str, user_id: int, base_url: str, template_path: str, target_date: Optional[datetime] = None) -> dict:
    """
    Send subscription reminder email to a user
    
    Args:
        user_email: Email address to send to
        user_id: User ID to fetch subscriptions for
        base_url: Base URL for absolute links (e.g., http://localhost:8000)
        template_path: Path to email template file
        target_date: Optional specific date to check for subscriptions (defaults to all active subscriptions)
    
    Returns:
        dict with success status and message
    """
    
    # Get subscriptions - either all active or only those due on target_date
    if target_date:
        subscriptions = get_subscriptions_due_date(user_id, target_date)
    else:
        subscriptions = get_active_subscriptions(user_id)
    
    if not subscriptions:
        return {
            "success": False,
            "message": "Keine aktiven Abos gefunden" if not target_date else "Keine Abos für dieses Datum gefunden"
        }
    
    # Generate email HTML
    email_html = generate_subscription_email_html(subscriptions, base_url, template_path)
    
    # Send the email
    try:
        send_email(
            to=user_email,
            subject="Erinnerung an dein Abo bei MyAboabo.ch",
            text="Folgende deiner Bestellungen sind demnächst fällig",
            html=email_html
        )
        return {
            "success": True,
            "message": f"E-Mail erfolgreich an {user_email} gesendet"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Fehler beim Senden der E-Mail: {str(e)}"
        }
