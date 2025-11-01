import os, ssl, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv() 

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_USER")

def send_email(to: str, subject: str, text: str, html: str | None = None):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS]):
        raise RuntimeError("SMTP environment variables missing")
    else:
        # Create multipart message for both text and HTML
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to

        # Add plain text part
        part1 = MIMEText(text, "plain")
        msg.attach(part1)

        # Add HTML part if provided
        if html:
            part2 = MIMEText(html, "html")
            msg.attach(part2)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)


if __name__ == "__main__":
    load_dotenv() 
    send_email(to="davidandrist@outlook.com", subject="test", text="this is a test")