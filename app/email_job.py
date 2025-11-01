"""
Email job script for sending daily subscription reminders
This script should be run daily (e.g., via cron job) to send reminder emails
to users who have subscriptions due the next day.
"""

import os
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Add the current directory to the Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from backend.subscription_emailer import (
    set_db_path,
    send_subscription_reminder_email
)

# Configuration
DB_PATH = Path(__file__).parent / "autobuyer.db"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "E-Mail-Template.html"
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def get_next_buy_date(created_at: datetime, frequency: int) -> datetime:
    """
    Calculate the next buy date for a subscription
    
    Args:
        created_at: When the subscription was created
        frequency: Number of days between purchases
        
    Returns:
        The next buy date
    """
    days_since_creation = (datetime.now() - created_at).days
    days_until_next = frequency - (days_since_creation % frequency)
    next_buy_date = datetime.now() + timedelta(days=days_until_next)
    return next_buy_date.replace(hour=0, minute=0, second=0, microsecond=0)


def get_users_with_subscriptions_due_tomorrow() -> list:
    """
    Get all users who have at least one subscription due tomorrow
    
    Returns:
        List of tuples (user_id, user_email)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all active subscriptions
    cursor.execute("""
        SELECT DISTINCT u.id, u.email, s.created_at, s.frequency
        FROM users u
        JOIN subscriptions s ON u.id = s.user_id
        WHERE s.is_active = 1
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    # Calculate tomorrow's date (midnight)
    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Check which users have subscriptions due tomorrow
    users_due = {}
    
    for user_id, user_email, created_at_str, frequency in rows:
        try:
            created_at = datetime.fromisoformat(created_at_str)
            next_buy = get_next_buy_date(created_at, frequency)
            
            # Check if next buy is tomorrow
            if next_buy.date() == tomorrow.date():
                if user_id not in users_due:
                    users_due[user_id] = user_email
        except (ValueError, TypeError) as e:
            print(f"Error processing subscription for user {user_id}: {e}")
            continue
    
    return [(user_id, email) for user_id, email in users_due.items()]


def send_daily_reminders():
    """
    Main function to send daily reminder emails to users with subscriptions due tomorrow
    """
    # Set the database path for the subscription emailer module
    set_db_path(str(DB_PATH))
    
    print(f"Starting daily email job at {datetime.now()}")
    print(f"Database: {DB_PATH}")
    print(f"Template: {TEMPLATE_PATH}")
    print(f"Base URL: {BASE_URL}")
    
    # Get users with subscriptions due tomorrow
    users_to_notify = get_users_with_subscriptions_due_tomorrow()
    
    if not users_to_notify:
        print("No users with subscriptions due tomorrow")
        return
    
    print(f"Found {len(users_to_notify)} users with subscriptions due tomorrow")
    
    # Send emails to each user
    success_count = 0
    error_count = 0
    
    for user_id, user_email in users_to_notify:
        try:
            print(f"Sending email to {user_email} (user_id: {user_id})...")
            
            result = send_subscription_reminder_email(
                user_email=user_email,
                user_id=user_id,
                base_url=BASE_URL,
                template_path=str(TEMPLATE_PATH)
            )
            
            if result["success"]:
                print(f"✓ Successfully sent email to {user_email}")
                success_count += 1
            else:
                print(f"✗ Failed to send email to {user_email}: {result['message']}")
                error_count += 1
                
        except Exception as e:
            print(f"✗ Error sending email to {user_email}: {str(e)}")
            error_count += 1
    
    print("\n" + "="*50)
    print(f"Email job completed at {datetime.now()}")
    print(f"Successfully sent: {success_count}")
    print(f"Errors: {error_count}")
    print("="*50)


if __name__ == "__main__":
    try:
        send_daily_reminders()
    except Exception as e:
        print(f"Fatal error in email job: {str(e)}")
        sys.exit(1)
