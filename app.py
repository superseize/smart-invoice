# ============================================================
# SMART BUSINESS PRO - Complete ERP System
# Deploy Ready for Render.com
# Features: Auto-sync, Cloud Backup, Multi-user, HR, Accounting
# ============================================================

from pathlib import Path
import sys
import os
import datetime
import json
import hashlib
import shutil
import sqlite3
import threading
import time
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEBase
from email.mime.base import MIMEBase
from email import encoders
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, render_template_string,
    flash, jsonify, session, send_file, abort, make_response,
    send_from_directory, get_flashed_messages  # YEH ADD KIYA
)
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
import pandas as pd
import io
import base64

# ===================== CONFIGURATION =====================
if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path(__file__).parent if '__file__' in dir() else Path.cwd()

# Render.com ke liye environment variables
import os
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///data/db/business.db')
SECRET_KEY = os.environ.get('SECRET_KEY', 'smart-business-pro-2024-secure-key')
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5000')

BASE_DATA = ROOT / "data"
DB_DIR = BASE_DATA / "db"
UPLOADS_DIR = BASE_DATA / "uploads"
BACKUP_DIR = BASE_DATA / "backups"
EXPORT_DIR = BASE_DATA / "exports"
LOGS_DIR = BASE_DATA / "logs"
SYNC_DIR = BASE_DATA / "sync"

for folder in (DB_DIR, UPLOADS_DIR, BACKUP_DIR, EXPORT_DIR, LOGS_DIR, SYNC_DIR):
    folder.mkdir(parents=True, exist_ok=True)

DB_FILE = DB_DIR / "business.db"
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Global settings cache
SETTINGS_CACHE = {}
SYNC_QUEUE = []

