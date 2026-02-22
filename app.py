# app.py — Smart Invoice Pro (Complete Fixed Version)
# ===================================================

from pathlib import Path
import sys
import os
import datetime
import json
import hashlib
import shutil
from typing import Optional, List, Dict, Tuple
import sqlite3
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, render_template_string,
    flash, jsonify, session, send_file, abort
)
from werkzeug.utils import secure_filename
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
import textwrap

# ===================== CONFIGURATION =====================
if getattr(sys, 'frozen', False):
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path(__file__).parent if '__file__' in dir() else Path.cwd()

BASE_DATA = ROOT / "data"
DB_DIR = BASE_DATA / "db"
UPLOADS_DIR = BASE_DATA / "uploads"
BACKUP_DIR = BASE_DATA / "backups"
EXPORT_DIR = BASE_DATA / "exports"

for folder in (DB_DIR, UPLOADS_DIR, BACKUP_DIR, EXPORT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

DB_FILE = DB_DIR / "business.db"
app = Flask(__name__)
app.secret_key = "your-secret-key-change-this-in-production-2024"

# ===================== HTML TEMPLATES (INLINE) =====================
# Base template components
HTML_HEAD = """
<!DOCTYPE html>
<html lang="en" data-theme="{{ session.get('theme', 'light') }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        :root {
            --primary: #3b82f6;
            --primary-dark: #2563eb;
            --secondary: #64748b;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --info: #06b6d4;
            --bg: #f1f5f9;
            --card: #ffffff;
            --text: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        
        [data-theme="dark"] {
            --bg: #0f172a;
            --card: #1e293b;
            --text: #f1f5f9;
            --text-muted: #94a3b8;
            --border: #334155;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }
        
        .sidebar {
            position: fixed;
            left: 0;
            top: 0;
            width: 260px;
            height: 100vh;
            background: var(--card);
            border-right: 1px solid var(--border);
            z-index: 1000;
            transition: transform 0.3s;
        }
        
        .sidebar-header {
            padding: 1.5rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .sidebar-header i {
            font-size: 2rem;
            color: var(--primary);
        }
        
        .sidebar-header h1 {
            font-size: 1.25rem;
            font-weight: 700;
        }
        
        .nav-menu {
            padding: 1rem 0;
        }
        
        .nav-item {
            display: flex;
            align-items: center;
            padding: 0.875rem 1.5rem;
            color: var(--text-muted);
            text-decoration: none;
            transition: all 0.2s;
            border-left: 3px solid transparent;
        }
        
        .nav-item:hover, .nav-item.active {
            background: rgba(59, 130, 246, 0.1);
            color: var(--primary);
            border-left-color: var(--primary);
        }
        
        .nav-item i {
            width: 24px;
            margin-right: 12px;
        }
        
        .main-content {
            margin-left: 260px;
            min-height: 100vh;
        }
        
        .top-bar {
            background: var(--card);
            padding: 1rem 2rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .user-menu {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .user-avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--primary);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
        }
        
        .content {
            padding: 2rem;
        }
        
        .page-header {
            margin-bottom: 2rem;
        }
        
        .page-header h2 {
            font-size: 1.875rem;
            margin-bottom: 0.5rem;
        }
        
        .card {
            background: var(--card);
            border-radius: 12px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .stat-card {
            background: var(--card);
            padding: 1.5rem;
            border-radius: 12px;
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
        }
        
        .stat-card .icon {
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            margin-bottom: 1rem;
        }
        
        .stat-card.primary .icon { background: rgba(59, 130, 246, 0.1); color: var(--primary); }
        .stat-card.success .icon { background: rgba(16, 185, 129, 0.1); color: var(--success); }
        .stat-card.warning .icon { background: rgba(245, 158, 11, 0.1); color: var(--warning); }
        .stat-card.danger .icon { background: rgba(239, 68, 68, 0.1); color: var(--danger); }
        
        .stat-value {
            font-size: 1.875rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }
        
        .stat-label {
            color: var(--text-muted);
            font-size: 0.875rem;
        }
        
        .table-container {
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th, td {
            padding: 1rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        
        th {
            background: rgba(59, 130, 246, 0.05);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
            color: var(--text-muted);
        }
        
        tr:hover {
            background: rgba(59, 130, 246, 0.02);
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.625rem 1.25rem;
            border-radius: 8px;
            font-weight: 500;
            text-decoration: none;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: var(--primary-dark); }
        
        .btn-success { background: var(--success); color: white; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-secondary { background: var(--secondary); color: white; }
        
        .btn-sm { padding: 0.375rem 0.75rem; font-size: 0.875rem; }
        
        .form-group {
            margin-bottom: 1.25rem;
        }
        
        .form-label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            font-size: 0.875rem;
        }
        
        .form-control {
            width: 100%;
            padding: 0.625rem 0.875rem;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--card);
            color: var(--text);
            font-size: 0.875rem;
            transition: border-color 0.2s;
        }
        
        .form-control:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }
        
        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }
        
        .alert {
            padding: 1rem 1.25rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .alert-success { background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.2); }
        .alert-error { background: rgba(239, 68, 68, 0.1); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.2); }
        .alert-warning { background: rgba(245, 158, 11, 0.1); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.2); }
        
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
        .badge-info { background: rgba(6, 182, 212, 0.1); color: var(--info); }
        
        .login-container {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 2rem;
        }
        
        .login-box {
            background: var(--card);
            padding: 2.5rem;
            border-radius: 16px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 420px;
        }
        
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        
        .login-header i {
            font-size: 3rem;
            color: var(--primary);
            margin-bottom: 1rem;
        }
        
        @media (max-width: 768px) {
            .sidebar { transform: translateX(-100%); }
            .sidebar.open { transform: translateX(0); }
            .main-content { margin-left: 0; }
            .stats-grid { grid-template-columns: 1fr; }
        }
        
        @media print {
            .sidebar, .top-bar, .no-print { display: none !important; }
            .main-content { margin-left: 0 !important; }
        }
    </style>
</head>
<body>
"""

HTML_SIDEBAR = """
    <aside class="sidebar">
        <div class="sidebar-header">
            <i class="fas fa-file-invoice-dollar"></i>
            <div>
                <h1>Smart Invoice</h1>
                <small style="color: var(--text-muted);">Pro</small>
            </div>
        </div>
        
        <nav class="nav-menu">
            <a href="{url_dashboard}" class="nav-item {active_dashboard}">
                <i class="fas fa-home"></i> Dashboard
            </a>
            <a href="{url_new_invoice}" class="nav-item {active_new_invoice}">
                <i class="fas fa-plus-circle"></i> New Invoice
            </a>
            <a href="{url_invoices}" class="nav-item {active_invoices}">
                <i class="fas fa-file-invoice"></i> Invoices
            </a>
            <a href="{url_customers}" class="nav-item {active_customers}">
                <i class="fas fa-users"></i> Customers
            </a>
            <a href="{url_products}" class="nav-item {active_products}">
                <i class="fas fa-boxes"></i> Products
            </a>
            <a href="{url_ledger}" class="nav-item {active_ledger}">
                <i class="fas fa-book"></i> Ledger
            </a>
            
            {admin_menu}
        </nav>
    </aside>
    
    <main class="main-content">
        <header class="top-bar">
            <div>
                <h3 style="font-weight: 600;">{page_title}</h3>
            </div>
            <div class="user-menu">
                <span style="color: var(--text-muted);">{full_name}</span>
                <div class="user-avatar">{avatar}</div>
                <a href="{url_logout}" class="btn btn-secondary btn-sm">
                    <i class="fas fa-sign-out-alt"></i> Logout
                </a>
            </div>
        </header>
        
        <div class="content">
            {alerts}
            {content}
        </div>
    </main>
"""

HTML_LOGIN = """
    <div class="login-container">
        <div class="login-box">
            <div class="login-header">
                <i class="fas fa-file-invoice-dollar"></i>
                <h2>Smart Invoice Pro</h2>
                <p style="color: var(--text-muted);">Business Management System</p>
            </div>
            
            {alerts}
            
            <form method="post">
                <div class="form-group">
                    <label class="form-label">Username</label>
                    <input type="text" name="username" class="form-control" placeholder="Enter username" required autofocus>
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input type="password" name="password" class="form-control" placeholder="Enter password" required>
                </div>
                <button type="submit" class="btn btn-primary" style="width: 100%; justify-content: center;">
                    <i class="fas fa-sign-in-alt"></i> Login
                </button>
            </form>
            
            <div style="text-align: center; margin-top: 1.5rem; color: var(--text-muted); font-size: 0.875rem;">
                <p>Default: admin / admin123</p>
            </div>
        </div>
    </div>
"""

HTML_FOOTER = """
</body>
</html>
"""

# ===================== DATABASE SCHEMA =====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Users table (Multi-login system)
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        role TEXT DEFAULT 'salesman',
        phone TEXT,
        email TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_login TEXT
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
    
    # Products
    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        unit_price REAL DEFAULT 0,
        purchase_price REAL DEFAULT 0,
        stock REAL DEFAULT 0,
        min_stock REAL DEFAULT 0,
        unit TEXT DEFAULT 'pcs',
        category TEXT,
        barcode TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Customers
    c.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        phone TEXT,
        email TEXT,
        credit_limit REAL DEFAULT 0,
        balance REAL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, phone)
    )
    """)
    
    # Invoices
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inv_no TEXT UNIQUE NOT NULL,
        date TEXT,
        customer_id INTEGER,
        customer_name TEXT,
        customer_address TEXT,
        customer_phone TEXT,
        salesman_id INTEGER,
        salesman_name TEXT,
        subtotal REAL DEFAULT 0,
        tax_rate REAL DEFAULT 0,
        tax_amount REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        total REAL DEFAULT 0,
        paid REAL DEFAULT 0,
        balance REAL DEFAULT 0,
        status TEXT DEFAULT 'pending',
        payment_method TEXT DEFAULT 'cash',
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (salesman_id) REFERENCES users(id)
    )
    """)
    
    # Invoice Items
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        product_id INTEGER,
        product_name TEXT,
        qty REAL,
        unit_price REAL,
        total REAL,
        FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)
    
    # Transactions (Ledger)
    c.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        customer_id INTEGER,
        invoice_id INTEGER,
        type TEXT,
        amount REAL,
        balance REAL,
        description TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (invoice_id) REFERENCES invoices(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    
    # Expenses
    c.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        category TEXT,
        amount REAL,
        description TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    
    # Activity Log
    c.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        details TEXT,
        ip_address TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)
    
    conn.commit()
    
    # Create default admin if not exists
    c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
    if not c.fetchone():
        admin_pass = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute("""
            INSERT INTO users (username, password_hash, full_name, role, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, ("admin", admin_pass, "System Administrator", "admin", 1))
        
        # Default settings
        defaults = [
            ("company_name", "Your Business Name"),
            ("company_address", "Your Business Address"),
            ("company_phone", "+92-XXX-XXXXXXX"),
            ("company_email", "info@yourbusiness.com"),
            ("tax_rate", "16"),
            ("currency", "PKR"),
            ("invoice_prefix", "INV-"),
            ("theme", "light")
        ]
        c.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults)
        
        conn.commit()
        print("✅ Default admin created: username='admin', password='admin123'")
    
    conn.close()
    print("✅ Database initialized successfully")

init_db()

# ===================== HELPER FUNCTIONS =====================
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
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

def log_activity(user_id, action, details=""):
    conn = get_db()
    c = conn.cursor()
    ip = request.remote_addr if request else 'unknown'
    c.execute("""
        INSERT INTO activity_log (user_id, action, details, ip_address)
        VALUES (?, ?, ?, ?)
    """, (user_id, action, details, ip))
    conn.commit()
    conn.close()

def get_setting(key, default=""):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else default

def generate_invoice_number():
    prefix = get_setting("invoice_prefix", "INV-")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as count FROM invoices")
    count = c.fetchone()['count'] + 1
    conn.close()
    return f"{prefix}{datetime.datetime.now().strftime('%Y%m')}-{count:04d}"

def render_page(title, page_title, content, active_menu="dashboard"):
    """Helper function to render a full page with sidebar"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Build alerts HTML
    alerts_html = ""
    messages = session.get('_flashes', [])
    for category, message in messages:
        alerts_html += f'<div class="alert alert-{category}"><i class="fas fa-{"check-circle" if category == "success" else "exclamation-circle" if category == "error" else "info-circle"}"></i> {message}</div>'
    session['_flashes'] = []  # Clear flashes
    
    # Build admin menu if user is admin
    admin_menu = ""
    if session.get('role') == 'admin':
        admin_menu = """
            <div style="margin-top: 2rem; padding: 0 1.5rem; color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;">
                Administration
            </div>
            <a href="{url_users}" class="nav-item {active_users}">
                <i class="fas fa-user-shield"></i> Users
            </a>
            <a href="{url_settings}" class="nav-item {active_settings}">
                <i class="fas fa-cog"></i> Settings
            </a>
            <a href="{url_backup}" class="nav-item {active_backup}">
                <i class="fas fa-database"></i> Backup
            </a>
        """.format(
            url_users=url_for('users'),
            url_settings=url_for('settings'),
            url_backup=url_for('backup'),
            active_users="active" if active_menu == "users" else "",
            active_settings="active" if active_menu == "settings" else "",
            active_backup="active" if active_menu == "backup" else ""
        )
    
    # Build sidebar
    sidebar_html = HTML_SIDEBAR.format(
        url_dashboard=url_for('dashboard'),
        url_new_invoice=url_for('new_invoice'),
        url_invoices=url_for('invoices'),
        url_customers=url_for('customers'),
        url_products=url_for('products'),
        url_ledger=url_for('ledger'),
        url_logout=url_for('logout'),
        active_dashboard="active" if active_menu == "dashboard" else "",
        active_new_invoice="active" if active_menu == "new_invoice" else "",
        active_invoices="active" if active_menu == "invoices" else "",
        active_customers="active" if active_menu == "customers" else "",
        active_products="active" if active_menu == "products" else "",
        active_ledger="active" if active_menu == "ledger" else "",
        admin_menu=admin_menu,
        page_title=page_title,
        full_name=session.get('full_name', 'User'),
        avatar=session.get('full_name', 'U')[0].upper(),
        alerts=alerts_html,
        content=content
    )
    
    head = HTML_HEAD.replace("{title}", title)
    return head + sidebar_html + HTML_FOOTER

def render_login_page(alerts=""):
    """Render login page"""
    head = HTML_HEAD.replace("{title}", "Login - Smart Invoice Pro")
    return head + HTML_LOGIN.replace("{alerts}", alerts) + HTML_FOOTER

# ===================== AUTHENTICATION ROUTES =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Username and password required", "error")
            return redirect(url_for('login'))
        
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT id, username, full_name, role, is_active 
            FROM users 
            WHERE username = ? AND password_hash = ?
        """, (username, hash_password(password)))
        
        user = c.fetchone()
        
        if user and user['is_active']:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            
            c.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
            conn.commit()
            log_activity(user['id'], "LOGIN", f"User {username} logged in")
            
            conn.close()
            flash(f"Welcome back, {user['full_name']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            conn.close()
            flash("Invalid credentials or account disabled", "error")
            return redirect(url_for('login'))
    
    # Build alerts for GET request
    alerts_html = ""
    messages = session.get('_flashes', [])
    for category, message in messages:
        alerts_html += f'<div class="alert alert-{category}" style="margin-bottom: 1rem;">{message}</div>'
    session['_flashes'] = []
    
    return render_login_page(alerts_html)

@app.route("/logout")
def logout():
    if 'user_id' in session:
        log_activity(session['user_id'], "LOGOUT", f"User {session.get('username')} logged out")
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for('login'))

# ===================== DASHBOARD =====================
@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    c = conn.cursor()
    
    # Today's stats
    today = datetime.date.today().isoformat()
    c.execute("SELECT COUNT(*) as count, COALESCE(SUM(total), 0) as total FROM invoices WHERE date = ?", (today,))
    today_stats = c.fetchone()
    
    # Monthly stats
    month_start = datetime.date.today().replace(day=1).isoformat()
    c.execute("SELECT COUNT(*) as count, COALESCE(SUM(total), 0) as total FROM invoices WHERE date >= ?", (month_start,))
    month_stats = c.fetchone()
    
    # Total customers
    c.execute("SELECT COUNT(*) as count FROM customers")
    customers_count = c.fetchone()['count']
    
    # Low stock products
    c.execute("SELECT COUNT(*) as count FROM products WHERE stock <= min_stock")
    low_stock = c.fetchone()['count']
    
    # Recent invoices
    c.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i 
        LEFT JOIN customers c ON i.customer_id = c.id 
        ORDER BY i.created_at DESC LIMIT 5
    """)
    recent_invoices = c.fetchall()
    
    conn.close()
    
    # Build content HTML
    content = f"""
    <div class="stats-grid">
        <div class="stat-card primary">
            <div class="icon"><i class="fas fa-calendar-day"></i></div>
            <div class="stat-value">Rs {today_stats['total']:.0f}</div>
            <div class="stat-label">Today's Sales ({today_stats['count']} invoices)</div>
        </div>
        <div class="stat-card success">
            <div class="icon"><i class="fas fa-chart-line"></i></div>
            <div class="stat-value">Rs {month_stats['total']:.0f}</div>
            <div class="stat-label">This Month ({month_stats['count']} invoices)</div>
        </div>
        <div class="stat-card warning">
            <div class="icon"><i class="fas fa-users"></i></div>
            <div class="stat-value">{customers_count}</div>
            <div class="stat-label">Total Customers</div>
        </div>
        <div class="stat-card danger">
            <div class="icon"><i class="fas fa-exclamation-triangle"></i></div>
            <div class="stat-value">{low_stock}</div>
            <div class="stat-label">Low Stock Items</div>
        </div>
    </div>
    
    <div class="card">
        <div class="card-header">
            <h3><i class="fas fa-clock"></i> Recent Invoices</h3>
            <a href="{url_for('invoices')}" class="btn btn-primary btn-sm">View All</a>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Invoice #</th>
                        <th>Customer</th>
                        <th>Date</th>
                        <th>Amount</th>
                        <th>Status</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for inv in recent_invoices:
        status_class = "success" if inv['status'] == 'paid' else "warning" if inv['status'] == 'partial' else "danger"
        content += f"""
                    <tr>
                        <td><strong>{inv['inv_no']}</strong></td>
                        <td>{inv['customer_name'] or 'Walk-in'}</td>
                        <td>{inv['date']}</td>
                        <td>Rs {inv['total']:.2f}</td>
                        <td><span class="badge badge-{status_class}">{inv['status'].title()}</span></td>
                        <td>
                            <a href="{url_for('view_invoice', id=inv['id'])}" class="btn btn-sm btn-secondary">
                                <i class="fas fa-eye"></i> View
                            </a>
                        </td>
                    </tr>
        """
    
    content += """
                </tbody>
            </table>
        </div>
    </div>
    """
    
    return render_page("Dashboard - Smart Invoice Pro", "Dashboard", content, "dashboard")

# ===================== INVOICE MANAGEMENT =====================
@app.route("/invoice/new", methods=["GET", "POST"])
@login_required
def new_invoice():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        data = request.get_json()
        
        # Create invoice
        inv_no = generate_invoice_number()
        customer_id = data.get('customer_id')
        items = data.get('items', [])
        
        # Calculate totals
        subtotal = sum(item['qty'] * item['price'] for item in items)
        tax_rate = float(get_setting('tax_rate', 0))
        tax_amount = subtotal * (tax_rate / 100)
        discount = float(data.get('discount', 0))
        total = subtotal + tax_amount - discount
        paid = float(data.get('paid', 0))
        balance = total - paid
        
        # Determine status
        if balance <= 0:
            status = 'paid'
        elif paid > 0:
            status = 'partial'
        else:
            status = 'pending'
        
        # Get customer details
        c.execute("SELECT name, address, phone FROM customers WHERE id = ?", (customer_id,))
        customer = c.fetchone()
        
        # Insert invoice
        c.execute("""
            INSERT INTO invoices 
            (inv_no, date, customer_id, customer_name, customer_address, customer_phone,
             salesman_id, salesman_name, subtotal, tax_rate, tax_amount, discount, 
             total, paid, balance, status, payment_method, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (inv_no, data.get('date'), customer_id, 
              customer['name'] if customer else data.get('customer_name'),
              customer['address'] if customer else data.get('address'),
              customer['phone'] if customer else data.get('phone'),
              session['user_id'], session['full_name'],
              subtotal, tax_rate, tax_amount, discount, total, paid, balance,
              status, data.get('payment_method', 'cash'), data.get('notes')))
        
        invoice_id = c.lastrowid
        
        # Insert items and update stock
        for item in items:
            c.execute("""
                INSERT INTO invoice_items 
                (invoice_id, product_id, product_name, qty, unit_price, total)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (invoice_id, item.get('product_id'), item['name'], 
                  item['qty'], item['price'], item['qty'] * item['price']))
            
            # Update stock
            c.execute("UPDATE products SET stock = stock - ? WHERE id = ?", 
                     (item['qty'], item.get('product_id')))
        
        # Update customer balance
        if customer_id:
            c.execute("UPDATE customers SET balance = balance + ? WHERE id = ?", 
                     (balance, customer_id))
            
            # Add to ledger
            c.execute("""
                INSERT INTO transactions 
                (date, customer_id, invoice_id, type, amount, balance, description, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (data.get('date'), customer_id, invoice_id, 'invoice', 
                  total, balance, f"Invoice #{inv_no}", session['user_id']))
        
        conn.commit()
        log_activity(session['user_id'], "CREATE_INVOICE", f"Created invoice {inv_no}")
        
        conn.close()
        return jsonify({"success": True, "invoice_id": invoice_id, "inv_no": inv_no})
    
    # GET request - show form
    c.execute("SELECT id, name, address, phone, balance FROM customers ORDER BY name")
    customers = c.fetchall()
    
    c.execute("SELECT id, name, unit_price, stock FROM products WHERE stock > 0 ORDER BY name")
    products = c.fetchall()
    
    conn.close()
    
    # Build customers options
    customers_options = ""
    for c in customers:
        balance_info = f" (Balance: Rs {c['balance']})" if c['balance'] > 0 else ""
        customers_options += f'<option value="{c["id"]}" data-address="{c["address"] or ""}" data-phone="{c["phone"] or ""}" data-balance="{c["balance"]}">{c["name"]}{balance_info}</option>'
    
    # Build products JSON for JavaScript
    products_json = json.dumps([dict(p) for p in products])
    
    content = f"""
    <div class="card">
        <form id="invoiceForm">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Customer *</label>
                    <select name="customer_id" id="customerSelect" class="form-control" required>
                        <option value="">Select Customer</option>
                        {customers_options}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Date *</label>
                    <input type="date" name="date" class="form-control" value="{datetime.date.today().isoformat()}" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Payment Method</label>
                    <select name="payment_method" class="form-control">
                        <option value="cash">Cash</option>
                        <option value="bank_transfer">Bank Transfer</option>
                        <option value="credit">Credit</option>
                    </select>
                </div>
            </div>
            
            <div class="form-row" id="customerDetails" style="display: none;">
                <div class="form-group">
                    <label class="form-label">Address</label>
                    <input type="text" name="address" id="customerAddress" class="form-control" readonly>
                </div>
                <div class="form-group">
                    <label class="form-label">Phone</label>
                    <input type="text" name="phone" id="customerPhone" class="form-control" readonly>
                </div>
            </div>
            
            <hr style="margin: 2rem 0; border: none; border-top: 1px solid var(--border);">
            
            <h3 style="margin-bottom: 1rem;">Invoice Items</h3>
            
            <div class="table-container">
                <table id="itemsTable">
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th style="width: 120px;">Qty</th>
                            <th style="width: 150px;">Price</th>
                            <th style="width: 150px;">Total</th>
                            <th style="width: 50px;"></th>
                        </tr>
                    </thead>
                    <tbody id="itemsBody">
                    </tbody>
                </table>
            </div>
            
            <button type="button" class="btn btn-secondary" onclick="addItem()">
                <i class="fas fa-plus"></i> Add Item
            </button>
            
            <hr style="margin: 2rem 0; border: none; border-top: 1px solid var(--border);">
            
            <div class="form-row" style="max-width: 400px; margin-left: auto;">
                <div class="form-group" style="display: flex; justify-content: space-between; align-items: center;">
                    <label>Subtotal:</label>
                    <strong id="subtotal">Rs 0.00</strong>
                </div>
                <div class="form-group" style="display: flex; justify-content: space-between; align-items: center;">
                    <label>Tax ({get_setting('tax_rate', 16)}%):</label>
                    <strong id="taxAmount">Rs 0.00</strong>
                </div>
                <div class="form-group">
                    <label class="form-label">Discount</label>
                    <input type="number" name="discount" id="discount" class="form-control" value="0" step="0.01" onchange="calculateTotals()">
                </div>
                <div class="form-group" style="display: flex; justify-content: space-between; align-items: center; font-size: 1.25rem; color: var(--primary);">
                    <label>Total:</label>
                    <strong id="grandTotal">Rs 0.00</strong>
                </div>
                <div class="form-group">
                    <label class="form-label">Paid Amount</label>
                    <input type="number" name="paid" id="paid" class="form-control" value="0" step="0.01" onchange="calculateTotals()">
                </div>
                <div class="form-group" style="display: flex; justify-content: space-between; align-items: center; color: var(--danger);">
                    <label>Balance:</label>
                    <strong id="balance">Rs 0.00</strong>
                </div>
            </div>
            
            <div class="form-group">
                <label class="form-label">Notes</label>
                <textarea name="notes" class="form-control" rows="3"></textarea>
            </div>
            
            <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                <button type="button" class="btn btn-secondary" onclick="window.location.href='{url_for('dashboard')}'">Cancel</button>
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-save"></i> Save Invoice
                </button>
            </div>
        </form>
    </div>
    
    <script>
        let products = {products_json};
        let taxRate = {get_setting('tax_rate', 16)};
        let itemCount = 0;
        
        document.getElementById('customerSelect').addEventListener('change', function() {{
            const option = this.options[this.selectedIndex];
            if (this.value) {{
                document.getElementById('customerDetails').style.display = 'grid';
                document.getElementById('customerAddress').value = option.dataset.address || '';
                document.getElementById('customerPhone').value = option.dataset.phone || '';
            }} else {{
                document.getElementById('customerDetails').style.display = 'none';
            }}
        }});
        
        function addItem() {{
            itemCount++;
            const tbody = document.getElementById('itemsBody');
            const row = document.createElement('tr');
            let optionsHtml = '<option value="">Select Product</option>';
            products.forEach(p => {{
                optionsHtml += `<option value="${{p.id}}" data-price="${{p.unit_price}}" data-stock="${{p.stock}}">${{p.name}} (Stock: ${{p.stock}})</option>`;
            }});
            
            row.innerHTML = `
                <td>
                    <select name="product" class="form-control product-select" required onchange="updatePrice(this)">
                        ${{optionsHtml}}
                    </select>
                </td>
                <td><input type="number" name="qty" class="form-control" value="1" min="1" step="0.01" required onchange="calculateRow(this)"></td>
                <td><input type="number" name="price" class="form-control" value="0" step="0.01" required onchange="calculateRow(this)"></td>
                <td class="row-total">0.00</td>
                <td><button type="button" class="btn btn-danger btn-sm" onclick="removeItem(this)"><i class="fas fa-trash"></i></button></td>
            `;
            tbody.appendChild(row);
        }}
        
        function updatePrice(select) {{
            const option = select.options[select.selectedIndex];
            const row = select.closest('tr');
            const priceInput = row.querySelector('input[name="price"]');
            priceInput.value = option.dataset.price || 0;
            calculateRow(priceInput);
        }}
        
        function calculateRow(input) {{
            const row = input.closest('tr');
            const qty = parseFloat(row.querySelector('input[name="qty"]').value) || 0;
            const price = parseFloat(row.querySelector('input[name="price"]').value) || 0;
            const total = qty * price;
            row.querySelector('.row-total').textContent = total.toFixed(2);
            calculateTotals();
        }}
        
        function calculateTotals() {{
            let subtotal = 0;
            document.querySelectorAll('.row-total').forEach(el => {{
                subtotal += parseFloat(el.textContent) || 0;
            }});
            
            const tax = subtotal * (taxRate / 100);
            const discount = parseFloat(document.getElementById('discount').value) || 0;
            const total = subtotal + tax - discount;
            const paid = parseFloat(document.getElementById('paid').value) || 0;
            const balance = total - paid;
            
            document.getElementById('subtotal').textContent = 'Rs ' + subtotal.toFixed(2);
            document.getElementById('taxAmount').textContent = 'Rs ' + tax.toFixed(2);
            document.getElementById('grandTotal').textContent = 'Rs ' + total.toFixed(2);
            document.getElementById('balance').textContent = 'Rs ' + balance.toFixed(2);
        }}
        
        function removeItem(btn) {{
            btn.closest('tr').remove();
            calculateTotals();
        }}
        
        document.getElementById('invoiceForm').addEventListener('submit', async function(e) {{
            e.preventDefault();
            
            const items = [];
            document.querySelectorAll('#itemsBody tr').forEach(row => {{
                const productSelect = row.querySelector('.product-select');
                items.push({{
                    product_id: productSelect.value,
                    name: productSelect.options[productSelect.selectedIndex].text.split(' (Stock:')[0],
                    qty: parseFloat(row.querySelector('input[name="qty"]').value),
                    price: parseFloat(row.querySelector('input[name="price"]').value)
                }});
            }});
            
            const data = {{
                customer_id: document.querySelector('[name="customer_id"]').value,
                date: document.querySelector('[name="date"]').value,
                payment_method: document.querySelector('[name="payment_method"]').value,
                discount: parseFloat(document.getElementById('discount').value) || 0,
                paid: parseFloat(document.getElementById('paid').value) || 0,
                notes: document.querySelector('[name="notes"]').value,
                items: items
            }};
            
            const response = await fetch('{url_for('new_invoice')}', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }});
            
            const result = await response.json();
            if (result.success) {{
                alert('Invoice created successfully!');
                window.location.href = '{url_for('view_invoice', id=0)}'.replace('0', result.invoice_id);
            }} else {{
                alert('Error creating invoice');
            }}
        }});
        
        // Add first item row by default
        addItem();
    </script>
    """
    
    return render_page("New Invoice - Smart Invoice Pro", "Create New Invoice", content, "new_invoice")

@app.route("/invoices")
@login_required
def invoices():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i 
        LEFT JOIN customers c ON i.customer_id = c.id 
        ORDER BY i.created_at DESC
    """)
    invoices_list = c.fetchall()
    conn.close()
    
    rows = ""
    for inv in invoices_list:
        status_class = "success" if inv['status'] == 'paid' else "warning" if inv['status'] == 'partial' else "danger"
        rows += f"""
        <tr>
            <td><strong>{inv['inv_no']}</strong></td>
            <td>{inv['customer_name'] or 'Walk-in Customer'}</td>
            <td>{inv['date']}</td>
            <td>Rs {inv['total']:.2f}</td>
            <td>Rs {inv['paid']:.2f}</td>
            <td>Rs {inv['balance']:.2f}</td>
            <td><span class="badge badge-{status_class}">{inv['status'].title()}</span></td>
            <td>
                <a href="{url_for('view_invoice', id=inv['id'])}" class="btn btn-sm btn-secondary">
                    <i class="fas fa-eye"></i>
                </a>
                <a href="{url_for('print_invoice', id=inv['id'])}" class="btn btn-sm btn-primary" target="_blank">
                    <i class="fas fa-print"></i>
                </a>
            </td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <div style="display: flex; gap: 1rem;">
                <input type="text" id="searchInput" class="form-control" placeholder="Search invoices..." style="width: 300px;">
            </div>
            <a href="{url_for('new_invoice')}" class="btn btn-primary">
                <i class="fas fa-plus"></i> New Invoice
            </a>
        </div>
        
        <div class="table-container">
            <table id="invoicesTable">
                <thead>
                    <tr>
                        <th>Invoice #</th>
                        <th>Customer</th>
                        <th>Date</th>
                        <th>Total</th>
                        <th>Paid</th>
                        <th>Balance</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        document.getElementById('searchInput').addEventListener('keyup', function() {{
            const value = this.value.toLowerCase();
            document.querySelectorAll('#invoicesTable tbody tr').forEach(row => {{
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(value) ? '' : 'none';
            }});
        }});
    </script>
    """
    
    return render_page("Invoices - Smart Invoice Pro", "All Invoices", content, "invoices")

@app.route("/invoice/<int:id>")
@login_required
def view_invoice(id):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT i.*, c.name as customer_name, c.phone as customer_phone, c.address as customer_address
        FROM invoices i 
        LEFT JOIN customers c ON i.customer_id = c.id 
        WHERE i.id = ?
    """, (id,))
    invoice = c.fetchone()
    
    if not invoice:
        abort(404)
    
    c.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (id,))
    items = c.fetchall()
    
    conn.close()
    
    # Build items rows
    items_rows = ""
    for i, item in enumerate(items, 1):
        items_rows += f"""
        <tr>
            <td>{i}</td>
            <td>{item['product_name']}</td>
            <td style="text-align: right;">{item['qty']}</td>
            <td style="text-align: right;">Rs {item['unit_price']:.2f}</td>
            <td style="text-align: right;">Rs {item['total']:.2f}</td>
        </tr>
        """
    
    discount_row = ""
    if invoice['discount'] > 0:
        discount_row = f"""
        <div style="display: flex; justify-content: space-between; padding: 0.75rem 0; border-bottom: 1px solid var(--border);">
            <span>Discount:</span>
            <strong>-Rs {invoice['discount']:.2f}</strong>
        </div>
        """
    
    content = f"""
    <div class="card" id="invoiceCard">
        <div style="display: flex; justify-content: space-between; margin-bottom: 2rem;">
            <div>
                <h2 style="color: var(--primary); margin-bottom: 0.5rem;">{get_setting('company_name', 'Your Company')}</h2>
                <p style="color: var(--text-muted);">{get_setting('company_address', '')}</p>
                <p style="color: var(--text-muted);">Phone: {get_setting('company_phone', '')}</p>
            </div>
            <div style="text-align: right;">
                <h1 style="font-size: 2rem; margin-bottom: 0.5rem;">INVOICE</h1>
                <p><strong>{invoice['inv_no']}</strong></p>
                <p>Date: {invoice['date']}</p>
            </div>
        </div>
        
        <div style="background: rgba(59, 130, 246, 0.05); padding: 1.5rem; border-radius: 8px; margin-bottom: 2rem;">
            <h4 style="margin-bottom: 1rem;">Bill To:</h4>
            <p><strong>{invoice['customer_name'] or 'Walk-in Customer'}</strong></p>
            <p>{invoice['customer_address'] or ''}</p>
            <p>{invoice['customer_phone'] or ''}</p>
        </div>
        
        <table style="margin-bottom: 2rem;">
            <thead>
                <tr style="background: var(--primary); color: white;">
                    <th>#</th>
                    <th>Description</th>
                    <th style="text-align: right;">Qty</th>
                    <th style="text-align: right;">Unit Price</th>
                    <th style="text-align: right;">Total</th>
                </tr>
            </thead>
            <tbody>
                {items_rows}
            </tbody>
        </table>
        
        <div style="display: flex; justify-content: flex-end;">
            <div style="width: 350px;">
                <div style="display: flex; justify-content: space-between; padding: 0.75rem 0; border-bottom: 1px solid var(--border);">
                    <span>Subtotal:</span>
                    <strong>Rs {invoice['subtotal']:.2f}</strong>
                </div>
                <div style="display: flex; justify-content: space-between; padding: 0.75rem 0; border-bottom: 1px solid var(--border);">
                    <span>Tax ({invoice['tax_rate']}%):</span>
                    <strong>Rs {invoice['tax_amount']:.2f}</strong>
                </div>
                {discount_row}
                <div style="display: flex; justify-content: space-between; padding: 1rem 0; font-size: 1.25rem; border-top: 2px solid var(--primary); margin-top: 0.5rem;">
                    <span><strong>Total:</strong></span>
                    <strong style="color: var(--primary);">Rs {invoice['total']:.2f}</strong>
                </div>
                <div style="display: flex; justify-content: space-between; padding: 0.75rem 0; color: var(--success);">
                    <span>Paid:</span>
                    <strong>Rs {invoice['paid']:.2f}</strong>
                </div>
                {f'<div style="display: flex; justify-content: space-between; padding: 0.75rem 0; color: var(--danger);"><span>Balance Due:</span><strong>Rs {invoice["balance"]:.2f}</strong></div>' if invoice['balance'] > 0 else ''}
            </div>
        </div>
        
        {f'<div style="margin-top: 2rem; padding-top: 2rem; border-top: 1px solid var(--border);"><h4>Notes:</h4><p>{invoice["notes"]}</p></div>' if invoice['notes'] else ''}
        
        <div style="margin-top: 3rem; text-align: center; color: var(--text-muted);">
            <p>Thank you for your business!</p>
        </div>
    </div>
    
    <div class="no-print" style="display: flex; gap: 1rem; justify-content: center; margin-top: 2rem;">
        <button onclick="window.print()" class="btn btn-primary">
            <i class="fas fa-print"></i> Print Invoice
        </button>
        <a href="{url_for('invoices')}" class="btn btn-secondary">Back to List</a>
    </div>
    """
    
    return render_page(f"Invoice {invoice['inv_no']} - Smart Invoice Pro", "Invoice Details", content, "invoices")

