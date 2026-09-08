# app.py — Smart Invoice (stable header)

# ===================== IMPORTS =====================
from pathlib import Path
import sys
import os
import re
import csv, datetime, json, io
from typing import Optional
import sqlite3
import uuid
import smtplib
import ssl
import secrets
import hashlib
from email.mime.text import MIMEText

from flask import (
    Flask, request, redirect, url_for,
    send_from_directory, render_template_string,
    flash, jsonify, session, Response,
    send_file, get_flashed_messages, render_template
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

import threading
import time
_inv_no_lock = threading.Lock()  # Invoice number race condition rokne ke liye
import tkinter as tk
from tkinter import font
from PIL import Image, ImageTk
############## ═══════════════════════════════════════════════════════
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Register Bahnschrift Bold ──
font_path = r"C:\Windows\Fonts\bahnschrift.ttf"

try:
    pdfmetrics.registerFont(
        TTFont("BahnschriftBold", font_path)
    )
except:
    pass
#####

# ===================== EXE / ROOT =====================
if getattr(sys, 'frozen', False):  # PyInstaller EXE
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path.cwd()

# ===================== FULL SQLITE + SE FOLDER (High Risk Solved) ====================
BASE_DATA = Path(os.environ.get("DATA_PATH", str(ROOT / "db_files_seize")))
DATA_DIR = BASE_DATA / "data_files"
UPLOADS_DIR = BASE_DATA / "Data"
RECORDS_DIR = BASE_DATA / "SEIZE"
DB_DIR = BASE_DATA / "seize_db"

for p in (DATA_DIR, UPLOADS_DIR, RECORDS_DIR, DB_DIR):
    p.mkdir(parents=True, exist_ok=True)

# Keep old database
DB_FILE = DB_DIR / "seize_cleaning.db"

print(f"Using existing database: {DB_FILE}")
# ===================== SALES LOG SQLite HELPERS =====================
def read_sales_csv():
    """Sales log SQLite se read karta hai (CSV ki jagah)"""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT date, inv_no, product, qty, sell_price FROM sales_log ORDER BY id")
        rows = [
            {"date": r[0], "inv_no": r[1], "product": r[2], "qty": r[3], "sell_price": r[4]}
            for r in cur.fetchall()
        ]
        con.close()
        return rows
    except Exception as e:
        print("❌ read_sales_csv error:", e)
        return []


def write_sales_csv(rows):
    """Sales log SQLite mein write karta hai — poori table replace hoti hai"""
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("DELETE FROM sales_log")
        for r in rows:
            cur.execute(
                "INSERT INTO sales_log (date, inv_no, product, qty, sell_price) VALUES (?,?,?,?,?)",
                (r.get("date",""), r.get("inv_no",""), r.get("product",""), r.get("qty",0), r.get("sell_price",0))
            )
        con.commit()
        con.close()
    except Exception as e:
        print("❌ write_sales_csv error:", e)


# ===================== SQLITE INIT =====================
def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        # === Invoices Master (Improved) ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            inv_no TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            customer TEXT,
            customer_address TEXT,
            customer_phone TEXT,
            salesman TEXT,
            tax REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            subtotal REAL DEFAULT 0,
            grand_total REAL DEFAULT 0,
            pending_added REAL DEFAULT 0,
            total REAL DEFAULT 0,
            customer_type TEXT DEFAULT 'customer',
            remarks TEXT,
            logo_path TEXT,
            status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # === Invoice Items ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no TEXT,
            product TEXT,
            qty REAL,
            unit_price REAL,
            FOREIGN KEY(inv_no) REFERENCES invoices(inv_no) ON DELETE CASCADE
        )
        """)

        # === Orders (Pending, confirm karne se pehle) ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_no INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            delivery_date TEXT,
            customer TEXT,
            customer_address TEXT,
            customer_phone TEXT,
            salesman TEXT,
            tax REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            subtotal REAL DEFAULT 0,
            grand_total REAL DEFAULT 0,
            customer_type TEXT DEFAULT 'customer',
            status TEXT DEFAULT 'pending',
            remarks TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no INTEGER,
            product TEXT,
            qty REAL,
            unit_price REAL,
            FOREIGN KEY(order_no) REFERENCES orders(order_no) ON DELETE CASCADE
        )
        """)

        # === Products (Carton + Piece Support) ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            name TEXT PRIMARY KEY,
            unit_price REAL DEFAULT 0,           -- Carton Price (Default)
            purchase_price REAL DEFAULT 0,
            wholesaler_price REAL DEFAULT 0,
            distributor_price REAL DEFAULT 0,
            customer_price REAL DEFAULT 0,
            pieces_per_carton INTEGER DEFAULT 12,
            price_per_piece REAL DEFAULT 0,
            stock REAL DEFAULT 0,                -- Stock in Cartons
            min_stock REAL DEFAULT 0
        )
        """)
        # === Salesmen + HR Tables ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS salesmen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            salary REAL DEFAULT 0,
            commission_pct REAL DEFAULT 0,
            salesman_type TEXT DEFAULT 'salesman',
            status TEXT DEFAULT 'Active',
            joining_date TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS salesman_hr (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            salesman TEXT,
            date TEXT,
            type TEXT,
            amount REAL DEFAULT 0,
            note TEXT
        )
        """)
        # === Customers ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            phone TEXT,
            joined_date TEXT,
            UNIQUE(name, address)
        )
        """)

        # === Sales Log ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS sales_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            inv_no TEXT,
            product TEXT,
            qty REAL,
            sell_price REAL
        )
        """)

        # === Other Tables (Existing + New) ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            amount REAL,
            description TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS other_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            name TEXT,
            amount REAL,
            description TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT,
            product TEXT,
            qty REAL DEFAULT 0,
            UNIQUE(month, product)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS customer_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            customer_address TEXT,
            pending_amount REAL DEFAULT 0,
            UNIQUE(customer_name, customer_address)
        )
        """)
        # ===================== DELETED / RECYCLE BIN TABLES =====================
        
        # Main Deleted Invoices (Recommended - Simple)
        c.execute("""
        CREATE TABLE IF NOT EXISTS deleted_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no TEXT UNIQUE,
            date TEXT,
            customer TEXT,
            customer_address TEXT,
            customer_phone TEXT,
            salesman TEXT,
            tax REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            subtotal REAL DEFAULT 0,
            grand_total REAL DEFAULT 0,
            pending_added REAL DEFAULT 0,
            total REAL DEFAULT 0,
            customer_type TEXT,
            remarks TEXT,
            logo_path TEXT,
            deleted_on TEXT DEFAULT CURRENT_TIMESTAMP,
            deleted_lines TEXT   -- JSON of items
        )
        """)

        # Optional: Normalized Deleted Items (future use ke liye rakh sakte ho)
        c.execute("""
        CREATE TABLE IF NOT EXISTS deleted_invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no TEXT,
            product TEXT,
            qty REAL,
            unit_price REAL,
            deleted_on TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("""
                CREATE TABLE IF NOT EXISTS stock_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    product TEXT,
                    qty REAL DEFAULT 0,
                    purchase_price REAL DEFAULT 0,
                    wholesaler_price REAL,
                    distributor_price REAL,
                    customer_price REAL,
                    month_key TEXT
         )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS salesman_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            salesman TEXT,
            month TEXT,
            product_name TEXT,
            target_qty REAL DEFAULT 0,
            achieved_qty REAL DEFAULT 0,
            target_amount REAL DEFAULT 0,
            achieved_amount REAL DEFAULT 0
        )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inv_no TEXT,
                date TEXT,
                amount REAL,
                method TEXT,
                customer TEXT,
                address TEXT,
                note TEXT,
                batch_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS monthly_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month TEXT,
                product TEXT,
                qty REAL DEFAULT 0,
                UNIQUE(month, product)
            )
        """)
        conn.commit()
        conn.close()
        print("✅ Full SQLite tables ready (Updated Structure)")
    except Exception as e:
        print("❌ DB Error:", e)

def migrate_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # ---------- invoices ----------
    cur.execute("PRAGMA table_info(invoices)")
    cols = [c[1] for c in cur.fetchall()]

    invoice_columns = {
        "customer_phone": "TEXT",
        "salesman": "TEXT",
        "tax": "REAL DEFAULT 0",
        "discount": "REAL DEFAULT 0",
        "subtotal": "REAL DEFAULT 0",
        "grand_total": "REAL DEFAULT 0",
        "pending_added": "REAL DEFAULT 0",
        "total": "REAL DEFAULT 0",
        "customer_type": "TEXT DEFAULT 'customer'",
        "remarks": "TEXT",
        "logo_path": "TEXT",
        "status": "TEXT DEFAULT 'Active'",
        "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP"
    }

    for col, dtype in invoice_columns.items():
        if col not in cols:
            cur.execute(f"ALTER TABLE invoices ADD COLUMN {col} {dtype}")

    # ---------- payments ----------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inv_no TEXT,
        date TEXT,
        amount REAL DEFAULT 0,
        method TEXT,
        customer TEXT,
        address TEXT,
        note TEXT,
        batch_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("PRAGMA table_info(payments)")
    pay_cols = [c[1] for c in cur.fetchall()]
    if "batch_id" not in pay_cols:
        # ── Adds batch_id so every "Add Payment" action can be traced back
        # to ONE original transaction, even after record_payment_fifo()
        # splits it across several invoices. This lets the Customer Ledger
        # reliably show the TOTAL amount that was actually entered, instead
        # of the per-invoice split fragment. ──
        cur.execute("ALTER TABLE payments ADD COLUMN batch_id TEXT")

    # ---------- auth: password reset OTP (new, isolated table) ----------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_otp(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT,
        otp_hash TEXT,
        expires_at TEXT,
        attempts INTEGER DEFAULT 0,
        last_sent_at TEXT,
        verified INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()
# ===================== INIT DB (ON START) =====================
init_db()
migrate_db()
def db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

import contextlib

@contextlib.contextmanager
def db_transaction():
    """
    Rollback-safe SQLite transaction helper.
    Usage:
        with db_transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT ...")
            cur.execute("UPDATE ...")
    Agar block ke andar koi bhi exception aaye, sab changes automatically
    rollback ho jayenge (koi partial/corrupt data save nahi hoga).
    Agar sab theek raha, changes automatically commit ho jate hain.
    """
    conn = db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ===================== FLASK APP =====================
app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("APP_SECRET", "smart-invoice-change-this")


# ========== EMAIL + PASSWORD AUTHENTICATION ==========
# Shared visual tokens for the standalone (pre-login) auth pages — mirrors the
# app's main design system (:root vars + 3D pressed .btn from TPL_H) so these
# screens look consistent with the rest of the app.
AUTH_STYLE = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,Arial,sans-serif;background:linear-gradient(135deg,#0d3b34,#0f5c52 55%,#1a4a2e);
  display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;padding:20px}
.auth-box{background:#ffffff;padding:40px;border-radius:20px;box-shadow:0 20px 50px rgba(0,0,0,.35);width:400px;text-align:center}
.auth-box h2{color:#0d3b34;margin-bottom:8px;font-size:26px;font-weight:800}
.auth-box p.sub{color:#5f7a75;margin-bottom:22px;font-size:13.5px}
.auth-box input{width:100%;padding:14px 16px;margin:8px 0;border:1.5px solid #dde8e5;border-radius:12px;font-size:15px;box-sizing:border-box;background:#f7faf9;transition:border-color .15s}
.auth-box input:focus{outline:none;border-color:#0d9488}
.auth-btn{width:100%;padding:15px;margin-top:14px;border:none;border-radius:12px;font-size:16px;font-weight:800;color:white;cursor:pointer;
  background:linear-gradient(135deg,#0d3b34,#0f5c52);
  box-shadow:0 4px 0 rgba(0,0,0,.28),0 6px 10px rgba(0,0,0,.16);
  transition:transform .1s ease,box-shadow .1s ease,filter .15s ease;position:relative;top:0}
.auth-btn:hover{filter:brightness(1.1)}
.auth-btn:active{transform:translateY(4px);box-shadow:0 0 0 rgba(0,0,0,.28),0 1px 2px rgba(0,0,0,.12);filter:brightness(.92)}
.auth-link{margin-top:20px;font-size:14px}
.auth-link a{color:#0d9488;text-decoration:none;font-weight:700}
.auth-link a:hover{text-decoration:underline}
.masked-email{display:inline-block;background:#ecfdf5;color:#065f46;font-weight:700;padding:4px 12px;border-radius:20px;font-size:13px;margin:10px 0}
.notice{background:#fee2e2;color:#c62828;padding:11px 14px;border-radius:10px;margin:14px 0;font-size:13.5px}
.notice.ok{background:#ecfdf5;color:#065f46}
.otp-inputs{display:flex;gap:8px;justify-content:center;margin:16px 0}
.otp-inputs input{width:46px;height:56px;text-align:center;font-size:22px;font-weight:800;padding:0;margin:0}
.cooldown{font-size:12.5px;color:#94a3b8;margin-top:10px}
"""

def _session_version_ok():
    return session.get("session_version") == get_setting("session_version", "1")


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("logged_in") and _session_version_ok():
            return f(*args, **kwargs)
        session.pop("logged_in", None)
        flash("Login")
        return redirect(url_for("login"))
    return decorated_function

@app.route("/login", methods=["GET", "POST"])
def login():
    admin_email = get_setting("admin_email", "")
    admin_password_hash = get_setting("admin_password_hash", "")

    # First run: no account set up yet -> redirect to setup
    if not admin_email or not admin_password_hash:
        return redirect(url_for("setup_account"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        master_password = get_setting("master_password", "MASTER2025")

        if password == master_password:
            session["logged_in"] = True
            session["session_version"] = get_setting("session_version", "1")
            flash("Logged in with Master Password")
            return redirect(url_for("home"))
        elif email == admin_email.lower() and check_password_hash(admin_password_hash, password):
            session["logged_in"] = True
            session["session_version"] = get_setting("session_version", "1")
            flash("Login successful")
            return redirect(url_for("home"))
        else:
            flash("Invalid email or password")
    html = """
    <!doctype html>
    <html lang="en">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Login</title>
    <style>""" + AUTH_STYLE + """</style>
    </head>
    <body>
        <div class="auth-box">
            <h2>🔐 Smart Invoice Pro</h2>
            <p class="sub">Sign in to continue</p>
            {% with messages = get_flashed_messages() %}
              {% if messages %}<div class="notice">{{ messages[0] }}</div>{% endif %}
            {% endwith %}
            <form method="post">
                <input type="email" name="email" placeholder="Email" required autofocus>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="auth-btn">Log In</button>
            </form>
            <div class="auth-link">
              <a href="{{ url_for('forgot_password') }}">Forgot Password?</a>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)
    html = """
    <!doctype html>
    <html lang="ur" dir="rtl">
    <head><meta charset="utf-8"><title>Login password</title>
    <style>
        body {background: linear-gradient(135deg, #1e3a8a, #3b82f6); display:flex; justify-content:center; align-items:center; height:100vh; margin:0; font-family: system-ui, Arial;}
        .login-box {background: white; padding: 40px; border-radius: 20px; box-shadow: 0 15px 40px rgba(0,0,0,0.3); width: 380px; text-align: center;}
        h2 {color: #1e3a8a; margin-bottom: 30px; font-size: 28px;}
        input {width: 100%; padding: 16px; margin: 12px 0; border: 1px solid #ddd; border-radius: 12px; font-size: 18px;}
        button {width: 100%; padding: 16px; background: #1e3a8a; color: white; border: none; border-radius: 12px; font-size: 20px; cursor: pointer;}
        button:hover {background: #1e40af;}
        .info {margin-top: 25px; color: #666; font-size: 14px;}
        .notice {background: #fee; color: #c62828; padding: 10px; border-radius: 8px; margin: 15px 0;}
    </style>
    </head>
    <body>
        <div class="login-box">
            <h2>🔐 Smart Invoice Pro</h2>
            <p style="color:#555; margin-bottom:25px;">Enter password to open the app</p>
            {% with messages = get_flashed_messages() %}
              {% if messages %}
                <div class="notice">{{ messages[0] }}</div>
              {% endif %}
            {% endwith %}
            <form method="post">
                <input type="password" name="password" placeholder="Password" required autofocus>
                <button type="submit">Open Account</button>
    <div style="margin-top:30px; text-align:center;">
      <a href="{{ url_for('reset_password') }}" style="color:#d32f2f; font-size:16px; text-decoration:underline;">
        🔄 Forgot Password? Reset Here
      </a>
    </div>
            </form>
            <div class="info">
                <small> <strong> </strong></small>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/setup-account", methods=["GET", "POST"])
def setup_account():
    admin_email = get_setting("admin_email", "")
    admin_password_hash = get_setting("admin_password_hash", "")
    if admin_email and admin_password_hash:
        return redirect(url_for("login"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        security_question = request.form.get("security_question") or ""
        security_answer = request.form.get("security_answer") or ""

        if not email or "@" not in email:
            flash("Please enter a valid email")
        elif len(password) < 4:
            flash("Password must be at least 4 characters")
        elif password != confirm:
            flash("Passwords do not match")
        elif not security_question or not security_answer:
            flash("Security question is required (for password recovery)")
        else:
            try:
                with db_transaction() as _c:
                    pass  # ensures settings table connection ready
                set_setting("admin_email", email)
                set_setting("admin_password_hash", generate_password_hash(password))
                set_setting("security_question", security_question.strip())
                set_setting("security_answer", security_answer.strip().lower())
                flash("Account created successfully. Please log in.")
                return redirect(url_for("login"))
            except Exception as e:
                flash(f"Setup failed: {e}")

    html = """
    <!doctype html>
    <html lang="en">
    <head><meta charset="utf-8"><title>Set Up Your Account</title>
    <style>
        body {background: linear-gradient(135deg, #1e3a8a, #3b82f6); display:flex; justify-content:center; align-items:center; min-height:100vh; margin:0; font-family: system-ui, Arial; padding:20px;}
        .box {background: white; padding: 40px; border-radius: 20px; box-shadow: 0 15px 40px rgba(0,0,0,0.3); width: 420px; text-align: center;}
        h2 {color: #1e3a8a; margin-bottom: 10px; font-size: 26px;}
        p {color:#666; margin-bottom:20px;}
        input {width: 100%; padding: 14px; margin: 8px 0; border: 1px solid #ddd; border-radius: 10px; font-size: 15px; box-sizing: border-box;}
        button {width: 100%; padding: 15px; background: #1e3a8a; color: white; border: none; border-radius: 10px; font-size: 18px; cursor: pointer; margin-top:10px;}
        button:hover {background: #1e40af;}
        .notice {background: #fee; color: #c62828; padding: 10px; border-radius: 8px; margin: 15px 0;}
    </style>
    </head>
    <body>
        <div class="box">
            <h2>Set Up Your Account</h2>
            <p>This is a one-time setup for this installation</p>
            {% with messages = get_flashed_messages() %}
              {% if messages %}<div class="notice">{{ messages[0] }}</div>{% endif %}
            {% endwith %}
            <form method="post">
                <input type="email" name="email" placeholder="Your Email" required>
                <input type="password" name="password" placeholder="Create Password" required>
                <input type="password" name="confirm" placeholder="Confirm Password" required>
                <input type="text" name="security_question" placeholder="Security Question (e.g. your pet's name?)" required>
                <input type="text" name="security_answer" placeholder="Answer" required>
                <button type="submit">Create Account</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    flash("log out")
    return redirect(url_for("login"))
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    question = get_setting("security_question", "What is your favorite color?")
    correct_answer = get_setting("security_answer", "").lower().strip()

    MASTER_PASSWORD = "ishtiaq@404"  # 🔐 hidden backup

    if request.method == "POST":
        user_input = request.form.get("answer", "").lower().strip()

        # ── Security answer OR Master password same field ──
        if user_input == correct_answer or user_input == MASTER_PASSWORD:
            set_setting("app_password", "0475")
            flash("Password reset successful!")
            return redirect(url_for("login"))
        else:
            flash("Incorrect answer. Try again.")

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Reset Password</title>
        <style>
            body {
                background: linear-gradient(135deg,#667eea,#764ba2);
                display:flex;
                justify-content:center;
                align-items:center;
                height:100vh;
                margin:0;
                font-family:system-ui;
            }

            .box {
                background:white;
                padding:40px;
                border-radius:20px;
                width:400px;
                text-align:center;
                box-shadow:0 15px 40px rgba(0,0,0,0.3);
            }

            h2 { color:#d32f2f; }

            input {
                width:100%;
                padding:12px;
                margin-top:15px;
                border:1px solid #ddd;
                border-radius:10px;
            }

            button {
                width:100%;
                padding:12px;
                margin-top:15px;
                background:#d32f2f;
                color:white;
                border:none;
                border-radius:10px;
                cursor:pointer;
            }

            p { color:#555; }
        </style>
    </head>
    <body>
        <div class="box">
            <h2>🔄 Reset Password</h2>

            <p><b>Security Question:</b><br>{{ question }}</p>

            <form method="post" autocomplete="off">
                <!-- ONLY ONE INPUT FIELD -->
                <input name="answer" placeholder="Enter your answer">
                <button type="submit">Reset Password</button>
            </form>
        </div>
    </body>
    </html>
    """, question=question)
# ---------- Paths ----------
#ROOT = Path.cwd()
DATA = ROOT / "db_files"
UPLOADS = ROOT / "media"

# DB_FILE upar pehle se define ho chuka hai (DB_DIR / "smart_invoice.db") — dobara define nahi kiya
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)

for p in (DATA, UPLOADS):
    p.mkdir(parents=True, exist_ok=True)

PRODUCTS  = DATA / "products.csv"
CUSTOMERS = DATA / "customers.csv"
INVOICES  = DATA / "invoices.csv"
#LINES     = DATA / "invoice_lines.csv"
PAYMENTS  = DATA / "payments.csv"
SETTINGS  = DATA / "settings.csv"
SEQ       = DATA / "sequence.csv"
#EXPENSES_CSV = DATA / "expenses.csv"
# موجودہ paths کے ساتھ یہ لائن شامل کریں
#TARGETS_CSV = DATA / "targets.csv"
#SALESMEN_CSV = DATA / "salesmen.csv"
PENDING_LOG_CSV = DATA / "pending_log.csv"
DISCOUNT_LOG_CSV = DATA / "discount_log.csv"
DELETED_INVOICES_CSV = DATA / "deleted_invoices.csv"   # soft delete bin
SALESMAN_HR_CSV = DATA / "salesman_hr.csv"              # attendance/advance/leaves
PROFIT_HISTORY_CSV = DATA / "profit_history.csv"        # monthly P&L snapshots

def _ensure(path: Path, head):
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(head)

_ensure(PRODUCTS,  ["name","unit_price","purchase_price","wholesaler_price","distributor_price","customer_price","stock","min_stock"])
_ensure(CUSTOMERS, ["name","address","phone","joined_date"])
_ensure(INVOICES, ["inv_no","date","name","address","phone","tax","discount","subtotal","grand_total","total","logo_path","pending_added","remarks","customer_type","salesman"])
_ensure(PAYMENTS,  ["pay_id","inv_no","date","amount","method","customer","address","note"])
_ensure(SETTINGS,  ["key","value"])
_ensure(SEQ,       ["key","value"])
_ensure(PENDING_LOG_CSV, ["id","date","from_inv","to_inv","customer","address","amount","status","approved_by"])
_ensure(DISCOUNT_LOG_CSV, ["id","date","inv_no","customer","discount_amt","approved_by"])
_ensure(DELETED_INVOICES_CSV, ["inv_no","date","name","address","phone","tax","discount","total","logo_path","pending_added","remarks","customer_type","salesman","deleted_on","deleted_lines"])
_ensure(SALESMAN_HR_CSV, ["id","salesman","date","type","amount","note"])
_ensure(PROFIT_HISTORY_CSV, ["month","year","total_sales","total_expenses","gross_profit","net_profit","saved_on"])

# ---------- CSV helpers ----------
def read_csv(p: Path):
    try:
        with p.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []

def write_csv(p: Path, rows, head):
    # Atomic write: pehle temp file mein likho, phir rename — power cut/crash safe
    import tempfile, os as _os
    tmp = p.parent / (p.name + ".tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=head)
            w.writeheader()
            for row in rows:
                clean_row = {k: (v if v is not None else "") for k, v in row.items()}
                clean_row = {k: clean_row.get(k, "") for k in head}
                w.writerow(clean_row)
        _os.replace(str(tmp), str(p))  # atomic on same filesystem
    except Exception as e:
        try: tmp.unlink()
        except: pass
        raise e

def append_csv(p: Path, row, head):
    with _inv_no_lock:
        if not p.exists() or p.stat().st_size == 0:
            write_csv(p, [], head)
        rows = read_csv(p)
        rows.append(row)
        write_csv(p, rows, head)
# ---------- Settings & Sequence: SQLite (settings.csv / sequence.csv legacy, kept only for one-time migration) ----------
def _ensure_kv_tables():
    with db_transaction() as c:
        c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS app_sequence (key TEXT PRIMARY KEY, value TEXT)")

def _migrate_kv_csv_to_sqlite(csv_path, table):
    try:
        with db_transaction() as c:
            count = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count > 0:
            return
        rows = read_csv(csv_path)
        if not rows:
            return
        with db_transaction() as c:
            for r in rows:
                c.execute(f"INSERT OR IGNORE INTO {table} (key, value) VALUES (?,?)",
                          (r.get("key",""), r.get("value","")))
        print(f"✅ Migrated {len(rows)} rows from {csv_path.name} to {table}")
    except Exception as e:
        print(f"❌ {table} CSV→SQLite migration error:", e)

_ensure_kv_tables()
_migrate_kv_csv_to_sqlite(SEQ, "app_sequence")

def get_seq(key, start=1):
    with db_transaction() as c:
        row = c.execute("SELECT value FROM app_sequence WHERE key=?", (key,)).fetchone()
        if row:
            try: return int(row[0])
            except: return start
        c.execute("INSERT INTO app_sequence (key, value) VALUES (?,?)", (key, str(start)))
    return start

def set_seq(key, val):
    with db_transaction() as c:
        c.execute("""
            INSERT INTO app_sequence (key, value) VALUES (?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, str(val)))

def read_payments_db():
    with db_transaction() as c:
        rows = c.execute("""
            SELECT id, inv_no, date, amount, method, customer, address, note, batch_id
            FROM payments ORDER BY id DESC
        """).fetchall()
    return [{
        "pay_id": str(r[0]), "inv_no": str(r[1]), "date": r[2] or "",
        "amount": f"{float(r[3] or 0):.2f}", "method": r[4] or "",
        "customer": r[5] or "", "address": r[6] or "", "note": r[7] or "",
        "batch_id": r[8] or ""
    } for r in rows]

def insert_payment_db(conn, inv_no, date, amount, method, customer, address, note, batch_id=""):
    cur = conn.execute("""
        INSERT INTO payments (inv_no, date, amount, method, customer, address, note, batch_id)
        VALUES (?,?,?,?,?,?,?,?)
    """, (str(inv_no), date, float(amount), method, customer, address, note, batch_id))
    return cur.lastrowid

def delete_payment_db(pay_id):
    with db_transaction() as c:
        c.execute("DELETE FROM payments WHERE id=?", (int(pay_id),))

def migrate_payments_csv_to_sqlite():
    try:
        with db_transaction() as c:
            count = c.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
        if count > 0:
            return
        old_rows = read_payments_db()
        if not old_rows:
            return
        old_rows.sort(key=lambda r: int(r.get("pay_id") or 0))
        with db_transaction() as c:
            for r in old_rows:
                c.execute("""
                    INSERT INTO payments (inv_no, date, amount, method, customer, address, note)
                    VALUES (?,?,?,?,?,?,?)
                """, (
                    str(r.get("inv_no","")), r.get("date",""),
                    float(r.get("amount","0") or 0), r.get("method",""),
                    r.get("customer",""), r.get("address",""), r.get("note","")
                ))
        print(f"✅ Migrated {len(old_rows)} payments from CSV to SQLite")
    except Exception as e:
        print("❌ Payments CSV→SQLite migration error:", e)

migrate_payments_csv_to_sqlite()

def record_payment_fifo(cust_name, cust_addr, amount, method, date_raw, note_in):
    """
    Shared FIFO payment logic — used by BOTH the Payments page and the
    Customer Ledger's own payment form, so the split behaves identically
    everywhere. Older invoices are cleared first; leftover becomes Advance.
    Returns (ok: bool, message: str).
    """
    cust_name = to_caps(cust_name); cust_addr = to_caps(cust_addr)
    if amount <= 0:
        return False, "Amount must be > 0"
    if not cust_name:
        return False, "Customer not found"

    date_raw = (date_raw or "").strip()
    if date_raw:
        try:
            date = fmt_date(datetime.datetime.strptime(date_raw, "%Y-%m-%d").date())
        except:
            date = fmt_date()
    else:
        date = fmt_date()

    with db_transaction() as _c2:
        _full_rows = _c2.execute("""
            SELECT inv_no, date, customer, customer_address, total,
                   grand_total, pending_added, remarks
            FROM invoices
        """).fetchall()
    cust_invs = [
        {"inv_no": r[0], "date": r[1], "name": r[2], "address": r[3],
         "total": r[4], "grand_total": r[5], "pending_added": r[6], "remarks": r[7]}
        for r in _full_rows
        if to_caps(r[2]) == cust_name and to_caps(r[3]) == cust_addr
    ]

    def _pd(d):
        for fmt in ("%Y-%m-%d","%d-%m-%y","%d-%m-%Y"):
            try: return datetime.datetime.strptime(d, fmt)
            except: pass
        return datetime.datetime.min
    cust_invs.sort(key=lambda r: _pd(r.get("date","")))

    existing_pays = read_payments_db()
    pay_map = {}
    for p in existing_pays:
        try: pay_map.setdefault(int(p["inv_no"]), []).append(p)
        except: pass

    remaining = amount
    plan = []

    for r in cust_invs:
        if remaining <= 0:
            break
        try: invn = int(r["inv_no"])
        except: continue

        if str(r.get("remarks","")).startswith("Pending Transferred to Inv #"):
            continue

        gt = r.get("grand_total")
        inv_total = float(gt) if gt not in (None,"") else max(
            float(r.get("total","0") or 0) - float(r.get("pending_added","0") or 0), 0.0)

        already = sum(float(p.get("amount","0") or 0) for p in pay_map.get(invn, []))
        inv_pending = max(inv_total - already, 0.0)
        if inv_pending <= 0:
            continue

        alloc = min(inv_pending, remaining)
        remaining -= alloc
        plan.append((invn, alloc))

    advance = round(remaining, 2)
    if not plan and advance <= 0:
        return False, "Nothing to apply — no pending invoices found"

    parts = [f"INV-{i} = Rs {a:,.0f}" for i, a in plan]
    note_auto = f"Received Rs {amount:,.0f}. Auto-adjusted: " + "; ".join(parts) if parts \
                else f"Received Rs {amount:,.0f}."
    if advance > 0:
        note_auto += f"; Advance = Rs {advance:,.0f}"
    if note_in:
        note_auto += f" | {note_in}"

    with db_transaction() as _c3:
        batch_id = uuid.uuid4().hex[:12]   # one id shared by every fragment of THIS payment
        for invn, alloc in plan:
            insert_payment_db(_c3, invn, date, alloc, method, cust_name, cust_addr, note_auto, batch_id)
        if advance > 0:
            insert_payment_db(_c3, 0, date, advance, method, cust_name, cust_addr, note_auto, batch_id)

    if advance > 0:
        return True, f"Split across {len(plan)} invoice(s) · Rs {advance:,.0f} kept as advance"
    return True, f"Payment of Rs {amount:,.0f} split across {len(plan)} invoice(s), oldest first"


def advance_monthly_inv_no() -> int:
    """Safe Auto Increase Invoice Number — thread lock se race condition se protected"""
    with _inv_no_lock:
        today = datetime.date.today()
        key = f"inv_{today.year}_{today.month:02d}"
        
        current = get_seq(key, 101)
        
        with db_transaction() as _c:
            _rows = _c.execute("SELECT inv_no FROM invoices").fetchall()
        used_numbers = {int(r[0]) for r in _rows if str(r[0]).isdigit()}
        
        while current in used_numbers:
            current += 1
        
        set_seq(key, current + 1)
        return current


# ---------- Settings ----------
_migrate_kv_csv_to_sqlite(SETTINGS, "app_settings")

def get_setting(k, default=""):
    with db_transaction() as c:
        row = c.execute("SELECT value FROM app_settings WHERE key=?", (k,)).fetchone()
    return row[0] if row else default

def set_setting(k, v):
    with db_transaction() as c:
        c.execute("""
            INSERT INTO app_settings (key, value) VALUES (?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (k, str(v)))

def init_settings():
    defaults = {
        "project_name": "Smart Invoice",
        "company_name": "SEIZE",
        "tax_default": "0",
        "date_format": "dd-mm-yy",
        "invoice_start": "100",
        "logo_path": "",
        "logo_show": "1",
        "auto_create_folders": "1",
        "output_folder": "",
        "developer_name": "ISHTIAQ AHMAD MAGRAY",
        "developer_phone": "+923495820495",   # Change to your phone number
        "contact_msg": "For new software development, contact the developer above.",
        "growth_rate": "10",
        "show_pending": "0",
        "pending_approval": "1",
        "discount_permission": "1",
       "master_password": "MASTER2025",      # Master password — forgotten app password se bypass
        # ---- Email (SMTP) settings for login verification / password reset ----
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_app_password": "",
        "smtp_from_name": "Sharim Enterprises",
        "smtp_use_tls": "1",
        "session_version": "1",   # bumped on password reset to invalidate old sessions
    }
    with db_transaction() as c:
        existing = {r[0] for r in c.execute("SELECT key FROM app_settings").fetchall()}
        for k, v in defaults.items():
            if k not in existing:
                c.execute("INSERT INTO app_settings (key, value) VALUES (?,?)", (k, v))
init_settings()

# ===================== AUTH: EMAIL MASKING / SMTP / OTP HELPERS =====================
def mask_email(email: str) -> str:
    """john.doe@gmail.com -> j*******e@gmail.com  |  customer123@gmail.com -> c********r@gmail.com"""
    email = (email or "").strip()
    if "@" not in email:
        return "•••••"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked = local[0] + "*" * max(len(local) - 1, 1)
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def send_email(to_email: str, subject: str, body_html: str):
    """Sends email via SMTP settings configured in Settings page. Never hardcoded.
    Returns (success, message). Never logs/prints the full email body (may contain OTP)."""
    host = get_setting("smtp_host", "").strip()
    port = get_setting("smtp_port", "587").strip()
    user = get_setting("smtp_user", "").strip()
    app_pw = get_setting("smtp_app_password", "").strip()
    from_name = get_setting("smtp_from_name", "Sharim Enterprises").strip()
    use_tls = get_setting("smtp_use_tls", "1") == "1"

    if not host or not user or not app_pw:
        return False, "Email service not configured. Ask admin to set SMTP details in Settings."

    try:
        msg = MIMEText(body_html, "html")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{user}>"
        msg["To"] = to_email

        with smtplib.SMTP(host, int(port or 587), timeout=15) as server:
            if use_tls:
                server.starttls(context=ssl.create_default_context())
            server.login(user, app_pw)
            server.sendmail(user, [to_email], msg.as_string())
        return True, "sent"
    except Exception as e:
        # Do not leak credentials/OTP; generic message only
        print("❌ send_email error:", type(e).__name__)
        return False, "Could not send email right now. Please try again shortly."


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def generate_and_send_otp(email: str, purpose: str = "reset"):
    """Creates a 6-digit OTP (10 min expiry), stores its HASH only, emails it.
    Always returns a generic outcome message — caller must never reveal whether
    the email matched an account."""
    code = f"{secrets.randbelow(1000000):06d}"
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat()

    with db_transaction() as c:
        c.execute("DELETE FROM password_reset_otp WHERE email=?", (email.lower(),))
        c.execute("""
            INSERT INTO password_reset_otp (email, otp_hash, expires_at, attempts, last_sent_at, verified)
            VALUES (?,?,?,0,?,0)
        """, (email.lower(), _hash_otp(code), expires_at, datetime.datetime.utcnow().isoformat()))

    subject = "Your Verification Code"
    body = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:420px;margin:auto;padding:24px;
    background:#f3f7f6;border-radius:14px">
      <h2 style="color:#0d3b34;margin-bottom:6px">🔐 Verification Code</h2>
      <p style="color:#5f7a75;font-size:13px;margin-bottom:18px">Use this code to continue. It expires in 10 minutes.</p>
      <div style="background:#0d3b34;color:#f5a524;font-size:32px;font-weight:900;letter-spacing:6px;
      text-align:center;padding:16px;border-radius:10px">{code}</div>
      <p style="color:#94a3b8;font-size:11px;margin-top:18px">If you didn't request this, you can ignore this email.</p>
    </div>"""
    ok, msg = send_email(email, subject, body)
    return ok, msg


def verify_otp_code(email: str, code: str):
    with db_transaction() as c:
        row = c.execute("""
            SELECT id, otp_hash, expires_at, attempts FROM password_reset_otp
            WHERE email=? ORDER BY id DESC LIMIT 1
        """, (email.lower(),)).fetchone()

        if not row:
            return False, "Code expired or not found. Please request a new one."

        rid, otp_hash, expires_at, attempts = row
        if attempts >= 5:
            return False, "Too many incorrect attempts. Please request a new code."

        try:
            expired = datetime.datetime.utcnow() > datetime.datetime.fromisoformat(expires_at)
        except Exception:
            expired = True
        if expired:
            return False, "Code expired. Please request a new one."

        if _hash_otp((code or "").strip()) != otp_hash:
            c.execute("UPDATE password_reset_otp SET attempts=attempts+1 WHERE id=?", (rid,))
            return False, "Incorrect code. Please try again."

        c.execute("UPDATE password_reset_otp SET verified=1 WHERE id=?", (rid,))
    return True, "verified"


def otp_resend_cooldown_seconds(email: str) -> int:
    """Returns seconds remaining before a resend is allowed (60s cooldown)."""
    with db_transaction() as c:
        row = c.execute("""
            SELECT last_sent_at FROM password_reset_otp WHERE email=? ORDER BY id DESC LIMIT 1
        """, (email.lower(),)).fetchone()
    if not row or not row[0]:
        return 0
    try:
        elapsed = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(row[0])).total_seconds()
    except Exception:
        return 0
    remaining = 60 - int(elapsed)
    return max(remaining, 0)


def is_otp_verified(email: str) -> bool:
    with db_transaction() as c:
        row = c.execute("""
            SELECT verified FROM password_reset_otp WHERE email=? ORDER BY id DESC LIMIT 1
        """, (email.lower(),)).fetchone()
    return bool(row and row[0] == 1)


def clear_otp(email: str):
    with db_transaction() as c:
        c.execute("DELETE FROM password_reset_otp WHERE email=?", (email.lower(),))


def check_password_strength(pw: str) -> str:
    """Returns empty string if OK, else an error message."""
    if len(pw) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", pw):
        return "Password must include at least one uppercase letter"
    if not re.search(r"[a-z]", pw):
        return "Password must include at least one lowercase letter"
    if not re.search(r"[0-9]", pw):
        return "Password must include at least one number"
    return ""


# ---------- Utils ----------
def to_caps(s: str) -> str:
    """Title Case — Mr Ishtiaq Ahmad Magray (har lafz ka pehla harf bara)"""
    s = (s or "").strip()
    if not s:
        return ""
    return " ".join(
        w[0].upper() + w[1:].lower() if len(w) > 1 else w.upper()
        for w in s.split()
    )

def fmt_date(dt: Optional[datetime.date] = None, for_db: bool = False) -> str:  
    if dt is None:  
        dt = datetime.date.today()  
    if for_db:  
        return dt.isoformat()  # 2026-01-01 → DB   
    else:  
        f = get_setting("date_format","dd-mm-yy")   # settings   
        if f == "dd-mm-yyyy":  
            return dt.strftime("%d-%m-%Y")  
        if f == "yyyy-mm-dd":  
            return dt.strftime("%Y-%m-%d")  
        return dt.strftime("%d-%m-%Y")  # dd-mm-yy  

def output_base() -> Path:
    base_text = get_setting("output_folder","")
    return Path(base_text) if base_text else ROOT

def ensure_out_dirs(year: int, month_name: str) -> Path:
    base = output_base()
    target = base / "SEIZE" / str(year) / month_name
    if get_setting("auto_create_folders","1") == "1":
        target.mkdir(parents=True, exist_ok=True)
    return target

def safe_name(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch in " _-").strip().replace(" ","_")

# ---------- Domain loaders ----------
def load_products():
    """اب SQLite سے پروڈکٹس لوڈ ہوں گے"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            SELECT name, unit_price, purchase_price, wholesaler_price, 
                   distributor_price, customer_price, stock, min_stock,
                   pieces_per_carton, price_per_piece 
            FROM products 
            ORDER BY name
        """)
        rows = cur.fetchall()
        conn.close()

        out = []
        for r in rows:
            out.append({
                "name": r[0],
                "unit_price": float(r[1] or 0),
                "purchase_price": float(r[2] or 0),
                "wholesaler_price": float(r[3] or 0),
                "distributor_price": float(r[4] or 0),
                "customer_price": float(r[5] or 0),
                "stock": float(r[6] or 0),
                "min_stock": float(r[7] or 0),
                "pieces_per_carton": int(r[8] or 12),
                "price_per_piece": float(r[9] or 0)
            })
        return out
    except Exception as e:
        print("❌ Load Products Error:", e)
        return []
def load_customers():
    """اب Customers بھی SQLite سے لوڈ ہوں گے"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT name, address, phone, joined_date FROM customers ORDER BY name")
        rows = cur.fetchall()
        conn.close()

        out = []
        for r in rows:
            out.append({
                "name": to_caps(r[0]),
                "address": to_caps(r[1] or ""),
                "phone": r[2] or "",
                "joined_date": r[3] or ""
            })
        return out
    except Exception as e:
        print("❌ Load Customers Error:", e)
        return []

def ensure_sales_log_table():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            inv_no TEXT
            product TEXT,
            qty REAL,
            sell_price REAL
        )
    """)
    conn.commit()
    conn.close()

# ensure_sales_log_table already init_db ke andar hai — dobara call zaroori nahi
# (init_db() pehle se line 201 par call ho chuka hai)


# ---------- PDF helpers ----------
def draw_invoice_pdf(out_path: Path, company: str, logo_path: Optional[str], show_logo: bool,
                     inv_no: int, date_str_display: str, cust_name: str, cust_addr: str, cust_phone: str,
                     lines, tax_pct: float, pending_added: float = 0.0,
                     discount: float = 0.0, salesman: str = "",
                     customer_type: str = "customer") -> float:
    """
    Professional invoice PDF — exact match to "SEIZE" image
    Logo ab bada + bilkul center mein dikhega
    """
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.lib import colors
    import textwrap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    W, H = A4

    ML = 15*mm; MR = W - 15*mm
    lw = 0.7

    # ── compute totals ──
    subtotal = sum(float(li.get("qty",0))*float(li.get("unit_price",0)) for li in lines)
    total_qty = sum(float(li.get("qty",0)) for li in lines)
    tax_amt   = subtotal * tax_pct / 100
    net_sale  = subtotal + tax_amt - discount
    grand     = net_sale + pending_added

    # ══════════════════════════════════════════════════════
    # ROW 1 — Company name + Logo (Logo ab bada + center)
    # ══════════════════════════════════════════════════════
    top_y = H - 16*mm
    c.setFont("Helvetica-Bold", 32)
    c.setFillColor(colors.black)
    c.drawString(ML, top_y - 8*mm, company.upper())

    if show_logo and logo_path and Path(logo_path).exists():
        try:
            img = ImageReader(logo_path)
            c.drawImage(img, MR - 36*mm, top_y - 12*mm, width=45*mm, height=18*mm,
                        preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print("Logo error:", e)

    # ── Outer top border line ──
    row1_bottom = top_y - 10*mm
    c.setLineWidth(lw)
    c.line(ML, row1_bottom, MR, row1_bottom)

    # ══════════════════════════════════════════════════════
    # ROW 2 — Customer info (left) | Invoice box (right)
    # ══════════════════════════════════════════════════════
    box_x = ML + 125*mm
    box_top = row1_bottom
    box_row_h = 7.5*mm
    box_bottom = box_top - 3 * box_row_h

    c.setLineWidth(lw)
    c.rect(box_x, box_bottom, MR - box_x, box_top - box_bottom)
    mid_x = box_x + (MR - box_x) * 0.55
    c.line(mid_x, box_bottom, mid_x, box_top)

    # Row 1 in box: Invoice #
    y_b = box_top - box_row_h
    c.line(box_x, y_b, MR, y_b)
    c.setFont("Helvetica", 10)
    c.drawString(box_x + 3*mm, y_b + 2.5*mm, "Invoice #:")
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString((mid_x + MR)/2, y_b + 2.5*mm, str(inv_no))

    # Row 2: Date
    y_b2 = box_top - 2*box_row_h
    c.line(box_x, y_b2, MR, y_b2)
    c.setFont("Helvetica", 10)
    c.drawString(box_x + 3*mm, y_b2 + 2.5*mm, "Date:")
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString((mid_x + MR)/2, y_b2 + 2.5*mm, date_str_display)

    # Row 3: Total Qty
    c.setFont("Helvetica", 10)
    c.drawString(box_x + 3*mm, box_bottom + 2.5*mm, "Total Qty:")
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString((mid_x + MR)/2, box_bottom + 2.5*mm, f"{total_qty:g}")

    # Left customer info
    cy = row1_bottom - 6.5*mm
    lbl_x = ML + 2*mm; colon_x = ML + 22*mm; val_x = ML + 26*mm

    def cust_row(label, value, yy):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(lbl_x, yy, label)
        c.drawString(colon_x, yy, ":")
        c.setFont("Helvetica", 11)
        c.drawString(val_x, yy, str(value)[:42])

    cust_row("Name",    cust_name, cy)
    cy -= 5.5*mm
    cust_row("Address", cust_addr, cy)
    cy -= 5.5*mm
    cust_row("Phone",   cust_phone or "", cy)
    if salesman:
        cy -= 5.5*mm
        cust_row("Salesman", salesman, cy)
    header_bottom = box_bottom - 1*mm

    # Bottom border of header section
    c.setLineWidth(lw)
    #c.line(ML, header_bottom, MR, header_bottom)

    # ══════════════════════════════════════════════════════
    # PRODUCTS TABLE
    # ══════════════════════════════════════════════════════
    tbl_top = header_bottom -3*mm
    RH = 7.5*mm

    c_sr   = ML
    c_prod = ML + 14*mm
    c_qty  = ML + 105*mm
    c_up   = ML + 122*mm
    c_total_start = ML+155*mm
    c_tot  = MR

    def tbl_vlines(y_top, y_bot):
        for x in [c_prod, c_qty, c_up, c_total_start]:
            c.line(x, y_top, x, y_bot)

    # Header row
    th_y = tbl_top - RH
    c.setLineWidth(lw)
    c.rect(ML, th_y, MR - ML, RH)
    tbl_vlines(tbl_top, th_y)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawCentredString(c_sr + 7*mm,          th_y + 2.8*mm, "Sr.")
    c.drawCentredString((c_prod + c_qty)/2,   th_y + 2.8*mm, "Product")
    c.drawCentredString(c_qty + 8.5*mm,       th_y + 2.8*mm, "Qty")
    c.drawCentredString((c_up + c_total_start)/2,th_y + 2.8*mm,"Unit Price")
    c.drawCentredString((c_total_start + c_tot)/2,th_y + 2.8*mm,"Total")

    # Data rows
    y = th_y
    for sr, li in enumerate(lines, 1):
        try:
            qty = float(li.get("qty",0)); up = float(li.get("unit_price",0))
        except: qty = up = 0.0
        row_y = y - RH
        c.setLineWidth(0.4)
        c.rect(ML, row_y, MR - ML, RH)
        tbl_vlines(y, row_y)
        c.setFont("Helvetica", 10)
        c.drawCentredString(c_sr + 7*mm,        row_y + 2.8*mm, str(sr))
        c.drawString(c_prod + 2*mm,             row_y + 2.8*mm, str(li.get("product",""))[:40])
        c.drawCentredString(c_qty + 8.5*mm,     row_y + 2.8*mm, f"{qty:g}")
        c.drawRightString(c_total_start - 2*mm,row_y + 2.8*mm,f"{up:,.0f}")
        c.drawRightString(c_tot - 2*mm, row_y + 2.8*mm,f"{qty*up:,.0f}")
        y = row_y

    prod_table_bottom = y

    # ══════════════════════════════════════════════════════
    # BOTTOM TABLES
    # ══════════════════════════════════════════════════════
    grand_total   = subtotal + tax_amt - discount
    total_amount  = grand_total + pending_added

    gap  = 5*mm
    half = (MR - ML - gap) / 2
    left_x  = ML
    right_x = ML + half + gap
    BRH = 8.5*mm

    # LEFT TABLE
    if pending_added > 0:
        left_rows = [
            ("Previous Pending",  f"Rs {pending_added:,.0f}", False),
            ("Current Amount",    f"Rs {grand_total:,.0f}",   False),
            ("Total Amount",      f"Rs {total_amount:,.0f}",  False),
        ]
    else:
        left_rows = []
    lmid = left_x + half * 0.56

    lt_top = prod_table_bottom - 8*mm
    for i, (label, value, is_bold) in enumerate(left_rows):
        ry = lt_top - (i + 1) * BRH
        c.setLineWidth(lw)
        c.rect(left_x, ry, half, BRH)
        c.line(lmid, ry, lmid, ry + BRH)
        c.setFont("Helvetica-Bold" if is_bold else "Helvetica", 10.5)
        c.drawString(left_x + 3*mm, ry + 2.8*mm, label)
        c.setFont("Helvetica-Bold" if is_bold else "Helvetica", 10.5)
        c.drawRightString(lmid + half * 0.44 - 2*mm, ry + 2.8*mm, value)

    # RIGHT TABLE
    right_rows_all = [
        ("Subtotal",              f"Rs {subtotal:,.0f}",   False,        False),
        ("Discount",              f"Rs {discount:,.0f}",   discount==0,  False),
        (f"Tax ({tax_pct:.0f}%)", f"Rs {tax_amt:,.0f}",   tax_pct==0,   False),
        ("GRAND TOTAL",           f"Rs {grand_total:,.0f}", False,       True),
    ]
    right_rows = [(l, v, bold) for l, v, hide, bold in right_rows_all if not hide]

    rmid = right_x + half * 0.56
    rt_top = prod_table_bottom
    for i, (label, value, is_bold) in enumerate(right_rows):
        ry = rt_top - (i + 1) * BRH
        c.setLineWidth(lw)
        c.rect(right_x, ry, half, BRH)
        c.line(rmid, ry, rmid, ry + BRH)
        c.setFont("Helvetica-Bold" if is_bold else "Helvetica", 10.5)
        c.drawString(right_x + 3*mm, ry + 2.8*mm, label)
        c.drawRightString(rmid + half * 0.44 - 2*mm, ry + 2.8*mm, value)

    bottom_rows  = max(len(left_rows), len(right_rows))
    tables_bottom = prod_table_bottom - bottom_rows * BRH

    # ── SIGNATURE ──
    sig_y = tables_bottom - 20*mm
    c.setLineWidth(0.6)
    sig_left  = ML + half + gap + 5*mm
    sig_right = MR - 5*mm
    c.line(sig_left, sig_y, sig_right, sig_y)
    c.setFont("Helvetica", 10)
    c.drawCentredString((sig_left + sig_right) / 2, sig_y - 5*mm, "Customer Signature")

    # ── THANK YOU BOX ──
    thank_box_y = sig_y - 18*mm
    thank_box_h = 12*mm

    c.setLineWidth(0)
    c.roundRect(
        ML + 25*mm,
        thank_box_y,
        (MR - ML) - 50*mm,
        thank_box_h,
        3*mm,
        stroke=0,
        fill=0
    )

    c.setFont("BahnschriftBold", 14)
    c.setFillColor(colors.HexColor("#0B5394"))
    c.drawCentredString(W/2, thank_box_y + 4.5*mm, "THANK YOU FOR YOUR BUSINESS")

    c.setFillColor(colors.black)

    # ── OUTER BORDER ──
    page_bottom = sig_y - 15*mm
    c.setLineWidth(1.5)
    c.rect(ML - 1*mm, page_bottom, (MR - ML) + 2*mm, (H - 10*mm) - page_bottom)

    c.save()
    return total_amount



# ===== PENDING MANAGEMENT SYSTEM — Carry Forward with Duplicate Prevention =====

def get_pending(name, address):
    """Get total outstanding pending for a customer"""
    name = to_caps(name); address = to_caps(address)
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT pending_amount FROM customer_pending WHERE customer_name=? AND customer_address=?", (name, address))
        row = c.fetchone()
        conn.close()
        return float(row[0]) if row else 0.0
    except: return 0.0

def update_pending(name, address, new_pending):
    """Set new pending amount for customer (never negative)"""
    name = to_caps(name); address = to_caps(address)
    new_pending = max(0.0, float(new_pending))
    try:
        with db_transaction() as c:
            c.execute("""INSERT INTO customer_pending (customer_name, customer_address, pending_amount)
                         VALUES (?,?,?)
                         ON CONFLICT(customer_name,customer_address) DO UPDATE SET
                         pending_amount=excluded.pending_amount""", (name, address, new_pending))
    except Exception as e:
        print("Pending update error:", e)
def _ensure_pending_log_table():
    with db_transaction() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, from_inv TEXT, to_inv TEXT,
                customer TEXT, address TEXT, amount REAL,
                status TEXT, approved_by TEXT
            )
        """)

def _migrate_pending_log_csv():
    try:
        with db_transaction() as c:
            count = c.execute("SELECT COUNT(*) FROM pending_log").fetchone()[0]
        if count > 0:
            return
        rows = read_csv(PENDING_LOG_CSV)
        if not rows:
            return
        with db_transaction() as c:
            for r in rows:
                c.execute("""
                    INSERT INTO pending_log (date, from_inv, to_inv, customer, address, amount, status, approved_by)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    r.get("date",""), r.get("from_inv",""), r.get("to_inv",""),
                    r.get("customer",""), r.get("address",""), float(r.get("amount","0") or 0),
                    r.get("status",""), r.get("approved_by","")
                ))
        print(f"✅ Migrated {len(rows)} rows from pending_log.csv to pending_log table")
    except Exception as e:
        print("❌ pending_log CSV→SQLite migration error:", e)

_ensure_pending_log_table()
_migrate_pending_log_csv()

def add_pending_to_invoice(from_inv_no, to_inv_no, customer_name, customer_address, pending_amount):
    """
    Carry-forward pending from one invoice to another.
    Rules:
      1. Same pending cannot be added twice (duplicate prevention)
      2. Once transferred, source invoice status = 'Transferred'
      3. Logs the transfer in pending_log (SQLite)
    Returns: (success: bool, message: str)
    """
    name = to_caps(customer_name); address = to_caps(customer_address)

    try:
        with db_transaction() as c:
            # ── Duplicate check + log insert + invoice remarks update, ALL
            # in one transaction — no race window between checking and
            # writing, and no partial state (log without remarks, or
            # vice-versa) if anything fails mid-way. ──
            dup = c.execute(
                "SELECT to_inv FROM pending_log WHERE from_inv=? AND status='Transferred'",
                (str(from_inv_no),)
            ).fetchone()
            if dup:
                return False, f"Pending from Invoice #{from_inv_no} has already been transferred to Invoice #{dup[0]}. Duplicate blocked!"

            c.execute("""
                INSERT INTO pending_log (date, from_inv, to_inv, customer, address, amount, status, approved_by)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                datetime.date.today().strftime("%d-%m-%Y"), str(from_inv_no), str(to_inv_no),
                name, address, float(pending_amount), "Transferred", "System"
            ))
            c.execute(
                "UPDATE invoices SET remarks=? WHERE inv_no=?",
                (f"Pending Transferred to Inv #{to_inv_no}", str(from_inv_no))
            )
    except Exception as e:
        print("Pending transfer error:", e)
        return False, "Error transferring pending — nothing was saved."

    return True, f"Pending Rs {pending_amount:,.0f} transferred from Inv #{from_inv_no} to Inv #{to_inv_no}"


def is_pending_already_transferred(from_inv_no):
    """Check if pending from this invoice was already transferred"""
    with db_transaction() as c:
        row = c.execute(
            "SELECT to_inv FROM pending_log WHERE from_inv=? AND status='Transferred'",
            (str(from_inv_no),)
        ).fetchone()
    return (True, row[0]) if row else (False, None)

def build_month_summary_pdf(year: int, month_name: str, out_dir: Path) -> Path:
    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT inv_no, date, customer, customer_address, total
            FROM invoices
        """).fetchall()
    rows = [
        {"inv_no": r[0], "date": r[1], "name": r[2], "address": r[3], "total": r[4]}
        for r in _inv_rows
    ]
    month_rows = []
    for r in rows:
        d = r.get("date","")
        try:  
            dt = datetime.datetime.strptime(d, "%Y-%m-%d")  
        except:  
            try:  
                if "-" in d and len(d.split("-")[2]) == 2:  
                    dt = datetime.datetime.strptime(d, "%d-%m-%y")  
                elif "-" in d and len(d.split("-")[2]) == 4:  
                    dt = datetime.datetime.strptime(d, "%d-%m-%Y")  
                else:  
                    continue  
            except:  
                continue  
        if dt.year == year and dt.strftime("%B") == month_name:
            month_rows.append(r)
    total = sum(float(r.get("total","0") or 0) for r in month_rows)
    invs  = len(month_rows)
    custs = len({(to_caps(r["name"]), to_caps(r["address"])) for r in month_rows})
    fn = out_dir / f"SUMMARY_{year}_{month_name}.pdf"
    c = canvas.Canvas(str(fn), pagesize=A4)
    margin = 30; left = margin; right = PAGE_W - margin
    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, PAGE_H - margin - 10, f"Monthly Summary – {month_name} {year}")
    c.setFont("Helvetica", 11)
    c.drawString(left, PAGE_H - margin - 30, f"Total Sales: Rs {total:,.2f}   |   Invoices: {invs}   |   Customers: {custs}")
    c.line(left, PAGE_H - margin - 36, right, PAGE_H - margin - 36)
    y = PAGE_H - margin - 56
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left,      y, "Invoice"); c.drawString(left+40,   y, "Date"); c.drawString(left+100,  y, "Customer")
    c.drawString(left+280,  y, "Address"); c.drawRightString(right-8, y, "Amount")
    y -= 14; c.setFont("Helvetica", 10)
    for r in month_rows[:40]:
        c.drawString(left, y, str(r["inv_no"])); c.drawString(left+40, y, r["date"])
        c.drawString(left+100, y, to_caps(r["name"])[:24]); c.drawString(left+280, y, to_caps(r["address"])[:22])
        c.drawRightString(right-8, y, f"{float(r.get('total','0')):,.2f}"); y -= 14
        if y < 100: break
    bar_x = left; bar_y = 90; bar_w = right - left - 60; bar_h = 30
    c.setFont("Helvetica", 10); c.drawString(left, bar_y + bar_h + 12, "Monthly Sales (Rs)")
    c.rect(bar_x, bar_y, bar_w, bar_h)
    max_expected = max(total * 1.1, 1.0)
    fill_w = bar_w * (total / max_expected)
    c.rect(bar_x, bar_y, fill_w, bar_h, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 12); c.drawRightString(right, bar_y - 6, f"{total:,.2f}")
    c.showPage(); c.save(); return fn
def generate_monthly_summary_pdf(year: int, month_name: str) -> Path:
    """
    Auto-generates a professional Monthly Summary PDF (matches "SEIZE" sample layout).
    Called automatically whenever an invoice is created, edited, deleted, or recovered.
    Saved as: <output_base>/Seize/<year>/<month_name>/<month_name>_Summary.pdf  (overwrites old file)
    """
    import math
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    def parse_dt(d):
        for fmt in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(d, fmt)
            except Exception:
                continue
        return None

    try:
        with db_transaction() as _c:
            _inv_rows = _c.execute("""
                SELECT inv_no, date, customer, customer_address, total
                FROM invoices
            """).fetchall()
        rows = [
            {"inv_no": r[0], "date": r[1], "name": r[2], "address": r[3], "total": r[4]}
            for r in _inv_rows
        ]
        month_rows = []
        for r in rows:
            dt = parse_dt(r.get("date", ""))
            if dt and dt.year == year and dt.strftime("%B") == month_name:
                month_rows.append(r)
        month_rows.sort(key=lambda r: int(r.get("inv_no", 0) or 0))

        total_sales = sum(float(r.get("total", "0") or 0) for r in month_rows)
        inv_count = len(month_rows)
        cust_count = len({(to_caps(r.get("name", "")), to_caps(r.get("address", ""))) for r in month_rows})

        pays = read_payments_db()
        received = 0.0
        for p in pays:
            dt = parse_dt(p.get("date", ""))
            if dt and dt.year == year and dt.strftime("%B") == month_name:
                try:
                    received += float(p.get("amount", "0") or 0)
                except Exception:
                    pass

        pending = max(0.0, total_sales - received)

        inv_nos_set = {str(r.get("inv_no")) for r in month_rows}
        with db_transaction() as _c:
            _line_rows = _c.execute("""
                SELECT inv_no, product, qty, unit_price
                FROM invoice_items
            """).fetchall()
        lines_all = [
            {"inv_no": r[0], "product": r[1], "qty": r[2], "unit_price": r[3]}
            for r in _line_rows
        ]
        prod_cost = {p["name"]: float(p.get("purchase_price", 0) or 0) for p in load_products()}
        profit = 0.0
        for li in lines_all:
            if str(li.get("inv_no")) in inv_nos_set:
                try:
                    q = float(li.get("qty", 0) or 0)
                    u = float(li.get("unit_price", 0) or 0)
                    cp = prod_cost.get(to_caps(li.get("product", "")), 0.0)
                    profit += (u - cp) * q
                except Exception:
                    pass

        company = get_setting("company_name","SEIZE")
        out_dir = ensure_out_dirs(year, month_name)
        out_dir.mkdir(parents=True, exist_ok=True)
        fn = out_dir / f"{month_name}_Summary.pdf"

        W, H = A4
        ML = 15 * mm
        MR = W - 15 * mm
        ROW_H = 6 * mm
        BOTTOM_LIMIT = 22 * mm

        col_inv, col_date, col_cust, col_addr, col_amt = ML, ML + 18 * mm, ML + 38 * mm, ML + 100 * mm, MR

        def header_bottom_y():
            y = H - 15 * mm
            y -= 8 * mm
            y -= 7 * mm
            y -= 6 * mm
            y -= 6 * mm
            y -= 3 * mm
            y -= 7 * mm
            y -= 2.5 * mm
            y -= 4.5 * mm
            return y

        def draw_header(c):
            y = H - 15 * mm
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 20)
            c.drawString(ML, y, company.upper())
            y -= 8 * mm
            c.setFont("Helvetica-Bold", 14)
            c.drawString(ML, y, f"Monthly Summary \u2013 {month_name} {year}")
            y -= 7 * mm
            c.setFont("Helvetica", 10.5)
            c.drawString(ML, y, f"Total Sales: Rs {total_sales:,.2f}   |   Invoices: {inv_count}   |   Customers: {cust_count}")
            y -= 6 * mm
            c.drawString(ML, y, f"Received: Rs {received:,.2f}   |   Pending: Rs {pending:,.2f}   |   Profit: Rs {profit:,.2f}")
            y -= 3 * mm
            c.setLineWidth(0.8)
            c.line(ML, y, MR, y)
            y -= 7 * mm
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(col_inv, y, "Invoice")
            c.drawString(col_date, y, "Date")
            c.drawString(col_cust, y, "Customer")
            c.drawString(col_addr, y, "Address")
            c.drawRightString(col_amt, y, "Amount")
            y -= 2.5 * mm
            c.setLineWidth(0.5)
            c.line(ML, y, MR, y)
            y -= 4.5 * mm
            return y

        def draw_footer(c, page_num, total_pages):
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.grey)
            gen_time = datetime.datetime.now().strftime("%d-%m-%Y %I:%M %p")
            c.drawString(ML, 10 * mm, f"Generated on {gen_time}")
            c.drawRightString(MR, 10 * mm, f"Page {page_num} of {total_pages}")
            c.setFillColor(colors.black)

        y_start = header_bottom_y()
        rows_per_page = max(1, int((y_start - BOTTOM_LIMIT) / ROW_H))
        total_pages = max(1, math.ceil(len(month_rows) / rows_per_page)) if month_rows else 1

        c = canvas.Canvas(str(fn), pagesize=A4)
        if not month_rows:
            draw_header(c)
            draw_footer(c, 1, 1)
            c.showPage()
        else:
            idx = 0
            page_num = 1
            while idx < len(month_rows):
                y = draw_header(c)
                chunk = month_rows[idx: idx + rows_per_page]
                c.setFont("Helvetica", 9)
                for r in chunk:
                    c.drawString(col_inv, y, str(r.get("inv_no", "")))
                    c.drawString(col_date, y, str(r.get("date", "")))
                    c.drawString(col_cust, y, to_caps(r.get("name", ""))[:26])
                    c.drawString(col_addr, y, to_caps(r.get("address", ""))[:30])
                    c.drawRightString(col_amt, y, f"{float(r.get('total', 0) or 0):,.2f}")
                    y -= ROW_H
                draw_footer(c, page_num, total_pages)
                idx += rows_per_page
                page_num += 1
                if idx < len(month_rows):
                    c.showPage()
            c.showPage()
        c.save()
        return fn
    except Exception as e:
        print("Monthly Summary PDF error:", e)
        return None
# ---------- HTML shell — Enterprise Professional UI ----------
TPL_H = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{project}} — Enterprise Pro</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="manifest" href="/static/manifest.json">
<meta name="theme-color" content="#0f172a">
<script>if("serviceWorker" in navigator){navigator.serviceWorker.register("/static/service-worker.js");}</script>
<style>
/* ============ CSS VARIABLES ============ */
:root {
  --sidebar-w: 260px;
  --sidebar-bg: linear-gradient(180deg, #0b2b27 0%, #0f3d37 55%, #0c332e 100%);
  --sidebar-accent: #f5a524;
  --sidebar-text: #c9dcd8;
  --sidebar-hover: rgba(245,165,36,0.14);
  --sidebar-active: rgba(245,165,36,0.22);
  --topbar-bg: #ffffff;
  --topbar-shadow: 0 1px 3px rgba(13,59,52,0.1);
  --body-bg: #f3f7f6;
  --card-bg: #ffffff;
  --card-shadow: 0 2px 8px rgba(13,59,52,0.07), 0 10px 24px rgba(13,59,52,0.06);
  --card-radius: 16px;
  --border: #dde8e5;
  --text: #10302b;
  --text-muted: #5f7a75;
  --btn-primary: #4f46e5;
  --btn-danger: #e11d48;
  --btn-success: #0d9488;
  --btn-warning: #f5a524;
  --heading: #0d3b34;
  --input-bg: #f7faf9;
  --input-border: #dde8e5;
  --notice-bg: #ecfdf5;
  --notice-border: #6ee7b7;
  --notice-text: #065f46;
  --error-bg: #fef2f2;
  --error-border: #fca5a5;
  --error-text: #991b1b;
  --badge-blue: #e0e7ff;
  --badge-blue-text: #4338ca;
  --badge-green: #ccfbf1;
  --badge-green-text: #0f766e;
  --badge-red: #ffe4e6;
  --badge-red-text: #be123c;
  --badge-yellow: #fef3c7;
  --badge-yellow-text: #b45309;
  --badge-purple: #f3e8ff;
  --badge-purple-text: #7e22ce;
}
body.dark {
  --topbar-bg: #0f2b27;
  --body-bg: #081c19;
  --card-bg: #0f2b27;
  --border: #1c4038;
  --text: #eaf5f2;
  --text-muted: #8fb0aa;
  --input-bg: #081c19;
  --input-border: #1c4038;
  --notice-bg: #064e3b;
  --notice-border: #059669;
  --notice-text: #a7f3d0;
  --heading: #f5a524;
}
/* ============ RESET ============ */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--body-bg);color:var(--text);display:flex;min-height:100vh;transition:background .3s,color .3s}

/* ============ SIDEBAR ============ */
#sidebar{width:var(--sidebar-w);background:var(--sidebar-bg);display:flex;flex-direction:column;position:fixed;top:0;left:0;height:100vh;z-index:1000;transition:transform .3s;overflow-y:auto;overflow-x:hidden}
#sidebar.collapsed{transform:translateX(-100%)}
.sb-brand{padding:20px 18px 14px;border-bottom:1px solid rgba(255,255,255,.08)}
.sb-brand .brand-name{font-size:17px;font-weight:800;color:#f8fafc;letter-spacing:.5px;line-height:1.2}
.sb-brand .brand-sub{font-size:11px;color:#94a3b8;margin-top:3px;text-transform:uppercase;letter-spacing:1px}
.sb-section{padding:10px 0}
.sb-label{font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:1.2px;padding:10px 18px 4px}
.sb-item{display:flex;align-items:center;gap:10px;padding:9px 18px;color:var(--sidebar-text);text-decoration:none;font-size:13.5px;font-weight:500;border-radius:8px;margin:1px 8px;transition:all .2s}
.sb-item:hover{background:var(--sidebar-hover);color:#f1f5f9}
.sb-item.active{background:var(--sidebar-active);color:#60a5fa;font-weight:600}
.sb-item .si{font-size:16px;width:22px;text-align:center;flex-shrink:0}
.sb-badge{margin-left:auto;background:#ef4444;color:white;font-size:10px;font-weight:700;padding:1px 6px;border-radius:999px}
.sb-footer{padding:14px 18px;border-top:1px solid rgba(255,255,255,.08);margin-top:auto}
.sb-footer .sf-text{font-size:11px;color:#475569;line-height:1.5}

/* ============ MAIN AREA ============ */
#main-wrap{margin-left:var(--sidebar-w);flex:1;display:flex;flex-direction:column;min-height:100vh;transition:margin-left .3s}
#main-wrap.expanded{margin-left:0}

/* ============ TOPBAR ============ */
#topbar{background:var(--topbar-bg);box-shadow:var(--topbar-shadow);padding:0 20px;height:56px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:500;gap:14px}
.tb-left{display:flex;align-items:center;gap:12px}
#sidebar-toggle{background:none;border:none;cursor:pointer;padding:6px;border-radius:8px;color:var(--text);font-size:20px;display:flex;align-items:center}
#sidebar-toggle:hover{background:var(--border)}
.tb-page-title{font-size:16px;font-weight:700;color:var(--text)}
.tb-right{display:flex;align-items:center;gap:10px}
.tb-search{position:relative}
.tb-search input{padding:7px 12px 7px 34px;border:1px solid var(--input-border);border-radius:20px;font-size:13px;background:var(--input-bg);color:var(--text);width:220px}
.tb-search::before{content:"🔍";position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:13px}
.tb-btn{background:none;border:1px solid var(--border);border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer;color:var(--text);display:flex;align-items:center;gap:5px}
.tb-btn:hover{background:var(--border)}
.tb-user{display:flex;align-items:center;gap:8px;padding:5px 10px;border-radius:8px;border:1px solid var(--border);font-size:13px;font-weight:600}
.tb-user .avatar{width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#6366f1);display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:13px}

/* ============ PAGE CONTENT ============ */
#page-content{padding:20px;flex:1}
.page-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:10px}
.page-header h2{font-size:22px;font-weight:800;color:var(--heading)}
.page-header p{font-size:13px;color:var(--text-muted);margin-top:2px}
.breadcrumb{font-size:12px;color:var(--text-muted);margin-bottom:4px}
.breadcrumb a{color:var(--btn-primary);text-decoration:none}

/* ============ CARDS ============ */
.card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);padding:20px;border:1px solid var(--border)}
.card h3{font-size:15px;font-weight:700;color:var(--heading);margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--border)}
.card-grid{display:grid;gap:16px}
.card-grid-2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.card-grid-3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card-grid-4{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}

/* ============ STAT CARDS ============ */
.stat-card{background:var(--card-bg);border-radius:var(--card-radius);padding:18px 20px;box-shadow:var(--card-shadow);border:1px solid var(--border);display:flex;align-items:flex-start;gap:14px}
.stat-icon{width:46px;height:46px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.stat-icon.blue{background:#dbeafe}
.stat-icon.green{background:#dcfce7}
.stat-icon.red{background:#fee2e2}
.stat-icon.yellow{background:#fef9c3}
.stat-icon.purple{background:#f3e8ff}
.stat-icon.orange{background:#ffedd5}
.stat-body .stat-label{font-size:12px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.stat-body .stat-value{font-size:22px;font-weight:800;color:var(--text);margin-top:2px}
.stat-body .stat-sub{font-size:12px;color:var(--text-muted);margin-top:3px}
.stat-body .stat-up{color:#16a34a;font-weight:600}
.stat-body .stat-down{color:#dc2626;font-weight:600}

/* ============ BUTTONS ============ */
.btn{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;border:none;border-radius:10px;cursor:pointer;font-size:13.5px;font-weight:700;text-decoration:none;white-space:nowrap;
  transition:transform .1s ease, box-shadow .1s ease, filter .15s ease;
  box-shadow:0 4px 0 rgba(0,0,0,.28), 0 6px 10px rgba(0,0,0,.16);
  position:relative; top:0;}
.btn:hover{filter:brightness(1.1) saturate(1.15);}
.btn:active{transform:translateY(4px); box-shadow:0 0 0 rgba(0,0,0,.28), 0 1px 2px rgba(0,0,0,.12); filter:brightness(.92);}
.btn-primary{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:white}
.btn-success{background:linear-gradient(135deg,#22c55e,#16a34a);color:white}
.btn-danger{background:linear-gradient(135deg,#ef4444,#dc2626);color:white}
.btn-warning{background:linear-gradient(135deg,#f59e0b,#d97706);color:white}
.btn-secondary{background:linear-gradient(135deg,#64748b,#475569);color:white}
.btn-outline{background:var(--card-bg);border:1.5px solid var(--btn-primary);color:var(--btn-primary); box-shadow:0 3px 0 var(--btn-primary), 0 5px 8px rgba(0,0,0,.1);}
.btn-outline:active{box-shadow:0 0 0 var(--btn-primary), 0 1px 2px rgba(0,0,0,.08);}
.btn-sm{padding:6px 12px;font-size:12px; box-shadow:0 3px 0 rgba(0,0,0,.24), 0 4px 6px rgba(0,0,0,.14);}
.btn-lg{padding:14px 32px;font-size:15px; box-shadow:0 5px 0 rgba(0,0,0,.3), 0 7px 12px rgba(0,0,0,.2);}
.btn-icon{padding:8px 12px}

/* ============ FORMS ============ */
.form-group{margin-bottom:14px}
.form-label{font-size:12.5px;font-weight:600;color:var(--text-muted);margin-bottom:5px;display:block;text-transform:uppercase;letter-spacing:.4px}
.form-control{width:100%;padding:9px 12px;border:1.5px solid var(--input-border);border-radius:9px;font-size:14px;background:var(--input-bg);color:var(--text);transition:border .2s}
.form-control:focus{outline:none;border-color:var(--btn-primary);box-shadow:0 0 0 3px rgba(37,99,235,.1)}
.form-row{display:grid;gap:12px}
.form-row-2{grid-template-columns:1fr 1fr}
.form-row-3{grid-template-columns:1fr 1fr 1fr}
.form-row-4{grid-template-columns:1fr 1fr 1fr 1fr}
select.form-control{cursor:pointer}

/* ============ TABLES ============ */
.table-wrap{overflow-x:auto;border-radius:var(--card-radius);border:1px solid var(--border)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
thead tr{background:linear-gradient(135deg,#0d3b34,#0f5c52);color:white}
thead th{padding:11px 13px;text-align:left;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}
tbody tr{border-bottom:1px solid var(--border);transition:background .15s}
tbody tr:hover{background:rgba(59,130,246,.04)}
tbody tr:last-child{border-bottom:none}
tbody td{padding:10px 13px;color:var(--text);vertical-align:middle}
tbody tr:nth-child(even){background:rgba(0,0,0,.012)}

/* ============ BADGES ============ */
.badge{display:inline-flex;align-items:center;padding:3px 9px;border-radius:999px;font-size:11px;font-weight:700}
.badge-blue{background:var(--badge-blue);color:var(--badge-blue-text)}
.badge-green{background:var(--badge-green);color:var(--badge-green-text)}
.badge-red{background:var(--badge-red);color:var(--badge-red-text)}
.badge-yellow{background:var(--badge-yellow);color:var(--badge-yellow-text)}
.badge-purple{background:var(--badge-purple);color:var(--badge-purple-text)}

/* ============ ALERTS ============ */
.alert{padding:11px 16px;border-radius:10px;font-size:13.5px;margin-bottom:14px;border-left:4px solid}
.alert-success{background:var(--notice-bg);border-color:#22c55e;color:var(--notice-text)}
.alert-error{background:var(--error-bg);border-color:#ef4444;color:var(--error-text)}
.alert-warning{background:#fffbeb;border-color:#f59e0b;color:#92400e}
.alert-info{background:#eff6ff;border-color:#3b82f6;color:#1e40af}
.notice{background:var(--notice-bg);border:1px solid var(--notice-border);padding:10px 14px;border-radius:9px;color:var(--notice-text);margin-bottom:12px}

/* ============ MISC ============ */
.flex{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}
.flex-center{justify-content:center;align-items:center}
.flex-between{justify-content:space-between}
.sep{border:none;border-top:1px solid var(--border);margin:16px 0}
.text-right{text-align:right}
.text-center{text-align:center}
.fw-bold{font-weight:700}
.text-muted{color:var(--text-muted)}
.text-success{color:#16a34a}
.text-danger{color:#dc2626}
.text-primary{color:#2563eb}
.mt-1{margin-top:6px}.mt-2{margin-top:12px}.mt-3{margin-top:20px}
.mb-1{margin-bottom:6px}.mb-2{margin-bottom:12px}.mb-3{margin-bottom:20px}
.p-0{padding:0}
.gap-1{gap:6px}.gap-2{gap:12px}
input[type=date].form-control{cursor:pointer}
.filter-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:var(--card-bg);padding:12px 16px;border-radius:10px;border:1px solid var(--border);margin-bottom:16px}
.search-box{position:relative;flex:1;min-width:180px}
.search-box input{width:100%;padding-left:32px}
.search-box::before{content:"🔍";position:absolute;left:9px;top:50%;transform:translateY(-50%);font-size:13px;pointer-events:none}
.price-type-badge{padding:4px 10px;border-radius:6px;font-size:11px;font-weight:700}
.price-type-w{background:#e0e7ff;color:#4338ca}
.price-type-d{background:#f3e8ff;color:#7e22ce}
.price-type-c{background:#ccfbf1;color:#0f766e}
@media(max-width:768px){
  #sidebar{transform:translateX(-100%)}
  #sidebar.mobile-open{transform:translateX(0)}
  #main-wrap{margin-left:0}
  .form-row-2,.form-row-3,.form-row-4{grid-template-columns:1fr}
  .tb-search{display:none}
}
</style>

<!-- ============ SIDEBAR ============ -->
<div id="sidebar">
  <div class="sb-brand">
    <div class="brand-name">⚡ {{project}}</div>
    <div class="brand-sub">Enterprise Business Pro</div>
  </div>

  <div class="sb-section">
    <div class="sb-label">Main</div>
    <a class="sb-item" href="{{url_for('home')}}"><span class="si">🏠</span> Dashboard</a>
    <a class="sb-item" href="{{url_for('new_invoice')}}"><span class="si">➕</span> New Invoice</a>
    <a class="sb-item" href="{{url_for('invoices_list')}}"><span class="si">📄</span> All Invoices</a>
    <a class="sb-item" href="{{url_for('new_delivery_note')}}"><span class="si">🚚</span> Delivery Note</a>
    <a class="sb-item" href="{{url_for('recycle_bin')}}"><span class="si">🗑️</span> Recycle Bin</a>
    <a class="sb-item" href="{{url_for('payments')}}"><span class="si">💳</span> Payments</a>
    <a class="sb-item" href="{{url_for('customer_ledger')}}"><span class="si">📒</span> Customer Ledger</a>
  </div>

  <div class="sb-section">
    <div class="sb-label">Inventory</div>
    <a class="sb-item" href="{{url_for('stock_entry')}}"><span class="si">🏭</span> Stock Entry</a>
    <a class="sb-item" href="{{url_for('products')}}"><span class="si">📦</span> Products</a>
    <a class="sb-item" href="{{url_for('stock_summary')}}"><span class="si">📊</span> Stock Summary</a>
  </div>

  <div class="sb-section">
    <div class="sb-label">Contacts</div>
    <a class="sb-item" href="{{url_for('customers')}}"><span class="si">👥</span> Customers</a>
    <a class="sb-item" href="{{url_for('salesmen')}}"><span class="si">🤝</span> Salesmen</a>
  </div>

  <div class="sb-section">
    <div class="sb-label">Finance</div>
    <a class="sb-item" href="{{url_for('profit_loss')}}"><span class="si">📈</span> Profit & Loss</a>
    <a class="sb-item" href="{{url_for('expenses')}}"><span class="si">💸</span> Expenses</a>
    <a class="sb-item" href="{{url_for('other_expenses')}}"><span class="si">🧾</span> Other Expenses</a>
  </div>

  <div class="sb-section">
    <div class="sb-label">Analytics</div>
    <a class="sb-item" href="{{url_for('sales_record')}}"><span class="si">📉</span> Sales Record</a>
    <a class="sb-item" href="{{url_for('reports')}}"><span class="si">📋</span> Reports</a>
    <a class="sb-item" href="{{url_for('target')}}"><span class="si">🎯</span> Targets</a>
    <a class="sb-item" href="{{url_for('market_analysis')}}"><span class="si">🔬</span> Market Analysis</a>
    <a class="sb-item" href="{{url_for('sales_history')}}"><span class="si">🗓️</span> Sales History</a>
  </div>
<a class="sb-item" href="{{url_for('factory_dashboard')}}"><span class="si">🏭</span> Factory</a>
  <div class="sb-section">
    <div class="sb-label">System</div>
    <a class="sb-item" href="{{url_for('settings')}}"><span class="si">⚙️</span> Settings</a>
    <a class="sb-item" href="{{url_for('backup_restore')}}"><span class="si">💾</span> Backup</a>
    <a class="sb-item" href="{{url_for('logout')}}"><span class="si">🚪</span> Logout</a>
  </div>

  <div class="sb-footer">
    <div class="sf-text">Smart Invoice Enterprise<br>© 2025 ISHTIAQ AHMAD MAGRAY</div>
  </div>
</div>

<!-- ============ MAIN WRAP ============ -->
<div id="main-wrap">

<!-- TOPBAR -->
<div id="topbar">
  <div class="tb-left">
    <button id="sidebar-toggle" onclick="toggleSidebar()">☰</button>
    <div class="tb-page-title" id="page-title-bar">{{project}}</div>
  </div>
  <div class="tb-right">
    <button class="tb-btn" id="themeToggle" onclick="toggleTheme()">🌙</button>
    <div id="topbarPageMenu"></div>
    <div class="tb-user">
      <div class="avatar">A</div>
      <span style="font-size:13px">Admin</span>
    </div>
  </div>
</div>

<!-- FLASH MESSAGES -->
{% with m=get_flashed_messages() %}
{% if m %}
<script>
    window.onload = function() {
        const messages = {{ get_flashed_messages() | tojson | safe }};
        messages.forEach(msg => {
            if (msg) {
                const popup = document.createElement('div');
                popup.style.cssText = `
                    position: fixed; 
                    top: 70px; 
                    left: 50%; 
                    transform: translateX(-50%);
                    background: #d32f2f; 
                    color: white; 
                    padding: 18px 35px; 
                    border-radius: 12px; 
                    box-shadow: 0 10px 35px rgba(211, 47, 47, 0.5);
                    font-size: 16.5px; 
                    font-weight: bold; 
                    z-index: 99999; 
                    text-align: center;
                    max-width: 85%;
                    border: 3px solid #fff;
                    animation: slideDown 0.4s ease;
                `;
                popup.innerHTML = '⚠️ ' + msg;
                document.body.appendChild(popup);

                // 6 سیکنڈ بعد خود بند ہو جائے
                setTimeout(() => {
                    popup.style.opacity = "0";
                    popup.style.transition = "all 0.6s";
                    setTimeout(() => popup.remove(), 600);
                }, 6000);
            }
        });
    };
</script>
{% endif %}
{% endwith %}

<!-- PAGE CONTENT START -->
<div id="page-content">
"""

TPL_F = """
</div><!-- /page-content -->
</div><!-- /main-wrap -->

<script>
// ========== SIDEBAR TOGGLE ==========
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  const mw = document.getElementById('main-wrap');
  if (window.innerWidth <= 768) {
    sb.classList.toggle('mobile-open');
  } else {
    sb.classList.toggle('collapsed');
    mw.classList.toggle('expanded');
  }
}

// ========== THEME ==========
function toggleTheme() {
  const body = document.body;
  const btn = document.getElementById('themeToggle');
  body.classList.toggle('dark');
  const isDark = body.classList.contains('dark');
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
  btn.textContent = isDark ? '☀️' : '🌙';
}
(function(){
  if(localStorage.getItem('theme')==='dark'){
    document.body.classList.add('dark');
    const b=document.getElementById('themeToggle');
    if(b) b.textContent='☀️';
  }
})();

// ========== ACTIVE SIDEBAR ITEM ==========
(function(){
  const path = window.location.pathname;
  document.querySelectorAll('.sb-item').forEach(a => {
    if(a.getAttribute('href') === path) a.classList.add('active');
  });
})();

// ========== TITLE CASE INPUT ==========
function titleCaseInput(el){
  const pos = el.selectionStart;
  const v = el.value.replace(/[A-Za-z][^ ]*/g, t => t.charAt(0).toUpperCase()+t.substr(1).toLowerCase());
  if(el.value !== v){ el.value = v; try{el.setSelectionRange(pos,pos);}catch(e){} }
}
document.querySelectorAll('input[data-titlecase]').forEach(el=>{
  el.addEventListener('input',()=>titleCaseInput(el));
  el.addEventListener('blur',()=>titleCaseInput(el));
});

// ========== GLOBAL QUICK SEARCH ==========
function quickSearch(val){
  if(!val.trim()) return;
  const pages = [
    {name:'New Invoice', url:'/invoice/new'},
    {name:'All Invoices', url:'/invoices'},
    {name:'Products', url:'/products'},
    {name:'Customers', url:'/customers'},
    {name:'Salesmen', url:'/salesmen'},
    {name:'Payments', url:'/payments'},
    {name:'Stock Entry', url:'/stock_entry'},
    {name:'Reports', url:'/reports'},
    {name:'Target', url:'/target'},
    {name:'Market Analysis', url:'/market_analysis'},
    {name:'Settings', url:'/settings'},
    {name:'Backup', url:'/backup'},
  ];
  // future: show dropdown
}

// ========== PRINT PREVIEW ==========
function printPage(){
  window.print();
}
</script>
</body></html>
"""


# ---------- welcome page ----------

# ---------- Home ----------
@app.route("/")
@login_required
def home():
    now = datetime.datetime.now()
    cur_month = now.strftime("%B"); cur_year = now.year
    month_total = 0.0; month_invoices = 0
    total_pending = 0.0; total_customers = 0
    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT inv_no, date, customer, customer_address, customer_type, total, grand_total, pending_added, remarks
            FROM invoices
        """).fetchall()
    all_invoices = [
        {"inv_no": r[0], "date": r[1], "name": r[2], "address": r[3], "customer_type": r[4],
         "total": r[5], "grand_total": r[6], "pending_added": r[7], "remarks": r[8]}
        for r in _inv_rows
    ]
    all_customers = load_customers()
    all_products = load_products()
    payments_all = read_payments_db()
    # This month totals (grand_total = actual sale, excludes carried-forward pending)
    for r in all_invoices:
        d = r.get("date","")
        try:
            for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
                try: dt = datetime.datetime.strptime(d, fmt); break
                except: continue
            else: continue
            if dt.year == cur_year and dt.strftime("%B") == cur_month:
                gt = r.get("grand_total")
                month_total += float(gt) if gt not in (None, "") else float(r.get("total","0") or 0)
                month_invoices += 1
        except: continue
    # Total pending — SAME FIFO logic as Customer Ledger (real per-customer
    # invoice total minus FIFO-applied payments). Replaces the old
    # customer_pending SQLite table, which only tracked manual carry-forward
    # transfers and drifted out of sync with actual payments received.
    try:
        def _dpd(d):
            for fmt in ("%Y-%m-%d","%d-%m-%y","%d-%m-%Y"):
                try: return datetime.datetime.strptime(d, fmt)
                except: pass
            return datetime.datetime.min

        pay_by_inv = {}
        for p in payments_all:
            try:
                pay_by_inv.setdefault(int(p["inv_no"]), []).append(p)
            except: pass

        by_customer = {}
        for r in all_invoices:
            key = (to_caps(r.get("name","")), to_caps(r.get("address","")))
            by_customer.setdefault(key, []).append(r)

        total_pending = 0.0
        for _key, _invs in by_customer.items():
            _invs.sort(key=lambda r: _dpd(r.get("date","")))
            _pool = 0.0
            for r in _invs:
                try: _invn = int(r["inv_no"])
                except: continue
                for p in pay_by_inv.get(_invn, []):
                    _pool += float(p.get("amount","0") or 0)
            for r in _invs:
                try: _invn = int(r["inv_no"])
                except: continue
                gt = r.get("grand_total")
                if gt not in (None, ""):
                    _inv_total = float(gt)
                else:
                    _inv_total = max(float(r.get("total","0") or 0) - float(r.get("pending_added","0") or 0), 0.0)
                if str(r.get("remarks","")).startswith("Pending Transferred to Inv #"):
                    continue  # settled via transfer, debt lives in destination invoice
                _rcvd = min(_inv_total, _pool)
                _pool -= _rcvd
                total_pending += max(_inv_total - _rcvd, 0.0)
    except Exception as e:
        print("Dashboard total_pending calc error:", e)
        total_pending = 0.0

    total_customers = len(all_customers)
    low_stock = [p for p in all_products if p["stock"] <= p["min_stock"] and p["min_stock"] > 0]

    # This month payments received
    month_received = 0.0
    for p in payments_all:
        d = p.get("date","")
        try:
            for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
                try: dt = datetime.datetime.strptime(d, fmt); break
                except: continue
            else: continue
            if dt.year == cur_year and dt.strftime("%B") == cur_month:
                month_received += float(p.get("amount","0") or 0)
        except: continue

    # Today's Sale + Today's Expense
    today_str_variants = set()
    for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
        today_str_variants.add(now.strftime(fmt))

    today_sale = 0.0
    for r in all_invoices:
        if r.get("date","") in today_str_variants:
            gt = r.get("grand_total")
            today_sale += float(gt) if gt not in (None, "") else float(r.get("total","0") or 0)

    today_expense = 0.0
    try:
        with db_transaction() as _c:
            _exp1 = _c.execute("SELECT date, amount FROM expenses").fetchall()
            _exp2 = _c.execute("SELECT date, amount FROM other_expenses").fetchall()
        for d, amt in (list(_exp1) + list(_exp2)):
            if (d or "") in today_str_variants:
                today_expense += float(amt or 0)
    except Exception as e:
        print("Today expense calc error:", e)

    today_received = 0.0
    for p in payments_all:
        if p.get("date","") in today_str_variants:
            today_received += float(p.get("amount","0") or 0)

    today_pending = max(0.0, today_sale - today_received)

    # Last 5 invoices
    recent_inv = sorted(all_invoices, key=lambda x: x.get("date",""), reverse=True)[:5]
    company = get_setting("company_name","SEIZE")

    html = TPL_H + """
<div class="page-header">
  <div>
    <div class="breadcrumb">Dashboard</div>
    <h2>📊 Business Dashboard</h2>
    <p>Welcome to {{company}} — {{cur_month}} {{cur_year}}</p>
  </div>
  <div class="flex">
    <a href="{{url_for('new_invoice')}}" class="btn btn-primary">➕ New Invoice</a>
    <a href="{{url_for('reports')}}" class="btn btn-outline">📋 Reports</a>
  </div>
</div>

<style>
.dash-stat{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);padding:18px 20px;display:flex;align-items:center;gap:14px}
.dash-stat .ic{width:48px;height:48px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;color:white}
.dash-stat .lbl{font-size:11.5px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px}
.dash-stat .val{font-size:21px;font-weight:800;color:var(--text);margin-top:2px}
.dash-stat .sub{font-size:11.5px;color:var(--text-muted);margin-top:2px}
</style>

<!-- TODAY ROW -->
<div class="card-grid card-grid-4 mb-2">
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#0d9488,#0f766e)">🟢</div>
    <div>
      <div class="lbl">Today's Sale</div>
      <div class="val">Rs {{today_sale}}</div>
      <div class="sub">Invoices dated today</div>
    </div>
  </div>
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#4f46e5,#4338ca)">💵</div>
    <div>
      <div class="lbl">Today's Received</div>
      <div class="val">Rs {{today_received}}</div>
      <div class="sub">Payments collected today</div>
    </div>
  </div>
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#f5a524,#d97706)">⏳</div>
    <div>
      <div class="lbl">Today's Pending</div>
      <div class="val" style="color:#d97706">Rs {{today_pending}}</div>
      <div class="sub">From today's unpaid sales</div>
    </div>
  </div>
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#e11d48,#be123c)">🔴</div>
    <div>
      <div class="lbl">Today's Expense</div>
      <div class="val">Rs {{today_expense}}</div>
      <div class="sub">Expenses dated today</div>
    </div>
  </div>
</div>

<!-- MONTH ROW -->
<div class="card-grid card-grid-4 mb-3">
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#4f46e5,#4338ca)">💰</div>
    <div>
      <div class="lbl">Month Sales</div>
      <div class="val">Rs {{month_total}}</div>
      <div class="sub">{{month_invoices}} invoices this month</div>
    </div>
  </div>
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#0d9488,#0f766e)">✅</div>
    <div>
      <div class="lbl">Received</div>
      <div class="val">Rs {{month_received}}</div>
      <div class="sub">Payments collected</div>
    </div>
  </div>
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#e11d48,#be123c)">⏳</div>
    <div>
      <div class="lbl">Total Pending</div>
      <div class="val" style="color:#e11d48">Rs {{total_pending}}</div>
      <div class="sub">Outstanding balance</div>
    </div>
  </div>
  <div class="dash-stat">
    <div class="ic" style="background:linear-gradient(135deg,#f5a524,#d97706)">👥</div>
    <div>
      <div class="lbl">Customers</div>
      <div class="val">{{total_customers}}</div>
      <div class="sub">Registered accounts</div>
    </div>
  </div>
</div>

<!-- QUICK ACCESS + RECENT INVOICES -->
<div class="card-grid card-grid-2 mb-3">
  <!-- Quick Access -->
  <div class="card">
    <h3>⚡ Quick Access</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
      <a href="{{url_for('new_invoice')}}" class="btn btn-primary" style="justify-content:center;padding:14px">
        ➕ New Invoice
      </a>
      <a href="{{url_for('payments')}}" class="btn btn-success" style="justify-content:center;padding:14px">
        💳 Payments
      </a>
      <a href="{{url_for('products')}}" class="btn btn-secondary" style="justify-content:center;padding:14px">
        📦 Products
      </a>
      <a href="{{url_for('customers')}}" class="btn btn-secondary" style="justify-content:center;padding:14px">
        👥 Customers
      </a>
      <a href="{{url_for('stock_entry')}}" class="btn btn-warning" style="justify-content:center;padding:14px">
        🏭 Stock Entry
      </a>
      <a href="{{url_for('target')}}" class="btn btn-outline" style="justify-content:center;padding:14px">
        🎯 Targets
      </a>
      <a href="{{url_for('salesmen')}}" class="btn btn-secondary" style="justify-content:center;padding:14px">
        🤝 Salesmen
      </a>
      <a href="{{url_for('market_analysis')}}" class="btn btn-primary" style="justify-content:center;padding:14px;background:#7c3aed">
        🔬 Analysis
      </a>
    </div>
    {% if low_stock %}
    <div class="alert alert-warning mt-2">
      ⚠️ <strong>{{low_stock|length}} product(s)</strong> are low on stock!
      <a href="{{url_for('stock_summary')}}" style="color:inherit;font-weight:700"> View →</a>
    </div>
    {% endif %}
  </div>

  <!-- Recent Invoices -->
  <div class="card p-0">
    <div style="padding:16px 18px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
      <h3 style="margin:0;border:none;padding:0">📄 Recent Invoices</h3>
      <a href="{{url_for('invoices_list')}}" class="btn btn-sm btn-outline">View All</a>
    </div>
    <table>
      <thead><tr><th>#</th><th>Customer</th><th>Amount</th><th>Type</th><th>Date</th></tr></thead>
      <tbody>
        {% for r in recent_inv %}
        <tr>
          <td><strong>#{{r.inv_no}}</strong></td>
          <td>{{r.name[:18]}}</td>
          <td class="fw-bold">Rs {{'{:,.0f}'.format(r.total|float)}}</td>
          <td>
            {% if r.get('customer_type','customer') == 'wholesaler' %}
              <span class="badge badge-blue">🏭 W</span>
            {% elif r.get('customer_type','customer') == 'distributor' %}
              <span class="badge badge-purple">🚚 D</span>
            {% else %}
              <span class="badge badge-green">🛒 C</span>
            {% endif %}
          </td>
          <td class="text-muted">{{r.date}}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<!-- ALL MODULES GRID -->
<div class="card mb-3">
  <h3>🗂️ All Modules</h3>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">
    {% set modules = [
      ('🏠','Dashboard',url_for('home')),
      ('➕','New Invoice',url_for('new_invoice')),
      ('📄','All Invoices',url_for('invoices_list')),
      ('💳','Payments',url_for('payments')),
      ('📒','Ledger',url_for('customer_ledger')),
      ('📦','Products',url_for('products')),
      ('🏭','Stock Entry',url_for('stock_entry')),
      ('📊','Stock Summary',url_for('stock_summary')),
      ('👥','Customers',url_for('customers')),
      ('🤝','Salesmen',url_for('salesmen')),
      ('📈','Profit & Loss',url_for('profit_loss')),
      ('💸','Expenses',url_for('expenses')),
      ('🧾','Other Expenses',url_for('other_expenses')),
      ('📉','Sales Record',url_for('sales_record')),
      ('📋','Reports',url_for('reports')),
      ('🎯','Targets',url_for('target')),
      ('🔬','Market Analysis',url_for('market_analysis')),
      ('🗓️','Sales History',url_for('sales_history')),
      ('⚙️','Settings',url_for('settings')),
      ('💾','Backup',url_for('backup_restore')),
    ] %}
    {% for icon, label, link in modules %}
    <a href="{{link}}" style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px 8px;background:var(--card-bg);border:1px solid var(--border);border-radius:12px;text-decoration:none;color:var(--text);transition:all .2s;gap:8px;font-size:13px;font-weight:600;text-align:center"
       onmouseover="this.style.background='var(--badge-blue)';this.style.transform='translateY(-2px)'"
       onmouseout="this.style.background='var(--card-bg)';this.style.transform='none'">
      <span style="font-size:24px">{{icon}}</span>{{label}}
    </a>
    {% endfor %}
  </div>
</div>

<p style="text-align:center;color:var(--text-muted);font-size:12px;padding:10px 0">
  © 2025 Smart Invoice Enterprise Pro | Developed by ISHTIAQ AHMAD MAGRAY | +923495820495
</p>
""" + TPL_F
    return render_template_string(html,
        project=get_setting("project_name"),
        company=company,
        cur_month=cur_month, cur_year=cur_year,
        month_total=f"{month_total:,.0f}",
        month_invoices=month_invoices,
        month_received=f"{month_received:,.0f}",
        total_pending=f"{total_pending:,.0f}",
        total_customers=total_customers,
        recent_inv=recent_inv,
        low_stock=low_stock
    )
@app.route("/products/template")
@login_required
def download_products_template():
    from io import BytesIO
    buf = BytesIO()
    buf.write(b"name,unit_price,purchase_price,wholesaler_price,distributor_price,customer_price,stock,min_stock\r\n")
    buf.write(b"Example Product,100,70,90,85,100,0,5\r\n")
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name="products_import_template.csv")


@app.route("/products/import", methods=["POST"])
@login_required
def import_products():
    file = request.files.get("import_file")
    if not file or file.filename == "":
        flash("Please choose a CSV file to import")
        return redirect(url_for("products"))

    try:
        content = file.stream.read().decode("utf-8-sig")
        reader = csv.DictReader(content.splitlines())

        imported = 0
        skipped = 0
        errors = []

        with db_transaction() as cur:
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    skipped += 1
                    continue
                try:
                    unit_price = float(row.get("unit_price") or 0)
                    purchase_price = float(row.get("purchase_price") or 0)
                    wholesaler_price = float(row.get("wholesaler_price") or 0) or unit_price
                    distributor_price = float(row.get("distributor_price") or 0) or unit_price
                    customer_price = float(row.get("customer_price") or 0) or unit_price
                    stock = float(row.get("stock") or 0)
                    min_stock = float(row.get("min_stock") or 0)

                    cur.execute("""
                        INSERT INTO products
                        (name, unit_price, purchase_price, wholesaler_price,
                         distributor_price, customer_price, stock, min_stock)
                        VALUES (?,?,?,?,?,?,?,?)
                        ON CONFLICT(name) DO UPDATE SET
                            unit_price=excluded.unit_price,
                            purchase_price=excluded.purchase_price,
                            wholesaler_price=excluded.wholesaler_price,
                            distributor_price=excluded.distributor_price,
                            customer_price=excluded.customer_price,
                            stock = stock + excluded.stock,
                            min_stock=excluded.min_stock
                    """, (name, unit_price, purchase_price, wholesaler_price,
                          distributor_price, customer_price, stock, min_stock))
                    imported += 1
                except Exception as row_err:
                    errors.append(f"{name}: {row_err}")
                    skipped += 1

        msg = f"Import complete: {imported} product(s) added/updated"
        if skipped:
            msg += f", {skipped} row(s) skipped"
        flash(msg)
        if errors:
            flash("Errors: " + "; ".join(errors[:5]))
    except Exception as e:
        flash(f"Import failed, no changes were made (safe rollback): {e}")

    return redirect(url_for("products"))


# ---------- Products ----------
@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    if request.method == "POST":
        act = request.form.get("action", "")

        if act == "save":
            name = to_caps(request.form.get("name", "").strip())
            if not name:
                flash("Product name required")
                return redirect(url_for("products"))

            sell_price_input = request.form.get("unit_price", "").strip()
            purchase_price_input = request.form.get("purchase_price", "").strip()
            wholesaler_price_input = request.form.get("wholesaler_price", "").strip()
            distributor_price_input = request.form.get("distributor_price", "").strip()
            customer_price_input = request.form.get("customer_price", "").strip()
            add_stock_input = request.form.get("stock", "0").strip()
            min_stock_input = request.form.get("min_stock", "0").strip()

            try:
                add_stock = max(0.0, float(add_stock_input or "0"))
                min_stock = max(0.0, float(min_stock_input or "0"))
            except:
                flash("Invalid stock values")
                return redirect(url_for("products"))

            try:
                with db_transaction() as cur:
                    sell_price = float(sell_price_input) if sell_price_input else 0
                    purchase_price = float(purchase_price_input) if purchase_price_input else 0
                    wholesaler_price = float(wholesaler_price_input) if wholesaler_price_input else sell_price
                    distributor_price = float(distributor_price_input) if distributor_price_input else sell_price
                    customer_price = float(customer_price_input) if customer_price_input else sell_price
# Check if product exists
                    exists = cur.execute("SELECT name FROM products WHERE name = ?", (name,)).fetchone()

                    if exists:
                        cur.execute("""
                            UPDATE products
                            SET unit_price=?,
                                purchase_price=?,
                                wholesaler_price=?,
                                distributor_price=?,
                                customer_price=?,
                                stock = stock + ?,
                                min_stock=?
                            WHERE name=?
                        """, (sell_price, purchase_price, wholesaler_price,
                              distributor_price, customer_price, add_stock, min_stock, name))
                    else:
                        cur.execute("""
                            INSERT INTO products
                            (name, unit_price, purchase_price, wholesaler_price,
                             distributor_price, customer_price, stock, min_stock)
                            VALUES (?,?,?,?,?,?,?,?)
                        """, (name, sell_price, purchase_price, wholesaler_price,
                              distributor_price, customer_price, add_stock, min_stock))

                    # Auto-sync into Stock Entry log + Stock Summary (only if stock was actually added)
                    if add_stock > 0:
                        cur.execute("""
                            INSERT INTO stock_entries
                                (date, product, qty, purchase_price, wholesaler_price,
                                 distributor_price, customer_price, month_key)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            datetime.date.today().strftime("%d-%m-%Y"), name, add_stock,
                            purchase_price, wholesaler_price, distributor_price, customer_price,
                            datetime.date.today().strftime("%B %Y")
                        ))

                if exists:
                    flash(f"Updated: {name}")
                else:
                    flash(f"New Product Added: {name}")
            except Exception as e:
                flash(f"Error saving product: {str(e)}")
                print("Product Save Error:", e)

            return redirect(url_for("products"))

        elif act == "delete":
            name_del = request.form.get("name_del", "").strip()
            if name_del:
                try:
                    with db_transaction() as cur:
                        cur.execute("DELETE FROM products WHERE name = ?", (name_del,))
                    flash(f"Product deleted: {name_del}")
                except Exception as e:
                    flash(f"Delete failed: {str(e)}")

            return redirect(url_for("products"))

    # GET request
    prods = load_products()

    html = TPL_H + """
<h3>📦 Products / Stock Management</h3>

<style>
.pmenu-wrap{position:relative;display:inline-block}
.pmenu-btn{background:var(--card-bg);border:1.5px solid var(--border);border-radius:9px;width:38px;height:38px;font-size:19px;cursor:pointer;color:var(--text)}
.pmenu-dropdown{display:none;position:absolute;right:0;top:44px;background:var(--card-bg);border:1px solid var(--border);border-radius:10px;box-shadow:var(--card-shadow);min-width:230px;z-index:900;overflow:hidden}
.pmenu-dropdown.open{display:block}
.pmenu-dropdown a,.pmenu-dropdown button{display:flex;align-items:center;gap:8px;width:100%;padding:12px 16px;background:none;border:none;text-align:left;font-size:13.5px;color:var(--text);cursor:pointer;text-decoration:none;box-shadow:none}
.pmenu-dropdown a:hover,.pmenu-dropdown button:hover{background:var(--body-bg)}
.pmenu-dropdown form{margin:0}
.pmenu-note{padding:10px 16px;font-size:11px;color:var(--text-muted);border-top:1px solid var(--border)}
</style>

<div style="margin:25px 0;">
  <input type="text" id="prodSearchBox" placeholder="🔍 Search product name..." 
         style="width:100%; max-width:500px; padding:14px; font-size:18px; border-radius:12px; border:2px solid var(--input-border);">
</div>

<div class="pmenu-wrap no-print" id="pmenuWrap" style="display:none;">
  <button type="button" class="pmenu-btn" onclick="document.getElementById('pmenuDD').classList.toggle('open')">⋮</button>
  <div class="pmenu-dropdown" id="pmenuDD">
    <label for="pmenuImportFile" style="cursor:pointer;">📥 Import CSV</label>
    <form method="post" action="{{ url_for('import_products') }}" enctype="multipart/form-data" id="pmenuImportForm">
      <input type="file" name="import_file" id="pmenuImportFile" accept=".csv" required
             style="display:none" onchange="document.getElementById('pmenuImportForm').submit()">
    </form>
    <a href="{{ url_for('download_products_template') }}">📄 Download Template</a>
    <button type="button" onclick="window.print()">🖨️ Print Product Sheet</button>
    <div class="pmenu-note">CSV columns: name, unit_price, purchase_price, wholesaler_price, distributor_price, customer_price, stock, min_stock</div>
  </div>
</div>

<script>
// Ye 3-dots menu ko topbar (Admin ke pass) mein move kar deta hai
(function(){
  const target = document.getElementById('topbarPageMenu');
  const source = document.getElementById('pmenuWrap');
  if(target && source){
    source.style.display = 'inline-block';
    target.appendChild(source);
  }
  document.addEventListener('click', function(e){
    const wrap = document.getElementById('pmenuWrap');
    const dd = document.getElementById('pmenuDD');
    if(wrap && dd && !wrap.contains(e.target)) dd.classList.remove('open');
  });
})();
</script>

<style>
.pc-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);padding:0;margin-bottom:30px;overflow:hidden}
.pc-header{background:linear-gradient(135deg,#0d3b34,#0f5c52);color:white;padding:16px 26px;font-size:17px;font-weight:800;display:flex;align-items:center;gap:10px}
.pc-body{padding:26px}
.pc-body label{font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:5px}
.pc-body input{width:100%;padding:10px 12px;border:1.5px solid var(--input-border);border-radius:9px;font-size:14px;background:var(--input-bg);color:var(--text);transition:border .15s, box-shadow .15s;box-sizing:border-box}
.pc-body input:focus{outline:none;border-color:var(--btn-primary);box-shadow:0 0 0 3px rgba(79,70,229,.12)}
</style>

<form method="post">
  <input type="hidden" name="action" value="save">
  <div class="pc-card">
    <div class="pc-header">📦 Add / Update Product</div>
    <div class="pc-body">
    <div style="display:grid; grid-template-columns: 280px 130px 130px 130px 130px 130px 130px 120px auto; gap:14px; align-items:end;">
      <div>
        <label>Product Name</label>
        <input name="name" id="pname" list="prodlist" placeholder="Type or select" required autocomplete="off">
        <datalist id="prodlist">
          {% for p in prods %}
            <option value="{{p.name}}" 
                    data-purchase="{{p.purchase_price}}" 
                    data-wp="{{p.wholesaler_price}}" 
                    data-dp="{{p.distributor_price}}" 
                    data-cp="{{p.customer_price}}">
          {% endfor %}
        </datalist>
      </div>
      <div><label>Purchase Price</label>
        <input name="purchase_price" id="purchase_price" type="number" step="any" placeholder="Cost">
      </div>
      <div><label>🏭 Wholesaler</label>
        <input name="wholesaler_price" id="wholesaler_price" type="number" step="any" placeholder="Wholesale" style="background:#e0e7ff;">
      </div>
      <div><label>🚚 Distributor</label>
        <input name="distributor_price" id="distributor_price" type="number" step="any" placeholder="Distributor" style="background:#f3e8ff;">
      </div>
      <div><label>🛒 Customer</label>
        <input name="customer_price" id="customer_price" type="number" step="any" placeholder="Customer" style="background:#ccfbf1;">
      </div>
      <div><label>Add Stock</label>
        <input name="stock" type="number" step="any" min="0" value="0">
      </div>
      <div><label>Min Stock</label>
        <input name="min_stock" type="number" step="any" min="0">
      </div>
    </div>
    <div style="text-align:center; margin-top:26px;">
      <button type="submit" class="btn btn-success btn-lg">
        💾 Save Product / Update Stock
      </button>
    </div>
    </div>
  </div>
</form>
<style>
@media print {
  .no-print, .no-print *, #prodSearchBox, .sb-item, #sidebar, #topbar,
  .page-header a, form, button, .btn, input, select, textarea { display:none !important; }
  #main-wrap { margin-left:0 !important; }
  #prodTable { display:table !important; }
  #prodTable * { display:revert !important; }
  /* Sirf Sr#, Product, Purchase, Wholesale, Distributor, Customer print hon —
     Stock, Min Stock, Status, Action hide hon (columns 7,8,9,10) */
  #prodTable th:nth-child(7), #prodTable td:nth-child(7),
  #prodTable th:nth-child(8), #prodTable td:nth-child(8),
  #prodTable th:nth-child(9), #prodTable td:nth-child(9),
  #prodTable th:nth-child(10), #prodTable td:nth-child(10) { display:none !important; }
}
</style>
<table id="prodTable" class="table-wrap" style="width:100%">
  <thead>
    <tr>
      <th>Sr#</th>
      <th>Product</th>
      <th>Purchase</th>
      <th>🏭 Wholesale</th>
      <th>🚚 Distributor</th>
      <th>🛒 Customer</th>
      <th>Stock</th>
      <th>Min Stock</th>
      <th>Status</th>
      <th>Action</th>
    </tr>
  </thead>
  <tbody>
    {% for p in prods %}
    <tr {% if p.min_stock > 0 and p.stock <= p.min_stock %}style="background:#ffebee;"{% endif %}>
      <td style="text-align:center;color:var(--text-muted);font-weight:600;">{{loop.index}}</td>
      <td style="font-weight:600;">{{p.name}}</td>
      <td>Rs {{'%.0f'|format(p.purchase_price or 0)}}</td>
      <td style="background:#e3f2fd;">Rs {{'%.0f'|format(p.wholesaler_price or 0)}}</td>
      <td style="background:#f3e5f5;">Rs {{'%.0f'|format(p.distributor_price or 0)}}</td>
      <td style="background:#e8f5e9;">Rs {{'%.0f'|format(p.customer_price or 0)}}</td>
      <td style="text-align:center;font-weight:bold;color:#1e40af;">{{'%.2f'|format(p.stock)}}</td>
      <td style="text-align:center;">{{'%.0f'|format(p.min_stock)}}</td>
      <td style="text-align:center;">
        {% if p.min_stock > 0 and p.stock <= p.min_stock %}<span class="badge badge-red">🔴 LOW</span>
        {% elif p.min_stock > 0 and p.stock <= p.min_stock * 1.5 %}<span class="badge badge-yellow">🟡 Low</span>
        {% else %}<span class="badge badge-green">✅ OK</span>{% endif %}
      </td>
      <td>
        <form method="post" style="display:inline;">
          <input type="hidden" name="action" value="delete">
          <input type="hidden" name="name_del" value="{{p.name}}">
          <button class="btn btn-sm btn-danger" onclick="return confirm('Delete {{p.name}}? This action cannot be undone.')">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<script>
document.getElementById('prodSearchBox').addEventListener('input', function() {
  const query = this.value.toLowerCase().trim();
  const rows = document.querySelectorAll('#prodTable tbody tr');
  rows.forEach(row => {
    const productName = row.querySelector('td:first-child').textContent.toLowerCase();
    row.style.display = (query === '' || productName.includes(query)) ? '' : 'none';
  });
});

// Auto-fill prices when selecting from datalist
document.getElementById('pname').addEventListener('input', function() {
  const val = this.value.trim().toLowerCase();
  if (!val) return;
  const opts = document.querySelectorAll('#prodlist option');
  for (let opt of opts) {
    if (opt.value.toLowerCase() === val) {
      document.getElementById('purchase_price').value = opt.dataset.purchase || '';
      document.getElementById('wholesaler_price').value = opt.dataset.wp || '';
      document.getElementById('distributor_price').value = opt.dataset.dp || '';
      document.getElementById('customer_price').value = opt.dataset.cp || '';
      return;
    }
  }
});
</script>
""" + TPL_F

    return render_template_string(html, prods=prods, project=get_setting("project_name"))

# ---------- Customers ----------
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        act = request.form.get("action", "save")

        if act == "save":
            name = to_caps(request.form.get("name", "").strip())
            addr = to_caps(request.form.get("address", "").strip())
            phone = request.form.get("phone", "").strip()
            joined = request.form.get("joined_date", "").strip()

            if not joined:
                joined = datetime.date.today().strftime("%d-%m-%Y")
            else:
                try:
                    joined = datetime.datetime.strptime(joined, "%Y-%m-%d").strftime("%d-%m-%Y")
                except:
                    pass

            if not name or not addr:
                flash("Name and Address are required")
                return redirect(url_for("customers"))

            try:
                with db_transaction() as cur:
                    cur.execute("""
                        INSERT INTO customers (name, address, phone, joined_date)
                        VALUES (?,?,?,?)
                        ON CONFLICT(name, address) 
                        DO UPDATE SET 
                            phone = excluded.phone,
                            joined_date = COALESCE(excluded.joined_date, customers.joined_date)
                    """, (name, addr, phone, joined))
                flash(f"'{name}' saved successfully")
            except Exception as e:
                flash(f"Error saving customer: {str(e)}")
                print("Customer Save Error:", e)

            return redirect(url_for("customers"))

        elif act == "delete":
            name_del = to_caps(request.form.get("name_del", ""))
            addr_del = to_caps(request.form.get("addr_del", ""))

            if name_del and addr_del:
                try:
                    with db_transaction() as cur:
                        cur.execute("DELETE FROM customers WHERE name = ? AND address = ?", 
                                   (name_del, addr_del))
                    flash(f"Customer deleted: {name_del}")
                except Exception as e:
                    flash(f"Delete failed: {str(e)}")

            return redirect(url_for("customers"))

    # GET - Load from SQLite
    custs = load_customers()

    # Stats (ab SQLite se)
    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT customer, customer_address, date, grand_total, total
            FROM invoices
        """).fetchall()
    all_inv = [
        {"name": r[0], "address": r[1], "date": r[2], "grand_total": r[3], "total": r[4]}
        for r in _inv_rows
    ]
    cust_stats = {}
    for inv in all_inv:
        k = (to_caps(inv.get("name","")), to_caps(inv.get("address","")))
        if k not in cust_stats:
            cust_stats[k] = {"count": 0, "total": 0.0, "last_date": ""}
        cust_stats[k]["count"] += 1
        try:
            cust_stats[k]["total"] += float(inv.get("grand_total") or inv.get("total","0") or 0)
        except:
            pass
        d = inv.get("date","")
        if d > cust_stats[k]["last_date"]:
            cust_stats[k]["last_date"] = d

    today_d = datetime.date.today()
    def _parse_joined(d):
        for fmt in ("%d-%m-%Y","%d-%m-%y","%Y-%m-%d"):
            try: return datetime.datetime.strptime(d, fmt).date()
            except: pass
        return None

    new_this_month = []
    stale_no_invoice = []
    for c in custs:
        jd = _parse_joined(c.get("joined_date",""))
        if not jd:
            continue
        k = (to_caps(c.get("name","")), to_caps(c.get("address","")))
        stat = cust_stats.get(k, {"count": 0, "total": 0.0, "last_date": ""})
        if jd.year == today_d.year and jd.month == today_d.month:
            new_this_month.append(c)
        elif (today_d - jd).days > 30 and stat.get("count", 0) == 0:
            stale_no_invoice.append(c)

    import json as _json
    custs_json = _json.dumps([{"name": c["name"], "address": c["address"]} for c in custs])

    html = TPL_H + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="/">Dashboard</a> › Customers</div>
    <h2>👥 Customers</h2>
    <p class="text-muted">{{custs|length}} registered customers</p>
  </div>
</div>

{% if new_this_month %}
<div class="card mb-3" style="border-left:4px solid #16a34a">
  <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
    <h3 style="margin:0;border:none;padding:0">🆕 New Customers This Month</h3>
    <span class="badge badge-green">{{new_this_month|length}}</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Address</th><th>Phone</th><th>Joined</th><th>Ledger</th></tr></thead>
      <tbody>
        {% for c in new_this_month %}
        <tr>
          <td class="fw-bold">{{c.name}}</td>
          <td class="text-muted">{{c.address}}</td>
          <td>{{c.phone or '—'}}</td>
          <td><span class="badge badge-blue">📅 {{c.joined_date}}</span></td>
          <td><a class="btn btn-sm btn-outline" href="{{ url_for('customer_ledger', name=c.name, address=c.address) }}">📒 Ledger</a></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}

{% if stale_no_invoice %}
<div class="card mb-3" style="border-left:4px solid #e67e22">
  <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
    <h3 style="margin:0;border:none;padding:0">⚠️ No Invoice Yet (30+ Days Since Joining)</h3>
    <span class="badge" style="background:#fef3c7;color:#92400e">{{stale_no_invoice|length}}</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Address</th><th>Phone</th><th>Joined</th><th>New Invoice</th></tr></thead>
      <tbody>
        {% for c in stale_no_invoice %}
        <tr>
          <td class="fw-bold">{{c.name}}</td>
          <td class="text-muted">{{c.address}}</td>
          <td>{{c.phone or '—'}}</td>
          <td><span class="badge badge-blue">📅 {{c.joined_date}}</span></td>
          <td><a class="btn btn-sm btn-primary" href="{{ url_for('invoice_new') }}">➕ Create Invoice</a></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}

<div class="card mb-3">
  <h3>➕ Add / Update Customer</h3>
  <form method="post">
    <input type="hidden" name="action" value="save">
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Customer Name *</label>
        <input name="name" id="cn_inp" class="form-control" list="cn_dl"
               placeholder="Full Name" required
               oninput="titleCaseInput(this);fillCA(this.value)">
        <datalist id="cn_dl">
          {% for c in custs %}<option value="{{c.name}}">{% endfor %}
        </datalist>
      </div>
      <div class="form-group">
        <label class="form-label">Address *</label>
        <input name="address" id="ca_inp" class="form-control" list="ca_dl"
               placeholder="City / Area" required oninput="titleCaseInput(this)">
        <datalist id="ca_dl">
          {% for c in custs %}<option value="{{c.address}}">{% endfor %}
        </datalist>
      </div>
      <div class="form-group">
        <label class="form-label">Phone</label>
        <input name="phone" class="form-control" placeholder="+92...">
      </div>
      <div class="form-group">
        <label class="form-label">Joining Date</label>
        <input name="joined_date" type="date" class="form-control" value="{{today}}">
      </div>
    </div>
    <button class="btn btn-primary">💾 Save Customer</button>
  </form>
</div>

<div class="filter-bar mb-2">
  <div class="search-box" style="flex:1">
    <input id="custSearch" class="form-control"
           placeholder="🔍 Search by name, address, phone...">
  </div>
</div>

<div class="card p-0">
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Customer Name + Address</th>
          <th>Phone</th>
          <th>Joined Date</th>
          <th style="text-align:right">Invoices</th>
          <th style="text-align:right">Total Sales</th>
          <th>Last Invoice</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody id="cust_tbody">
        {% for c in custs %}
        {% set st = cust_stats.get((c.name, c.address), {}) %}
        <tr class="cust-row">
          <td style="text-align:center;color:var(--text-muted);font-weight:600">{{loop.index}}</td>
          <td>
            <div style="font-weight:700;font-size:14px;color:var(--text)">{{c.name}}</div>
            <div style="font-size:12px;color:var(--text-muted);margin-top:2px">📍 {{c.address}}</div>
          </td>
          <td>{{c.phone or '—'}}</td>
          <td>
            {% if c.joined_date %}
              <span class="badge badge-blue">📅 {{c.joined_date}}</span>
            {% else %}
              <span class="text-muted">—</span>
            {% endif %}
          </td>
          <td style="text-align:right"><span class="badge badge-green">{{st.get('count',0)}}</span></td>
          <td style="text-align:right;font-weight:700;color:#1e40af">Rs {{'{:,.0f}'.format(st.get('total',0))}}</td>
          <td style="font-size:12px;color:var(--text-muted)">{{st.get('last_date','—')}}</td>
          <td>
            <div class="flex gap-1">
              <a class="btn btn-sm btn-outline" href="{{ url_for('customer_ledger', name=c.name, address=c.address) }}">📒 Ledger</a>
              <form method="post" style="display:inline">
                <input type="hidden" name="action" value="delete">
                <input type="hidden" name="name_del" value="{{c.name}}">
                <input type="hidden" name="addr_del" value="{{c.address}}">
                <button class="btn btn-sm btn-danger" onclick="return confirm('Delete {{c.name}}?')">🗑</button>
              </form>
            </div>
          </td>
        </tr>
        {% endfor %}
        {% if not custs %}
        <tr><td colspan="8" class="text-center text-muted" style="padding:40px">No customers yet.</td></tr>
        {% endif %}
      </tbody>
    </table>
  </div>
</div>

<script>
document.getElementById('custSearch').addEventListener('input', function(){
  const q = this.value.toLowerCase();
  document.querySelectorAll('.cust-row').forEach(row => {
    row.style.display = row.innerText.toLowerCase().includes(q) ? '' : 'none';
  });
});

const _custData = {{ custs_json|safe }};
function fillCA(name){
  const c = _custData.find(x => x.name.toLowerCase() === name.trim().toLowerCase());
  if(c) document.getElementById('ca_inp').value = c.address;
}
</script>
""" + TPL_F

    return render_template_string(html, custs=custs, cust_stats=cust_stats,
        today=datetime.date.today().isoformat(),
        custs_json=custs_json,
        project=get_setting("project_name"))

# ================== NEW & EDIT INVOICE - FINAL WORKING VERSION ==================
# ================= Check if editing an existing invoice =================
@app.route("/invoice/new", methods=["GET","POST"])
@login_required
def new_invoice():
    #today = datetime.date.today().isoformat()
    prods = load_products()
    custs = load_customers()
    company = get_setting("company_name","Smart Invoice")
    logo    = get_setting("logo_path","") or None
    show_logo = (get_setting("logo_show","1") == "1")
    tax_def = float(get_setting("tax_default","0") or "0")

    if request.method == "POST":
        name = to_caps(request.form.get("name",""))
        addr = to_caps(request.form.get("address",""))
        phone = request.form.get("phone","")
        tax_in = request.form.get("tax","")
        tax = float(tax_in) if tax_in != "" else tax_def

        # ===== PENDING CARRY-FORWARD SYSTEM =====
        pending_input = request.form.get("pending_amount", "").strip()
        from_inv_no   = request.form.get("pending_from_inv", "").strip()  # source invoice
        try:
            pending_added = float(pending_input) if pending_input else 0.0
        except:
            pending_added = 0.0

        # Auto-fill pending from settings (if enabled and user didn't enter)
        if get_setting("show_pending","0") == "1" and pending_added == 0.0:
            pending_added = get_pending(name, addr)

        # Duplicate check — if source invoice provided, block re-use
        pending_blocked = False
        if from_inv_no and pending_added > 0:
            already, dest = is_pending_already_transferred(from_inv_no)
            if already:
                flash(f"⛔ Pending from Invoice #{from_inv_no} already transferred to Invoice #{dest}. Duplicate blocked!")
                pending_added = 0.0
                pending_blocked = True
        # =========================================

        lines = []
        used = set()
        idx = 0
        err = None
        any_line = False
        while True:
            prod = request.form.get(f"prod_{idx}")
            qty  = request.form.get(f"qty_{idx}")
            price_in = request.form.get(f"u_{idx}")

            if not prod:
                break
            any_line = True
            if prod in used:
                err = f"'{prod}' already added"; break
            try:
                q = float(qty)
            except:
                q = 0.0
            try:
                unit_price = float(price_in)
            except:
                unit_price = None

            info = next((p for p in prods if p["name"] == prod), None)
            if not info:
                err = "Select product from list"; break
            if q <= 0:
                err = "Quantity must be positive"; break
            if unit_price is None:
                unit_price = float(info["unit_price"])

            if q > info["stock"]:
                err = f"Insufficient stock for '{prod}' (have {info['stock']})"; break
            lines.append({
    "product": prod,
    "qty": q,
    "unit_price": unit_price
})

            used.add(prod)
            idx += 1

        if not any_line:
            err = "Add at least one item"
        if err:
            flash(err); return redirect(url_for("new_invoice"))

        # ===== Invoice Number: Monthly (starts 101 each month), user can override =====
        # ===================== AUTO INVOICE NUMBER (FINAL) =====================
        custom_inv_no = request.form.get("inv_no_custom", "").strip()
        
        if custom_inv_no:
            try:
                inv_no = int(custom_inv_no)
                with db_transaction() as _c:
                    _exists = _c.execute("SELECT 1 FROM invoices WHERE inv_no=?", (str(inv_no),)).fetchone()
                if _exists:
                    flash(f"Invoice #{inv_no} already exists!")
                    return redirect(url_for("new_invoice"))
            except:
                flash("Invalid invoice number")
                return redirect(url_for("new_invoice"))
        else:
            inv_no = advance_monthly_inv_no()

        # Date
        user_date = request.form.get("date")
        if user_date:
            date_obj = datetime.datetime.strptime(user_date, "%Y-%m-%d").date()
        else:
            date_obj = datetime.date.today()

        date_str_display = fmt_date(date_obj)

        if user_date:
            date_obj = datetime.datetime.strptime(user_date, "%Y-%m-%d").date()
        else:
            date_obj = datetime.date.today()

        date_str_display = fmt_date(date_obj)
        date_str_db = date_obj.isoformat()
        subtotal = sum(float(li["qty"]) * float(li["unit_price"]) for li in lines)

        # Save customer_type and salesman in invoice
        customer_type = request.form.get("customer_type", "customer")
        # Salesman Mandatory
        salesman = to_caps(request.form.get("salesman","").strip())
        if not salesman:
            flash("Please slect Salesman Name!")
            return redirect(url_for("new_invoice"))
        try: discount = max(0.0, float(request.form.get("discount","0") or "0"))
        except: discount = 0.0

        # ── CORRECT FORMULA (matches PDF and image) ──
        tax_amt    = subtotal * (tax / 100.0)
        grand_total   = subtotal + tax_amt - discount       # Grand Total (no pending)
        total_amount  = grand_total + pending_added          # Total Amount (with pending)

        try:
            with db_transaction() as _c:
                _cur = _c.cursor()
                _cur.execute("""
                    INSERT OR REPLACE INTO invoices
                    (inv_no, date, customer, customer_address, customer_phone, salesman,
                     tax, discount, subtotal, grand_total, pending_added, total,
                     customer_type, remarks, logo_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(inv_no), date_str_display, name, addr, phone, salesman,
                    float(tax), float(discount), float(subtotal), float(grand_total),
                    float(pending_added), float(total_amount), customer_type, "", (logo or "")
                ))
                _cur.execute("DELETE FROM invoice_items WHERE inv_no=?", (str(inv_no),))
                for li in lines:
                    _cur.execute("""
                        INSERT INTO invoice_items (inv_no, product, qty, unit_price)
                        VALUES (?,?,?,?)
                    """, (str(inv_no), li["product"], float(li["qty"]), float(li["unit_price"])))

                _cur.execute("""
                    INSERT INTO customers (name, address, phone, joined_date)
                    VALUES (?,?,?,COALESCE((SELECT joined_date FROM customers WHERE name=? AND address=?), ?))
                    ON CONFLICT(name, address) DO UPDATE SET phone=excluded.phone
                """, (name, addr, phone, name, addr, datetime.date.today().isoformat()))

                for li in lines:
                    prod_name = li["product"].strip()
                    qty_sold = float(li.get("qty", 0) or 0)
                    _cur.execute("""
                        UPDATE products SET stock = MAX(0, stock - ?)
                        WHERE lower(trim(name)) = lower(?)
                    """, (qty_sold, prod_name))
                    _cur.execute("""
                        INSERT INTO sales_log (date, inv_no, product, qty, sell_price)
                        VALUES (?, ?, ?, ?, ?)
                    """, (date_str_db, str(inv_no), li["product"], li["qty"], li["unit_price"]))
        except Exception as e:
            flash(f"Invoice could not be saved, no changes were made (safe rollback): {e}")
            return redirect(url_for("new_invoice"))
##################
# Auto-regenerate this month's Monthly Summary PDF
        try:
            generate_monthly_summary_pdf(date_obj.year, date_obj.strftime("%B"))
        except Exception as e:
            print("Monthly summary regen error:", e)
#############
        # ── PENDING CARRY-FORWARD: log transfer & update customer pending ──
        if pending_added > 0 and not pending_blocked:
            # Log transfer with source invoice
            if from_inv_no:
                ok, msg = add_pending_to_invoice(from_inv_no, inv_no, name, addr, pending_added)
                if not ok:
                    flash(msg)
            # Reduce customer pending by the amount added to this invoice
            old_pending = get_pending(name, addr)
            new_pending = max(0.0, old_pending - pending_added)
            update_pending(name, addr, new_pending)
        elif not pending_blocked:
            # Calculate new pending = grand_total (this invoice becomes receivable)
            # Only update if net amount > 0
            pass  # pending is managed via payments received

        now = datetime.datetime.now()
        year = now.year
        month = now.strftime("%B")
        out_dir = ensure_out_dirs(year, month)

        pdf_name = f"INV_{inv_no}_{safe_name(name)}_{safe_name(addr)}.pdf"
        out_path = out_dir / pdf_name
        draw_invoice_pdf(out_path, company, logo, show_logo, inv_no, date_str_display, name, addr, phone, lines, tax, pending_added,
                         discount=discount, salesman=salesman, customer_type=customer_type)

        if not out_path.exists():
            flash(f"Invoice saved but PDF not found: {out_path}")
            return redirect(url_for("new_invoice"))

        pdf_url = url_for('view_pdf', y=year, m=month, fn=pdf_name)
        company_name = get_setting("company_name","SEIZE")
        new_url   = url_for('new_invoice')
        list_url  = url_for('invoices_list')
        led_url   = url_for('customer_ledger', name=name, address=addr)

        # Build invoice preview rows HTML
        lines_html = ""
        for i, li in enumerate(lines, 1):
            t = float(li['qty']) * float(li['unit_price'])
            lines_html += f"<tr><td style='padding:9px 12px;text-align:center;color:#555'>{i}</td><td style='padding:9px 12px;font-weight:600'>{li['product']}</td><td style='padding:9px 12px;text-align:center'>{li['qty']:g}</td><td style='padding:9px 12px;text-align:right'>Rs {li['unit_price']:,.0f}</td><td style='padding:9px 12px;text-align:right;font-weight:700;color:#1a4a2e'>Rs {t:,.0f}</td></tr>"

        subtotal_v = sum(float(li['qty'])*float(li['unit_price']) for li in lines)
        tax_v      = subtotal_v * (tax/100.0)
        totals_html = f"<tr><td colspan='4' style='text-align:right;padding:8px 12px;color:#555;font-weight:600'>Subtotal:</td><td style='text-align:right;padding:8px 12px;font-weight:700'>Rs {subtotal_v:,.0f}</td></tr>"
        if tax > 0:
            totals_html += f"<tr><td colspan='4' style='text-align:right;padding:8px 12px;color:#555'>Tax ({tax:.1f}%):</td><td style='text-align:right;padding:8px 12px'>Rs {tax_v:,.0f}</td></tr>"
        if pending_added > 0:
            totals_html += f"<tr><td colspan='4' style='text-align:right;padding:8px 12px;color:#c0392b'>Previous Pending:</td><td style='text-align:right;padding:8px 12px;color:#c0392b;font-weight:700'>Rs {pending_added:,.0f}</td></tr>"
        totals_html += f"<tr style='background:#0d2818;color:white'><td colspan='4' style='text-align:right;padding:13px 12px;font-size:17px;font-weight:900'>GRAND TOTAL:</td><td style='text-align:right;padding:13px 12px;font-size:19px;font-weight:900;color:#6dbf82'>Rs {grand_total:,.0f}</td></tr>"

        view_html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Invoice #{inv_no} Created — {company_name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#f0f4f0;min-height:100vh;padding:20px}}
.wrap{{max-width:820px;margin:auto}}
.bar{{background:linear-gradient(135deg,#0d2818,#1a4a2e);color:white;padding:18px 26px;border-radius:14px 14px 0 0;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}}
.bar h2{{font-family:Georgia,serif;font-size:22px;margin:0}}
.inv-no{{font-size:32px;font-weight:900;color:#6dbf82}}
.card{{background:white;border-radius:0 0 14px 14px;box-shadow:0 8px 32px rgba(0,0,0,.15);overflow:hidden}}
.info-row{{display:grid;grid-template-columns:1fr 1fr;border-bottom:2px solid #f1f5f9}}
.ib{{padding:18px 24px}}.ib:last-child{{border-left:1px solid #f1f5f9;text-align:right}}
.lbl{{font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px}}
.val{{font-size:16px;font-weight:700;color:#0d2818}}.sub{{font-size:12px;color:#64748b;margin-top:3px}}
.qty-bar{{background:#e8f5e9;padding:11px 24px;font-weight:700;color:#1a4a2e;font-size:14px;border-bottom:1px solid #e2e8f0}}
table{{width:100%;border-collapse:collapse}}
thead tr{{background:#0d2818;color:#a8d5b0}}
th{{padding:10px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.5px}}
tbody tr{{border-bottom:1px solid #f1f5f9}}
tbody tr:nth-child(even){{background:#f8fafc}}
.actions{{display:flex;gap:11px;padding:20px 24px;background:#f8fafc;border-top:2px solid #e2e8f0;flex-wrap:wrap}}
.btn{{padding:12px 22px;border:none;border-radius:10px;cursor:pointer;font-size:14px;font-weight:700;text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:opacity .15s}}
.btn:hover{{opacity:.85}}
@media(max-width:600px){{.info-row{{grid-template-columns:1fr}}.ib:last-child{{text-align:left;border-left:none;border-top:1px solid #f1f5f9}}.actions{{justify-content:center}}}}
</style></head><body>
<div class="wrap">
  <div class="bar">
    <div>
      <div style="font-size:11px;color:#a8d5b0;margin-bottom:3px">✅ Invoice Successfully Created</div>
      <h2>{company_name}</h2>
    </div>
    <div class="inv-no">#{inv_no}</div>
  </div>
  <div class="card">
    <div class="info-row">
      <div class="ib"><div class="lbl">Customer</div><div class="val">{name}</div><div class="sub">{addr}</div><div class="sub" style="margin-top:4px">📞 {phone or '—'}</div></div>
      <div class="ib"><div class="lbl">Invoice Details</div><div class="val">{date_str_display}</div><div class="sub">Total Items: {len(lines)} | Qty: {sum(float(li['qty']) for li in lines):g} Pcs</div></div>
    </div>
    <div class="qty-bar">📦 Total Qty: {sum(float(li['qty']) for li in lines):g} Pcs &nbsp;|&nbsp; Grand Total: Rs {grand_total:,.0f} &nbsp;|&nbsp; 🏷️ {customer_type.title()}</div>
    <table>
      <thead><tr><th style="width:36px">Sr.</th><th>Product</th><th style="text-align:center">Qty</th><th style="text-align:right">Price</th><th style="text-align:right">Total</th></tr></thead>
      <tbody>{lines_html}{totals_html}</tbody>
    </table>
    <div class="actions">
      <a href="{pdf_url}?print=1" class="btn" style="background:linear-gradient(135deg,#0d2818,#1a4a2e);color:white">🖨 Print / PDF</a>
      <a href="{url_for('edit_invoice', inv_no=inv_no)}" class="btn" style="background:linear-gradient(135deg,#1565c0,#1976d2);color:white">✏️ Re-Edit</a>
      <a href="{led_url}" class="btn" style="background:linear-gradient(135deg,#6a1b9a,#7b1fa2);color:white">📋 Customer Ledger</a>
      <a href="{new_url}" class="btn" style="background:linear-gradient(135deg,#e65100,#f57c00);color:white">➕ New Invoice</a>
      <a href="{list_url}" class="btn" style="background:#e2e8f0;color:#374151">📂 All Invoices</a>
    </div>
  </div>
</div>
<script>try{{localStorage.removeItem('invoice_draft_v1');}}catch(e){{}}</script>
</body></html>"""
        flash(f"Invoice #{inv_no} created.")
        return view_html

    # GET: render form (script uses localStorage but not inside f-strings)
    prods = load_products(); custs = load_customers()
    cust_names_unique = sorted({(c.get("name") or "").strip() for c in custs if (c.get("name") or "").strip()})
    company = get_setting("company_name","Smart Invoice")
    tax_def = float(get_setting("tax_default","0") or "0")
    next_inv_no = get_seq("invoice_no", int(get_setting("invoice_start","100")))
    html = TPL_H + """

<style>
.ni-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);padding:26px 28px;margin-bottom:20px}
.ni-card label{font-size:11.5px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:5px}
.ni-card input[type=text],.ni-card input[type=number],.ni-card input[type=date],.ni-card input:not([type]),.ni-card select{
  padding:10px 12px;border:1.5px solid var(--input-border);border-radius:9px;font-size:14px;
  background:var(--input-bg);color:var(--text);transition:border .15s, box-shadow .15s;
}
.ni-card input:focus,.ni-card select:focus{outline:none;border-color:var(--btn-primary);box-shadow:0 0 0 3px rgba(79,70,229,.12)}
.ni-header-bar{background:linear-gradient(135deg,var(--heading),#0f3d37);color:white;padding:16px 22px;border-radius:var(--card-radius) var(--card-radius) 0 0;margin:-26px -28px 22px -28px;font-size:19px;font-weight:800;display:flex;align-items:center;gap:10px}
</style>

<div class="ni-card">
  <div class="ni-header-bar">🧾 New Invoice</div>
<div class="flex">
  <div style="flex:1">
    <form method="post" id="invoiceForm" onsubmit="return validateForm()">
      <div class="top">
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:10px">
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">Invoice # (Auto — Edit if needed)</label>
      <input name="inv_no_custom" id="inv_no_field" type="number"
             value="{{next_inv_no}}"
             style="width:140px;font-size:18px;font-weight:900;color:#1a4a2e;border:2px solid #2d6b45;border-radius:8px;padding:8px 10px;"
             title="Invoice number — auto filled, aap badal sakte hain">
    </div>
<div>
  <label style="font-size:12px;font-weight:700;color:#555;">Date</label>
  <input type="date" name="date" value="{{today}}">
</div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">🏷️ Customer Type *</label>
      <select id="ctype" name="customer_type" onchange="updatePriceType()" style="padding:8px 12px;font-size:15px;font-weight:700;border-radius:8px;border:2px solid #1976d2;background:#e3f2fd;">
        <option value="customer">🛒 Customer</option>
        <option value="distributor">🚚 Distributor</option>
        <option value="wholesaler">🏭 Wholesaler</option>
      </select>
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">Customer Name *</label>
      <input name="name" id="cname" list="cust_names" placeholder="Customer Name" required
             oninput="titleCaseInput(this)" onblur="titleCaseInput(this)">
      <datalist id="cust_names">{% for n in cust_names_unique %}<option value="{{n}}">{% endfor %}</datalist>
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">Address *</label>
      <input name="address" id="caddr" list="cust_addr" placeholder="Address" required
             oninput="titleCaseInput(this)" onblur="titleCaseInput(this)">
      <datalist id="cust_addr">{% for c in custs %}<option value="{{c.address}}">{% endfor %}</datalist>
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">Phone</label>
      <input name="phone" id="cphone" placeholder="Phone">
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">Tax %</label>
      <input name="tax" placeholder="{{tax_def}}" type="number" step="0.01" style="width:80px">
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">🤝 Salesman</label>
      <select name="salesman" style="padding:8px 10px;font-size:14px;border-radius:8px;border:1.5px solid #e2e8f0;min-width:150px">
        <option value="">— Select —</option>
        {% for sm in salesmen_list %}<option value="{{sm.name}}">{{sm.name}}</option>{% endfor %}
        <option value="Direct">Direct</option>
      </select>
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">💲 Discount (Rs)</label>
      <input name="discount" id="discount_field" type="number" step="any" min="0" value="0"
             placeholder="0" oninput="calc()" style="width:110px;padding:8px;border-radius:8px;border:1.5px solid #e2e8f0;">
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">⏳ Previous Pending (Rs)</label>
      <input name="pending_amount" id="pending_amount" type="number" step="any" min="0" placeholder="0"
             oninput="calc()" style="width:130px;padding:8px;border-radius:8px;border:1.5px solid #f59e0b;">
    </div>
    <div>
      <label style="font-size:12px;font-weight:700;color:#555;display:block;margin-bottom:3px">📄 From Invoice # <span style="color:#888;font-weight:400">(optional)</span></label>
      <input name="pending_from_inv" id="pending_from_inv" type="text" placeholder="Inv # source"
             style="width:120px;padding:8px;border-radius:8px;border:1.5px solid #e2e8f0;"
             title="Enter the invoice number from which pending is being carried">
    </div>
  </div>
  <div><span class="small">Company: {{company}}</span></div>
</div>
<script>
function titleCaseInput(inp){
  inp.value=inp.value.replace(/[A-Za-z][^ ]*/g,t=>t.charAt(0).toUpperCase()+t.substr(1).toLowerCase());
}
</script>

      <table id="tbl">
        <thead><tr><th>Product</th><th style="width:90px">Qty</th><th>Unit</th><th>Total</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
      <!-- Type through filter -->
      <div style="margin:20px 0;">
        <div style="position:relative;">
          <input type="text" id="prodSearch" placeholder="Type product name......" autocomplete="off"
                 style="width:100%; padding:14px; font-size:18px; border-radius:10px; border:2px solid #1976d2;">
          <div id="prodDropdown" style="display:none; position:absolute; top:100%; left:0; right:0; max-height:400px; overflow-y:auto;
               background:white; border:2px solid #1976d2; border-top:none; border-radius:0 0 10px 10px; z-index:1000;">
            {% for p in prods %}
              <div class="prod-item" data-name="{{p.name}}"
                   style="padding:14px 16px; cursor:pointer; border-bottom:1px solid #eee;"
                   onmouseover="this.style.background='#e3f2fd'"
                   onmouseout="this.style.background='white'"
                   onclick="addProductToInvoice('{{p.name}}')">
                <strong>{{p.name}}</strong>
              </div>
            {% endfor %}
          </div>
        </div>
      </div>

      <script>
      // سرچ باکس میں ٹائپ کرتے ہی لسٹ فلٹر ہو جائے
      document.getElementById('prodSearch').addEventListener('input', function() {
        const query = this.value.toLowerCase().trim();
        const dropdown = document.getElementById('prodDropdown');
        const items = dropdown.querySelectorAll('.prod-item');
        
        if (query === '') {
          dropdown.style.display = 'none';
          return;
        }
        
        let visible = false;
        items.forEach(item => {
          if (item.dataset.name.toLowerCase().includes(query)) {
            item.style.display = 'block';
            visible = true;
          } else {
            item.style.display = 'none';
          }
        });
        
        dropdown.style.display = visible ? 'block' : 'none';
      });

      // باہر کلک کرنے پر لسٹ چھپ جائے
      document.addEventListener('click', function(e) {
        if (!e.target.closest('#prodSearch')) {
          document.getElementById('prodDropdown').style.display = 'none';
        }
      });

      // پروڈکٹ پر کلک کرنے سے رو میں شامل ہو جائے
      function addProductToInvoice(name) {
        addRow(); // پہلے سے موجود فنکشن جو نئی رو بناتا ہے
        const lastIndex = row - 1;
        const select = document.querySelector(`select[name="prod_${lastIndex}"]`);
        if (select) {
          select.value = name;
          setInfo(select, lastIndex);  // پرائس خود بخود آ جائے گی
          calc();
        }
        document.getElementById('prodSearch').value = '';
        document.getElementById('prodDropdown').style.display = 'none';
      }
      </script>

      <p class="small" id="sumline"></p>
      <p>
        <button type="button" class="btn" onclick="addRow()">+ Add Item</button>
        <button type="button" class="btn" onclick="clearForm()">Clear Form</button>
        <a class="link" href="{{url_for('home')}}">Back</a>
      </p>

      <p><button class="btn">💾Save & PDF</button></p> 
    </form>
  </div>

  <div class="side">
    <div class="card"><h3>Customer History & Pending</h3>
      <label style="display:flex;align-items:center;gap:6px;font-size:13px;font-weight:700;color:#1a4a2e;margin-bottom:8px;cursor:pointer">
        <input type="checkbox" id="showLastBill" onchange="loadHist()"> 🧾 Show Last Bill Prices
      </label>
      <div id="lastBillBox" style="margin-bottom:10px"></div>
      <div id="hist" class="small">Type name & address…</div>
    </div>
  </div>
</div>
</div>
<script>
function validateForm() {
  const rows = document.querySelectorAll("#tbl tbody tr");

  for (let r of rows) {
    const select     = r.querySelector("select");
    const priceInput = r.querySelector("input[name^='u_']");  // name سے لیا — step 1 کی وجہ سے کام کرے گا

    if (!select || !select.value) continue;

    const minPrice     = parseFloat(priceInput.dataset.minPrice) || 0;
    const currentPrice = parseFloat(priceInput.value) || 0;

    if (currentPrice > 0 && currentPrice < minPrice) {
      alert(`Error: Selling price for "${select.value}" cannot be lower than the purchase price!\nMinimum: Rs ${minPrice}`);

      // یہ تین لائنیں روکنے میں مدد دیں گی
      priceInput.focus();
      priceInput.select();              // متن سلیکٹ ہو جائے
      priceInput.style.border = "3px solid red";  // زیادہ نمایاں

      return false;   // یہ لائن فارم کو روک دے گی
    }
  }

  // اگر کوئی غلطی نہ ہو تو فارم جانے دیں
  return true;
}
// فارم submit کو مکمل کنٹرول کرنے والا کوڈ
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('invoiceForm');
    if (!form) return;

    form.addEventListener('submit', function(e) {
        // پہلے موجودہ validation (اگر ہے تو)
        if (typeof validateForm === 'function' && !validateForm()) {
            e.preventDefault();
            return;
        }

        // pending چیک
        const pendingInput = document.getElementById('pending_amount');
        if (!pendingInput) return; // اگر فیلڈ نہ ملے تو چھوڑ دو

        let pending = parseFloat(pendingInput.value) || 0;

        if (pending > 0) {
            const message = `Previous pending: Rs ${pending.toFixed(2)}\nCreate invoice including this amount?`;

            if (!confirm(message)) {
                // No → pending کو 0 کر دو
                pendingInput.value = "0";
                pendingInput.focus(); // optional: واپس فیلڈ پر لے جاؤ
            }
            // Yes → کچھ نہ کرو، ویلیو ویسی ہی رہے گی
        }

        // فارم کو جانے دو
        // e.preventDefault() یہاں نہیں لگائیں گے — صرف غلطی پر روکا تھا
    });
});

</script>
<script>
const prods = {{ prods|tojson }};  // includes wholesaler_price, distributor_price, customer_price
let row=0;
const DKEY = "invoice_draft_v1";

function saveDraft(){
  try {
    const cname = document.getElementById('cname').value||"";
    const caddr = document.getElementById('caddr').value||"";
    const cphone = document.getElementById('cphone').value||"";
    const tax = document.querySelector('input[name="tax"]').value||"";
    const ctypeEl = document.getElementById('ctype');
    const ctype = ctypeEl ? ctypeEl.value||"" : "";
    const smEl = document.querySelector('select[name="salesman"]');
    const salesman = smEl ? smEl.value||"" : "";
    const rows = [];
    for(const r of document.querySelectorAll("#tbl tbody tr")){
      const sel = r.querySelector("select");
      const qty = r.querySelector("input[name^='qty_']");
      const price = r.querySelector("input[id^='u_']");
      if(sel && sel.value){
        rows.push({product: sel.value, qty: qty.value||"", price: price ? price.value||"" : ""});
      }
    }
    localStorage.setItem(DKEY, JSON.stringify({name:cname,address:caddr,phone:cphone,tax:tax,ctype:ctype,salesman:salesman,rows:rows}));
  } catch(e) { console.error("saveDraft", e); }
}
function restoreDraft(){
  try {
    const raw = localStorage.getItem(DKEY);
    if(!raw) return false;
    const o = JSON.parse(raw);
    if(o.name) document.getElementById('cname').value = o.name;
    if(o.address) document.getElementById('caddr').value = o.address;
    if(o.phone) document.getElementById('cphone').value = o.phone;
    if(o.tax) document.querySelector('input[name="tax"]').value = o.tax;
    if(o.ctype){
      const ctypeEl = document.getElementById('ctype');
      if(ctypeEl){ ctypeEl.value = o.ctype; if(typeof updatePriceType === 'function') updatePriceType(); }
    }
    if(o.salesman){
      const smEl = document.querySelector('select[name="salesman"]');
      if(smEl) smEl.value = o.salesman;
    }
    const tb=document.querySelector("#tbl tbody"); tb.innerHTML=""; row=0;
    if(o.rows && o.rows.length){
      for(const r of o.rows){
        addRow();
        const i = row-1;
        const sel = document.querySelector(`select[name="prod_${i}"]`);
        const qty = document.querySelector(`input[name="qty_${i}"]`);
        if(sel) sel.value = r.product;
        if(qty) qty.value = r.qty;
        setTimeout(()=>{
          if(document.querySelector(`select[name="prod_${i}"]`)) setInfo(document.querySelector(`select[name="prod_${i}"]`), i);
          const priceEl = document.getElementById(`u_${i}`);
          if(priceEl && r.price !== undefined && r.price !== ""){ priceEl.value = r.price; }
          calc();
        }, 10);
      }
    } else {
      addRow();
    }
    return true;
  } catch(e){ console.error("restoreDraft", e); return false; }
}

function addRow(){
  const tb=document.querySelector("#tbl tbody");
  const tr=document.createElement("tr");
  tr.innerHTML=`
    <td>
      <select name="prod_${row}" onchange="setInfo(this, ${row})" required style="min-width:100%">
        <option value="">-- select --</option>
        ${prods.map(p=>`<option value="${p.name}">${p.name}</option>`).join('')}
      </select>
    </td>
    <td><input name="qty_${row}" type="number" min="0" step="any" inputmode="decimal" required oninput="calc()"></td>
    <td>
      <span id="price_badge_${row}" style="display:none;font-size:10px;background:#e3f2fd;border-radius:4px;padding:2px 5px;margin-bottom:2px;"></span><br>
      <input name="u_${row}" id="u_${row}" type="number" step="any" oninput="calc(); this.dataset.manualEdit='1';" style="font-weight:bold;">
    </td>
    <td><input id="t_${row}" disabled></td>
    <td><button type="button" class="btn" onclick="this.closest('tr').remove(); calc(); saveDraft();">X</button></td>
  `;
  tb.appendChild(tr); row++; calc(); saveDraft();
}
function updatePriceType() {
  // When customer type changes, re-run setInfo on all rows
  const rows = document.querySelectorAll("#tbl tbody tr");
  rows.forEach((row, i) => {
    const sel = row.querySelector("select[name^='prod_']");
    if (sel && sel.value) {
      const idx = sel.name.replace("prod_","");
      setInfo(sel, parseInt(idx));
    }
  });
}

function setInfo(sel, i) {
  const p = prods.find(x => x.name === sel.value);
  const u = document.getElementById('u_' + i);
  const ctype = document.getElementById('ctype') ? document.getElementById('ctype').value : 'customer';
  if (p) {
    let price = p.unit_price;
    if (ctype === 'wholesaler' && p.wholesaler_price > 0) price = p.wholesaler_price;
    else if (ctype === 'distributor' && p.distributor_price > 0) price = p.distributor_price;
    else if (ctype === 'customer' && p.customer_price > 0) price = p.customer_price;
    if (u.dataset.manualEdit !== '1' || u.dataset.lastProduct !== sel.value) {
      u.value = price;
    }
    u.dataset.lastProduct = sel.value;
    u.dataset.minPrice = p.purchase_price || 0;
    // Show customer type badge
    const badge = document.getElementById('price_badge_' + i);
    if (badge) {
      const labels = {wholesaler:'🏭 Wholesaler', distributor:'🚚 Distributor', customer:'🛒 Customer'};
      badge.textContent = labels[ctype] || '';
      badge.style.display = 'inline';
    }
  } else {
    u.value = "";
    u.dataset.minPrice = 0;
  }
  calc(); 
  loadHist(); 
  saveDraft();

  // ➕ Is product ka customer ke sath last date+price dikhao (sirf jab toggle ON ho)
  const showLastBill = document.getElementById('showLastBill');
  const cnameEl = document.getElementById('cname');
  const caddrEl = document.getElementById('caddr');
  if (showLastBill && showLastBill.checked && sel.value && cnameEl.value.trim() && caddrEl.value.trim()) {
    fetch(`/api/last_product_price?name=${encodeURIComponent(cnameEl.value.trim())}&address=${encodeURIComponent(caddrEl.value.trim())}&product=${encodeURIComponent(sel.value)}`)
      .then(r => r.json())
      .then(d => {
        const box = document.getElementById('lastBillBox');
        if (!box) return;
        const safeKey = sel.value.replace(/"/g, '');
        const existing = box.querySelector(`[data-prod="${safeKey}"]`);
        if (existing) existing.remove();

        let line;
        if (d.is_new) {
          line = `<div data-prod="${safeKey}" style="background:#fff7e6;border:1px solid #f5b942;border-radius:8px;padding:6px 10px;font-size:12px;margin-bottom:6px">
            🆕 <strong>${d.product}</strong> — <strong style="color:#c77700">New Product</strong> (${d.date})
          </div>`;
        } else {
          line = `<div data-prod="${safeKey}" style="background:#eef7ff;border:1px solid #90caf9;border-radius:8px;padding:6px 10px;font-size:12px;margin-bottom:6px">
            🧾 <strong>${d.product}</strong> — last sold: ${d.date} @ <strong style="color:#1565c0">Rs ${parseFloat(d.unit_price).toFixed(0)}</strong>
          </div>`;
        }
        box.insertAdjacentHTML('afterbegin', line);
      });
  }

  // اگر یوزر دستی پرائس کم ڈالے تو الرٹ
    u.addEventListener('input', function() {
    const minPrice = parseFloat(this.dataset.minPrice) || 0;
    const current  = parseFloat(this.value) || 0;

    if (current > 0 && current < minPrice) {
      this.style.border = "2px solid red";
    } else {
      this.style.border = "";
    }
    calc();
  });
}
function calc(){
  let sum = 0;
  let total_qty = 0;
  const rows = [...document.querySelectorAll("#tbl tbody tr")];
  const names = [];

  for(const r of rows){
    const sel = r.querySelector("select");
    const qty = r.querySelector("input[name^='qty_']");
    const u = r.querySelector("input[id^='u_']");
    const t = r.querySelector("input[id^='t_']");

    if(!sel || !qty || !u) continue;

    if(sel.value && names.includes(sel.value)){
      alert(sel.value + " already added.");
      sel.value = "";
      saveDraft();
      return;
    }
    if(sel.value) names.push(sel.value);

    const q = parseFloat(qty.value || "0");
    const up = parseFloat(u.value || "0");

    // 🔴 Stock check — qty cell turns red immediately if entered quantity
    // exceeds the product's available stock, so mistakes are caught before
    // the invoice is even submitted.
    const prod = sel.value ? prods.find(x => x.name === sel.value) : null;
    if (prod && q > prod.stock) {
      qty.style.border = "2px solid red";
      qty.style.background = "#fee2e2";
      qty.title = `⚠️ Stock available: ${prod.stock}`;
    } else {
      qty.style.border = "";
      qty.style.background = "";
      qty.title = "";
    }

    t.value = (isNaN(q) || isNaN(up)) ? "" : (q * up).toFixed(2);
    sum += (isNaN(q) || isNaN(up)) ? 0 : q * up;
    total_qty += isNaN(q) ? 0 : q;
  }

  // Include discount
  const discEl = document.getElementById('discount_field');
  const discount = discEl ? parseFloat(discEl.value || "0") : 0;
  const net = Math.max(0, sum - discount);

  // Include pending
  const pendEl = document.getElementById('pending_amount');
  const pending = pendEl ? parseFloat(pendEl.value || "0") : 0;

  const ctype = document.getElementById('ctype') ? document.getElementById('ctype').value : 'customer';
  const ctypeLabels = {wholesaler:'🏭 Wholesaler', distributor:'🚚 Distributor', customer:'🛒 Customer'};

  document.getElementById("sumline").innerHTML =
    `<strong>Total Qty: ${total_qty.toFixed(2)}</strong> &nbsp;|&nbsp;
     Subtotal: Rs ${sum.toFixed(2)} &nbsp;|&nbsp;
     <span style="color:#dc2626">Discount: Rs ${discount.toFixed(2)}</span> &nbsp;|&nbsp;
     <strong>Net: Rs ${net.toFixed(2)}</strong>
     ${pending > 0 ? ` &nbsp;|&nbsp; <span style="color:#f59e0b">Pending: Rs ${pending.toFixed(2)}</span> &nbsp;|&nbsp; <strong style="color:#dc2626">Grand: Rs ${(net+pending).toFixed(2)}</strong>` : ''}
     &nbsp;|&nbsp; <span class="price-type-badge ${ctype==='wholesaler'?'price-type-w':ctype==='distributor'?'price-type-d':'price-type-c'}">${ctypeLabels[ctype]||''}</span>`;

  saveDraft();
}
function validateForm(){
  const firstLine=document.querySelector("#tbl tbody tr");
  if(!firstLine){ alert("Add at least one item"); return false; }
  const rows=[...document.querySelectorAll("#tbl tbody tr")];
  for(const r of rows){
    const sel=r.querySelector("select"); const qty=r.querySelector("input[name^='qty_']");
    if(sel && sel.value){
      const p = prods.find(x=>x.name===sel.value);
      const q = parseFloat(qty.value||"0");
      if(p && q > p.stock){ alert("Insufficient stock for "+p.name+" (have "+p.stock+")"); return false; }
    }
  }
  return true;
}
function clearForm(){
  if(!confirm("Clear form? Unsaved data will be lost.")) return;
  document.getElementById('invoiceForm').reset();
  const tb=document.querySelector("#tbl tbody"); tb.innerHTML="";
  row=0; addRow(); document.getElementById('hist').innerText='Type name & address…'; document.getElementById('sumline').innerText='';
  try{ localStorage.removeItem(DKEY); } catch(e){}
}
function loadHist(){
  const n=document.getElementById('cname').value.trim(), a=document.getElementById('caddr').value.trim();
  if(!n||!a){ document.getElementById('hist').innerText='Type name & address to see history…'; return; }
  fetch(`/api/history?name=${encodeURIComponent(n)}&address=${encodeURIComponent(a)}`).then(r=>r.json()).then(d=>{
    const pendField = document.getElementById('pending_amount');
    const fromField = document.getElementById('pending_from_inv');
    const totalPending = d.pending || 0;

    if(d.rows.length==0){ document.getElementById('hist').innerText='No history yet'; return; }

    let html = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
      <strong style="color:#dc2626;font-size:15px">⏳ Outstanding Pending: Rs ${totalPending.toFixed(0)}</strong>`;

    if(totalPending > 0){
      html += `<button type="button" onclick="fillPending(${totalPending})"
                style="background:#f59e0b;color:white;border:none;border-radius:6px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer">
                + Add Pending to Invoice</button>`;
    }
    html += `</div>`;

    // Pending invoices list
    if(d.pending_invoices && d.pending_invoices.length > 0){
      html += `<div style="background:#fff8e1;border:1px solid #f59e0b;border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:12px">
        <strong style="color:#92400e">📋 Unpaid Invoices (click to select source):</strong><br>`;
      for(const pi of d.pending_invoices){
        html += `<span onclick="selectPendingInv('${pi.inv_no}','${pi.remaining}')"
                  style="display:inline-block;margin:3px;padding:3px 8px;background:#fef3c7;border:1px solid #f59e0b;border-radius:5px;cursor:pointer;font-weight:600">
                  #${pi.inv_no} (Rs ${pi.remaining.toFixed(0)})</span>`;
      }
      html += `</div>`;
    }

    html += '<table><tr><th>Inv#</th><th>Date</th><th>Total</th><th>Received</th><th>Pending</th><th>PDF</th></tr>';
    for(const r of d.rows){
      const isUnpaid = r.pending > 0;
      html += `<tr style="${isUnpaid?'background:#fff8e1':''}">
        <td><strong>${r.inv_no}</strong></td><td>${r.date}</td>
        <td>Rs ${parseFloat(r.total).toFixed(0)}</td>
        <td style="color:#16a34a">Rs ${r.received.toFixed(0)}</td>
        <td style="color:${isUnpaid?'#dc2626':'#16a34a'};font-weight:700">Rs ${r.pending.toFixed(0)}</td>
        <td><a class="link" href="${r.pdf}">PDF</a></td>
      </tr>`;
    }
    html += '</table>';
    document.getElementById('hist').innerHTML = html;
    document.getElementById('lastBillBox').innerHTML = '';
    if(d.customer_type){
      const ctypeSel = document.getElementById('ctype');
      if(ctypeSel){ ctypeSel.value = d.customer_type; if(typeof updatePriceType==='function') updatePriceType(); }
    }
    if(d.salesman){
      const smSel = document.querySelector('select[name="salesman"]');
      if(smSel && [...smSel.options].some(o=>o.value===d.salesman)){ smSel.value = d.salesman; }
    }
  });
}

function fillPending(amount){
  const pendField = document.getElementById('pending_amount');
  if(pendField){ pendField.value = amount.toFixed(0); calc(); }
}

function selectPendingInv(invNo, remaining){
  const pendField = document.getElementById('pending_amount');
  const fromField = document.getElementById('pending_from_inv');
  if(pendField){ pendField.value = parseFloat(remaining).toFixed(0); calc(); }
  if(fromField){ fromField.value = invNo; }
}
document.addEventListener('DOMContentLoaded', function(){
  const ok = restoreDraft();
  if(!ok){
    const tb=document.querySelector("#tbl tbody");
    if(!tb.querySelector("tr")) addRow();
  }
});
document.getElementById('cname').addEventListener('input', saveDraft);
document.getElementById('caddr').addEventListener('input', saveDraft);
document.getElementById('cname').addEventListener('blur', loadHist);
document.getElementById('caddr').addEventListener('blur', loadHist);
document.getElementById('cphone').addEventListener('input', saveDraft);
document.querySelector('input[name="tax"]').addEventListener('input', saveDraft);
</script>
""" + TPL_F

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
    SELECT name
    FROM salesmen
    WHERE status='Active' AND salesman_type='salesman'
    ORDER BY name
    """)

    salesmen_list = [dict(r) for r in cur.fetchall()]
    conn.close()
    next_inv_no = advance_monthly_inv_no()
    return render_template_string(html, prods=prods, custs=custs, cust_names_unique=cust_names_unique,
        company=company, tax_def=tax_def, next_inv_no=next_inv_no,
        salesmen_list=salesmen_list,
        project=get_setting("project_name"), today=datetime.date.today().isoformat() )

#####################################
# ===================== DELETE + RECYCLE BIN (FULL SQLITE) =====================

import json

# ===================== DELETE INVOICE (SQLite + Recycle) =====================
# ===================== DELETE INVOICE (FULL SQLITE) =====================
@app.route("/invoice/delete/<int:inv_no>")
@login_required
def delete_invoice(inv_no):
    try:
        with db_transaction() as _c:
            row = _c.execute("""
                SELECT inv_no, date, customer, customer_address, customer_phone, salesman,
                       tax, discount, subtotal, grand_total, pending_added, total,
                       customer_type, remarks, logo_path
                FROM invoices WHERE inv_no=?
            """, (str(inv_no),)).fetchone()

            if not row:
                flash("Invoice not found")
                return redirect(url_for("invoices_list"))

            cols = ["inv_no","date","customer","customer_address","customer_phone","salesman",
                    "tax","discount","subtotal","grand_total","pending_added","total",
                    "customer_type","remarks","logo_path"]
            invoice = dict(zip(cols, row))

            inv_lines = _c.execute(
                "SELECT product, qty, unit_price FROM invoice_items WHERE inv_no=?", (str(inv_no),)
            ).fetchall()
            inv_lines = [{"product": p, "qty": q, "unit_price": u} for (p, q, u) in inv_lines]

            _cur = _c.cursor()
            _cur.execute("""
                INSERT OR REPLACE INTO deleted_invoices
                (inv_no, date, customer, customer_address, customer_phone, salesman,
                 tax, discount, subtotal, grand_total, pending_added, total,
                 customer_type, remarks, logo_path, deleted_on, deleted_lines)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                invoice["inv_no"], invoice["date"], invoice["customer"], invoice["customer_address"],
                invoice["customer_phone"], invoice["salesman"], invoice["tax"], invoice["discount"],
                invoice["subtotal"], invoice["grand_total"], invoice["pending_added"], invoice["total"],
                invoice["customer_type"], invoice["remarks"], invoice["logo_path"],
                datetime.date.today().isoformat(), json.dumps(inv_lines)
            ))

            _cur.execute("DELETE FROM deleted_invoice_items WHERE inv_no=?", (str(inv_no),))
            for li in inv_lines:
                _cur.execute("""
                    INSERT INTO deleted_invoice_items (inv_no, product, qty, unit_price)
                    VALUES (?,?,?,?)
                """, (str(inv_no), li["product"], li["qty"], li["unit_price"]))

            _cur.execute("DELETE FROM invoice_items WHERE inv_no=?", (str(inv_no),))
            _cur.execute("DELETE FROM invoices WHERE inv_no=?", (str(inv_no),))

            for li in inv_lines:
                pname = li["product"].strip()
                qty = float(li.get("qty", 0) or 0)
                _cur.execute("""
                    UPDATE products SET stock = stock + ?
                    WHERE lower(trim(name)) = lower(?)
                """, (qty, pname))
        # Auto-regenerate Monthly Summary PDF for the deleted invoice's month
        try:
            for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
                try:
                    _dt = datetime.datetime.strptime(invoice.get("date",""), fmt)
                    generate_monthly_summary_pdf(_dt.year, _dt.strftime("%B"))
                    break
                except Exception:
                    continue
        except Exception as e:
            print("Monthly summary regen error:", e)

        flash(f"Invoice #{inv_no} moved to Recycle Bin (recoverable within 30 days)")
        return redirect(url_for("invoices_list"))

    except Exception as e:
        print("Delete Error:", e)
        flash("An error occurred while deleting")
        return redirect(url_for("invoices_list"))


@app.route("/invoice/recycle_bin", methods=["GET","POST"])
@login_required
def recycle_bin():
    today = datetime.date.today()

    with db_transaction() as _c:
        rows = _c.execute("""
            SELECT inv_no, date, customer, customer_address, customer_phone, salesman,
                   tax, discount, subtotal, grand_total, pending_added, total,
                   customer_type, remarks, logo_path, deleted_on
            FROM deleted_invoices
        """).fetchall()

        recoverable = []
        expired_inv_nos = []
        for row in rows:
            (inv_no, date, customer, customer_address, customer_phone, salesman,
             tax, discount, subtotal, grand_total, pending_added, total,
             customer_type, remarks, logo_path, deleted_on) = row
            try:
                d = datetime.date.fromisoformat(deleted_on[:10])
                days_left = 30 - (today - d).days
            except Exception:
                days_left = 30
            if days_left >= 0:
                recoverable.append({
                    "inv_no": inv_no, "date": date, "name": customer, "address": customer_address,
                    "phone": customer_phone, "salesman": salesman, "tax": tax, "discount": discount,
                    "subtotal": subtotal, "grand_total": grand_total, "pending_added": pending_added,
                    "total": total, "customer_type": customer_type, "remarks": remarks,
                    "logo_path": logo_path, "deleted_on": deleted_on, "days_left": days_left
                })
            else:
                expired_inv_nos.append(inv_no)

        # Auto-purge expired (30+ din purane)
        for inv_no in expired_inv_nos:
            _c.execute("DELETE FROM deleted_invoice_items WHERE inv_no=?", (inv_no,))
            _c.execute("DELETE FROM deleted_invoices WHERE inv_no=?", (inv_no,))

    recoverable.sort(key=lambda x: x.get("deleted_on",""), reverse=True)

    html = TPL_H + """
<div class="page-header">
  <div><h2>🗑️ Recycle Bin — Deleted Invoices</h2>
  <p class="text-muted">Deleted invoices recoverable within 30 days. After 30 days, auto-purged.</p></div>
  <a href="/invoices" class="btn btn-secondary">← Back to Invoices</a>
</div>
<div class="card">
  <div class="table-wrap">
    <table>
      <thead><tr><th>Inv#</th><th>Customer</th><th>Date</th><th>Grand Total</th><th>Deleted On</th><th>Days Left</th><th>Actions</th></tr></thead>
      <tbody>
        {% for r in recoverable %}
        {% set gt = r.get('grand_total','') | float if r.get('grand_total') else (r.total|float - r.get('pending_added','0')|float) %}
        <tr>
          <td><strong>#{{r.inv_no}}</strong></td>
          <td>{{r.name}}<br><small class="text-muted">{{r.address}}</small></td>
          <td>{{r.date}}</td>
          <td class="fw-bold">Rs {{'{:,.0f}'.format(gt)}}</td>
          <td>{{r.deleted_on}}</td>
          <td>
            <span class="badge {{'badge-green' if r.days_left>10 else 'badge-yellow' if r.days_left>5 else 'badge-red'}}">
              {{r.days_left}} days left
            </span>
          </td>
          <td>
            <div class="flex gap-1">
              <form method="post" action="/invoice/recover/{{r.inv_no}}" style="display:inline">
                <button class="btn btn-success btn-sm">↩️ Recover</button>
              </form>
              <form method="post" action="/invoice/permanent_delete/{{r.inv_no}}" style="display:inline"
                    onsubmit="return confirm('PERMANENTLY delete Invoice #{{r.inv_no}}? This cannot be undone!')">
                <button class="btn btn-danger btn-sm">💀 Delete Forever</button>
              </form>
            </div>
          </td>
        </tr>
        {% endfor %}
        {% if not recoverable %}
        <tr><td colspan="7" class="text-center text-muted" style="padding:40px">
          🗂️ Recycle bin is empty
        </td></tr>
        {% endif %}
      </tbody>
    </table>
  </div>
</div>
""" + TPL_F
    return render_template_string(html, recoverable=recoverable, project=get_setting("project_name"))


@app.route("/invoice/recover/<int:inv_no>", methods=["POST"])
@login_required
def recover_invoice(inv_no):
    today = datetime.date.today()

    with db_transaction() as _c:
        row = _c.execute("""
            SELECT inv_no, date, customer, customer_address, customer_phone, salesman,
                   tax, discount, subtotal, grand_total, pending_added, total,
                   customer_type, remarks, logo_path, deleted_on
            FROM deleted_invoices WHERE inv_no=?
        """, (str(inv_no),)).fetchone()

        if not row:
            flash("Invoice not found in recycle bin")
            return redirect(url_for("recycle_bin"))

        (inv_no_v, date, customer, customer_address, customer_phone, salesman,
         tax, discount, subtotal, grand_total, pending_added, total,
         customer_type, remarks, logo_path, deleted_on) = row

        try:
            d = datetime.date.fromisoformat(deleted_on[:10])
            if (today - d).days > 30:
                flash("❌ Recovery period expired (30 days limit)")
                return redirect(url_for("recycle_bin"))
        except Exception:
            pass

        exists = _c.execute("SELECT 1 FROM invoices WHERE inv_no=?", (str(inv_no),)).fetchone()
        if exists:
            flash("❌ Invoice number already exists in active records")
            return redirect(url_for("recycle_bin"))

        restored_lines = _c.execute(
            "SELECT product, qty, unit_price FROM deleted_invoice_items WHERE inv_no=?", (str(inv_no),)
        ).fetchall()
        restored_lines = [{"product": p, "qty": q, "unit_price": u} for (p, q, u) in restored_lines]

        _cur = _c.cursor()
        _cur.execute("""
            INSERT INTO invoices
            (inv_no, date, customer, customer_address, customer_phone, salesman,
             tax, discount, subtotal, grand_total, pending_added, total,
             customer_type, remarks, logo_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            inv_no_v, date, customer, customer_address, customer_phone, salesman,
            tax, discount, subtotal, grand_total, pending_added, total,
            customer_type, remarks, logo_path
        ))

        for li in restored_lines:
            _cur.execute("""
                INSERT INTO invoice_items (inv_no, product, qty, unit_price)
                VALUES (?,?,?,?)
            """, (str(inv_no), li["product"], li["qty"], li["unit_price"]))

            qty = float(li.get("qty", 0) or 0)
            _cur.execute("""
                UPDATE products SET stock = MAX(0, stock - ?)
                WHERE lower(trim(name)) = lower(?)
            """, (qty, li["product"].strip()))

        _cur.execute("DELETE FROM deleted_invoice_items WHERE inv_no=?", (str(inv_no),))
        _cur.execute("DELETE FROM deleted_invoices WHERE inv_no=?", (str(inv_no),))

    # Auto-regenerate Monthly Summary PDF for the recovered invoice's month
    try:
        for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
            try:
                _dt = datetime.datetime.strptime(date, fmt)
                generate_monthly_summary_pdf(_dt.year, _dt.strftime("%B"))
                break
            except Exception:
                continue
    except Exception as e:
        print("Monthly summary regen error:", e)

    flash(f"✅ Invoice #{inv_no} recovered successfully!")
    return redirect(url_for("invoices_list"))

@app.route("/invoice/permanent_delete/<int:inv_no>", methods=["POST"])
@login_required
def permanent_delete_invoice(inv_no):
    with db_transaction() as _c:
        _c.execute("DELETE FROM deleted_invoice_items WHERE inv_no=?", (str(inv_no),))
        _c.execute("DELETE FROM deleted_invoices WHERE inv_no=?", (str(inv_no),))
    flash(f"💀 Invoice #{inv_no} permanently deleted")
    return redirect(url_for("recycle_bin"))

################## receive-offline
@app.route("/receive-offline", methods=["POST"])
def receive_offline():
    data = request.json or []
    print("RECEIVED OFFLINE DATA:", data)
    return {"status": "ok", "received": len(data)}



# ---------- API endpoints ----------
@app.get("/api/history")
@login_required
def api_history():
    name = to_caps(request.args.get("name",""))
    addr = to_caps(request.args.get("address",""))

    # +FIX: naya invoice sirf SQLite table mein save hota hai (invoices.csv
    # migration ke baad se update nahi hoti) - is liye ab seedha DB se
    # read kar rahe hain taake customer_type/salesman/pending ka sahi/live data mile.
    # (Read-only query - koi data delete/overwrite nahi hoti, zero data-loss risk.)
    _conn = db()
    _conn.row_factory = sqlite3.Row
    try:
        _db_rows = _conn.execute("""
            SELECT inv_no, date, customer AS name, customer_address AS address,
                   grand_total, total, pending_added, remarks, customer_type, salesman
            FROM invoices
        """).fetchall()
    finally:
        _conn.close()
    invs = [dict(r) for r in _db_rows if to_caps(r["name"]) == name and to_caps(r["address"]) == addr]

    pays = read_payments_db()
    pay_map = {}
    for p in pays:
        try:
            i = int(p["inv_no"])
            pay_map.setdefault(i, []).append(p)
        except: pass

    def parse_d(d):
        for fmt in ("%Y-%m-%d","%d-%m-%y","%d-%m-%Y"):
            try: return datetime.datetime.strptime(d,fmt)
            except: pass
        return datetime.datetime.min

    invs.sort(key=lambda r: parse_d(r.get("date","")))
 # ➕ NAYI LINES:
    last_customer_type = (invs[-1].get("customer_type","") or "").strip().lower() if invs else ""
    last_salesman       = (invs[-1].get("salesman","") or "").strip() if invs else ""

    out = []
    total_pending = 0.0

    payment_pool = 0.0
    for _r in invs:
        try: _invn = int(_r["inv_no"])
        except: continue
        for _p in pay_map.get(_invn, []):
            payment_pool += float(_p.get("amount","0") or 0)

    for r in invs:
        try: invn = int(r["inv_no"])
        except: continue

        # ── Same fix as customer_ledger: use grand_total (this invoice's OWN
        # new sale amount only), not "total" (which can already include
        # pending carried forward from an earlier invoice and would double
        # count it here). ──
        raw_total     = float(r.get("total","0") or 0)
        pending_added = float(r.get("pending_added","0") or 0)
        if r.get("grand_total","") not in ("", None):
            total = float(r.get("grand_total","0") or 0)
        else:
            total = max(raw_total - pending_added, 0.0)

        # ── If this invoice's pending was already transferred forward into
        # a later invoice, it's settled here — the debt now lives in the
        # destination invoice's grand_total. ──
        was_transferred = str(r.get("remarks","")).startswith("Pending Transferred to Inv #")

        inv_pays = pay_map.get(invn, [])
        if was_transferred:
            recvd = total  # settled via transfer, not a cash payment
        else:
            recvd = min(total, payment_pool)
            payment_pool -= recvd
        pend = 0.0 if was_transferred else max(total - recvd, 0.0)
        total_pending += pend
        try:
            d = r["date"]
            if "-" in d and len(d.split("-")[2]) == 2:
                dt = datetime.datetime.strptime(d, "%d-%m-%y")
            elif "-" in d and len(d.split("-")[2]) == 4:
                dt = datetime.datetime.strptime(d, "%d-%m-%Y")
            else:
                dt = datetime.datetime.strptime(d, "%Y-%m-%d")
            y = dt.year; m = dt.strftime("%B")
        except:
            now = datetime.datetime.now(); y = now.year; m = now.strftime("%B")

        fn = f"INV_{r['inv_no']}_{safe_name(name)}_{safe_name(addr)}.pdf"
        out.append({
            "inv_no": invn, "date": r["date"], "total": total,
            "received": recvd, "pending": pend,
            "pdf": url_for("open_pdf_path", y=y, m=m, fn=fn),
        })

    out = out[-50:]

    # ── Pending invoices list (for the "+ Add Pending to Invoice" picker) ──
    # Only invoices with real outstanding pending AND not already transferred.
    pending_invoices = []
    for r in out:
        if r["pending"] > 0:
            pending_invoices.append({"inv_no": r["inv_no"], "remaining": r["pending"]})

    return jsonify({"rows": out, "pending": total_pending, "pending_invoices": pending_invoices[-5:],
                 "customer_type": last_customer_type, "salesman": last_salesman})


@app.route("/api/pending")
@login_required
def api_pending():
    name = to_caps(request.args.get("name",""))
    addr = to_caps(request.args.get("address",""))
    if not name or not addr:
        return jsonify({"pending": 0.0, "pending_invoices": []})

    # +FIX: naya invoice sirf SQLite table mein save hota hai (invoices.csv
    # migration ke baad se update nahi hoti) - is liye ab seedha DB se
    # read kar rahe hain taake customer_type/salesman/pending ka sahi/live data mile.
    # (Read-only query - koi data delete/overwrite nahi hoti, zero data-loss risk.)
    _conn = db()
    _conn.row_factory = sqlite3.Row
    try:
        _db_rows = _conn.execute("""
            SELECT inv_no, date, customer AS name, customer_address AS address,
                   grand_total, total, pending_added, remarks, customer_type, salesman
            FROM invoices
        """).fetchall()
    finally:
        _conn.close()
    invs = [dict(r) for r in _db_rows if to_caps(r["name"]) == name and to_caps(r["address"]) == addr]

    pays = read_payments_db()
    pay_map = {}
    for p in pays:
        try:
            i = int(p["inv_no"])
            pay_map.setdefault(i, []).append(p)
        except: pass

    def _pd(d):
        for fmt in ("%Y-%m-%d","%d-%m-%y","%d-%m-%Y"):
            try: return datetime.datetime.strptime(d, fmt)
            except: pass
        return datetime.datetime.min
    invs.sort(key=lambda r: _pd(r.get("date","")))

    pending = 0.0
    pending_invoices = []  # list of {inv_no, date, total, paid, remaining}

    payment_pool = 0.0
    for _r in invs:
        try: _invn = int(_r["inv_no"])
        except: continue
        for _p in pay_map.get(_invn, []):
            payment_pool += float(_p.get("amount","0") or 0)

    for r in invs:
        try: invn = int(r["inv_no"])
        except: continue

        # ── Same fix as customer_ledger: use grand_total, not the
        # carry-forward-inclusive "total" field. ──
        raw_total     = float(r.get("total","0") or 0)
        pending_added = float(r.get("pending_added","0") or 0)
        if r.get("grand_total","") not in ("", None):
            total = float(r.get("grand_total","0") or 0)
        else:
            total = max(raw_total - pending_added, 0.0)

        was_transferred = str(r.get("remarks","")).startswith("Pending Transferred to Inv #")
        if was_transferred:
            continue  # settled via transfer — debt now lives in the destination invoice

        inv_pays = pay_map.get(invn, [])
        paid = min(total, payment_pool)
        payment_pool -= paid
        remaining = max(total - paid, 0.0)
        if remaining > 0:
            pending += remaining
            pending_invoices.append({
                "inv_no": str(invn),
                "date": r.get("date",""),
                "total": total,
                "paid": paid,
                "remaining": remaining
            })

    return jsonify({
        "pending": round(pending, 2),
        "pending_invoices": pending_invoices[-5:]  # last 5 unpaid invoices
    })

# ---------- Last Product Price ----------
@app.get("/api/last_product_price")
@login_required
def api_last_product_price():
    """Customer ke liye is EXACT product ki last date + price dhoondta hai.
    Agar product bilkul NAYA ho (is customer ko pehle kabhi nahi becha) to
    price ki jagah 'New' aur date ki jagah aaj ki date wapas bhejta hai.
    db_transaction() se proper commit/rollback (error aane par sab automatically
    rollback ho jata hai, koi partial/corrupt read nahi hota)."""
    name = to_caps(request.args.get("name",""))
    addr = to_caps(request.args.get("address",""))
    product = (request.args.get("product","") or "").strip()

    today_display = fmt_date(datetime.date.today())

    if not name or not addr or not product:
        return jsonify({"found": False, "is_new": True, "product": product,
                         "date": today_display, "unit_price": "New"})

    try:
        with db_transaction() as _c:
            _c.row_factory = sqlite3.Row
            rows = _c.execute("""
                SELECT i.date AS date, i.customer AS cust_name, i.customer_address AS cust_address,
                       ii.unit_price AS unit_price
                FROM invoice_items ii
                JOIN invoices i ON i.inv_no = ii.inv_no
                WHERE lower(trim(ii.product)) = lower(trim(?))
            """, (product,)).fetchall()
    except Exception as e:
        print("❌ api_last_product_price error (rolled back):", e)
        return jsonify({"found": False, "is_new": True, "product": product,
                         "date": today_display, "unit_price": "New"})

    matched = [r for r in rows if to_caps(r["cust_name"]) == name and to_caps(r["cust_address"]) == addr]

    if not matched:
        return jsonify({"found": False, "is_new": True, "product": product,
                         "date": today_display, "unit_price": "New"})

    def parse_d(d):
        for fmt in ("%Y-%m-%d","%d-%m-%y","%d-%m-%Y"):
            try: return datetime.datetime.strptime(d,fmt)
            except: pass
        return datetime.datetime.min

    matched.sort(key=lambda r: parse_d(r["date"]))
    last = matched[-1]
    return jsonify({"found": True, "is_new": False, "product": product,
                     "date": last["date"], "unit_price": last["unit_price"]})
# ================================================
@app.route("/payments", methods=["GET","POST"])
@login_required
def payments():
    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT inv_no, date, customer, customer_address, total
            FROM invoices
        """).fetchall()
    invs = [
        {"inv_no": r[0], "date": r[1], "name": r[2], "address": r[3], "total": r[4]}
        for r in _inv_rows
    ]
    pays = read_payments_db()

    # ================= POST =================
    if request.method == "POST":
        action = request.form.get("action","")

        # ===== ADD PAYMENT (TOP FORM) — AUTO FIFO SPLIT (shared helper) =====
        if action == "add_payment":
            try:
                inv_no = int(request.form.get("inv_no"))
                amount = float(request.form.get("amount") or 0)
                method = request.form.get("method","Cash")
                note_in = request.form.get("note","").strip()
                date_raw = request.form.get("date","").strip()

                inv_row   = next((i for i in invs if str(i.get("inv_no")) == str(inv_no)), {})
                cust_name = inv_row.get("name","")
                cust_addr = inv_row.get("address","")
                if not cust_name:
                    flash("Invoice not found")
                    return redirect(url_for("payments"))

                ok, msg = record_payment_fifo(cust_name, cust_addr, amount, method, date_raw, note_in)
                flash(msg)
                return redirect(url_for("payments"))

            except Exception as e:
                flash(f"Error adding payment: {e}")
                return redirect(url_for("payments"))

        # ===== DELETE (UNDO 7 DAYS) =====
        if action == "delete_payment":
            pid = request.form.get("pay_id")
            target = next((p for p in pays if str(p.get("pay_id")) == str(pid)), None)

            if target:
                try:
                    d = datetime.datetime.strptime(target.get("date"), "%d-%m-%y")
                    if (datetime.datetime.now() - d).days > 7:
                        flash("Undo limit exceeded (7 days)")
                        return redirect(url_for("payments"))
                except:
                    pass
                delete_payment_db(pid)

            flash("Payment undone")
            return redirect(url_for("payments"))

    # ================= CALCULATE =================
    from collections import defaultdict
    grouped = defaultdict(list)
    invs = sorted(invs, key=lambda x: int(x.get("inv_no",0)), reverse=True)

    def _month_label(d):
        for fmt in ("%d-%m-%Y","%d-%m-%y","%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(d, fmt).strftime("%B %Y")
            except:
                pass
        return "Unknown"

    for inv in invs:
        inv_no = int(inv.get("inv_no",0))
        total = float(inv.get("total",0))

        related = sorted(
            [p for p in pays if str(p.get("inv_no")) == str(inv_no)],
            key=lambda x: int(x.get("pay_id",0)),
            reverse=True
        )

        received = sum(float(p.get("amount",0)) for p in related)
        pending = total - received

        # ✅ allow overpaid
        if pending < 0:
            overpaid = abs(pending)
        else:
            overpaid = 0

        if pending < 0:
            overpaid = abs(pending)
            pending = 0
        else:
            overpaid = 0

        month = _month_label(inv.get("date",""))

        grouped[month].append({
            "inv_no": inv_no,
            "date": inv.get("date"),
            "name": inv.get("name"),
            "address": inv.get("address"),
            "total": total,
            "received": received,
            "pending": max(pending, 0),
            "overpaid": overpaid,
            "payments": related
        })

    def _month_sort_key(m):
        try: return datetime.datetime.strptime(m, "%B %Y")
        except: return datetime.datetime.min
    month_order = sorted(grouped.keys(), key=_month_sort_key, reverse=True)

    # ================= HTML =================
    html = TPL_H + """

<h3>💰 Payments System</h3>

<!-- TOP ADD PAYMENT -->
<form method="post" style="background:var(--card-bg);border:1px solid var(--border);box-shadow:var(--card-shadow);padding:18px;border-radius:var(--card-radius);margin-bottom:20px;">
<input type="hidden" name="action" value="add_payment">

<input id="search" placeholder="Search name / invoice" style="width:200px">

<select name="inv_no" id="invSelect" required>
<option value="">Select Invoice</option>
{% for i in invs %}
<option value="{{i.inv_no}}">
{{i.inv_no}} - {{i.name}} - {{i.address}}
</option>
{% endfor %}
</select>

<input name="date" type="date" id="payDate" required>

<input name="amount" type="number" placeholder="Amount" required>

<select name="method">
<option>Cash</option>
<option>Bank</option>
<option>JazzCash</option>
<option>EasyPaisa</option>
</select>

<input name="note" placeholder="Note">

<button class="btn">Add Payment</button>
</form>

<script>
document.getElementById("payDate").valueAsDate = new Date();
document.getElementById("search").addEventListener("input", function(){
 let q=this.value.toLowerCase();
 document.querySelectorAll("#invSelect option").forEach(o=>{
  o.style.display = o.text.toLowerCase().includes(q) ? "block":"none";
 });
});
</script>

<!-- TABLE -->
{% for month in month_order %}
{% set rows = grouped[month] %}
<h4 onclick="toggle('{{month|replace(' ','_')}}')" style="cursor:pointer;background:#333;color:#fff;padding:8px;">
📂 {{month}} <small style="opacity:.7">({{rows|length}} invoice{{'s' if rows|length!=1 else ''}})</small>
</h4>

<div id="m_{{month|replace(' ','_')}}" style="display:none">

<table style="width:100%;border-collapse:collapse;">
<tr style="background:linear-gradient(135deg,#0d3b34,#0f5c52);color:#fff;">
<th>Inv</th><th>Name</th><th>Total</th>
<th>Received</th><th>Pending</th><th>Overpaid</th>
<th>History</th>
</tr>

{% for r in rows %}
<tr>
<td>{{r.inv_no}}</td>
<td>{{r.name}}<br><small>{{r.address}}</small></td>
<td>{{r.total}}</td>
<td>{{r.received}}</td>
<td style="color:red">{{r.pending}}</td>
<td style="color:green">{{r.overpaid}}</td>

<td>
<button onclick="showHistory({{r.inv_no}})">View</button>
<button ondblclick="undoPayment({{r.inv_no}})">Undo</button>
</td>
</tr>
{% endfor %}
</table>

</div>
{% endfor %}

<script>
function toggle(m){
 let el=document.getElementById("m_"+m);
 el.style.display = el.style.display=="none"?"block":"none";
}

function showHistory(inv){
 fetch("/api/payment_history?inv_no="+inv)
 .then(r=>r.json())
 .then(d=>{
  let msg="Payment History:\\n";
  d.forEach(p=>{
    msg += p.date+" | Rs "+p.amount+" | "+p.method+"\\n"+p.note+"\\n---\\n";
  });
  alert(msg);
 });
}
</script>
<script>
function undoPayment(inv){
  if(confirm("Undo last payment?")){
    fetch("/undo_last_payment?inv_no="+inv)
    .then(()=>location.reload());
  }
}
</script>

""" + TPL_F

    return render_template_string(html, grouped=grouped, invs=invs, month_order=month_order)
# ======================
@app.route("/undo_last_payment")
def undo_last_payment():
    inv_no = request.args.get("inv_no")
    pays = read_payments_db()

    target_pid = None
    for i in range(len(pays)-1, -1, -1):
        if str(pays[i].get("inv_no")) == str(inv_no):
            target_pid = pays[i].get("pay_id")
            break

    if target_pid:
        delete_payment_db(target_pid)

    return "ok"
#==========================
@app.route("/api/payment_history")
def payment_history():
    inv_no = request.args.get("inv_no")
    pays = read_payments_db()

    rows = [p for p in pays if str(p.get("inv_no")) == str(inv_no)]
    return jsonify(rows)
# ========== PAYMENT RECEIPT (Print) =============
# ================================================
@app.route("/payment_receipt/<int:inv_no>", methods=["GET","POST"])
@login_required
def payment_receipt(inv_no):
    """Generate printable Payment Receipt for a specific invoice payment."""
    with db_transaction() as _c:
        _row = _c.execute("""
            SELECT inv_no, date, customer, customer_address, customer_phone, total
            FROM invoices WHERE inv_no=?
        """, (str(inv_no),)).fetchone()
    inv = None
    if _row:
        inv = {"inv_no": _row[0], "date": _row[1], "name": _row[2], "address": _row[3],
               "phone": _row[4], "total": _row[5]}
    if not inv:
        flash("Invoice not found"); return redirect(url_for("payments"))

    pays = read_payments_db()
    inv_pays = [p for p in pays if str(p.get("inv_no","")) == str(inv_no)]
    total    = float(inv.get("total","0") or 0)
    received = sum(float(p.get("amount","0") or 0) for p in inv_pays)
    pending  = max(total - received, 0.0)

    # POST = save new payment then show receipt
    if request.method == "POST":
        amt_raw = request.form.get("new_amount","").strip()
        method  = request.form.get("new_method","Cash")
        note    = request.form.get("new_note","").strip()
        try:
            amt = float(amt_raw)
        except:
            flash("Invalid amount"); return redirect(url_for("payment_receipt", inv_no=inv_no))
        if amt <= 0:
            flash("Amount must be positive"); return redirect(url_for("payment_receipt", inv_no=inv_no))

        with db_transaction() as _c4:
            insert_payment_db(_c4, inv_no, fmt_date(), amt, method,
                               inv.get("name",""), inv.get("address",""), note)
        received += amtG4851

        pending   = max(total - received, 0.0)
        flash(f"Payment Rs {amt:,.0f} recorded.")
        # Refresh
        inv_pays = read_payments_db()
        inv_pays = [p for p in inv_pays if str(p.get("inv_no","")) == str(inv_no)]

    company = get_setting("company_name","SEIZE")
    cust    = to_caps(inv.get("name",""))
    addr    = to_caps(inv.get("address",""))
    phone   = inv.get("phone","")

    # ── Recover the ACTUAL original payment amount, same de-fragmentation
    # logic used in Customer Ledger. record_payment_fifo() stamps every
    # split row of one payment with the same batch_id. Group by that
    # across ALL payments (not just this invoice) so this page shows what
    # the customer actually paid, not the split fragment that happened to
    # land on this invoice. Rows from before batch_id existed fall back to
    # grouping by (date, note). ──
    all_pays_now = read_payments_db()
    payment_groups_global = {}
    for _p in all_pays_now:
        _bid = _p.get("batch_id","")
        _gkey = ("B", _bid) if _bid else ("DN", _p.get("date",""), _p.get("note",""))
        payment_groups_global[_gkey] = payment_groups_global.get(_gkey, 0.0) + float(_p.get("amount","0") or 0)

    # Build payment rows HTML
    pay_rows_html = ""
    for p in inv_pays:
        frag_amt = float(p.get('amount',0) or 0)
        _bid     = p.get("batch_id","")
        gkey     = ("B", _bid) if _bid else ("DN", p.get("date",""), p.get("note",""))
        full_amt = payment_groups_global.get(gkey, frag_amt)
        split_note = ""
        if full_amt > frag_amt + 0.01:
            split_note = f"<div style='font-size:11px;color:#94a3b8;font-weight:500;margin-top:2px'>Split · Rs {frag_amt:,.0f} applied to Inv #{inv_no}</div>"
        pay_rows_html += f"""
        <tr>
          <td style="padding:9px 12px">{p.get('date','')}</td>
          <td style="padding:9px 12px;font-weight:700;color:#1a4a2e">Rs {full_amt:,.0f}{split_note}</td>
          <td style="padding:9px 12px">{p.get('method','')}</td>
          <td style="padding:9px 12px;color:#555">{p.get('note','') or '—'}</td>
          <td style="padding:9px 12px;text-align:center">
            <a href="{url_for('print_single_receipt', pay_id=p.get('pay_id',''))}" target="_blank"
               style="background:#0d2818;color:white;padding:5px 10px;border-radius:6px;font-size:12px;font-weight:700;text-decoration:none">🖨 Print</a>
          </td>
        </tr>"""

    receipt_html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Payment Receipt — Invoice #{inv_no}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:linear-gradient(160deg,#eef5f0,#e6f0ea);padding:20px}}
.wrap{{max-width:820px;margin:auto}}
.bar{{background:linear-gradient(120deg,#0d3b2e,#1a4a2e 45%,#2d6b45 75%,#3f8f5c);color:white;padding:18px 24px;border-radius:16px 16px 0 0;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;box-shadow:0 4px 14px rgba(13,40,24,.25);position:relative;overflow:hidden}}
.bar::after{{content:'';position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#6dbf82,#f5c542,#4aa3ff,#6dbf82)}}
.card{{background:white;border-radius:0 0 16px 16px;box-shadow:0 12px 40px rgba(13,40,24,.18);overflow:hidden;border:1px solid #e5efe8;border-top:none}}
.info-row{{display:grid;grid-template-columns:1fr 1fr;border-bottom:2px solid #eef2f5;background:linear-gradient(90deg,#f8fbf9,#ffffff)}}
.ib{{padding:16px 24px}}.ib:last-child{{border-left:1px solid #eef2f5;text-align:right}}
.lbl{{font-size:10px;font-weight:700;color:#7d93a8;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}}
.val{{font-size:15px;font-weight:700;color:#0d2818}}.sub{{font-size:12px;color:#64748b;margin-top:2px}}
.summary-bar{{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:2px solid #eef2f5}}
.sum-cell{{padding:16px 20px;text-align:center;border-right:1px solid #eef2f5;position:relative;transition:transform .15s}}
.sum-cell:hover{{transform:translateY(-2px)}}
.sum-cell:nth-child(1){{background:linear-gradient(180deg,#eef4ff,#ffffff);border-top:3px solid #4aa3ff}}
.sum-cell:nth-child(2){{background:linear-gradient(180deg,#eafaf0,#ffffff);border-top:3px solid #2d6b45}}
.sum-cell:nth-child(3){{background:linear-gradient(180deg,#fff3ec,#ffffff);border-top:3px solid #ff8a4c}}
.sum-cell:last-child{{border-right:none}}
.sum-lbl{{font-size:10px;font-weight:700;color:#7d93a8;text-transform:uppercase;margin-bottom:4px;letter-spacing:.5px}}
.sum-val{{font-size:22px;font-weight:900}}
table{{width:100%;border-collapse:collapse}}
thead tr{{background:linear-gradient(90deg,#0d2818,#1a4a2e);color:#a8d5b0}}
th{{padding:11px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.5px}}
tbody tr{{border-bottom:1px solid #f1f5f9;transition:background .15s}}
tbody tr:nth-child(even){{background:#f6faf7}}
tbody tr:hover{{background:#eaf6ee}}
.add-form{{background:linear-gradient(135deg,#f0f9f4,#e8f5ee);padding:20px 24px;border-top:2px solid #e2e8f0}}
.add-form h4{{font-size:14px;font-weight:700;color:#0d2818;margin-bottom:14px}}
.form-row{{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}}
.form-row label{{font-size:11px;font-weight:700;color:#64748b;display:block;margin-bottom:4px;text-transform:uppercase}}
.form-row input,.form-row select{{padding:9px 12px;border:1.5px solid #d7e4dc;border-radius:8px;font-size:13px;background:white;transition:border-color .15s}}
.form-row input:focus,.form-row select:focus{{outline:none;border-color:#2d6b45}}
.actions{{display:flex;gap:11px;padding:18px 24px;background:linear-gradient(90deg,#f8fafc,#f1f6f3);border-top:2px solid #e2e8f0;flex-wrap:wrap}}
.btn{{padding:11px 20px;border:none;border-radius:9px;cursor:pointer;font-size:13px;font-weight:700;text-decoration:none;display:inline-flex;align-items:center;gap:5px;box-shadow:0 3px 8px rgba(0,0,0,.12);transition:transform .15s,box-shadow .15s,opacity .15s}}
.btn:hover{{opacity:.92;transform:translateY(-2px);box-shadow:0 6px 14px rgba(0,0,0,.18)}}
@media(max-width:600px){{.info-row{{grid-template-columns:1fr}}.summary-bar{{grid-template-columns:1fr}}.form-row{{flex-direction:column}}}}
</style></head><body>
<div class="wrap">
  <div class="bar">
    <div><div style="font-size:11px;color:#a8d5b0;margin-bottom:3px">Payment Receipts</div><div style="font-family:Georgia,serif;font-size:20px;font-weight:900">{company}</div></div>
    <div style="font-size:26px;font-weight:900;color:#6dbf82">Invoice #{inv_no}</div>
  </div>
  <div class="card">
    <div class="info-row">
      <div class="ib"><div class="lbl">Customer</div><div class="val">{cust}</div><div class="sub">{addr}</div><div class="sub">📞 {phone or '—'}</div></div>
      <div class="ib"><div class="lbl">Invoice Date</div><div class="val">{inv.get('date','')}</div><div class="sub">Total Items in Invoice</div></div>
    </div>
    <div class="summary-bar">
      <div class="sum-cell"><div class="sum-lbl">Invoice Total</div><div class="sum-val" style="color:#0d2818">Rs {total:,.0f}</div></div>
      <div class="sum-cell"><div class="sum-lbl">Total Received</div><div class="sum-val" style="color:#2d6b45">Rs {received:,.0f}</div></div>
      <div class="sum-cell"><div class="sum-lbl">Balance Due</div><div class="sum-val" style="color:{'#c0392b' if pending>0 else '#2d6b45'}">{'Rs {:,.0f}'.format(pending) if pending>0 else '✓ Clear'}</div></div>
    </div>

    <div style="padding:18px 24px 8px">
      <div style="font-size:13px;font-weight:700;color:#0d2818;margin-bottom:10px">📜 Payment History</div>
    </div>
    <table>
      <thead><tr><th>Date</th><th>Amount</th><th>Method</th><th>Note</th><th style="text-align:center">Receipt</th></tr></thead>
      <tbody>
        {pay_rows_html if pay_rows_html else "<tr><td colspan='5' style='text-align:center;padding:24px;color:#94a3b8'>No payments recorded yet</td></tr>"}
      </tbody>
    </table>

    <!-- Add New Payment -->
    <div class="add-form">
      <h4>➕ New Payment Receive Karein</h4>
      <form method="post">
        <div class="form-row">
          <div><label>Amount (Rs) *</label><input name="new_amount" type="number" step="any" min="0.01" placeholder="0" required style="width:140px"></div>
          <div><label>Payment Method</label>
            <select name="new_method">
              <option value="Cash">💵 Cash</option>
              <option value="Bank Transfer">🏦 Bank Transfer</option>
              <option value="JazzCash">📱 JazzCash</option>
              <option value="EasyPaisa">📱 EasyPaisa</option>
              <option value="Cheque">📄 Cheque</option>
              <option value="Online">🌐 Online</option>
            </select>
          </div>
          <div><label>Note (optional)</label><input name="new_note" placeholder="e.g. partial payment" style="width:200px"></div>
          <div style="margin-top:20px"><button type="submit" class="btn" style="background:linear-gradient(135deg,#1a4a2e,#2d6b45);color:white">✓ Save Payment & Print Receipt</button></div>
        </div>
      </form>
    </div>

    <div class="actions">
      <a href="{url_for('customer_ledger', name=inv.get('name',''), address=addr)}" class="btn" style="background:linear-gradient(135deg,#6a1b9a,#7b1fa2);color:white">📋 Customer Ledger</a>
      <a href="{url_for('payments')}" class="btn" style="background:#1565c0;color:white">💳 All Payments</a>
      <a href="{url_for('invoices_list')}" class="btn" style="background:#e2e8f0;color:#374151">📂 All Invoices</a>
    </div>
  </div>
</div>
</body></html>"""
    return receipt_html


# ================================================
# ========== PRINT SINGLE RECEIPT (PDF-like) ====
# ================================================
@app.route("/print_receipt/<pay_id>")
@login_required
def print_single_receipt(pay_id):
    """Print a single payment receipt."""
    pays = read_payments_db()
    pay  = next((p for p in pays if str(p.get("pay_id","")) == str(pay_id)), None)
    if not pay:
        flash("Receipt not found"); return redirect(url_for("payments"))

    inv_no = pay.get("inv_no","")
    with db_transaction() as _c:
        _row = _c.execute("""
            SELECT inv_no, customer, customer_address, customer_phone, total
            FROM invoices WHERE inv_no=?
        """, (str(inv_no),)).fetchone()
    inv = None
    if _row:
        inv = {"inv_no": _row[0], "name": _row[1], "address": _row[2],
               "phone": _row[3], "total": _row[4]}

    cust    = to_caps(pay.get("customer","") or (inv.get("name","") if inv else ""))
    addr    = to_caps(pay.get("address","") or (inv.get("address","") if inv else ""))
    phone   = inv.get("phone","") if inv else ""
    company = get_setting("company_name","SEIZE")
    frag_amt = float(pay.get("amount","0") or 0)
    method  = pay.get("method","")
    note    = pay.get("note","")
    date    = pay.get("date","")
    batch_id = pay.get("batch_id","")

    # Total & pending
    pays_all  = read_payments_db()
    total     = float(inv.get("total","0") or 0) if inv else 0
    total_rcv = sum(float(p.get("amount","0") or 0) for p in pays_all if str(p.get("inv_no","")) == str(inv_no))
    balance   = max(total - total_rcv, 0.0)

    # ── Recover the ACTUAL original payment amount (same de-fragmentation
    # logic as Customer Ledger / Payment Receipt page). If this payment was
    # FIFO-split across multiple invoices, show what the customer actually
    # paid, not just the fragment that landed on this specific invoice.
    # Prefer batch_id (robust); fall back to (date, note) for old rows. ──
    if batch_id:
        full_amt = sum(float(p.get("amount","0") or 0) for p in pays_all if p.get("batch_id","") == batch_id)
    else:
        full_amt = sum(
            float(p.get("amount","0") or 0) for p in pays_all
            if p.get("date","") == date and p.get("note","") == note
        )
    is_split = full_amt > frag_amt + 0.01
    amt = full_amt if is_split else frag_amt
    split_line = (f'<div class="method-badge" style="background:rgba(255,255,255,.1);margin-top:4px">'
                  f'Split payment · Rs {frag_amt:,.0f} applied to Inv #{inv_no}</div>') if is_split else ""

    receipt_no = f"RCP-{pay_id}"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Payment Receipt {receipt_no}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#fff;padding:30px;max-width:560px;margin:auto}}
.logo{{font-family:Georgia,serif;font-size:26px;font-weight:900;color:#0d2818;margin-bottom:2px}}
.logo span{{color:#2d6b45}}
.title{{font-size:14px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:18px;padding-bottom:12px;border-bottom:2px solid #0d2818}}
.info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:18px;padding:16px;background:#f8fafc;border-radius:10px}}
.ig-block .lbl{{font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin-bottom:3px}}
.ig-block .val{{font-size:14px;font-weight:700;color:#0d2818}}.ig-block .sub{{font-size:12px;color:#64748b}}
.amount-box{{background:linear-gradient(135deg,#0d2818,#1a4a2e);color:white;border-radius:12px;padding:18px 24px;text-align:center;margin-bottom:18px}}
.amt-lbl{{font-size:11px;color:#a8d5b0;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px}}
.amt-val{{font-size:36px;font-weight:900;color:#6dbf82}}
.method-badge{{display:inline-block;background:rgba(255,255,255,.15);border-radius:20px;padding:4px 12px;font-size:13px;margin-top:6px}}
.detail-row{{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #f1f5f9;font-size:13px}}
.detail-row .lbl{{color:#94a3b8;font-weight:600}}.detail-row .val{{font-weight:700;color:#0d2818}}
.balance{{background:{'#fee2e2' if balance>0 else '#d1fae5'};border-radius:10px;padding:12px 18px;margin-top:14px;display:flex;justify-content:space-between;align-items:center}}
.bal-lbl{{font-size:13px;font-weight:700;color:{'#c0392b' if balance>0 else '#065f46'}}}
.bal-val{{font-size:18px;font-weight:900;color:{'#c0392b' if balance>0 else '#065f46'}}}
.sig-row{{display:flex;justify-content:space-between;margin-top:36px}}
.sig{{text-align:center;width:160px;border-top:1.5px solid #374151;padding-top:7px;font-size:11px;color:#64748b}}
.footer{{margin-top:22px;padding-top:14px;border-top:1px solid #e2e8f0;text-align:center;font-size:11px;color:#94a3b8}}
.thanks{{font-family:Georgia,serif;font-size:20px;font-style:italic;color:#1a4a2e;text-align:center;margin-top:16px}}
@media print{{body{{padding:10px;max-width:100%}}button{{display:none}}}}
</style></head><body>
<div class="logo">"SEIZE"<span>.</span></div>
<div class="title">Payment Receipt</div>
<div class="info-grid">
  <div class="ig-block"><div class="lbl">Receipt No.</div><div class="val">{receipt_no}</div></div>
  <div class="ig-block"><div class="lbl">Date</div><div class="val">{date}</div></div>
  <div class="ig-block"><div class="lbl">Invoice #</div><div class="val">#{inv_no}</div></div>
  <div class="ig-block"><div class="lbl">Invoice Total</div><div class="val">Rs {total:,.0f}</div></div>
</div>
<div class="ig-block" style="margin-bottom:18px;padding:12px 16px;background:#f8fafc;border-radius:10px">
  <div class="lbl">Customer</div>
  <div class="val" style="font-size:17px">{cust}</div>
  <div class="sub">{addr} {'| 📞 '+phone if phone else ''}</div>
</div>
<div class="amount-box">
  <div class="amt-lbl">Amount Received</div>
  <div class="amt-val">Rs {amt:,.0f}</div>
  <div class="method-badge">💳 {method}</div>
  {split_line}
</div>
<div class="detail-row"><span class="lbl">Total Paid to Date:</span><span class="val" style="color:#2d6b45">Rs {total_rcv:,.0f}</span></div>
{f'<div class="detail-row"><span class="lbl">Note:</span><span class="val">{note}</span></div>' if note else ''}
<div class="balance">
  <div class="bal-lbl">{'⚠ Balance Due' if balance>0 else '✅ Fully Cleared'}</div>
  <div class="bal-val">{'Rs {:,.0f}'.format(balance) if balance>0 else 'PAID IN FULL'}</div>
</div>
<div class="sig-row">
  <div class="sig">Customer Signature</div>
  <div class="sig">Received By</div>
</div>
<div class="thanks">Thank You</div>
<div style="font-size:11px;color:#94a3b8;text-align:center;font-weight:600;letter-spacing:1px;margin-top:4px">FOR YOUR BUSINESS</div>
<div class="footer">{company} &nbsp;|&nbsp; www.seizecompany.com &nbsp;|&nbsp; +923......</div>
<br><div style="text-align:center"><button onclick="window.location.href='/invoice/new'" style="background:#64748b;color:white;padding:11px 28px;border:none;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;margin-right:10px">⬅ Back</button><button onclick="window.print()" style="background:#0d2818;color:white;padding:11px 28px;border:none;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer">🖨 Print Receipt</button></div>
<script>window.onload=()=>window.print();</script>
</body></html>"""
    return html
def draw_ledger_pdf(out_path: Path, company: str, cust_name: str, cust_addr: str, cust_phone: str,
                     today_str: str, rows_data: list, total_billed: float,
                     total_received: float, total_pending: float) -> Path:
    """Customer Ledger ka PDF banata hai aur disk par save karta hai (auto-save)."""
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                             topMargin=15*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    elems = []

    title_style = ParagraphStyle('LedgerTitle', parent=styles['Title'], fontSize=18,
                                  textColor=colors.HexColor("#4a148c"))
    elems.append(Paragraph(company.upper(), title_style))
    elems.append(Paragraph("Customer Ledger Statement", styles['Heading3']))
    elems.append(Spacer(1, 6*mm))

    info = styles['Normal']
    elems.append(Paragraph(f"<b>Customer:</b> {cust_name}", info))
    elems.append(Paragraph(f"<b>Address:</b> {cust_addr}", info))
    if cust_phone:
        elems.append(Paragraph(f"<b>Phone:</b> {cust_phone}", info))
    elems.append(Paragraph(f"<b>Generated:</b> {today_str}", info))
    elems.append(Spacer(1, 6*mm))

    data = [["Inv#", "Date", "Total (Rs)", "Received (Rs)", "Pending (Rs)", "Balance (Rs)"]]
    for r in rows_data:
        data.append([
            f"#{r['inv_no']}", r['date'],
            f"{r['total']:,.0f}", f"{r['received']:,.0f}",
            ("Clear" if r['pending'] <= 0 else f"{r['pending']:,.0f}"),
            f"{r['balance']:,.0f}"
        ])
    data.append(["", "TOTAL", f"{total_billed:,.0f}", f"{total_received:,.0f}", f"{total_pending:,.0f}", ""])

    tbl = Table(data, colWidths=[18*mm, 25*mm, 30*mm, 30*mm, 30*mm, 30*mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4a148c")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor("#dddddd")),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#f3e5f5")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor("#4a148c")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor("#faf9fb")]),
    ]))
    elems.append(tbl)
    doc.build(elems)
    return out_path
# ========== CUSTOMER LEDGER =====================

@app.route("/customer_ledger", methods=["GET","POST"])
@login_required
def customer_ledger():
    if request.method == "POST" and request.form.get("action") == "add_payment":
        _name = request.form.get("name","")
        _addr = request.form.get("address","")
        _amount = float(request.form.get("amount") or 0)
        _method = request.form.get("method","Cash")
        _date_raw = request.form.get("date","").strip()
        _note = request.form.get("note","").strip()
        ok, msg = record_payment_fifo(_name, _addr, _amount, _method, _date_raw, _note)
        flash(msg)
        return redirect(url_for("customer_ledger", name=_name, address=_addr))

    name = to_caps(request.args.get("name","").strip())
    from_date = request.args.get("from_date","").strip()
    addr = to_caps(request.args.get("address","").strip())

    custs_all = load_customers()

    # If no customer selected, show picker
    if not name:
        html = TPL_H + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="/">Dashboard</a> › Customer Ledger</div>
    <h2>📒 Customer Ledger</h2>
    <p>Customer chunein ya search karein statement dekhne ke liye</p>
  </div>
</div>

<div class="card mb-3">
  <form method="get" class="form-row form-row-3" style="align-items:end">
    <div class="form-group" style="margin-bottom:0">
      <label class="form-label">Customer Name</label>
      <input name="name" list="cn" class="form-control" placeholder="Type or select customer" required>
      <datalist id="cn">{% for c in custs %}<option value="{{c.name}}">{% endfor %}</datalist>
    </div>
    <div class="form-group" style="margin-bottom:0">
      <label class="form-label">Address</label>
      <input name="address" list="ca" class="form-control" placeholder="Address">
      <datalist id="ca">{% for c in custs %}<option value="{{c.address}}">{% endfor %}</datalist>
    </div>
    <button class="btn btn-primary" style="height:38px">📒 View Ledger</button>
  </form>
</div>

<div class="card p-0">
  <div class="table-wrap">
    <table>
      <thead><tr><th>Customer</th><th>Address</th><th>Phone</th><th>Ledger</th></tr></thead>
      <tbody>
      {% for c in custs %}
      <tr>
        <td class="fw-bold">{{c.name}}</td>
        <td class="text-muted">{{c.address}}</td>
        <td>{{c.phone}}</td>
        <td>
          <a href="{{ url_for('customer_ledger', name=c.name, address=c.address) }}" class="btn btn-sm" style="background:#6a1b9a;color:white">
            📒 Ledger
          </a>
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>""" + TPL_F
        return render_template_string(html, custs=custs_all, project=get_setting("project_name"))

    # Load invoices + payments for this customer (ab SQLite se)
    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT inv_no, date, customer, customer_address, grand_total, total,
                   pending_added, remarks
            FROM invoices
        """).fetchall()
    invs = [
        {
            "inv_no": r[0], "date": r[1], "name": r[2], "address": r[3],
            "grand_total": r[4], "total": r[5], "pending_added": r[6], "remarks": r[7]
        }
        for r in _inv_rows
    ]
    cust_invs = [r for r in invs if to_caps(r.get("name","")) == name and to_caps(r.get("address","")) == addr]
    pays = read_payments_db()
    pay_map = {}
    for p in pays:
        try:
            i = int(p["inv_no"])
            pay_map.setdefault(i, []).append(p)
        except: pass

    # ── Group FIFO-split payments back into their ORIGINAL full-amount
    # transaction. record_payment_fifo() stamps every split row of one
    # payment with the same batch_id, so grouping by that reconstructs
    # exactly what the customer actually paid in one go. Shown to the
    # customer as ONE entry (on the earliest invoice it touched) instead of
    # scattered fragments — the internal split still drives Received/Pending
    # math correctly, only the customer-facing display is de-fragmented.
    # Rows from before the batch_id column existed fall back to grouping by
    # (date, note), which was the original approach. ──
    payment_groups = {}
    for invn_key, plist in pay_map.items():
        for p in plist:
            bid = p.get("batch_id","")
            gkey = ("B", bid) if bid else ("DN", p.get("date",""), p.get("note",""))
            g = payment_groups.setdefault(gkey, {"amount": 0.0, "method": p.get("method",""), "invs": set()})
            g["amount"] += float(p.get("amount","0") or 0)
            g["invs"].add(invn_key)

    rows_data = []
    total_billed   = 0.0
    total_received = 0.0
    total_pending  = 0.0
    running_balance = 0.0

    # Sort by date
    def parse_d(d):
        for fmt in ("%Y-%m-%d","%d-%m-%y","%d-%m-%Y"):
            try: return datetime.datetime.strptime(d,fmt)
            except: pass
        return datetime.datetime.min

    cust_invs.sort(key=lambda r: parse_d(r.get("date","")))
    opening_balance = 0.0

    _order = [int(r["inv_no"]) for r in cust_invs if str(r.get("inv_no","")).strip().isdigit()]
    for g in payment_groups.values():
        g["first_inv"] = next((iv for iv in _order if iv in g["invs"]), None)

    payment_pool = 0.0
    for _r in cust_invs:
        try: _invn = int(_r["inv_no"])
        except: continue
        for _p in pay_map.get(_invn, []):
            payment_pool += float(_p.get("amount","0") or 0)

    for r in cust_invs:
        try: invn = int(r["inv_no"])
        except: continue

        # ── FIX: use grand_total (this invoice's OWN new sale amount only) ──
        # "total" field can already include carried-forward pending from an
        # earlier invoice (pending_added), which would double/triple count
        # the same pending across the ledger's running balance. grand_total
        # never includes pending_added, so summing it can never double count,
        # no matter how many times pending was carried forward.
        raw_total     = float(r.get("total","0") or 0)
        pending_added = float(r.get("pending_added","0") or 0)
        if r.get("grand_total","") not in ("", None):
            inv_total = float(r.get("grand_total","0") or 0)
        else:
            # Older rows without a grand_total column: derive it
            inv_total = max(raw_total - pending_added, 0.0)

        # ── FIX: if this invoice's pending was transferred forward into a
        # later invoice (remarks set by add_pending_to_invoice), treat it as
        # settled here — the debt now lives in the destination invoice's
        # grand_total via pending_added, so counting it again here would be
        # the double-counting bug.
        was_transferred = str(r.get("remarks","")).startswith("Pending Transferred to Inv #")

        inv_pays  = pay_map.get(invn, [])
        if was_transferred:
            inv_rcvd = inv_total  # settled via transfer, not a cash payment
        else:
            inv_rcvd = min(inv_total, payment_pool)
            payment_pool -= inv_rcvd
        inv_pend  = 0.0 if was_transferred else max(inv_total - inv_rcvd, 0.0)
        # Ledger Calculation
        total_billed += inv_total
        total_received += inv_rcvd

        running_balance = total_billed - total_received
        total_pending = running_balance

        # Payment detail rows — full original amount, shown once
        pay_details = []
        _shown_groups = set()
        for p in sorted(inv_pays, key=lambda x: x.get("date","")):
            bid = p.get("batch_id","")
            gkey = ("B", bid) if bid else ("DN", p.get("date",""), p.get("note",""))
            g = payment_groups.get(gkey)
            if g and gkey not in _shown_groups:
                if g["first_inv"] == invn:
                    pay_details.append({
                        "date":   p.get("date",""),
                        "amount": g["amount"],   # FULL original amount, not the split fragment
                        "method": p.get("method",""),
                        "pay_id": p.get("pay_id",""),
                    })
                    _shown_groups.add(gkey)
                else:
                    # part of a payment already shown in full on an earlier invoice — skip duplicate
                    _shown_groups.add(gkey)
            elif not g:
                pay_details.append({
                    "date":   p.get("date",""),
                    "amount": float(p.get("amount","0") or 0),
                    "method": p.get("method",""),
                    "pay_id": p.get("pay_id",""),
                })
        if was_transferred:
            pay_details.append({
                "date":   r.get("date",""),
                "amount": inv_total,
                "method": "Transferred to Inv #" + str(r.get("remarks","")).split("#")[-1].strip(),
                "pay_id": "",
            })

        rows_data.append({
            "inv_no":   invn,
            "date":     r.get("date",""),
            "total":    inv_total,
            "received": inv_rcvd,
            "pending":  inv_pend,
            "balance":  running_balance,
            "payments": pay_details,
        })

    # find customer phone
    cust_obj = next((c for c in custs_all if to_caps(c["name"]) == name), {})
    phone = cust_obj.get("phone","")

    company = get_setting("SEIZE","SEIZE")
    today_str = datetime.date.today().strftime("%d %b %Y")

    # ── AUTO-SAVE LEDGER PDF (har baar ledger khulte hi latest PDF disk pe save hoti hai) ──
    ledger_pdf_path = RECORDS_DIR / "Ledgers" / f"LEDGER_{safe_name(name)}_{safe_name(addr)}.pdf"
    try:
        draw_ledger_pdf(ledger_pdf_path, company, name, addr, phone, today_str,
                         rows_data, total_billed, total_received, total_pending)
    except Exception as e:
        print("❌ Ledger PDF auto-save error:", e)

    # Build rows HTML
    if from_date:
        fd = parse_d(from_date)
        opening_balance = sum(r["pending"] for r in rows_data if parse_d(r["date"]) < fd)
        rows_data = [r for r in rows_data if parse_d(r["date"]) >= fd]
    rows_data = list(reversed(rows_data))
    rows_html = ""
    for r in rows_data:
        pay_detail_str = ""
        for p in r["payments"]:
            pay_detail_str += f"<span class='pay-chip'>{p['date']} · Rs {p['amount']:,.0f} ({p['method']})</span>"
        if not pay_detail_str:
            pay_detail_str = "<span class='no-pay'>No payment yet</span>"

        pend_color = "#b3261e" if r["pending"] > 0 else "#1c6b45"
        row_bg = "background:#fdf8f0;" if r["pending"] > 0 else ""
        rows_html += f"""
        <tr style="{row_bg}">
          <td class="c-inv">#{r['inv_no']}</td>
          <td class="c-date">{r['date']}</td>
          <td class="c-num c-total">Rs {r['total']:,.0f}</td>
          <td class="c-num c-received">Rs {r['received']:,.0f}</td>
          <td class="c-num c-pending" style="color:{pend_color}">{'Rs {:,.0f}'.format(r['pending']) if r['pending']>0 else '✓ Clear'}</td>
          <td class="c-num c-balance">Rs {r['balance']:,.0f}</td>
          <td class="c-pay">{pay_detail_str}</td>
          <td class="c-action no-print">
            <a href="{url_for('payment_receipt', inv_no=r['inv_no'])}" class="row-btn">💳 Pay / Receipt</a>
          </td>
        </tr>"""

    if not rows_html:
        rows_html = "<tr><td colspan='8' style='text-align:center;padding:40px;color:#9aa3ab'>Is customer ka koi invoice nahi</td></tr>"

    ledger_html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ledger — {name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --ink:#10302b; --muted:#5f7a75; --line:#dde8e5;
  --brand:#0d3b34; --brand-2:#0d9488; --accent:#f5a524;
  --danger:#e11d48; --paper:#ffffff; --bg:#f3f7f6;
}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--ink);padding:24px}}
.wrap{{max-width:1120px;margin:auto}}

/* header */
.bar{{background:linear-gradient(135deg,#0b2b27,#0f3d37);color:#fff;padding:22px 28px;border-radius:14px 14px 0 0;
     display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:14px}}
.bar .kicker{{font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:#f5c877;margin-bottom:4px}}
.bar .cust-name{{font-family:Georgia,'Times New Roman',serif;font-size:23px;font-weight:700}}
.bar .cust-sub{{font-size:13px;color:#cfe6e0;margin-top:3px}}
.bar .company{{font-size:18px;font-weight:800;color:#f5a524}}
.bar .meta{{font-size:12px;color:#cfe6e0;margin-top:3px}}

.card{{background:var(--paper);border-radius:0 0 14px 14px;box-shadow:0 10px 30px rgba(20,35,26,.10);overflow:hidden;border:2px solid var(--brand)}}

/* summary */
.summary-bar{{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--line)}}
.sum-cell{{padding:18px 20px;text-align:center;border-right:1px solid var(--line)}}
.sum-cell:last-child{{border-right:none}}
.sum-lbl{{font-size:10.5px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}}
.sum-val{{font-size:23px;font-weight:800;font-variant-numeric:tabular-nums}}

/* table */
.tbl-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
thead tr{{background:var(--brand);color:#c9e0d2}}
th{{padding:12px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.6px;white-space:nowrap;font-weight:700}}
th.c-num, td.c-num{{text-align:right}}
tbody tr{{border-bottom:1px solid var(--line)}}
tbody tr:last-child{{border-bottom:none}}
td{{padding:12px 14px;vertical-align:middle}}
.c-inv{{font-weight:700;color:var(--brand)}}
.c-date{{color:var(--muted);white-space:nowrap}}
.c-total{{font-weight:700}}
.c-received{{color:var(--brand-2);font-weight:600}}
.c-pending{{font-weight:700}}
.c-balance{{font-weight:800;color:var(--brand)}}
.c-pay{{max-width:230px}}
.pay-chip{{display:inline-block;background:#e7f4ec;color:#155a34;border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600;margin:2px}}
.no-pay{{color:#9aa3ab;font-size:12px}}
.row-btn{{background:var(--brand);color:#fff;padding:6px 12px;border-radius:6px;font-size:12px;font-weight:700;text-decoration:none;white-space:nowrap;display:inline-block}}
.row-btn:hover{{opacity:.85}}

tfoot tr{{background:var(--brand);color:#fff}}
tfoot td{{padding:14px;font-weight:700}}
.tot-billed{{font-size:15.5px;font-weight:900}}
.tot-received{{color:#a7e3bf}}
.tot-pending{{color:#f6b4ae;font-weight:900}}

/* actions bar (screen only) */
.actions{{display:flex;gap:10px;padding:18px 24px;background:#f7f9f7;border-top:1px solid var(--line);flex-wrap:wrap}}
.btn{{padding:11px 20px;border:none;border-radius:9px;cursor:pointer;font-size:13px;font-weight:700;text-decoration:none;display:inline-flex;align-items:center;gap:6px}}
.btn:hover{{opacity:.88}}

/* print footer note, hidden on screen */
.print-only{{display:none}}

@media (max-width:700px){{
  .summary-bar{{grid-template-columns:1fr 1fr}}
}}

/* ===================== PRINT: clean statement look ===================== */
@media print{{
  body{{background:#fff;padding:0}}
  .wrap{{max-width:100%}}
  .bar{{border-radius:0;background:#fff !important;color:var(--ink) !important;border-bottom:2px solid var(--brand);padding:0 0 14px 0}}
  .bar .kicker,.bar .cust-sub,.bar .meta{{color:var(--muted) !important}}
  .bar .cust-name,.bar .company{{color:var(--brand) !important}}
  .card{{box-shadow:none;border-radius:0}}
  .summary-bar{{border-bottom:2px solid var(--brand)}}
  thead tr{{background:#fff !important;color:var(--ink) !important;border-bottom:2px solid var(--brand)}}
  tfoot tr{{background:#fff !important;color:var(--ink) !important;border-top:2px solid var(--brand)}}
  .tot-received{{color:var(--brand-2) !important}}
  .tot-pending{{color:var(--danger) !important}}
  .no-print, .actions{{display:none !important}}
  .print-only{{display:block;margin-top:18px;padding-top:10px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}}
  table{{font-size:12px}}
  .pay-chip{{background:#fff !important;border:1px solid var(--line);color:var(--ink) !important}}
}}
</style></head><body>
<div class="wrap">
  <div class="bar">
    <div>
      <div class="kicker">📋 Customer Ledger</div>
      <div class="cust-name">{name}</div>
      <div class="cust-sub">{addr} {('| 📞 '+phone) if phone else ''}</div>
    </div>
    <div style="text-align:right">
      <div class="kicker" style="text-align:right">Company</div>
      <div class="company">{company}</div>
      <div class="meta">{len(rows_data)} invoice(s) · as of {today_str}</div>
    </div>
  </div>
  <div class="card">
    <form method="get" class="no-print" style="display:flex;gap:10px;align-items:center;padding:14px 16px;flex-wrap:wrap">
      <input type="hidden" name="name" value="{name}">
      <input type="hidden" name="address" value="{addr}">
      <label style="font-size:13px;font-weight:600;color:var(--muted)">📅 From Date:</label>
      <input type="date" name="from_date" value="{from_date}" style="padding:8px;border-radius:6px;border:1px solid #ccc">
      <button class="btn" style="background:var(--brand-2);color:#fff">Apply</button>
      {('<a href="'+url_for('customer_ledger',name=name,address=addr)+'" class="btn" style="background:#e7ece8;color:#374151">Clear</a>') if from_date else ''}
    </form>
    <form method="post" class="no-print" style="display:flex;gap:10px;align-items:center;padding:14px 16px;flex-wrap:wrap;background:#faf5ff;border-top:1px solid var(--line);border-bottom:1px solid var(--line)">
      <input type="hidden" name="action" value="add_payment">
      <input type="hidden" name="name" value="{name}">
      <input type="hidden" name="address" value="{addr}">
      <label style="font-size:13px;font-weight:700;color:var(--accent)">💰 Add Payment:</label>
      <input type="date" name="date" id="ledgerPayDate" required style="padding:8px;border-radius:6px;border:1px solid #ccc">
      <input type="number" name="amount" placeholder="Amount" step="0.01" required style="padding:8px;border-radius:6px;border:1px solid #ccc;width:130px">
      <select name="method" style="padding:8px;border-radius:6px;border:1px solid #ccc">
        <option>Cash</option><option>Bank</option><option>JazzCash</option><option>EasyPaisa</option>
      </select>
      <input type="text" name="note" placeholder="Note (optional)" style="padding:8px;border-radius:6px;border:1px solid #ccc;flex:1;min-width:150px">
      <button class="btn" style="background:var(--accent);color:#fff">Save Payment</button>
    </form>
    <script>document.getElementById('ledgerPayDate').valueAsDate = new Date();</script>
    <div class="summary-bar">
      <div class="sum-cell"><div class="sum-lbl">Total Billed</div><div class="sum-val" style="color:var(--brand)">Rs {total_billed:,.0f}</div></div>
      <div class="sum-cell"><div class="sum-lbl">Total Received</div><div class="sum-val" style="color:var(--brand-2)">Rs {total_received:,.0f}</div></div>
      <div class="sum-cell"><div class="sum-lbl">Balance Due</div><div class="sum-val" style="color:{'var(--danger)' if total_pending>0 else 'var(--brand-2)'}">{'Rs {:,.0f}'.format(total_pending) if total_pending>0 else '✓ Clear'}</div></div>
      <div class="sum-cell"><div class="sum-lbl">Invoices</div><div class="sum-val" style="color:var(--accent)">{len(rows_data)}</div></div>
    </div>
    <div class="tbl-wrap">
    <table>
      <thead><tr>
        <th>Invoice #</th><th>Date</th><th class="c-num">Invoice Total</th><th class="c-num">Received</th><th class="c-num">Pending</th><th class="c-num">Running Balance</th><th>Payment Details</th><th class="no-print">Action</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
      <tfoot>
        <tr>
          <td colspan="2">TOTALS</td>
          <td class="c-num tot-billed">Rs {total_billed:,.0f}</td>
          <td class="c-num tot-received">Rs {total_received:,.0f}</td>
          <td class="c-num tot-pending">Rs {running_balance:,.0f}</td>
          <td colspan="3" class="no-print"></td>
        </tr>
      </tfoot>
    </table>
    </div>
    <div class="print-only">
      This is a system-generated statement from {company}. Figures reflect invoices and payments recorded up to {today_str}.
    </div>
    <div class="actions">
      <a href="{url_for('customer_ledger')}" class="btn" style="background:var(--accent);color:#fff">👥 All Customers</a>
      <a href="{url_for('payments')}" class="btn" style="background:#1565c0;color:#fff">💳 Payments</a>
      <a href="{url_for('invoices_list')}" class="btn" style="background:#e7ece8;color:#374151">📂 Invoices</a>
      <a href="{url_for('customer_ledger_pdf', name=name, address=addr)}" class="btn" style="background:#15803d;color:#fff">📥 Download PDF</a>
      <button onclick="window.print()" class="btn" style="background:var(--brand);color:#fff">🖨 Print Ledger</button>
    </div>
  </div>
</div>
<script>
      // Page open hote hi ledger PDF apne aap download ho jayegi
      window.addEventListener('load', function() {{
        var a = document.createElement('a');
        a.href = "{url_for('customer_ledger_pdf', name=name, address=addr)}";
        a.download = "";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }});
    </script>
</body></html>"""
    return ledger_html

# ================================================
@app.route("/customer_ledger/pdf")
@login_required
def customer_ledger_pdf():
    name = to_caps(request.args.get("name","").strip())
    addr = to_caps(request.args.get("address","").strip())
    fn = RECORDS_DIR / "Ledgers" / f"LEDGER_{safe_name(name)}_{safe_name(addr)}.pdf"
    if not fn.exists():
        flash("❌ Ledger PDF nahi mili — pehle ledger page open karein taake woh generate ho")
        return redirect(url_for('customer_ledger', name=name, address=addr))
    return send_file(str(fn), as_attachment=True, download_name=fn.name)
# ---------- Invoices List (with monthly sub-cards) ----------
# ---------- invoices list (shortened) ----------
@app.route("/invoices", methods=["GET","POST"])
@login_required
def invoices_list():

    # ================= POST ACTIONS =================
    import datetime as _dt
    if request.method == "POST":
        act = request.form.get("action","")

        if act == "delete":
            del_inv = request.form.get("inv_no_del","")
            if del_inv:
                try:
                    with db_transaction() as _c:
                        row = _c.execute("""
                            SELECT inv_no, date, customer, customer_address, customer_phone, salesman,
                                   tax, discount, subtotal, grand_total, pending_added, total,
                                   customer_type, remarks, logo_path
                            FROM invoices WHERE inv_no=?
                        """, (str(del_inv),)).fetchone()

                        if not row:
                            flash("Invoice not found")
                            return redirect(url_for("invoices_list"))

                        (inv_no_v, date, customer, customer_address, customer_phone, salesman,
                         tax, discount, subtotal, grand_total, pending_added, total,
                         customer_type, remarks, logo_path) = row

                        inv_lines = _c.execute(
                            "SELECT product, qty, unit_price FROM invoice_items WHERE inv_no=?", (str(del_inv),)
                        ).fetchall()

                        _cur = _c.cursor()
                        _cur.execute("""
                            INSERT OR REPLACE INTO deleted_invoices
                            (inv_no, date, customer, customer_address, customer_phone, salesman,
                             tax, discount, subtotal, grand_total, pending_added, total,
                             customer_type, remarks, logo_path, deleted_on, deleted_lines)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (
                            inv_no_v, date, customer, customer_address, customer_phone, salesman,
                            tax, discount, subtotal, grand_total, pending_added, total,
                            customer_type, remarks, logo_path,
                            _dt.date.today().isoformat(),
                            json.dumps([{"product": p, "qty": q, "unit_price": u} for (p, q, u) in inv_lines])
                        ))

                        _cur.execute("DELETE FROM deleted_invoice_items WHERE inv_no=?", (str(del_inv),))
                        for (p, q, u) in inv_lines:
                            _cur.execute("""
                                INSERT INTO deleted_invoice_items (inv_no, product, qty, unit_price)
                                VALUES (?,?,?,?)
                            """, (str(del_inv), p, q, u))
                            _cur.execute("""
                                UPDATE products SET stock = stock + ?
                                WHERE lower(trim(name)) = lower(?)
                            """, (float(q or 0), p.strip()))

                        _cur.execute("DELETE FROM invoice_items WHERE inv_no=?", (str(del_inv),))
                        _cur.execute("DELETE FROM invoices WHERE inv_no=?", (str(del_inv),))

                    flash(f"✅ Invoice #{del_inv} moved to Recycle Bin (recoverable for 30 days)")
                except Exception as e:
                    flash(f"Delete failed, no changes were made (safe rollback): {e}")
            return redirect(url_for("invoices_list"))

    # ================= GET LIST =================
    from collections import defaultdict

    with db_transaction() as _c:
        _raw = _c.execute("""
            SELECT inv_no, date, customer, customer_address, customer_phone, tax, discount,
                   subtotal, grand_total, pending_added, total, logo_path, remarks,
                   customer_type, salesman
            FROM invoices
        """).fetchall()

    rows = [{
        "inv_no": r[0], "date": r[1], "name": r[2], "address": r[3], "phone": r[4],
        "tax": r[5], "discount": r[6], "subtotal": r[7], "grand_total": r[8],
        "pending_added": r[9], "total": r[10], "logo_path": r[11], "remarks": r[12],
        "customer_type": r[13], "salesman": r[14]
    } for r in _raw]

    def parse_date(d):
        for fmt in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
            try: return _dt.datetime.strptime(d, fmt)
            except: pass
        return None

    # -------- MONTH GROUPING --------
    monthly = defaultdict(list)

    for r in rows:
        dt = parse_date(r.get("date",""))
        if not dt:
            continue
        key = dt.strftime("%B %Y")
        r["_dt"] = dt
        monthly[key].append(r)

    # -------- SORT (NEWEST FIRST) --------
    monthly_sorted = dict(
        sorted(
            monthly.items(),
            key=lambda x: _dt.datetime.strptime(x[0], "%B %Y"),
            reverse=True
        )
    )

    for m in monthly_sorted:
        monthly_sorted[m].sort(
            key=lambda r: (r["_dt"], int(r.get("inv_no",0))),
            reverse=True
        )

    # -------- SUMMARY per month --------
    summary = {}
    for m, invs in monthly_sorted.items():
        grand_totals = [float(i.get("grand_total","0") or i.get("total","0") or 0) for i in invs]
        total_amounts = [float(i.get("total","0") or 0) for i in invs]
        summary[m] = {
            "count": len(invs),
            "grand_total": sum(grand_totals),
            "total_amount": sum(total_amounts),
            "first_date": min((i.get("date","") for i in invs), default=""),
            "last_date":  max((i.get("date","") for i in invs), default=""),
        }

    # ================= HTML =================
    html = TPL_H + """
<style>
.month-summary-strip{background:linear-gradient(135deg,#0d3b34,#0f5c52);color:white;border-radius:12px;padding:16px 20px;margin-bottom:20px;overflow-x:auto}
.month-summary-strip table{border-collapse:collapse;width:100%;min-width:700px;color:white}
.month-summary-strip th{font-size:11px;font-weight:600;opacity:.7;padding:4px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,.2)}
.month-summary-strip td{padding:8px 10px;font-size:13px;border-bottom:1px solid rgba(255,255,255,.1)}
.month-summary-strip tr:hover td{background:rgba(255,255,255,.08);cursor:pointer}
.inv-table th{padding:10px 12px;font-size:11.5px;text-align:left;white-space:nowrap}
.inv-table td{padding:9px 12px;vertical-align:middle}
.action-btns{display:flex;gap:4px;flex-wrap:nowrap}
</style>

<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="/">Dashboard</a> › All Invoices</div>
    <h2>📄 All Invoices</h2>
  </div>
  <div class="flex gap-1">
    <a href="{{url_for('new_invoice')}}" class="btn btn-primary">➕ New Invoice</a>
    <a href="{{url_for('recycle_bin')}}" class="btn btn-secondary">🗑️ Recycle Bin</a>
  </div>
</div>

<!-- ═══ MONTHLY SUMMARY STRIP (top) — auto updates when new invoice added ═══ -->
<div class="month-summary-strip mb-3">
  <div style="font-weight:700;font-size:14px;margin-bottom:10px;opacity:.9">📊 Monthly Summary — click to jump</div>
  <table>
    <thead>
      <tr>
        <th>Month</th><th>Invoices</th><th>Date Range</th>
        <th style="text-align:right">Grand Total</th>
        <th style="text-align:right">Total Amount</th>
      </tr>
    </thead>
    <tbody>
      {% for m, s in summary.items() %}
      <tr onclick="jumpToMonth('{{loop.index}}')">
        <td style="font-weight:700">📁 {{m}}</td>
        <td><span style="background:rgba(255,255,255,.2);padding:2px 8px;border-radius:99px;font-size:12px;font-weight:700">{{s.count}}</span></td>
        <td style="opacity:.8;font-size:12px">{{s.first_date}} – {{s.last_date}}</td>
        <td style="text-align:right;font-weight:700">Rs {{'{:,.0f}'.format(s.grand_total)}}</td>
        <td style="text-align:right;font-weight:800;color:#93c5fd">Rs {{'{:,.0f}'.format(s.total_amount)}}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<!-- ═══ FILTER BAR ═══ -->
<div class="filter-bar mb-2">
  <div class="search-box" style="flex:2">
    <input id="invSearch" class="form-control" placeholder="🔍 Search: invoice#, customer name, address, salesman...">
  </div>
  <select id="typeFilter" class="form-control" style="width:155px">
    <option value="">All Types</option>
    <option value="customer">🛒 Customer</option>
    <option value="distributor">🚚 Distributor</option>
    <option value="wholesaler">🏭 Wholesaler</option>
  </select>
  <select id="monthJump" class="form-control" style="width:170px" onchange="jumpToMonthName(this.value)">
    <option value="">Jump to Month...</option>
    {% for m in monthly.keys() %}<option value="{{m}}">{{m}}</option>{% endfor %}
  </select>
</div>

<!-- ═══ MONTHLY INVOICE CARDS ═══ -->
{% for month, invs in monthly.items() %}
<div class="card mb-2" id="mcard_{{loop.index}}" data-month="{{month}}">
  <!-- Month Header — click to fold/expand -->
  <div onclick="toggleMonth('{{loop.index}}')" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;padding:2px 0 10px">
    <div>
      <span style="font-weight:800;font-size:16px;color:var(--heading)">📁 {{month}}</span>
      <span style="margin-left:12px;font-size:13px;color:var(--text-muted)">
        {{summary[month].count}} invoices &nbsp;|&nbsp;
        Grand: <strong style="font-size:24px;font-weight:900;background:linear-gradient(90deg,#f59e0b,#ef4444,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent;text-shadow:2px 2px 8px rgba(0,0,0,.25);letter-spacing:.5px;">💰 Rs {{'{:,.0f}'.format(summary[month].grand_total)}}</strong> &nbsp;|&nbsp;
        Total: <strong style="color:#1e40af">Rs {{'{:,.0f}'.format(summary[month].total_amount)}}</strong>
      </span>
    </div>
    <span id="arr_{{loop.index}}" style="font-size:18px;color:var(--text-muted)">▼</span>
  </div>

  <div id="mbody_{{loop.index}}" class="month-body">
    <div class="table-wrap">
      <table class="inv-table">
        <thead>
          <tr>
            <th>Inv#</th>
            <th>Date</th>
            <th>Customer</th>
            <th>Address</th>
            <th>Type</th>
            <th>Salesman</th>
            <th style="text-align:right">Grand Total</th>
            <th style="text-align:right;color:#1e40af">Total Amount</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
        {% for r in invs %}
        {% set gt  = r.get('grand_total','') | float if r.get('grand_total') else
                     (r.total|float - (r.get('pending_added','0')|float)) %}
        {% set pa  = r.get('pending_added','0') | float %}
        {% set tot = r.total | float %}
        <tr class="inv-row" data-type="{{r.get('customer_type','customer')}}">
          <td><strong style="color:var(--heading)">#{{r.inv_no}}</strong></td>
          <td style="white-space:nowrap">{{r.date}}</td>
          <td><strong>{{r.name[:22]}}</strong></td>
          <td style="color:var(--text-muted)">{{r.address[:20]}}</td>
          <td>
            {% if r.get('customer_type','customer') == 'wholesaler' %}
              <span class="badge badge-blue">🏭 W</span>
            {% elif r.get('customer_type','customer') == 'distributor' %}
              <span class="badge badge-purple">🚚 D</span>
            {% else %}
              <span class="badge badge-green">🛒 C</span>
            {% endif %}
          </td>
          <td style="font-size:12px">{{r.get('salesman','') or '—'}}</td>
          <td style="text-align:right;font-weight:700">Rs {{'{:,.0f}'.format(gt)}}</td>
          <td style="text-align:right;font-weight:800;color:#1e40af">
            {% if pa > 0 %}
              Rs {{'{:,.0f}'.format(tot)}}
              <div style="font-size:10px;color:#e67e22;font-weight:600">+Rs {{'{:,.0f}'.format(pa)}} pending</div>
            {% else %}
              Rs {{'{:,.0f}'.format(gt)}}
            {% endif %}
          </td>
          <td>
            <div class="action-btns">
              <!-- VIEW PDF -->
              <a class="btn btn-sm btn-outline"
                 href="{{ url_for('find_view_pdf', inv=r.inv_no) }}"
                 title="View Invoice PDF">👁 View</a>
              <a class="btn btn-sm btn-outline" target="_blank"
                 href="{{ url_for('new_delivery_note', from_invoice=r.inv_no) }}"
                 style="background:#0369a1;color:white"
                 title="Generate Delivery Note">🚚 DN</a>
              <!-- EDIT -->
              <a class="btn btn-sm btn-primary"
                 href="{{ url_for('edit_invoice', inv_no=r.inv_no) }}"
                 title="Edit Invoice">✏️ Edit</a>
              <!-- PRINT -->
              <a class="btn btn-sm"
                 href="{{ url_for('find_view_pdf', inv=r.inv_no) }}?print=1"
                 style="background:#1b5e20;color:white"
                 title="Print Invoice">🖨 Print</a>
              <!-- DELETE -->
              <form method="post" style="display:inline">
                <input type="hidden" name="action" value="delete">
                <input type="hidden" name="inv_no_del" value="{{r.inv_no}}">
                <button class="btn btn-sm btn-danger"
                        onclick="return confirm('Move Invoice #{{r.inv_no}} to Recycle Bin?\\nCan recover within 30 days.')"
                        title="Delete (recoverable for 30 days)">🗑 Del</button>
              </form>
            </div>
          </td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% endfor %}

{% if not monthly %}
<div class="card text-center" style="padding:40px">
  <p style="font-size:18px;color:var(--text-muted)">No invoices yet</p>
  <a href="{{url_for('new_invoice')}}" class="btn btn-primary btn-lg mt-2">➕ Create First Invoice</a>
</div>
{% endif %}

<script>
// ── Toggle month ──
function toggleMonth(id){
  const body = document.getElementById('mbody_' + id);
  const arr  = document.getElementById('arr_'   + id);
  if(!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  if(arr) arr.textContent = open ? '▶' : '▼';
}

// ── Jump to month by index ──
function jumpToMonth(idx){
  const card = document.getElementById('mcard_' + idx);
  const body = document.getElementById('mbody_' + idx);
  const arr  = document.getElementById('arr_'   + idx);
  if(!card) return;
  body.style.display = 'block';
  if(arr) arr.textContent = '▼';
  card.scrollIntoView({behavior:'smooth', block:'start'});
}

// ── Jump by month name ──
function jumpToMonthName(name){
  if(!name) return;
  document.querySelectorAll('[data-month]').forEach((card, i) => {
    if(card.dataset.month === name){
      const idx = i + 1;
      jumpToMonth(idx);
    }
  });
}

// ── Filters ──
function applyFilters(){
  const q    = document.getElementById('invSearch').value.toLowerCase().trim();
  const type = document.getElementById('typeFilter').value;
  let anyVisible = false;
  document.querySelectorAll('.inv-row').forEach(row => {
    const text  = row.innerText.toLowerCase();
    const rtype = (row.dataset.type || '').toLowerCase();
    const matchQ = !q || text.includes(q);
    const matchT = !type || rtype === type;
    row.style.display = (matchQ && matchT) ? '' : 'none';
  });
  // Auto-open cards that have visible rows, hide empty ones
  document.querySelectorAll('.month-body').forEach((body, i) => {
    const vis = body.querySelectorAll('.inv-row:not([style*="display: none"])');
    if(q || type){
      body.style.display = vis.length ? 'block' : 'none';
      const arr = document.getElementById('arr_' + (i+1));
      if(arr) arr.textContent = vis.length ? '▼' : '▶';
    }
  });
}

document.getElementById('invSearch').addEventListener('input',  applyFilters);
document.getElementById('typeFilter').addEventListener('change', applyFilters);

// ── Open first (most recent) month by default ──
(function(){
  const body = document.getElementById('mbody_1');
  const arr  = document.getElementById('arr_1');
  if(body){ body.style.display = 'block'; }
  if(arr)  { arr.textContent = '▼'; }
})();
</script>
""" + TPL_F

    return render_template_string(
        html,
        monthly=monthly_sorted,
        summary=summary,
        project=get_setting("project_name")
    )
######################################################################
@app.route("/share_pdf/<inv>")
@login_required
def share_pdf(inv):
    # 1. Locate local PDF
    pdf_path = None
    with db_transaction() as _c:
        _row = _c.execute(
            "SELECT inv_no, customer, customer_address FROM invoices WHERE inv_no=?", (str(inv),)
        ).fetchone()
    if _row:
        name_safe = safe_name(to_caps(_row[1] or ""))
        addr_safe = safe_name(to_caps(_row[2] or ""))
        fn = f"INV_{_row[0]}_{name_safe}_{addr_safe}.pdf"
        base = output_base() / "SEIZE"
        for p in base.rglob(fn):
            pdf_path = p
            break

    if not pdf_path or not pdf_path.exists():
        flash("PDF not found")
        return redirect(url_for("invoices_list"))

    # 2. Upload to cloud
    link = upload_to_gdrive(str(pdf_path))  # Google Drive
    # link = upload_to_s3(str(pdf_path), "bucket_name")  # AWS S3 optional

    # 3. Show share box
    html = f"""
    <h3>Share Invoice {inv}</h3>
    <p>Share this link via WhatsApp, Email, or copy:</p>
    <input type="text" value="{link}" id="share_link" readonly style="width:80%;">
    <button onclick="navigator.clipboard.writeText(document.getElementById('share_link').value)">
        Copy Link
    </button>
    <a href="https://wa.me/?text=Invoice%20{inv}%20link:%20{link}" target="_blank" 
       style="background:#25d366;padding:6px 12px;font-size:13px;margin-left:5px;">
       WhatsApp
    </a>
    """
    return html

# ---------- Edit Invoice (new route) ----------
@app.route("/invoice/edit/<int:inv_no>", methods=["GET", "POST"])
@login_required
def edit_invoice(inv_no):
    prods = load_products()

    with db_transaction() as _c:
        _row = _c.execute("""
            SELECT inv_no, date, customer, customer_address, customer_phone, tax, discount,
                   subtotal, grand_total, pending_added, total, logo_path, remarks,
                   customer_type, salesman
            FROM invoices WHERE inv_no=?
        """, (str(inv_no),)).fetchone()

        if not _row:
            flash("Invoice not found")
            return redirect(url_for("invoices_list"))

        invoice = {
            "inv_no": _row[0], "date": _row[1], "name": _row[2], "address": _row[3], "phone": _row[4],
            "tax": _row[5], "discount": _row[6], "subtotal": _row[7], "grand_total": _row[8],
            "pending_added": _row[9], "total": _row[10], "logo_path": _row[11], "remarks": _row[12],
            "customer_type": _row[13], "salesman": _row[14]
        }

        _lines_raw = _c.execute(
            "SELECT product, qty, unit_price FROM invoice_items WHERE inv_no=?", (str(inv_no),)
        ).fetchall()
        existing_lines = [{"product": p, "qty": q, "unit_price": u} for (p, q, u) in _lines_raw]

    tax_def = float(get_setting("tax_default", "0") or 0)
    custs = load_customers()
    with db_transaction() as _c:
        _c.row_factory = sqlite3.Row
        salesmen_list = [dict(row) for row in _c.execute("SELECT name FROM salesmen WHERE status=? AND salesman_type='salesman'", ("Active",)).fetchall()]
    if request.method == "POST":
        try:
            name         = to_caps(request.form.get("name",""))
            addr         = to_caps(request.form.get("address",""))
            phone        = request.form.get("phone","")
            tax          = float(request.form.get("tax", tax_def) or tax_def)
            date_str     = request.form.get("date") or invoice["date"]
            pending_added = float(request.form.get("pending_amount","0") or 0)
            customer_type = request.form.get("customer_type", invoice.get("customer_type","customer"))
            salesman      = to_caps(request.form.get("salesman", invoice.get("salesman","")) or "")
            try: discount = max(0.0, float(request.form.get("discount","0") or 0))
            except: discount = 0.0
            # Allow editing inv_no if user changes it
            new_inv_no_str = request.form.get("inv_no_edit","").strip()
            new_inv_no = int(new_inv_no_str) if new_inv_no_str else inv_no

            new_lines = []
            used = set()
            keys = sorted([k for k in request.form if k.startswith("prod_")],
                          key=lambda x: int(x.split("_")[1]))
            for k in keys:
                i = k.split("_")[1]
                prod = request.form.get(f"prod_{i}","").strip()
                if not prod: continue
                qty_raw = request.form.get(f"qty_{i}","").strip()
                qty = float(qty_raw) if qty_raw else 0.0
                if qty <= 0: raise Exception("Quantity must be > 0")
                if prod in used: raise Exception(f"Duplicate: {prod}")
                price_raw = request.form.get(f"price_{i}","").strip()
                # Price based on customer type if empty
                info = next((p for p in prods if p["name"] == prod), None)
                if price_raw:
                    price = float(price_raw)
                elif info:
                    if customer_type == "wholesaler" and info.get("wholesaler_price",0):
                        price = float(info["wholesaler_price"])
                    elif customer_type == "distributor" and info.get("distributor_price",0):
                        price = float(info["distributor_price"])
                    elif info.get("customer_price",0):
                        price = float(info["customer_price"])
                    else:
                        price = float(info["unit_price"])
                else:
                    price = 0.0
                new_lines.append({"product": prod, "qty": qty, "unit_price": price})
                used.add(prod)

            if not new_lines: raise Exception("Add at least one product")

            # Calculate totals
            edit_subtotal    = sum(l["qty"] * l["unit_price"] for l in new_lines)
            edit_tax_amt     = edit_subtotal * tax / 100.0
            edit_grand_total = edit_subtotal + edit_tax_amt - discount
            edit_total       = edit_grand_total + pending_added
            subtotal = edit_subtotal
            total    = edit_total

            low_stock = []
            with db_transaction() as _c:
                _cur = _c.cursor()

                # Reverse old stock (jo purani lines thi unka stock wapas add karo)
                for l in existing_lines:
                    _cur.execute("""
                        UPDATE products SET stock = stock + ?
                        WHERE lower(trim(name)) = lower(?)
                    """, (float(l["qty"]), l["product"].strip()))

                # Apply new stock (naya stock minus karo, check insufficient)
                for l in new_lines:
                    row = _cur.execute(
                        "SELECT stock, min_stock FROM products WHERE lower(trim(name))=lower(?)",
                        (l["product"].strip(),)
                    ).fetchone()
                    if row:
                        st, mn = float(row[0] or 0), float(row[1] or 0)
                        if st < l["qty"]:
                            raise Exception(f"Insufficient stock: {l['product']}")
                        if st - l["qty"] <= mn:
                            low_stock.append(l["product"])
                        _cur.execute("""
                            UPDATE products SET stock = stock - ?
                            WHERE lower(trim(name)) = lower(?)
                        """, (l["qty"], l["product"].strip()))

                # Update sales_log
                _cur.execute("DELETE FROM sales_log WHERE inv_no=?", (str(inv_no),))
                for l in new_lines:
                    _cur.execute("""
                        INSERT INTO sales_log (date, inv_no, product, qty, sell_price)
                        VALUES (?,?,?,?,?)
                    """, (date_str, str(new_inv_no), l["product"], l["qty"], l["unit_price"]))

                # Delete old invoice row + items (agar inv_no change hua ho to bhi purana hat jaye)
                _cur.execute("DELETE FROM invoice_items WHERE inv_no=?", (str(inv_no),))
                _cur.execute("DELETE FROM invoices WHERE inv_no=?", (str(inv_no),))

                _cur.execute("""
                    INSERT INTO invoices
                    (inv_no, date, customer, customer_address, customer_phone, salesman,
                     tax, discount, subtotal, grand_total, pending_added, total,
                     customer_type, remarks, logo_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(new_inv_no), date_str, name, addr, phone, salesman,
                    float(tax), float(discount), float(edit_subtotal), float(edit_grand_total),
                    float(pending_added), float(edit_total), customer_type,
                    invoice.get("remarks",""), invoice.get("logo_path","")
                ))

                for l in new_lines:
                    _cur.execute("""
                        INSERT INTO invoice_items (inv_no, product, qty, unit_price)
                        VALUES (?,?,?,?)
                    """, (str(new_inv_no), l["product"], l["qty"], l["unit_price"]))
            # Auto-regenerate Monthly Summary PDF(s) — old month (if changed) and new month
            try:
                old_dt = None
                for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
                    try:
                        old_dt = datetime.datetime.strptime(invoice.get("date",""), fmt); break
                    except Exception:
                        continue
                new_dt = None
                for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
                    try:
                        new_dt = datetime.datetime.strptime(date_str, fmt); break
                    except Exception:
                        continue
                regenerated = set()
                if new_dt:
                    generate_monthly_summary_pdf(new_dt.year, new_dt.strftime("%B"))
                    regenerated.add((new_dt.year, new_dt.strftime("%B")))
                if old_dt and (old_dt.year, old_dt.strftime("%B")) not in regenerated:
                    generate_monthly_summary_pdf(old_dt.year, old_dt.strftime("%B"))
            except Exception as e:
                print("Monthly summary regen error:", e)
            # Regenerate PDF
            now2 = datetime.datetime.now()
            out_dir = ensure_out_dirs(now2.year, now2.strftime("%B"))
            pdf = out_dir / f"INV_{new_inv_no}_{safe_name(name)}_{safe_name(addr)}.pdf"
            draw_invoice_pdf(pdf, get_setting("company_name"), get_setting("logo_path") or None,
                             get_setting("logo_show")=="1", new_inv_no, date_str, name, addr, phone,
                             new_lines, tax, pending_added, discount=discount,
                             salesman=salesman, customer_type=customer_type)

            if low_stock: flash("⚠️ Low stock: " + ", ".join(low_stock))
            flash(f"✅ Invoice #{new_inv_no} updated successfully!")
            return redirect(url_for("invoices_list"))

        except Exception as e:
            flash(f"❌ Error: {e}")
            return redirect(url_for("edit_invoice", inv_no=inv_no))

    # =================== GET — Full Professional Edit Form ===================
    html = TPL_H + """
<style>
.edit-section{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}
.edit-section h4{font-size:14px;font-weight:700;color:var(--heading);margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.edit-tbl{width:100%;border-collapse:collapse}
.edit-tbl th{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:white;padding:10px 12px;font-size:12px;text-align:left}
.edit-tbl td{padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
.edit-tbl tbody tr:hover{background:rgba(59,130,246,.04)}
.ein{width:100%;padding:7px 9px;border:1.5px solid var(--input-border);border-radius:7px;font-size:13px;background:var(--input-bg);color:var(--text)}
.price-badge{font-size:10px;padding:2px 6px;border-radius:4px;font-weight:700;margin-left:4px}
</style>

<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="/">Home</a> › <a href="/invoices">Invoices</a> › Edit</div>
    <h2>✏️ Edit Invoice #{{inv_no}}</h2>
  </div>
  <div class="flex">
    <a href="/invoices" class="btn btn-secondary">← Back</a>
    <a href="/find_view_pdf/{{inv_no}}" class="btn btn-outline">📄 View PDF</a>
  </div>
</div>

<form method="post" id="editForm">

<!-- SECTION 1: Invoice Info -->
<div class="edit-section">
  <h4>📋 Invoice Information</h4>
  <div class="form-row form-row-4">
    <div class="form-group">
      <label class="form-label">Invoice #</label>
      <input name="inv_no_edit" class="ein" value="{{inv_no}}" type="number">
    </div>
    <div class="form-group">
      <label class="form-label">Date</label>
      <input name="date" class="ein" type="date" value="{{invoice_date_iso}}">
    </div>
    <div class="form-group">
      <label class="form-label">🏷️ Customer Type</label>
      <select name="customer_type" id="edit_ctype" class="ein" onchange="updateEditPrices()">
        <option value="customer" {{'selected' if invoice.customer_type=='customer' else ''}}>🛒 Customer</option>
        <option value="distributor" {{'selected' if invoice.customer_type=='distributor' else ''}}>🚚 Distributor</option>
        <option value="wholesaler" {{'selected' if invoice.customer_type=='wholesaler' else ''}}>🏭 Wholesaler</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">🤝 Salesman</label>
      <select name="salesman" class="ein">
        <option value="">— Select —</option>
        {% for sm in salesmen_list %}
        <option value="{{sm.name}}" {{'selected' if invoice.get('salesman','')==sm.name else ''}}>{{sm.name}}</option>
        {% endfor %}
        <option value="Direct" {{'selected' if invoice.get('salesman','')=='Direct' else ''}}>Direct</option>
      </select>
    </div>
  </div>
</div>

<!-- SECTION 2: Customer Info -->
<div class="edit-section">
  <h4>👤 Customer Information</h4>
  <div class="form-row form-row-3">
    <div class="form-group">
      <label class="form-label">Customer Name *</label>
      <input name="name" class="ein" value="{{invoice.name}}" required list="cust_names_edit"
             oninput="titleCaseInput(this)" data-titlecase>
      <datalist id="cust_names_edit">{% for c in custs %}<option value="{{c.name}}">{% endfor %}</datalist>
    </div>
    <div class="form-group">
      <label class="form-label">Address *</label>
      <input name="address" class="ein" value="{{invoice.address}}" required list="cust_addr_edit"
             oninput="titleCaseInput(this)" data-titlecase>
      <datalist id="cust_addr_edit">{% for c in custs %}<option value="{{c.address}}">{% endfor %}</datalist>
    </div>
    <div class="form-group">
      <label class="form-label">Phone</label>
      <input name="phone" class="ein" value="{{invoice.phone}}">
    </div>
  </div>
</div>

<!-- SECTION 3: Products -->
<div class="edit-section">
  <h4>📦 Products</h4>
  <div class="table-wrap">
    <table class="edit-tbl" id="edit_tbl">
      <thead><tr><th>Product</th><th>Qty</th><th>Unit Price</th><th>Total</th><th></th></tr></thead>
      <tbody>
        {% for l in existing_lines %}
        <tr>
          <td>
            <select name="prod_{{loop.index0}}" class="ein" onchange="editSetPrice(this, {{loop.index0}})">
              <option value="">-- select --</option>
              {% for p in prods %}
              <option value="{{p.name}}"
                data-up="{{p.unit_price}}" data-wp="{{p.wholesaler_price or p.unit_price}}"
                data-dp="{{p.distributor_price or p.unit_price}}" data-cp="{{p.customer_price or p.unit_price}}"
                {{'selected' if p.name==l.product else ''}}>{{p.name}}</option>
              {% endfor %}
            </select>
          </td>
          <td><input name="qty_{{loop.index0}}" id="eq_{{loop.index0}}" class="ein" type="number"
                     step="any" value="{{l.qty}}" oninput="editCalc()" style="width:80px"></td>
          <td>
            <input name="price_{{loop.index0}}" id="ep_{{loop.index0}}" class="ein" type="number"
                   step="any" value="{{l.unit_price}}" oninput="editCalc()" style="width:110px">
          </td>
          <td id="et_{{loop.index0}}" style="font-weight:700;color:var(--btn-success)">
            Rs {{'{:,.0f}'.format(l.qty|float * l.unit_price|float)}}
          </td>
          <td><button type="button" class="btn btn-sm btn-danger"
                onclick="this.closest('tr').remove();editCalc()">✕</button></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="flex mt-2" style="gap:10px">
    <button type="button" class="btn btn-outline" onclick="editAddRow()">➕ Add Product</button>
  </div>
</div>

<!-- SECTION 4: Totals -->
<div class="edit-section">
  <h4>💰 Totals & Adjustments</h4>
  <div class="form-row form-row-4">
    <div class="form-group">
      <label class="form-label">Tax %</label>
      <input name="tax" class="ein" type="number" step="0.01" value="{{invoice.tax or 0}}" oninput="editCalc()">
    </div>
    <div class="form-group">
      <label class="form-label">💲 Discount (Rs)</label>
      <input name="discount" id="edit_discount" class="ein" type="number" step="any"
             value="{{invoice.discount or 0}}" oninput="editCalc()">
    </div>
    <div class="form-group">
      <label class="form-label">⏳ Previous Pending (Rs)</label>
      <input name="pending_amount" id="edit_pending" class="ein" type="number" step="any"
             value="{{invoice.pending_added or 0}}" oninput="editCalc()">
    </div>
    <div class="form-group">
      <label class="form-label" style="color:transparent">.</label>
      <div id="edit_grand_box" style="background:#e3f2fd;color:#1e3a8a;padding:8px 14px;border-radius:8px;font-weight:700;font-size:14px;text-align:center;margin-bottom:4px">
        Grand Total: Rs 0
      </div>
      <div id="edit_total_box" style="background:#1e3a8a;color:white;padding:10px 14px;border-radius:8px;font-weight:800;font-size:15px;text-align:center">
        Total Amount: Rs 0
      </div>
    </div>
  </div>
  <div id="edit_sumbar" style="background:#f1f5f9;padding:10px 14px;border-radius:8px;font-size:13px;margin-top:8px"></div>
</div>

<div class="flex" style="justify-content:flex-end;gap:10px;padding:10px 0">
  <a href="/invoices" class="btn btn-secondary">Cancel</a>
  <button type="submit" class="btn btn-primary btn-lg">💾 Save Changes</button>
</div>
</form>

<script>
const editProds = {{ prods|tojson }};
let editRow = {{ existing_lines|length }};

function editSetPrice(sel, i) {
  const ctype = document.getElementById('edit_ctype').value;
  const opt = sel.options[sel.selectedIndex];
  if (!opt || !opt.value) return;
  let price = opt.dataset.up;
  if (ctype === 'wholesaler' && opt.dataset.wp) price = opt.dataset.wp;
  else if (ctype === 'distributor' && opt.dataset.dp) price = opt.dataset.dp;
  else if (ctype === 'customer' && opt.dataset.cp) price = opt.dataset.cp;
  const pEl = document.getElementById('ep_' + i);
  if (pEl) pEl.value = parseFloat(price || 0).toFixed(2);
  editCalc();
}

function updateEditPrices() {
  // Re-run price fill for all rows based on new customer type
  document.querySelectorAll('#edit_tbl tbody tr').forEach((tr, i) => {
    const sel = tr.querySelector('select');
    if (sel && sel.value) editSetPrice(sel, i);
  });
}

function editCalc() {
  let sub = 0, tqty = 0;
  document.querySelectorAll('#edit_tbl tbody tr').forEach((tr, i) => {
    const q = parseFloat(tr.querySelector('input[name^="qty_"]')?.value || 0);
    const p = parseFloat(tr.querySelector('input[name^="price_"]')?.value || 0);
    const t = q * p;
    sub += t; tqty += q;
    const te = tr.querySelector('[id^="et_"]');
    if (te) te.textContent = 'Rs ' + t.toLocaleString('en-PK', {maximumFractionDigits:0});
  });
  const tax   = parseFloat(document.querySelector('input[name="tax"]')?.value || 0);
  const disc  = parseFloat(document.getElementById('edit_discount')?.value || 0);
  const pend  = parseFloat(document.getElementById('edit_pending')?.value || 0);
  const taxAmt     = sub * tax / 100;
  const grandTotal = sub + taxAmt - disc;      // Grand Total (no pending)
  const totalAmt   = grandTotal + pend;         // Total Amount (with pending)
  document.getElementById('edit_grand_box').textContent = 'Grand Total: Rs ' + grandTotal.toLocaleString('en-PK',{maximumFractionDigits:0});
  document.getElementById('edit_total_box').textContent = 'Total Amount: Rs ' + totalAmt.toLocaleString('en-PK',{maximumFractionDigits:0});
  document.getElementById('edit_sumbar').innerHTML =
    `Qty: <b>${tqty.toFixed(1)}</b> | Subtotal: Rs ${sub.toFixed(0)} | Tax: Rs ${taxAmt.toFixed(0)} | Discount: Rs ${disc.toFixed(0)}` +
    (pend > 0 ? ` | <span style="color:#e67e22">Pending: Rs ${pend.toFixed(0)}</span>` : '');
}

function editAddRow() {
  const tb = document.querySelector('#edit_tbl tbody');
  const tr = document.createElement('tr');
  const opts = editProds.map(p =>
    `<option value="${p.name}" data-up="${p.unit_price}" data-wp="${p.wholesaler_price||p.unit_price}" data-dp="${p.distributor_price||p.unit_price}" data-cp="${p.customer_price||p.unit_price}">${p.name}</option>`
  ).join('');
  tr.innerHTML = `
    <td><select name="prod_${editRow}" class="ein" onchange="editSetPrice(this,${editRow})">
      <option value="">-- select --</option>${opts}</select></td>
    <td><input name="qty_${editRow}" id="eq_${editRow}" class="ein" type="number" step="any" style="width:80px" oninput="editCalc()"></td>
    <td><input name="price_${editRow}" id="ep_${editRow}" class="ein" type="number" step="any" style="width:110px" oninput="editCalc()"></td>
    <td id="et_${editRow}" style="font-weight:700;color:var(--btn-success)">Rs 0</td>
    <td><button type="button" class="btn btn-sm btn-danger" onclick="this.closest('tr').remove();editCalc()">✕</button></td>
  `;
  tb.appendChild(tr); editRow++; editCalc();
}

// Init calc on load
document.addEventListener('DOMContentLoaded', editCalc);
</script>
""" + TPL_F

    # Convert date to ISO for date input
    raw_date = invoice.get("date","")
    invoice_date_iso = ""
    for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
        try:
            invoice_date_iso = datetime.datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
            break
        except: pass

    return render_template_string(html,
        prods=prods, invoice=invoice, existing_lines=existing_lines,
        inv_no=inv_no, invoice_date_iso=invoice_date_iso,
        custs=custs, salesmen_list=salesmen_list,
        project=get_setting("project_name")
    )



# ---------- find_view_pdf ----------
@app.route("/find_view_pdf/<inv>")
@login_required
def find_view_pdf(inv):
    with db_transaction() as _c:
        _row = _c.execute(
            "SELECT inv_no, date, customer, customer_address FROM invoices WHERE inv_no=?", (str(inv),)
        ).fetchone()
    if _row:
        d = _row[1] or ""
        try:
            if "-" in d and len(d.split("-")[2])==2:
                dt = datetime.datetime.strptime(d,"%d-%m-%y")
            elif "-" in d and len(d.split("-")[2])==4:
                dt = datetime.datetime.strptime(d,"%d-%m-%Y")
            else:
                dt = datetime.datetime.strptime(d,"%Y-%m-%d")
        except:
            dt = datetime.datetime.now()
        name_safe = safe_name(to_caps(_row[2] or ""))
        addr_safe = safe_name(to_caps(_row[3] or ""))
        fn = f"INV_{_row[0]}_{name_safe}_{addr_safe}.pdf"
        return redirect(url_for("view_pdf", y=dt.year, m=dt.strftime("%B"), fn=fn))
    flash("Invoice not found")
    return redirect(url_for("reports"))
# ---------- reports ----------
@app.route("/reports", methods=["GET","POST"])
@login_required
def reports():
    page = request.args.get('page', 1, type=int)
    per_page = 15
   
    if request.method == "POST":
        action = request.form.get("action")
        if action == "build":
            month_req = request.form.get("month")
            if month_req:
                parts = month_req.split()
                m_name = parts[0]
                year = int(parts[1])
            else:
                now = datetime.datetime.now()
                m_name = now.strftime("%B")
                year = now.year
               
            out_dir = ensure_out_dirs(year, m_name)
           
            build_month_summary_pdf(year, m_name, out_dir)
           
            flash(f"✅ Manual Report generated for {m_name} {year}")
            return redirect(url_for("reports"))
       
        if action == "delete_summary":
            fn = request.form.get("fn")
            if fn and Path(fn).exists():
                try:
                    Path(fn).unlink()
                    flash("Saved report deleted")
                except:
                    pass
            return redirect(url_for("reports"))

    # Data
   # Data (ab SQLite se)
    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT inv_no, date, customer, customer_address, salesman, total FROM invoices
        """).fetchall()
    rows = [
        {"inv_no": r[0], "date": r[1], "name": r[2], "address": r[3], "salesman": r[4], "total": r[5]}
        for r in _inv_rows
    ]
    rows = sorted(rows, key=lambda x: int(x.get("inv_no",0) or 0), reverse=True)
   
    from collections import defaultdict
    grouped_rows = defaultdict(list)
    for r in rows:
        d = r.get("date","")
        try:
            for fmt in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
                try:
                    dt = datetime.datetime.strptime(d, fmt)
                    break
                except:
                    continue
            key = dt.strftime("%B %Y")
        except:
            key = "Unknown"
        grouped_rows[key].append(r)

    salesman_summary = defaultdict(lambda: {"count": 0, "total": 0.0})
    for r in rows:
        sm = r.get("salesman", "Unknown")
        try:
            salesman_summary[sm]["count"] += 1
            salesman_summary[sm]["total"] += float(r.get("total", 0) or 0)
        except:
            pass

    # Pagination
    total_rows = len(rows)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_rows = rows[start:end]
    total_pages = (total_rows + per_page - 1) // per_page

    html = TPL_H + """
<style>
.rep-hero{background:linear-gradient(135deg,#0d3b34,#0f5c52);border-radius:var(--card-radius);padding:22px 26px;margin-bottom:22px}
.rep-hero h2{color:white;margin:0;font-size:20px;font-weight:800;border:none;padding:0}
.rep-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);overflow:hidden;margin-bottom:22px}
.rep-card-header{padding:16px 26px;color:white;font-size:15px;font-weight:800}
.rep-card-body{padding:22px}
.rep-month-item{margin:10px 0;border:1px solid var(--border);border-radius:10px;overflow:hidden}
.rep-month-hdr{cursor:pointer;font-weight:700;padding:14px 18px;background:linear-gradient(135deg,#f5a524,#d97706);color:white;
  display:flex;justify-content:space-between;align-items:center;
  box-shadow:0 3px 0 rgba(0,0,0,.2), 0 4px 8px rgba(0,0,0,.12);
  transition:transform .1s ease, box-shadow .1s ease;}
.rep-month-hdr:active{transform:translateY(3px);box-shadow:0 0 0 rgba(0,0,0,.2)}
.rep-month-body{display:none;padding:14px 18px}
.rep-month-body.open{display:block}
.rep-month-actions{display:flex;gap:6px;flex-wrap:nowrap;overflow-x:auto}
.rep-month-actions .btn{padding:5px 10px;font-size:11.5px;box-shadow:0 2px 0 rgba(0,0,0,.2), 0 3px 5px rgba(0,0,0,.12);white-space:nowrap}
</style>

<div class="rep-hero"><h2>📊 Reports</h2></div>

<div class="rep-card">
  <div class="rep-card-header" style="background:linear-gradient(135deg,#4338ca,#312e81)">👤 Salesman Performance</div>
  <div class="rep-card-body">
  <table class="table-wrap">
    <thead><tr><th>Salesman</th><th>Invoices</th><th>Total Sales</th></tr></thead>
    <tbody>
      {% for sm, v in salesman_summary.items() %}
      <tr>
        <td class="fw-bold">{{ sm }}</td>
        <td>{{ v.count }}</td>
        <td class="fw-bold" style="color:#0f766e">Rs {{ v.total|float|round(0)|int }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
</div>

<div class="rep-card">
  <div class="rep-card-header" style="background:linear-gradient(135deg,#f5a524,#d97706)">📅 Monthly Reports</div>
  <div class="rep-card-body">
  {% for month, items in grouped_rows.items() %}
  <div class="rep-month-item">
    <div class="rep-month-hdr" onclick="this.nextElementSibling.classList.toggle('open')">
      <span>📂 {{ month }} ({{ items|length }})</span>
      <span>▼</span>
    </div>
    <div class="rep-month-body">
      <div class="rep-month-actions">
        <button onclick="buildMonth('{{month}}')" class="btn btn-sm btn-primary">⚡ Build PDF</button>
        <button onclick="viewMonth('{{month}}')" class="btn btn-sm btn-success">👁 View</button>
        <button onclick="printMonth('{{month}}')" class="btn btn-sm btn-outline">🖨 Print</button>
      </div>
    </div>
  </div>
  {% endfor %}
  </div>
</div>

<div class="rep-card">
  <div class="rep-card-header" onclick="document.getElementById('allInvBody').classList.toggle('open')"
       style="background:linear-gradient(135deg,#0d3b34,#0f5c52);cursor:pointer;display:flex;justify-content:space-between;align-items:center;
              box-shadow:0 3px 0 rgba(0,0,0,.2), 0 4px 8px rgba(0,0,0,.12);transition:transform .1s ease, box-shadow .1s ease;">
    <span>📋 All Invoices (Page {{ page }} of {{ total_pages }})</span>
    <span>▼</span>
  </div>
  <div class="rep-card-body rep-month-body" id="allInvBody">
  <input id="searchBox" placeholder="🔍 Search..." style="width:100%;max-width:320px;padding:11px 13px;margin-bottom:14px;border:1.5px solid var(--input-border);border-radius:9px;background:var(--input-bg);color:var(--text)">
  <table class="table-wrap" id="invoiceTable">
    <thead><tr><th>Inv#</th><th>Date</th><th>Customer</th><th>Address</th><th>Total</th><th>Action</th></tr></thead>
    <tbody>
      {% for r in paginated_rows %}
      <tr>
        <td><strong>#{{ r.inv_no }}</strong></td>
        <td>{{ r.date }}</td>
        <td>{{ r.name }}</td>
        <td>{{ r.address }}</td>
        <td class="fw-bold" style="color:#0f766e">Rs {{ r.total|float|round(0)|int }}</td>
        <td><a href="{{ url_for('find_view_pdf', inv=r.inv_no) }}" target="_blank" class="btn btn-sm btn-primary">📄 PDF</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
</div>

<div style="text-align:center;margin:20px;">
  {% if page > 1 %}<a href="{{ url_for('reports', page=page-1) }}" class="btn btn-sm">Previous</a>{% endif %}
  <span>Page {{ page }} of {{ total_pages }}</span>
  {% if page < total_pages %}<a href="{{ url_for('reports', page=page+1) }}" class="btn btn-sm">Next</a>{% endif %}
</div>

<script>
document.getElementById("searchBox").addEventListener("input", function(){
  let q = this.value.toLowerCase();
  document.querySelectorAll("#invoiceTable tbody tr").forEach(row => {
    row.style.display = row.innerText.toLowerCase().includes(q) ? "" : "none";
  });
});

function buildMonth(month){
  fetch("/reports", {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:"action=build&month="+encodeURIComponent(month)})
  .then(() => {alert("✅ PDF Created!"); location.reload();});
}
function viewMonth(month){
  window.open("/open_summary_auto?month=" + encodeURIComponent(month), "_blank");
}
function printMonth(month){
  let win = window.open("/open_summary_auto?month=" + encodeURIComponent(month), "_blank");
  win.onload = () => win.print();
}
</script>
""" + TPL_F

    return render_template_string(html,
        grouped_rows=grouped_rows,
        salesman_summary=salesman_summary,
        paginated_rows=paginated_rows,
        page=page,
        total_pages=total_pages
    )

@app.route("/open_summary/<year>/<month>/<path:fn>")
@login_required
def open_summary(year, month, fn):
    base = output_base() / "SEIZE" / str(year) / str(month)
    if not base.exists():
        flash("Folder not found"); return redirect(url_for("reports"))
    return send_from_directory(base, fn)
@app.route("/open_summary_auto")
@login_required
def open_summary_auto():
    month = request.args.get("month", "").strip()
    if not month:
        return "<h3 style='color:red'>Error: Month parameter missing</h3>"
    
    # Extract month and year
    try:
        parts = month.split()
        m_name = parts[0]
        year = parts[1]
    except:
        return "<h3 style='color:red'>Invalid month format</h3>"
    
    # First try: Check if manual PDF exists
    base = output_base() / "SEIZE" / str(year) / str(m_name)
    if base.exists():
        files = list(base.glob("SUMMARY_*.pdf"))
        if files:
            files.sort(reverse=True) # Latest file
            return send_file(files[0], as_attachment=False)
    
   # If no manual PDF, generate live summary (HTML) — ab SQLite se
    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT inv_no, date, customer, customer_address, total FROM invoices
        """).fetchall()
    rows = [
        {"inv_no": r[0], "date": r[1], "name": r[2], "address": r[3], "total": r[4]}
        for r in _inv_rows
    ]
    month_rows = []
    total = 0.0
    for r in rows:
        d = r.get("date", "")
        try:
            for fmt in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
                try:
                    dt = datetime.datetime.strptime(d, fmt)
                    break
                except:
                    continue
            if dt.strftime("%B %Y") == month:
                month_rows.append(r)
                total += float(r.get("total", 0) or 0)
        except:
            continue

    # Beautiful Live Summary with Name + Address
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Live Summary - {month}</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 30px; background: #f8fafc; }}
            h2 {{ color: #1e40af; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ border: 1px solid #333; padding: 10px; text-align: left; }}
            th {{ background: #1e40af; color: white; }}
            .total {{ font-size: 22px; font-weight: bold; color: #16a34a; }}
            .address {{ font-size: 0.95em; color: #444; }}
        </style>
    </head>
    <body>
        <h2>📊 Monthly Summary - {month}</h2>
        <p class="total">Total Sales: Rs {total:,.0f} | Total Invoices: {len(month_rows)}</p>
       
        <table>
            <tr>
                <th>Inv#</th>
                <th>Date</th>
                <th>Customer Name</th>
                <th>Address</th>
                <th>Total Amount</th>
            </tr>
    """
    for r in month_rows:
        html_content += f"""
            <tr>
                <td><strong>#{r.get('inv_no')}</strong></td>
                <td>{r.get('date')}</td>
                <td><strong>{r.get('name', '')}</strong></td>
                <td class="address">{r.get('address', '') or r.get('addr', '') or r.get('billing_address', '') or '---'}</td>
                <td>Rs {float(r.get('total',0)):,.0f}</td>
            </tr>
        """
    html_content += """
        </table>
        <br>
        <button onclick="window.print()" style="padding:12px 25px; font-size:16px; background:#1e40af; color:white; border:none; border-radius:8px; cursor:pointer;">
            <a href="/invoice/new" style="display:inline-block;padding:12px 25px;font-size:16px;background:#64748b;color:white;border:none;border-radius:8px;cursor:pointer;margin-right:10px;text-decoration:none;">
    ⬅ Back
</a>
        </button>
        <button onclick="window.print()" style="padding:12px 25px; font-size:16px; background:#1e40af; color:white; border:none; border-radius:8px; cursor:pointer;">
            🖨 Print This Report
        </button>
    </body>
    </html>
    """
    return html_content
@app.route("/open/<int:y>/<m>/<path:fn>")
@login_required
def open_pdf_path(y, m, fn):
    base = output_base() / "SEIZE" / str(y) / m
    if not base.exists():
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            try:
                desktop = Path.home() / "Desktop" / "SEIZE" / str(y) / m
                desktop.mkdir(parents=True, exist_ok=True)
                base = desktop
            except Exception:
                flash("Folder not found and could not create folder"); return redirect(url_for("reports"))
    fp = base / fn
    if not fp.exists():
        # PDF missing hai — SQLite se invoice data nikaal kar dobara banane ki koshish
        regenerated = False
        m_match = re.match(r'^INV_(\d+)_', fn)
        if m_match:
            inv_no = m_match.group(1)
            try:
                with db_transaction() as _c:
                    _inv = _c.execute("""
                        SELECT inv_no, date, customer, customer_address, customer_phone,
                               tax, discount, pending_added, salesman, customer_type, logo_path
                        FROM invoices WHERE inv_no=?
                    """, (inv_no,)).fetchone()
                    if _inv:
                        _lines = _c.execute(
                            "SELECT product, qty, unit_price FROM invoice_items WHERE inv_no=?", (inv_no,)
                        ).fetchall()
                if _inv:
                    lines_data = [{"product": r[0], "qty": r[1], "unit_price": r[2]} for r in _lines]
                    company = get_setting("company_name","SEIZE")
                    logo = _inv[10] or get_setting("logo_path", "") or None
                    show_logo = (get_setting("logo_show", "1") == "1")
                    draw_invoice_pdf(
                        fp, company, logo, show_logo,
                        int(_inv[0]), _inv[1], _inv[2] or "", _inv[3] or "", _inv[4] or "",
                        lines_data, float(_inv[5] or 0), float(_inv[7] or 0),
                        discount=float(_inv[6] or 0), salesman=_inv[8] or "",
                        customer_type=_inv[9] or "customer"
                    )
                    regenerated = True
            except Exception as e:
                print("PDF auto-regenerate error:", e)

        if not regenerated or not fp.exists():
            flash(f"PDF not found and could not be regenerated: {fn}")
            return redirect(url_for("reports"))

    return send_file(
        fp,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=fn
    )

@app.route("/view_pdf/<int:y>/<m>/<path:fn>")
@login_required
def view_pdf(y,m,fn):
    html = """
<!doctype html><title>View Invoice</title>
<style>
  html, body { margin:0; padding:0; height:100%; width:100%; overflow:hidden; }
  #pdfembed { position:fixed; top:0; left:0; width:100vw; height:100vh; border:none; }
  #backBtn { position:fixed; top:14px; left:14px; z-index:9999; background:#0d2818; color:#fff; border:none; padding:10px 18px; border-radius:8px; font-size:14px; font-weight:700; cursor:pointer; box-shadow:0 2px 8px rgba(0,0,0,0.35); }
</style>
<button id="backBtn" onclick="window.location.href='/invoice/new'">⬅ Back</button>
<embed src="{{url_for('open_pdf_path', y=y, m=m, fn=fn)}}" type="application/pdf" id="pdfembed">
<script>
if (location.search.indexOf('print=1')>=0){
  setTimeout(function(){ try{ window.print(); }catch(e){ window.print(); } }, 600);
}
</script>
"""
    return render_template_string(html, y=y, m=m, fn=fn)
# ---------- Settings ----------
@app.route("/settings", methods=["GET","POST"])
@login_required
def settings():
    if request.method == "POST":
        # Normal settings
        set_setting("project_name", request.form.get("project", get_setting("project_name")))
        set_setting("company_name", request.form.get("company", get_setting("company_name")))
        set_setting("tax_default", request.form.get("tax_default","0") or "0")
        set_setting("date_format", request.form.get("date_format","dd-mm-yy"))
        set_setting("invoice_start", request.form.get("invoice_start","100"))
        set_setting("output_folder", request.form.get("output_folder",""))
        set_setting("auto_create_folders", "1" if request.form.get("auto_create")=="on" else "0")
        set_setting("logo_show", "1" if request.form.get("logo_show")=="on" else "0")
        set_setting("show_pending", "1" if request.form.get("show_pending")=="on" else "0")

        # ==================== LOGO UPLOAD ====================
        f = request.files.get("logo")
        if f and f.filename:
            fn = secure_filename(f.filename)
            path = UPLOADS / fn
            f.save(path)
            set_setting("logo_path", str(path))

        # ==================== DELETE LOGO ====================
        if request.form.get("delete_logo") == "1":
            current_path = get_setting("logo_path", "")
            if current_path:
                try:
                    path_obj = Path(current_path)
                    if path_obj.exists() and path_obj.is_file():
                        path_obj.unlink()
                    set_setting("logo_path", "")
                    flash("Logo deleted successfully!")
                except:
                    pass
            else:
                flash("No logo to delete!")

        # ==================== PASSWORD CHANGE ====================
        new_password = request.form.get("new_password")
        security_question = request.form.get("security_question")
        security_answer = request.form.get("security_answer")
        if new_password:
            if len(new_password.strip()) >= 4:
                if security_question and security_answer:
                    set_setting("app_password", new_password.strip())
                    set_setting("security_question", security_question.strip())
                    set_setting("security_answer", security_answer.strip().lower())
                    flash("Password and security question updated successfully!")
                else:
                    flash("Both security question and answer are required!")
            else:
                flash("New password must be at least 4 characters long")

        # Rebuild monthly summary
        try:
            now = datetime.datetime.now()
            out_dir = ensure_out_dirs(now.year, now.strftime("%B"))
            pdf_path = build_month_summary_pdf(now.year, now.strftime("%B"), out_dir)
            flash("Settings saved + Monthly summary rebuilt!")
        except:
            flash("Settings saved successfully!")

        return redirect(url_for("settings"))

    # ==================== GET ====================
    html = TPL_H + """
<style>
.set-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);overflow:hidden;margin-bottom:22px}
.set-card-header{padding:16px 26px;color:white;font-size:16px;font-weight:800;display:flex;align-items:center;gap:10px}
.set-card-body{padding:26px}
.set-card-body label{font-size:11.5px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:5px;margin-top:14px}
.set-card-body label:first-child{margin-top:0}
.set-card-body input[type=text],.set-card-body input[type=password],.set-card-body input:not([type]),.set-card-body select{
  width:100%;padding:11px 13px;border:1.5px solid var(--input-border);border-radius:9px;font-size:14px;
  background:var(--input-bg);color:var(--text);box-sizing:border-box;transition:border .15s, box-shadow .15s;
}
.set-card-body input:focus,.set-card-body select:focus{outline:none;border-color:var(--btn-primary);box-shadow:0 0 0 3px rgba(79,70,229,.12)}
.set-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.set-check{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:600;color:var(--text);margin-top:16px;cursor:pointer}
.set-check-highlight{background:#fef3c7;padding:12px 14px;border-radius:9px;border:1px solid #f5a524}
</style>

<h2 style="margin-bottom:20px;">⚙️ Settings</h2>

<div class="set-card">
  <div class="set-card-header" style="background:linear-gradient(135deg,#0d3b34,#0f5c52)">🏢 General Settings</div>
  <div class="set-card-body">
  <form method="post" enctype="multipart/form-data">
    <div class="set-grid">
      <div>
        <label>Project Name</label>
        <input name="project" value="{{project}}" placeholder="Project name">
      </div>
      <div>
        <label>Company Name</label>
        <input name="company" value="{{company}}" placeholder="Company name">
      </div>
      <div>
        <label>Default Tax %</label>
        <input name="tax_default" value="{{tax}}" placeholder="0">
      </div>
      <div>
        <label>Date Format</label>
        <select name="date_format">
          {% for f in ["dd-mm-yy","dd-mm-yyyy","yyyy-mm-dd"] %}
            <option value="{{f}}" {% if f==date_format %}selected{% endif %}>{{f}}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label>Invoice Start Number</label>
        <input name="invoice_start" value="{{invoice_start}}" placeholder="100">
      </div>
      <div>
        <label>Output Folder (optional)</label>
        <input name="output_folder" value="{{output_folder}}" placeholder="Leave blank for default">
      </div>
    </div>

    <label class="set-check"><input type="checkbox" name="auto_create" {% if auto_create=='1' %}checked{% endif %} style="width:auto"> Auto-create folders</label>
    <label class="set-check"><input type="checkbox" name="logo_show" {% if logo_show=='1' %}checked{% endif %} style="width:auto"> Show logo on invoices</label>
    <label class="set-check set-check-highlight"><input type="checkbox" name="show_pending" {% if show_pending=='1' %}checked{% endif %} style="width:auto"> Show Pending Amount in New Invoice</label>

    <label style="margin-top:18px">Upload Logo</label>
    <input type="file" name="logo" accept="image/*">

    <div style="margin-top:22px;text-align:right;">
      <button class="btn btn-primary btn-lg">💾 Save Settings</button>
    </div>
  </form>
  </div>
</div>

<div class="set-card">
  <div class="set-card-header" style="background:linear-gradient(135deg,#4338ca,#312e81)">🖼️ Current Logo</div>
  <div class="set-card-body">
  {% if logo_path %}
    <p style="color:var(--text)">✅ Logo is set (<code>{{logo_path}}</code>)</p>
    <form method="post" style="display:inline;">
      <input type="hidden" name="delete_logo" value="1">
      <button type="submit" class="btn btn-danger">🗑 Delete Logo</button>
    </form>
  {% else %}
    <p style="color:var(--text-muted)"><strong>No logo uploaded yet.</strong></p>
  {% endif %}
  </div>
</div>

<div class="set-card">
  <div class="set-card-header" style="background:linear-gradient(135deg,#0d9488,#0f766e)">🔑 Update App Login Password</div>
  <div class="set-card-body">
  <p style="color:var(--text-muted); margin-bottom:6px;">Security question is mandatory.</p>
  <form method="post">
    <label>New Password</label>
    <input name="new_password" type="password" placeholder="At least 4 characters">
    <label>Security Question</label>
    <input name="security_question" placeholder="e.g. What is your mother's maiden name?" required>
    <label>Answer</label>
    <input name="security_answer" placeholder="Enter answer (case insensitive)" required>
    <div style="margin-top:22px;text-align:right;">
      <button class="btn btn-success btn-lg">Update Password & Question</button>
    </div>
  </form>
  </div>
</div>
""" + TPL_F

    return render_template_string(html,
        project=get_setting("project_name"),
        company=get_setting("company_name"),
        tax=get_setting("tax_default","0"),
        date_format=get_setting("date_format","dd-mm-yy"),
        invoice_start=get_setting("invoice_start","100"),
        output_folder=get_setting("output_folder",""),
        auto_create=get_setting("auto_create_folders","1"),
        logo_show=get_setting("logo_show","1"),
        logo_path=get_setting("logo_path",""),
        developer_name=get_setting("developer_name"),
        developer_phone=get_setting("developer_phone"),
        contact_msg=get_setting("contact_msg"),
        show_pending=get_setting("show_pending", "0")
    )
# ================== سیلز ریکارڈ ==================
# ================== SALES RECORD + MONTHLY TARGETS (بالکل درست اور خوبصورت) ==================
@app.route("/sales_record")
@login_required
def sales_record():
    with db_transaction() as _c:
        _inv_rows = _c.execute("SELECT inv_no, date FROM invoices").fetchall()
        _line_rows = _c.execute("SELECT inv_no, product, qty FROM invoice_items").fetchall()
    invoices = [{"inv_no": r[0], "date": r[1]} for r in _inv_rows]
    lines = [{"inv_no": r[0], "product": r[1], "qty": r[2]} for r in _line_rows]
    monthly_data = {}
    grand_totals = {}

    for line in lines:
        inv_no = line.get("inv_no")
        inv = next((i for i in invoices if i.get("inv_no") == inv_no), None)
        if not inv:
            continue

        date_str = inv.get("date", "")
        try:
            if "-" in date_str:
                parts = date_str.split("-")
                if len(parts) == 3:
                    if len(parts[2]) == 2:
                        dt = datetime.datetime.strptime(date_str, "%d-%m-%y")
                    elif len(parts[2]) == 4 and len(parts[0]) == 4:
                        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                    else:
                        dt = datetime.datetime.strptime(date_str, "%d-%m-%Y")
            else:
                continue

            month_name = dt.strftime("%B %Y")
        except:
            continue

        prod = to_caps(line.get("product", "Unknown"))

        try:
            qty = float(line.get("qty", 0) or 0)
        except:
            qty = 0.0

        if qty <= 0:
            continue

        if month_name not in monthly_data:
            monthly_data[month_name] = {}
            grand_totals[month_name] = 0.0

        if prod not in monthly_data[month_name]:
            monthly_data[month_name][prod] = 0.0

        monthly_data[month_name][prod] += qty
        grand_totals[month_name] += qty

    result = {}
    for month, prods in monthly_data.items():
        items = [{"product": p, "qty": q} for p, q in sorted(prods.items(), key=lambda x: x[1], reverse=True)]
        result[month] = items

    sorted_months = sorted(result.keys(), key=lambda x: datetime.datetime.strptime(x, "%B %Y"), reverse=True)
    sorted_result = {m: result[m] for m in sorted_months}

    html = TPL_H + """

<style>
@media print {
  .no-print, #globalSearch, .btn {
    display: none !important;
  }
  body { background: white; }
  .card { box-shadow: none !important; border: none !important; }
}
</style>

<h2>📊 Sales Record (Product-wise Monthly Quantity Sold)</h2>
<p class="small">Monthly Sale QTY (CSV based)</p>

<input type="text" id="globalSearch" placeholder="🔍 search product name" 
       class="no-print"
       style="width:100%;max-width:700px;padding:14px;font-size:16px;border-radius:10px;border:2px solid #1976d2;margin:20px 0;">

<div class="no-print" style="margin-bottom:20px;">
  <a href="/export_sales" class="btn" style="background:#00897b;">⬇ Export CSV</a>
</div>

{% if sorted_result %}
  {% for month, items in sorted_result.items() %}
  <div class="card" style="margin-bottom:30px;box-shadow:0 4px 15px rgba(0,0,0,0.08);border-radius:12px;overflow:hidden;">
    
    <h3 style="background:#1976d2;color:white;padding:16px;margin:0;font-size:19px;">
      {{ month }}
      
      <span style="float:right;font-size:17px;">
        Total QTY: <strong>{{ "%.2f"|format(grand_totals[month]) }}</strong>
      </span>

      <span class="no-print" style="float:right;margin-right:20px;">
        <button onclick="printMonth(this)" style="padding:6px 12px;">🖨️</button>
        <button onclick="downloadPDF(this)" style="padding:6px 12px;">📄</button>
      </span>
    </h3>

    <div style="padding:20px;">
      <table style="width:100%;border-collapse:collapse;">
        <thead style="background:#e3f2fd;">
          <tr>
            <th style="padding:12px;text-align:left;">Product Name</th>
            <th style="padding:12px;text-align:center;width:200px;">Sold QTY</th>
          </tr>
        </thead>
        <tbody>
          {% for item in items %}
          <tr class="search-row">
            <td style="padding:12px;font-weight:600;">{{ item.product }}</td>
            <td style="padding:12px;text-align:center;font-weight:bold;font-size:17px;color:#1565c0;">
              {{ "%.2f"|format(item.qty) }}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% endfor %}
{% else %}
  <div class="card" style="text-align:center;padding:50px;color:#666;background:#f9f9f9;">
    <h3>No Record Found</h3>
  </div>
{% endif %}

<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>

<script>
document.getElementById('globalSearch').addEventListener('keyup', function() {
  let val = this.value.toLowerCase().trim();
  document.querySelectorAll('.search-row').forEach(row => {
    let text = row.textContent.toLowerCase();
    row.style.display = text.includes(val) ? '' : 'none';
  });
});

function printMonth(btn) {
  let card = btn.closest('.card');
  let printContents = card.outerHTML;
  let originalContents = document.body.innerHTML;

  document.body.innerHTML = printContents;
  window.print();
  document.body.innerHTML = originalContents;
  location.reload();
}

function downloadPDF(btn) {
  let card = btn.closest('.card');

  let opt = {
    margin: 0.5,
    filename: 'sales_' + new Date().getTime() + '.pdf',
    image: { type: 'jpeg', quality: 1 },
    html2canvas: { scale: 2 },
    jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' }
  };

  html2pdf().set(opt).from(card).save();
}
</script>

<p class="no-print" style="text-align:center;margin-top:40px;">
  <a href="{{ url_for('home') }}" class="btn" style="padding:14px 40px;font-size:18px;background:#424242;">
    ← Back to Home
  </a>
</p>

""" + TPL_F

    return render_template_string(
        html,
        sorted_result=sorted_result,
        grand_totals=grand_totals,
        project=get_setting("project_name")
    )

@app.route("/export_sales")
@login_required
def export_sales():
    import csv
    from flask import send_file

    file_path = "sales_report.csv"

    with db_transaction() as _c:
        _rows = _c.execute("""
            SELECT i.date, ii.product, ii.qty
            FROM invoice_items ii
            JOIN invoices i ON i.inv_no = ii.inv_no
        """).fetchall()

    with open(file_path, "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Month", "Product", "Qty"])
        for date_val, product, qty in _rows:
            writer.writerow([date_val, product, qty])

    return send_file(file_path, as_attachment=True)
# ================== Stock Entry (Final – Clean & Working) ==================
@app.route("/stock_entry", methods=["GET", "POST"])
@login_required
def stock_entry():
    msg = ""
    now = datetime.datetime.now()
    current_month_key = now.strftime("%B %Y")
    
    month_folder = ensure_out_dirs(now.year, now.strftime("%B"))
    stock_report_file = month_folder / f"Stock_Entry_{now.year}_{now.strftime('%B')}.csv"

    # Create file if not exists
    if not stock_report_file.exists():
        with open(stock_report_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Entry_ID", "Date", "Product", "Quantity", "Purchase_Price", "Wholesaler_Price", "Distributor_Price", "Customer_Price"])

    if request.method == "POST":
        action = request.form.get("action")
        conn = db()
        cur = conn.cursor()

        if action == "delete":
            entry_id = request.form.get("entry_id")
            try:
                with db_transaction() as _c:
                    _row = _c.execute(
                        "SELECT product, qty FROM stock_entries WHERE id=?", (entry_id,)
                    ).fetchone()
                    if _row:
                        prod, qty = _row[0], float(_row[1] or 0)
                        _c.execute("UPDATE products SET stock = stock - ? WHERE name = ?", (qty, prod))
                        _c.execute("DELETE FROM stock_entries WHERE id=?", (entry_id,))
                        flash("Entry deleted successfully. Stock reduced.")
                    else:
                        flash("Entry not found.")
            except Exception as e:
                flash(f"❌ Delete failed: {e}")

            conn.close()
            return redirect(url_for("stock_entry"))

        # === Add New Stock Entry ===
        product = to_caps(request.form.get("product", "").strip())  # Auto Title Case
        qty_str = request.form.get("qty", "").strip()
        price_str = request.form.get("price", "").strip()
        wholesaler_price_str = request.form.get("wholesaler_price", "").strip()
        distributor_price_str = request.form.get("distributor_price", "").strip()
        customer_price_str = request.form.get("customer_price", "").strip()
        min_stock_str = request.form.get("min_stock", "").strip()

        if not product or not qty_str or not price_str:
            msg = "Please fill all required fields"
        else:
            try:
                qty = float(qty_str)
                price = float(price_str)
                wholesaler_price = float(wholesaler_price_str) if wholesaler_price_str else None
                distributor_price = float(distributor_price_str) if distributor_price_str else None
                customer_price = float(customer_price_str) if customer_price_str else None
                min_stock_new = float(min_stock_str) if min_stock_str else None

                if qty <= 0:
                    raise ValueError
            except:
                msg = "Quantity and Price must be valid numbers"
            else:
                try:
                    with db_transaction() as _c:
                        # SQLite Products Update
                        _c.execute("""
                            INSERT INTO products (name, unit_price, purchase_price, wholesaler_price,
                                                 distributor_price, customer_price, stock, min_stock)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(name) DO UPDATE SET
                                stock = stock + ?,
                                purchase_price = ?,
                                wholesaler_price = COALESCE(?, wholesaler_price),
                                distributor_price = COALESCE(?, distributor_price),
                                customer_price = COALESCE(?, customer_price),
                                min_stock = COALESCE(?, min_stock)
                        """, (
                            product, customer_price or price, price,
                            wholesaler_price, distributor_price, customer_price,
                            qty, min_stock_new,
                            qty, price, wholesaler_price, distributor_price, customer_price, min_stock_new
                        ))

                        # Stock Entry Log (ab SQLite mein, CSV nahi)
                        _c.execute("""
                            INSERT INTO stock_entries
                                (date, product, qty, purchase_price, wholesaler_price,
                                 distributor_price, customer_price, month_key)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            now.strftime("%d-%m-%Y"), product, qty, price,
                            wholesaler_price, distributor_price, customer_price,
                            current_month_key
                        ))

                    flash(f"✅ {qty} × {product} Successfully Added to Stock")
                except Exception as e:
                    flash(f"❌ Stock entry save failed: {e}")

                return redirect(url_for("stock_entry"))

        conn.close()

    # ===================== GET: All Monthly Data (Foldable, ab SQLite se) =====================
    all_months = {}
    with db_transaction() as _c:
        _rows = _c.execute("""
            SELECT id, date, product, qty, purchase_price, wholesaler_price,
                   distributor_price, customer_price, month_key
            FROM stock_entries
            ORDER BY id DESC
        """).fetchall()

    for r in _rows:
        month_key = r[8] or "Unknown"
        entry = {
            "Entry_ID": r[0],
            "Date": r[1],
            "Product": r[2],
            "Quantity": r[3],
            "Purchase_Price": r[4],
            "Wholesaler_Price": r[5] if r[5] is not None else "",
            "Distributor_Price": r[6] if r[6] is not None else "",
            "Customer_Price": r[7] if r[7] is not None else "",
        }
        all_months.setdefault(month_key, []).append(entry)

    # Current month on top
    sorted_months = sorted(all_months.keys(), 
                          key=lambda x: datetime.datetime.strptime(x, "%B %Y") if x else datetime.datetime.min, 
                          reverse=True)

    product_list = [p['name'] for p in load_products()]
    html = TPL_H + """
<style>
.se-hero{background:linear-gradient(135deg,#0d3b34,#0f5c52);border-radius:var(--card-radius);padding:22px 26px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px}
.se-hero h2{color:white;margin:0;font-size:20px;font-weight:800;border:none;padding:0}
.se-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);overflow:hidden;margin-bottom:24px}
.se-card-header{background:linear-gradient(135deg,#0d3b34,#0f5c52);color:white;padding:16px 26px;font-size:16px;font-weight:800}
.se-card-body{padding:26px}
.se-card-body label{font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:5px}
.se-card-body input{width:100%;padding:10px 12px;border:1.5px solid var(--input-border);border-radius:9px;font-size:14px;background:var(--input-bg);color:var(--text);box-sizing:border-box}
.se-card-body input:focus{outline:none;border-color:var(--btn-primary);box-shadow:0 0 0 3px rgba(79,70,229,.12)}
</style>

<div class="se-hero">
  <h2>🏭 Stock Entry + Monthly Reports</h2>
  <a href="{{ url_for('stock_summary') }}" class="btn btn-warning">📊 View Full Stock Summary</a>
</div>

{% if msg %}<div class="notice">{{ msg }}</div>{% endif %}

<!-- Add Stock Form -->
<div class="se-card">
  <div class="se-card-header">➕ Add New Stock Entry</div>
  <div class="se-card-body">
  <form method="post">
    <div style="display:grid;grid-template-columns:320px 140px 140px 140px 140px 140px 130px;gap:16px;align-items:end;">
      <div>
        <label>Product Name *</label>
        <input name="product" id="se_product" list="allprods" placeholder="Select or type" required
               oninput="autoFillPrices(this.value)">
        <datalist id="allprods">
          {% for p in product_list %}<option value="{{ p }}">{% endfor %}
        </datalist>
      </div>
      <div><label>Quantity *</label><input name="qty" type="number" step="any" required></div>
      <div><label>Purchase Price *</label><input name="price" id="se_purchase" type="number" step="any" required></div>
      <div><label>🏭 Wholesaler</label><input name="wholesaler_price" id="se_wp" type="number" step="any" style="background:#e0e7ff;"></div>
      <div><label>🚚 Distributor</label><input name="distributor_price" id="se_dp" type="number" step="any" style="background:#f3e8ff;"></div>
      <div><label>🛒 Customer</label><input name="customer_price" id="se_cp" type="number" step="any" style="background:#ccfbf1;"></div>
      <div><label>Min Stock</label><input name="min_stock" id="se_ms" type="number" step="any"></div>

      <div style="grid-column:span 7;text-align:right;margin-top:6px;">
        <button class="btn btn-success btn-lg">➕ Add to Stock</button>
      </div>
    </div>
  </form>
  </div>
</div>

<script>
const seProds = {{ prods_json|safe }};
function autoFillPrices(val) {
  if (!val) return;
  const p = seProds.find(x => x.name.toLowerCase() === val.trim().toLowerCase());
  if (!p) return;
  if (p.purchase_price) document.getElementById('se_purchase').value = p.purchase_price;
  if (p.wholesaler_price) document.getElementById('se_wp').value = p.wholesaler_price;
  if (p.distributor_price) document.getElementById('se_dp').value = p.distributor_price;
  if (p.customer_price) document.getElementById('se_cp').value = p.customer_price;
  if (p.min_stock) document.getElementById('se_ms').value = p.min_stock;
}
document.addEventListener('DOMContentLoaded', function(){
  const el = document.getElementById('se_product');
  if(el) {
    el.addEventListener('change', () => autoFillPrices(el.value));
    el.addEventListener('input', () => autoFillPrices(el.value));
  }
});
</script>

<h3 style="margin:30px 0 15px;">📂 All Monthly Stock Entries</h3>

{% for month_key in sorted_months %}
<div class="card" style="margin-bottom:18px;">
  <div style="background:#1e40af;color:white;padding:16px;cursor:pointer;font-weight:bold;font-size:17px;"
       onclick="this.nextElementSibling.style.display = (this.nextElementSibling.style.display === 'none') ? 'block' : 'none';">
    📆 {{ month_key }} 
    <span style="float:right;">▼</span>
  </div>
  <div class="month-body" style="{% if month_key == current_month_key %}display:block;{% else %}display:none;{% endif %}">
    <table style="width:100%;">
      <thead style="background:#1b5e20;color:white;">
        <tr>
          <th>ID</th><th>Date</th><th>Product</th><th>Qty</th>
          <th>Purchase</th><th>Wholesaler</th><th>Distributor</th><th>Customer</th><th>Action</th>
        </tr>
      </thead>
      <tbody>
        {% for e in all_months[month_key] %}
        <tr>
          <td>{{ e.Entry_ID }}</td>
          <td>{{ e.Date }}</td>
          <td><strong>{{ e.Product }}</strong></td>
          <td>{{ e.Quantity }}</td>
          <td>Rs {{ e.Purchase_Price }}</td>
          <td>Rs {{ e.Wholesaler_Price or '—' }}</td>
          <td>Rs {{ e.Distributor_Price or '—' }}</td>
          <td>Rs {{ e.Customer_Price or '—' }}</td>
          <td>
            <form method="post" style="display:inline;">
              <input type="hidden" name="action" value="delete">
              <input type="hidden" name="entry_id" value="{{ e.Entry_ID }}">
              <button class="btn btn-danger btn-sm" onclick="return confirm('Delete this entry?')">Delete</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endfor %}

{% if not sorted_months %}
<p style="text-align:center;color:#888;padding:50px;">No stock entries found yet.</p>
{% endif %}
""" + TPL_F

    return render_template_string(
        html,
        msg=msg,
        sorted_months=sorted_months,
        all_months=all_months,
        current_month_key=current_month_key,
        product_list=product_list,
        prods_json=json.dumps(load_products()),
        project=get_setting("project_name")
    )
@app.route("/stock_summary")
@login_required
def stock_summary():
    with db_transaction() as _c:
        _sale_rows = _c.execute("""
            SELECT month_key, product, SUM(qty) FROM stock_entries
            GROUP BY month_key, product
        """).fetchall()
        _stock_rows = _c.execute("SELECT name, stock FROM products").fetchall()

    stock_qty = {to_caps(r[0]): float(r[1] or 0) for r in _stock_rows}

    sales_by_month = {}
    for month_key, prod, qty in _sale_rows:
        prod_c = to_caps((prod or "").strip())
        qty = float(qty or 0)
        if qty <= 0:
            continue
        sales_by_month.setdefault(month_key, {})
        sales_by_month[month_key][prod_c] = sales_by_month[month_key].get(prod_c, 0.0) + qty

    all_months = {}
    for month_key, sale_qty in sales_by_month.items():
        totals = {
            prod: {"sale_qty": qty, "stock_qty": stock_qty.get(prod, 0.0)}
            for prod, qty in sale_qty.items()
        }
        sorted_items = sorted(totals.items(), key=lambda x: x[1]["stock_qty"], reverse=True)
        all_months[month_key] = {"totals": sorted_items}

    if not all_months:
        flash("No stock entries found.")
        return redirect(url_for("stock_entry"))
    current_month = datetime.datetime.now().strftime("%B %Y")
    sorted_months = sorted(
        all_months.keys(),
        key=lambda x: (x != current_month, datetime.datetime.strptime(x, "%B %Y") if x else datetime.datetime.min),
        reverse=True
    )

    html = TPL_H + """
<style>
.no-print {display:inline;}
@media print {
  .no-print, #globalSearch, .btn {display:none !important;}
}
.card {margin-bottom:25px; border-radius:12px; overflow:hidden; box-shadow:0 4px 15px rgba(0,0,0,0.08);}
.summary-header {background:#1e40af; color:white; padding:16px; cursor:pointer; font-weight:bold; font-size:17px;}
</style>

<div style="margin-bottom:20px;">
  <a href="{{ url_for('stock_entry') }}" class="btn btn-secondary" style="padding:12px 30px;font-size:16px;">
    ← Back to Stock Entry
  </a>
</div>

<h2>📊 Monthly Stock Entry Summary (with Current Stock)</h2>

<input type="text" id="globalSearch" placeholder="🔍 Search product name, SR, stock qty..."
       class="no-print form-control" style="max-width:650px;margin:20px 0;">

{% for month_key in sorted_months %}
{% set data = all_months[month_key] %}
<div class="card">
  <div class="summary-header" onclick="this.nextElementSibling.style.display = (this.nextElementSibling.style.display === 'none') ? 'block' : 'none';">
    📆 {{ month_key }}
    <span class="no-print" style="float:right;">
      <button onclick="printMonth(this)" style="padding:6px 14px;margin-right:8px;">🖨️ Print</button>
    </span>
  </div>
  
  <div class="month-body" style="{% if loop.first %}display:block;{% else %}display:none;{% endif %} padding:20px;">
    <table style="width:100%;border-collapse:collapse;">
      <thead style="background:#1e40af;color:white;">
        <tr>
          <th style="padding:12px;width:60px;text-align:center;">SR</th>
          <th style="padding:12px;text-align:left;">Product Name</th>
          <th style="padding:12px;text-align:center;">Total Sale Qty</th>
          <th style="padding:12px;text-align:center;">Current Stock Qty</th>
        </tr>
      </thead>
      <tbody>
        {% for prod, info in data.totals %}
        {% set sr = loop.index %}
        <tr class="search-row">
          <td style="text-align:center;font-weight:600;">{{ sr }}</td>
          <td style="padding:12px;font-weight:500;">{{ prod }}</td>
          <td style="padding:12px;text-align:center;font-weight:bold;font-size:17px;color:#1e40af;">
            {{ "%.2f"|format(info.sale_qty) }}
          </td>
          <td style="padding:12px;text-align:center;font-weight:bold;font-size:17px;color:#16a34a;">
            {{ "%.2f"|format(info.stock_qty) }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endfor %}

<script>
document.getElementById('globalSearch').addEventListener('keyup', function() {
  let val = this.value.toLowerCase().trim();
  document.querySelectorAll('.search-row').forEach(row => {
    let text = row.textContent.toLowerCase();
    row.style.display = text.includes(val) ? '' : 'none';
  });
});

function printMonth(btn) {
  let card = btn.closest('.card');
  let content = card.querySelector('.month-body').innerHTML;
  let monthTitle = card.querySelector('.summary-header').childNodes[0].textContent.trim();
  
  let win = window.open('', '', 'width=1000,height=800');
  win.document.write(`
    <html>
    <head><title>Stock Summary - ${monthTitle}</title>
    <style>
      body {font-family: Arial, sans-serif; padding:30px;}
      h2 {text-align:center; color:#1e40af;}
      table {width:100%; border-collapse:collapse; margin-top:20px;}
      th, td {border:1px solid #333; padding:12px; text-align:center;}
      th {background:#1a2a5e; color:white;}
    </style>
    </head>
    <body>
      <h2>Stock Summary - ${monthTitle}</h2>
      ${content}
    </body>
    </html>
  `);
  win.document.close();
  win.print();
}
</script>
""" + TPL_F

    return render_template_string(
        html,
        sorted_months=sorted_months,
        all_months=all_months,
        project=get_setting("project_name")
    )
# 5 PROFESSIONAL ENGLISH CARDS - FINAL VERSION
# ========================================


# 3. Monthly Targets (ٹھیک شدہ)
# Replace the existing @app.route("/target") function with this updated version

@app.route("/target/print/<month>")
@login_required
def print_target_month(month):
    with db_transaction() as _c:
        _rows = _c.execute(
            "SELECT product, qty FROM monthly_targets WHERE month=?", (month,)
        ).fetchall()
        _inv_rows = _c.execute("""
            SELECT ii.product, SUM(ii.qty)
            FROM invoice_items ii
            JOIN invoices i ON i.inv_no = ii.inv_no
            WHERE strftime('%m-%Y', i.date) = strftime('%m-%Y', ?) OR 1=1
            GROUP BY ii.product
        """, (month,)).fetchall()

    achieved = {}
    with db_transaction() as _c2:
        _all_lines = _c2.execute("""
            SELECT ii.product, ii.qty, i.date FROM invoice_items ii
            JOIN invoices i ON i.inv_no = ii.inv_no
        """).fetchall()
    for prod, qty, d in _all_lines:
        dt = None
        for fmt in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                dt = datetime.datetime.strptime(d, fmt)
                break
            except:
                continue
        if not dt or dt.strftime("%B %Y") != month:
            continue
        p = to_caps(prod or "")
        achieved[p] = achieved.get(p, 0.0) + float(qty or 0)

    rows_html = ""
    for prod, qty in _rows:
        ach = achieved.get(to_caps(prod or ""), 0.0)
        pct = round((ach / qty * 100), 1) if qty else 0
        rows_html += f"""
            <tr>
                <td>{prod}</td>
                <td>{qty:.1f}</td>
                <td>{ach:.1f}</td>
                <td>{pct}%</td>
            </tr>
        """

    html_content = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <title>Target Report - {month}</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 30px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ border: 1px solid #333; padding: 10px; text-align: left; }}
        th {{ background: #1e40af; color: white; }}
    </style></head><body>
        <h2>🎯 Target Report — {month}</h2>
        <table>
            <tr><th>Product</th><th>Target</th><th>Achieved</th><th>%</th></tr>
            {rows_html if rows_html else "<tr><td colspan='4' style='text-align:center'>No targets for this month</td></tr>"}
        </table>
        <br>
        <a href="/invoice/new" style="display:inline-block;padding:12px 25px;font-size:16px;background:#64748b;color:white;border:none;border-radius:8px;cursor:pointer;margin-right:10px;text-decoration:none;">⬅ Back</a>
        <button onclick="window.print()" style="padding:12px 25px;font-size:16px;background:#1e40af;color:white;border:none;border-radius:8px;cursor:pointer;">🖨 Print</button>
    </body></html>
    """
    return html_content


@app.route("/target", methods=["GET", "POST"])
@login_required
def target():
    import calendar
    prods = load_products()
    growth = float(get_setting("growth_rate", "10"))

    if request.method == "POST":
        act = request.form.get("action", "")

        if act == "delete":
            product_del = request.form.get("product_del", "").strip()
            month_del = request.form.get("month_del", "").strip()
            today_m = datetime.date.today().strftime("%B %Y")

            if not month_del:
                flash("Month missing")
                return redirect(url_for("target"))

            if month_del == today_m:
                flash("⚠️ Cannot delete current month target. Edit qty to 0 instead.")
                return redirect(url_for("target"))

            try:
                with db_transaction() as _c:
                    if product_del:
                        _c.execute("DELETE FROM monthly_targets WHERE month=? AND product=?", (month_del, product_del))
                        flash(f"🗑️ Target for {product_del} in {month_del} deleted")
                    else:
                        _c.execute("DELETE FROM monthly_targets WHERE month=?", (month_del,))
                        flash(f"🗑️ All targets for {month_del} deleted")
            except Exception as e:
                flash(f"❌ Delete failed: {e}")
            return redirect(url_for("target"))

        # Save target (ab SQLite mein)
        product = request.form.get("product")
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
        base_qty = float(request.form.get("qty", 0))

        if not product or base_qty <= 0:
            flash("Invalid product or quantity")
            return redirect(url_for("target"))

        month_name = calendar.month_name[month] + f" {year}"

        try:
            with db_transaction() as _c:
                _c.execute("""
                    INSERT INTO monthly_targets (month, product, qty)
                    VALUES (?, ?, ?)
                    ON CONFLICT(month, product) DO UPDATE SET qty=excluded.qty
                """, (month_name, product, base_qty))
            flash(f"Target saved for {product} in {month_name}")
        except Exception as e:
            flash(f"❌ Target save failed: {e}")
   # ================= AUTO CREATE NEXT MONTH TARGET from PREVIOUS MONTH SALES =================
    today = datetime.date.today()

    next_month_date = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    next_month_name = next_month_date.strftime("%B %Y")
    prev_month_date = (today.replace(day=1) - datetime.timedelta(days=1))
    prev_month_name = prev_month_date.strftime("%B %Y")

    with db_transaction() as _c:
        _all_targets_rows = _c.execute("SELECT month, product, qty FROM monthly_targets").fetchall()
        _all_lines_rows = _c.execute("""
            SELECT ii.product, ii.qty, i.date FROM invoice_items ii
            JOIN invoices i ON i.inv_no = ii.inv_no
        """).fetchall()

    targets_all = [{"month": r[0], "product": r[1], "qty": r[2]} for r in _all_targets_rows]
    existing_next = {t["product"] for t in targets_all if t.get("month") == next_month_name}

    # Previous month ki actual sales (in-memory, ek hi query se)
    prev_sales = {}
    for prod, qty, d in _all_lines_rows:
        dt = None
        for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
            try: dt = datetime.datetime.strptime(d, fmt); break
            except: continue
        if not dt or dt.strftime("%B %Y") != prev_month_name:
            continue
        p = to_caps(prod or "")
        prev_sales[p] = prev_sales.get(p, 0.0) + float(qty or 0)

    prev_targets = {t["product"]: float(t.get("qty",0)) for t in targets_all if t.get("month") == prev_month_name}

    if prev_sales or prev_targets:
        all_prods_for_target = set(list(prev_sales.keys()) + list(prev_targets.keys()))
        new_rows = []
        for prod in all_prods_for_target:
            if prod in existing_next:
                continue
            base_qty = prev_targets.get(prod, prev_sales.get(prod, 0.0))
            if base_qty <= 0:
                continue
            new_qty = base_qty * (1 + growth / 100)
            new_rows.append((next_month_name, prod, new_qty))
        if new_rows:
            try:
                with db_transaction() as _c:
                    for m, p, q in new_rows:
                        _c.execute("""
                            INSERT INTO monthly_targets (month, product, qty)
                            VALUES (?, ?, ?)
                            ON CONFLICT(month, product) DO NOTHING
                        """, (m, p, q))
            except Exception as e:
                print("Auto next-month target error:", e)

    # ================= FETCH CURRENT MONTH TARGET + ACHIEVED (SQLite se) =================
    current_month = today.strftime("%B %Y")

    with db_transaction() as _c:
        _cur_target_rows = _c.execute(
            "SELECT product, qty FROM monthly_targets WHERE month=?", (current_month,)
        ).fetchall()
    current_targets = {p: float(q or 0) for p, q in _cur_target_rows}

    achieved = {}
    for prod, qty, d in _all_lines_rows:
        dt = None
        for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
            try: dt = datetime.datetime.strptime(d, fmt); break
            except: continue
        if not dt or dt.strftime("%B %Y") != current_month:
            continue
        p = to_caps(prod or "")
        achieved[p] = achieved.get(p, 0.0) + float(qty or 0)

    data = []
    for prod_name, target_qty in current_targets.items():
        ach = achieved.get(prod_name, 0.0)
        percent = (ach / target_qty * 100) if target_qty > 0 else 0
        data.append({
            "product": prod_name,
            "target": target_qty,
            "achieved": ach,
            "percent": round(percent, 1)
        })

    # Build ALL months history grouped (SQLite se — delete turant reflect hoga)
    history_months = {}
    for t in targets_all:
        m = t.get("month","")
        history_months.setdefault(m, [])
        try: history_months[m].append({"product": t["product"], "qty": float(t.get("qty",0))})
        except: pass

    def get_month_achieved(month_name):
        ach = {}
        for prod, qty, d in _all_lines_rows:
            dt = None
            for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
                try: dt = datetime.datetime.strptime(d, fmt); break
                except: continue
            if not dt or dt.strftime("%B %Y") != month_name:
                continue
            p = to_caps(prod or "")
            ach[p] = ach.get(p, 0.0) + float(qty or 0)
        return ach

    sorted_history = sorted(history_months.keys(),
        key=lambda x: datetime.datetime.strptime(x, "%B %Y") if x else datetime.datetime.min,
        reverse=True)

    html = TPL_H + """
<style>
.target-month{border:1px solid var(--border);border-radius:var(--card-radius);margin-bottom:14px;overflow:hidden;box-shadow:var(--card-shadow)}
.target-month-hdr{background:linear-gradient(135deg,#f5a524,#d97706);color:white;padding:14px 20px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;font-weight:700;font-size:14px;user-select:none;
  box-shadow:0 3px 0 rgba(0,0,0,.2), 0 4px 8px rgba(0,0,0,.12);transition:transform .1s ease, box-shadow .1s ease;}
.target-month-hdr:active{transform:translateY(3px);box-shadow:0 0 0 rgba(0,0,0,.2)}
.target-month-body{display:none;padding:0}
.target-month-body.open{display:block}
.target-tbl{width:100%;border-collapse:collapse}
.target-tbl th{background:var(--body-bg);padding:10px 12px;font-size:12px;font-weight:700;text-align:left;color:var(--text-muted)}
.target-tbl td{padding:9px 12px;border-bottom:1px solid var(--border);font-size:13px}
.pbar{height:10px;background:var(--border);border-radius:5px;overflow:hidden}
.pbar-fill{height:100%;border-radius:5px;transition:width .5s}
.tgt-hero{background:linear-gradient(135deg,#0d3b34,#0f5c52);border-radius:var(--card-radius);padding:22px 26px;margin-bottom:22px}
.tgt-hero h2{color:white;margin:0;font-size:20px;font-weight:800;border:none;padding:0}
.tgt-hero p{color:#cfe6e0;margin-top:4px;font-size:13px}
.tgt-form-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);overflow:hidden;margin-bottom:20px}
.tgt-form-header{padding:16px 26px;color:white;font-size:15px;font-weight:800;background:linear-gradient(135deg,#4338ca,#312e81)}
.tgt-form-body{padding:24px}
</style>

<div class="tgt-hero">
  <h2>🎯 Monthly Targets</h2>
  <p>All months history preserved — foldable view</p>
</div>

<!-- ADD TARGET FORM -->
<div class="tgt-form-card">
  <div class="tgt-form-header">➕ Set / Update Target</div>
  <div class="tgt-form-body">
  <form method="post">
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Product</label>
        <select name="product" class="form-control" required>
          {% for p in prods %}<option value="{{p.name}}">{{p.name}}</option>{% endfor %}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Month</label>
        <select name="month" class="form-control" required>
          {% for m in range(1,13) %}
          <option value="{{m}}" {{'selected' if m==now.month else ''}}>{{ calendar.month_name[m] }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Year</label>
        <input name="year" class="form-control" type="number" value="{{now.year}}" required>
      </div>
      <div class="form-group">
        <label class="form-label">Target Qty</label>
        <input name="qty" class="form-control" type="number" step="any" placeholder="Qty" required>
      </div>
    </div>
    <button class="btn btn-primary" type="submit">💾 Save Target</button>
  </form>
  </div>
</div>

<!-- AUTO TARGET INFO -->
<div class="alert alert-success mb-3" style="border:1.5px solid #0d9488;border-left:4px solid #0d9488;border-radius:9px;background:#ccfbf1;color:#0f766e;">
  ✅ Next month (<strong>{{next_month_name}}</strong>) target auto-creates from previous month's target (or first-month sales) with <strong>{{growth}}%</strong> growth
</div>

<!-- CURRENT MONTH — always open -->
<div class="target-month" style="border-color:#0d9488">
  <div class="target-month-hdr" onclick="toggleFold(this)" style="background:linear-gradient(135deg,#0d9488,#0f766e)">
    <span>📅 {{current_month}} — Current Month</span>
    <span id="badge_cur" class="fold-arrow" style="background:rgba(255,255,255,.2);padding:3px 10px;border-radius:20px;font-size:12px">▼</span>
  </div>
  <div class="target-month-body open">
    <table class="target-tbl">
      <thead><tr><th>Product</th><th>Target</th><th>Achieved</th><th>Progress</th><th>%</th></tr></thead>
      <tbody>
        {% for row in data %}
        <tr>
          <td class="fw-bold">{{row.product}}</td>
          <td>{{'{:.1f}'.format(row.target)}}</td>
          <td style="color:var(--btn-primary);font-weight:700">{{'{:.1f}'.format(row.achieved)}}</td>
          <td style="width:140px">
            <div class="pbar"><div class="pbar-fill" style="width:{{[row.percent,100]|min}}%;background:{{'#16a34a' if row.percent>=100 else '#f59e0b' if row.percent>=70 else '#dc2626'}}"></div></div>
          </td>
          <td style="font-weight:700;color:{{'#16a34a' if row.percent>=100 else '#f59e0b' if row.percent>=70 else '#dc2626'}}">{{row.percent}}%</td>
        </tr>
        {% endfor %}
        {% if not data %}<tr><td colspan="5" class="text-center text-muted">No targets set for this month</td></tr>{% endif %}
      </tbody>
    </table>
  </div>
</div>

<!-- HISTORY — all other months foldable -->
{% for month_key in sorted_history %}
{% if month_key != current_month %}
<div class="target-month">
  <div class="target-month-hdr" style="cursor:default">
    <span onclick="toggleFold(this.closest('.target-month-hdr'))" style="cursor:pointer">📁 {{month_key}}</span>
    <span style="display:flex;gap:8px;align-items:center">
      <a href="{{ url_for('print_target_month', month=month_key) }}" target="_blank"
         onclick="event.stopPropagation()"
         style="background:rgba(255,255,255,.2);padding:3px 10px;border-radius:20px;font-size:12px;color:white;text-decoration:none">🖨️ Print</a>
      <form method="post" style="display:inline" onsubmit="return confirm('Poore {{month_key}} ka target delete karna hai?')" onclick="event.stopPropagation()">
        <input type="hidden" name="action" value="delete">
        <input type="hidden" name="month_del" value="{{month_key}}">
        <button type="submit" style="background:rgba(255,255,255,.2);border:none;padding:3px 10px;border-radius:20px;font-size:12px;color:white;cursor:pointer">🗑️ Delete Month</button>
      </form>
      <span class="fold-arrow" onclick="toggleFold(this.closest('.target-month-hdr'))" style="background:rgba(255,255,255,.2);padding:3px 10px;border-radius:20px;font-size:12px;cursor:pointer">▶</span>
    </span>
  </div>
  <div class="target-month-body">
    <table class="target-tbl">
      <thead><tr><th>Product</th><th>Target</th><th>Achieved</th><th>Progress</th><th>%</th></tr></thead>
      <tbody>
        {% for t in history_months[month_key] %}
        {% set ach = month_achieved.get(month_key, {}).get(t.product, 0) %}
        {% set pct = ((ach / t.qty * 100) | round(1)) if t.qty > 0 else 0 %}
        <tr>
          <td class="fw-bold">{{t.product}}</td>
          <td>{{'{:.1f}'.format(t.qty)}}</td>
          <td style="color:var(--btn-primary);font-weight:700">{{'{:.1f}'.format(ach)}}</td>
          <td style="width:140px">
            <div class="pbar"><div class="pbar-fill" style="width:{{[pct,100]|min}}%;background:{{'#16a34a' if pct>=100 else '#f59e0b' if pct>=70 else '#dc2626'}}"></div></div>
          </td>
          <td style="font-weight:700;color:{{'#16a34a' if pct>=100 else '#f59e0b' if pct>=70 else '#dc2626'}}">{{pct}}%</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}
{% endfor %}

<script>
function toggleFold(hdr){
  const body = hdr.nextElementSibling;
  const arrow = hdr.querySelector('.fold-arrow');
  const open = body.classList.toggle('open');
  arrow.textContent = open ? '▼' : '▶';
}
</script>
""" + TPL_F

    # Pre-calculate achieved for all months
    month_achieved = {m: get_month_achieved(m) for m in sorted_history}

    return render_template_string(
        html,
        prods=prods,
        data=data,
        now=today,
        current_month=current_month,
        next_month_name=next_month_name,
        calendar=calendar,
        growth=growth,
        sorted_history=sorted_history,
        history_months=history_months,
        month_achieved=month_achieved,
        project=get_setting("project_name")
    )



# 4. Profit & Loss Report — with monthly foldable history
@app.route("/profit_loss")
@login_required
def profit_loss():
    def parse_inv_date(date_str):
        date_str = (date_str or "").strip()
        if not date_str: return None
        for fmt in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
            try: return datetime.datetime.strptime(date_str, fmt)
            except: pass
        return None

    with db_transaction() as _c:
        _inv_rows = _c.execute("""
            SELECT inv_no, date, total, discount FROM invoices
        """).fetchall()
        _line_rows = _c.execute("""
            SELECT inv_no, product, qty, unit_price FROM invoice_items
        """).fetchall()
        _exp_rows = _c.execute("SELECT date, amount FROM expenses").fetchall()
        _other_exp_rows = _c.execute("SELECT date, amount FROM other_expenses").fetchall()

    invoices = [
        {"inv_no": r[0], "date": r[1], "total": r[2], "discount": r[3]}
        for r in _inv_rows
    ]
    lines_all = [
        {"inv_no": r[0], "product": r[1], "qty": r[2], "unit_price": r[3]}
        for r in _line_rows
    ]
    expenses_all = [{"date": r[0], "amount": r[1]} for r in _exp_rows]
    other_exp_all = [{"date": r[0], "amount": r[1]} for r in _other_exp_rows]
    products     = load_products()
    # Build inv_no → month map
    inv_month_map = {}
    for inv in invoices:
        dt = parse_inv_date(inv.get("date",""))
        if dt:
            inv_month_map[inv.get("inv_no","")] = dt.strftime("%B %Y")

    all_months_set = set(inv_month_map.values())

    def calc_month_pl(month_key):
        sales = 0.0
        discounts = 0.0
        prod_sales = {}

        for inv in invoices:
            if inv_month_map.get(inv.get("inv_no","")) != month_key: continue
            try: 
                sales += float(inv.get("total","0") or 0)
                discounts += float(inv.get("discount","0") or 0)
            except: pass

            for li in lines_all:
                if li.get("inv_no") == inv.get("inv_no"):
                    pn = to_caps(li.get("product",""))
                    try:
                        q = float(li.get("qty",0) or 0)
                        u = float(li.get("unit_price",0) or 0)
                        if pn not in prod_sales:
                            prod_sales[pn] = {"qty": 0.0, "revenue": 0.0}
                        prod_sales[pn]["qty"] += q
                        prod_sales[pn]["revenue"] += q * u
                    except: pass

        # Expenses
        expenses = 0.0
        for e in expenses_all + other_exp_all:
            dt = parse_inv_date(e.get("date",""))
            if dt and dt.strftime("%B %Y") == month_key:
                try: expenses += float(e.get("amount","0") or 0)
                except: pass

        # Product wise gross profit
        prod_rows = []
        total_gross = 0.0
        prod_map = {p["name"]: p for p in products}
        for pn, d in prod_sales.items():
            p = prod_map.get(pn, {})
            cp = float(p.get("purchase_price", 0) or 0)
            gross = d["revenue"] - (cp * d["qty"])
            total_gross += gross
            prod_rows.append({
                "product": pn, 
                "qty": d["qty"], 
                "revenue": d["revenue"],
                "cost": cp * d["qty"], 
                "gross": gross
            })

        prod_rows.sort(key=lambda x: x["revenue"], reverse=True)
        net = sales - expenses

        return {
            "sales": sales, 
            "expenses": expenses, 
            "net": net,
            "discounts": discounts, 
            "gross": total_gross, 
            "prod_rows": prod_rows
        }

    today = datetime.date.today()
    current_month = today.strftime("%B %Y")

    def month_sort_key(m):
        try: return datetime.datetime.strptime(m, "%B %Y")
        except: return datetime.datetime.min

    sorted_months = sorted(all_months_set, key=month_sort_key, reverse=True)
    if current_month not in sorted_months:
        sorted_months.insert(0, current_month)

    cur_pl = calc_month_pl(current_month)
    month_pl = {m: calc_month_pl(m) for m in sorted_months}

    # ==================== HR RECORDS (Foldable) — ab SQLite se ====================
    with db_transaction() as _c:
        _hr_rows = _c.execute("SELECT salesman, date, type, amount, note FROM salesman_hr").fetchall()
    hr_rows = [
        {"salesman": r[0], "date": r[1], "type": r[2], "amount": r[3], "note": r[4]}
        for r in _hr_rows
    ]
    from collections import defaultdict
    hr_monthly = defaultdict(list)
    hr_month_total = defaultdict(float)

    for h in hr_rows:
        try:
            dt = datetime.datetime.strptime(h.get("date",""), "%d-%m-%Y")
            month_key = dt.strftime("%B %Y")
            hr_monthly[month_key].append(h)
            if h.get("amount"):
                hr_month_total[month_key] += float(h.get("amount", 0))
        except:
            continue

    hr_sorted_months = sorted(hr_monthly.keys(), key=month_sort_key, reverse=True)

    # ==================== HTML TEMPLATE ====================
    html = TPL_H + """
<style>
.pl-month, .hr-month {border:1px solid var(--border);border-radius:var(--card-radius);margin-bottom:20px;overflow:hidden;box-shadow:var(--card-shadow)}
.pl-hdr, .hr-hdr {padding:15px 20px;cursor:pointer;font-weight:700;display:flex;justify-content:space-between;align-items:center;color:white}
.pl-hdr.green {background:linear-gradient(135deg,#0d9488,#0f766e)}
.pl-hdr.red {background:linear-gradient(135deg,#e11d48,#be123c)}
.hr-hdr {background:linear-gradient(135deg,#4338ca,#312e81)}
.pl-hdr:hover, .hr-hdr:hover {opacity:0.92}
.pl-body, .hr-body {display:none;padding:20px;background:var(--card-bg)}
.pl-body.open, .hr-body.open {display:block}
.pl-card{border-radius:12px;padding:16px 18px}
</style>

<div class="page-header">
  <div><h2>📈 Profit & Loss + HR Summary</h2></div>
  <button class="btn btn-secondary" onclick="window.print()">🖨 Print</button>
</div>

<!-- ==================== P&L SECTION ==================== -->
<h3 style="margin:25px 0 15px 5px;">💰 Profit & Loss Reports</h3>
{% for month_key in sorted_months %}
{% set pl = month_pl[month_key] %}
{% set is_cur = (month_key == current_month) %}
<div class="pl-month">
  <div class="pl-hdr {{'pl-hdr green' if pl.net>=0 else 'pl-hdr red'}}" onclick="toggleFold(this)">
    <span>{{ '📅' if is_cur else '📁' }} {{ month_key }} {{ '— Current' if is_cur else '' }}</span>
    <span>Net: <strong>Rs {{'{:,.0f}'.format(pl.net|abs)}}</strong> {{ '▲' if pl.net>=0 else '▼' }}</span>
  </div>
  <div class="pl-body {{'open' if is_cur else ''}}">
    <div class="pl-stat" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">
      <div class="pl-card" style="background:#e0e7ff"><div class="lbl">Total Sales</div><div class="val">Rs {{'{:,.0f}'.format(pl.sales)}}</div></div>
      <div class="pl-card" style="background:#fef3c7"><div class="lbl">Gross Profit</div><div class="val">Rs {{'{:,.0f}'.format(pl.gross)}}</div></div>
      <div class="pl-card" style="background:#ffe4e6"><div class="lbl">Expenses</div><div class="val text-danger">Rs {{'{:,.0f}'.format(pl.expenses)}}</div></div>
      <div class="pl-card" style="background:{{'#ccfbf1' if pl.net>=0 else '#ffe4e6'}}">
        <div class="lbl">{{ 'Net Profit' if pl.net>=0 else 'Net Loss' }}</div>
        <div class="val" style="color:{{'#0f766e' if pl.net>=0 else '#be123c'}}">Rs {{'{:,.0f}'.format(pl.net|abs)}}</div>
      </div>
    </div>

    {% if pl.prod_rows %}
    <h4 style="margin:20px 0 10px">Product Wise Performance</h4>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Product</th><th>Qty</th><th>Revenue</th><th>Cost</th><th>Gross Profit</th></tr></thead>
        <tbody>
          {% for r in pl.prod_rows %}
          <tr>
            <td class="fw-bold">{{r.product}}</td>
            <td>{{'{:.1f}'.format(r.qty)}}</td>
            <td>Rs {{'{:,.0f}'.format(r.revenue)}}</td>
            <td>Rs {{'{:,.0f}'.format(r.cost)}}</td>
            <td style="color:{{'#16a34a' if r.gross >=0 else '#dc2626'}};font-weight:bold">Rs {{'{:,.0f}'.format(r.gross)}}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endif %}
  </div>
</div>
{% endfor %}

<!-- ==================== HR SECTION ==================== -->
<h3 style="margin:40px 0 15px 5px;">👥 Salesmen HR Records</h3>
{% for month_key in hr_sorted_months %}
<div class="hr-month">
  <div class="hr-hdr" style="background:#1e40af;color:white" onclick="toggleFold(this)">
    <span>📋 {{ month_key }}</span>
    <span>Total Amount: Rs {{'{:,.0f}'.format(hr_month_total[month_key])}}</span>
  </div>
  <div class="hr-body">
    <table style="width:100%">
      <thead style="background:#f1f5f9">
        <tr><th>Date</th><th>Salesman</th><th>Type</th><th>Amount</th><th>Note</th></tr>
      </thead>
      <tbody>
        {% for h in hr_monthly[month_key] %}
        <tr>
          <td>{{ h.date }}</td>
          <td class="fw-bold">{{ h.salesman }}</td>
          <td>
            {% if h.type == 'attendance' %}✅ Present
            {% elif h.type == 'advance' %}💵 Advance
            {% elif h.type == 'leave' %}🏠 Leave
            {% else %}🏢 Company Leave{% endif %}
          </td>
          <td>{% if h.amount and h.amount != '0' %}Rs {{ h.amount }}{% else %}—{% endif %}</td>
          <td>{{ h.note or '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endfor %}

<script>
function toggleFold(el) {
  const body = el.nextElementSibling;
  body.style.display = (body.style.display === 'none' || body.style.display === '') ? 'block' : 'none';
}
</script>
""" + TPL_F

    # Auto save current month P&L
    try:
        hist = read_csv(PROFIT_HISTORY_CSV)
        month_name = current_month.split()[0]
        exists = any(r.get("month") == month_name and r.get("year") == str(today.year) for r in hist)
        if not exists:
            hist.append({
                "month": month_name,
                "year": str(today.year),
                "total_sales": f"{cur_pl['sales']:.2f}",
                "total_expenses": f"{cur_pl['expenses']:.2f}",
                "gross_profit": f"{cur_pl['gross']:.2f}",
                "net_profit": f"{cur_pl['net']:.2f}",
                "saved_on": today.isoformat()
            })
            write_csv(PROFIT_HISTORY_CSV, hist, ["month","year","total_sales","total_expenses","gross_profit","net_profit","saved_on"])
    except Exception as e:
        print("P&L save error:", e)

    return render_template_string(html,
        sorted_months=sorted_months,
        month_pl=month_pl,
        current_month=current_month,
        hr_monthly=hr_monthly,
        hr_sorted_months=hr_sorted_months,
        hr_month_total=hr_month_total,
        project=get_setting("project_name")
    )
# 5. splash 
def show_splash(company_name: str):
    import tkinter as tk
    from PIL import Image, ImageTk

    root = tk.Tk()
    root.overrideredirect(True)
    root.configure(bg="black")

    w, h = 640, 360
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # 🔒 HOLD references (MOST IMPORTANT)
    root.img_ref = None

    # ---------- LOGO ----------
    try:
        img = Image.open("logo.jpg")
        img = img.resize((180, 180))
        root.img_ref = ImageTk.PhotoImage(img)
        canvas.create_image(w//2, 110, image=root.img_ref)
    except Exception as e:
        print("Logo error:", e)

    # ---------- FORCE TEXT (TEST SAFE) ----------
    text = company_name.strip() if company_name.strip() else"SEIZE"

    canvas.create_text(
        w//2, 240,
        text=text,
        fill="red",              # 🔥 simple color (no font tricks)
        font=("Arial", 36, "bold")
    )

    canvas.create_text(
        w//2, 280,
        text="Smart Invoice Pro",
        fill="white",
        font=("Arial", 14)
    )

    # 🔒 BLOCK for 3 seconds
    root.after(3000, root.destroy)
    root.mainloop()

# 5. Expenses Sheet - مکمل درست اور چلنے والا
@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    today = datetime.date.today()
    today_str = today.isoformat()
    current_year = today.year

    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            exp_id = request.form.get("exp_id")
            if exp_id:
                try:
                    with db_transaction() as _c:
                        _c.execute("DELETE FROM expenses WHERE id = ?", (exp_id,))
                    flash("Expense deleted successfully")
                except Exception as e:
                    flash(f"❌ Delete failed: {e}")

        elif action == "add":   # Add new expense
            try:
                amount = float(request.form.get("amount", 0))
                desc = request.form.get("desc", "").strip()
                date_val = request.form.get("date", today_str)

                if amount > 0 and desc:
                    with db_transaction() as _c:
                        _c.execute("""
                            INSERT INTO expenses (date, amount, description)
                            VALUES (?, ?, ?)
                        """, (date_val, amount, desc))
                    flash(f"✅ Added: Rs {amount:,.2f} - {desc}")
                else:
                    flash("Please enter valid amount and description")
            except ValueError:
                flash("Invalid amount entered")
            except Exception as e:
                flash(f"❌ Error saving expense: {e}")

        return redirect(url_for("expenses"))

    # ===================== GET: SQLite سے ڈیٹا لوڈ =====================
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, date, amount, description 
        FROM expenses 
        ORDER BY date DESC, id DESC
    """)
    all_exps = cur.fetchall()
    conn.close()

    # Monthly Grouping
    from collections import defaultdict
    monthly = defaultdict(list)
    monthly_totals = defaultdict(float)
    yearly_total = 0.0

    for row in all_exps:
        try:
            exp_id = row[0]
            exp_date = row[1]
            amount = float(row[2])
            desc = row[3] or "—"

            dt = datetime.datetime.strptime(exp_date, "%Y-%m-%d")
            month_key = dt.strftime("%B %Y")

            monthly[month_key].append({
                "id": exp_id,
                "date": exp_date,
                "amount": amount,
                "desc": desc
            })
            monthly_totals[month_key] += amount
            yearly_total += amount
        except:
            continue

    sorted_months = sorted(
        monthly.keys(), 
        key=lambda x: datetime.datetime.strptime(x, "%B %Y"), 
        reverse=True
    )

    html = TPL_H + """
<style>
.exp-hero{background:linear-gradient(135deg,#0d3b34,#0f5c52);border-radius:var(--card-radius);padding:22px 26px;margin-bottom:22px}
.exp-hero h2{color:white;margin:0;font-size:20px;font-weight:800;border:none;padding:0}
.exp-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);overflow:hidden;margin-bottom:22px}
.exp-card-header{padding:16px 26px;color:white;font-size:16px;font-weight:800;background:linear-gradient(135deg,#4338ca,#312e81)}
.exp-card-body{padding:26px}
.exp-card-body label{font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:5px}
.exp-card-body input{width:100%;padding:10px 12px;border:1.5px solid var(--input-border);border-radius:9px;font-size:14px;background:var(--input-bg);color:var(--text);box-sizing:border-box}
.exp-card-body input:focus{outline:none;border-color:var(--btn-primary);box-shadow:0 0 0 3px rgba(79,70,229,.12)}
.exp-yearly{background:linear-gradient(135deg,#f5a524,#d97706);border-radius:var(--card-radius);padding:26px;text-align:center;margin-bottom:22px;color:white;box-shadow:var(--card-shadow)}
.exp-yearly h3{color:white;border:none;padding:0;margin-bottom:6px;font-size:14px;text-transform:uppercase;letter-spacing:.5px;opacity:.9}
.exp-yearly .amt{font-size:40px;font-weight:900}
</style>

<div class="exp-hero"><h2>💸 Expense Manager</h2></div>

{% with messages = get_flashed_messages() %}
  {% if messages %}
    {% for msg in messages %}<div class="notice">{{ msg }}</div>{% endfor %}
  {% endif %}
{% endwith %}

<!-- Add Expense Form -->
<div class="exp-card">
  <div class="exp-card-header">➕ Add New Expense</div>
  <div class="exp-card-body">
  <form method="post">
    <input type="hidden" name="action" value="add">
    <div style="display:grid;grid-template-columns:180px 180px 1fr 180px;gap:16px;align-items:end;">
      <div>
        <label>Date</label>
        <input name="date" type="date" value="{{ today_str }}" required>
      </div>
      <div>
        <label>Amount (Rs)</label>
        <input name="amount" type="number" step="0.01" placeholder="0.00" required>
      </div>
      <div>
        <label>Description</label>
        <input name="desc" placeholder="Electricity bill, Rent, Fuel etc." required>
      </div>
      <div>
        <button type="submit" class="btn btn-primary btn-lg" style="width:100%">💾 Save Expense</button>
      </div>
    </div>
  </form>
  </div>
</div>

<!-- Yearly Total -->
<div class="exp-yearly">
  <h3>📅 Yearly Total Expenses ({{ current_year }})</h3>
  <div class="amt">Rs {{ "%.2f"|format(yearly_total) }}</div>
</div>

<!-- Monthly Sections -->
{% if sorted_months %}
  {% for month in sorted_months %}
  <div class="card" style="margin-bottom:20px;border-radius:12px;overflow:hidden;">
    <div style="background:#d32f2f;color:white;padding:18px;cursor:pointer;font-size:18px;font-weight:bold;"
         onclick="this.nextElementSibling.style.display = (this.nextElementSibling.style.display === 'none') ? 'block' : 'none';">
      📆 {{ month }}
      <span style="float:right;">
        Total: <strong>Rs {{ "%.2f"|format(monthly_totals[month]) }}</strong>
        <i style="margin-left:12px;">▼</i>
      </span>
    </div>
    <div class="month-body" style="display:block;padding:10px 0;">
      <table style="width:100%;border-collapse:collapse;">
        <thead style="background:#ffebee;">
          <tr>
            <th style="padding:12px;text-align:left;">Date</th>
            <th style="padding:12px;text-align:right;">Amount</th>
            <th style="padding:12px;text-align:left;">Description</th>
            <th style="padding:12px;text-align:center;width:100px;">Action</th>
          </tr>
        </thead>
        <tbody>
          {% for e in monthly[month] %}
          <tr style="border-bottom:1px solid #eee;">
            <td style="padding:12px;">{{ e.date }}</td>
            <td style="padding:12px;text-align:right;font-weight:bold;color:#d32f2f;">
              Rs {{ "%.2f"|format(e.amount) }}
            </td>
            <td style="padding:12px;">{{ e.desc }}</td>
            <td style="padding:12px;text-align:center;">
              <form method="post" style="display:inline;" onsubmit="return confirm('Delete this expense permanently?')">
                <input type="hidden" name="action" value="delete">
                <input type="hidden" name="exp_id" value="{{ e.id }}">
                <button class="btn btn-danger btn-sm">🗑 Delete</button>
              </form>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% endfor %}
{% else %}
  <div class="card text-center" style="padding:60px;color:#666;">
    <h3>No expenses recorded yet</h3>
    <p>Use the form above to start adding expenses.</p>
  </div>
{% endif %}

<script>
  // پہلا مہینہ ہمیشہ کھلا رکھیں
  document.querySelectorAll('.month-body')[0].style.display = 'block';
</script>
""" + TPL_F

    return render_template_string(
        html,
        today_str=today_str,
        current_year=current_year,
        yearly_total=yearly_total,
        sorted_months=sorted_months,
        monthly=monthly,
        monthly_totals=monthly_totals,
        project=get_setting("project_name")
    )


# ================== Other Expenses (نیا صفحہ – Name, Amount, Description) ==================
@app.route("/other_expenses", methods=["GET", "POST"])
@login_required
def other_expenses():
    today = datetime.date.today()
    today_str = today.isoformat()
    current_year = today.year

    if request.method == "POST":
        action = request.form.get("action")
        conn = db()
        cur = conn.cursor()

        if action == "delete":
            exp_id = request.form.get("exp_id")
            if exp_id:
                cur.execute("DELETE FROM other_expenses WHERE id = ?", (exp_id,))
                conn.commit()
                flash("Entry deleted successfully")

        elif action == "add":
            try:
                name = request.form.get("name", "").strip()
                amount_str = request.form.get("amount", "").strip()
                desc = request.form.get("desc", "").strip()
                date_val = request.form.get("date", today_str)

                if not name or not amount_str:
                    flash("Name and Amount are required")
                    conn.close()
                    return redirect(url_for("other_expenses"))

                amount = float(amount_str)
                if amount <= 0:
                    flash("Amount must be greater than zero")
                    conn.close()
                    return redirect(url_for("other_expenses"))

                cur.execute("""
                    INSERT INTO other_expenses (date, name, amount, description)
                    VALUES (?, ?, ?, ?)
                """, (date_val, name, amount, desc))
                conn.commit()
                flash(f"✅ Added: {name} – Rs {amount:,.2f}")
            except ValueError:
                flash("Invalid amount entered")
            except Exception as e:
                flash("Error saving entry")

        conn.close()
        return redirect(url_for("other_expenses"))

    # ===================== GET: SQLite سے ڈیٹا =====================
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, date, name, amount, description 
        FROM other_expenses 
        ORDER BY date DESC, id DESC
    """)
    all_entries = cur.fetchall()
    conn.close()

    # Monthly Grouping + Yearly Total
    from collections import defaultdict
    monthly = defaultdict(list)
    monthly_totals = defaultdict(float)
    yearly_total = 0.0

    for row in all_entries:
        try:
            exp_id = row[0]
            exp_date = row[1]
            name = row[2] or "—"
            amount = float(row[3] or 0)
            desc = row[4] or "—"

            dt = datetime.datetime.strptime(exp_date, "%Y-%m-%d")
            month_key = dt.strftime("%B %Y")

            monthly[month_key].append({
                "id": exp_id,
                "date": exp_date,
                "name": name,
                "amount": amount,
                "desc": desc
            })
            monthly_totals[month_key] += amount
            yearly_total += amount
        except:
            continue

    sorted_months = sorted(
        monthly.keys(),
        key=lambda x: datetime.datetime.strptime(x, "%B %Y"),
        reverse=True
    )

    html = TPL_H + """
<h2>📑 Other Expenses / Miscellaneous Entries</h2>

{% with messages = get_flashed_messages() %}
  {% if messages %}
    {% for msg in messages %}<div class="notice">{{ msg }}</div>{% endfor %}
  {% endif %}
{% endwith %}

<!-- Add Form -->
<div class="card mb-3">
  <h3>➕ Add New Miscellaneous Expense</h3>
  <form method="post" style="background:#fff8e1;padding:25px;border-radius:12px;">
    <input type="hidden" name="action" value="add">
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Date</label>
        <input name="date" type="date" value="{{ today_str }}" class="form-control" required>
      </div>
      <div class="form-group">
        <label class="form-label">Name / Item *</label>
        <input name="name" placeholder="e.g. Transport, Marketing" class="form-control" required>
      </div>
      <div class="form-group">
        <label class="form-label">Description</label>
        <input name="desc" placeholder="Optional details" class="form-control">
      </div>
      <div class="form-group" style="align-self:end;">
        <label class="form-label">Amount (Rs) *</label>
        <input name="amount" type="number" step="0.01" class="form-control" required>
        <button type="submit" class="btn btn-primary" style="margin-top:10px;width:100%;">
          💾 Save Entry
        </button>
      </div>
    </div>
  </form>
</div>

<!-- Yearly Total -->
<div class="card mb-3" style="text-align:center;background:#fff0e0;border-left:8px solid #ff6d00;">
  <h3>📅 Yearly Total ({{ current_year }})</h3>
  <p style="font-size:42px;font-weight:bold;color:#d84315;">
    Rs {{ "%.2f"|format(yearly_total) }}
  </p>
</div>

<!-- Monthly Sections -->
{% if sorted_months %}
  {% for month in sorted_months %}
  <div class="card" style="margin-bottom:22px;border-radius:14px;overflow:hidden;">
    <div style="background:#ff6d00;color:white;padding:18px;cursor:pointer;font-size:19px;font-weight:bold;"
         onclick="this.nextElementSibling.style.display = (this.nextElementSibling.style.display === 'none') ? 'block' : 'none';">
      📆 {{ month }}
      <span style="float:right;">Total: <strong>Rs {{ "%.2f"|format(monthly_totals[month]) }}</strong> ▼</span>
    </div>
    <div class="month-body" style="display:block;">
      <table style="width:100%;border-collapse:collapse;">
        <thead style="background:#fff3e0;">
          <tr>
            <th style="padding:14px;text-align:left;">Date</th>
            <th style="padding:14px;text-align:left;">Name / Item</th>
            <th style="padding:14px;text-align:left;">Description</th>
            <th style="padding:14px;text-align:right;">Amount</th>
            <th style="padding:14px;text-align:center;">Action</th>
          </tr>
        </thead>
        <tbody>
          {% for e in monthly[month] %}
          <tr>
            <td>{{ e.date }}</td>
            <td><strong>{{ e.name }}</strong></td>
            <td>{{ e.desc }}</td>
            <td style="text-align:right;font-weight:bold;color:#d84315;">
              Rs {{ "%.2f"|format(e.amount) }}
            </td>
            <td style="text-align:center;">
              <form method="post" style="display:inline;" onsubmit="return confirm('Delete this entry?')">
                <input type="hidden" name="action" value="delete">
                <input type="hidden" name="exp_id" value="{{ e.id }}">
                <button class="btn btn-danger btn-sm">🗑 Delete</button>
              </form>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% endfor %}
{% else %}
  <div class="card text-center" style="padding:80px;color:#777;">
    <h3>No miscellaneous expenses yet</h3>
  </div>
{% endif %}

<script>
  document.querySelectorAll('.month-body')[0].style.display = 'block';
</script>
""" + TPL_F

    return render_template_string(
        html,
        today_str=today_str,
        current_year=current_year,
        yearly_total=yearly_total,          # ← یہ لائن اہم تھی
        sorted_months=sorted_months,
        monthly=monthly,
        monthly_totals=monthly_totals,
        project=get_setting("project_name")
    )
# ================== BACKUP & RESTORE ==================
# ================== BACKUP & RESTORE (with Delete Button) ==================
@app.route("/backup", methods=["GET", "POST"])
def backup_restore():
    import zipfile, shutil, tempfile

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    message = ""

    if request.method == "POST":
        action = request.form.get("action")

        # ============ CREATE FULL BACKUP ============
        if action == "create_backup":
            try:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                backup_filename = f"SmartInvoice_Backup_{timestamp}.zip"
                backup_path = backup_dir / backup_filename

                with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # تمام CSV فائلیں
                    for csv_file in DATA.glob("*.csv"):
                        if csv_file.is_file():
                            zipf.write(csv_file, arcname=f"db_files/{csv_file.name}")

                    # SQLite ڈیٹا بیس (db/ فولڈر میں — ریسٹور کے ساتھ ہمیشہ میچ کرے گا)
                    if DB_FILE.exists() and DB_FILE.is_file():
                        zipf.write(DB_FILE, arcname=f"db/{DB_FILE.name}")

                    # پوری uploads/ فولڈر (لوگو سمیت تمام اپلوڈڈ فائلیں)
                    if UPLOADS.exists():
                        for up_file in UPLOADS.rglob("*"):
                            if up_file.is_file():
                                rel = up_file.relative_to(UPLOADS)
                                zipf.write(up_file, arcname=f"media/{rel.as_posix()}")

                if not backup_path.exists() or backup_path.stat().st_size == 0:
                    raise Exception("Backup file empty ya create nahi hui")

                flash(f"✅ Backup created: {backup_filename}")
                return send_from_directory(str(backup_dir), backup_filename, as_attachment=True)

            except Exception as e:
                flash(f"Error creating backup: {str(e)}")
                return redirect(url_for("backup_restore"))

        # ============ RESTORE FROM BACKUP ============
        elif action == "restore" and 'restore_file' in request.files:
            file = request.files['restore_file']
            if file.filename == '' or not file.filename.lower().endswith('.zip'):
                flash("Please select a valid .zip backup file")
                return redirect(url_for("backup_restore"))

            temp_path = backup_dir / f"temp_restore_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
            file.save(temp_path)
            stage_dir = None

            try:
                # Step 1: zip valid hai?
                with zipfile.ZipFile(temp_path, 'r') as zipf:
                    bad = zipf.testzip()
                    if bad:
                        raise Exception(f"Corrupt zip file: {bad}")

                # Step 2: staging folder mein pehle extract karo (asal data touch nahi hota abhi)
                stage_dir = Path(tempfile.mkdtemp(prefix="restore_stage_", dir=str(backup_dir)))
                with zipfile.ZipFile(temp_path, 'r') as zipf:
                    zipf.extractall(stage_dir)

                staged_csvs = list((stage_dir / "db_files").glob("*.csv")) if (stage_dir / "db_files").exists() else []
                staged_db = stage_dir / "db" / DB_FILE.name
                staged_uploads = stage_dir / "media"

                if not staged_csvs and not staged_db.exists():
                    raise Exception("Backup zip mein koi valid data (CSV/DB) nahi mila — restore rok diya gaya")

                # Step 3: Safety — restore se PEHLE current data ka auto-backup lo
                safety_backup = backup_dir / f"pre_restore_safety_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
                with zipfile.ZipFile(safety_backup, 'w', zipfile.ZIP_DEFLATED) as sbz:
                    for csv_file in DATA.glob("*.csv"):
                        sbz.write(csv_file, arcname=f"db_files/{csv_file.name}")
                    if DB_FILE.exists():
                        sbz.write(DB_FILE, arcname=f"db/{DB_FILE.name}")
                    if UPLOADS.exists():
                        for up_file in UPLOADS.rglob("*"):
                            if up_file.is_file():
                                sbz.write(up_file, arcname=f"media/{up_file.relative_to(UPLOADS).as_posix()}")

                # Step 4: Ab staged data ko real jagah move karo
                if staged_csvs:
                    DATA.mkdir(parents=True, exist_ok=True)
                    for csv_file in DATA.glob("*.csv"):
                        try: csv_file.unlink()
                        except: pass
                    for sc in staged_csvs:
                        shutil.copy2(str(sc), str(DATA / sc.name))

                if staged_db.exists():
                    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
                    tmp_db = DB_FILE.parent / (DB_FILE.name + ".restoring")
                    shutil.copy2(str(staged_db), str(tmp_db))
                    os.replace(str(tmp_db), str(DB_FILE))   # atomic swap — crash-safe

                if staged_uploads.exists():
                    UPLOADS.mkdir(parents=True, exist_ok=True)
                    for up_file in staged_uploads.rglob("*"):
                        if up_file.is_file():
                            rel = up_file.relative_to(staged_uploads)
                            target = UPLOADS / rel
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(up_file), str(target))
                            if "logo" in up_file.name.lower():
                                set_setting("logo_path", str(target))

                init_db()
                flash("✅ Backup restored successfully! Refreshing in 3 seconds...")
                message = "<script>setTimeout(() => location.reload(), 3000);</script>"

            except Exception as e:
                flash(f"Restore failed: {str(e)} — your original data is safe, nothing was deleted")

            finally:
                try: temp_path.unlink()
                except: pass
                if stage_dir and stage_dir.exists():
                    try: shutil.rmtree(stage_dir)
                    except: pass

            return redirect(url_for("backup_restore"))

        # ============ DELETE BACKUP ============
        elif action == "delete_backup":
            filename = request.form.get("filename")
            if filename:
                backup_file = backup_dir / filename
                if backup_file.exists() and backup_file.name.startswith("SmartInvoice_Backup_"):
                    try:
                        backup_file.unlink()
                        flash(f"Backup deleted: {filename}")
                    except Exception as e:
                        flash(f"Error deleting backup: {str(e)}")
                else:
                    flash("Invalid backup file")
            return redirect(url_for("backup_restore"))

    # موجودہ بیک اپس کی لسٹ (multiple backups, sab dikhte hain)
    backups = sorted(backup_dir.glob("SmartInvoice_Backup_*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)

    # 3D بٹن اسٹائل
    button_3d_style = """
        display: inline-block;
        padding: 18px 50px;
        font-size: 18px;
        font-weight: bold;
        color: white;
        border: none;
        border-radius: 12px;
        cursor: pointer;
        box-shadow: 0 8px 0 rgb(0,0,0,0.3), 0 12px 20px rgba(0,0,0,0.4);
        transition: all 0.2s ease;
        text-transform: uppercase;
        letter-spacing: 1px;
    """
    button_3d_hover = "transform: translateY(4px); box-shadow: 0 4px 0 rgb(0,0,0,0.3), 0 8px 15px rgba(0,0,0,0.3);"

    html = TPL_H + """
<h2>🔒 Backup & Restore</h2>
<p class="notice">تمام ڈیٹا (انوائسز، پروڈکٹس، کسٹمرز، سٹاک، ایکسپینسز، سیٹنگز، اپلوڈڈ فائلیں) محفوظ طریقے سے بیک اپ اور بحال کیا جا سکتا ہے۔</p>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:30px;margin:30px 0;">
  <!-- Create Backup -->
  <div class="card" style="border-left:6px solid #4caf50; text-align:center;">
    <h3 style="color:#2e7d32;">📥 Create New Backup</h3>
    <p>فوری مکمل بیک اپ بنائیں اور ڈاؤن لوڈ کریں۔</p>
    <form method="post">
      <input type="hidden" name="action" value="create_backup">
      <button type="submit" class="btn-3d" style="background:#2e7d32; {button_3d_style}"
              onmouseover="this.style.{button_3d_hover}"
              onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 8px 0 rgb(0,0,0,0.3), 0 12px 20px rgba(0,0,0,0.4)';">
        🗜️ Create Backup & Download
      </button>
    </form>
  </div>

  <!-- Restore Backup -->
  <div class="card" style="border-left:6px solid #ff9800; text-align:center;">
    <h3 style="color:#ff6d00;">📤 Restore from Backup</h3>
    <p><strong>خبردار:</strong> موجودہ تمام ڈیٹا نئے بیک اپ سے بدل جائے گا (پرانا ڈیٹا خودکار طور پر محفوظ ہو گا)۔</p>
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="action" value="restore">
      <input type="file" name="restore_file" accept=".zip" required
             style="width:100%;padding:12px;margin:15px 0;border:2px dashed #ff9800;border-radius:8px;">
      <button type="submit" class="btn-3d" style="background:#ff6d00; {button_3d_style}"
              onmouseover="this.style.{button_3d_hover}"
              onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 8px 0 rgb(0,0,0,0.3), 0 12px 20px rgba(0,0,0,0.4)';"
              onclick="return confirm('Are you sure? Current data will be overwritten!')">
        ⚠️ Restore Backup
      </button>
    </form>
  </div>
</div>

<!-- Existing Backups -->
{% if backups %}
<h3 style="margin-top:40px;">📁 Previous Backups ({{ backups|length }} files)</h3>
<table style="width:100%;border-collapse:collapse;">
  <thead style="background:#1976d2;color:white;">
    <tr>
      <th style="padding:12px;text-align:left;">Backup File</th>
      <th style="padding:12px;text-align:center;">Date & Time</th>
      <th style="padding:12px;text-align:center;">Size</th>
      <th style="padding:12px;text-align:center;">Actions</th>
    </tr>
  </thead>
  <tbody>
    {% for b in backups %}
    <tr>
      <td style="padding:12px;font-weight:600;">{{ b.name }}</td>
      <td style="padding:12px;text-align:center;">{{ b.stat().st_mtime|datetimeformat }}</td>
      <td style="padding:12px;text-align:center;">{{ (b.stat().st_size / 1024)|round(1) }} KB</td>
      <td style="padding:12px;text-align:center;">
        <a href="{{ url_for('download_backup', filename=b.name) }}" class="btn"
           style="background:#1565c0;color:white;padding:8px 16px;font-size:14px;margin-right:8px;">
          Download
        </a>
        <form method="post" style="display:inline;" onsubmit="return confirm('This backup will be permanently deleted. Are you sure?')">
          <input type="hidden" name="action" value="delete_backup">
          <input type="hidden" name="filename" value="{{ b.name }}">
          <button class="btn" style="background:#c62828;color:white;padding:8px 16px;font-size:14px;">
            Delete
          </button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<div class="card" style="text-align:center;padding:60px;color:#999;background:#f9f9f9;">
  <h3>کوئی پچھلا بیک اپ نہیں ملا</h3>
  <p>اوپر "Create Backup" بٹن سے نیا بیک اپ بنائیں۔</p>
</div>
{% endif %}
{message}
""" + TPL_F

    def datetimeformat(value):
        try:
            return datetime.datetime.fromtimestamp(value).strftime('%d-%b-%Y %I:%M %p')
        except:
            return "Unknown"
    app.jinja_env.filters['datetimeformat'] = datetimeformat

    return render_template_string(html, backups=backups, project=get_setting("project_name"), message=message)
@app.route("/backup/download/<filename>")
@login_required
def download_backup(filename):
    backup_dir = ROOT / "backups"
    return send_from_directory(str(backup_dir), filename, as_attachment=True)

@app.route("/sales_history", methods=["GET", "POST"])
@login_required
def sales_history():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # تمام پروڈکٹس کی لسٹ فلٹر کے لیے
    c.execute("SELECT name FROM products ORDER BY name")
    all_products = [row[0] for row in c.fetchall()]

    # مہینہ وار ڈیٹا (پروڈکٹ وائز ٹوٹل qty)
    c.execute("""
        SELECT 
            strftime('%Y-%m', date) AS ym,
            strftime('%B %Y', date) AS month_name,
            product,
            SUM(qty) AS total_qty
        FROM sales_log
        GROUP BY ym, product
        ORDER BY ym DESC, total_qty DESC
    """)
    raw = c.fetchall()

    monthly_data = {}
    grand_totals = {}

    for ym, month_name, prod, qty in raw:
        if month_name not in monthly_data:
            monthly_data[month_name] = []
            grand_totals[month_name] = 0.0
        monthly_data[month_name].append({"product": prod, "qty": float(qty)})
        grand_totals[month_name] += float(qty)

    # ڈیٹ رینج فلٹر
    filtered_result = None
    filtered_grand = 0.0
    if request.method == "POST":
        from_date = request.form.get("from_date")
        to_date = request.form.get("to_date")
        prod_filter = request.form.get("product_filter", "").strip()

        query = """
            SELECT product, SUM(qty) AS total_qty
            FROM sales_log
            WHERE date BETWEEN ? AND ?
        """
        params = [from_date, to_date]

        if prod_filter:
            query += " AND product = ?"
            params.append(prod_filter)

        query += " GROUP BY product ORDER BY total_qty DESC"

        c.execute(query, params)
        results = c.fetchall()
        filtered_result = [{"product": r[0], "qty": float(r[1])} for r in results]
        filtered_grand = sum(float(r[1]) for r in results)

    conn.close()

    html = TPL_H + """
<h2>📊 Product Sales History (Monthly)</h2>
<p class="small"> SQLite </p>



{% if filtered_result is not none %}
<div class="card" style="background:#e8f5e9;border-left:6px solid #4caf50;padding:20px;margin-bottom:40px;">
  <h3>Filtered Result: {{ request.form.get('from_date') }}  {{ request.form.get('to_date') }}</h3>
  <p style="font-size:20px;margin:15px 0;"><strong>Total Quantity Sold: {{ "%.2f"|format(filtered_grand) }}</strong></p>
  <table style="width:100%;border-collapse:collapse;">
    <thead style="background:#4caf50;color:white;">
      <tr><th style="padding:12px;">Product</th><th style="padding:12px;text-align:center;">Total Qty</th></tr>
    </thead>
    <tbody>
      {% for r in filtered_result %}
      <tr>
        <td style="padding:12px;font-weight:600;">{{ r.product }}</td>
        <td style="padding:12px;text-align:center;font-weight:bold;font-size:18px;color:#2e7d32;">{{ "%.2f"|format(r.qty) }}</td>
      </tr>
      {% else %}
      <tr><td colspan="2" style="text-align:center;padding:40px;color:#999;">No entry found</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

<!-- Global Search -->
<input type="text" id="globalSearch" placeholder="🔍" 
       style="width:100%;max-width:700px;padding:14px;font-size:16px;border-radius:10px;border:2px solid #1976d2;margin:20px 0;">

<!-- Monthly Breakdown -->
{% for month, items in monthly_data.items() %}
<div class="card" style="margin-bottom:30px;box-shadow:0 4px 15px rgba(0,0,0,0.08);border-radius:12px;overflow:hidden;">
  <h3 style="background:#1976d2;color:white;padding:16px;margin:0;font-size:19px;">
    {{ month }}
    <span style="float:right;font-size:17px;">Total Qty: <strong>{{ "%.2f"|format(grand_totals[month]) }}</strong></span>
  </h3>
  <div style="padding:20px;">
    <table style="width:100%;border-collapse:collapse;">
      <thead style="background:#e3f2fd;">
        <tr>
          <th style="padding:12px;text-align:left;">Product Name</th>
          <th style="padding:12px;text-align:center;width:200px;">Qty Sold</th>
        </tr>
      </thead>
      <tbody>
        {% for item in items %}
        <tr class="search-row">
          <td style="padding:12px;font-weight:600;">{{ item.product }}</td>
          <td style="padding:12px;text-align:center;font-weight:bold;font-size:17px;color:#1565c0;">
            {{ "%.2f"|format(item.qty) }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% else %}
<div class="card" style="text-align:center;padding:50px;color:#666;background:#f9f9f9;">
  <h3>ابھی تک کوئی سیل نہیں ہوئی</h3>
  <p> ۔</p>
</div>
{% endfor %}

<script>
document.getElementById('globalSearch').addEventListener('keyup', function() {
  let val = this.value.toLowerCase().trim();
  document.querySelectorAll('.search-row').forEach(row => {
    let text = row.textContent.toLowerCase();
    row.style.display = text.includes(val) ? '' : 'none';
  });
});
</script>

<p style="text-align:center;margin-top:40px;">
  <a href="{{ url_for('products') }}" class="btn" style="padding:14px 40px;font-size:18px;background:#424242;">
    ← Back to Products
  </a>
</p>
""" + TPL_F

    return render_template_string(
        html,
        all_products=all_products,
        monthly_data=monthly_data,
        grand_totals=grand_totals,
        filtered_result=filtered_result,
        filtered_grand=filtered_grand,
        project=get_setting("project_name")
    )


# (redirect loops removed — all routes already defined above)

# ============================================================
# SALESMEN MANAGEMENT
def calc_salesman_month_hr(cur, name, month_key, days_in_month, base_salary, commission_pct):
    """
    Ek salesman ke ek specific month (format: 'MM-YYYY') ka poora HR + salary
    summary calculate karta hai, in rules ke sath:
      - 3 Late (punctuality) marks = 1 Half Day
      - 3 Half Days (direct ya Late se convert hue) = 1 Poori Leave
      - Baaki bache hue Half Days (jo 3 ka set nahi banate) = 0.5x per-day salary deduct
      - Holiday = paid, koi deduction nahi
    """
    cur.execute("""
        SELECT type, COUNT(*) as cnt, COALESCE(SUM(amount),0) as total
        FROM salesman_hr
        WHERE salesman=? AND substr(date,4,7)=?
        GROUP BY type
    """, (name, month_key))
    hr_month = {row["type"]: {"cnt": row["cnt"], "total": row["total"]} for row in cur.fetchall()}

    present_cnt   = hr_month.get("attendance", {}).get("cnt", 0)
    absent_cnt    = hr_month.get("absent", {}).get("cnt", 0)
    leave_cnt     = hr_month.get("leave", {}).get("cnt", 0)
    holiday_cnt   = hr_month.get("holiday", {}).get("cnt", 0)
    half_day_cnt  = hr_month.get("half_day", {}).get("cnt", 0)
    late_cnt      = hr_month.get("late", {}).get("cnt", 0)
    advance_total = round(hr_month.get("advance", {}).get("total", 0), 2)
    bonus_total   = round(hr_month.get("bonus", {}).get("total", 0), 2)
    salary_paid_total = round(hr_month.get("salary_paid", {}).get("total", 0), 2)
    manual_commission_total = round(hr_month.get("commission", {}).get("total", 0), 2)

    # --- Conversion: 3 Late = 1 Half Day ---
    half_days_from_late = late_cnt // 3
    remaining_late = late_cnt % 3
    total_half_days = half_day_cnt + half_days_from_late

    # --- Conversion: 3 Half Days = 1 Full Leave ---
    leaves_from_half_days = total_half_days // 3
    remaining_half_days = total_half_days % 3

    total_leave_equivalent = leave_cnt + leaves_from_half_days
    deduction_days = absent_cnt + total_leave_equivalent + (remaining_half_days * 0.5)

    per_day_salary = round(base_salary / days_in_month, 2) if days_in_month else 0
    leave_deduction_amount = round(per_day_salary * deduction_days, 2)
    salary_after_leave = round(base_salary - leave_deduction_amount, 2)

    # --- Auto commission = commission_pct% of this month's sales ---
    cur.execute("""
        SELECT COALESCE(SUM(total),0) as sales_total
        FROM invoices
        WHERE salesman=? AND substr(date,4,7)=?
    """, (name, month_key))
    month_sales = cur.fetchone()["sales_total"] or 0
    auto_commission = round(month_sales * (float(commission_pct or 0) / 100.0), 2)

    net_payable = round(
        salary_after_leave + auto_commission + bonus_total + manual_commission_total
        - advance_total - salary_paid_total, 2
    )

    return {
        "month": month_key,
        "present_this_month": present_cnt,
        "absent_this_month": absent_cnt,
        "leaves_this_month": leave_cnt,
        "holidays_this_month": holiday_cnt,
        "half_days_this_month": half_day_cnt,
        "late_this_month": late_cnt,
        "remaining_late_uncounted": remaining_late,
        "half_days_from_late": half_days_from_late,
        "leaves_from_half_days": leaves_from_half_days,
        "remaining_half_days_deducted": remaining_half_days,
        "advance_this_month": advance_total,
        "bonus_this_month": bonus_total,
        "salary_paid_this_month": salary_paid_total,
        "manual_commission_this_month": manual_commission_total,
        "per_day_salary": per_day_salary,
        "deduction_days": deduction_days,
        "leave_deduction_amount": leave_deduction_amount,
        "salary_after_leave": salary_after_leave,
        "month_sales_total": round(month_sales, 2),
        "auto_commission_this_month": auto_commission,
        "net_payable_this_month": net_payable,
    }
# ============================================================

@app.route("/salesmen", methods=["GET", "POST"])
@login_required
def salesmen():

    import calendar

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    today_obj = datetime.date.today()
    current_month = today_obj.strftime("%m-%Y")
    _pm_num = 12 if today_obj.month == 1 else today_obj.month - 1
    _pm_year = today_obj.year - 1 if today_obj.month == 1 else today_obj.year
    prev_month = f"{_pm_num:02d}-{_pm_year}"

    _cm_month, _cm_year = int(current_month.split("-")[0]), int(current_month.split("-")[1])
    days_in_current_month = calendar.monthrange(_cm_year, _cm_month)[1]

    # ================= POST =================
    if request.method == "POST":

        act = request.form.get("action", "")

        try:
            # =========================================================
            # SAVE PERSON (Add new OR Edit existing — duplicate name blocked)
            # =========================================================
            if act == "save_person":

                person_id = request.form.get("person_id", "").strip()
                name = to_caps(request.form.get("name", "").strip())
                phone = request.form.get("phone", "").strip()
                salary = float(request.form.get("salary", 0) or 0)
                commission_pct = float(request.form.get("commission_pct", 0) or 0)
                person_type = request.form.get("person_type", "salesman")

                if not name:
                    flash("Name Required")
                    conn.rollback()
                    return redirect(url_for("salesmen"))

                cur.execute(
                    "SELECT id FROM salesmen WHERE UPPER(name)=UPPER(?) AND id != ?",
                    (name, person_id or -1)
                )
                if cur.fetchone():
                    flash(f"A salesman/worker named '{name}' already exists. Please use a different name.")
                    conn.rollback()
                    return redirect(url_for("salesmen"))

                if person_id:
                    cur.execute("SELECT name FROM salesmen WHERE id=?", (person_id,))
                    old_row = cur.fetchone()

                    if not old_row:
                        flash("Salesman not found")
                        conn.rollback()
                        return redirect(url_for("salesmen"))

                    old_name = old_row["name"]

                    cur.execute("""
                        UPDATE salesmen
                        SET name=?, phone=?, salary=?, commission_pct=?, salesman_type=?
                        WHERE id=?
                    """, (name, phone, salary, commission_pct, person_type, person_id))

                    if old_name != name:
                        cur.execute("UPDATE salesman_hr SET salesman=? WHERE salesman=?", (name, old_name))
                        cur.execute("UPDATE salesman_targets SET salesman=? WHERE salesman=?", (name, old_name))
                        cur.execute("UPDATE invoices SET salesman=? WHERE salesman=?", (name, old_name))

                    conn.commit()
                    flash(f"{name} Updated Successfully")

                else:
                    cur.execute("""
                        INSERT INTO salesmen
                        (name, phone, salary, commission_pct, salesman_type, status, joining_date)
                        VALUES (?,?,?,?,?,?,?)
                    """, (
                        name, phone, salary, commission_pct,
                        person_type, "Active", today_obj.strftime("%d-%m-%Y")
                    ))
                    conn.commit()
                    flash(f"{name} Saved Successfully")

            # =========================================================
            # HR ENTRY (attendance/absent/leave/holiday/advance/salary_paid/commission/bonus)
            # =========================================================
            elif act == "hr_entry":

                name = request.form.get("salesman", "").strip()
                hr_type = request.form.get("hr_type", "attendance").strip()
                date_str = request.form.get("hr_date") or today_obj.strftime("%d-%m-%Y")
                amount = float(request.form.get("amount", 0) or 0)
                note = request.form.get("note", "").strip()

                if not name:
                    flash("Salesman required")
                    conn.rollback()
                    return redirect(url_for("salesmen"))

                if hr_type in ("attendance", "absent", "leave", "holiday", "half_day", "late"):
                    cur.execute("""
                    SELECT id FROM salesman_hr
                    WHERE salesman=? AND date=? AND type IN
                    ('attendance','absent','leave','holiday','half_day','late')
                    """, (name, date_str))
                    if cur.fetchone():
                        flash("Attendance already marked for this date")
                        conn.rollback()
                        return redirect(url_for("salesmen"))
                cur.execute("""
                INSERT INTO salesman_hr (salesman, date, type, amount, note)
                VALUES (?,?,?,?,?)
                """, (name, date_str, hr_type, amount, note))

                conn.commit()
                flash(f"{hr_type.title()} Saved")

            # =========================================================
            # TARGET SAVE (insert or update, no duplicate rows)
            # =========================================================
            elif act == "save_target":

                salesman = request.form.get("salesman", "").strip()
                month = request.form.get("month", "").strip() or current_month
                product_name = request.form.get("product_name", "").strip()
                target_qty = float(request.form.get("target_qty", 0) or 0)
                target_amount = float(request.form.get("target_amount", 0) or 0)

                if not salesman or not product_name:
                    flash("Salesman aur Product dono required hain")
                    conn.rollback()
                    return redirect(url_for("salesmen"))

                cur.execute("""
                    SELECT id FROM salesman_targets
                    WHERE salesman=? AND month=? AND product_name=?
                """, (salesman, month, product_name))
                existing = cur.fetchone()

                if existing:
                    cur.execute("""
                        UPDATE salesman_targets
                        SET target_qty=?, target_amount=?
                        WHERE id=?
                    """, (target_qty, target_amount, existing["id"]))
                else:
                    cur.execute("""
                    INSERT INTO salesman_targets
                    (salesman, month, product_name, target_qty, target_amount)
                    VALUES (?,?,?,?,?)
                    """, (salesman, month, product_name, target_qty, target_amount))

                conn.commit()
                flash(f"Target Saved for {month}")

            # =========================================================
            # COPY PREVIOUS MONTH TARGETS -> NEW MONTH
            # =========================================================
            elif act == "copy_prev_target":

                salesman = request.form.get("salesman", "").strip()
                from_month = request.form.get("from_month", "").strip() or prev_month
                to_month = request.form.get("to_month", "").strip() or current_month

                cur.execute("""
                    SELECT product_name, target_qty, target_amount
                    FROM salesman_targets
                    WHERE salesman=? AND month=?
                """, (salesman, from_month))
                rows = cur.fetchall()

                if not rows:
                    flash(f"No target found for {from_month}")
                    conn.rollback()
                else:
                    copied = 0
                    for r in rows:
                        cur.execute("""
                            SELECT id FROM salesman_targets
                            WHERE salesman=? AND month=? AND product_name=?
                        """, (salesman, to_month, r["product_name"]))
                        ex = cur.fetchone()
                        if ex:
                            cur.execute("""
                                UPDATE salesman_targets
                                SET target_qty=?, target_amount=?
                                WHERE id=?
                            """, (r["target_qty"], r["target_amount"], ex["id"]))
                        else:
                            cur.execute("""
                                INSERT INTO salesman_targets
                                (salesman, month, product_name, target_qty, target_amount)
                                VALUES (?,?,?,?,?)
                            """, (salesman, to_month, r["product_name"], r["target_qty"], r["target_amount"]))
                        copied += 1
                    conn.commit()
                    flash(f"{copied} Targets copied from {from_month} to {to_month}")

            # =========================================================
            # DELETE HR ENTRY
            # =========================================================
            elif act == "delete_entry":
                entry_id = request.form.get("entry_id")
                cur.execute("DELETE FROM salesman_hr WHERE id=?", (entry_id,))
                conn.commit()
                flash("Entry Deleted")

            # =========================================================
            # DELETE TARGET
            # =========================================================
            elif act == "delete_target":
                target_id = request.form.get("target_id")
                cur.execute("DELETE FROM salesman_targets WHERE id=?", (target_id,))
                conn.commit()
                flash("Target Deleted")

            # =========================================================
            # DELETE SALESMAN (+ uski HR/Targets bhi saaf)
            # =========================================================
            elif act == "delete_salesman":
                sid = request.form.get("sid")
                cur.execute("SELECT name FROM salesmen WHERE id=?", (sid,))
                row = cur.fetchone()
                if row:
                    pname = row["name"]
                    cur.execute("DELETE FROM salesmen WHERE id=?", (sid,))
                    cur.execute("DELETE FROM salesman_hr WHERE salesman=?", (pname,))
                    cur.execute("DELETE FROM salesman_targets WHERE salesman=?", (pname,))
                    conn.commit()
                    flash("Salesman Deleted")
                else:
                    conn.rollback()
                    flash("Salesman not found")

            else:
                conn.rollback()

        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
        finally:
            conn.close()

        return redirect(url_for("salesmen"))

    # ================= GET DATA =================

    cur.execute("SELECT * FROM salesmen ORDER BY name")
    all_persons = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM salesman_hr ORDER BY id DESC")
    hr_rows = [dict(r) for r in cur.fetchall()]

    for r in hr_rows:
        try:
            d = datetime.datetime.strptime(r["date"], "%d-%m-%Y").date()
            r["days_old"] = (today_obj - d).days
        except:
            r["days_old"] = 999

    cur.execute("SELECT * FROM salesman_targets ORDER BY month DESC, salesman, product_name")
    target_rows = [dict(r) for r in cur.fetchall()]

    all_target_months = sorted({t["month"] for t in target_rows if t["month"]}, reverse=True)

    cur.execute("SELECT name FROM products ORDER BY name")
    product_names = [row["name"] for row in cur.fetchall()]

    # ================= AUTO SALARY / COMMISSION / LEAVES / SALES (per person) =================

    commission_summary = {}

    for p in all_persons:
        name = p["name"]

        # --- HR summary for current month, auto grouped ---
        cur.execute("""
            SELECT type, COUNT(*) as cnt, COALESCE(SUM(amount),0) as total
            FROM salesman_hr
            WHERE salesman=? AND substr(date,4,7)=?
            GROUP BY type
        """, (name, current_month))
        hr_month = {row["type"]: {"cnt": row["cnt"], "total": row["total"]} for row in cur.fetchall()}

        p["leaves_this_month"]   = hr_month.get("leave", {}).get("cnt", 0)
        p["absent_this_month"]   = hr_month.get("absent", {}).get("cnt", 0)
        p["holidays_this_month"] = hr_month.get("holiday", {}).get("cnt", 0)
        p["present_this_month"]  = hr_month.get("attendance", {}).get("cnt", 0)
        p["advance_this_month"]  = round(hr_month.get("advance", {}).get("total", 0), 2)
        p["bonus_this_month"]    = round(hr_month.get("bonus", {}).get("total", 0), 2)
        p["salary_paid_this_month"] = round(hr_month.get("salary_paid", {}).get("total", 0), 2)
        p["manual_commission_this_month"] = round(hr_month.get("commission", {}).get("total", 0), 2)

        # --- AUTO LEAVE/ABSENT SALARY DEDUCTION ---
        base_salary = float(p["salary"] or 0)
        per_day_salary = round(base_salary / days_in_current_month, 2) if days_in_current_month else 0
        deduction_days = p["absent_this_month"] + p["leaves_this_month"]   # holiday paid hai, deduct nahi hoti
        leave_deduction_amount = round(per_day_salary * deduction_days, 2)
        salary_after_leave = round(base_salary - leave_deduction_amount, 2)

        p["per_day_salary"] = per_day_salary
        p["deduction_days"] = deduction_days
        p["leave_deduction_amount"] = leave_deduction_amount
        p["salary_after_leave"] = salary_after_leave

        # --- Auto commission = commission_pct% of this month's sales by this salesman ---
        cur.execute("""
            SELECT COALESCE(SUM(total),0) as sales_total
            FROM invoices
            WHERE salesman=? AND substr(date,4,7)=?
        """, (name, current_month))
        month_sales = cur.fetchone()["sales_total"] or 0
        p["month_sales_total"] = round(month_sales, 2)
        p["auto_commission_this_month"] = round(month_sales * (float(p["commission_pct"] or 0) / 100.0), 2)

        # --- Net payable, fully auto (salary after leave deduction is used here) ---
        p["net_payable_this_month"] = round(
            salary_after_leave
            + p["auto_commission_this_month"]
            + p["bonus_this_month"]
            - p["advance_this_month"]
            - p["salary_paid_this_month"], 2
        )

        commission_summary[name] = p["auto_commission_this_month"] + p["manual_commission_this_month"]

        # --- Product wise sales this month for this salesman ---
        cur.execute("""
            SELECT ii.product as product,
                   COALESCE(SUM(ii.qty),0) as qty,
                   COALESCE(SUM(ii.qty*ii.unit_price),0) as revenue
            FROM invoices i
            JOIN invoice_items ii ON i.inv_no = ii.inv_no
            WHERE i.salesman=? AND substr(i.date,4,7)=?
            GROUP BY ii.product
            ORDER BY revenue DESC
        """, (name, current_month))
        p["products_this_month"] = [dict(row) for row in cur.fetchall()]

        # --- HR history (last 15) for this person's foldable card ---
        p["hr_history"] = [h for h in hr_rows if h["salesman"] == name][:15]

        # --- Targets grouped by month, achieved auto-calculated ---
        p_targets = [dict(t) for t in target_rows if t["salesman"] == name]
        for t in p_targets:
            cur.execute("""
                SELECT COALESCE(SUM(ii.qty),0) as aq, COALESCE(SUM(ii.qty*ii.unit_price),0) as aa
                FROM invoices i
                JOIN invoice_items ii ON i.inv_no = ii.inv_no
                WHERE i.salesman=? AND substr(i.date,4,7)=? AND ii.product=?
            """, (name, t["month"], t["product_name"]))
            ach = cur.fetchone()
            t["achieved_qty"] = round(ach["aq"] or 0, 2)
            t["achieved_amount"] = round(ach["aa"] or 0, 2)

        targets_by_month = {}
        for t in p_targets:
            targets_by_month.setdefault(t["month"], []).append(t)
        p["targets_by_month"] = dict(sorted(targets_by_month.items(), reverse=True))

    conn.close()

    # ================= HTML =================

    html = TPL_H + """

<style>

.person-card{
border:1px solid var(--border);
border-radius:var(--card-radius);
margin-bottom:16px;
background:var(--card-bg);
overflow:hidden;
box-shadow:var(--card-shadow);
}

.person-card > summary{
list-style:none;
cursor:pointer;
padding:16px 20px;
display:flex;
justify-content:space-between;
align-items:center;
flex-wrap:wrap;
gap:8px;
background:linear-gradient(135deg,#4338ca,#312e81);
color:white;
}
.person-card > summary::-webkit-details-marker{ display:none; }
.person-card > summary:after{
content:"▾";
font-size:16px;
margin-left:auto;
transition:transform .2s;
}
.person-card[open] > summary:after{ transform:rotate(180deg); }

.person-card .p-name{ font-size:17px; font-weight:800; color:white; }
.person-card .p-badges{ display:flex; gap:8px; flex-wrap:wrap; }
.mini-badge{
background:rgba(255,255,255,.15);
border:1px solid rgba(255,255,255,.3);
border-radius:6px;
padding:3px 8px;
font-size:12px;
font-weight:600;
color:white;
}
.mini-badge.green{ background:#ccfbf1; color:#0f766e; border-color:#5eead4; }
.mini-badge.red{ background:#ffe4e6; color:#be123c; border-color:#fda4af; }
.mini-badge.blue{ background:#e0e7ff; color:#4338ca; border-color:#a5b4fc; }

.person-body{ padding:20px; border-top:1px solid var(--border); background:var(--card-bg); }

.record-table{
width:100%;
border-collapse:collapse;
margin-top:15px;
}

.record-table th{
background:var(--body-bg);
border:1px solid var(--border);
padding:9px 10px;
font-size:12px;
font-weight:700;
color:var(--text-muted);
}
.record-table td{
border:1px solid var(--border);
padding:8px 10px;
font-size:13px;
color:var(--text);
}

.delete-btn{
background:linear-gradient(135deg,#e11d48,#be123c);
color:white;
border:none;
padding:6px 10px;
border-radius:6px;
cursor:pointer;
font-size:12px;
font-weight:600;
box-shadow:0 2px 0 rgba(0,0,0,.2);
}

.add-btn{
position:fixed;
bottom:30px;
right:30px;
width:64px;
height:64px;
border-radius:50%;
font-size:30px;
border:none;
background:linear-gradient(135deg,#f5a524,#d97706);
color:white;
cursor:pointer;
z-index:998;
box-shadow:0 4px 0 rgba(0,0,0,.25), 0 8px 16px rgba(0,0,0,.2);
transition:transform .1s ease, box-shadow .1s ease;
}
.add-btn:active{transform:translateY(3px);box-shadow:0 1px 0 rgba(0,0,0,.25)}

.month-group{
border:1px solid var(--border);
border-radius:9px;
margin-top:10px;
background:var(--body-bg);
overflow:hidden;
}
.month-group > summary{
cursor:pointer;
padding:10px 14px;
font-weight:700;
color:var(--text);
background:linear-gradient(135deg,#0d9488,#0f766e);
color:white;
}
.month-group > summary::-webkit-details-marker{ display:none; }

.salary-box{
background:var(--body-bg);
border:1.5px dashed #f5a524;
border-radius:9px;
padding:14px 16px;
margin:12px 0;
font-size:13px;
color:var(--text);
}
.salary-box b{ color:#0d3b34; }

</style>

<div class="tgt-hero" style="margin-bottom:20px;">
  <h2 style="color:white;margin:0;font-size:20px;font-weight:800;border:none;padding:0;">👥 Salesmen & Workers Management</h2>
</div>

<button class="add-btn" onclick="openAddModal()">+</button>

<!-- ================= ADD / EDIT PERSON ================= -->

<div id="addModal"
style="display:none;position:fixed;top:0;left:0;
width:100%;height:100%;
background:rgba(0,0,0,0.7);z-index:999;">

<div style="background:white;
max-width:700px;
margin:70px auto;
padding:25px;
border-radius:12px;">

<h3 id="modalTitle">Add Salesman / Worker</h3>

<form method="post">
<input type="hidden" name="action" value="save_person">
<input type="hidden" name="person_id" id="f_person_id" value="">

<div class="form-row form-row-2">
<div class="form-group">
<label>Name</label>
<input name="name" id="f_name" class="form-control" required>
</div>
<div class="form-group">
<label>Phone</label>
<input name="phone" id="f_phone" class="form-control">
</div>
</div>

<div class="form-row form-row-3">
<div class="form-group">
<label>Salary</label>
<input type="number" name="salary" id="f_salary" class="form-control">
</div>
<div class="form-group">
<label>Commission %</label>
<input type="number" step="0.1" name="commission_pct" id="f_commission_pct" class="form-control">
</div>
<div class="form-group">
<label>Type</label>
<select name="person_type" id="f_person_type" class="form-control">
<option value="salesman">Salesman</option>
<option value="worker">Worker</option>
</select>
</div>
</div>

<button class="btn btn-primary">Save</button>
<button type="button" class="btn btn-secondary" onclick="closePersonModal()">Close</button>

</form>
</div>
</div>

<script>
function openAddModal(){
    document.getElementById('modalTitle').innerText = 'Add Salesman / Worker';
    document.getElementById('f_person_id').value = '';
    document.getElementById('f_name').value = '';
    document.getElementById('f_phone').value = '';
    document.getElementById('f_salary').value = '';
    document.getElementById('f_commission_pct').value = '';
    document.getElementById('f_person_type').value = 'salesman';
    document.getElementById('addModal').style.display = 'block';
}
function editPerson(ev, id, name, phone, salary, pct, ptype){
    ev.preventDefault();
    ev.stopPropagation();
    document.getElementById('modalTitle').innerText = 'Edit Salesman / Worker';
    document.getElementById('f_person_id').value = id;
    document.getElementById('f_name').value = name;
    document.getElementById('f_phone').value = phone;
    document.getElementById('f_salary').value = salary;
    document.getElementById('f_commission_pct').value = pct;
    document.getElementById('f_person_type').value = ptype;
    document.getElementById('addModal').style.display = 'block';
}
function closePersonModal(){
    document.getElementById('addModal').style.display = 'none';
}
</script>

<!-- ================= PERSONS (FOLDABLE) ================= -->

<div class="card">
<h3>All Salesmen / Workers — {{current_month}} ({{days_in_current_month}} din)</h3>

{% for p in all_persons %}
<details class="person-card">
<summary>
<span class="p-name">{{p.name}} <small style="font-weight:400;color:#64748b">({{p.salesman_type}})</small></span>
<span class="p-badges">
<span class="mini-badge blue">Sales: Rs {{'{:,.0f}'.format(p.month_sales_total)}}</span>
<span class="mini-badge green">Commission: Rs {{'{:,.0f}'.format(p.auto_commission_this_month)}}</span>
<span class="mini-badge red">Leave Deduction: Rs {{'{:,.0f}'.format(p.leave_deduction_amount)}}</span>
<span class="mini-badge">Net Payable: Rs {{'{:,.0f}'.format(p.net_payable_this_month)}}</span>
<span class="mini-badge">Present: {{p.present_this_month}}</span>
<span class="mini-badge red">Leave: {{p.leaves_this_month}}</span>
<span class="mini-badge red">Absent: {{p.absent_this_month}}</span>
<span class="mini-badge">Holiday: {{p.holidays_this_month}}</span>
</span>
</summary>

<div class="person-body">

<button type="button" class="btn btn-secondary"
onclick="editPerson(event, '{{p.id}}', '{{p.name}}', '{{p.phone}}', '{{p.salary}}', '{{p.commission_pct}}', '{{p.salesman_type}}')">
✏️ Edit
</button>

<form method="post" onsubmit="return confirm('Delete salesman? HR & targets bhi delete ho jayenge.')" style="display:inline">
<input type="hidden" name="action" value="delete_salesman">
<input type="hidden" name="sid" value="{{p.id}}">
<button class="delete-btn">Delete Salesman</button>
</form>

<!-- ===== AUTO SALARY CALCULATION BOX ===== -->
<div class="salary-box">
<b>Salary Calculation ({{current_month}}):</b><br>
Base Salary: Rs {{'{:,.0f}'.format(p.salary)}} ÷ {{days_in_current_month}} din = Per Day <b>Rs {{p.per_day_salary}}</b><br>
Leave + Absent Days: <b>{{p.deduction_days}}</b> × Rs {{p.per_day_salary}} = Deduction <b style="color:#dc2626">Rs {{'{:,.0f}'.format(p.leave_deduction_amount)}}</b><br>
Salary After Leave Deduction: <b style="color:#166534">Rs {{'{:,.0f}'.format(p.salary_after_leave)}}</b><br>
+ Auto Commission: Rs {{'{:,.0f}'.format(p.auto_commission_this_month)}}
&nbsp;+ Bonus: Rs {{p.bonus_this_month}}
&nbsp;− Advance: Rs {{p.advance_this_month}}
&nbsp;− Already Paid: Rs {{p.salary_paid_this_month}}<br>
<b>= Net Payable: Rs {{'{:,.0f}'.format(p.net_payable_this_month)}}</b>
</div>

<hr>

<!-- ===== Product wise sales this month ===== -->
<h4>📦 Is Mahine Product Wise Sale</h4>
<table class="record-table">
<thead><tr><th>Product</th><th>Qty</th><th>Revenue</th></tr></thead>
<tbody>
{% for row in p.products_this_month %}
<tr><td>{{row.product}}</td><td>{{row.qty}}</td><td>Rs {{'{:,.0f}'.format(row.revenue)}}</td></tr>
{% endfor %}
{% if not p.products_this_month %}
<tr><td colspan="3" class="text-center text-muted">Is mahine koi sale nahi</td></tr>
{% endif %}
</tbody>
</table>

<hr>

<!-- ===== HR ENTRY ===== -->
<h4>🕒 Attendance / Advance / Bonus Entry</h4>
<form method="post">
<input type="hidden" name="action" value="hr_entry">
<input type="hidden" name="salesman" value="{{p.name}}">
<div class="form-row form-row-4">
<div class="form-group">
<label>Date</label>
<input type="text" name="hr_date" value="{{today}}" class="form-control">
</div>
<div class="form-group">
<label>Type</label>
<select name="hr_type" class="form-control">
<option value="attendance">Attendance</option>
<option value="absent">Absent</option>
<option value="leave">Leave</option>
<option value="holiday">Holiday (Company/National)</option>
<option value="half_day">Half Day</option>
<option value="late">Late (Punctuality)</option>
<option value="advance">Advance</option>
<option value="salary_paid">Salary Paid</option>
<option value="bonus">Bonus</option>
<option value="commission">Manual Commission (adjustment)</option>
</select>
</div>
<div class="form-group">
<label>Amount</label>
<input type="number" step="0.01" name="amount" class="form-control">
</div>
<div class="form-group">
<label>Note</label>
<input name="note" class="form-control">
</div>
</div>
<button class="btn btn-success">Save Entry</button>
</form>

<table class="record-table" style="margin-top:12px">
<thead><tr><th>Date</th><th>Type</th><th>Amount</th><th>Note</th><th></th></tr></thead>
<tbody>
{% for h in p.hr_history %}
<tr>
<td>{{h.date}}</td><td>{{h.type}}</td><td>Rs {{h.amount}}</td><td>{{h.note}}</td>
<td>
<form method="post" onsubmit="return confirm('Delete entry?')">
<input type="hidden" name="action" value="delete_entry">
<input type="hidden" name="entry_id" value="{{h.id}}">
<button class="delete-btn">X</button>
</form>
</td>
</tr>
{% endfor %}
{% if not p.hr_history %}
<tr><td colspan="5" class="text-center text-muted">Koi record nahi</td></tr>
{% endif %}
</tbody>
</table>

<hr>

<!-- ===== TARGET SAVE ===== -->
<h4>🎯 Target Save Karein</h4>
<form method="post">
<input type="hidden" name="action" value="save_target">
<input type="hidden" name="salesman" value="{{p.name}}">
<div class="form-row form-row-4">
<div class="form-group">
<label>Month (MM-YYYY)</label>
<input name="month" placeholder="{{current_month}}" value="{{current_month}}" class="form-control">
</div>
<div class="form-group">
<label>Product</label>
<select name="product_name" class="form-control">
{% for pn in product_names %}<option value="{{pn}}">{{pn}}</option>{% endfor %}
</select>
</div>
<div class="form-group">
<label>Target Qty</label>
<input type="number" step="0.01" name="target_qty" class="form-control">
</div>
<div class="form-group">
<label>Target Amount</label>
<input type="number" step="0.01" name="target_amount" class="form-control">
</div>
</div>
<button class="btn btn-primary">Save Target</button>
</form>

<!-- ===== COPY PREVIOUS MONTH TARGET ===== -->
<form method="post" style="margin-top:10px">
<input type="hidden" name="action" value="copy_prev_target">
<input type="hidden" name="salesman" value="{{p.name}}">
<div class="form-row form-row-3">
<div class="form-group">
<label>From Month</label>
<select name="from_month" class="form-control">
{% for m in all_target_months %}<option value="{{m}}" {% if m==prev_month %}selected{% endif %}>{{m}}</option>{% endfor %}
</select>
</div>
<div class="form-group">
<label>To Month</label>
<input name="to_month" value="{{current_month}}" class="form-control">
</div>
<div class="form-group" style="display:flex;align-items:end">
<button class="btn btn-secondary">📋 Copy Previous Month Target</button>
</div>
</div>
</form>

<!-- ===== TARGETS BY MONTH (FOLDABLE HISTORY) ===== -->
{% for month, trows in p.targets_by_month.items() %}
<details class="month-group" {% if month==current_month %}open{% endif %}>
<summary>{{month}}{% if month==current_month %} (Current){% endif %} — {{trows|length}} product(s)</summary>
<table class="record-table">
<thead><tr><th>Product</th><th>Target Qty</th><th>Achieved Qty</th><th>Target Amt</th><th>Achieved Amt</th><th></th></tr></thead>
<tbody>
{% for t in trows %}
<tr>
<td>{{t.product_name}}</td>
<td>{{t.target_qty}}</td>
<td class="{% if t.achieved_qty >= t.target_qty and t.target_qty > 0 %}text-success{% else %}text-danger{% endif %}">{{t.achieved_qty}}</td>
<td>Rs {{'{:,.0f}'.format(t.target_amount)}}</td>
<td class="{% if t.achieved_amount >= t.target_amount and t.target_amount > 0 %}text-success{% else %}text-danger{% endif %}">Rs {{'{:,.0f}'.format(t.achieved_amount)}}</td>
<td>
<form method="post" onsubmit="return confirm('Delete target?')">
<input type="hidden" name="action" value="delete_target">
<input type="hidden" name="target_id" value="{{t.id}}">
<button class="delete-btn">X</button>
</form>
</td>
</tr>
{% endfor %}
</tbody>
</table>
</details>
{% endfor %}
{% if not p.targets_by_month %}
<p class="text-muted" style="margin-top:8px">Abhi koi target save nahi hua</p>
{% endif %}

</div>
</details>
{% endfor %}
{% if not all_persons %}
<p class="text-center text-muted">Koi salesman/worker abhi tak add nahi hua</p>
{% endif %}

</div>

""" + TPL_F

    return render_template_string(
        html,
        project=get_setting("project_name"),
        all_persons=all_persons,
        hr_rows=hr_rows,
        target_rows=target_rows,
        all_target_months=all_target_months,
        product_names=product_names,
        commission_summary=commission_summary,
        current_month=current_month,
        prev_month=prev_month,
        days_in_current_month=days_in_current_month,
        today=today_obj.strftime("%d-%m-%Y")
    )
# ============================================================
# MARKET ANALYSIS
# ============================================================
@app.route("/market_analysis")
@login_required
def market_analysis():
    try:
        with db_transaction() as _c:
            _inv_rows = _c.execute("""
                SELECT customer, customer_address, salesman, total, customer_type, date
                FROM invoices
            """).fetchall()
            _line_rows = _c.execute("""
                SELECT product, qty, unit_price FROM invoice_items
            """).fetchall()
    except Exception as e:
        flash(f"Market analysis load failed, no changes made (safe rollback): {e}")
        return redirect(url_for("home"))

    all_inv = [
        {"name": r[0], "address": r[1], "salesman": r[2], "total": r[3],
         "customer_type": r[4], "date": r[5]}
        for r in _inv_rows
    ]
    all_lines = [
        {"product": r[0], "qty": r[1], "unit_price": r[2]}
        for r in _line_rows
    ]
    all_payments = read_payments_db()

    # Customer wise analysis
    cust_data = {}
    for inv in all_inv:
        key = (to_caps(inv.get("name","")), to_caps(inv.get("address","")))
        if key[0]:
            if key not in cust_data:
                cust_data[key] = {"invoices": 0, "total": 0.0, "paid": 0.0, "type": inv.get("customer_type","customer")}
            cust_data[key]["invoices"] += 1
            try: cust_data[key]["total"] += float(inv.get("total","0") or 0)
            except: pass

    for p in all_payments:
        key = (to_caps(p.get("customer","")), to_caps(p.get("address","")))
        if key in cust_data:
            try: cust_data[key]["paid"] += float(p.get("amount","0") or 0)
            except: pass

    top_customers = sorted(cust_data.items(), key=lambda x: x[1]["total"], reverse=True)[:10]

    # Salesman wise
    sm_data = {}
    for inv in all_inv:
        sm = to_caps(inv.get("salesman","") or "Unassigned")
        if sm not in sm_data:
            sm_data[sm] = {"invoices": 0, "total": 0.0}
        sm_data[sm]["invoices"] += 1
        try: sm_data[sm]["total"] += float(inv.get("total","0") or 0)
        except: pass

    # Product wise
    prod_data = {}
    for li in all_lines:
        pn = to_caps(li.get("product",""))
        if pn:
            if pn not in prod_data:
                prod_data[pn] = {"qty": 0.0, "revenue": 0.0}
            try:
                q = float(li.get("qty","0") or 0)
                u = float(li.get("unit_price","0") or 0)
                prod_data[pn]["qty"] += q
                prod_data[pn]["revenue"] += q * u
            except: pass

    top_products = sorted(prod_data.items(), key=lambda x: x[1]["revenue"], reverse=True)[:10]

    # Monthly trend (last 6 months)
    now = datetime.datetime.now()
    monthly = {}
    for i in range(6):
        d = now - datetime.timedelta(days=30*i)
        k = d.strftime("%b %Y")
        monthly[k] = 0.0
    for inv in all_inv:
        d = inv.get("date","")
        try:
            for fmt in ("%d-%m-%y","%d-%m-%Y","%Y-%m-%d"):
                try: dt = datetime.datetime.strptime(d, fmt); break
                except: continue
            else: continue
            k = dt.strftime("%b %Y")
            if k in monthly:
                monthly[k] += float(inv.get("total","0") or 0)
        except: pass
    monthly_list = list(reversed(list(monthly.items())))

    # Customer type split
    type_split = {"wholesaler": 0.0, "distributor": 0.0, "customer": 0.0}
    for inv in all_inv:
        t = inv.get("customer_type","customer") or "customer"
        try: type_split[t] = type_split.get(t,0) + float(inv.get("total","0") or 0)
        except: pass

    html = TPL_H + """
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>

<style>
.ma-hero{background:linear-gradient(135deg,#0d3b34,#0f5c52);border-radius:var(--card-radius);padding:22px 26px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px}
.ma-hero h2{color:white;margin:0;font-size:20px;font-weight:800;border:none;padding:0}
.ma-hero .breadcrumb{color:#cfe6e0}
.ma-hero .breadcrumb a{color:#f5c877}
.chart-card{background:var(--card-bg);border-radius:var(--card-radius);box-shadow:var(--card-shadow);border:1px solid var(--border);padding:22px;margin-bottom:22px}
.chart-card h3{margin-top:0}
</style>

<div class="ma-hero no-print">
  <div><div class="breadcrumb"><a href="/">Dashboard</a> › Market Analysis</div>
  <h2>🔬 Market Analysis & Business Intelligence</h2></div>
  <button class="btn btn-secondary" onclick="printPage()">🖨 Print Report</button>
</div>

<!-- MONTHLY TREND -->
<div class="chart-card">
  <h3>📈 Monthly Sales Trend (Last 6 Months)</h3>
  <canvas id="monthlyTrendChart" height="90"></canvas>
</div>

<!-- CUSTOMER TYPE SPLIT -->
<div class="card-grid card-grid-2 mb-3">
  <div class="chart-card">
    <h3>🥧 Sales By Customer Type</h3>
    <canvas id="typeSplitChart" height="220"></canvas>
  </div>
  <div class="card-grid card-grid-1" style="display:flex;flex-direction:column;gap:14px">
    <div class="dash-stat">
      <div class="ic" style="background:linear-gradient(135deg,#4f46e5,#4338ca)">🏭</div>
      <div><div class="lbl">Wholesaler Sales</div><div class="val">Rs {{'{:,.0f}'.format(type_split.wholesaler)}}</div></div>
    </div>
    <div class="dash-stat">
      <div class="ic" style="background:linear-gradient(135deg,#7e22ce,#6b21a8)">🚚</div>
      <div><div class="lbl">Distributor Sales</div><div class="val">Rs {{'{:,.0f}'.format(type_split.distributor)}}</div></div>
    </div>
    <div class="dash-stat">
      <div class="ic" style="background:linear-gradient(135deg,#0d9488,#0f766e)">🛒</div>
      <div><div class="lbl">Customer Sales</div><div class="val">Rs {{'{:,.0f}'.format(type_split.customer)}}</div></div>
    </div>
  </div>
</div>

<div class="card-grid card-grid-2 mb-3">
  <!-- TOP CUSTOMERS -->
  <div class="card p-0">
    <div style="padding:14px 16px;border-bottom:1px solid var(--border)"><h3 style="margin:0;border:none;padding:0">👑 Top 10 Customers</h3></div>
    <table>
      <thead><tr><th>#</th><th>Customer</th><th>Invoices</th><th>Total</th><th>Pending</th></tr></thead>
      <tbody>
        {% for (name,addr), d in top_customers %}
        <tr>
          <td>{{loop.index}}</td>
          <td>
            <div class="fw-bold">{{name[:20]}}</div>
            <div class="text-muted" style="font-size:11px">{{addr[:20]}}</div>
          </td>
          <td><span class="badge badge-blue">{{d.invoices}}</span></td>
          <td class="fw-bold text-success">Rs {{'{:,.0f}'.format(d.total)}}</td>
          <td class="text-danger">Rs {{'{:,.0f}'.format([d.total - d.paid, 0]|max)}}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- TOP PRODUCTS -->
  <div class="card p-0">
    <div style="padding:14px 16px;border-bottom:1px solid var(--border)"><h3 style="margin:0;border:none;padding:0">🏆 Top 10 Products</h3></div>
    <div style="padding:16px 16px 4px"><canvas id="topProductsChart" height="180"></canvas></div>
    <table>
      <thead><tr><th>#</th><th>Product</th><th>Qty Sold</th><th>Revenue</th></tr></thead>
      <tbody>
        {% for pname, d in top_products %}
        <tr>
          <td>{{loop.index}}</td>
          <td class="fw-bold">{{pname[:22]}}</td>
          <td>{{'{:,.0f}'.format(d.qty)}}</td>
          <td class="fw-bold text-primary">Rs {{'{:,.0f}'.format(d.revenue)}}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<!-- SALESMAN ANALYSIS -->
<div class="card mb-3">
  <h3>🤝 Salesman Wise Performance</h3>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Salesman</th><th>Total Invoices</th><th>Total Sales</th><th>Avg Invoice</th></tr></thead>
      <tbody>
        {% for sm, d in sm_data.items()|sort(attribute='1.total',reverse=True) %}
        <tr>
          <td class="fw-bold">{{sm}}</td>
          <td><span class="badge badge-blue">{{d.invoices}}</span></td>
          <td class="fw-bold text-success">Rs {{'{:,.0f}'.format(d.total)}}</td>
          <td class="text-muted">Rs {{'{:,.0f}'.format(d.total / d.invoices if d.invoices else 0)}}</td>
        </tr>
        {% endfor %}
        {% if not sm_data %}<tr><td colspan="4" class="text-center text-muted">No data yet</td></tr>{% endif %}
      </tbody>
    </table>
  </div>
</div>
""" + TPL_F
    return render_template_string(html,
        project=get_setting("project_name"),
        monthly_list=monthly_list,
        type_split=type_split,
        top_customers=top_customers,
        top_products=top_products,
        sm_data=sm_data
    )

# ======================================================================
# ============  DELIVERY NOTE MODULE (SQLite, self-contained) — v4 =====
# ======================================================================
# PASTE LOCATION: agar PEHLI (v1) ya DOOSRI (v2) ya TEESRI (v3) wali
# already paste ki hui hai to usay poori tarah REMOVE karke (start se
# "MODULE — END" tak) is NAYI (v4) file se REPLACE kar do.
# Nayi baar paste kar rahe ho to: is poore block ko file k END mein,
# is line k UOPER paste karo:
#     if __name__ == "__main__":
# Bas EK jaga paste karna hai. Kahi aur kuch nahi chairna.
#
# v4 mein kya fix hua:
#   - *** ASAL BUG FIX ***: "Load From Invoice" kaam nahi kar raha tha
#     kyunke aapke app mein invoice DATA seedha SQLite "invoices" table
#     mein nahi jata (save_invoice_sqlite() function bani hui hai lekin
#     kahin call hi nahi hoti) — asal invoice data sirf CSV files
#     (invoices.csv + invoice_lines.csv) mein save hota hai. Ab yeh
#     module wahi CSV files (jo aapka asal source-of-truth hai) se
#     invoice ka data parhta hai, is liye ab load hoga.
#   - Customer Name aur Address ab typing-suggestion (datalist) se
#     filter hote hain — wahi customers list jo baqi invoice forms
#     mein use hoti hai (load_customers()). Naam select karte hi
#     address/phone bhi khud bhar jate hain agar match mil jaye.
#   - Duplicate product MERGE nahi hota — seedha ALLOW hi nahi hota.
#   - Product select karo to uski Quantity likhna LAZMI hai (0 se zyada).
#   - Customer Name aur Address dono LAZMI hain.
#   - Total Quantity form pe live dikhti hai.
#   - Unit agar select/edit na ho to print (PDF) mein UNIT column khali
#     rahega — "Carton" force nahi hoga.
#   - Auto-extend row (last row mein type karte hi nayi row).
# ======================================================================

# ---------- 1) TABLES ----------
def init_delivery_note_tables():
    try:
        conn = db()
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS delivery_notes (
            dn_no TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            ref_no TEXT,
            po_no TEXT,
            inv_no TEXT,
            customer TEXT,
            customer_address TEXT,
            customer_phone TEXT,
            notes TEXT,
            total_qty REAL DEFAULT 0,
            status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS delivery_note_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dn_no TEXT,
            product TEXT,
            unit TEXT,
            qty REAL DEFAULT 0,
            FOREIGN KEY(dn_no) REFERENCES delivery_notes(dn_no) ON DELETE CASCADE
        )
        """)
        conn.commit()
        print("✅ Delivery Note tables ready")
    except Exception as e:
        conn.rollback()
        print("❌ Delivery Note DB Error:", e)
    finally:
        conn.close()

init_delivery_note_tables()

# ---------- 2) OPTIONAL COMPANY-INFO SETTINGS (address/phone/email/tagline) ----------
def ensure_dn_settings():
    try:
        with db_transaction() as _c5:
            existing = {r[0] for r in _c5.execute("SELECT key FROM app_settings").fetchall()}
        defaults = {
            "company_address": "",
            "company_phone": "",
            "company_email": "",
            "company_website": "",
            "company_tagline": "",
        }
        for k, v in defaults.items():
            if k not in existing:
                set_setting(k, v)
    except Exception as e:
        print("❌ DN Settings init error:", e)

ensure_dn_settings()

# ---------- 3) DN NUMBER GENERATOR (pure SQLite, race-safe) ----------
def next_dn_no():
    with _inv_no_lock:
        conn = db()
        try:
            cur = conn.cursor()
            year = datetime.date.today().year
            cur.execute(
                "SELECT dn_no FROM delivery_notes WHERE dn_no LIKE ? ORDER BY rowid DESC LIMIT 1",
                (f"DN-{year}-%",)
            )
            row = cur.fetchone()
            last_seq = int(row[0].split("-")[-1]) if row else 0
            return f"DN-{year}-{last_seq+1:04d}"
        finally:
            conn.close()

# ---------- 4) DUPLICATE CHECK (ab merge nahi karte — sirf pehchan k reject karte hain) ----------
def _find_duplicate_product(items: list):
    """Same product agar 2 dafa list mein ho to uska naam return kar do, warna None."""
    seen = set()
    for it in items:
        name = (it.get("product") or "").strip().lower()
        if not name:
            continue
        if name in seen:
            return it.get("product")
        seen.add(name)
    return None

# ---------- 5) SAVE (WITH PROPER ROLLBACK) ----------
def save_delivery_note_sqlite(dn: dict, items: list):
    conn = db()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO delivery_notes
            (dn_no, date, ref_no, po_no, inv_no, customer, customer_address,
             customer_phone, notes, total_qty, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            dn["dn_no"], dn["date"], dn.get("ref_no",""), dn.get("po_no",""),
            dn.get("inv_no",""), dn.get("customer",""), dn.get("customer_address",""),
            dn.get("customer_phone",""), dn.get("notes",""),
            sum(i["qty"] for i in items), "Active"
        ))
        for li in items:
            c.execute("""
                INSERT INTO delivery_note_items (dn_no, product, unit, qty)
                VALUES (?,?,?,?)
            """, (dn["dn_no"], li["product"], li.get("unit","") or "", li["qty"]))
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def load_delivery_note(dn_no):
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT dn_no,date,ref_no,po_no,inv_no,customer,customer_address,customer_phone,notes,total_qty,status FROM delivery_notes WHERE dn_no=?", (dn_no,))
        row = c.fetchone()
        if not row:
            return None, []
        dn = {
            "dn_no": row[0], "date": row[1], "ref_no": row[2], "po_no": row[3],
            "inv_no": row[4], "customer": row[5], "customer_address": row[6],
            "customer_phone": row[7], "notes": row[8], "total_qty": row[9], "status": row[10]
        }
        c.execute("SELECT product, unit, qty FROM delivery_note_items WHERE dn_no=?", (dn_no,))
        items = [{"product": r[0], "unit": r[1], "qty": r[2]} for r in c.fetchall()]
        return dn, items
    finally:
        conn.close()

# ---------- 6) PDF DRAWING (matches the "SEIZE ENTERPRISES" Delivery Note layout) ----------
#     Multi-page safe: agar items zyada hon to table khud agle page pe chali jati
#     hai, aur "Thank You" + signatures hamesha content k NEECHE hi print hote hain.
#     Unit column: agar user ne unit select/edit nahi ki (khali chori) to PRINT
#     mein bhi khali rahega — koi default force nahi hota.
def draw_delivery_note_pdf(buf, company, address, phone, email, tagline, logo_path, show_logo,
                            dn_no, date_str, ref_no, po_no,
                            cust_name, cust_addr, cust_phone,
                            items, notes) -> None:
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.lib import colors
    import textwrap

    NAVY = colors.HexColor("#132a52")
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    ML = 15*mm; MR = W - 15*mm
    lw = 0.8
    BOTTOM_MARGIN = 15*mm
    FOOTER_BLOCK_H = 92*mm   # total-qty + notes + receiver-confirmation + signatures + thank-you k liye reserved height

    # ---------- HEADER ----------
    top_y = H - 15*mm
    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(NAVY)
    c.drawString(ML, top_y, (company or "").upper())

    info_y = top_y - 6*mm
    c.setFont("Helvetica", 9.5)
    c.setFillColor(colors.black)
    for line in [address, phone, email]:
        if line:
            c.drawString(ML, info_y, str(line))
            info_y -= 4.5*mm

    if show_logo and logo_path and Path(logo_path).exists():
        try:
            img = ImageReader(logo_path)
            c.drawImage(img, MR - 40*mm, top_y - 14*mm, width=40*mm, height=16*mm,
                        preserveAspectRatio=True, mask='auto')
            if tagline:
                c.setFont("Helvetica-Oblique", 8)
                c.setFillColor(NAVY)
                c.drawCentredString(MR - 20*mm, top_y - 17*mm, tagline)
        except Exception as e:
            print("Logo error:", e)
    elif tagline:
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(NAVY)
        c.drawRightString(MR, top_y - 2*mm, tagline)

    c.setFillColor(colors.black)
    header_bottom = min(info_y, top_y - 16*mm) - 2*mm
    c.setLineWidth(1.2)
    c.setStrokeColor(NAVY)
    c.line(ML, header_bottom, MR, header_bottom)
    c.setStrokeColor(colors.black)
    c.setLineWidth(lw)

    # ---------- TITLE + INFO BOX ----------
    title_y = header_bottom - 12*mm
    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(NAVY)
    c.drawString(ML, title_y, "DELIVERY NOTE")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.grey)
    c.drawString(ML, title_y - 6*mm, "GOODS DELIVERED IN GOOD CONDITION")
    c.setFillColor(colors.black)

    box_w = 75*mm
    box_x = MR - box_w
    box_top = header_bottom - 4*mm
    row_h = 6*mm
    box_bot = box_top - 4*row_h
    c.setLineWidth(lw)
    c.rect(box_x, box_bot, box_w, box_top - box_bot)
    label_x = box_x + 2*mm
    val_x = box_x + 30*mm
    rows = [("Delivery No.", dn_no), ("Date", date_str),
            ("Reference No.", ref_no or "-"), ("PO / Order No.", po_no or "-")]
    ry = box_top
    for i, (lbl, val) in enumerate(rows):
        if i > 0:
            c.line(box_x, ry, box_x + box_w, ry)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(label_x, ry - row_h + 2*mm, lbl)
        c.setFont("Helvetica", 9)
        c.drawString(val_x, ry - row_h + 2*mm, str(val))
        ry -= row_h

    # ---------- DELIVER TO BOX ----------
    dt_top = box_bot - 8*mm
    c.setFillColor(NAVY)
    c.rect(ML, dt_top - 6*mm, 40*mm, 6*mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(ML + 3*mm, dt_top - 4.2*mm, "DELIVER TO")
    c.setFillColor(colors.black)

    dt_box_top = dt_top - 6*mm
    dt_box_h = 26*mm
    dt_box_bot = dt_box_top - dt_box_h
    c.setLineWidth(lw)
    c.rect(ML, dt_box_bot, MR - ML, dt_box_h)

    ty = dt_box_top - 6*mm
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(ML + 3*mm, ty, "Customer / Shop Name :")
    c.setFont("Helvetica", 9.5)
    c.drawString(ML + 52*mm, ty, str(cust_name or "")[:45])
    ty -= 6*mm
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(ML + 3*mm, ty, "Address :")
    c.setFont("Helvetica", 9.5)
    addr_lines = textwrap.wrap(str(cust_addr or ""), 70) or [""]
    for al in addr_lines[:2]:
        c.drawString(ML + 52*mm, ty, al)
        ty -= 5*mm
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(ML + 3*mm, ty, "Phone / Mobile :")
    c.setFont("Helvetica", 9.5)
    c.drawString(ML + 52*mm, ty, str(cust_phone or ""))

    # ---------- ITEMS TABLE (multi-page safe) ----------
    c_prod = ML + 18*mm
    c_unit = MR - 55*mm
    c_qty  = MR - 25*mm
    RH = 7*mm

    def draw_table_header(y_top):
        hy = y_top - RH
        c.setFillColor(NAVY)
        c.rect(ML, hy, MR - ML, RH, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString((ML + c_prod)/2, hy + 2.3*mm, "Sr.")
        c.drawCentredString((c_prod + c_unit)/2, hy + 2.3*mm, "PRODUCT NAME")
        c.drawCentredString((c_unit + c_qty)/2, hy + 2.3*mm, "UNIT")
        c.drawCentredString((c_qty + MR)/2, hy + 2.3*mm, "QUANTITY")
        c.setFillColor(colors.black)
        return hy

    tbl_top = dt_box_bot - 6*mm
    y = draw_table_header(tbl_top)
    total_qty = 0.0
    n_rows = max(len(items), 5)

    for i in range(n_rows):
        if y - RH < BOTTOM_MARGIN + FOOTER_BLOCK_H and i < n_rows - 1:
            c.showPage()
            y = draw_table_header(H - 15*mm)

        row_y = y - RH
        c.setLineWidth(0.4)
        c.rect(ML, row_y, MR - ML, RH)
        for x in [c_prod, c_unit, c_qty]:
            c.line(x, y, x, row_y)
        c.setFont("Helvetica", 9.5)
        c.drawCentredString((ML + c_prod)/2, row_y + 2.3*mm, str(i+1))
        if i < len(items):
            li = items[i]
            qty = float(li.get("qty") or 0)
            total_qty += qty
            unit_val = str(li.get("unit") or "").strip()   # unit select/edit na ho to yahan khali hi rahega
            c.drawString(c_prod + 2*mm, row_y + 2.3*mm, str(li.get("product",""))[:38])
            if unit_val:
                c.drawCentredString((c_unit + c_qty)/2, row_y + 2.3*mm, unit_val)
            c.drawCentredString((c_qty + MR)/2, row_y + 2.3*mm, f"{qty:g}")
        y = row_y

    tbl_bottom = y
    c.setLineWidth(lw)

    if tbl_bottom - FOOTER_BLOCK_H < BOTTOM_MARGIN:
        c.showPage()
        tbl_bottom = H - 15*mm

    # ---------- TOTAL QTY + NOTES ----------
    tq_top = tbl_bottom - 3*mm
    tq_h = 14*mm
    tq_w = 55*mm
    c.setLineWidth(lw)
    c.rect(ML, tq_top - tq_h, tq_w, tq_h)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(ML + 2*mm, tq_top - 5*mm, "TOTAL QUANTITY")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(ML + 2*mm, tq_top - 11*mm, f"{total_qty:g}")

    c.setFont("Helvetica-Bold", 9)
    c.drawString(ML + tq_w + 8*mm, tq_top - 4*mm, "Notes / Remarks :")
    c.setFont("Helvetica", 8.5)
    note_lines = textwrap.wrap(str(notes or ""), 60)[:2]
    ny = tq_top - 9*mm
    for nl in note_lines:
        c.drawString(ML + tq_w + 8*mm, ny, nl)
        ny -= 4.5*mm
    c.line(ML + tq_w + 8*mm, tq_top - 4.5*mm, MR, tq_top - 4.5*mm)

    # ---------- RECEIVER CONFIRMATION ----------
    rc_top = tq_top - tq_h - 5*mm
    c.setFillColor(NAVY)
    c.rect(ML, rc_top - 6*mm, 55*mm, 6*mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(ML + 3*mm, rc_top - 4.2*mm, "RECEIVER CONFIRMATION")
    c.setFillColor(colors.black)
    c.setLineWidth(lw)
    c.rect(ML, rc_top - 6*mm - 10*mm, MR - ML, 10*mm)
    c.setFont("Helvetica", 8.5)
    c.drawString(ML + 3*mm, rc_top - 6*mm - 6*mm,
                 "We hereby acknowledge the receipt of the above goods in good condition.")

    # ---------- SIGNATURE BLOCKS ----------
    sig_top = rc_top - 6*mm - 10*mm - 6*mm
    col_w = (MR - ML) / 3
    for i, lbl in enumerate(["DELIVERED BY", "RECEIVED BY", "COMPANY STAMP"]):
        x0 = ML + i*col_w
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(x0 + col_w/2, sig_top, lbl)

    for i in range(2):
        x0 = ML + i*col_w
        field_y = sig_top - 7*mm
        for fl in ["Name", "Signature", "Date & Time"]:
            c.setFont("Helvetica", 8.5)
            c.drawString(x0 + 2*mm, field_y, fl + " :")
            c.line(x0 + 22*mm, field_y - 0.5*mm, x0 + col_w - 4*mm, field_y - 0.5*mm)
            field_y -= 7*mm

    stamp_x0 = ML + 2*col_w
    c.setDash(2, 2)
    c.rect(stamp_x0 + 6*mm, sig_top - 24*mm, col_w - 12*mm, 18*mm)
    c.setDash()

    # ---------- THANK YOU — hamesha signature block k theek neeche ----------
    thanks_y = min(sig_top - 30*mm, 12*mm)
    thanks_y = max(thanks_y, BOTTOM_MARGIN - 3*mm)
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(NAVY)
    c.drawCentredString(W/2, thanks_y, "Thank You For Your Business!")

    c.showPage()
    c.save()

# ---------- 7) API — pull an existing invoice's data to auto-fill the form ----------
#     IMPORTANT: aapke app mein invoice ka asal data CSV files (INVOICES,
#     LINES) mein save hota hai, SQLite "invoices" table mein nahi (kyunke
#     save_invoice_sqlite() kahin call nahi hoti). Is liye yahan pehle CSV
#     check karte hain (source of truth), aur agar wahan na mile to
#     SQLite ko bhi fallback k tor pe check kar lete hain (future-proof).
@app.route("/api/invoice_for_dn/<inv_no>")
@login_required
def api_invoice_for_dn(inv_no):
    inv_no = (inv_no or "").strip()
    try:
        customer, cust_addr, cust_phone = None, "", ""
        items = []

# ---- SQLite se dhoondo (ab yehi asal source of truth hai) ----
        with db_transaction() as _c:
            row = _c.execute(
                "SELECT customer, customer_address, customer_phone FROM invoices WHERE inv_no=?", (inv_no,)
            ).fetchone()
            if row:
                customer, cust_addr, cust_phone = row[0] or "", row[1] or "", row[2] or ""
                items = [
                    {"product": r[0], "qty": r[1]}
                    for r in _c.execute(
                        "SELECT product, SUM(qty) FROM invoice_items WHERE inv_no=? GROUP BY product", (inv_no,)
                    ).fetchall()
                ]

        if customer is None:
            return jsonify({"ok": False, "error": "Invoice number nahi mila."}), 404

        return jsonify({
            "ok": True,
            "customer": customer,
            "customer_address": cust_addr,
            "customer_phone": cust_phone,
            "items": items
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ---------- 8) CREATE — standalone ya invoice se auto-fill, dono ek hi form se ----------
@app.route("/delivery-note/new", methods=["GET", "POST"])
@login_required
def new_delivery_note():
    if request.method == "POST":
        try:
            dn_date   = request.form.get("date") or fmt_date(for_db=True)
            ref_no    = request.form.get("ref_no", "").strip()
            po_no     = request.form.get("po_no", "").strip()
            inv_no    = request.form.get("inv_no", "").strip()
            cust_name = request.form.get("cust_name", "").strip()
            cust_addr = request.form.get("cust_addr", "").strip()
            cust_phone= request.form.get("cust_phone", "").strip()
            notes     = request.form.get("notes", "").strip()

            # ---- Name / Address LAZMI ----
            if not cust_name:
                flash("Customer name is required.")
                return redirect(url_for("new_delivery_note"))
            if not cust_addr:
                flash("Address is required.")
                return redirect(url_for("new_delivery_note"))

            products_l = request.form.getlist("product[]")
            units_l    = request.form.getlist("unit[]")
            qtys_l     = request.form.getlist("qty[]")

            items = []
            for p, u, q in zip(products_l, units_l, qtys_l):
                p = (p or "").strip()
                if not p:
                    continue   # khali extendable row — ignore
                q = (q or "").strip()
                # ---- Product select ho to Qty LAZMI hai ----
                if q == "":
                    flash(f"Quantity is required for '{p}'.")
                    return redirect(url_for("new_delivery_note"))
                try:
                    qf = float(q)
                except Exception:
                    flash(f"Quantity for '{p}' is not a valid number.")
                    return redirect(url_for("new_delivery_note"))
                if qf <= 0:
                    flash(f"'{p}' ki Quantity 0 se zyada honi chahiye.")
                    return redirect(url_for("new_delivery_note"))
                items.append({"product": p, "unit": (u or "").strip(), "qty": qf})

            if not items:
                flash("Kam az kam 1 product line required hai.")
                return redirect(url_for("new_delivery_note"))

            # ---- Duplicate product — MERGE nahi, seedha REJECT ----
            dup = _find_duplicate_product(items)
            if dup:
                flash(f"'{dup}' is already in the list — each product can only appear in one row (duplicates not allowed).")
                return redirect(url_for("new_delivery_note"))

            if request.form.get("save_company_info") == "1":
                set_setting("company_address", request.form.get("company_address", "").strip())
                set_setting("company_phone", request.form.get("company_phone", "").strip())
                set_setting("company_email", request.form.get("company_email", "").strip())
                set_setting("company_tagline", request.form.get("company_tagline", "").strip())

            dn_no = next_dn_no()
            dn = {
                "dn_no": dn_no, "date": dn_date, "ref_no": ref_no, "po_no": po_no,
                "inv_no": inv_no, "customer": cust_name, "customer_address": cust_addr,
                "customer_phone": cust_phone, "notes": notes
            }
            ok, err = save_delivery_note_sqlite(dn, items)
            if not ok:
                flash(f"Delivery Note could not be saved: {err}")
                return redirect(url_for("new_delivery_note"))

            flash(f"Delivery Note {dn_no} created successfully")
            return redirect(url_for("delivery_note_pdf", dn_no=dn_no))
        except Exception as e:
            flash(f"Error: {e}")
            return redirect(url_for("new_delivery_note"))

    prods = load_products()
    custs = load_customers()
    prefill_inv = request.args.get("from_invoice", "").strip()

    html = TPL_H + """
<style>
  #itemsTbl{border-collapse:collapse;width:100%}
  #itemsTbl th,#itemsTbl td{border:1px solid var(--border);padding:6px 8px}
  #itemsTbl thead th{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff}
  #itemsTbl td input,#itemsTbl td select{border:1px solid var(--input-border);width:100%}
  .req-star{color:#dc2626}
</style>
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Delivery Note</div>
    <h2>🚚 New Delivery Note</h2>
    <p>Invoice se auto-fill karo, ya bilkul standalone bana lo.</p>
  </div>
  <a href="{{url_for('delivery_notes_list')}}" class="btn btn-outline">📋 All Delivery Notes</a>
</div>

<form method="POST" id="dnForm">
<datalist id="dn_cust_names">{% for c in custs %}<option value="{{c.name}}">{% endfor %}</datalist>
<datalist id="dn_cust_addr">{% for c in custs %}<option value="{{c.address}}">{% endfor %}</datalist>
<div class="card mb-3">
  <h3>Link se Invoice (Optional)</h3>
  <div class="form-row form-row-3">
    <div class="form-group">
      <label class="form-label">Invoice #</label>
      <input type="text" class="form-control" id="inv_no" name="inv_no" value="{{prefill_inv}}" placeholder="e.g. 2026-101">
    </div>
    <div class="form-group" style="align-self:flex-end">
      <button type="button" class="btn btn-primary" onclick="loadFromInvoice()">⬇️ Load From Invoice</button>
    </div>
  </div>
  <div id="loadMsg" class="text-muted" style="font-size:12.5px"></div>
</div>

<div class="card mb-3">
  <h3>Delivery Details</h3>
  <div class="form-row form-row-4">
    <div class="form-group">
      <label class="form-label">Delivery No. (preview)</label>
      <input type="text" class="form-control" value="{{dn_preview}}" disabled>
    </div>
    <div class="form-group">
      <label class="form-label">Date</label>
      <input type="date" class="form-control" name="date" value="{{today_db}}">
    </div>
    <div class="form-group">
      <label class="form-label">Reference No.</label>
      <input type="text" class="form-control" name="ref_no">
    </div>
    <div class="form-group">
      <label class="form-label">PO / Order No.</label>
      <input type="text" class="form-control" name="po_no">
    </div>
  </div>
</div>

<div class="card mb-3">
  <h3>Deliver To</h3>
  <div class="form-row form-row-3">
    <div class="form-group">
      <label class="form-label">Customer / Shop Name <span class="req-star">*</span></label>
      <input type="text" class="form-control" id="cust_name" name="cust_name" list="dn_cust_names" required>
    </div>
    <div class="form-group">
      <label class="form-label">Address <span class="req-star">*</span></label>
      <input type="text" class="form-control" id="cust_addr" name="cust_addr" list="dn_cust_addr" required>
    </div>
    <div class="form-group">
      <label class="form-label">Phone / Mobile</label>
      <input type="text" class="form-control" id="cust_phone" name="cust_phone">
    </div>
  </div>
</div>

<div class="card mb-3">
  <h3>Items <span class="badge badge-blue" id="totalQtyBadge">Total Qty: 0</span>
    <span class="text-muted" style="font-size:11px;font-weight:400">(last row mein type karte hi nayi row khud ban jayegi · duplicate product allow nahi · qty lazmi)</span>
  </h3>
  <datalist id="prod_list">
    {% for p in prods %}<option value="{{p.name}}">{% endfor %}
  </datalist>
  <div class="table-wrap">
    <table id="itemsTbl">
      <thead><tr><th style="width:40px">#</th><th>Product Name</th><th style="width:120px">Unit</th><th style="width:110px">Quantity <span class="req-star">*</span></th><th style="width:40px"></th></tr></thead>
      <tbody id="itemsBody"></tbody>
    </table>
  </div>
  <button type="button" class="btn btn-secondary mt-2" onclick="addRow()">➕ Add Row</button>
</div>

<div class="card mb-3">
  <h3>Notes / Remarks</h3>
  <textarea class="form-control" name="notes" rows="2"></textarea>
</div>

<div class="card mb-3">
  <h3>Company Info on Print <span class="text-muted" style="font-size:11px;font-weight:400">(sab optional hain — khali chor do to print pe nahi aayenge)</span></h3>
  <div class="form-row form-row-4">
    <div class="form-group">
      <label class="form-label">Address</label>
      <input type="text" class="form-control" name="company_address" value="{{company_address}}">
    </div>
    <div class="form-group">
      <label class="form-label">Phone</label>
      <input type="text" class="form-control" name="company_phone" value="{{company_phone}}">
    </div>
    <div class="form-group">
      <label class="form-label">Email</label>
      <input type="text" class="form-control" name="company_email" value="{{company_email}}">
    </div>
    <div class="form-group">
      <label class="form-label">Tagline</label>
      <input type="text" class="form-control" name="company_tagline" value="{{company_tagline}}" placeholder="e.g. QUALITY YOU CAN TRUST">
    </div>
  </div>
  <label style="font-size:12.5px;display:flex;gap:6px;align-items:center">
    <input type="checkbox" name="save_company_info" value="1" checked> Yeh info default ke tor pe save kar do
  </label>
</div>

<button type="submit" class="btn btn-primary btn-lg">💾 Save &amp; Generate PDF</button>
</form>

<script>
let rowCount = 0;
const DN_CUSTOMERS = {{ custs|tojson }};

// Customer Name select/type karte hi (agar exact match mila) Address+Phone khud bhar do
function tryAutofillCustomer(){
  const val = document.getElementById('cust_name').value.trim().toLowerCase();
  if(!val) return;
  const match = DN_CUSTOMERS.find(c => (c.name||'').trim().toLowerCase() === val);
  if(match){
    document.getElementById('cust_addr').value = match.address || '';
    if(match.phone) document.getElementById('cust_phone').value = match.phone;
  }
}
document.getElementById('cust_name').addEventListener('change', tryAutofillCustomer);

function addRow(product, unit, qty){
  rowCount++;
  const tb = document.getElementById('itemsBody');
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td>${rowCount}</td>
    <td><input type="text" class="form-control" list="prod_list" name="product[]" value="${product||''}"></td>
    <td>
      <select class="form-control" name="unit[]">
        <option value="" ${(!unit)?'selected':''}>-- Unit --</option>
        <option value="Carton" ${unit==='Carton'?'selected':''}>Carton</option>
        <option value="Piece" ${unit==='Piece'?'selected':''}>Piece</option>
        <option value="Box" ${unit==='Box'?'selected':''}>Box</option>
        <option value="Kg" ${unit==='Kg'?'selected':''}>Kg</option>
      </select>
    </td>
    <td><input type="number" step="any" class="form-control qtyInput" name="qty[]" value="${qty||''}" oninput="calcTotal()"></td>
    <td><button type="button" class="btn btn-danger btn-sm" onclick="this.closest('tr').remove(); calcTotal();">✕</button></td>
  `;
  tb.appendChild(tr);
  const prodInput = tr.querySelector('input[name="product[]"]');
  prodInput.addEventListener('input', function(){ autoExtend(tr); });
  prodInput.addEventListener('change', function(){ checkDuplicateProduct(this); });
  const qtyInput = tr.querySelector('.qtyInput');
  qtyInput.addEventListener('input', function(){ autoExtend(tr); calcTotal(); });
  return tr;
}

// ---- Duplicate product select hote hi rok do (merge nahi karte) ----
function checkDuplicateProduct(input){
  const val = input.value.trim().toLowerCase();
  if(!val) return;
  const allInputs = document.querySelectorAll('input[name="product[]"]');
  let count = 0;
  allInputs.forEach(i => { if(i.value.trim().toLowerCase() === val) count++; });
  if(count > 1){
    alert('⚠️ "' + input.value.trim() + '" pehle se list mein add hai.\\nEk product sirf ek hi row mein aa sakta hai — duplicate allow nahi.');
    input.value = '';
    input.focus();
  }
}

// ---- Aakhri row mein type karte hi khud nayi khali row ban jaye ----
function autoExtend(tr){
  const tb = document.getElementById('itemsBody');
  if(tr === tb.lastElementChild){
    const prodVal = tr.querySelector('input[name="product[]"]').value.trim();
    const qtyVal = tr.querySelector('.qtyInput').value.trim();
    if(prodVal !== '' || qtyVal !== ''){
      addRow();
    }
  }
}

function calcTotal(){
  let t = 0;
  document.querySelectorAll('.qtyInput').forEach(i => t += (parseFloat(i.value)||0));
  document.getElementById('totalQtyBadge').innerText = 'Total Qty: ' + t;
}

function loadFromInvoice(){
  const inv = document.getElementById('inv_no').value.trim();
  const msg = document.getElementById('loadMsg');
  if(!inv){ msg.innerText = 'Invoice # likho pehle.'; return; }
  msg.innerText = 'Loading...';
  fetch('/api/invoice_for_dn/' + encodeURIComponent(inv))
    .then(r => r.json())
    .then(d => {
      if(!d.ok){ msg.innerText = '❌ ' + d.error; return; }
      // ===== NAME CONFIRMATION — overwrite se pehle confirm dialog =====
      const ok = confirm(
        "Invoice #" + inv + "\\n" +
        "Customer: " + (d.customer || "-") + "\\n" +
        "Address: " + (d.customer_address || "-") + "\\n\\n" +
        "Is data se form fill karna hai? Maujooda list REPLACE ho jayegi."
      );
      if(!ok){ msg.innerText = 'Cancel kar diya — purana data waisa hi hai.'; return; }

      document.getElementById('cust_name').value = d.customer;
      document.getElementById('cust_addr').value = d.customer_address;
      document.getElementById('cust_phone').value = d.customer_phone;
      document.getElementById('itemsBody').innerHTML = '';
      rowCount = 0;
      d.items.forEach(it => addRow(it.product, '', it.qty));  // unit khali — user khud chunay ga
      addRow(); // aakhir mein ek khali extendable row
      calcTotal();
      msg.innerText = '✅ Loaded: ' + d.items.length + ' items (' + d.customer + '). Har row ki Unit khud select karo.';
    })
    .catch(e => { msg.innerText = '❌ ' + e; });
}

// ---- Submit se pehle final validation (name/address/qty/duplicate) ----
document.getElementById('dnForm').addEventListener('submit', function(e){
  const custName = document.getElementById('cust_name').value.trim();
  const custAddr = document.getElementById('cust_addr').value.trim();
  if(!custName){ alert('Customer name is required.'); e.preventDefault(); return; }
  if(!custAddr){ alert('Address is required.'); e.preventDefault(); return; }

  const rows = document.querySelectorAll('#itemsBody tr');
  const seen = new Set();
  let errorMsg = '';
  let filledCount = 0;

  rows.forEach(tr => {
    const prod = tr.querySelector('input[name="product[]"]').value.trim();
    const qty = tr.querySelector('.qtyInput').value.trim();
    if(!prod) return; // khali extendable row — ignore
    filledCount++;
    const key = prod.toLowerCase();
    if(seen.has(key) && !errorMsg){
      errorMsg = '"' + prod + '" duplicate hai — ek product sirf 1 row mein aa sakta hai.';
    }
    seen.add(key);
    if((qty === '' || parseFloat(qty) <= 0) && !errorMsg){
      errorMsg = '"' + prod + '" requires a quantity (greater than 0).';
    }
  });

  if(filledCount === 0){ errorMsg = 'Kam az kam 1 product add karo.'; }

  if(errorMsg){ alert('⚠️ ' + errorMsg); e.preventDefault(); return; }
});

// page load pe kam se kam 1 khali row
addRow();
{% if prefill_inv %}
document.getElementById('inv_no').value = "{{prefill_inv}}";
loadFromInvoice();
{% endif %}
</script>
""" + TPL_F
    return render_template_string(
        html, project=get_setting("project_name"), prods=prods, custs=custs,
        today_db=fmt_date(for_db=True), dn_preview=next_dn_no(), prefill_inv=prefill_inv,
        company_address=get_setting("company_address", ""),
        company_phone=get_setting("company_phone", ""),
        company_email=get_setting("company_email", ""),
        company_tagline=get_setting("company_tagline", "")
    )

# ---------- 9) LIST ----------
@app.route("/delivery-notes")
@login_required
def delivery_notes_list():
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT dn_no,date,customer,inv_no,total_qty,status FROM delivery_notes ORDER BY rowid DESC LIMIT 300")
        rows = c.fetchall()
    finally:
        conn.close()

    html = TPL_H + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Delivery Notes</div>
    <h2>🚚 All Delivery Notes</h2>
  </div>
  <a href="{{url_for('new_delivery_note')}}" class="btn btn-primary">➕ New Delivery Note</a>
</div>
<div class="card">
  <div class="table-wrap">
    <table>
      <thead><tr><th>DN No.</th><th>Date</th><th>Customer</th><th>Invoice #</th><th>Total Qty</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>
        {% for r in rows %}
        <tr>
          <td class="fw-bold">{{r[0]}}</td>
          <td>{{r[1]}}</td>
          <td>{{r[2]}}</td>
          <td>{{r[3] or '-'}}</td>
          <td>{{r[4]}}</td>
          <td><span class="badge badge-green">{{r[5]}}</span></td>
          <td>
            <a href="{{url_for('delivery_note_pdf', dn_no=r[0])}}" class="btn btn-outline btn-sm" target="_blank">📄 PDF</a>
            <a href="{{url_for('delete_delivery_note', dn_no=r[0])}}" class="btn btn-danger btn-sm" onclick="return confirm('Delete karna hai?')">🗑️</a>
          </td>
        </tr>
        {% endfor %}
        {% if not rows %}<tr><td colspan="7" class="text-center text-muted">Koi Delivery Note nahi</td></tr>{% endif %}
      </tbody>
    </table>
  </div>
</div>
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), rows=rows)

# ---------- 10) PDF VIEW (generated on-the-fly from DB — no disk-path issues) ----------
@app.route("/delivery-note/pdf/<dn_no>")
@login_required
def delivery_note_pdf(dn_no):
    dn, items = load_delivery_note(dn_no)
    if not dn:
        flash("Delivery Note not found.")
        return redirect(url_for("delivery_notes_list"))

    buf = io.BytesIO()
    draw_delivery_note_pdf(
        buf,
        company=get_setting("company_name", "COMPANY NAME"),
        address=get_setting("company_address", ""),
        phone=get_setting("company_phone", ""),
        email=get_setting("company_email", ""),
        tagline=get_setting("company_tagline", ""),
        logo_path=get_setting("logo_path", ""),
        show_logo=get_setting("logo_show", "1") == "1",
        dn_no=dn["dn_no"], date_str=dn["date"], ref_no=dn["ref_no"], po_no=dn["po_no"],
        cust_name=dn["customer"], cust_addr=dn["customer_address"], cust_phone=dn["customer_phone"],
        items=items, notes=dn["notes"]
    )
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf",
                      as_attachment=False,
                      download_name=f"DeliveryNote_{dn_no}.pdf")

# ---------- 11) DELETE (7-day time-locked, same rule as invoices) ----------
@app.route("/delivery-note/delete/<dn_no>")
@login_required
def delete_delivery_note(dn_no):
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT date FROM delivery_notes WHERE dn_no=?", (dn_no,))
        row = c.fetchone()
        if not row:
            flash("Delivery Note not found.")
            return redirect(url_for("delivery_notes_list"))
        # Date limit hata di gayi — ab kabhi bhi delete ho sakta hai
        c.execute("DELETE FROM delivery_note_items WHERE dn_no=?", (dn_no,))
        c.execute("DELETE FROM delivery_notes WHERE dn_no=?", (dn_no,))
        conn.commit()
        flash(f"Delivery Note {dn_no} deleted successfully.")
    except Exception as e:
        conn.rollback()
        flash(f"Delete error: {e}")
    finally:
        conn.close()
    return redirect(url_for("delivery_notes_list"))

# ======================================================================
# ====================  DELIVERY NOTE MODULE — END  ====================
# ====================  DELIVERY NOTE MODULE — END  ====================
# ======================================================================
# ===========  FACTORY MODULE: Raw Material + Purchase + Production ====
# ===========  v2 — Monthly Foldable Grouping + Auto Totals          ====
# ===========  (SQLite, self-contained, single-paste)               ====
# ======================================================================
# v2 mein naya: Purchases aur Production list ab MAHINE (month) k
# hisab se foldable <details> sections mein group hoti hai, har section
# ka total (cost/qty/cartons) khud calculate hota hai. Factory Dashboard
# mein "Aaj" k sath "Is Mahine" k tiles bhi khud calculate ho k aate hain.
# PASTE LOCATION: is poore block ko file k END mein, is line k UOPER
# paste karo:
#     if __name__ == "__main__":
# Agar Delivery Note module bhi wahan paste hai to koi masla nahi —
# dono ek hi jagah, ek k neeche ek paste ho sakte hain. Bas EK jaga
# paste karna hai, kahi aur kuch chairna nahi.
#
# Design (aapke diye hue Minimal Structure k mutabiq):
#   1) Raw Material   — Name / Unit / Purchase Price / Current Stock / Min Stock
#   2) Purchase Entry  — stock khud badhta hai, Purchase Price "Latest Price"
#      tareeqe se update hoti hai (jo aapne confirm kiya)
#   3) Production      — Raw Material select karo, qty do, Output Cartons +
#      Extra Pieces do -> khud Material Cost, Cost/Carton, Cost/Piece nikalta
#      hai, Raw Material stock khud kam karta hai. "Load Last Recipe" se
#      pehle wali production ka data (materials + qty + pieces/carton)
#      auto-fill ho jata hai — is liye alag Recipe screen ki zaroorat nahi.
#   4) Factory Dashboard — Low Stock, Today's Purchase/Production/Sales/
#      Expenses/Profit
#
# Har save/delete try/except + conn.rollback() k saath hai.
# ======================================================================

# ---------- 1) TABLES ----------
def init_factory_tables():
    try:
        conn = db()
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS raw_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            unit TEXT,
            purchase_price REAL DEFAULT 0,
            current_stock REAL DEFAULT 0,
            min_stock REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS purchase_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            supplier TEXT,
            material_id INTEGER,
            material_name TEXT,
            qty REAL DEFAULT 0,
            purchase_price REAL DEFAULT 0,
            total_cost REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(material_id) REFERENCES raw_materials(id)
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS productions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            product_name TEXT NOT NULL,
            size_pack TEXT,
            pieces_per_carton REAL DEFAULT 0,
            output_cartons REAL DEFAULT 0,
            extra_pieces REAL DEFAULT 0,
            material_cost REAL DEFAULT 0,
            cost_per_carton REAL DEFAULT 0,
            cost_per_piece REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS production_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            production_id INTEGER,
            material_id INTEGER,
            material_name TEXT,
            qty REAL DEFAULT 0,
            unit_price REAL DEFAULT 0,
            line_cost REAL DEFAULT 0,
            FOREIGN KEY(production_id) REFERENCES productions(id) ON DELETE CASCADE,
            FOREIGN KEY(material_id) REFERENCES raw_materials(id)
        )
        """)
        conn.commit()
        print("✅ Factory tables ready (raw_materials / purchase_entries / productions)")
    except Exception as e:
        conn.rollback()
        print("❌ Factory DB Error:", e)
    finally:
        conn.close()

init_factory_tables()

# ---------- 2) SMALL HELPERS ----------
def _parse_any_date(s):
    """App mein date kabhi ISO (YYYY-MM-DD) kabhi dd-mm-yyyy save hoti hai — dono handle karo."""
    s = (s or "").strip()
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.datetime.strptime(s, f).date()
        except Exception:
            continue
    return None

def _is_today(date_str):
    d = _parse_any_date(date_str)
    return d == datetime.date.today() if d else False

def _month_of(date_str):
    """'2026-07-18' ya '18-07-2026' -> '2026-07' (foldable monthly grouping k liye)"""
    d = _parse_any_date(date_str)
    return d.strftime("%Y-%m") if d else "Unknown"

def _is_this_month(date_str):
    return _month_of(date_str) == datetime.date.today().strftime("%Y-%m")

def _group_by_month(rows, date_key):
    """rows ko month (naye se purane) k hisab se group karo — foldable UI k liye.
       Return: [ (month_label, [rows...]) , ... ] descending order."""
    groups = {}
    for r in rows:
        m = _month_of(r[date_key])
        groups.setdefault(m, []).append(r)
    return sorted(groups.items(), key=lambda kv: kv[0], reverse=True)

def _month_label(ym):
    try:
        d = datetime.datetime.strptime(ym, "%Y-%m")
        return d.strftime("%B %Y")   # e.g. "July 2026"
    except Exception:
        return ym

def load_raw_materials():
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT id,name,unit,purchase_price,current_stock,min_stock FROM raw_materials ORDER BY name")
        return [{
            "id": r[0], "name": r[1], "unit": r[2] or "",
            "purchase_price": r[3] or 0, "current_stock": r[4] or 0, "min_stock": r[5] or 0
        } for r in c.fetchall()]
    finally:
        conn.close()

def _distinct_suppliers():
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT supplier FROM purchase_entries WHERE supplier IS NOT NULL AND supplier<>'' ORDER BY supplier")
        return [r[0] for r in c.fetchall()]
    finally:
        conn.close()

def _distinct_production_products():
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT product_name FROM productions ORDER BY product_name")
        return [r[0] for r in c.fetchall()]
    finally:
        conn.close()

FACTORY_STYLE = """
<style>
  .fx-tbl{border-collapse:collapse;width:100%}
  .fx-tbl th,.fx-tbl td{border:1px solid var(--border);padding:6px 8px}
  .fx-tbl thead th{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff}
  .fx-tbl td input,.fx-tbl td select{border:1px solid var(--input-border);width:100%}
  .req-star{color:#dc2626}
  .fx-warn{background:#fef2f2;color:#991b1b;border:1px solid #fecaca;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:13px}
  .fx-tile{background:var(--card-bg,#fff);border:1px solid var(--border);border-radius:12px;padding:16px;flex:1;min-width:160px}
  .fx-tile h4{margin:0 0 6px;font-size:12.5px;color:var(--text-muted,#666);font-weight:600}
  .fx-tile .val{font-size:22px;font-weight:800}
  .fx-grid{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px}
</style>
"""

# ======================================================================
# ==========================  RAW MATERIAL  =============================
# ======================================================================
@app.route("/raw-materials", methods=["GET", "POST"])
@login_required
def raw_materials_page():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        unit = request.form.get("unit", "").strip()
        try:
            price = float(request.form.get("purchase_price") or 0)
            stock = float(request.form.get("current_stock") or 0)
            min_stock = float(request.form.get("min_stock") or 0)
        except Exception:
            flash("Price / Stock mein sahi number likho.")
            return redirect(url_for("raw_materials_page"))

        if not name:
            flash("Material Name likhna zaroori hai.")
            return redirect(url_for("raw_materials_page"))

        conn = db()
        try:
            c = conn.cursor()
            c.execute("""INSERT INTO raw_materials (name, unit, purchase_price, current_stock, min_stock)
                         VALUES (?,?,?,?,?)""", (name, unit, price, stock, min_stock))
            conn.commit()
            flash(f"✅ Raw Material '{name}' add ho gaya.")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash(f"⚠️ '{name}' pehle se maujood hai — naya nahi bana, chahe to Edit karo.")
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}")
        finally:
            conn.close()
        return redirect(url_for("raw_materials_page"))

    materials = load_raw_materials()
    html = TPL_H + FACTORY_STYLE + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Raw Material</div>
    <h2>🧱 Raw Material</h2>
    <p>Sirf ek baar har material bana do, phir Purchase/Production mein use hota rahega.</p>
  </div>
  <div style="display:flex;gap:8px">
    <a href="{{url_for('new_purchase')}}" class="btn btn-outline">🛒 Purchase Entry</a>
    <a href="{{url_for('new_production')}}" class="btn btn-outline">🏭 Production</a>
    <a href="{{url_for('factory_dashboard')}}" class="btn btn-primary">📊 Factory Dashboard</a>
  </div>
</div>

<div class="card mb-3">
  <h3>➕ Naya Raw Material</h3>
  <form method="POST">
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Material Name <span class="req-star">*</span></label>
        <input type="text" class="form-control" name="name" required>
      </div>
      <div class="form-group">
        <label class="form-label">Unit</label>
        <input type="text" class="form-control" name="unit" placeholder="kg / ltr / pcs">
      </div>
      <div class="form-group">
        <label class="form-label">Purchase Price</label>
        <input type="number" step="any" class="form-control" name="purchase_price" value="0">
      </div>
      <div class="form-group">
        <label class="form-label">Current Stock</label>
        <input type="number" step="any" class="form-control" name="current_stock" value="0">
      </div>
    </div>
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Minimum Stock (Low Stock Alert)</label>
        <input type="number" step="any" class="form-control" name="min_stock" value="0">
      </div>
    </div>
    <button type="submit" class="btn btn-primary">💾 Save</button>
  </form>
</div>

<div class="card">
  <h3>Sab Raw Materials</h3>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Unit</th><th>Purchase Price</th><th>Current Stock</th><th>Min Stock</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>
        {% for m in materials %}
        <tr>
          <td class="fw-bold">{{m.name}}</td>
          <td>{{m.unit}}</td>
          <td>Rs {{ "%.2f"|format(m.purchase_price) }}</td>
          <td>{{ "%.2f"|format(m.current_stock) }}</td>
          <td>{{ "%.2f"|format(m.min_stock) }}</td>
          <td>
            {% if m.min_stock > 0 and m.current_stock <= m.min_stock %}
              <span class="badge badge-red">⚠️ Low Stock</span>
            {% else %}
              <span class="badge badge-green">OK</span>
            {% endif %}
          </td>
          <td>
            <a href="{{url_for('edit_raw_material', rid=m.id)}}" class="btn btn-outline btn-sm">✏️ Edit</a>
            <a href="{{url_for('delete_raw_material', rid=m.id)}}" class="btn btn-danger btn-sm" onclick="return confirm('Delete karna hai?')">🗑️</a>
          </td>
        </tr>
        {% endfor %}
        {% if not materials %}<tr><td colspan="7" class="text-center text-muted">Koi Raw Material nahi — upar se add karo</td></tr>{% endif %}
      </tbody>
    </table>
  </div>
</div>
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), materials=materials)


@app.route("/raw-material/edit/<int:rid>", methods=["GET", "POST"])
@login_required
def edit_raw_material(rid):
    conn = db()
    try:
        c = conn.cursor()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            unit = request.form.get("unit", "").strip()
            try:
                price = float(request.form.get("purchase_price") or 0)
                stock = float(request.form.get("current_stock") or 0)
                min_stock = float(request.form.get("min_stock") or 0)
            except Exception:
                flash("Price / Stock mein sahi number likho.")
                return redirect(url_for("edit_raw_material", rid=rid))

            if not name:
                flash("Material Name likhna zaroori hai.")
                return redirect(url_for("edit_raw_material", rid=rid))
            try:
                c.execute("""UPDATE raw_materials SET name=?, unit=?, purchase_price=?, current_stock=?, min_stock=?
                             WHERE id=?""", (name, unit, price, stock, min_stock, rid))
                conn.commit()
                flash("✅ Update ho gaya.")
            except sqlite3.IntegrityError:
                conn.rollback()
                flash(f"⚠️ '{name}' naam se pehle se koi aur material maujood hai.")
                return redirect(url_for("edit_raw_material", rid=rid))
            except Exception as e:
                conn.rollback()
                flash(f"Error: {e}")
                return redirect(url_for("edit_raw_material", rid=rid))
            return redirect(url_for("raw_materials_page"))

        c.execute("SELECT id,name,unit,purchase_price,current_stock,min_stock FROM raw_materials WHERE id=?", (rid,))
        row = c.fetchone()
        if not row:
            flash("Material nahi mila.")
            return redirect(url_for("raw_materials_page"))
    finally:
        conn.close()

    m = {"id": row[0], "name": row[1], "unit": row[2] or "", "purchase_price": row[3] or 0,
         "current_stock": row[4] or 0, "min_stock": row[5] or 0}

    html = TPL_H + FACTORY_STYLE + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Raw Material / Edit</div>
    <h2>✏️ Edit Raw Material</h2>
  </div>
  <a href="{{url_for('raw_materials_page')}}" class="btn btn-outline">⬅ Back</a>
</div>
<div class="card">
  <form method="POST">
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Material Name <span class="req-star">*</span></label>
        <input type="text" class="form-control" name="name" value="{{m.name}}" required>
      </div>
      <div class="form-group">
        <label class="form-label">Unit</label>
        <input type="text" class="form-control" name="unit" value="{{m.unit}}">
      </div>
      <div class="form-group">
        <label class="form-label">Purchase Price</label>
        <input type="number" step="any" class="form-control" name="purchase_price" value="{{m.purchase_price}}">
      </div>
      <div class="form-group">
        <label class="form-label">Current Stock</label>
        <input type="number" step="any" class="form-control" name="current_stock" value="{{m.current_stock}}">
      </div>
    </div>
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Minimum Stock</label>
        <input type="number" step="any" class="form-control" name="min_stock" value="{{m.min_stock}}">
      </div>
    </div>
    <button type="submit" class="btn btn-primary">💾 Update</button>
  </form>
</div>
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), m=m)


@app.route("/raw-material/delete/<int:rid>")
@login_required
def delete_raw_material(rid):
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM purchase_entries WHERE material_id=?", (rid,))
        used_p = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM production_materials WHERE material_id=?", (rid,))
        used_pm = c.fetchone()[0]
        if used_p or used_pm:
            flash("⚠️ Yeh material Purchase/Production history mein use ho chuka hai — data integrity k liye delete nahi ho sakta.")
            return redirect(url_for("raw_materials_page"))
        c.execute("DELETE FROM raw_materials WHERE id=?", (rid,))
        conn.commit()
        flash("🗑️ Raw Material delete ho gaya.")
    except Exception as e:
        conn.rollback()
        flash(f"Delete error: {e}")
    finally:
        conn.close()
    return redirect(url_for("raw_materials_page"))


# ======================================================================
# ==========================  PURCHASE ENTRY  ===========================
# ======================================================================
@app.route("/purchase/new", methods=["GET", "POST"])
@login_required
def new_purchase():
    if request.method == "POST":
        p_date = request.form.get("date") or fmt_date(for_db=True)
        supplier = request.form.get("supplier", "").strip()
        material_id = request.form.get("material_id", "").strip()
        qty_s = request.form.get("qty", "").strip()
        price_s = request.form.get("purchase_price", "").strip()

        if not material_id:
            flash("Raw Material select karna zaroori hai.")
            return redirect(url_for("new_purchase"))
        try:
            mid = int(material_id)
        except Exception:
            flash("Material sahi select nahi hua.")
            return redirect(url_for("new_purchase"))
        if qty_s == "" or float(qty_s) <= 0:
            flash("Quantity 0 se zyada honi chahiye.")
            return redirect(url_for("new_purchase"))
        if price_s == "" or float(price_s) < 0:
            flash("Purchase Price sahi likho.")
            return redirect(url_for("new_purchase"))

        qf, pf = float(qty_s), float(price_s)

        conn = db()
        try:
            c = conn.cursor()
            c.execute("SELECT name FROM raw_materials WHERE id=?", (mid,))
            mrow = c.fetchone()
            if not mrow:
                conn.rollback()
                flash("Material nahi mila.")
                return redirect(url_for("new_purchase"))
            mname = mrow[0]
            total_cost = qf * pf
            c.execute("""INSERT INTO purchase_entries (date, supplier, material_id, material_name, qty, purchase_price, total_cost)
                         VALUES (?,?,?,?,?,?,?)""", (p_date, supplier, mid, mname, qf, pf, total_cost))
            # Stock += qty, Purchase Price = LATEST price (aapka confirmed tareeqa)
            c.execute("UPDATE raw_materials SET current_stock = current_stock + ?, purchase_price = ? WHERE id=?",
                      (qf, pf, mid))
            conn.commit()
            flash(f"✅ Purchase Entry save ho gayi — {mname}: stock +{qf:g}, price ab Rs {pf:,.2f}")
        except Exception as e:
            conn.rollback()
            flash(f"Save error: {e}")
        finally:
            conn.close()
        return redirect(url_for("purchases_list"))

    materials = load_raw_materials()
    suppliers = _distinct_suppliers()
    html = TPL_H + FACTORY_STYLE + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Purchase Entry</div>
    <h2>🛒 New Purchase Entry</h2>
    <p>Save karte hi Raw Material ka stock aur price khud update ho jayenge.</p>
  </div>
  <a href="{{url_for('purchases_list')}}" class="btn btn-outline">📋 All Purchases</a>
</div>

<datalist id="supplier_list">{% for s in suppliers %}<option value="{{s}}">{% endfor %}</datalist>

<div class="card">
  <form method="POST" id="purchForm">
    <div class="form-row form-row-4">
      <div class="form-group">
        <label class="form-label">Date</label>
        <input type="date" class="form-control" name="date" value="{{today_db}}">
      </div>
      <div class="form-group">
        <label class="form-label">Supplier</label>
        <input type="text" class="form-control" name="supplier" list="supplier_list">
      </div>
      <div class="form-group">
        <label class="form-label">Raw Material <span class="req-star">*</span></label>
        <select class="form-control" id="material_id" name="material_id" required onchange="fillMatInfo()">
          <option value="">-- Select --</option>
          {% for m in materials %}
          <option value="{{m.id}}" data-unit="{{m.unit}}" data-price="{{m.purchase_price}}" data-stock="{{m.current_stock}}">{{m.name}} ({{m.unit}})</option>
          {% endfor %}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Quantity <span class="req-star">*</span> <span id="unitLbl" class="text-muted"></span></label>
        <input type="number" step="any" class="form-control" name="qty" required>
      </div>
    </div>
    <div class="form-row form-row-3">
      <div class="form-group">
        <label class="form-label">Purchase Price (per unit) <span class="req-star">*</span></label>
        <input type="number" step="any" class="form-control" id="purchase_price" name="purchase_price" required>
      </div>
      <div class="form-group">
        <label class="form-label">Current Stock (is material ki)</label>
        <input type="text" class="form-control" id="curStockShow" disabled>
      </div>
    </div>
    {% if not materials %}
      <div class="fx-warn">⚠️ Pehle koi Raw Material banao (<a href="{{url_for('raw_materials_page')}}">yahan se</a>), phir Purchase Entry karo.</div>
    {% endif %}
    <button type="submit" class="btn btn-primary">💾 Save Purchase</button>
  </form>
</div>

<script>
function fillMatInfo(){
  const sel = document.getElementById('material_id');
  const opt = sel.options[sel.selectedIndex];
  if(!opt || !opt.value){ document.getElementById('unitLbl').innerText=''; document.getElementById('curStockShow').value=''; return; }
  document.getElementById('unitLbl').innerText = '(' + (opt.dataset.unit||'') + ')';
  document.getElementById('purchase_price').value = opt.dataset.price || 0;
  document.getElementById('curStockShow').value = (opt.dataset.stock || 0) + ' ' + (opt.dataset.unit||'');
}
</script>
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), materials=materials,
                                   suppliers=suppliers, today_db=fmt_date(for_db=True))


@app.route("/purchases")
@login_required
def purchases_list():
    conn = db()
    try:
        c = conn.cursor()
        c.execute("""SELECT id,date,supplier,material_name,qty,purchase_price,total_cost
                     FROM purchase_entries ORDER BY id DESC LIMIT 1000""")
        rows = [{"id":r[0],"date":r[1],"supplier":r[2],"material_name":r[3],
                  "qty":r[4],"purchase_price":r[5],"total_cost":r[6]} for r in c.fetchall()]
    finally:
        conn.close()

    # ---- Har MAHINE ka data alag (foldable group) — total khud calculate hota hai ----
    grouped = _group_by_month(rows, "date")
    month_blocks = []
    for ym, grows in grouped:
        month_blocks.append({
            "label": _month_label(ym),
            "rows": grows,
            "total_cost": sum(r["total_cost"] or 0 for r in grows),
            "total_qty": sum(r["qty"] or 0 for r in grows),
            "count": len(grows),
        })

    html = TPL_H + FACTORY_STYLE + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Purchases</div>
    <h2>🛒 All Purchase Entries</h2>
    <p>Har mahine ka data alag foldable section mein — total khud calculate hota hai.</p>
  </div>
  <a href="{{url_for('new_purchase')}}" class="btn btn-primary">➕ New Purchase</a>
</div>

{% for blk in month_blocks %}
<details class="card mb-3" {% if loop.first %}open{% endif %}>
  <summary style="cursor:pointer;font-weight:700;font-size:15px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>📅 {{blk.label}} <span class="text-muted" style="font-weight:400;font-size:12.5px">({{blk.count}} entries)</span></span>
    <span class="badge badge-blue">Total: Rs {{ "%.2f"|format(blk.total_cost) }} · Qty: {{ "%.2f"|format(blk.total_qty) }}</span>
  </summary>
  <div class="table-wrap mt-2">
    <table>
      <thead><tr><th>Date</th><th>Supplier</th><th>Material</th><th>Qty</th><th>Price/Unit</th><th>Total</th><th>Action</th></tr></thead>
      <tbody>
        {% for r in blk.rows %}
        <tr>
          <td>{{r.date}}</td><td>{{r.supplier or '-'}}</td><td class="fw-bold">{{r.material_name}}</td>
          <td>{{ "%.2f"|format(r.qty) }}</td><td>Rs {{ "%.2f"|format(r.purchase_price) }}</td>
          <td>Rs {{ "%.2f"|format(r.total_cost) }}</td>
          <td><a href="{{url_for('delete_purchase', pid=r.id)}}" class="btn btn-danger btn-sm" onclick="return confirm('Delete karna hai? Stock wapis ghat/badh jayega.')">🗑️</a></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</details>
{% endfor %}
{% if not month_blocks %}<div class="card text-center text-muted">Koi Purchase Entry nahi</div>{% endif %}
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), month_blocks=month_blocks)


@app.route("/purchase/delete/<int:pid>")
@login_required
def delete_purchase(pid):
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT material_id, qty FROM purchase_entries WHERE id=?", (pid,))
        row = c.fetchone()
        if not row:
            flash("Purchase entry nahi mili.")
            return redirect(url_for("purchases_list"))
        mid, qty = row
        # Stock wapis ghata do (reverse). Note: Price revert nahi hoti (Latest-Price model hai).
        c.execute("UPDATE raw_materials SET current_stock = current_stock - ? WHERE id=?", (qty, mid))
        c.execute("DELETE FROM purchase_entries WHERE id=?", (pid,))
        conn.commit()
        flash("🗑️ Purchase entry delete ho gayi, stock wapis adjust ho gaya.")
    except Exception as e:
        conn.rollback()
        flash(f"Delete error: {e}")
    finally:
        conn.close()
    return redirect(url_for("purchases_list"))


# ======================================================================
# =============================  PRODUCTION  =============================
# ======================================================================
@app.route("/api/last_recipe")
@login_required
def api_last_recipe():
    product_name = (request.args.get("product") or "").strip()
    if not product_name:
        return jsonify({"ok": False, "error": "Product name do."}), 400
    conn = db()
    try:
        c = conn.cursor()
        c.execute("""SELECT id, size_pack, pieces_per_carton FROM productions
                     WHERE lower(product_name)=? ORDER BY id DESC LIMIT 1""", (product_name.lower(),))
        row = c.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Is product ki pehle koi Production record nahi mila."}), 404
        pid, size_pack, ppc = row
        c.execute("SELECT material_id, material_name, qty FROM production_materials WHERE production_id=?", (pid,))
        materials = [{"material_id": r[0], "material_name": r[1], "qty": r[2]} for r in c.fetchall()]
        return jsonify({"ok": True, "size_pack": size_pack or "", "pieces_per_carton": ppc or 0, "materials": materials})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route("/production/new", methods=["GET", "POST"])
@login_required
def new_production():
    if request.method == "POST":
        p_date = request.form.get("date") or fmt_date(for_db=True)
        product_name = request.form.get("product_name", "").strip()
        size_pack = request.form.get("size_pack", "").strip()
        notes = request.form.get("notes", "").strip()

        if not product_name:
            flash("Product Name likhna zaroori hai.")
            return redirect(url_for("new_production"))

        try:
            ppc = float(request.form.get("pieces_per_carton") or 0)
            out_cartons = float(request.form.get("output_cartons") or 0)
            extra_pieces = float(request.form.get("extra_pieces") or 0)
        except Exception:
            flash("Cartons / Pieces mein sahi number likho.")
            return redirect(url_for("new_production"))

        if out_cartons <= 0 and extra_pieces <= 0:
            flash("Output Cartons ya Extra Pieces mein se koi ek zaroor bharo.")
            return redirect(url_for("new_production"))

        mat_ids = request.form.getlist("material_id[]")
        mat_qtys = request.form.getlist("material_qty[]")

        lines = []
        for mid_s, q_s in zip(mat_ids, mat_qtys):
            mid_s = (mid_s or "").strip()
            if not mid_s:
                continue
            q_s = (q_s or "").strip()
            if q_s == "" or float(q_s) <= 0:
                flash("Har select ki hui Raw Material ki Quantity 0 se zyada honi chahiye.")
                return redirect(url_for("new_production"))
            lines.append({"material_id": int(mid_s), "qty": float(q_s)})

        if not lines:
            flash("Kam az kam 1 Raw Material select karo.")
            return redirect(url_for("new_production"))

        mids = [l["material_id"] for l in lines]
        if len(mids) != len(set(mids)):
            flash("⚠️ Ek Raw Material sirf ek hi row mein select ho sakti hai — duplicate allow nahi.")
            return redirect(url_for("new_production"))

        conn = db()
        try:
            c = conn.cursor()
            material_cost = 0.0
            resolved = []
            low_stock_warns = []
            for l in lines:
                c.execute("SELECT name, purchase_price, current_stock, min_stock FROM raw_materials WHERE id=?", (l["material_id"],))
                mrow = c.fetchone()
                if not mrow:
                    raise Exception("Ek Raw Material record nahi mila.")
                mname, mprice, mstock, mminstock = mrow
                mprice = mprice or 0
                line_cost = l["qty"] * mprice
                material_cost += line_cost
                new_stock = (mstock or 0) - l["qty"]
                resolved.append({
                    "material_id": l["material_id"], "material_name": mname,
                    "qty": l["qty"], "unit_price": mprice, "line_cost": line_cost, "new_stock": new_stock
                })
                if new_stock <= (mminstock or 0):
                    low_stock_warns.append(f"{mname} ({new_stock:g})")

            total_pieces = out_cartons * ppc + extra_pieces
            cost_per_carton = (material_cost / out_cartons) if out_cartons > 0 else 0.0
            cost_per_piece = (material_cost / total_pieces) if total_pieces > 0 else 0.0

            c.execute("""INSERT INTO productions
                (date, product_name, size_pack, pieces_per_carton, output_cartons, extra_pieces,
                 material_cost, cost_per_carton, cost_per_piece, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (p_date, product_name, size_pack, ppc, out_cartons, extra_pieces,
                 material_cost, cost_per_carton, cost_per_piece, notes))
            production_id = c.lastrowid

            for r in resolved:
                c.execute("""INSERT INTO production_materials
                    (production_id, material_id, material_name, qty, unit_price, line_cost)
                    VALUES (?,?,?,?,?,?)""",
                    (production_id, r["material_id"], r["material_name"], r["qty"], r["unit_price"], r["line_cost"]))
                c.execute("UPDATE raw_materials SET current_stock=? WHERE id=?", (r["new_stock"], r["material_id"]))

            conn.commit()
            msg = f"✅ Production #{production_id} save ho gayi — Material Cost Rs {material_cost:,.2f}"
            if cost_per_carton:
                msg += f" | Cost/Carton Rs {cost_per_carton:,.2f}"
            if cost_per_piece:
                msg += f" | Cost/Piece Rs {cost_per_piece:,.2f}"
            flash(msg)
            if low_stock_warns:
                flash("⚠️ Low/negative stock ho gaya: " + ", ".join(low_stock_warns))
        except Exception as e:
            conn.rollback()
            flash(f"Save error: {e}")
            return redirect(url_for("new_production"))
        finally:
            conn.close()

        return redirect(url_for("productions_list"))

    materials = load_raw_materials()
    products_history = _distinct_production_products()
    html = TPL_H + FACTORY_STYLE + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Production</div>
    <h2>🏭 New Production</h2>
    <p>Product select karo — pehle kabhi banaya ho to "Load Last Recipe" se sab khud bhar jayega.</p>
  </div>
  <a href="{{url_for('productions_list')}}" class="btn btn-outline">📋 All Production</a>
</div>

<datalist id="product_hist">{% for p in products_history %}<option value="{{p}}">{% endfor %}</datalist>

<form method="POST" id="prodForm">
<div class="card mb-3">
  <div class="form-row form-row-4">
    <div class="form-group">
      <label class="form-label">Date</label>
      <input type="date" class="form-control" name="date" value="{{today_db}}">
    </div>
    <div class="form-group">
      <label class="form-label">Product Name <span class="req-star">*</span></label>
      <input type="text" class="form-control" id="product_name" name="product_name" list="product_hist" required>
    </div>
    <div class="form-group">
      <label class="form-label">Size / Pack</label>
      <input type="text" class="form-control" id="size_pack" name="size_pack" placeholder="e.g. 500ml">
    </div>
    <div class="form-group" style="align-self:flex-end">
      <button type="button" class="btn btn-primary" onclick="loadLastRecipe()">⬇️ Load Last Recipe</button>
    </div>
  </div>
  <div id="loadMsg" class="text-muted" style="font-size:12.5px"></div>
</div>

<div class="card mb-3">
  <h3>Raw Materials Used <span class="text-muted" style="font-size:11px;font-weight:400">(last row mein select karte hi nayi row khud ban jayegi · duplicate allow nahi)</span></h3>
  <div class="table-wrap">
    <table class="fx-tbl" id="matTbl">
      <thead><tr><th style="width:40px">#</th><th>Raw Material</th><th style="width:90px">Unit</th><th style="width:120px">Qty <span class="req-star">*</span></th><th style="width:100px">Stock</th><th style="width:40px"></th></tr></thead>
      <tbody id="matBody"></tbody>
    </table>
  </div>
</div>

<div class="card mb-3">
  <h3>Output</h3>
  <div class="form-row form-row-4">
    <div class="form-group">
      <label class="form-label">Pieces Per Carton</label>
      <input type="number" step="any" class="form-control" id="pieces_per_carton" name="pieces_per_carton" value="0">
    </div>
    <div class="form-group">
      <label class="form-label">Output Cartons</label>
      <input type="number" step="any" class="form-control" name="output_cartons" value="0">
    </div>
    <div class="form-group">
      <label class="form-label">Extra Pieces</label>
      <input type="number" step="any" class="form-control" name="extra_pieces" value="0">
    </div>
  </div>
</div>

<div class="card mb-3">
  <h3>Notes</h3>
  <textarea class="form-control" name="notes" rows="2"></textarea>
</div>

{% if not materials %}
  <div class="fx-warn">⚠️ Pehle koi Raw Material banao (<a href="{{url_for('raw_materials_page')}}">yahan se</a>), phir Production karo.</div>
{% endif %}

<button type="submit" class="btn btn-primary btn-lg">💾 Save Production</button>
</form>

<script>
const RAW_MATERIALS = {{ materials|tojson }};
let matRowCount = 0;

function materialOptions(selectedId){
  let opts = '<option value="">-- Select --</option>';
  RAW_MATERIALS.forEach(m => {
    const sel = (String(m.id) === String(selectedId)) ? 'selected' : '';
    opts += `<option value="${m.id}" data-unit="${m.unit}" data-stock="${m.current_stock}" ${sel}>${m.name}</option>`;
  });
  return opts;
}

function addMatRow(materialId, qty){
  matRowCount++;
  const tb = document.getElementById('matBody');
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td>${matRowCount}</td>
    <td><select class="form-control matSelect" name="material_id[]" onchange="onMatChange(this)">${materialOptions(materialId)}</select></td>
    <td class="matUnit">-</td>
    <td><input type="number" step="any" class="form-control qtyInput" name="material_qty[]" value="${qty||''}"></td>
    <td class="matStock">-</td>
    <td><button type="button" class="btn btn-danger btn-sm" onclick="this.closest('tr').remove();">✕</button></td>
  `;
  tb.appendChild(tr);
  const sel = tr.querySelector('.matSelect');
  const qtyInput = tr.querySelector('.qtyInput');
  sel.addEventListener('change', function(){ checkDupMaterial(this); autoExtendMat(tr); });
  qtyInput.addEventListener('input', function(){ autoExtendMat(tr); });
  if(materialId){ onMatChange(sel); }
  return tr;
}

function onMatChange(sel){
  const tr = sel.closest('tr');
  const opt = sel.options[sel.selectedIndex];
  tr.querySelector('.matUnit').innerText = opt && opt.value ? (opt.dataset.unit || '-') : '-';
  tr.querySelector('.matStock').innerText = opt && opt.value ? (opt.dataset.stock || '0') : '-';
}

function checkDupMaterial(sel){
  const val = sel.value;
  if(!val) return;
  const all = document.querySelectorAll('.matSelect');
  let count = 0;
  all.forEach(s => { if(s.value === val) count++; });
  if(count > 1){
    alert('⚠️ Yeh Raw Material pehle se ek row mein select hai. Ek material sirf ek hi row mein aa sakta hai.');
    sel.value = '';
    onMatChange(sel);
  }
}

function autoExtendMat(tr){
  const tb = document.getElementById('matBody');
  if(tr === tb.lastElementChild){
    const selVal = tr.querySelector('.matSelect').value;
    const qtyVal = tr.querySelector('.qtyInput').value.trim();
    if(selVal !== '' || qtyVal !== ''){
      addMatRow();
    }
  }
}

function loadLastRecipe(){
  const prod = document.getElementById('product_name').value.trim();
  const msg = document.getElementById('loadMsg');
  if(!prod){ msg.innerText = 'Product Name likho pehle.'; return; }
  msg.innerText = 'Loading...';
  fetch('/api/last_recipe?product=' + encodeURIComponent(prod))
    .then(r => r.json())
    .then(d => {
      if(!d.ok){ msg.innerText = 'ℹ️ ' + d.error; return; }
      const ok = confirm(
        'Product: ' + prod + '\\n' +
        'Pichli Production mein ' + d.materials.length + ' Raw Material use hue the.\\n\\n' +
        'Wahi data (materials + quantities + pieces/carton) load karke form fill karna hai? Maujooda list REPLACE ho jayegi.'
      );
      if(!ok){ msg.innerText = 'Cancel kar diya.'; return; }

      document.getElementById('size_pack').value = d.size_pack || '';
      document.getElementById('pieces_per_carton').value = d.pieces_per_carton || 0;
      document.getElementById('matBody').innerHTML = '';
      matRowCount = 0;
      d.materials.forEach(m => addMatRow(m.material_id, m.qty));
      addMatRow();
      msg.innerText = '✅ Last recipe load ho gayi — quantities check/edit kar lo.';
    })
    .catch(e => { msg.innerText = '❌ ' + e; });
}

// submit se pehle final check
document.getElementById('prodForm').addEventListener('submit', function(e){
  const rows = document.querySelectorAll('#matBody tr');
  const seen = new Set();
  let errorMsg = '';
  let filled = 0;
  rows.forEach(tr => {
    const sel = tr.querySelector('.matSelect').value;
    const qty = tr.querySelector('.qtyInput').value.trim();
    if(!sel) return;
    filled++;
    if(seen.has(sel) && !errorMsg){ errorMsg = 'Ek Raw Material duplicate select hai.'; }
    seen.add(sel);
    if((qty === '' || parseFloat(qty) <= 0) && !errorMsg){ errorMsg = 'Har select ki hui Material ki Quantity 0 se zyada honi chahiye.'; }
  });
  if(filled === 0){ errorMsg = 'Kam az kam 1 Raw Material select karo.'; }
  if(errorMsg){ alert('⚠️ ' + errorMsg); e.preventDefault(); return; }
});

addMatRow();
</script>
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), materials=materials,
                                   products_history=products_history, today_db=fmt_date(for_db=True))


@app.route("/productions")
@login_required
def productions_list():
    conn = db()
    try:
        c = conn.cursor()
        c.execute("""SELECT id,date,product_name,size_pack,output_cartons,extra_pieces,
                     material_cost,cost_per_carton,cost_per_piece FROM productions ORDER BY id DESC LIMIT 1000""")
        rows = [{"id":r[0],"date":r[1],"product_name":r[2],"size_pack":r[3],"output_cartons":r[4],
                  "extra_pieces":r[5],"material_cost":r[6],"cost_per_carton":r[7],"cost_per_piece":r[8]}
                 for r in c.fetchall()]
    finally:
        conn.close()

    # ---- Har MAHINE ka data alag (foldable group) — total khud calculate hota hai ----
    grouped = _group_by_month(rows, "date")
    month_blocks = []
    for ym, grows in grouped:
        month_blocks.append({
            "label": _month_label(ym),
            "rows": grows,
            "total_cost": sum(r["material_cost"] or 0 for r in grows),
            "total_cartons": sum(r["output_cartons"] or 0 for r in grows),
            "count": len(grows),
        })

    html = TPL_H + FACTORY_STYLE + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Production</div>
    <h2>🏭 All Production</h2>
    <p>Har mahine ka data alag foldable section mein — total khud calculate hota hai.</p>
  </div>
  <a href="{{url_for('new_production')}}" class="btn btn-primary">➕ New Production</a>
</div>

{% for blk in month_blocks %}
<details class="card mb-3" {% if loop.first %}open{% endif %}>
  <summary style="cursor:pointer;font-weight:700;font-size:15px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>📅 {{blk.label}} <span class="text-muted" style="font-weight:400;font-size:12.5px">({{blk.count}} production entries)</span></span>
    <span class="badge badge-blue">Cost: Rs {{ "%.2f"|format(blk.total_cost) }} · Cartons: {{ "%.2f"|format(blk.total_cartons) }}</span>
  </summary>
  <div class="table-wrap mt-2">
    <table>
      <thead><tr><th>Date</th><th>Product</th><th>Size</th><th>Cartons</th><th>Extra Pcs</th><th>Material Cost</th><th>Cost/Carton</th><th>Cost/Piece</th><th>Action</th></tr></thead>
      <tbody>
        {% for r in blk.rows %}
        <tr>
          <td>{{r.date}}</td><td class="fw-bold">{{r.product_name}}</td><td>{{r.size_pack or '-'}}</td>
          <td>{{ "%.2f"|format(r.output_cartons) }}</td><td>{{ "%.2f"|format(r.extra_pieces) }}</td>
          <td>Rs {{ "%.2f"|format(r.material_cost) }}</td>
          <td>Rs {{ "%.2f"|format(r.cost_per_carton) }}</td>
          <td>Rs {{ "%.2f"|format(r.cost_per_piece) }}</td>
          <td><a href="{{url_for('delete_production', pid=r.id)}}" class="btn btn-danger btn-sm" onclick="return confirm('Delete karna hai? Raw Material stock wapis add ho jayega.')">🗑️</a></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</details>
{% endfor %}
{% if not month_blocks %}<div class="card text-center text-muted">Koi Production record nahi</div>{% endif %}
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), month_blocks=month_blocks)


@app.route("/production/delete/<int:pid>")
@login_required
def delete_production(pid):
    conn = db()
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM productions WHERE id=?", (pid,))
        if not c.fetchone():
            flash("Production record nahi mila.")
            return redirect(url_for("productions_list"))
        c.execute("SELECT material_id, qty FROM production_materials WHERE production_id=?", (pid,))
        used = c.fetchall()
        for mid, qty in used:
            c.execute("UPDATE raw_materials SET current_stock = current_stock + ? WHERE id=?", (qty, mid))
        c.execute("DELETE FROM production_materials WHERE production_id=?", (pid,))
        c.execute("DELETE FROM productions WHERE id=?", (pid,))
        conn.commit()
        flash("🗑️ Production delete ho gayi, Raw Material stock wapis add ho gaya.")
    except Exception as e:
        conn.rollback()
        flash(f"Delete error: {e}")
    finally:
        conn.close()
    return redirect(url_for("productions_list"))


# ======================================================================
# ==========================  FACTORY DASHBOARD  =========================
# ======================================================================
@app.route("/factory-dashboard")
@login_required
def factory_dashboard():
    materials = load_raw_materials()
    low_stock = [m for m in materials if m["min_stock"] > 0 and m["current_stock"] <= m["min_stock"]]

    try:
        with db_transaction() as conn:
            c = conn.cursor()
            c.execute("SELECT date, total_cost FROM purchase_entries")
            purch_rows = c.fetchall()
            today_purchase = sum((r[1] or 0) for r in purch_rows if _is_today(r[0]))
            month_purchase = sum((r[1] or 0) for r in purch_rows if _is_this_month(r[0]))

            c.execute("SELECT date, material_cost FROM productions")
            prod_rows = c.fetchall()
            today_production_cost = sum((r[1] or 0) for r in prod_rows if _is_today(r[0]))
            today_production_count = sum(1 for r in prod_rows if _is_today(r[0]))
            month_production_cost = sum((r[1] or 0) for r in prod_rows if _is_this_month(r[0]))
            month_production_count = sum(1 for r in prod_rows if _is_this_month(r[0]))

            c.execute("SELECT date, amount FROM expenses")
            exp1 = c.fetchall()
            c.execute("SELECT date, amount FROM other_expenses")
            exp2 = c.fetchall()
            today_expenses = sum((r[1] or 0) for r in exp1 if _is_today(r[0])) + \
                              sum((r[1] or 0) for r in exp2 if _is_today(r[0]))
            month_expenses = sum((r[1] or 0) for r in exp1 if _is_this_month(r[0])) + \
                              sum((r[1] or 0) for r in exp2 if _is_this_month(r[0]))

            c.execute("SELECT date, grand_total, total FROM invoices")
            inv_rows = c.fetchall()
    except Exception as e:
        flash(f"Factory dashboard load failed, no changes made (safe rollback): {e}")
        return redirect(url_for("home"))

    today_sales = 0.0
    month_sales = 0.0
    for rdate, gtotal, total in inv_rows:
        try:
            amt = float(gtotal or total or 0)
        except Exception:
            amt = 0.0
        if _is_today(rdate):
            today_sales += amt
        if _is_this_month(rdate):
            month_sales += amt

    today_profit = today_sales - today_production_cost - today_expenses
    month_profit = month_sales - month_production_cost - month_expenses
    this_month_label = _month_label(datetime.date.today().strftime("%Y-%m"))

    html = TPL_H + FACTORY_STYLE + """
<div class="page-header">
  <div>
    <div class="breadcrumb"><a href="{{url_for('home')}}">Home</a> / Factory Dashboard</div>
    <h2>📊 Factory Dashboard</h2>
  </div>
  <div style="display:flex;gap:8px">
    <a href="{{url_for('raw_materials_page')}}" class="btn btn-outline">🧱 Raw Material</a>
    <a href="{{url_for('new_purchase')}}" class="btn btn-outline">🛒 Purchase</a>
    <a href="{{url_for('new_production')}}" class="btn btn-primary">🏭 Production</a>
  </div>
</div>

<h3 style="margin:6px 0">📌 Aaj (Today)</h3>
<div class="fx-grid">
  <div class="fx-tile"><h4>TODAY'S PURCHASE</h4><div class="val">Rs {{ "%.0f"|format(today_purchase) }}</div></div>
  <div class="fx-tile"><h4>TODAY'S PRODUCTION</h4><div class="val">{{today_production_count}} <span style="font-size:13px;font-weight:400">entries</span></div><div class="text-muted" style="font-size:12px">Cost: Rs {{ "%.0f"|format(today_production_cost) }}</div></div>
  <div class="fx-tile"><h4>TODAY'S SALES</h4><div class="val">Rs {{ "%.0f"|format(today_sales) }}</div></div>
  <div class="fx-tile"><h4>TODAY'S EXPENSES</h4><div class="val">Rs {{ "%.0f"|format(today_expenses) }}</div></div>
  <div class="fx-tile"><h4>TODAY'S PROFIT</h4><div class="val" style="color:{{ 'green' if today_profit>=0 else 'red' }}">Rs {{ "%.0f"|format(today_profit) }}</div></div>
</div>

<h3 style="margin:16px 0 6px">📅 Is Mahine ({{this_month_label}}) — khud calculate</h3>
<div class="fx-grid">
  <div class="fx-tile"><h4>MONTH'S PURCHASE</h4><div class="val">Rs {{ "%.0f"|format(month_purchase) }}</div></div>
  <div class="fx-tile"><h4>MONTH'S PRODUCTION</h4><div class="val">{{month_production_count}} <span style="font-size:13px;font-weight:400">entries</span></div><div class="text-muted" style="font-size:12px">Cost: Rs {{ "%.0f"|format(month_production_cost) }}</div></div>
  <div class="fx-tile"><h4>MONTH'S SALES</h4><div class="val">Rs {{ "%.0f"|format(month_sales) }}</div></div>
  <div class="fx-tile"><h4>MONTH'S EXPENSES</h4><div class="val">Rs {{ "%.0f"|format(month_expenses) }}</div></div>
  <div class="fx-tile"><h4>MONTH'S PROFIT</h4><div class="val" style="color:{{ 'green' if month_profit>=0 else 'red' }}">Rs {{ "%.0f"|format(month_profit) }}</div></div>
</div>

<div class="card">
  <h3>⚠️ Low Stock Alerts <span class="badge badge-red">{{low_stock|length}}</span></h3>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Material</th><th>Current Stock</th><th>Min Stock</th><th>Action</th></tr></thead>
      <tbody>
        {% for m in low_stock %}
        <tr>
          <td class="fw-bold">{{m.name}}</td>
          <td style="color:#dc2626">{{ "%.2f"|format(m.current_stock) }} {{m.unit}}</td>
          <td>{{ "%.2f"|format(m.min_stock) }} {{m.unit}}</td>
          <td><a href="{{url_for('new_purchase')}}" class="btn btn-primary btn-sm">🛒 Purchase Karo</a></td>
        </tr>
        {% endfor %}
        {% if not low_stock %}<tr><td colspan="4" class="text-center text-muted">Sab materials ka stock theek hai ✅</td></tr>{% endif %}
      </tbody>
    </table>
  </div>
</div>
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), low_stock=low_stock,
        today_purchase=today_purchase, today_production_cost=today_production_cost,
        today_production_count=today_production_count, today_sales=today_sales,
        today_expenses=today_expenses, today_profit=today_profit,
        month_purchase=month_purchase, month_production_cost=month_production_cost,
        month_production_count=month_production_count, month_sales=month_sales,
        month_expenses=month_expenses, month_profit=month_profit, this_month_label=this_month_label)

# ======================================================================
# =======================  FACTORY MODULE — END  ========================
if __name__ == "__main__":
    import time
    import webview

    company = get_setting("company_name", "SEIZE CLEANING SOLUTION")

    show_splash(company)

    # Flask ko background thread mein chalayein
    def run_flask():
        app.run(
            host="127.0.0.1",
            port=20497,
            debug=False,
            use_reloader=False
        )

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Flask ko start hone ka thora sa time dein
    time.sleep(1.2)

    # Apni khud ki desktop window mein app kholein (browser ki jagah)
    webview.create_window(
        company if company.strip() else "Seize Enterprise",
        "http://127.0.0.1:20497",
        width=1280,
        height=800,
        min_size=(1000, 650)
    )
    webview.start()