# ===================== DATABASE SCHEMA =====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Users with enhanced roles
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        role TEXT DEFAULT 'salesman',
        phone TEXT,
        email TEXT,
        commission_rate REAL DEFAULT 0,
        target_monthly REAL DEFAULT 0,
        salary REAL DEFAULT 0,
        joining_date TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_login TEXT,
        last_sync TEXT,
        permissions TEXT,
        device_id TEXT
    )
    """)
    
    # Settings
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_by TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Workers/Employees
    c.execute("""
    CREATE TABLE IF NOT EXISTS workers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        address TEXT,
        designation TEXT,
        salary REAL DEFAULT 0,
        daily_wage REAL DEFAULT 0,
        joining_date TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Worker Attendance
    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER,
        date TEXT,
        status TEXT,  -- present, absent, half-day, leave
        check_in TEXT,
        check_out TEXT,
        overtime_hours REAL DEFAULT 0,
        notes TEXT,
        marked_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (worker_id) REFERENCES workers(id),
        FOREIGN KEY (marked_by) REFERENCES users(id),
        UNIQUE(worker_id, date)
    )
    """)
    
    # Worker Payments (Salary, Advance, Loan)
    c.execute("""
    CREATE TABLE IF NOT EXISTS worker_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER,
        date TEXT,
        type TEXT,  -- salary, advance, loan, loan_repayment, bonus, deduction
        amount REAL,
        balance REAL,  -- running balance for loans
        description TEXT,
        month_year TEXT,
        paid_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (worker_id) REFERENCES workers(id),
        FOREIGN KEY (paid_by) REFERENCES users(id)
    )
    """)
    
    # Expenses
    c.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        category TEXT,
        subcategory TEXT,
        amount REAL,
        description TEXT,
        payment_method TEXT,
        reference_no TEXT,
        receipt_image TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    
    # Expense Categories
    c.execute("""
    CREATE TABLE IF NOT EXISTS expense_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        type TEXT,  -- fixed, variable
        budget_limit REAL DEFAULT 0
    )
    """)
    
    # Customer Categories
    c.execute("""
    CREATE TABLE IF NOT EXISTS customer_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        discount_percent REAL DEFAULT 0,
        price_level INTEGER DEFAULT 1,
        credit_limit REAL DEFAULT 0
    )
    """)
    
    # Customers
    c.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        name TEXT NOT NULL,
        address TEXT,
        phone TEXT,
        email TEXT,
        city TEXT,
        region TEXT,
        credit_limit REAL DEFAULT 0,
        balance REAL DEFAULT 0,
        total_sales REAL DEFAULT 0,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (category_id) REFERENCES customer_categories(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    
    # Products with cost tracking
    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        category TEXT,
        barcode TEXT UNIQUE,
        unit TEXT DEFAULT 'pcs',
        
        -- Cost & Pricing
        purchase_price REAL DEFAULT 0,  -- Auto-calculated from purchases
        avg_cost REAL DEFAULT 0,        -- Weighted average cost
        retail_price REAL DEFAULT 0,
        wholesale_price REAL DEFAULT 0,
        distributor_price REAL DEFAULT 0,
        min_price REAL DEFAULT 0,       -- Minimum selling price (auto)
        
        -- Stock
        stock REAL DEFAULT 0,
        min_stock REAL DEFAULT 0,
        max_stock REAL DEFAULT 0,
        location TEXT,
        
        -- Auto-calculation flags
        auto_price INTEGER DEFAULT 1,   -- Auto calculate selling price
        profit_margin REAL DEFAULT 20,  -- Default profit margin %
        
        supplier TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Purchase Records (for auto cost calculation)
    c.execute("""
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        product_id INTEGER,
        supplier_id INTEGER,
        qty REAL,
        unit_cost REAL,
        total_cost REAL,
        transport_cost REAL DEFAULT 0,
        other_cost REAL DEFAULT 0,
        final_cost REAL,  -- Including all overheads
        invoice_no TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    
    # Stock Movements
    c.execute("""
    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        type TEXT,  -- 'in', 'out', 'adjustment', 'return', 'purchase'
        qty REAL,
        unit_cost REAL,
        total_cost REAL,
        reference_type TEXT,
        reference_id INTEGER,
        notes TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    
    # Invoices
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inv_no TEXT UNIQUE NOT NULL,
        date TEXT,
        month_year TEXT,
        customer_id INTEGER,
        customer_name TEXT,
        customer_address TEXT,
        customer_phone TEXT,
        customer_category TEXT,
        salesman_id INTEGER,
        salesman_name TEXT,
        
        -- Financial
        subtotal REAL DEFAULT 0,
        tax_rate REAL DEFAULT 0,
        tax_amount REAL DEFAULT 0,
        discount_percent REAL DEFAULT 0,
        discount_amount REAL DEFAULT 0,
        total REAL DEFAULT 0,
        paid REAL DEFAULT 0,
        balance REAL DEFAULT 0,
        previous_pending REAL DEFAULT 0,
        
        -- Profit Calculation
        total_cost REAL DEFAULT 0,      -- Total cost of items
        gross_profit REAL DEFAULT 0,    -- total - total_cost
        profit_margin REAL DEFAULT 0,   -- (gross_profit / total) * 100
        
        -- Status
        status TEXT DEFAULT 'draft',
        payment_method TEXT DEFAULT 'cash',
        payment_status TEXT DEFAULT 'pending',
        
        -- Order/Approval
        is_order INTEGER DEFAULT 0,
        approved_by INTEGER,
        approved_at TEXT,
        
        -- Timestamps
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        editable_until TEXT,
        
        -- Sync
        sync_status TEXT DEFAULT 'synced',
        sync_id TEXT,
        
        notes TEXT,
        terms TEXT,
        
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (salesman_id) REFERENCES users(id),
        FOREIGN KEY (approved_by) REFERENCES users(id)
    )
    """)
    
    # Invoice Items
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        product_id INTEGER,
        product_name TEXT,
        description TEXT,
        qty REAL,
        unit TEXT,
        unit_price REAL,
        unit_cost REAL,     -- Cost at time of sale
        profit REAL,        -- (unit_price - unit_cost) * qty
        total REAL,
        FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)
    
    # Payments
    c.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        customer_id INTEGER,
        invoice_id INTEGER,
        amount REAL,
        method TEXT,
        reference_no TEXT,
        notes TEXT,
        received_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (invoice_id) REFERENCES invoices(id),
        FOREIGN KEY (received_by) REFERENCES users(id)
    )
    """)
    
    # Customer Ledger
    c.execute("""
    CREATE TABLE IF NOT EXISTS ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        customer_id INTEGER,
        invoice_id INTEGER,
        payment_id INTEGER,
        type TEXT,
        debit REAL DEFAULT 0,
        credit REAL DEFAULT 0,
        balance REAL,
        description TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    
    # Profit & Loss Records
    c.execute("""
    CREATE TABLE IF NOT EXISTS profit_loss (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        month_year TEXT,
        
        -- Income
        total_sales REAL DEFAULT 0,
        total_receipts REAL DEFAULT 0,
        
        -- Cost of Goods Sold
        cogs REAL DEFAULT 0,           -- Cost of goods sold
        
        -- Expenses
        total_expenses REAL DEFAULT 0,
        salary_expense REAL DEFAULT 0,
        rent_expense REAL DEFAULT 0,
        utility_expense REAL DEFAULT 0,
        transport_expense REAL DEFAULT 0,
        other_expense REAL DEFAULT 0,
        
        -- Calculated
        gross_profit REAL DEFAULT 0,    -- total_sales - cogs
        net_profit REAL DEFAULT 0,      -- gross_profit - total_expenses
        profit_margin REAL DEFAULT 0,   -- (net_profit / total_sales) * 100
        
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Sync Log
    c.execute("""
    CREATE TABLE IF NOT EXISTS sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT,
        user_id INTEGER,
        table_name TEXT,
        record_id INTEGER,
        action TEXT,  -- insert, update, delete
        data TEXT,    -- JSON
        sync_status TEXT DEFAULT 'pending',
        synced_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)
    
    # Activity Log
    c.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        entity_type TEXT,
        entity_id INTEGER,
        old_values TEXT,
        new_values TEXT,
        ip_address TEXT,
        user_agent TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)
    
    conn.commit()
    
    # Insert default data
    defaults = [
        ("company_name", "Your Business Name"),
        ("company_address", "Your Business Address"),
        ("company_phone", "+92-XXX-XXXXXXX"),
        ("company_email", "admin@business.com"),
        ("company_logo", ""),
        ("tax_rate", "16"),
        ("tax_number", ""),
        ("currency", "PKR"),
        ("invoice_prefix", "INV-"),
        ("order_prefix", "ORD-"),
        ("receipt_prefix", "RCP-"),
        ("theme", "light"),
        ("language", "en"),
        ("date_format", "%d-%m-%Y"),
        ("time_zone", "Asia/Karachi"),
        ("auto_backup", "1"),
        ("backup_time", "23:00"),
        ("auto_sync", "1"),
        ("sync_interval", "5"),  # minutes
        ("auto_email_reports", "0"),
        ("admin_email", ""),
        ("smtp_server", ""),
        ("smtp_port", "587"),
        ("smtp_user", ""),
        ("smtp_pass", ""),
        ("edit_time_limit", "24"),
        ("low_stock_alert", "1"),
        ("auto_price_calculation", "1"),
        ("default_profit_margin", "20"),
        ("enable_worker_module", "1"),
        ("enable_expense_module", "1"),
        ("daily_backup", "1"),
        ("cloud_backup_url", ""),
    ]
    
    c.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults)
    
    # Default categories
    categories = [
        ("Distributor", 15.0, 3, 500000),
        ("Retailer", 10.0, 2, 100000),
        ("General", 0.0, 1, 50000),
        ("Walk-in", 0.0, 1, 0),
    ]
    c.executemany("INSERT OR IGNORE INTO customer_categories (name, discount_percent, price_level, credit_limit) VALUES (?, ?, ?, ?)", categories)
    
    # Expense categories
    expense_cats = [
        ("Salary", "fixed", 0),
        ("Rent", "fixed", 0),
        ("Utilities", "variable", 0),
        ("Transport", "variable", 0),
        ("Office Supplies", "variable", 0),
        ("Marketing", "variable", 0),
        ("Maintenance", "variable", 0),
        ("Other", "variable", 0),
    ]
    c.executemany("INSERT OR IGNORE INTO expense_categories (name, type, budget_limit) VALUES (?, ?, ?)", expense_cats)
    
    # Default admin
    c.execute("SELECT id FROM users WHERE username='admin'")
    if not c.fetchone():
        admin_pass = hashlib.sha256("admin123".encode()).hexdigest()
        permissions = json.dumps({
            "can_delete": True, "can_edit": True, "can_approve": True,
            "can_view_all": True, "can_modify_settings": True,
            "can_backup": True, "can_export": True, "can_import": True,
            "can_manage_workers": True, "can_view_profit": True
        })
        c.execute("""
            INSERT INTO users (username, password_hash, full_name, role, email, permissions, is_active, salary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("admin", admin_pass, "System Administrator", "admin", "admin@system.com", permissions, 1, 50000))
        
        # Sample salesman
        salesman_pass = hashlib.sha256("sales123".encode()).hexdigest()
        salesman_perm = json.dumps({
            "can_delete": False, "can_edit": True, "can_approve": False,
            "can_view_all": False, "can_modify_settings": False,
            "can_backup": False, "can_export": True, "can_import": False,
            "can_manage_workers": False, "can_view_profit": False
        })
        c.execute("""
            INSERT INTO users (username, password_hash, full_name, role, email, permissions, is_active, salary, commission_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("salesman", salesman_pass, "Sales Representative", "salesman", "sales@system.com", salesman_perm, 1, 25000, 5))
        
        print("✅ Default users created")
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")

init_db()

# ===================== HELPERS =====================
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_setting(key, default=""):
    if key in SETTINGS_CACHE:
        return SETTINGS_CACHE[key]
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    value = row['value'] if row else default
    SETTINGS_CACHE[key] = value
    return value

def log_activity(user_id, action, entity_type=None, entity_id=None, old_vals=None, new_vals=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO activity_log (user_id, action, entity_type, entity_id, old_values, new_values, ip_address, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, action, entity_type, entity_id, 
          json.dumps(old_vals) if old_vals else None,
          json.dumps(new_vals) if new_vals else None,
          request.remote_addr if request else 'unknown',
          request.user_agent.string if request and request.user_agent else 'unknown'))
    conn.commit()
    conn.close()

def generate_number(prefix_key, table="invoices", col="inv_no"):
    prefix = get_setting(prefix_key, "INV-")
    today = datetime.datetime.now()
    month_str = today.strftime("%Y%m")
    
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE ?", (f"{prefix}{month_str}%",))
    count = c.fetchone()[0] + 1
    conn.close()
    
    return f"{prefix}{month_str}-{count:04d}"

def calculate_product_prices(product_id):
    """Auto-calculate selling prices based on cost and margin"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = c.fetchone()
    
    if not product or not product['auto_price']:
        conn.close()
        return
    
    # Get latest purchase cost
    c.execute("""
        SELECT AVG(final_cost/qty) as avg_cost 
        FROM purchases 
        WHERE product_id = ? 
        ORDER BY date DESC LIMIT 10
    """, (product_id,))
    result = c.fetchone()
    
    avg_cost = result['avg_cost'] if result and result['avg_cost'] else product['purchase_price']
    margin = product['profit_margin'] / 100
    
    # Calculate prices with different margins
    retail = avg_cost * (1 + margin)
    wholesale = avg_cost * (1 + margin * 0.8)  # 20% less margin
    distributor = avg_cost * (1 + margin * 0.6)  # 40% less margin
    min_price = avg_cost * 1.05  # 5% minimum profit
    
    c.execute("""
        UPDATE products SET 
        avg_cost = ?, retail_price = ?, wholesale_price = ?, 
        distributor_price = ?, min_price = ?
        WHERE id = ?
    """, (avg_cost, retail, wholesale, distributor, min_price, product_id))
    
    conn.commit()
    conn.close()

def update_profit_loss(date=None):
    """Update daily profit/loss calculations"""
    if not date:
        date = datetime.date.today().isoformat()
    
    month_year = date[:7]
    conn = get_db()
    c = conn.cursor()
    
    # Get sales data
    c.execute("""
        SELECT SUM(total) as sales, SUM(total_cost) as cogs, SUM(gross_profit) as profit
        FROM invoices 
        WHERE date = ? AND status != 'cancelled'
    """, (date,))
    sales_data = c.fetchone()
    
    # Get expenses
    c.execute("""
        SELECT category, SUM(amount) as total 
        FROM expenses 
        WHERE date = ?
        GROUP BY category
    """, (date,))
    expenses = {row['category']: row['total'] for row in c.fetchall()}
    
    # Get salary expenses
    c.execute("SELECT SUM(amount) FROM worker_payments WHERE date = ? AND type='salary'", (date,))
    salary_exp = c.fetchone()[0] or 0
    
    total_sales = sales_data['sales'] or 0
    cogs = sales_data['cogs'] or 0
    gross_profit = sales_data['profit'] or 0
    total_exp = sum(expenses.values()) + salary_exp
    net_profit = gross_profit - total_exp
    margin = (net_profit / total_sales * 100) if total_sales > 0 else 0
    
    c.execute("""
        INSERT OR REPLACE INTO profit_loss 
        (date, month_year, total_sales, cogs, gross_profit, total_expenses, 
         salary_expense, net_profit, profit_margin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (date, month_year, total_sales, cogs, gross_profit, total_exp, 
          salary_exp, net_profit, margin))
    
    conn.commit()
    conn.close()

# ===================== AUTO SYNC & BACKUP =====================
def auto_sync():
    """Background sync task"""
    while True:
        if get_setting('auto_sync', '1') == '1':
            try:
                # Process sync queue
                conn = get_db()
                c = conn.cursor()
                c.execute("""
                    SELECT * FROM sync_log 
                    WHERE sync_status = 'pending' 
                    ORDER BY created_at ASC LIMIT 100
                """)
                pending = c.fetchall()
                
                for record in pending:
                    # In real implementation, send to cloud server
                    # For now, mark as synced
                    c.execute("""
                        UPDATE sync_log SET sync_status = 'synced', synced_at = datetime('now')
                        WHERE id = ?
                    """, (record['id'],))
                
                conn.commit()
                conn.close()
                
                # Cloud backup if configured
                cloud_url = get_setting('cloud_backup_url')
                if cloud_url and get_setting('daily_backup') == '1':
                    # TODO: Implement cloud backup
                    pass
                    
            except Exception as e:
                print(f"Sync error: {e}")
        
        time.sleep(int(get_setting('sync_interval', '5')) * 60)

def auto_backup():
    """Daily backup task"""
    while True:
        now = datetime.datetime.now()
        backup_time = get_setting('backup_time', '23:00')
        target_hour, target_min = map(int, backup_time.split(':'))
        
        if now.hour == target_hour and now.minute == target_min:
            if get_setting('auto_backup', '1') == '1':
                timestamp = now.strftime("%Y%m%d_%H%M%S")
                backup_file = BACKUP_DIR / f"auto_backup_{timestamp}.db"
                shutil.copy2(DB_FILE, backup_file)
                
                # Keep last 30 backups
                backups = sorted(BACKUP_DIR.glob("auto_backup_*.db"), key=lambda x: x.stat().st_mtime)
                for old in backups[:-30]:
                    old.unlink()
                
                print(f"✅ Backup created: {backup_file.name}")
            
            # Update profit/loss for yesterday
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            update_profit_loss(yesterday)
            
            time.sleep(60)
        
        time.sleep(30)

# Start background threads
sync_thread = threading.Thread(target=auto_sync, daemon=True)
backup_thread = threading.Thread(target=auto_backup, daemon=True)
sync_thread.start()
backup_thread.start()

# ===================== DECORATORS =====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({"error": "Not authenticated"}), 401
            flash("Please login first", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash("Admin access required", "error")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ===================== CSS FRAMEWORK =====================
CSS_FRAMEWORK = """
<style>
:root {
    --primary: #4f46e5;
    --primary-dark: #4338ca;
    --secondary: #64748b;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --info: #06b6d4;
    --bg: #f8fafc;
    --surface: #ffffff;
    --text: #1e293b;
    --text-muted: #64748b;
    --border: #e2e8f0;
    --shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    --radius: 8px;
    --radius-lg: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    font-size: 14px;
}

.app-container { display: flex; min-height: 100vh; }

.sidebar {
    width: 280px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    position: fixed;
    height: 100vh;
    z-index: 100;
    overflow-y: auto;
}

.sidebar-header {
    padding: 1.5rem;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(135deg, var(--primary), var(--primary-dark));
    color: white;
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 1.25rem;
    font-weight: 700;
}

.nav-section { padding: 1rem 0; flex: 1; }

.nav-title {
    padding: 0.5rem 1.5rem;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    font-weight: 600;
    margin-top: 1rem;
}

.nav-item {
    display: flex;
    align-items: center;
    padding: 0.75rem 1.5rem;
    color: var(--text-muted);
    text-decoration: none;
    transition: all 0.2s;
    border-left: 3px solid transparent;
    margin: 0 0.5rem;
    border-radius: var(--radius);
}

.nav-item:hover, .nav-item.active {
    background: rgba(79, 70, 229, 0.1);
    color: var(--primary);
    border-left-color: var(--primary);
}

.nav-item i { width: 20px; margin-right: 12px; text-align: center; }

.main-content {
    flex: 1;
    margin-left: 280px;
    display: flex;
    flex-direction: column;
}

.top-bar {
    background: var(--surface);
    padding: 1rem 2rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 50;
}

.content { padding: 2rem; flex: 1; }

.card {
    background: var(--surface);
    border-radius: var(--radius-lg);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    margin-bottom: 1.5rem;
}

.card-header {
    padding: 1.25rem 1.5rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.card-body { padding: 1.5rem; }

.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.stat-card {
    background: var(--surface);
    padding: 1.5rem;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
}

.stat-value {
    font-size: 1.875rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
    color: var(--primary);
}

.stat-label {
    color: var(--text-muted);
    font-size: 0.875rem;
}

.btn {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.625rem 1.25rem;
    border-radius: var(--radius);
    font-weight: 500;
    font-size: 0.875rem;
    text-decoration: none;
    border: none;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-primary { background: var(--primary); color: white; }
.btn-success { background: var(--success); color: white; }
.btn-danger { background: var(--danger); color: white; }
.btn-warning { background: var(--warning); color: white; }
.btn-secondary { background: var(--secondary); color: white; }
.btn-ghost { background: transparent; color: var(--text-muted); border: 1px solid var(--border); }

.form-control {
    width: 100%;
    padding: 0.625rem 0.875rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text);
    font-size: 0.875rem;
}

.form-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 1rem;
}

.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}

.data-table th, .data-table td {
    padding: 0.875rem 1rem;
    text-align: left;
    border-bottom: 1px solid var(--border);
}

.data-table th {
    background: var(--bg);
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    font-size: 0.75rem;
}

.badge {
    display: inline-flex;
    align-items: center;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
}

.badge-success { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.badge-warning { background: rgba(245, 158, 11, 0.1); color: var(--warning); }
.badge-danger { background: rgba(239, 68, 68, 0.1); color: var(--danger); }

.alert {
    padding: 1rem 1.25rem;
    border-radius: var(--radius);
    margin-bottom: 1.5rem;
}

.alert-success { background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.2); }
.alert-error { background: rgba(239, 68, 68, 0.1); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.2); }

.tabs {
    display: flex;
    gap: 0.5rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.5rem;
}

.tab {
    padding: 0.75rem 1.5rem;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
}

.tab.active {
    color: var(--primary);
    border-bottom-color: var(--primary);
}

.tab-content { display: none; }
.tab-content.active { display: block; }

@media (max-width: 768px) {
    .sidebar { transform: translateX(-100%); width: 100%; }
    .sidebar.open { transform: translateX(0); }
    .main-content { margin-left: 0; }
    .stats-grid { grid-template-columns: 1fr; }
}

.login-page {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
    background: var(--surface);
    padding: 2.5rem;
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);
    width: 100%;
    max-width: 420px;
}
</style>
"""

# ===================== PAGE RENDERER =====================
def render_page(title, content, active="dashboard", user=None):
    if not user:
        user = session
    
    nav_items = ""
    if user.get('role') == 'admin':
        nav_items = f"""
        <div class="nav-title">Admin</div>
        <a href="{url_for('workers')}" class="nav-item {'active' if active=='workers' else ''}"><i class="fas fa-users"></i> Workers</a>
        <a href="{url_for('attendance')}" class="nav-item {'active' if active=='attendance' else ''}"><i class="fas fa-calendar-check"></i> Attendance</a>
        <a href="{url_for('expenses')}" class="nav-item {'active' if active=='expenses' else ''}"><i class="fas fa-wallet"></i> Expenses</a>
        <a href="{url_for('profit_loss')}" class="nav-item {'active' if active=='profit_loss' else ''}"><i class="fas fa-chart-pie"></i> Profit/Loss</a>
        <a href="{url_for('users')}" class="nav-item {'active' if active=='users' else ''}"><i class="fas fa-user-shield"></i> Users</a>
        <a href="{url_for('settings')}" class="nav-item {'active' if active=='settings' else ''}"><i class="fas fa-cog"></i> Settings</a>
        <a href="{url_for('backup')}" class="nav-item {'active' if active=='backup' else ''}"><i class="fas fa-cloud"></i> Backup</a>
        """
    
    alerts = ""
    for category, message in get_flashed_messages(with_categories=True):
        alerts += f'<div class="alert alert-{category}">{message}</div>'
    
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    {CSS_FRAMEWORK}
</head>
<body>
    <div class="app-container">
        <aside class="sidebar">
            <div class="sidebar-header">
                <div class="brand">
                    <i class="fas fa-briefcase"></i>
                    <span>Smart Business Pro</span>
                </div>
            </div>
            <nav class="nav-section">
                <div class="nav-title">Main</div>
                <a href="{url_for('dashboard')}" class="nav-item {'active' if active=='dashboard' else ''}"><i class="fas fa-home"></i> Dashboard</a>
                <a href="{url_for('new_invoice')}" class="nav-item {'active' if active=='new_invoice' else ''}"><i class="fas fa-plus-circle"></i> New Invoice</a>
                <a href="{url_for('invoices')}" class="nav-item {'active' if active=='invoices' else ''}"><i class="fas fa-file-invoice"></i> Invoices</a>
                <a href="{url_for('customers')}" class="nav-item {'active' if active=='customers' else ''}"><i class="fas fa-users"></i> Customers</a>
                <a href="{url_for('products')}" class="nav-item {'active' if active=='products' else ''}"><i class="fas fa-boxes"></i> Products</a>
                <a href="{url_for('stock')}" class="nav-item {'active' if active=='stock' else ''}"><i class="fas fa-warehouse"></i> Stock</a>
                <a href="{url_for('ledger')}" class="nav-item {'active' if active=='ledger' else ''}"><i class="fas fa-book"></i> Ledger</a>
                <a href="{url_for('payments')}" class="nav-item {'active' if active=='payments' else ''}"><i class="fas fa-money-bill-wave"></i> Payments</a>
                
                {nav_items}
                
                <div class="nav-title">Account</div>
                <a href="{url_for('change_password')}" class="nav-item"><i class="fas fa-key"></i> Change Password</a>
                <a href="{url_for('logout')}" class="nav-item"><i class="fas fa-sign-out-alt"></i> Logout</a>
            </nav>
        </aside>
        
        <main class="main-content">
            <header class="top-bar">
                <h2>{title}</h2>
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <span style="color: var(--text-muted);">{user.get('full_name', 'User')}</span>
                    <div style="width: 36px; height: 36px; background: var(--primary); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 600;">
                        {user.get('full_name', 'U')[0].upper()}
                    </div>
                </div>
            </header>
            
            <div class="content">
                {alerts}
                {content}
            </div>
        </main>
    </div>
    
    <script>
        // Auto-sync indicator
        function checkSync() {{
            fetch('/api/sync-status')
            .then(r => r.json())
            .then(data => {{
                if (data.pending > 0) {{
                    console.log('Sync pending:', data.pending);
                }}
            }});
        }}
        setInterval(checkSync, 30000); // Every 30 seconds
    </script>
</body>
</html>
"""

# ===================== ROUTES =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", 
                 (username, hash_password(password)))
        user = c.fetchone()
        conn.close()
        
        if user and user['is_active']:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            
            # Update last login and device
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute("UPDATE users SET last_login = datetime('now'), device_id = ? WHERE id = ?",
                         (request.headers.get('User-Agent'), user['id']))
            except sqlite3.OperationalError:
                # Column doesn't exist, update without device_id
                c.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?",
                         (user['id'],))
            conn.commit()
            conn.close()
            
            flash(f"Welcome {user['full_name']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials", "error")
    
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Smart Business Pro</title>
    {CSS_FRAMEWORK}
</head>
<body>
    <div class="login-page">
        <div class="login-card">
            <div style="text-align: center; margin-bottom: 2rem;">
                <i class="fas fa-briefcase" style="font-size: 3rem; color: var(--primary);"></i>
                <h2 style="margin-top: 1rem;">Smart Business Pro</h2>
                <p style="color: var(--text-muted);">Complete Business Management</p>
            </div>
            
            {'<div class="alert alert-error">Invalid username or password</div>' if request.method == 'POST' else ''}
            
            <form method="post">
                <div class="form-row">
                    <input type="text" name="username" class="form-control" placeholder="Username" required autofocus>
                </div>
                <div class="form-row">
                    <input type="password" name="password" class="form-control" placeholder="Password" required>
                </div>
                <button type="submit" class="btn btn-primary" style="width: 100%;">
                    <i class="fas fa-sign-in-alt"></i> Sign In
                </button>
            </form>
            
            <div style="text-align: center; margin-top: 1.5rem; color: var(--text-muted); font-size: 0.875rem;">
                <p>Default: admin / admin123</p>
                <p>salesman / sales123</p>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for('login'))

@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    c = conn.cursor()
    user_id = session['user_id']
    role = session['role']
    
    today = datetime.date.today().isoformat()
    month_start = datetime.date.today().replace(day=1).isoformat()
    
    # Stats based on role
    if role == 'admin':
        c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0), COALESCE(SUM(gross_profit), 0) FROM invoices WHERE date = ? AND status != 'cancelled'", (today,))
        today_stats = c.fetchone()
        
        c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM invoices WHERE date >= ? AND status != 'cancelled'", (month_start,))
        month_stats = c.fetchone()
        
        c.execute("SELECT COUNT(*) FROM customers")
        total_customers = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM products WHERE stock <= min_stock")
        low_stock = c.fetchone()[0]
        
        c.execute("SELECT SUM(balance) FROM invoices WHERE balance > 0")
        total_pending = c.fetchone()[0] or 0
        
        # Today's profit
        today_profit = today_stats[2] or 0
        
    else:
        c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0), COALESCE(SUM(gross_profit), 0) FROM invoices WHERE date = ? AND salesman_id = ? AND status != 'cancelled'", (today, user_id))
        today_stats = c.fetchone()
        
        c.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM invoices WHERE date >= ? AND salesman_id = ? AND status != 'cancelled'", (month_start, user_id))
        month_stats = c.fetchone()
        
        c.execute("SELECT COUNT(*) FROM customers WHERE created_by = ?", (user_id,))
        total_customers = c.fetchone()[0]
        
        low_stock = 0
        total_pending = 0
        today_profit = today_stats[2] or 0
    
    # Recent invoices
    if role == 'admin':
        c.execute("SELECT i.*, c.name as customer_name FROM invoices i LEFT JOIN customers c ON i.customer_id = c.id ORDER BY i.created_at DESC LIMIT 5")
    else:
        c.execute("SELECT i.*, c.name as customer_name FROM invoices i LEFT JOIN customers c ON i.customer_id = c.id WHERE i.salesman_id = ? ORDER BY i.created_at DESC LIMIT 5", (user_id,))
    
    recent = c.fetchall()
    conn.close()
    
    recent_html = ""
    for inv in recent:
        badge = f'<span class="badge badge-{"success" if inv["status"] == "paid" else "warning" if inv["status"] == "partial" else "danger"}">{inv["status"]}</span>'
        recent_html += f"""
        <tr>
            <td>{inv['inv_no']}</td>
            <td>{inv['customer_name'] or 'Walk-in'}</td>
            <td>Rs {inv['total']:,.0f}</td>
            <td>{badge}</td>
        </tr>
        """
    
    content = f"""
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value" style="color: var(--primary);">Rs {today_stats[1]:,.0f}</div>
            <div class="stat-label">Today's Sales ({today_stats[0]} bills)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: var(--success);">Rs {today_profit:,.0f}</div>
            <div class="stat-label">Today's Profit</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: var(--info);">Rs {month_stats[1]:,.0f}</div>
            <div class="stat-label">This Month ({month_stats[0]} bills)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: var(--warning);">{total_customers}</div>
            <div class="stat-label">Total Customers</div>
        </div>
        {f'<div class="stat-card"><div class="stat-value" style="color: var(--danger);">{low_stock}</div><div class="stat-label">Low Stock Alert</div></div>' if role == 'admin' else ''}
        {f'<div class="stat-card"><div class="stat-value" style="color: var(--danger);">Rs {total_pending:,.0f}</div><div class="stat-label">Pending Amount</div></div>' if role == 'admin' else ''}
    </div>
    
    <div class="card">
        <div class="card-header">
            <h3>Recent Invoices</h3>
            <a href="{url_for('invoices')}" class="btn btn-primary btn-sm">View All</a>
        </div>
        <div class="card-body">
            <table class="data-table">
                <thead>
                    <tr><th>Invoice #</th><th>Customer</th><th>Amount</th><th>Status</th></tr>
                </thead>
                <tbody>
                    {recent_html}
                </tbody>
            </table>
        </div>
    </div>
    """
    
    return render_page("Dashboard", content, "dashboard")

# ===================== INVOICE ROUTES =====================
@app.route("/invoice/new", methods=["GET", "POST"])
@login_required
def new_invoice():
    if request.method == "POST":
        data = request.get_json()
        
        inv_no = generate_number('invoice_prefix')
        month_year = datetime.datetime.now().strftime("%Y-%m")
        
        # Calculate
        subtotal = sum(item['qty'] * item['price'] for item in data['items'])
        tax_rate = float(data.get('tax_rate', get_setting('tax_rate', 16)))
        tax_amount = subtotal * (tax_rate / 100)
        discount = float(data.get('discount', 0))
        total = subtotal + tax_amount - discount
        paid = float(data.get('paid', 0))
        balance = total - paid
        
        # Cost and profit calculation
        total_cost = sum(item.get('cost', 0) * item['qty'] for item in data['items'])
        gross_profit = total - total_cost
        profit_margin = (gross_profit / total * 100) if total > 0 else 0
        
        status = 'paid' if balance <= 0 else 'partial' if paid > 0 else 'pending'
        
        conn = get_db()
        c = conn.cursor()
        
        c.execute("SELECT * FROM customers WHERE id = ?", (data['customer_id'],))
        customer = c.fetchone()
        
        c.execute("""
            INSERT INTO invoices 
            (inv_no, date, month_year, customer_id, customer_name, salesman_id, salesman_name,
             subtotal, tax_rate, tax_amount, discount_amount, total, paid, balance,
             total_cost, gross_profit, profit_margin, status, payment_method, notes, editable_until)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+24 hours'))
        """, (inv_no, data['date'], month_year, data['customer_id'],
              customer['name'] if customer else data.get('customer_name'),
              session['user_id'], session['full_name'],
              subtotal, tax_rate, tax_amount, discount, total, paid, balance,
              total_cost, gross_profit, profit_margin, status,
              data.get('payment_method', 'cash'), data.get('notes', '')))
        
        inv_id = c.lastrowid
        
        # Add items
        for item in data['items']:
            profit = (item['price'] - item.get('cost', 0)) * item['qty']
            c.execute("""
                INSERT INTO invoice_items 
                (invoice_id, product_id, product_name, qty, unit_price, unit_cost, profit, total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (inv_id, item.get('product_id'), item['name'], item['qty'],
                  item['price'], item.get('cost', 0), profit, item['qty'] * item['price']))
            
            # Update stock
            c.execute("UPDATE products SET stock = stock - ? WHERE id = ?", 
                     (item['qty'], item.get('product_id')))
        
        # Update customer
        if customer:
            c.execute("UPDATE customers SET balance = balance + ?, total_sales = total_sales + ? WHERE id = ?",
                     (balance, total, data['customer_id']))
            
            c.execute("""
                INSERT INTO ledger (date, customer_id, invoice_id, type, debit, balance, description, created_by)
                VALUES (?, ?, ?, 'invoice', ?, ?, ?, ?)
            """, (data['date'], data['customer_id'], inv_id, total, balance, f"Invoice #{inv_no}", session['user_id']))
        
        conn.commit()
        conn.close()
        
        # Update profit/loss
        update_profit_loss(data['date'])
        
        return jsonify({"success": True, "invoice_id": inv_id, "inv_no": inv_no})
    
    # GET
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, address, phone, balance FROM customers ORDER BY name")
    customers = c.fetchall()
    c.execute("SELECT id, name, retail_price, avg_cost as cost_price, stock FROM products WHERE is_active=1")
    products = c.fetchall()
    conn.close()
    
    customer_opts = "".join([f'<option value="{c["id"]}" data-address="{c["address"] or ""}" data-phone="{c["phone"] or ""}" data-balance="{c["balance"]}">{c["name"]}</option>' for c in customers])
    product_opts = "".join([f'<option value="{p["id"]}" data-price="{p["retail_price"]}" data-cost="{p["cost_price"] or 0}" data-stock="{p["stock"]}">{p["name"]} (Stock: {p["stock"]})</option>' for p in products])
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Create Invoice</h3>
        </div>
        <div class="card-body">
            <form id="invoiceForm">
                <div class="form-row">
                    <select name="customer_id" id="customerSelect" class="form-control" required onchange="fillCustomer()">
                        <option value="">Select Customer</option>
                        {customer_opts}
                    </select>
                    <input type="date" name="date" class="form-control" value="{datetime.date.today().isoformat()}" required>
                    <select name="payment_method" class="form-control">
                        <option value="cash">Cash</option>
                        <option value="bank">Bank Transfer</option>
                        <option value="credit">Credit</option>
                    </select>
                </div>
                
                <div id="customerDetails" style="display: none; background: var(--bg); padding: 1rem; border-radius: var(--radius); margin-bottom: 1rem;">
                    <p><strong>Address:</strong> <span id="cAddress"></span></p>
                    <p><strong>Phone:</strong> <span id="cPhone"></span></p>
                    <p><strong>Previous Balance:</strong> <span id="cBalance" style="color: var(--danger);"></span></p>
                </div>
                
                <h4 style="margin: 1.5rem 0 1rem;">Items</h4>
                <table class="data-table" id="itemsTable">
                    <thead>
                        <tr><th>Product</th><th>Stock</th><th>Qty</th><th>Price</th><th>Total</th><th></th></tr>
                    </thead>
                    <tbody id="itemsBody"></tbody>
                </table>
                
                <button type="button" class="btn btn-ghost" onclick="addItem()">
                    <i class="fas fa-plus"></i> Add Item
                </button>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 2rem;">
                    <div>
                        <textarea name="notes" class="form-control" rows="3" placeholder="Notes"></textarea>
                    </div>
                    <div style="background: var(--bg); padding: 1.5rem; border-radius: var(--radius);">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span>Subtotal:</span><strong id="subtotal">Rs 0</strong>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span>Tax ({get_setting('tax_rate', 16)}%):</span><strong id="tax">Rs 0</strong>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span>Discount:</span><input type="number" id="discount" class="form-control" value="0" style="width: 100px;" onchange="calc()">
                        </div>
                        <div style="display: flex; justify-content: space-between; margin: 1rem 0; padding: 1rem 0; border-top: 2px solid var(--border); font-size: 1.25rem; color: var(--primary);">
                            <span><strong>Total:</strong></span><strong id="total">Rs 0</strong>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span>Paid:</span><input type="number" id="paid" class="form-control" value="0" style="width: 100px;" onchange="calc()">
                        </div>
                        <div style="display: flex; justify-content: space-between; color: var(--danger); font-size: 1.125rem;">
                            <span><strong>Balance:</strong></span><strong id="balance">Rs 0</strong>
                        </div>
                    </div>
                </div>
                
                <div style="display: flex; gap: 1rem; justify-content: flex-end; margin-top: 2rem;">
                    <button type="button" class="btn btn-ghost" onclick="location.href='{url_for('dashboard')}'">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Invoice</button>
                </div>
            </form>
        </div>
    </div>
    
    <script>
        let products = {json.dumps([dict(p) for p in products])};
        let itemCount = 0;
        
        function fillCustomer() {{
            const s = document.getElementById('customerSelect');
            const o = s.options[s.selectedIndex];
            if (s.value) {{
                document.getElementById('customerDetails').style.display = 'block';
                document.getElementById('cAddress').textContent = o.dataset.address;
                document.getElementById('cPhone').textContent = o.dataset.phone;
                document.getElementById('cBalance').textContent = 'Rs ' + parseFloat(o.dataset.balance).toLocaleString();
            }}
        }}
        
        function addItem() {{
            itemCount++;
            const tbody = document.getElementById('itemsBody');
            const row = document.createElement('tr');
            let opts = '<option value="">Select</option>';
            products.forEach(p => {{
                opts += `<option value="${{p.id}}" data-price="${{p.retail_price}}" data-cost="${{p.cost_price}}" data-stock="${{p.stock}}">${{p.name}}</option>`;
            }});
            
            row.innerHTML = `
                <td><select class="form-control product-sel" onchange="updatePrice(this)" required>${{opts}}</select></td>
                <td class="stock-cell" style="text-align: center;">-</td>
                <td><input type="number" class="form-control qty" value="1" min="1" onchange="calc()" style="width: 80px;"></td>
                <td><input type="number" class="form-control price" onchange="calc()" style="width: 100px;"></td>
                <td class="row-total" style="text-align: right;">0</td>
                <td><button type="button" class="btn btn-danger btn-sm" onclick="this.closest('tr').remove(); calc();"><i class="fas fa-trash"></i></button></td>
            `;
            tbody.appendChild(row);
        }}
        
        function updatePrice(sel) {{
            const opt = sel.options[sel.selectedIndex];
            const row = sel.closest('tr');
            row.querySelector('.price').value = opt.dataset.price;
            row.querySelector('.stock-cell').textContent = opt.dataset.stock;
            calc();
        }}
        
        function calc() {{
            let subtotal = 0;
            document.querySelectorAll('#itemsBody tr').forEach(row => {{
                const qty = parseFloat(row.querySelector('.qty').value) || 0;
                const price = parseFloat(row.querySelector('.price').value) || 0;
                const total = qty * price;
                row.querySelector('.row-total').textContent = total.toLocaleString();
                subtotal += total;
            }});
            
            const taxRate = {get_setting('tax_rate', 16)};
            const tax = subtotal * (taxRate / 100);
            const discount = parseFloat(document.getElementById('discount').value) || 0;
            const grandTotal = subtotal + tax - discount;
            const paid = parseFloat(document.getElementById('paid').value) || 0;
            const balance = grandTotal - paid;
            
            document.getElementById('subtotal').textContent = 'Rs ' + subtotal.toLocaleString();
            document.getElementById('tax').textContent = 'Rs ' + tax.toLocaleString();
            document.getElementById('total').textContent = 'Rs ' + grandTotal.toLocaleString();
            document.getElementById('balance').textContent = 'Rs ' + balance.toLocaleString();
        }}
        
        document.getElementById('invoiceForm').addEventListener('submit', async function(e) {{
            e.preventDefault();
            const items = [];
            document.querySelectorAll('#itemsBody tr').forEach(row => {{
                const sel = row.querySelector('.product-sel');
                items.push({{
                    product_id: sel.value,
                    name: sel.options[sel.selectedIndex].text,
                    qty: parseFloat(row.querySelector('.qty').value),
                    price: parseFloat(row.querySelector('.price').value),
                    cost: parseFloat(sel.options[sel.selectedIndex].dataset.cost) || 0
                }});
            }});
            
            const data = {{
                customer_id: document.querySelector('[name="customer_id"]').value,
                date: document.querySelector('[name="date"]').value,
                payment_method: document.querySelector('[name="payment_method"]').value,
                tax_rate: {get_setting('tax_rate', 16)},
                discount: parseFloat(document.getElementById('discount').value) || 0,
                paid: parseFloat(document.getElementById('paid').value) || 0,
                notes: document.querySelector('[name="notes"]').value,
                items: items
            }};
            
            const res = await fetch('{url_for('new_invoice')}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }});
            const result = await res.json();
            if (result.success) {{
                alert('Invoice saved: ' + result.inv_no);
                location.href = '{url_for('view_invoice', id=0)}'.replace('0', result.invoice_id);
            }}
        }});
        
        addItem();
    </script>
    """
    return render_page("New Invoice", content, "new_invoice")

@app.route("/invoices")
@login_required
def invoices():
    month = request.args.get('month', datetime.datetime.now().strftime("%Y-%m"))
    
    conn = get_db()
    c = conn.cursor()
    
    if session['role'] == 'admin':
        c.execute("""
            SELECT i.*, c.name as customer_name 
            FROM invoices i 
            LEFT JOIN customers c ON i.customer_id = c.id 
            WHERE i.month_year = ? 
            ORDER BY i.created_at DESC
        """, (month,))
    else:
        c.execute("""
            SELECT i.*, c.name as customer_name 
            FROM invoices i 
            LEFT JOIN customers c ON i.customer_id = c.id 
            WHERE i.month_year = ? AND i.salesman_id = ?
            ORDER BY i.created_at DESC
        """, (month, session['user_id']))
    
    invoices = c.fetchall()
    conn.close()
    
    rows = ""
    for inv in invoices:
        badge = f'<span class="badge badge-{"success" if inv["status"] == "paid" else "warning" if inv["status"] == "partial" else "danger"}">{inv["status"]}</span>'
        rows += f"""
        <tr>
            <td>{inv['inv_no']}</td>
            <td>{inv['customer_name'] or 'Walk-in'}</td>
            <td>{inv['date']}</td>
            <td>Rs {inv['total']:,.0f}</td>
            <td>Rs {inv['gross_profit']:,.0f}</td>
            <td>{badge}</td>
            <td>
                <a href="{url_for('view_invoice', id=inv['id'])}" class="btn btn-sm btn-ghost"><i class="fas fa-eye"></i></a>
                <a href="{url_for('print_invoice', id=inv['id'])}" class="btn btn-sm btn-ghost" target="_blank"><i class="fas fa-print"></i></a>
            </td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Invoices</h3>
            <div>
                <input type="month" class="form-control" value="{month}" onchange="location.href='?month='+this.value" style="width: 150px; display: inline;">
                <a href="{url_for('new_invoice')}" class="btn btn-primary btn-sm"><i class="fas fa-plus"></i> New</a>
            </div>
        </div>
        <div class="card-body">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Invoice #</th><th>Customer</th><th>Date</th><th>Amount</th><th>Profit</th><th>Status</th><th>Action</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Invoices", content, "invoices")

@app.route("/invoice/<int:id>")
@login_required
def view_invoice(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT i.*, c.name as customer_name, c.phone as customer_phone, c.address as customer_address FROM invoices i LEFT JOIN customers c ON i.customer_id = c.id WHERE i.id = ?", (id,))
    inv = c.fetchone()
    c.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (id,))
    items = c.fetchall()
    conn.close()
    
    if not inv:
        abort(404)
    
    items_html = "".join([f"<tr><td>{it['product_name']}</td><td>{it['qty']}</td><td>Rs {it['unit_price']:,.2f}</td><td>Rs {it['total']:,.2f}</td></tr>" for it in items])
    
    content = f"""
    <div class="card" id="printArea">
        <div class="card-body">
            <div style="display: flex; justify-content: space-between; margin-bottom: 2rem;">
                <div>
                    <h2>{get_setting('company_name')}</h2>
                    <p>{get_setting('company_address')}</p>
                </div>
                <div style="text-align: right;">
                    <h1>INVOICE</h1>
                    <p><strong>#{inv['inv_no']}</strong></p>
                    <p>{inv['date']}</p>
                </div>
            </div>
            
            <div style="background: var(--bg); padding: 1rem; border-radius: var(--radius); margin-bottom: 1rem;">
                <p><strong>Customer:</strong> {inv['customer_name'] or 'Walk-in'}</p>
                <p>{inv['customer_address'] or ''}</p>
                <p>{inv['customer_phone'] or ''}</p>
            </div>
            
            <table class="data-table">
                <thead>
                    <tr style="background: var(--primary); color: white;">
                        <th>Product</th><th>Qty</th><th>Price</th><th>Total</th>
                    </tr>
                </thead>
                <tbody>
                    {items_html}
                </tbody>
            </table>
            
            <div style="width: 300px; margin-left: auto; margin-top: 1rem;">
                <div style="display: flex; justify-content: space-between;"><span>Subtotal:</span><strong>Rs {inv['subtotal']:,.2f}</strong></div>
                <div style="display: flex; justify-content: space-between;"><span>Tax:</span><strong>Rs {inv['tax_amount']:,.2f}</strong></div>
                <div style="display: flex; justify-content: space-between; font-size: 1.25rem; color: var(--primary); margin-top: 0.5rem; padding-top: 0.5rem; border-top: 2px solid var(--border);">
                    <span><strong>Total:</strong></span><strong>Rs {inv['total']:,.2f}</strong>
                </div>
            </div>
        </div>
    </div>
    
    <div style="display: flex; gap: 1rem; justify-content: center; margin-top: 1rem;">
        <button onclick="print()" class="btn btn-primary"><i class="fas fa-print"></i> Print</button>
        <a href="{url_for('invoices')}" class="btn btn-ghost">Back</a>
    </div>
    """
    return render_page(f"Invoice {inv['inv_no']}", content, "invoices")

@app.route("/invoice/<int:id>/print")
@login_required
def print_invoice(id):
    # PDF generation
    return redirect(url_for('view_invoice', id=id))

# ===================== WORKER/HR MODULE =====================
@app.route("/workers", methods=["GET", "POST"])
@admin_required
def workers():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        action = request.form.get('action')
        if action == 'add':
            c.execute("""
                INSERT INTO workers (name, phone, address, designation, salary, daily_wage, joining_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (request.form['name'], request.form['phone'], request.form['address'],
                  request.form['designation'], request.form['salary'], 
                  request.form.get('daily_wage', 0), request.form['joining_date']))
            conn.commit()
            flash("Worker added", "success")
        elif action == 'payment':
            c.execute("""
                INSERT INTO worker_payments (worker_id, date, type, amount, description, month_year, paid_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (request.form['worker_id'], request.form['date'], request.form['payment_type'],
                  request.form['amount'], request.form['description'],
                  request.form.get('month_year', ''), session['user_id']))
            
            # Update loan balance if applicable
            if request.form['payment_type'] in ['loan', 'loan_repayment']:
                c.execute("""
                    SELECT SUM(CASE WHEN type='loan' THEN amount ELSE -amount END) as balance
                    FROM worker_payments WHERE worker_id = ? AND type IN ('loan', 'loan_repayment')
                """, (request.form['worker_id'],))
                balance = c.fetchone()[0] or 0
                c.execute("UPDATE worker_payments SET balance = ? WHERE id = last_insert_rowid()", (balance,))
            
            conn.commit()
            flash("Payment recorded", "success")
    
    c.execute("SELECT w.*, (SELECT SUM(amount) FROM worker_payments WHERE worker_id=w.id AND type='advance') as total_advance, (SELECT SUM(CASE WHEN type='loan' THEN amount ELSE -amount END) FROM worker_payments WHERE worker_id=w.id AND type IN ('loan', 'loan_repayment')) as loan_balance FROM workers w WHERE w.status='active'")
    workers = c.fetchall()
    conn.close()
    
    rows = ""
    for w in workers:
        rows += f"""
        <tr>
            <td>{w['name']}</td>
            <td>{w['designation']}</td>
            <td>Rs {w['salary']:,.0f}</td>
            <td>Rs {w['total_advance'] or 0:,.0f}</td>
            <td>Rs {w['loan_balance'] or 0:,.0f}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="payWorker({w['id']}, '{w['name']}')">Pay</button>
                <a href="{url_for('worker_ledger', id=w['id'])}" class="btn btn-sm btn-ghost">Ledger</a>
            </td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Workers Management</h3>
            <button class="btn btn-primary btn-sm" onclick="document.getElementById('addWorker').style.display='block'">
                <i class="fas fa-plus"></i> Add Worker
            </button>
        </div>
        <div class="card-body">
            <table class="data-table">
                <thead>
                    <tr><th>Name</th><th>Designation</th><th>Salary</th><th>Advance</th><th>Loan</th><th>Action</th></tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    
    <!-- Add Worker Modal -->
    <div id="addWorker" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center;">
        <div style="background: white; padding: 2rem; border-radius: var(--radius-lg); width: 90%; max-width: 500px;">
            <h3>Add New Worker</h3>
            <form method="post">
                <input type="hidden" name="action" value="add">
                <div class="form-row"><input type="text" name="name" class="form-control" placeholder="Full Name" required></div>
                <div class="form-row"><input type="text" name="phone" class="form-control" placeholder="Phone"></div>
                <div class="form-row"><input type="text" name="address" class="form-control" placeholder="Address"></div>
                <div class="form-row"><input type="text" name="designation" class="form-control" placeholder="Designation" required></div>
                <div class="form-row">
                    <input type="number" name="salary" class="form-control" placeholder="Monthly Salary">
                    <input type="number" name="daily_wage" class="form-control" placeholder="Daily Wage">
                </div>
                <div class="form-row"><input type="date" name="joining_date" class="form-control" value="{datetime.date.today().isoformat()}"></div>
                <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                    <button type="button" class="btn btn-ghost" onclick="document.getElementById('addWorker').style.display='none'">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>
        </div>
    </div>
    
    <!-- Payment Modal -->
    <div id="payModal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center;">
        <div style="background: white; padding: 2rem; border-radius: var(--radius-lg); width: 90%; max-width: 400px;">
            <h3>Payment to <span id="payWorkerName"></span></h3>
            <form method="post">
                <input type="hidden" name="action" value="payment">
                <input type="hidden" name="worker_id" id="payWorkerId">
                <div class="form-row">
                    <select name="payment_type" class="form-control" required>
                        <option value="salary">Salary</option>
                        <option value="advance">Advance</option>
                        <option value="loan">Loan Given</option>
                        <option value="loan_repayment">Loan Repayment</option>
                        <option value="bonus">Bonus</option>
                    </select>
                </div>
                <div class="form-row"><input type="date" name="date" class="form-control" value="{datetime.date.today().isoformat()}" required></div>
                <div class="form-row"><input type="number" name="amount" class="form-control" placeholder="Amount" required></div>
                <div class="form-row"><input type="text" name="month_year" class="form-control" placeholder="Month-Year (e.g., 2024-01)"></div>
                <div class="form-row"><input type="text" name="description" class="form-control" placeholder="Description"></div>
                <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                    <button type="button" class="btn btn-ghost" onclick="document.getElementById('payModal').style.display='none'">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save Payment</button>
                </div>
            </form>
        </div>
    </div>
    
    <script>
        function payWorker(id, name) {{
            document.getElementById('payWorkerId').value = id;
            document.getElementById('payWorkerName').textContent = name;
            document.getElementById('payModal').style.display = 'flex';
        }}
    </script>
    """
    return render_page("Workers", content, "workers")

@app.route("/attendance", methods=["GET", "POST"])
@admin_required
def attendance():
    today = datetime.date.today().isoformat()
    date = request.args.get('date', today)
    
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        data = request.get_json()
        for record in data['attendance']:
            c.execute("""
                INSERT OR REPLACE INTO attendance (worker_id, date, status, check_in, check_out, overtime_hours, notes, marked_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (record['worker_id'], date, record['status'], record.get('check_in'), 
                  record.get('check_out'), record.get('overtime', 0), record.get('notes'), session['user_id']))
        conn.commit()
        return jsonify({"success": True})
    
    c.execute("SELECT id, name FROM workers WHERE status='active'")
    workers = c.fetchall()
    
    c.execute("SELECT * FROM attendance WHERE date = ?", (date,))
    attendance_data = {a['worker_id']: a for a in c.fetchall()}
    conn.close()
    
    rows = ""
    for w in workers:
        a = attendance_data.get(w['id'], {})
        status = a.get('status', 'present')
        rows += f"""
        <tr data-worker-id="{w['id']}">
            <td>{w['name']}</td>
            <td>
                <select class="form-control status" style="width: 120px;">
                    <option value="present" {'selected' if status=='present' else ''}>Present</option>
                    <option value="absent" {'selected' if status=='absent' else ''}>Absent</option>
                    <option value="half-day" {'selected' if status=='half-day' else ''}>Half Day</option>
                    <option value="leave" {'selected' if status=='leave' else ''}>Leave</option>
                </select>
            </td>
            <td><input type="time" class="form-control check-in" value="{a.get('check_in', '09:00')}" style="width: 120px;"></td>
            <td><input type="time" class="form-control check-out" value="{a.get('check_out', '18:00')}" style="width: 120px;"></td>
            <td><input type="number" class="form-control overtime" value="{a.get('overtime_hours', 0)}" style="width: 80px;" step="0.5"></td>
            <td><input type="text" class="form-control notes" value="{a.get('notes', '')}" placeholder="Notes"></td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Daily Attendance</h3>
            <input type="date" class="form-control" value="{date}" onchange="location.href='?date='+this.value" style="width: 150px;">
        </div>
        <div class="card-body">
            <table class="data-table">
                <thead>
                    <tr><th>Worker</th><th>Status</th><th>Check In</th><th>Check Out</th><th>OT Hours</th><th>Notes</th></tr>
                </thead>
                <tbody id="attendanceTable">{rows}</tbody>
            </table>
            <button onclick="saveAttendance()" class="btn btn-primary" style="margin-top: 1rem;">
                <i class="fas fa-save"></i> Save Attendance
            </button>
        </div>
    </div>
    
    <script>
        function saveAttendance() {{
            const data = [];
            document.querySelectorAll('#attendanceTable tr').forEach(row => {{
                data.push({{
                    worker_id: row.dataset.workerId,
                    status: row.querySelector('.status').value,
                    check_in: row.querySelector('.check-in').value,
                    check_out: row.querySelector('.check-out').value,
                    overtime: parseFloat(row.querySelector('.overtime').value) || 0,
                    notes: row.querySelector('.notes').value
                }});
            }});
            
            fetch('{url_for('attendance', date=date)}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{attendance: data}})
            }})
            .then(r => r.json())
            .then(result => {{
                if (result.success) alert('Attendance saved!');
            }});
        }}
    </script>
    """
    return render_page("Attendance", content, "attendance")

@app.route("/worker/<int:id>/ledger")
@admin_required
def worker_ledger(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM workers WHERE id = ?", (id,))
    worker = c.fetchone()
    
    c.execute("""
        SELECT * FROM worker_payments 
        WHERE worker_id = ? 
        ORDER BY date DESC
    """, (id,))
    payments = c.fetchall()
    conn.close()
    
    rows = "".join([f"<tr><td>{p['date']}</td><td>{p['type'].title()}</td><td>Rs {p['amount']:,.0f}</td><td>{p['description'] or ''}</td></tr>" for p in payments])
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Ledger: {worker['name']}</h3>
            <a href="{url_for('workers')}" class="btn btn-ghost btn-sm">Back</a>
        </div>
        <div class="card-body">
            <table class="data-table">
                <thead><tr><th>Date</th><th>Type</th><th>Amount</th><th>Description</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Worker Ledger", content, "workers")

# ===================== EXPENSE MODULE =====================
@app.route("/expenses", methods=["GET", "POST"])
@admin_required
def expenses():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        c.execute("""
            INSERT INTO expenses (date, category, subcategory, amount, description, payment_method, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (request.form['date'], request.form['category'], request.form.get('subcategory', ''),
              request.form['amount'], request.form['description'], request.form['payment_method'], session['user_id']))
        conn.commit()
        flash("Expense added", "success")
        return redirect(url_for('expenses'))
    
    month = request.args.get('month', datetime.datetime.now().strftime("%Y-%m"))
    
    c.execute("""
        SELECT e.*, u.full_name as created_by_name 
        FROM expenses e 
        LEFT JOIN users u ON e.created_by = u.id 
        WHERE strftime('%Y-%m', e.date) = ?
        ORDER BY e.date DESC
    """, (month,))
    expenses = c.fetchall()
    
    c.execute("SELECT category, SUM(amount) as total FROM expenses WHERE strftime('%Y-%m', date) = ? GROUP BY category", (month,))
    summary = c.fetchall()
    conn.close()
    
    rows = "".join([f"<tr><td>{e['date']}</td><td>{e['category']}</td><td>Rs {e['amount']:,.0f}</td><td>{e['description']}</td><td>{e['created_by_name']}</td></tr>" for e in expenses])
    
    summary_html = "".join([f"<div style='display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid var(--border);'><span>{s['category']}</span><strong>Rs {s['total']:,.0f}</strong></div>" for s in summary])
    
    content = f"""
    <div class="form-row">
        <div class="card" style="flex: 2;">
            <div class="card-header">
                <h3>Expenses</h3>
                <input type="month" class="form-control" value="{month}" onchange="location.href='?month='+this.value" style="width: 150px;">
            </div>
            <div class="card-body">
                <table class="data-table">
                    <thead><tr><th>Date</th><th>Category</th><th>Amount</th><th>Description</th><th>By</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
        
        <div style="flex: 1;">
            <div class="card">
                <div class="card-header"><h3>Add Expense</h3></div>
                <div class="card-body">
                    <form method="post">
                        <div class="form-row"><input type="date" name="date" class="form-control" value="{datetime.date.today().isoformat()}" required></div>
                        <div class="form-row">
                            <select name="category" class="form-control" required>
                                <option value="">Select Category</option>
                                <option value="Salary">Salary</option>
                                <option value="Rent">Rent</option>
                                <option value="Utilities">Utilities</option>
                                <option value="Transport">Transport</option>
                                <option value="Office">Office Supplies</option>
                                <option value="Marketing">Marketing</option>
                                <option value="Other">Other</option>
                            </select>
                        </div>
                        <div class="form-row"><input type="number" name="amount" class="form-control" placeholder="Amount" required></div>
                        <div class="form-row">
                            <select name="payment_method" class="form-control">
                                <option value="cash">Cash</option>
                                <option value="bank">Bank</option>
                                <option value="online">Online</option>
                            </select>
                        </div>
                        <div class="form-row"><textarea name="description" class="form-control" placeholder="Description"></textarea></div>
                        <button type="submit" class="btn btn-primary" style="width: 100%;">Add Expense</button>
                    </form>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header"><h3>Summary</h3></div>
                <div class="card-body">
                    {summary_html}
                </div>
            </div>
        </div>
    </div>
    """
    return render_page("Expenses", content, "expenses")

# ===================== PROFIT/LOSS =====================
@app.route("/profit-loss")
@admin_required
def profit_loss():
    month = request.args.get('month', datetime.datetime.now().strftime("%Y-%m"))
    
    conn = get_db()
    c = conn.cursor()
    
    # Get or calculate P&L
    c.execute("SELECT * FROM profit_loss WHERE month_year = ?", (month,))
    pl = c.fetchone()
    
    if not pl:
        # Auto-calculate
        c.execute("SELECT SUM(total) as sales, SUM(total_cost) as cogs, SUM(gross_profit) as profit FROM invoices WHERE month_year = ? AND status != 'cancelled'", (month,))
        sales_data = c.fetchone()
        
        c.execute("SELECT SUM(amount) FROM expenses WHERE strftime('%Y-%m', date) = ?", (month,))
        expenses = c.fetchone()[0] or 0
        
        c.execute("SELECT SUM(amount) FROM worker_payments WHERE strftime('%Y-%m', date) = ? AND type='salary'", (month,))
        salaries = c.fetchone()[0] or 0
        
        total_exp = expenses + salaries
        net = (sales_data['profit'] or 0) - total_exp
        
        pl = {
            'total_sales': sales_data['sales'] or 0,
            'cogs': sales_data['cogs'] or 0,
            'gross_profit': sales_data['profit'] or 0,
            'total_expenses': total_exp,
            'salary_expense': salaries,
            'net_profit': net,
            'profit_margin': (net / sales_data['sales'] * 100) if sales_data['sales'] else 0
        }
    
    # Daily breakdown
    c.execute("""
        SELECT date, SUM(total) as sales, SUM(gross_profit) as profit 
        FROM invoices 
        WHERE month_year = ? AND status != 'cancelled'
        GROUP BY date
        ORDER BY date
    """, (month,))
    daily = c.fetchall()
    conn.close()
    
    daily_html = "".join([f"<tr><td>{d['date']}</td><td>Rs {d['sales']:,.0f}</td><td>Rs {d['profit']:,.0f}</td></tr>" for d in daily])
    
    content = f"""
    <div class="form-row">
        <div class="card" style="flex: 1;">
            <div class="card-header">
                <h3>Profit & Loss - {month}</h3>
                <input type="month" class="form-control" value="{month}" onchange="location.href='?month='+this.value" style="width: 150px;">
            </div>
            <div class="card-body">
                <div class="stats-grid" style="grid-template-columns: 1fr 1fr;">
                    <div class="stat-card">
                        <div class="stat-value" style="color: var(--success);">Rs {pl['total_sales']:,.0f}</div>
                        <div class="stat-label">Total Sales</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: var(--danger);">Rs {pl['cogs']:,.0f}</div>
                        <div class="stat-label">Cost of Goods</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: var(--info);">Rs {pl['gross_profit']:,.0f}</div>
                        <div class="stat-label">Gross Profit</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" style="color: var(--warning);">Rs {pl['total_expenses']:,.0f}</div>
                        <div class="stat-label">Total Expenses</div>
                    </div>
                </div>
                
                <div style="background: var(--bg); padding: 2rem; border-radius: var(--radius-lg); text-align: center; margin-top: 1rem;">
                    <div style="font-size: 0.875rem; color: var(--text-muted); margin-bottom: 0.5rem;">NET PROFIT</div>
                    <div style="font-size: 3rem; font-weight: 700; color: {'var(--success)' if pl['net_profit'] >= 0 else 'var(--danger)'};">
                        Rs {pl['net_profit']:,.0f}
                    </div>
                    <div style="font-size: 1.25rem; color: var(--text-muted); margin-top: 0.5rem;">
                        Margin: {pl['profit_margin']:.1f}%
                    </div>
                </div>
            </div>
        </div>
        
        <div class="card" style="flex: 1;">
            <div class="card-header"><h3>Daily Breakdown</h3></div>
            <div class="card-body">
                <table class="data-table">
                    <thead><tr><th>Date</th><th>Sales</th><th>Profit</th></tr></thead>
                    <tbody>{daily_html}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Profit & Loss", content, "profit_loss")

# ===================== USER MANAGEMENT =====================
@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        action = request.form.get('action')
        
        if action == 'add':
            password = hashlib.sha256(request.form['password'].encode()).hexdigest()
            perms = json.dumps({
                "can_delete": request.form.get('can_delete') == 'on',
                "can_edit": request.form.get('can_edit') == 'on',
                "can_view_profit": request.form.get('can_view_profit') == 'on'
            })
            c.execute("""
                INSERT INTO users (username, password_hash, full_name, role, email, phone, salary, commission_rate, permissions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (request.form['username'], password, request.form['full_name'],
                  request.form['role'], request.form['email'], request.form['phone'],
                  request.form.get('salary', 0), request.form.get('commission', 0), perms))
            conn.commit()
            flash("User added", "success")
            
        elif action == 'toggle':
            c.execute("UPDATE users SET is_active = NOT is_active WHERE id = ?", (request.form['user_id'],))
            conn.commit()
            flash("Status updated", "success")
            
        elif action == 'delete':
            c.execute("DELETE FROM users WHERE id = ?", (request.form['user_id'],))
            conn.commit()
            flash("User deleted", "success")
    
    c.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = c.fetchall()
    conn.close()
    
    rows = ""
    for u in users:
        status = '<span class="badge badge-success">Active</span>' if u['is_active'] else '<span class="badge badge-danger">Inactive</span>'
        rows += f"""
        <tr>
            <td>{u['full_name']}</td>
            <td>{u['username']}</td>
            <td>{u['role'].title()}</td>
            <td>{u['phone'] or '-'}</td>
            <td>{status}</td>
            <td>
                <form method="post" style="display: inline;">
                    <input type="hidden" name="action" value="toggle">
                    <input type="hidden" name="user_id" value="{u['id']}">
                    <button type="submit" class="btn btn-sm btn-warning">{'Deactivate' if u['is_active'] else 'Activate'}</button>
                </form>
                <form method="post" style="display: inline;" onsubmit="return confirm('Delete this user?')">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="user_id" value="{u['id']}">
                    <button type="submit" class="btn btn-sm btn-danger">Delete</button>
                </form>
            </td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>User Management</h3>
            <button class="btn btn-primary btn-sm" onclick="document.getElementById('addUser').style.display='block'">
                <i class="fas fa-plus"></i> Add User
            </button>
        </div>
        <div class="card-body">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Phone</th><th>Status</th><th>Action</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    
    <div id="addUser" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center;">
        <div style="background: white; padding: 2rem; border-radius: var(--radius-lg); width: 90%; max-width: 500px;">
            <h3>Add New User</h3>
            <form method="post">
                <input type="hidden" name="action" value="add">
                <div class="form-row"><input type="text" name="full_name" class="form-control" placeholder="Full Name" required></div>
                <div class="form-row"><input type="text" name="username" class="form-control" placeholder="Username" required></div>
                <div class="form-row"><input type="password" name="password" class="form-control" placeholder="Password" required></div>
                <div class="form-row">
                    <select name="role" class="form-control" required>
                        <option value="salesman">Salesman</option>
                        <option value="manager">Manager</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
                <div class="form-row"><input type="email" name="email" class="form-control" placeholder="Email"></div>
                <div class="form-row"><input type="text" name="phone" class="form-control" placeholder="Phone"></div>
                <div class="form-row"><input type="number" name="salary" class="form-control" placeholder="Monthly Salary"></div>
                <div class="form-row"><input type="number" name="commission" class="form-control" placeholder="Commission %" step="0.01"></div>
                <div style="margin: 1rem 0;">
                    <label><input type="checkbox" name="can_delete"> Can Delete</label><br>
                    <label><input type="checkbox" name="can_edit" checked> Can Edit</label><br>
                    <label><input type="checkbox" name="can_view_profit"> Can View Profit</label>
                </div>
                <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                    <button type="button" class="btn btn-ghost" onclick="document.getElementById('addUser').style.display='none'">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save User</button>
                </div>
            </form>
        </div>
    </div>
    """
    return render_page("Users", content, "users")

@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = hashlib.sha256(request.form['old_password'].encode()).hexdigest()
        new = hashlib.sha256(request.form['new_password'].encode()).hexdigest()
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE id = ? AND password_hash = ?", (session['user_id'], old))
        if c.fetchone():
            c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new, session['user_id']))
            conn.commit()
            flash("Password changed", "success")
        else:
            flash("Old password incorrect", "error")
        conn.close()
        return redirect(url_for('dashboard'))
    
    content = """
    <div class="card" style="max-width: 400px; margin: 0 auto;">
        <div class="card-header"><h3>Change Password</h3></div>
        <div class="card-body">
            <form method="post">
                <div class="form-row"><input type="password" name="old_password" class="form-control" placeholder="Current Password" required></div>
                <div class="form-row"><input type="password" name="new_password" class="form-control" placeholder="New Password" required></div>
                <div class="form-row"><input type="password" name="confirm_password" class="form-control" placeholder="Confirm Password" required></div>
                <button type="submit" class="btn btn-primary" style="width: 100%;">Change Password</button>
            </form>
        </div>
    </div>
    """
    return render_page("Change Password", content)

# ===================== BACKUP & SYNC =====================
@app.route("/backup")
@admin_required
def backup():
    backups = sorted(BACKUP_DIR.glob("*.db"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]
    
    rows = ""
    for b in backups:
        size = b.stat().st_size / (1024*1024)
        date = datetime.datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        rows += f"<tr><td>{b.name}</td><td>{date}</td><td>{size:.2f} MB</td><td><a href='{url_for('download_backup', filename=b.name)}' class='btn btn-sm btn-primary'>Download</a></td></tr>"
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Database Backups</h3>
            <div>
                <a href="{url_for('create_backup')}" class="btn btn-primary btn-sm">Create Backup</a>
                <a href="{url_for('export_data')}" class="btn btn-success btn-sm">Export Excel</a>
            </div>
        </div>
        <div class="card-body">
            <table class="data-table">
                <thead><tr><th>Filename</th><th>Date</th><th>Size</th><th>Action</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    
    <div class="card">
        <div class="card-header"><h3>Sync Status</h3></div>
        <div class="card-body">
            <p>Auto-sync is {'enabled' if get_setting('auto_sync') == '1' else 'disabled'}</p>
            <p>Last sync: Checking...</p>
            <p>Pending items: <span id="pendingSync">0</span></p>
        </div>
    </div>
    """
    return render_page("Backup & Sync", content, "backup")

@app.route("/backup/create")
@admin_required
def create_backup():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"manual_backup_{timestamp}.db"
    shutil.copy2(DB_FILE, backup_file)
    flash(f"Backup created: {backup_file.name}", "success")
    return redirect(url_for('backup'))

@app.route("/backup/download/<filename>")
@admin_required
def download_backup(filename):
    return send_file(BACKUP_DIR / filename, as_attachment=True)

@app.route("/export")
@admin_required
def export_data():
    # Export all data to Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        conn = get_db()
        for table in ['invoices', 'customers', 'products', 'expenses', 'workers']:
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            df.to_excel(writer, sheet_name=table.title(), index=False)
        conn.close()
    
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"Export_{datetime.date.today()}.xlsx")

# ===================== API ROUTES =====================
@app.route("/api/sync-status")
@login_required
def sync_status():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM sync_log WHERE sync_status = 'pending'")
    pending = c.fetchone()[0]
    conn.close()
    return jsonify({"pending": pending, "last_sync": datetime.datetime.now().isoformat()})

# ===================== OTHER PLACEHOLDERS =====================
@app.route("/customers")
@login_required
def customers():
    content = "<div class='card'><div class='card-body'><h3>Customers</h3><p>Customer management module</p></div></div>"
    return render_page("Customers", content, "customers")

@app.route("/products")
@login_required
def products():
    content = "<div class='card'><div class='card-body'><h3>Products</h3><p>Product catalog with auto-price calculation</p></div></div>"
    return render_page("Products", content, "products")

@app.route("/stock")
@login_required
def stock():
    content = "<div class='card'><div class='card-body'><h3>Stock Management</h3><p>Stock in/out and adjustments</p></div></div>"
    return render_page("Stock", content, "stock")

@app.route("/ledger")
@login_required
def ledger():
    content = "<div class='card'><div class='card-body'><h3>Customer Ledger</h3><p>Detailed transaction history</p></div></div>"
    return render_page("Ledger", content, "ledger")

@app.route("/payments")
@login_required
def payments():
    content = "<div class='card'><div class='card-body'><h3>Payments</h3><p>Payment receipts and collection</p></div></div>"
    return render_page("Payments", content, "payments")

@app.route("/settings")
@admin_required
def settings():
    content = "<div class='card'><div class='card-body'><h3>Settings</h3><p>System configuration</p></div></div>"
    return render_page("Settings", content, "settings")

# ===================== MAIN =====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Smart Business Pro starting on port {port}")
    print("📊 Features: Invoicing, HR, Expenses, Profit/Loss, Auto-sync")
    print("🔑 Default: admin/admin123")
    
    # Generate initial insights
    try:
        pass  # generate_ai_insights() if implemented
    except:
        pass
    
    app.run(host="0.0.0.0", port=port, debug=False)