# ===================== CUSTOMER LEDGER =====================
@app.route("/ledger")
@login_required
def ledger():
    conn = get_db()
    c = conn.cursor()
    
    customer_id = request.args.get('customer_id', type=int)
    
    c.execute("SELECT id, name, phone, balance FROM customers ORDER BY name")
    customers = c.fetchall()
    
    transactions = []
    selected_customer = None
    
    if customer_id:
        c.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
        selected_customer = c.fetchone()
        
        c.execute("""
            SELECT t.*, i.inv_no, u.full_name as created_by_name
            FROM transactions t
            LEFT JOIN invoices i ON t.invoice_id = i.id
            LEFT JOIN users u ON t.created_by = u.id
            WHERE t.customer_id = ?
            ORDER BY t.date DESC, t.id DESC
        """, (customer_id,))
        transactions = c.fetchall()
    
    conn.close()
    
    # Build customer options
    customer_options = '<option value="">-- Select Customer --</option>'
    for c in customers:
        selected = 'selected' if selected_customer and selected_customer['id'] == c['id'] else ''
        customer_options += f'<option value="{c["id"]}" {selected}>{c["name"]} - {c["phone"] or "No phone"} (Balance: Rs {c["balance"]})</option>'
    
    transactions_rows = ""
    for t in transactions:
        type_class = "danger" if t['type'] == 'invoice' else "success" if t['type'] == 'payment' else "info"
        ref = f'<br><small>Ref: {t["inv_no"]}</small>' if t['inv_no'] else ''
        transactions_rows += f"""
        <tr>
            <td>{t['date']}</td>
            <td>{t['description']}{ref}</td>
            <td><span class="badge badge-{type_class}">{t['type'].title()}</span></td>
            <td>Rs {t['amount']:.2f}</td>
            <td>Rs {t['balance']:.2f}</td>
            <td>{t['created_by_name'] or 'System'}</td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Select Customer</h3>
        </div>
        <form method="get" class="form-row">
            <div class="form-group" style="flex: 1;">
                <select name="customer_id" class="form-control" onchange="this.form.submit()">
                    {customer_options}
                </select>
            </div>
            <a href="{url_for('customers')}" class="btn btn-primary">Add New Customer</a>
        </form>
    </div>
    """
    
    if selected_customer:
        balance_color = "var(--danger)" if selected_customer['balance'] > 0 else "var(--success)"
        content += f"""
    <div class="card">
        <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h3>{selected_customer['name']}</h3>
                <p style="color: var(--text-muted); margin: 0;">{selected_customer['address'] or ''}</p>
                <p style="color: var(--text-muted); margin: 0;">{selected_customer['phone'] or ''}</p>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 0.875rem; color: var(--text-muted);">Current Balance</div>
                <div style="font-size: 2rem; font-weight: 700; color: {balance_color};">
                    Rs {selected_customer['balance']:.2f}
                </div>
            </div>
        </div>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Description</th>
                        <th>Type</th>
                        <th>Amount</th>
                        <th>Balance</th>
                        <th>By</th>
                    </tr>
                </thead>
                <tbody>
                    {transactions_rows}
                </tbody>
            </table>
        </div>
    </div>
        """
    
    return render_page("Customer Ledger - Smart Invoice Pro", "Customer Ledger", content, "ledger")

