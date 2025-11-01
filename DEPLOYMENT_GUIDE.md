# AutoBuyer Deployment Guide - Email Configuration

This guide will help you deploy AutoBuyer on your VM with working email-based 2FA.

## Prerequisites

- A VM with Linux (Ubuntu/Debian recommended) or Windows Server
- Python 3.9+ installed
- Access to an email account for sending verification codes

---

## Step 1: Choose Your Email Provider

You need an SMTP server to send emails. Choose one option:

### Option A: Gmail (Recommended for Testing)
- **Pros**: Free, easy to set up
- **Cons**: Daily sending limits (100-500 emails/day)
- **Best for**: Development, small user base

### Option B: SendGrid (Recommended for Production)
- **Pros**: 100 free emails/day, reliable, no auth setup hassle
- **Cons**: Requires API key
- **Best for**: Production deployments

### Option C: Your Domain Email (Professional)
- **Pros**: Professional, branded emails
- **Cons**: Requires domain and email hosting
- **Best for**: Production with custom domain

---

## Step 2: Get SMTP Credentials

### For Gmail:

1. **Enable 2-Step Verification**
   - Go to: https://myaccount.google.com/security
   - Click "2-Step Verification" → Turn it ON
   - Follow the setup wizard

2. **Create an App Password**
   - Go to: https://myaccount.google.com/apppasswords
   - Select app: "Mail"
   - Select device: "Other" → Name it "AutoBuyer"
   - Click "Generate"
   - **Copy the 16-character password** (you'll need this!)

3. **Note your credentials:**
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-email@gmail.com
   SMTP_PASSWORD=xxxx xxxx xxxx xxxx (the app password)
   FROM_EMAIL=your-email@gmail.com
   ```

### For SendGrid:

1. **Create a free account**
   - Go to: https://signup.sendgrid.com/
   - Verify your email

2. **Create an API Key**
   - Dashboard → Settings → API Keys
   - Click "Create API Key"
   - Name: "AutoBuyer"
   - Permissions: "Full Access" or "Mail Send"
   - Copy the API key

3. **Note your credentials:**
   ```
   SMTP_HOST=smtp.sendgrid.net
   SMTP_PORT=587
   SMTP_USER=apikey
   SMTP_PASSWORD=<your-api-key>
   FROM_EMAIL=your-verified-sender@yourdomain.com
   ```

### For Custom Domain (e.g., Namecheap, GoDaddy):

1. **Check your email hosting provider's SMTP settings**
   - Usually found in: Email settings → SMTP/Outgoing mail settings
   
2. **Common settings:**
   ```
   SMTP_HOST=mail.yourdomain.com (or smtp.yourdomain.com)
   SMTP_PORT=587 (or 465 for SSL)
   SMTP_USER=noreply@yourdomain.com
   SMTP_PASSWORD=<your-email-password>
   FROM_EMAIL=noreply@yourdomain.com
   ```

---

## Step 3: Deploy to Your VM

### On Your VM (Linux):

1. **SSH into your VM**
   ```bash
   ssh username@your-vm-ip
   ```

2. **Clone or upload your project**
   ```bash
   cd /home/username
   git clone https://github.com/yourusername/AutoBuyer.git
   cd AutoBuyer
   ```

3. **Install Python and dependencies**
   ```bash
   # Update system
   sudo apt update && sudo apt upgrade -y
   
   # Install Python 3 and pip
   sudo apt install python3 python3-pip python3-venv -y
   
   # Create virtual environment
   python3 -m venv venv
   source venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

4. **Create .env file with your SMTP credentials**
   ```bash
   nano .env
   ```
   
   Paste your credentials (example for Gmail):
   ```env
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-email@gmail.com
   SMTP_PASSWORD=your-app-password-here
   FROM_EMAIL=your-email@gmail.com
   ```
   
   Save and exit: `Ctrl+X`, then `Y`, then `Enter`

5. **Secure the .env file**
   ```bash
   chmod 600 .env
   ```

6. **Test the application**
   ```bash
   python app/main.py
   ```
   
   You should see:
   ```
   ✅ Database initialized successfully
   INFO:     Started server process
   INFO:     Uvicorn running on http://127.0.0.1:8000
   ```

---

## Step 4: Set Up Production Server (Recommended)

For production, use a process manager and reverse proxy:

### Install and configure Gunicorn + Nginx:

1. **Install Gunicorn**
   ```bash
   pip install gunicorn
   ```

2. **Create a systemd service**
   ```bash
   sudo nano /etc/systemd/system/autobuyer.service
   ```
   
   Paste this configuration:
   ```ini
   [Unit]
   Description=AutoBuyer FastAPI Application
   After=network.target

   [Service]
   Type=notify
   User=your-username
   WorkingDirectory=/home/your-username/AutoBuyer
   Environment="PATH=/home/your-username/AutoBuyer/venv/bin"
   EnvironmentFile=/home/your-username/AutoBuyer/.env
   ExecStart=/home/your-username/AutoBuyer/venv/bin/gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   
   **Replace `your-username` with your actual username!**

3. **Enable and start the service**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable autobuyer
   sudo systemctl start autobuyer
   sudo systemctl status autobuyer
   ```

4. **Install and configure Nginx**
   ```bash
   sudo apt install nginx -y
   sudo nano /etc/nginx/sites-available/autobuyer
   ```
   
   Paste this configuration:
   ```nginx
   server {
       listen 80;
       server_name your-domain.com www.your-domain.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       location /static {
           alias /home/your-username/AutoBuyer/app/static;
       }
   }
   ```
   
   **Replace `your-domain.com` and `your-username`!**

5. **Enable the site**
   ```bash
   sudo ln -s /etc/nginx/sites-available/autobuyer /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

6. **Configure firewall**
   ```bash
   sudo ufw allow 'Nginx Full'
   sudo ufw enable
   ```

---

## Step 5: Enable HTTPS (Recommended)

1. **Install Certbot**
   ```bash
   sudo apt install certbot python3-certbot-nginx -y
   ```

2. **Get SSL certificate**
   ```bash
   sudo certbot --nginx -d your-domain.com -d www.your-domain.com
   ```
   
   Follow the prompts:
   - Enter your email
   - Agree to terms
   - Choose whether to redirect HTTP to HTTPS (recommended: Yes)

3. **Auto-renewal is set up automatically**
   Test it with:
   ```bash
   sudo certbot renew --dry-run
   ```

---

## Step 6: Verify Email Sending Works

1. **Check service logs**
   ```bash
   sudo journalctl -u autobuyer -f
   ```

2. **Register a new user** on your website with a real email address

3. **Look for log messages:**
   - ✅ Success: `✅ Verification email sent to user@example.com`
   - ⚠️ Not configured: `⚠️  Email not configured. Verification code for user: 123456`
   - ❌ Error: `❌ Failed to send email: [error message]`

4. **Check the email inbox** (and spam folder!) for the verification code

---

## Troubleshooting

### "Email not configured" message
- **Cause**: `.env` file missing or SMTP credentials empty
- **Fix**: 
  ```bash
  cat .env  # Check if credentials are set
  nano .env  # Edit if needed
  sudo systemctl restart autobuyer
  ```

### "Failed to send email: Authentication failed"
- **Cause**: Wrong password or username
- **Fix (Gmail)**: Make sure you're using the **App Password**, not your regular Gmail password
- **Fix (SendGrid)**: Username should be `apikey` (literally), password is your API key

### "Failed to send email: Connection timeout"
- **Cause**: Port 587 might be blocked by firewall
- **Fix**: 
  ```bash
  sudo ufw allow 587/tcp
  # Or use port 465 with SSL (requires code change)
  ```

### "Failed to send email: SSL/TLS error"
- **Cause**: Certificate validation issues
- **Fix**: Check if VM has proper SSL certificates installed:
  ```bash
  sudo apt install ca-certificates -y
  sudo update-ca-certificates
  ```

### Email arrives but goes to spam
- **Cause**: Sending from IP with poor reputation or no SPF/DKIM
- **Fix**: 
  - Use SendGrid or professional email service
  - Set up SPF and DKIM records for your domain
  - For Gmail, this is usually fine for small volumes

### Still can't send emails
1. **Test SMTP connection from VM:**
   ```bash
   python3 -c "
   import smtplib
   server = smtplib.SMTP('smtp.gmail.com', 587)
   server.starttls()
   server.login('your-email@gmail.com', 'your-app-password')
   print('✅ SMTP connection successful!')
   server.quit()
   "
   ```

2. **Check if you can send a test email:**
   ```bash
   source venv/bin/activate
   python3 << 'EOF'
   import asyncio
   import sys
   sys.path.insert(0, '/home/your-username/AutoBuyer')
   from app.main import send_verification_email
   asyncio.run(send_verification_email('your-test@email.com', '123456', 'TestUser'))
   EOF
   ```

---

## Step 7: Production Checklist

Before going live:

- [ ] `.env` file has valid SMTP credentials
- [ ] `.env` file has restricted permissions (`chmod 600 .env`)
- [ ] Service is running: `sudo systemctl status autobuyer`
- [ ] Nginx is running and proxying correctly
- [ ] HTTPS is enabled with valid SSL certificate
- [ ] Firewall allows ports 80, 443
- [ ] Test user registration with real email works
- [ ] Check logs for any errors: `sudo journalctl -u autobuyer -f`
- [ ] Database is backed up regularly
- [ ] Change default admin password from `admin123`

---

## Environment Variables Reference

All variables for `.env`:

```env
# Required for email sending
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=your-email@gmail.com

# Optional (with defaults)
# DATABASE_PATH=app/autobuyer.db
# SECRET_KEY=auto-generated
```

---

## Quick Reference: Service Management

```bash
# Start service
sudo systemctl start autobuyer

# Stop service
sudo systemctl stop autobuyer

# Restart service (after code changes)
sudo systemctl restart autobuyer

# View logs (live)
sudo journalctl -u autobuyer -f

# View last 100 logs
sudo journalctl -u autobuyer -n 100

# Check status
sudo systemctl status autobuyer
```

---

## Support

If you encounter issues not covered here:

1. Check the application logs: `sudo journalctl -u autobuyer -f`
2. Test SMTP connection manually (see Troubleshooting section)
3. Verify `.env` file has correct credentials
4. Make sure firewall isn't blocking SMTP ports
5. Check if your email provider has rate limits or requires additional setup

---

## Additional Security Recommendations

1. **Change default admin credentials immediately**
2. **Use strong passwords for all accounts**
3. **Keep Python packages updated**: `pip install -r requirements.txt --upgrade`
4. **Monitor logs for suspicious activity**
5. **Set up database backups**:
   ```bash
   # Add to crontab
   0 2 * * * cp /home/your-username/AutoBuyer/app/autobuyer.db /home/your-username/backups/autobuyer_$(date +\%Y\%m\%d).db
   ```

---

Good luck with your deployment! 🚀