# ===================== USER MANAGEMENT (ADMIN ONLY) =====================
@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def users():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            username = request.form.get("username").strip()
            full_name = request.form.get("full_name").strip()
            password = request.form.get("password")
            role = request.form.get("role")
            phone = request.form.get("phone", "")
            
            try:
                c.execute("""
                    INSERT INTO users (username, password_hash, full_name, role, phone)
                    VALUES (?, ?, ?, ?, ?)
                """, (username, hash_password(password), full_name, role, phone))
                conn.commit()
                flash(f"User {username} created successfully", "success")
                log_activity(session['user_id'], "CREATE_USER", f"Created user {username}")
            except sqlite3.IntegrityError:
                flash("Username already exists", "error")
        
        elif action == "toggle":
            user_id = request.form.get("user_id")
            c.execute("UPDATE users SET is_active = NOT is_active WHERE id = ?", (user_id,))
            conn.commit()
            flash("User status updated", "success")
    
    c.execute("SELECT * FROM users ORDER BY created_at DESC")
    users_list = c.fetchall()
    conn.close()
    
    users_rows = ""
    for user in users_list:
        status_badge = "success" if user['is_active'] else "danger"
        status_text = "Active" if user['is_active'] else "Inactive"
        btn_class = "danger" if user['is_active'] else "success"
        btn_text = "Deactivate" if user['is_active'] else "Activate"
        
        users_rows += f"""
        <tr>
            <td>{user['username']}</td>
            <td>{user['full_name']}</td>
            <td><span class="badge badge-info">{user['role'].title()}</span></td>
            <td>{user['phone'] or '-'}</td>
            <td><span class="badge badge-{status_badge}">{status_text}</span></td>
            <td>{user['last_login'] or 'Never'}</td>
            <td>
                <form method="post" style="display: inline;">
                    <input type="hidden" name="action" value="toggle">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <button type="submit" class="btn btn-sm btn-{btn_class}">{btn_text}</button>
                </form>
            </td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Add New User</h3>
        </div>
        <form method="post">
            <input type="hidden" name="action" value="add">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Username *</label>
                    <input type="text" name="username" class="form-control" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Full Name *</label>
                    <input type="text" name="full_name" class="form-control" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Password *</label>
                    <input type="password" name="password" class="form-control" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Role *</label>
                    <select name="role" class="form-control" required>
                        <option value="salesman">Salesman</option>
                        <option value="manager">Manager</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Phone</label>
                    <input type="text" name="phone" class="form-control">
                </div>
            </div>
            <button type="submit" class="btn btn-primary">Add User</button>
        </form>
    </div>
    
    <div class="card">
        <div class="card-header">
            <h3>All Users</h3>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Username</th>
                        <th>Full Name</th>
                        <th>Role</th>
                        <th>Phone</th>
                        <th>Status</th>
                        <th>Last Login</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {users_rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    
    return render_page("User Management - Smart Invoice Pro", "User Management", content, "users")

# ===================== BACKUP & RESTORE =====================
@app.route("/admin/backup", methods=["GET", "POST"])
@admin_required
def backup():
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "backup":
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = BACKUP_DIR / f"backup_{timestamp}.db"
            shutil.copy2(DB_FILE, backup_file)
            flash(f"Backup created: {backup_file.name}", "success")
            log_activity(session['user_id'], "BACKUP", f"Created backup {backup_file.name}")
        
        elif action == "restore":
            file = request.files.get("backup_file")
            if file:
                temp_path = BACKUP_DIR / "temp_restore.db"
                file.save(temp_path)
                
                try:
                    conn = sqlite3.connect(temp_path)
                    conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    conn.close()
                    
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    current_backup = BACKUP_DIR / f"before_restore_{timestamp}.db"
                    shutil.copy2(DB_FILE, current_backup)
                    
                    shutil.copy2(temp_path, DB_FILE)
                    temp_path.unlink()
                    
                    flash("Database restored successfully", "success")
                    log_activity(session['user_id'], "RESTORE", "Database restored from backup")
                except Exception as e:
                    flash(f"Invalid backup file: {str(e)}", "error")
    
    backups = sorted(BACKUP_DIR.glob("*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    backup_rows = ""
    for backup in backups:
        size_kb = backup.stat().st_size / 1024
        mtime = datetime.datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        backup_rows += f"""
        <tr>
            <td>{backup.name}</td>
            <td>{mtime}</td>
            <td>{size_kb:.2f} KB</td>
            <td>
                <a href="{url_for('download_backup', filename=backup.name)}" class="btn btn-sm btn-primary">
                    <i class="fas fa-download"></i> Download
                </a>
            </td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Create Backup</h3>
        </div>
        <p style="margin-bottom: 1rem;">Create a backup of your entire database. Backups are stored in the backups folder.</p>
        <form method="post">
            <input type="hidden" name="action" value="backup">
            <button type="submit" class="btn btn-primary">
                <i class="fas fa-download"></i> Create Backup Now
            </button>
        </form>
    </div>
    
    <div class="card">
        <div class="card-header">
            <h3>Restore from Backup</h3>
        </div>
        <p style="color: var(--danger); margin-bottom: 1rem;">
            <i class="fas fa-exclamation-triangle"></i> 
            Warning: Restoring will replace all current data. A backup of current data will be created automatically.
        </p>
        <form method="post" enctype="multipart/form-data">
            <input type="hidden" name="action" value="restore">
            <div class="form-group">
                <label class="form-label">Select Backup File</label>
                <input type="file" name="backup_file" class="form-control" accept=".db" required>
            </div>
            <button type="submit" class="btn btn-danger" onclick="return confirm('Are you sure? This will replace all current data.')">
                <i class="fas fa-upload"></i> Restore Backup
            </button>
        </form>
    </div>
    
    <div class="card">
        <div class="card-header">
            <h3>Available Backups</h3>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Filename</th>
                        <th>Date</th>
                        <th>Size</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {backup_rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    
    return render_page("Backup & Restore - Smart Invoice Pro", "Backup & Restore", content, "backup")

@app.route("/admin/backup/download/<filename>")
@admin_required
def download_backup(filename):
    return send_file(BACKUP_DIR / filename, as_attachment=True)

# ===================== ADDITIONAL ROUTES =====================
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        name = request.form.get("name").strip()
        address = request.form.get("address", "")
        phone = request.form.get("phone", "")
        email = request.form.get("email", "")
        
        try:
            c.execute("""
                INSERT INTO customers (name, address, phone, email)
                VALUES (?, ?, ?, ?)
            """, (name, address, phone, email))
            conn.commit()
            flash("Customer added successfully", "success")
        except sqlite3.IntegrityError:
            flash("Customer already exists", "error")
    
    c.execute("SELECT * FROM customers ORDER BY name")
    customers_list = c.fetchall()
    conn.close()
    
    rows = ""
    for c in customers_list:
        balance_color = "var(--danger)" if c['balance'] > 0 else "var(--success)"
        rows += f"""
        <tr>
            <td>{c['name']}</td>
            <td>{c['phone'] or '-'}</td>
            <td>{c['email'] or '-'}</td>
            <td style="color: {balance_color};">Rs {c['balance']:.2f}</td>
            <td>
                <a href="{url_for('ledger', customer_id=c['id'])}" class="btn btn-sm btn-secondary">Ledger</a>
            </td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Add New Customer</h3>
        </div>
        <form method="post" class="form-row">
            <div class="form-group">
                <label class="form-label">Name *</label>
                <input type="text" name="name" class="form-control" required>
            </div>
            <div class="form-group">
                <label class="form-label">Phone</label>
                <input type="text" name="phone" class="form-control">
            </div>
            <div class="form-group">
                <label class="form-label">Email</label>
                <input type="email" name="email" class="form-control">
            </div>
            <div class="form-group" style="grid-column: 1 / -1;">
                <label class="form-label">Address</label>
                <input type="text" name="address" class="form-control">
            </div>
            <div class="form-group">
                <button type="submit" class="btn btn-primary">Add Customer</button>
            </div>
        </form>
    </div>
    
    <div class="card">
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Phone</th>
                        <th>Email</th>
                        <th>Balance</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    
    return render_page("Customers - Smart Invoice Pro", "Customers", content, "customers")

@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        name = request.form.get("name").strip()
        description = request.form.get("description", "")
        unit_price = float(request.form.get("unit_price", 0))
        purchase_price = float(request.form.get("purchase_price", 0))
        stock = float(request.form.get("stock", 0))
        min_stock = float(request.form.get("min_stock", 0))
        unit = request.form.get("unit", "pcs")
        
        try:
            c.execute("""
                INSERT INTO products (name, description, unit_price, purchase_price, stock, min_stock, unit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, description, unit_price, purchase_price, stock, min_stock, unit))
            conn.commit()
            flash("Product added successfully", "success")
        except sqlite3.IntegrityError:
            c.execute("""
                UPDATE products SET 
                description = ?, unit_price = ?, purchase_price = ?, 
                stock = stock + ?, min_stock = ?, unit = ?
                WHERE name = ?
            """, (description, unit_price, purchase_price, stock, min_stock, unit, name))
            conn.commit()
            flash("Product updated successfully", "success")
    
    c.execute("SELECT * FROM products ORDER BY name")
    products_list = c.fetchall()
    conn.close()
    
    rows = ""
    for p in products_list:
        status_badge = "danger" if p['stock'] <= p['min_stock'] else "success"
        status_text = "Low Stock" if p['stock'] <= p['min_stock'] else "In Stock"
        
        rows += f"""
        <tr>
            <td>
                <strong>{p['name']}</strong>
                {f'<br><small>{p["description"]}</small>' if p['description'] else ''}
            </td>
            <td>Rs {p['unit_price']:.2f}</td>
            <td>{p['stock']} {p['unit']}</td>
            <td><span class="badge badge-{status_badge}">{status_text}</span></td>
        </tr>
        """
    
    content = f"""
    <div class="card">
        <div class="card-header">
            <h3>Add/Update Product</h3>
        </div>
        <form method="post" class="form-row">
            <div class="form-group">
                <label class="form-label">Name *</label>
                <input type="text" name="name" class="form-control" required>
            </div>
            <div class="form-group">
                <label class="form-label">Selling Price *</label>
                <input type="number" name="unit_price" class="form-control" step="0.01" required>
            </div>
            <div class="form-group">
                <label class="form-label">Cost Price</label>
                <input type="number" name="purchase_price" class="form-control" step="0.01">
            </div>
            <div class="form-group">
                <label class="form-label">Add Stock</label>
                <input type="number" name="stock" class="form-control" step="0.01" value="0">
            </div>
            <div class="form-group">
                <label class="form-label">Min Stock Alert</label>
                <input type="number" name="min_stock" class="form-control" step="0.01" value="10">
            </div>
            <div class="form-group">
                <label class="form-label">Unit</label>
                <input type="text" name="unit" class="form-control" value="pcs">
            </div>
            <div class="form-group" style="grid-column: 1 / -1;">
                <label class="form-label">Description</label>
                <input type="text" name="description" class="form-control">
            </div>
            <div class="form-group">
                <button type="submit" class="btn btn-primary">Save Product</button>
            </div>
        </form>
    </div>
    
    <div class="card">
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Price</th>
                        <th>Stock</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    
    return render_page("Products - Smart Invoice Pro", "Products", content, "products")

@app.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == "POST":
        for key in request.form:
            if key != "action":
                c.execute("""
                    INSERT OR REPLACE INTO settings (key, value, updated_by, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (key, request.form.get(key), session['user_id'], datetime.datetime.now().isoformat()))
        conn.commit()
        flash("Settings updated successfully", "success")
        log_activity(session['user_id'], "UPDATE_SETTINGS", "Updated system settings")
    
    c.execute("SELECT * FROM settings")
    settings_dict = {row['key']: row['value'] for row in c.fetchall()}
    conn.close()
    
    content = f"""
    <form method="post">
        <div class="card">
            <div class="card-header">
                <h3>Company Information</h3>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Company Name</label>
                    <input type="text" name="company_name" class="form-control" value="{settings_dict.get('company_name', '')}">
                </div>
                <div class="form-group">
                    <label class="form-label">Phone</label>
                    <input type="text" name="company_phone" class="form-control" value="{settings_dict.get('company_phone', '')}">
                </div>
                <div class="form-group" style="grid-column: 1 / -1;">
                    <label class="form-label">Address</label>
                    <input type="text" name="company_address" class="form-control" value="{settings_dict.get('company_address', '')}">
                </div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h3>Invoice Settings</h3>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Default Tax Rate (%)</label>
                    <input type="number" name="tax_rate" class="form-control" value="{settings_dict.get('tax_rate', '16')}">
                </div>
                <div class="form-group">
                    <label class="form-label">Invoice Prefix</label>
                    <input type="text" name="invoice_prefix" class="form-control" value="{settings_dict.get('invoice_prefix', 'INV-')}">
                </div>
                <div class="form-group">
                    <label class="form-label">Currency</label>
                    <input type="text" name="currency" class="form-control" value="{settings_dict.get('currency', 'PKR')}">
                </div>
            </div>
        </div>
        
        <div style="display: flex; justify-content: flex-end;">
            <button type="submit" class="btn btn-primary">Save Settings</button>
        </div>
    </form>
    """
    
    return render_page("Settings - Smart Invoice Pro", "System Settings", content, "settings")

# ===================== PDF GENERATION =====================
@app.route("/invoice/<int:id>/print")
@login_required
def print_invoice(id):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT i.*, c.name as customer_name, c.phone as customer_phone, c.address as customer_address
        FROM invoices i 
        LEFT JOIN customers c ON i.customer_id = c.id 
        WHERE i.id = ?
    """, (id,))
    invoice = c.fetchone()
    
    c.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (id,))
    items = c.fetchall()
    
    conn.close()
    
    if not invoice:
        abort(404)
    
    filename = f"invoice_{invoice['inv_no']}.pdf"
    filepath = EXPORT_DIR / filename
    
    c = canvas.Canvas(str(filepath), pagesize=A4)
    width, height = A4
    
    # Header
    c.setFont("Helvetica-Bold", 24)
    c.drawString(20*mm, height-30*mm, get_setting('company_name', 'Your Company'))
    
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, height-40*mm, get_setting('company_address', ''))
    c.drawString(20*mm, height-45*mm, f"Phone: {get_setting('company_phone', '')}")
    
    # Invoice Details
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(width-20*mm, height-30*mm, "INVOICE")
    c.setFont("Helvetica", 10)
    c.drawRightString(width-20*mm, height-40*mm, f"#{invoice['inv_no']}")
    c.drawRightString(width-20*mm, height-45*mm, f"Date: {invoice['date']}")
    
    # Customer
    y = height-70*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20*mm, y, "Bill To:")
    c.setFont("Helvetica", 10)
    y -= 6*mm
    c.drawString(20*mm, y, invoice['customer_name'] or 'Walk-in Customer')
    y -= 5*mm
    if invoice['customer_address']:
        c.drawString(20*mm, y, invoice['customer_address'])
        y -= 5*mm
    if invoice['customer_phone']:
        c.drawString(20*mm, y, f"Phone: {invoice['customer_phone']}")
    
    # Items Table
    y = height-110*mm
    c.setFillColorRGB(0.23, 0.51, 0.96)
    c.rect(20*mm, y-5*mm, width-40*mm, 10*mm, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25*mm, y, "Item")
    c.drawRightString(width-80*mm, y, "Qty")
    c.drawRightString(width-50*mm, y, "Price")
    c.drawRightString(width-25*mm, y, "Total")
    
    c.setFillColorRGB(0, 0, 0)
    y -= 10*mm
    
    for item in items:
        c.setFont("Helvetica", 10)
        c.drawString(25*mm, y, item['product_name'][:40])
        c.drawRightString(width-80*mm, y, str(item['qty']))
        c.drawRightString(width-50*mm, y, f"{item['unit_price']:.2f}")
        c.drawRightString(width-25*mm, y, f"{item['total']:.2f}")
        y -= 6*mm
    
    # Totals
    y -= 10*mm
    c.line(20*mm, y+5*mm, width-20*mm, y+5*mm)
    
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(width-50*mm, y, "Subtotal:")
    c.drawRightString(width-25*mm, y, f"{invoice['subtotal']:.2f}")
    y -= 6*mm
    
    c.drawRightString(width-50*mm, y, f"Tax ({invoice['tax_rate']}%):")
    c.drawRightString(width-25*mm, y, f"{invoice['tax_amount']:.2f}")
    y -= 6*mm
    
    if invoice['discount'] > 0:
        c.drawRightString(width-50*mm, y, "Discount:")
        c.drawRightString(width-25*mm, y, f"{invoice['discount']:.2f}")
        y -= 6*mm
    
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width-50*mm, y, "Total:")
    c.drawRightString(width-25*mm, y, f"{invoice['total']:.2f}")
    
    c.save()
    
    return send_file(filepath, as_attachment=True)

# ===================== MAIN ENTRY =====================
if __name__ == "__main__":
    import webbrowser
    webbrowser.open("http://127.0.0.1:5000")
    app.run(debug=True, port=5000, host="0.0.0.0")