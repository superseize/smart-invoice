# app.py — Smart Invoice (stable header)

# ===================== IMPORTS =====================
from pathlib import Path
import sys
import os
import csv, datetime, json, io
from typing import Optional
import sqlite3

from flask import (
    Flask, request, redirect, url_for,
    send_from_directory, render_template_string,
    flash, jsonify, session, Response,
    send_file, get_flashed_messages, render_template
)
from werkzeug.utils import secure_filename
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

#import threading
#import time
#import tkinter as tk
#from tkinter import font
#from PIL import Image, ImageTk


# ===================== EXE / ROOT =====================
if getattr(sys, 'frozen', False):  # PyInstaller EXE
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path.cwd()


# ===================== PERSISTENT DATA PATH =====================
# Local: ./data
# Render: /var/data (ENV: DATA_PATH)

BASE_DATA = Path(os.environ.get("DATA_PATH", "data"))

DATA_DIR = BASE_DATA / "data"
UPLOADS_DIR = BASE_DATA / "uploads"
RECORDS_DIR = BASE_DATA / "BusinessRecords"
DB_DIR = BASE_DATA / "db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
RECORDS_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE = DB_DIR / "smart_invoice.db"
SALES_CSV = DATA_DIR / "sales_log.csv"


# ===================== SALES CSV HELPERS =====================
def read_sales_csv():
    if not SALES_CSV.exists():
        return []
    with open(SALES_CSV, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_sales_csv(rows):
    with open(SALES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "inv_no", "product", "qty", "sell_price"]
        )
        writer.writeheader()
        writer.writerows(rows)


# ===================== SQLITE INIT =====================
def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()

        # ========== INVOICES MASTER ==========
        c.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no TEXT UNIQUE,
            date TEXT,
            customer TEXT,
            customer_address TEXT,
            salesman TEXT,
            total REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            status TEXT
        )
        """)

        # ========== INVOICE ITEMS ==========
        c.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no TEXT,
            product TEXT,
            qty REAL,
            price REAL
        )
        """)


        c.execute("""
            CREATE TABLE IF NOT EXISTS products (
                name TEXT PRIMARY KEY,
                stock REAL DEFAULT 0,
                unit_price REAL DEFAULT 0,
                purchase_price REAL DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT DEFAULT (date('now')),
                product TEXT,
                qty REAL,
                price REAL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                amount REAL,
                description TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS targets (
                month TEXT,
                product TEXT,
                qty REAL DEFAULT 0,
                PRIMARY KEY (month, product)
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

        conn.commit()
        conn.close()
        print("✅ SQLite tables ready")

    except Exception as e:
        print("❌ DB Error:", e)


# ===================== INIT DB (ON START) =====================
init_db()
def db():
    return sqlite3.connect(DB_FILE)

def save_invoice_sqlite(inv, items):
    con = db()
    cur = con.cursor()

    # --- invoice master ---
    cur.execute("""
        INSERT INTO invoices
        (inv_no, date, customer, customer_address, salesman, total, paid, status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        inv["inv_no"],
        inv["date"],
        inv["customer"],
        inv.get("customer_address", ""),
        inv.get("salesman", ""),
        inv["total"],
        inv.get("paid", 0),
        inv["status"]
    ))

    # --- invoice items ---
    for it in items:
        cur.execute("""
            INSERT INTO invoice_items
            (inv_no, product, qty, price)
            VALUES (?,?,?,?)
        """, (
            inv["inv_no"],
            it["product"],
            it["qty"],
            it["price"]
        ))

    con.commit()
    con.close()

# ===================== FLASK APP =====================
app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("APP_SECRET", "smart-invoice-change-this")


# ========== سادہ اور خوبصورت پاس ورڈ لاگ ان ==========
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("logged_in"):
            return f(*args, **kwargs)
        flash("Login")
        return redirect(url_for("login"))
    return decorated_function

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")
        # Get password from settings, default '12345'
        current_password = get_setting("app_password", "12345")
        if password == current_password:
            session["logged_in"] = True
            flash("Login successful!")
            return redirect(url_for("home"))
        else:
            flash("Invalid password")
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

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    flash("log out")
    return redirect(url_for("login"))
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    question = get_setting("security_question", "What is your favorite color?")
    correct_answer = get_setting("security_answer", "").lower()

    if request.method == "POST":
        user_answer = request.form.get("answer", "").lower().strip()
        if user_answer == correct_answer:
            set_setting("app_password", "12345")
            flash("Password reset successful! New password is 12345")
            return redirect(url_for("login"))
        else:
            flash("Incorrect answer. Try again.")

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>Reset Password</title>
        <style>
            body {background: linear-gradient(135deg, #667eea, #764ba2); display:flex; justify-content:center; align-items:center; height:100vh; margin:0; font-family: system-ui;}
            .box {background: white; padding: 40px; border-radius: 20px; box-shadow: 0 15px 40px rgba(0,0,0,0.3); width: 400px; text-align: center;}
            h2 {color: #d32f2f; margin-bottom: 30px;}
            p {color: #555; margin-bottom: 20px;}
            input {width: 100%; padding: 15px; margin: 10px 0; border: 1px solid #ddd; border-radius: 12px; font-size: 18px;}
            button {width: 100%; padding: 15px; background: #d32f2f; color: white; border: none; border-radius: 12px; font-size: 20px; cursor: pointer;}
        </style>
    </head>
    <body>
        <div class="box">
            <h2>🔄 Reset Password</h2>
            <p><strong>Security Question:</strong><br>{{ question }}</p>
            <form method="post">
                <input name="answer" placeholder="Enter your answer" required autofocus>
                <button type="submit">Reset Password</button>
            </form>
        </div>
    </body>
    </html>
    """, question=question)
# ---------- Paths ----------
#ROOT = Path.cwd()
DATA = ROOT / "data"
UPLOADS = ROOT / "uploads"

# <--- یہ تین نئی لائنز یہاں ڈالیں --->
DB_FILE = DATA / "smart_invoice_system.db"        # SQLite ڈیٹا بیس فائل
DATA.mkdir(parents=True, exist_ok=True)    # data فولڈر بن جائے گا
UPLOADS.mkdir(parents=True, exist_ok=True) # uploads بھی

for p in (DATA, UPLOADS):
    p.mkdir(parents=True, exist_ok=True)

PRODUCTS  = DATA / "products.csv"
CUSTOMERS = DATA / "customers.csv"
INVOICES  = DATA / "invoices.csv"
LINES     = DATA / "invoice_lines.csv"
PAYMENTS  = DATA / "payments.csv"
SETTINGS  = DATA / "settings.csv"
SEQ       = DATA / "sequence.csv"
EXPENSES_CSV = DATA / "expenses.csv"
# موجودہ paths کے ساتھ یہ لائن شامل کریں
TARGETS_CSV = DATA / "targets.csv"
def _ensure(path: Path, head):
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(head)

_ensure(PRODUCTS,  ["name","unit_price","purchase_price","stock","min_stock"])
_ensure(CUSTOMERS, ["name","address","phone"])
_ensure(INVOICES, ["inv_no","date","name","address","phone","tax","total","logo_path","pending_added","remarks"])
_ensure(LINES,     ["inv_no","product","qty","unit_price"])
_ensure(EXPENSES_CSV, ["id", "date", "amount", "description"])
_ensure(TARGETS_CSV, ["month", "product", "qty"])
_ensure(PAYMENTS,  ["pay_id","inv_no","date","amount","method","customer","address","note"])
_ensure(SETTINGS,  ["key","value"])
_ensure(SEQ,       ["key","value"])

# ---------- CSV helpers ----------
def read_csv(p: Path):
    try:
        with p.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []

def write_csv(p: Path, rows, head):
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=head)
        w.writeheader()
        for row in rows:
            # غائب یا None فیلڈز کو خالی سٹرنگ سے بھریں
            clean_row = {k: (v if v is not None else "") for k, v in row.items()}
            # اگر کوئی ایکسٹرا فیلڈ ہو تو ہٹا دیں
            clean_row = {k: clean_row.get(k, "") for k in head}
            w.writerow(clean_row)

def append_csv(p: Path, row, head):
    if not p.exists() or p.stat().st_size == 0:
        write_csv(p, [], head)
    with p.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=head).writerow(row)

def get_seq(key, start=1):
    rows = read_csv(SEQ)
    for r in rows:
        if r["key"] == key:
            try:
                return int(r["value"])
            except:
                return start
    rows.append({"key": key, "value": str(start)})
    write_csv(SEQ, rows, ["key","value"])
    return start

def set_seq(key, val):
    rows = read_csv(SEQ)
    found = False
    for r in rows:
        if r["key"] == key:
            r["value"] = str(val)
            found = True
    if not found:
        rows.append({"key": key, "value": str(val)})
    write_csv(SEQ, rows, ["key","value"])

# ---------- Settings ----------
def get_setting(k, default=""):
    for r in read_csv(SETTINGS):
        if r["key"] == k:
            return r["value"]
    return default

def set_setting(k, v):
    rows = read_csv(SETTINGS)
    found = False
    for r in rows:
        if r["key"] == k:
            r["value"] = str(v)
            found = True
    if not found:
        rows.append({"key": k, "value": str(v)})
    write_csv(SETTINGS, rows, ["key","value"])

def init_settings():
    s = read_csv(SETTINGS)
    keys = {r["key"] for r in s}
    def put(k, v):
        if k not in keys:
            s.append({"key": k, "value": v})
            keys.add(k)
    put("project_name","Smart Invoice")
    put("company_name","COMPANY NAME")
    put("tax_default","0")
    put("date_format","dd-mm-yy")
    put("invoice_start","100")
    put("logo_path","")
    put("logo_show","1")
    put("auto_create_folders","1")
    put("output_folder","")
    put("developer_name", "ISHTIAQ AHMAD MAGRAY")
    put("developer_phone", "+923495820495")  # Change to your phone number  
    put("contact_msg", "For new software development, contact the developer above.")  
    put("growth_rate", "10")   # <-- یہ نیا اضافہ کریں
    put("show_pending", "0")  # 0 = off, 1 = on
    write_csv(SETTINGS, s, ["key","value"])
init_settings()

# ---------- Utils ----------
def to_caps(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    # پہلا حرف کیپیٹل، باقی جیسے ہیں (صرف پہلا حرف بڑا)
    return s[0].upper() + s[1:]

def fmt_date(dt: Optional[datetime.date] = None, for_db: bool = False) -> str:  
    if dt is None:  
        dt = datetime.date.today()  
    if for_db:  
        return dt.isoformat()  # 2026-01-01 → DB کے لیے  
    else:  
        f = get_setting("date_format","dd-mm-yy")   # settings سے پڑھتا ہے  
        if f == "dd-mm-yyyy":  
            return dt.strftime("%d-%m-%Y")  
        if f == "yyyy-mm-dd":  
            return dt.strftime("%Y-%m-%d")  
        return dt.strftime("%d-%m-%y")  # dd-mm-yy  

def output_base() -> Path:
    base_text = get_setting("output_folder","")
    return Path(base_text) if base_text else ROOT

def ensure_out_dirs(year: int, month_name: str) -> Path:
    base = output_base()
    target = base / "BusinessRecords" / str(year) / month_name
    if get_setting("auto_create_folders","1") == "1":
        target.mkdir(parents=True, exist_ok=True)
    return target

def safe_name(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch in " _-").strip().replace(" ","_")

# ---------- Domain loaders ----------
def load_products():
    out = []
    for r in read_csv(PRODUCTS):
        if not r.get("name"):
            continue
        name = to_caps(r["name"])  # اب کیپیٹل ہو جائے گا
        try:
            up = float(r.get("unit_price","0") or "0")
            pp = float(r.get("purchase_price","0") or "0")
            st = float(r.get("stock","0") or "0")
            mn = float(r.get("min_stock","0") or "0")
        except:
            up, pp, st, mn = 0.0, 0.0, 0.0, 0.0
        out.append({
            "name": name,
            "unit_price": up,
            "purchase_price": pp,
            "stock": st,
            "min_stock": mn
        })
    return out
def load_customers():
    out = []
    for r in read_csv(CUSTOMERS):
        if r.get("name"):
            out.append({"name": to_caps(r["name"]), "address": to_caps(r.get("address","")), "phone": r.get("phone","")})
    return out

def ensure_customer(name, address, phone):
    name = to_caps(name)
    address = to_caps(address)
    rows = read_csv(CUSTOMERS)
    for r in rows:
        if to_caps(r["name"]) == name and to_caps(r.get("address","")) == address:
            r["phone"] = phone
            write_csv(CUSTOMERS, rows, ["name","address","phone"])
            return
    rows.append({"name": name, "address": address, "phone": phone})
    write_csv(CUSTOMERS, rows, ["name","address","phone"])

def ensure_sales_log_table():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sales_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            inv_no INTEGER,
            product TEXT,
            qty REAL,
            sell_price REAL
        )
    """)
    conn.commit()
    conn.close()

# ===================== INIT DB (ON START) =====================
init_db()
ensure_sales_log_table()


# ---------- PDF helpers ----------
PAGE_W, PAGE_H = A4

def draw_invoice_pdf(out_path: Path, company: str, logo_path: Optional[str], show_logo: bool,
                     inv_no: int, date_str_display: str, cust_name: str, cust_addr: str, cust_phone: str,
                     lines, tax_pct: float, pending_added: float = 0.0) -> float:
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    import textwrap

    out_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(out_path), pagesize=A4)
    W, H = A4

    left = 20 * mm
    right = W - 20 * mm
    top = H - 25 * mm

    if show_logo and logo_path and Path(logo_path).exists():
        try:
            img = ImageReader(logo_path)
            c.drawImage(img, right - 30*mm, top-5, width=25*mm, height=10*mm, preserveAspectRatio=True)
        except:
            pass

    c.setFont("Helvetica-Bold", 25)
    c.drawString(left + 1, top - 5, company)
    c.setFont("Helvetica", 12)
    c.drawRightString(right-5, top - 20, f"Invoice #: {inv_no}")
    c.drawRightString(right, top - 30, f"Date: {date_str_display}")

    y = top - 30
    c.setFont("Helvetica-Bold", 12); c.drawString(left, y, "Name:")
    c.setFont("Helvetica", 12); c.drawString(left + 60, y, cust_name)
    y -= 12
    c.setFont("Helvetica-Bold", 12); c.drawString(left, y, "Address:")
    c.setFont("Helvetica", 12)
    addr_lines = textwrap.wrap(cust_addr, width=45)
    for l in addr_lines:
        c.drawString(left + 60, y, l); y -= 12
    c.setFont("Helvetica-Bold", 12); c.drawString(left, y, "Phone:")
    c.setFont("Helvetica", 12); c.drawString(left + 60, y, cust_phone)
    y -= 20; c.line(left, y, right, y); y -= 15

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Sr."); c.drawString(left + 40, y, "Product"); c.drawString(left + 220, y, "Qty")
    c.drawString(left + 280, y, "Unit Price"); c.drawString(left + 380, y, "Total")
    y -= 10; c.line(left, y, right, y); y -= 15

    subtotal = 0.0; sr = 1
    for li in lines:
        pname = li["product"]; qty = float(li["qty"]); up = float(li["unit_price"]); tot = qty * up; subtotal += tot
        wrap = textwrap.wrap(pname, width=35)
        c.setFont("Helvetica", 12)
        c.drawString(left, y, str(sr)); c.drawString(left + 40, y, wrap[0]); c.drawString(left + 220, y, f"{qty:g}")
        c.drawString(left + 280, y, f"{up:,.0f}"); c.drawString(left + 380, y, f"{tot:,.0f}")
        y -= 15
        for w in wrap[1:]:
            c.drawString(left + 40, y, w); y -= 15
        sr += 1

    y -= 10; c.line(left, y, right, y); y -= 20

    # درست حساب — یہ دو لائنیں لازمی ہونی چاہییں
    tax_amt = subtotal * (tax_pct / 100)
    grand = subtotal + tax_amt + pending_added


    c.setFont("Helvetica-Bold", 12)

    c.drawRightString(right - 10, y, f"Subtotal:           Rs {subtotal:,.0f}")
    y -= 22

    if tax_pct > 0:
        c.drawRightString(right - 10, y, f"Tax ({tax_pct:.2f}%):        {tax_amt:,.0f}")
        y -= 22

    if pending_added > 0:
        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(right - 10, y, f"Previous Pending:   {pending_added:,.0f}")
        y -= 28

    c.setFont("Helvetica-Bold", 13)
    c.setFillColorRGB(0, 0, 0)
    c.drawRightString(right - 10, y, f"GRAND TOTAL:  {grand:,.0f}")

    y -= 70
    c.setFillColorRGB(0, 0, 0)
    c.line(right - 220, y, right - 10, y)
    c.setFont("Helvetica", 10)
    c.drawString(right - 170, y - 18, "Customer Signature")
    c.save()
# ===== Pending Amount Functions (نیا اضافہ) =====
def get_pending(name, address):
    name = to_caps(name)
    address = to_caps(address)
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT pending_amount FROM customer_pending WHERE customer_name = ? AND customer_address = ?", (name, address))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0.0
    except:
        return 0.0

def update_pending(name, address, new_pending):
    name = to_caps(name)
    address = to_caps(address)
    # Prevent negative pending (important fix)
    new_pending = max(0.0, float(new_pending))
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""INSERT INTO customer_pending (customer_name, customer_address, pending_amount)
                     VALUES (?, ?, ?)
                     ON CONFLICT(customer_name, customer_address) DO UPDATE SET
                     pending_amount = excluded.pending_amount""", (name, address, new_pending))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Pending update error:", e)
    # کوئی return نہیں – فنکشن void ہے

def build_month_summary_pdf(year: int, month_name: str, out_dir: Path) -> Path:
    rows = read_csv(INVOICES)
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

# ---------- HTML shell ----------
TPL_H = """
<!doctype html>
<title>{{project}}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<style>
body{margin:0;font-family:system-ui;background:#f8fafc}

/* layout */
.app{display:flex;min-height:100vh}

/* sidebar */
.sidebar{
  width:260px;
  background:linear-gradient(180deg,#020617,#0f172a);
  color:white;
  padding:20px;
}
.sidebar h2{text-align:center;margin-bottom:25px}
.sidebar a{
  display:block;
  padding:12px;
  margin:6px 0;
  color:#e5e7eb;
  text-decoration:none;
  border-radius:10px;
}
.sidebar a:hover{background:#2563eb}
.sidebar .logout{margin-top:25px;background:#7f1d1d}

/* content */
.content{flex:1;padding:25px}
.card{background:white;border-radius:12px;padding:20px}
/* ===== MOBILE RESPONSIVE SIDEBAR ===== */
@media (max-width: 768px){

  .sidebar{
    position: fixed;
    top: 0;
    left: -280px;
    width: 260px;
    height: 100vh;
    z-index: 1200;
    transition: left 0.3s ease;
    overflow-y: auto;
  }

  .sidebar.open{
    left: 0;
  }

  .content{
    padding: 80px 15px 15px;
  }
}

/* ===== MOBILE MENU BUTTON ===== */
.menu-btn{
  display:none;
  position:fixed;
  top:15px;
  left:15px;
  z-index:1300;
  background:#1e3a8a;
  color:white;
  border:none;
  font-size:22px;
  padding:10px 14px;
  border-radius:10px;
}

/* show menu button only on mobile */
@media (max-width: 768px){
  .menu-btn{
    display:block;
  }
}

/* ===== DASHBOARD CARDS MOBILE ===== */
@media(max-width:600px){

  .card-container{
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    margin: 20px 10px;
  }

  .dash-card{
    padding: 18px;
  }

  .dash-icon{
    width: 70px;
    height: 70px;
  }

  .dash-card p{
    font-size: 14px;
  }
}

/* ===== FORCE 4 DASHBOARD CARDS PER ROW (MOBILE) ===== */
@media (max-width: 768px){

  .card-container{
    grid-template-columns: repeat(4, 1fr) !important;
    gap: 8px !important;
    margin: 10px 5px !important;
  }

  .dash-card{
    padding: 10px !important;
    border-radius: 10px;
  }

  .dash-card img,
  .dash-icon{
    width: 40px !important;
    height: 40px !important;
  }

  .dash-card h3{
    font-size: 11px !important;
  }

  .dash-card p{
    font-size: 10px !important;
  }
}

/* ===== TABLE MOBILE FIX ===== */
.table-wrap{
  width:100%;
  overflow-x:auto;
}

table{
  min-width:700px;
}
/* ===== MOBILE TABLE SIZE SMALL ===== */
@media (max-width: 768px){

  table{
    font-size: 12px;      /* text chhota */
  }

  th, td{
    padding: 4px;         /* cells tight */
  }

}

</style>

<div class="app">

  <aside class="sidebar">
    <h2>Smart Invoice</h2>

    <a href="{{ url_for('home') }}">🏠 Home</a>
    <a href="{{ url_for('new_invoice') }}">🧾 New Invoice</a>
    <a href="{{ url_for('invoices_list') }}">📂 All Invoices</a>
    <a href="{{ url_for('products') }}">📦 Products</a>
    <a href="{{ url_for('stock_entry') }}">🏭 Stock Entry</a>
    <a href="{{ url_for('customers') }}">👥 Customers</a>
    <a href="{{ url_for('payments') }}">💳 Payments</a>
    <a href="{{ url_for('target') }}">🎯 Target</a>
    <a href="{{ url_for('expenses') }}">💰 Expenses</a>
    <a href="{{ url_for('sales_record') }}">📈 Sales Record</a>
    <a href="{{ url_for('profit_loss') }}">📉 Profit & Loss</a>
    <a href="{{ url_for('reports') }}">📊 Reports</a>
    <a href="{{ url_for('other_expenses') }}">🧾 Other Expenses</a>
    <a href="{{ url_for('settings') }}">⚙️ Settings</a>

    <a href="{{ url_for('logout') }}" class="logout">🚪 Logout</a>
  </aside>

  <main class="content">
<!-- MOBILE MENU BUTTON -->
<button id="menuBtn" class="menu-btn">☰</button>

  <div class="card">
"""
TPL_F = """
  </div>
  </main>
<script>
const menuBtn = document.getElementById("menuBtn");
const sidebar = document.querySelector(".sidebar");

if(menuBtn && sidebar){
  menuBtn.addEventListener("click", function(){
    sidebar.classList.toggle("open");
  });
}
</script>
<script>
const menuBtn = document.getElementById("menuBtn");
const sidebar = document.querySelector(".sidebar");

if(menuBtn && sidebar){
  menuBtn.addEventListener("click", function(){
    sidebar.classList.toggle("open");
  });
}
</script>

</div>
"""


# ---------- welcome page ----------

# ---------- Home ----------
@app.route("/")
@login_required
def home():
    now = datetime.datetime.now()
    cur_month = now.strftime("%B"); cur_year = now.year
    month_total = 0.0
    for r in read_csv(INVOICES):
        d = r.get("date","")
        try:  
            # پہلے نیا DB فارمیٹ try کریں  
            dt = datetime.datetime.strptime(d, "%Y-%m-%d")  
        except:  
            try:  
                dt = datetime.datetime.strptime(d, "%d-%m-%y")   # پرانا dd-mm-yy  
            except:  
                try:  
                    dt = datetime.datetime.strptime(d, "%d-%m-%Y")  
                except:  
                    continue  
        if dt.year == cur_year and dt.strftime("%B") == cur_month:
            month_total += float(r.get("total","0") or 0)

    html = TPL_H + """
<h2 style="text-align:center; color:#1565c0; font-size:32px; margin:40px 0; font-weight:bold;">
  Smart Invoice Pro — Professional Dashboard
</h2>

<style>
.card-container {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 28px;
    margin: 40px 20px;
    padding: 10px;
}

.dash-card {
    background: linear-gradient(145deg, #ffffff, #eef2ff);
    padding: 35px 25px;
    border-radius: 24px;
    text-align: center;
    text-decoration: none;
    color: #1e293b;
    border: none;
    box-shadow: 0 15px 35px rgba(59, 130, 246, 0.2);
    transition: all 0.5s ease;
    font-weight: bold;
    overflow: hidden;
}

.dash-card:hover {
    transform: translateY(-15px) scale(1.08);
    box-shadow: 0 30px 60px rgba(59, 130, 246, 0.4);
    background: linear-gradient(145deg, #dbeafe, #bfdbfe);
}

.dash-icon {
    width: 120px;
    height: 120px;
    object-fit: contain;
    margin-bottom: 20px;
    border-radius: 20px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    transition: transform 0.5s ease;
}

.dash-card:hover .dash-icon {
    transform: rotate(12deg) scale(1.2);
}

.dash-card p {
    font-size: 18px;
    margin: 0;
    color: #1d4ed8;
    font-weight: bold;
}
</style>

<div class="card-container">

  <!-- Home -->
  <a class="dash-card" href="{{url_for('home')}}">
    <img src="https://thumbs.dreamstime.com/b/laptop-floating-holographic-business-dashboards-data-analytics-concept-sleek-laptop-displays-glowing-holographic-panels-416620772.jpg" class="dash-icon">
    <p>Home</p>
  </a>

  <!-- New Invoice -->
  <a class="dash-card" href="{{url_for('new_invoice')}}">
    <img src="https://previews.123rf.com/images/tanzimgraphicszone/tanzimgraphicszone2205/tanzimgraphicszone220500089/186497647-dollar-invoice-icon-on-dark-background-3d-render-concept-for-bill-or-statement-progress-report.jpg" class="dash-icon">
    <p>New Invoice</p>
  </a>

  <!-- All Invoices -->
  <a class="dash-card" href="{{url_for('invoices_list')}}">
    <img src="https://png.pngtree.com/background/20231031/original/pngtree-3d-icon-of-a-file-folder-picture-image_5815960.jpg" class="dash-icon">
    <p>All Invoices</p>
  </a>

  <!-- Products -->
  <a class="dash-card" href="{{url_for('products')}}">
    <img src="https://media.istockphoto.com/id/1469950190/vector/realistic-vector-carton-square-boxes-in-open-and-closed-view-isolated-icon-illustration-on.jpg?s=612x612&w=0&k=20&c=Q8yejePKMXhK33Gz1G5QEk-AipTPBS0CktdcMIkWQU0=" class="dash-icon">
    <p>Products</p>
  </a>

  <!-- Stock Entry -->
  <a class="dash-card" href="{{url_for('stock_entry')}}">
    <img src="https://thumbs.dreamstime.com/b/vector-isometric-warehouse-building-icon-60015750.jpg" class="dash-icon">
    <p>Stock Entry</p>
  </a>

  <!-- Customers -->
  <a class="dash-card" href="{{url_for('customers')}}">
    <img src="https://img.freepik.com/free-photo/confident-business-people-diversity-teamwork-concept_53876-127138.jpg?semt=ais_hybrid&w=740&q=80" class="dash-icon">
    <p>Customers</p>
  </a>

  <!-- Payments -->
  <a class="dash-card" href="{{url_for('payments')}}">
    <img src="https://static.vecteezy.com/system/resources/previews/048/039/055/non_2x/3d-realistic-credit-card-coin-online-payment-online-cartoon-style-design-free-vector.jpg" class="dash-icon">
    <p>Payments</p>
  </a>

  <!-- Target -->
  <a class="dash-card" href="{{url_for('target')}}">
    <img src="https://media.istockphoto.com/id/2173963917/vector/target-landing-page-banner-business-3d-icon-vector-illustration.jpg?s=612x612&w=0&k=20&c=XJ_KdjF1RMcJ7f43p36V9X-WUUZvKS8RVL6qCDRmwTE=" class="dash-icon">
    <p>Target</p>
  </a>

  <!-- Expenses -->
  <a class="dash-card" href="{{url_for('expenses')}}">
    <img src="https://www.shutterstock.com/image-illustration/wallet-money-3d-icon-illustration-260nw-2451726875.jpg" class="dash-icon">
    <p>Expenses</p>
  </a>

  <!-- Sales Record -->
  <a class="dash-card" href="{{url_for('sales_record')}}">
    <img src="https://static.vecteezy.com/system/resources/previews/015/586/945/non_2x/growth-chart-trade-arrow-stock-price-chart-realistic-3d-design-render-change-in-value-exchange-trading-annual-and-quarterly-profit-report-vector.jpg" class="dash-icon">
    <p>Sales Record</p>
  </a>

  <!-- Profit & Loss -->
  <a class="dash-card" href="{{url_for('profit_loss')}}">
    <img src="https://thumbs.dreamstime.com/b/d-rendering-depicting-scale-balancing-financial-assets-gold-coins-money-bag-charts-against-sustainability-icons-recycling-404568368.jpg" class="dash-icon">
    <p>Profit & Loss</p>
  </a>

  <!-- Reports -->
  <a class="dash-card" href="{{url_for('reports')}}">
    <img src="https://thumbs.dreamstime.com/z/data-analytics-dashboard-business-finance-report-landing-page-d-gradient-isometric-illustrations-suitable-ui-ux-web-mobile-284937951.jpg" class="dash-icon">
    <p>Reports</p>
  </a>
  <!-- Other Expenses -->
  <a class="dash-card" href="{{url_for('other_expenses')}}">
    <img src="https://img.freepik.com/free-vector/expense-concept-illustration_114360-1359.jpg?w=740" class="dash-icon">
    <p>Other Expenses</p>
  </a>
  <!-- Settings -->
  <a class="dash-card" href="{{url_for('settings')}}">
    <img src="https://png.pngtree.com/png-vector/20251021/ourmid/pngtree-3d-silver-gear-icon-setting-png-image_17779951.webp" class="dash-icon">
    <p>Settings</p>
  </a>
  <!-- Professional Backup & Restore Card (Icon on Top) -->
  <!-- <a href="{{ url_for('backup_restore') }}" class="dash-card" style="background: linear-gradient(145deg, #ffffff, #eef2ff); color: #1e293b; box-shadow: 0 15px 35px rgba(59, 130, 246, 0.2); transition: all 0.5s ease; border-radius: 24px;">
    
    <div style="text-align: center; padding: 35px 25px;">
      <img src="https://www.shutterstock.com/image-vector/secure-cloud-storage-icon-inside-600nw-2477264067.jpg" 
           alt="Backup & Restore" 
           class="dash-icon" 
           style="width: 100px; height: 100px; margin-bottom: 20px;">
      <p style="font-size: 24px; font-weight: bold; margin: 0; color: #1d4ed8;">Backup & Restore</p>
      <p style="font-size: 14px; margin: 12px 0 0; opacity: 0.8; color: #64748b;">Secure Data Backup & Recovery</p>
    </div>
    
    <div style="position: absolute; bottom: 14px; right: 14px; background: rgba(59, 130, 246, 0.1); padding: 8px 14px; border-radius: 30px; font-size: 13px; color: #1d4ed8;"> -->
    </div>
  </a>
</div>

<p style="text-align:center; margin-top:60px; color:#64748b; font-size:15px;">
  © 2025 Smart Invoice Pro | Developed by ISHTIAQ AHMAD MAGRAY | +923495820495
</p>
""" + TPL_F
    return render_template_string(html, project=get_setting("project_name"), month_total=f"{month_total:,.2f}")

# ---------- Products ----------
@app.route("/products", methods=["GET","POST"])
@login_required
def products():
    if request.method == "POST":
        act = request.form.get("action", "")
        rows = read_csv(PRODUCTS)

        if act == "save":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Product name required")
                return redirect(url_for("products"))

            sell_price_input = request.form.get("unit_price", "").strip()
            purchase_price_input = request.form.get("purchase_price", "").strip()  # نیا
            add_stock_input = request.form.get("stock", "0").strip()
            min_stock_input = request.form.get("min_stock", "0").strip()

            try:
                add_stock = max(0.0, float(add_stock_input or "0"))
                min_stock = max(0.0, float(min_stock_input or "0"))
            except:
                flash("Invalid stock values")
                return redirect(url_for("products"))

            existing = None
            for r in rows:
                if r["name"].lower() == name.lower():
                    existing = r
                    break

            if existing:
                if sell_price_input:
                    try:
                        existing["unit_price"] = f"{float(sell_price_input):.2f}"
                    except:
                        flash("Invalid selling price")
                        return redirect(url_for("products"))
                if purchase_price_input:  # نیا
                    try:
                        existing["purchase_price"] = f"{float(purchase_price_input):.2f}"
                    except:
                        flash("Invalid purchase price")
                        return redirect(url_for("products"))

                current = float(existing.get("stock", "0") or "0")
                existing["stock"] = f"{max(0.0, current + add_stock):.2f}"
                existing["min_stock"] = f"{min_stock:.2f}"
                flash(f"Updated: {name}")

            else:
                if not sell_price_input or not purchase_price_input:
                    flash("Both Selling & Purchase Price required for new product")
                    return redirect(url_for("products"))
                try:
                    sell_price = float(sell_price_input)
                    purchase_price = float(purchase_price_input)
                except:
                    flash("Invalid prices")
                    return redirect(url_for("products"))

                rows.append({
                    "name": name,
                    "unit_price": f"{sell_price:.2f}",
                    "purchase_price": f"{purchase_price:.2f}",  # نیا
                    "stock": f"{add_stock:.2f}",
                    "min_stock": f"{min_stock:.2f}"
                })
                flash(f"New product added: {name}")

            write_csv(PRODUCTS, rows, ["name","unit_price","purchase_price","stock","min_stock"])  # header update
            return redirect(url_for("products"))

        if act == "delete":
            name_del = request.form.get("name_del", "").strip()
            if name_del:
          # Case-insensitive comparison
                rows = [r for r in rows if r["name"].lower() != name_del.lower()]
                write_csv(PRODUCTS, rows, ["name","unit_price","purchase_price","stock","min_stock"])
                flash(f"Product deleted: {name_del}")
            else:
                flash("No product selected to delete")
            return redirect(url_for("products"))

    prods = load_products()

    # load_products فنکشن کو بھی اپڈیٹ کریں (نیچے دیا گیا ہے)

    html = TPL_H + """
<h3>Products / Stock Management</h3>

<div style="margin:20px 0;">
  <!-- نیا: خوبصورت اور فوری فلٹر والا سرچ -->
<div style="margin:30px 0; text-align:center;">
  <input type="text" id="prodSearchBox" placeholder="🔍 Enter product name..." 
         style="width:80%; max-width:600px; padding:14px; font-size:18px; border-radius:12px; border:2px solid #1976d2;">
</div>

<script>
document.getElementById('prodSearchBox').addEventListener('input', function() {
  const query = this.value.toLowerCase().trim();
  const rows = document.querySelectorAll('#prodTable tbody tr');
  
  rows.forEach(row => {
    const productName = row.querySelector('td:first-child').textContent.toLowerCase();
    if (query === '' || productName.includes(query)) {
      row.style.display = '';
    } else {
      row.style.display = 'none';
    }
  });
});
</script>
</div>

<form method="post">
  <input type="hidden" name="action" value="save">
  <div style="background:#f1f8e9; padding:20px; border-radius:12px; border:2px dashed #689f38; margin-bottom:25px;">
    <div style="display:grid; grid-template-columns: 300px 150px 150px 150px 160px 160px auto; gap:15px; align-items:end;">
      <div><label><strong>Product Name</strong></label>
        <input name="name" id="pname" list="prodlist" placeholder="Type or select" required autocomplete="off" style="width:100%; padding:11px; font-size:15px;">
        <datalist id="prodlist">
          {% for p in prods %}
            <option value="{{p.name}}" data-sell="{{p.unit_price}}" data-purchase="{{p.purchase_price or ''}}">
          {% endfor %}
        </datalist>
      </div>
      <div><label><strong>Selling Price</strong></label>
        <input name="unit_price" id="sell_price" type="number" step="any" placeholder="New price" style="width:100%;">
      </div>
      <div><label><strong>Purchase Price</strong></label>
        <input name="purchase_price" id="purchase_price" type="number" step="any" placeholder="Cost price" style="width:100%;">
      </div>
      <div><label><strong>Add Stock</strong></label>
        <input name="stock" type="number" step="any" min="0" value="0">
      </div>
      <div><label><strong>Min Stock</strong></label>
        <input name="min_stock" type="number" step="any" min="0">
      </div>
    </div> <!-- grid بند -->

    <div style="text-align:center; margin-top:25px;">
      <button type="submit" class="btn" style="background:#2e7d32; color:white; padding:16px 80px; font-size:20px; border-radius:12px; font-weight:bold; box-shadow:0 4px 10px rgba(0,0,0,0.15);">
        Save Product / Update Stock
      </button>
    </div>
  </div> <!-- background div -->
</form>
<table id="prodTable">
  <thead style="background:#1976d2; color:black:bold;">
    <tr><th>Product</th><th>Selling Price</th><th>Purchase Price</th><th>Stock</th><th>Min Stock</th><th>Status</th><th>Delete</th></tr>
  </thead>
  <tbody>
    {% for p in prods %}
    <tr {% if p.stock <= p.min_stock %}style="background:#ffebee;"{% endif %}>
      <td style="padding:10px; font-weight:600;">{{p.name}}</td>
      <td>Rs {{'%.2f'|format(p.unit_price)}}</td>
      <td>Rs {{'%.2f'|format(p.purchase_price or 0)}}</td>
      <td style="text-align:center; font-weight:bold;">{{'%.2f'|format(p.stock)}}</td>
      <td style="text-align:center;">{{'%.f'|format(p.min_stock)}}</td>
      <td style="text-align:center;">
        {% if p.stock <= p.min_stock %}<span style="color:red; font-weight:bold;">LOW!</span>{% else %}<span style="color:green;">OK</span>{% endif %}
      </td>
      <td>
        <form method="post" style="display:inline;">
          <input type="hidden" name="action" value="delete">
          <input type="hidden" name="name_del" value="{{p.name}}">
          <button class="btn" style="background:#c62828;" onclick="return confirm('Delete {{p.name}}?')">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
<script>
function selectProduct(el) {
  document.getElementById('pname').value = el.dataset.name;
  document.getElementById('sell_price').value = el.dataset.sell;
  document.getElementById('purchase_price').value = el.dataset.purchase;
  document.getElementById('filteredProducts').style.display = 'none';
}

document.getElementById('pname').addEventListener('input', function() {
  const query = this.value.toLowerCase().trim();
  const container = document.getElementById('filteredProducts');
  const options = container.querySelectorAll('.prod-option');
  
  if (query === '') {
    container.style.display = 'none';
    return;
  }
  
  let hasMatch = false;
  options.forEach(opt => {
    const name = opt.dataset.name.toLowerCase();
    if (name.includes(query)) {
      opt.style.display = 'block';
      hasMatch = true;
    } else {
      opt.style.display = 'none';
    }
  });
  
  container.style.display = hasMatch ? 'block' : 'none';
});

// باہر کلک کرنے پر لسٹ چھپ جائے
document.addEventListener('click', function(e) {
  if (!e.target.closest('#pname') && !e.target.closest('#filteredProducts')) {
    document.getElementById('filteredProducts').style.display = 'none';
  }
});
</script>
<script>
document.getElementById('pname').addEventListener('input', function() {
  const val = this.value.trim().toLowerCase();
  if (!val) return;
  const opts = document.querySelectorAll('#prodlist option');
  for (let opt of opts) {
    if (opt.value.toLowerCase() === val.toLowerCase()) {
      document.getElementById('sell_price').value = opt.dataset.sell || '';
      document.getElementById('purchase_price').value = opt.dataset.purchase || '';
      document.getElementById('sell_price').placeholder = 'Current: Rs ' + opt.dataset.sell;
      document.getElementById('purchase_price').placeholder = 'Current: Rs ' + (opt.dataset.purchase || '0');
      return;
    }
  }
  document.getElementById('sell_price').value = '';
  document.getElementById('purchase_price').value = '';
  document.getElementById('sell_price').placeholder = 'Required';
  document.getElementById('purchase_price').placeholder = 'Required';
});
</script>
""" + TPL_F

    return render_template_string(html, prods=prods, project=get_setting("project_name"))


# ---------- Customers ----------
@app.route("/customers", methods=["GET","POST"])
@login_required
def customers():
    if request.method == "POST":
        act = request.form.get("action","save")
        if act == "save":
            name = to_caps(request.form.get("name",""))
            addr = to_caps(request.form.get("address",""))
            phone = request.form.get("phone","")
            if not name:
                flash("Name required"); return redirect(url_for("customers"))
            rows = read_csv(CUSTOMERS)
            done = False
            for r in rows:
                if to_caps(r["name"]) == name and to_caps(r["address"]) == addr:
                    r["phone"] = phone; done = True
            if not done:
                rows.append({"name": name, "address": addr, "phone": phone})
            write_csv(CUSTOMERS, rows, ["name","address","phone"])
            flash("Saved")
            return redirect(url_for("customers"))
        if act == "delete":
            name_del = to_caps(request.form.get("name_del",""))
            addr_del = to_caps(request.form.get("addr_del",""))
            rows = [r for r in read_csv(CUSTOMERS) if not (to_caps(r["name"])==name_del and to_caps(r["address"])==addr_del)]
            write_csv(CUSTOMERS, rows, ["name","address","phone"])
            flash("Customer deleted")
            return redirect(url_for("customers"))
    custs = load_customers()
    html = TPL_H + """
<h3>Customers</h3>
<form method="post" class="top">
  <input type="hidden" name="action" value="save">
  <input name="name" list="cust_names" placeholder="Customer" required>
  <datalist id="cust_names">{% for c in custs %}<option value="{{c.name}}">{% endfor %}</datalist>
  <input name="address" list="cust_addr" placeholder="Address" required>
  <datalist id="cust_addr">{% for c in custs %}<option value="{{c.address}}">{% endfor %}</datalist>
  <input name="phone" placeholder="Phone">
  <button class="btn">Save / Update</button>
</form>

<form method="post" class="top">
  <input type="hidden" name="action" value="delete">
  <select name="name_del"><option value="">-- select customer name --</option>{% for c in custs %}<option>{{c.name}}</option>{% endfor %}</select>
  <select name="addr_del"><option value="">-- select address --</option>{% for c in custs %}<option>{{c.address}}</option>{% endfor %}</select>
  <button class="btn" onclick="return confirm('Delete selected customer?')">Delete</button>
</form>

<table style="width:100%; border-collapse:collapse;">
  <thead style="background:#f0f0f0;">
    <tr>
      <th style="width:70px; text-align:center; padding:10px;">Sr. No.</th>
      <th style="padding:10px;">Name</th>
      <th style="padding:10px;">Address</th>
      <th style="padding:10px;">Phone</th>
    </tr>
  </thead>
  <tbody>
    {% for c in custs %}
    <tr style="border-bottom:1px solid #eee;">
      <td style="text-align:center; padding:10px; font-weight:600; color:#1976d2;">{{ loop.index }}</td>
      <td style="padding:10px;">{{ c.name }}</td>
      <td style="padding:10px;">{{ c.address }}</td>
      <td style="padding:10px;">{{ c.phone }}</td>
    </tr>
    {% endfor %}
    {% if not custs %}
    <tr>
      <td colspan="4" style="text-align:center; padding:30px; color:#999;">No customers added yet</td>
    </tr>
    {% endif %}
  </tbody>
</table>
""" + TPL_F
    return render_template_string(html, custs=custs, project=get_setting("project_name"))


# ---------- New Invoice ----------
# ================== NEW & EDIT INVOICE - FINAL WORKING VERSION ==================
# ================= Check if editing an existing invoice =================
@app.route("/invoice/new", methods=["GET","POST"])
@login_required
def new_invoice():
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

        # ===== Pending Amount Logic (نیا) =====
        pending_input = request.form.get("pending_amount", "").strip()
        try:
            pending_added = float(pending_input) if pending_input else 0.0
        except:
            pending_added = 0.0

        # اگر سیٹنگ آن ہے تو پچھلا pending خود ڈال دو (اگر یوزر نے کچھ نہ بھرا)
        if get_setting("show_pending", "0") == "1" and pending_added == 0.0:
            pending_added = get_pending(name, addr)
        # ======================================

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

        inv_no = get_seq("invoice_no", int(get_setting("invoice_start","100")))
        set_seq("invoice_no", inv_no + 1)
        date_str_display = fmt_date()           # PDF اور ڈسپلے کے لیے dd-mm-yy  
        date_str_db = fmt_date(for_db=True)     # SQLite کے لیے 2026-01-01  
        gross = sum(float(li["qty"]) * float(li["unit_price"]) for li in lines)
        total = gross * (1 + tax/100.0)

        # نیا: pending_added بھی سیو کرو
        grand_total = gross + (gross * tax / 100) + pending_added

        append_csv(
            INVOICES,
            {"inv_no": inv_no, "date": date_str_display, "name": name, "address": addr, "phone": phone,
            "tax": f"{tax:.2f}", "total": f"{grand_total:.2f}", "logo_path": (logo or ""), "pending_added": f"{pending_added:.2f}"},
            ["inv_no","date","name","address","phone","tax","total","logo_path","pending_added"]
        )
        for li in lines:
            append_csv(LINES, {"inv_no": inv_no, "product": li["product"], "qty": f"{li['qty']}", "unit_price": f"{li['unit_price']}"}, ["inv_no","product","qty","unit_price"])

                # ===== یہ 12 لائنیں یہاں پیسٹ کرو (append_csv(LINES, ...) کے فوراً بعد) =====
        # Sales Log میں بھی انٹری ڈالو (تاکہ Sales Record میں دکھے)
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            for li in lines:
                c.execute("""
                    INSERT INTO sales_log (date, inv_no, product, qty, sell_price)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str_db, inv_no, li["product"], li["qty"], li["unit_price"]))
            conn.commit()
            conn.close()
        except Exception as e:
            print("Sales log insert error:", e)  # کنسول پر دیکھنے کے لیے
        # =============================================================================
        ensure_customer(name, addr, phone)

        # decrement stock
        # ===== Decrement stock properly =====
        rows = read_csv(PRODUCTS)
        for li in lines:
            prod_name = li["product"].strip()
            qty_sold = float(li.get("qty", 0) or 0)
            for r in rows:
                if r["name"].strip().lower() == prod_name.lower():  # case-insensitive match
                    current_stock = float(r.get("stock", 0) or 0)
                    new_stock = max(0.0, current_stock - qty_sold)
                    r["stock"] = f"{new_stock:.2f}"
                    break  # product found, no need to loop further
        write_csv(PRODUCTS, rows, ["name","unit_price","purchase_price","stock","min_stock"])


        now = datetime.datetime.now()
        year = now.year
        month = now.strftime("%B")
        out_dir = ensure_out_dirs(year, month)

        pdf_name = f"INV_{inv_no}_{safe_name(name)}_{safe_name(addr)}.pdf"
        out_path = out_dir / pdf_name
        draw_invoice_pdf(out_path, company, logo, show_logo, inv_no, date_str_display, name, addr, phone, lines, tax, pending_added)

        if not out_path.exists():
            flash(f"Invoice saved but PDF not found: {out_path}")
            return redirect(url_for("new_invoice"))

        pdf_url = url_for('view_pdf', y=year, m=month, fn=pdf_name)
        redirect_url = url_for('new_invoice')

        # Build HTML without using Python f-strings for JS braces. Use placeholder replacement.
        html_template = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Invoice Created</title></head>
<body>
<script>
  try {
    localStorage.removeItem('invoice_draft_v1');
  } catch(e) {}
  var w = window.open("{PDF_URL}", "_blank");
  if (!w) {
    window.location = "{PDF_URL}";
  } else {
    setTimeout(function(){ window.location = "{REDIRECT}"; }, 700);
  }
</script>
<p>Invoice created. Opening PDF for print...</p>
</body>
</html>
"""
        html = html_template.replace("{PDF_URL}", pdf_url + "?print=1").replace("{REDIRECT}", redirect_url)
        flash(f"Invoice #{inv_no} created.")
        return html

    # GET: render form (script uses localStorage but not inside f-strings)
    prods = load_products(); custs = load_customers()
    company = get_setting("company_name","Smart Invoice")
    tax_def = float(get_setting("tax_default","0") or "0")
    html = TPL_H + """

<h3>New Invoice</h3>
<div class="flex">
  <div style="flex:1">
    <form method="post" id="invoiceForm">
      <div class="top">
  <div>
    <input name="name" id="cname" list="cust_names" placeholder="Customer Name" required>
    <datalist id="cust_names">{% for c in custs %}<option value="{{c.name}}">{% endfor %}</datalist>

    <input name="address" id="caddr" list="cust_addr" placeholder="Address" required>
    <datalist id="cust_addr">{% for c in custs %}<option value="{{c.address}}">{% endfor %}</datalist>

    <input name="phone" id="cphone" placeholder="Phone">

    <input name="tax" placeholder="Tax % (default {{tax_def}})" type="number" step="0.01">
    <input name="pending_amount" id="pending_amount" type="number" step="any" min="0" placeholder="Pending Amount (auto if enabled)" style="width:220px; margin-left:10px;">
  </div>
  <div><span class="small">Company: {{company}}</span></div>
</div>

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

      <p><button class="btn">Save & PDF</button></p>
    </form>
  </div>

  <div class="side">
    <div class="card"><h3>Customer History & Pending</h3>
      <div id="hist" class="small">Type name & address…</div>
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
      alert(`غلطی: "${select.value}" کی سیلنگ پرائس خریداری قیمت سے کم نہیں ہو سکتی!\nکم از کم: Rs ${minPrice}`);

      // یہ تین لائنیں روکنے میں مدد دیں گی
      priceInput.focus();
      priceInput.select();              // متن سلیکٹ ہو جائے
      priceInput.style.border = "3px solid red";  // زیادہ نمایاں

      return false;   // یہ لائن فارم کو روک دے گی
    }
  }

  // اگر کوئی غلطی نہ ہو تو فارم جانے دیں
  return true;
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
            const message = `پچھلا بقایا: Rs ${pending.toFixed(2)}\nکیا یہ رقم شامل کرکے انوائس بنائیں؟`;

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
const prods = {{ prods|tojson }};
let row=0;
const DKEY = "invoice_draft_v1";

function saveDraft(){
  try {
    const cname = document.getElementById('cname').value||"";
    const caddr = document.getElementById('caddr').value||"";
    const cphone = document.getElementById('cphone').value||"";
    const tax = document.querySelector('input[name="tax"]').value||"";
    const rows = [];
    for(const r of document.querySelectorAll("#tbl tbody tr")){
      const sel = r.querySelector("select");
      const qty = r.querySelector("input[name^='qty_']");
      if(sel && sel.value){
        rows.push({product: sel.value, qty: qty.value||""});
      }
    }
    localStorage.setItem(DKEY, JSON.stringify({name:cname,address:caddr,phone:cphone,tax:tax,rows:rows}));
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
    const tb=document.querySelector("#tbl tbody"); tb.innerHTML=""; row=0;
    if(o.rows && o.rows.length){
      for(const r of o.rows){
        addRow();
        const i = row-1;
        const sel = document.querySelector(`select[name="prod_${i}"]`);
        const qty = document.querySelector(`input[name="qty_${i}"]`);
        if(sel) sel.value = r.product;
        if(qty) qty.value = r.qty;
        setTimeout(()=>{ if(document.querySelector(`select[name="prod_${i}"]`)) setInfo(document.querySelector(`select[name="prod_${i}"]`), i); calc(); }, 10);
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
    <td><input name="u_${row}" id="u_${row}" type="number" step="any" oninput="calc()" style="font-weight:bold;"></td>
    <td><input id="t_${row}" disabled></td>
    <td><button type="button" class="btn" onclick="this.closest('tr').remove(); calc(); saveDraft();">X</button></td>
  `;
  tb.appendChild(tr); row++; calc(); saveDraft();
}
function setInfo(sel, i) {
  const p = prods.find(x => x.name === sel.value);
  const u = document.getElementById('u_' + i);
  if (p) {
    u.value = p.unit_price;
    u.dataset.minPrice = p.purchase_price || 0;  // کم سے کم پرائس سیٹ کر دی
  } else {
    u.value = "";
    u.dataset.minPrice = 0;
  }
  calc(); 
  loadHist(); 
  saveDraft();
  
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
  let total_qty = 0;  // نیا: کل qty جمع کرنے کے لیے
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

    t.value = (isNaN(q) || isNaN(up)) ? "" : (q * up).toFixed(2);
    sum += (isNaN(q) || isNaN(up)) ? 0 : q * up;
    total_qty += isNaN(q) ? 0 : q;  // qty جمع کرو
  }

  // اب دونوں دکھاؤ: کل qty اور کل رقم
  document.getElementById("sumline").innerHTML = 
    `<strong>Total Qty: ${total_qty.toFixed(2)}</strong> &nbsp;&nbsp;&nbsp; 
     <strong>Current Total: Rs ${sum.toFixed(2)}</strong>`;

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
  if(!n||!a){ document.getElementById('hist').innerText='Type name & address…'; return; }
  fetch(`/api/history?name=${encodeURIComponent(n)}&address=${encodeURIComponent(a)}`).then(r=>r.json()).then(d=>{
    if(d.rows.length==0){ document.getElementById('hist').innerText='No history yet'; return; }
    let html = '<p><strong>Pending: Rs ' + (d.pending||0).toFixed(2) + '</strong></p>';
    // Auto fill pending if setting is on
    const pendField = document.getElementById('pending_amount');
    if (pendField && (pendField.value === '' || pendField.value === '0')) {
      pendField.value = (d.pending || 0).toFixed(2);
    }
    html += '<table><tr><th>Inv#</th><th>Date</th><th>Total</th><th>Received</th><th>Pending</th><th>PDF</th></tr>';
    for(const r of d.rows){
      html += `<tr><td>${r.inv_no}</td><td>${r.date}</td><td>${r.total}</td><td>${r.received.toFixed(2)}</td><td>${r.pending.toFixed(2)}</td><td><a class="link" target="_blank" href="${r.pdf}">PDF</a></td></tr>`;
    }
    html += '</table>';
    document.getElementById('hist').innerHTML = html;
  });
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
document.getElementById('cphone').addEventListener('input', saveDraft);
document.querySelector('input[name="tax"]').addEventListener('input', saveDraft);
</script>
""" + TPL_F

    return render_template_string(html, prods=prods, custs=custs,
        company=company, tax_def=tax_def, project=get_setting("project_name"))

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
    name=to_caps(request.args.get("name","")); addr=to_caps(request.args.get("address",""))
    invs = [r for r in read_csv(INVOICES) if to_caps(r["name"])==name and to_caps(r["address"])==addr]
    pays = read_csv(PAYMENTS)
    pay_map = {}
    for p in pays:
        try: i=int(p["inv_no"]); pay_map[i]=pay_map.get(i,0.0)+float(p.get("amount","0") or 0)
        except: pass
    out=[]; total_pending = 0.0
    for r in invs[-50:]:
        inv = int(r["inv_no"])
        total = float(r.get("total","0") or 0)
        recvd = pay_map.get(inv,0.0)
        pend = max(total - recvd, 0.0)
        total_pending += pend
        try:
            d=r["date"]
            if "-" in d and len(d.split("-")[2])==2:
                dt=datetime.datetime.strptime(d,"%d-%m-%y")
            elif "-" in d and len(d.split("-")[2])==4:
                dt=datetime.datetime.strptime(d,"%d-%m-%Y")
            else:
                dt=datetime.datetime.strptime(d,"%Y-%m-%d")
            y=dt.year; m=dt.strftime("%B")
        except:
            now=datetime.datetime.now(); y=now.year; m=now.strftime("%B")
        fn = f"INV_{r['inv_no']}_{safe_name(name)}_{safe_name(addr)}.pdf"
        out.append({"inv_no": inv, "date": r["date"], "total": total, "received": recvd, "pending": pend, "pdf": url_for("open_pdf_path", y=y, m=m, fn=fn)})
    return jsonify({"rows":out, "pending": total_pending})

@app.route("/api/pending")
@login_required
def api_pending():
    name = to_caps(request.args.get("name",""))
    addr = to_caps(request.args.get("address",""))
    if not name or not addr:
        return jsonify({"pending": 0.0})

    invs = read_csv(INVOICES)
    pays = read_csv(PAYMENTS)
    pay_map = {}
    for p in pays:
        try:
            i = int(p["inv_no"])
            pay_map[i] = pay_map.get(i, 0.0) + float(p.get("amount",0) or 0)
        except: pass

    pending = 0.0
    for inv in invs:
        if to_caps(inv.get("name","")) == name and to_caps(inv.get("address","")) == addr:
            try:
                total = float(inv.get("total",0) or 0)
                inv_no = int(inv.get("inv_no",0))
                pending += max(total - pay_map.get(inv_no, 0), 0, 0)
            except: pass
    return jsonify({"pending": round(pending, 2)})

# ---------- Payments ----------
# ================================================
@app.route("/payments", methods=["GET","POST"])
@login_required
def payments():
    invs = read_csv(INVOICES)       # <--- یہ لائن لازمی شامل کریں
    pays = read_csv(PAYMENTS)
    if request.method == "POST":
        action = request.form.get("action","")
        
        # Bulk adjustment with method selection
        if action == "bulk_set":
            pays = read_csv(PAYMENTS)
            modified = 0
            selected_method = request.form.get("payment_method", "Cash")  # نیا: میتھڈ منتخب
                        # پہلے remarks save کریں
            for key, val in request.form.items():
                if key.startswith("remark_"):
                    try:
                        inv_no = int(key.split("_")[-1])  # remark_105 → 105
                        new_remark = val.strip()
                        # انوائس میں remarks اپڈیٹ کریں
                        for inv in invs:
                            if int(inv.get("inv_no", 0) or 0) == inv_no:
                                inv["remarks"] = new_remark
                                break
                    except:
                        pass
            # remarks save ہو گئیں تو INVOICES فائل لکھ دیں
            write_csv(INVOICES, invs, ["inv_no","date","name","address","phone","tax","total","logo_path","pending_added","remarks"])
            modified = 1  # تاکہ flash میسج آئے
            for key, val in request.form.items():
                if not key.startswith("set_received_"): 
                    continue
                try:
                    inv_no = int(key.split("_")[-1])
                    desired = float(val or 0)
                except: 
                    continue
                
                # موجودہ received کا حساب
                current = 0.0
                for p in pays:
                    try:
                        if int(p.get("inv_no","")) == inv_no:
                            current += float(p.get("amount","0") or 0)
                    except: 
                        continue
                
                diff = round(desired - current, 2)
                if abs(diff) >= 0.005:
                    # نیا adjustment payment ریکارڈ کریں
                    pid = get_seq("pay_id", 1)
                    set_seq("pay_id", pid + 1)
                    append_csv(PAYMENTS, {
                        "pay_id": pid,
                        "inv_no": inv_no,
                        "date": fmt_date(),  # آج کی تاریخ
                        "amount": f"{diff:.2f}",
                        "method": selected_method,  # منتخب کردہ میتھڈ
                        "customer": "",
                        "address": "",
                        "note": "Manual adjustment via Payments Sheet"
                    }, ["pay_id","inv_no","date","amount","method","customer","address","note"])
                    # === AUTO UPDATE CUSTOMER PENDING AFTER ADJUSTMENT ===
                    # Payments Sheet سے received تبدیل کرنے پر customer_pending بھی اپ ڈیٹ ہو جائے
                    inv_row = next((i for i in invs if str(i.get("inv_no","")) == str(inv_no)), None)
                    if inv_row:
                        cust_name = to_caps(inv_row.get("name", ""))
                        cust_addr = to_caps(inv_row.get("address", ""))
                        if cust_name and cust_addr:
                            # اس کسٹمر کے سارے انوائسز کا کل total
                            customer_invoices = [i for i in invs if to_caps(i.get("name","")) == cust_name and to_caps(i.get("address","")) == cust_addr]
                            total_due = sum(float(i.get("total","0") or 0) for i in customer_invoices)
                            
                            # اس کسٹمر کے سارے پیمنٹس کا کل received
                            total_received = 0.0
                            for p in pays:
                                if p.get("inv_no", "") == str(inv_no):
                                    total_received += float(p.get("amount","0") or 0)
                            
                            # adjustment کے بعد نیا received شامل کرو
                            total_received += diff
                            
                            # نیا باقی pending
                            new_pending = max(0.0, total_due - total_received)
                            update_pending(cust_name, cust_addr, new_pending)
                    # =====================================================
                    modified += 1
            
            flash(f"{modified} adjustment(s) recorded with method: {selected_method}")
            return redirect(url_for("payments"))
        
        # Export CSV
        if action == "export_csv":
            inv_no_q = request.form.get("filter_inv_no","").strip()
            name_q = request.form.get("filter_name","").strip().lower()
            addr_q = request.form.get("filter_address","").strip().lower()
            date_q = request.form.get("filter_date","").strip()
            invs = read_csv(INVOICES)
            pays = read_csv(PAYMENTS)
            rows = []
            for r in invs:
                if inv_no_q and str(r.get("inv_no","")) != inv_no_q: continue
                if name_q and name_q not in r.get("name","").lower(): continue
                if addr_q and addr_q not in r.get("address","").lower(): continue
                if date_q and date_q not in r.get("date",""): continue
                try: invn = int(r.get("inv_no"))
                except: continue
                total = float(r.get("total","0") or 0)
                received = sum(float(p.get("amount","0") or 0) for p in pays if str(p.get("inv_no","")) == str(invn))
                pending = max(total - received, 0.0)
                rows.append({"inv_no": invn, "date": r.get("date",""), "customer": r.get("name",""), "address": r.get("address",""),
                             "total": f"{total:.2f}", "received": f"{received:.2f}", "pending": f"{pending:.2f}"})
            si = io.StringIO()
            cw = csv.DictWriter(si, fieldnames=["inv_no","date","customer","address","total","received","pending"])
            cw.writeheader()
            cw.writerows(rows)
            mem = io.BytesIO()
            mem.write(si.getvalue().encode("utf-8"))
            mem.seek(0)
            return Response(mem.read(), mimetype="text/csv", 
                            headers={"Content-Disposition": "attachment;filename=payments_export.csv"})
    
    # GET request - فلٹر اور ڈسپلے
    inv_no_q = request.args.get("inv_no","").strip()
    name_q = request.args.get("name","").strip().lower()
    addr_q = request.args.get("address","").strip().lower()
    date_q = request.args.get("date","").strip()
    
    invs = read_csv(INVOICES)
    pays = read_csv(PAYMENTS)
    # نئی انوائس (اور پیمنٹس) سب سے اوپر دکھانے کے لیے sorting
    def sort_key(r):
        date_str = r.get("date", "01-01-00")
        parts = date_str.split("-")
        if len(parts) != 3:
            year, month, day = 2000, 1, 1
        else:
            day = int(parts[0] or 1)
            month = int(parts[1] or 1)
            year = 2000 + int(parts[2]) if len(parts[2]) == 2 else int(parts[2] or 2000)
        inv_no = int(r.get("inv_no", 0) or 0)
        return (year, month, day, inv_no)

    invs.sort(key=sort_key, reverse=True)  # نئی انوائس سب سے اوپر
    display_rows = []
    total_received_sum = 0.0
    total_pending_sum = 0.0
    
    for r in invs:
        if inv_no_q and str(r.get("inv_no","")) != inv_no_q: continue
        if name_q and name_q not in r.get("name","").lower(): continue
        if addr_q and addr_q not in r.get("address","").lower(): continue
        if date_q and date_q not in r.get("date",""): continue
        try: invn = int(r.get("inv_no"))
        except: continue
        
        # Total = اصل grand total (pending سمیت)
        total = float(r.get("total","0") or 0)
        received = sum(float(p.get("amount","0") or 0) for p in pays if str(p.get("inv_no","")) == str(invn))
        pending = round(max(total - received, 0.0), 2)

        total_received_sum += received
        total_pending_sum += pending

        display_rows.append({
            "inv_no": invn,
            "date": r.get("date",""),
            "customer": r.get("name",""),
            "address": r.get("address",""),
            "total": f"{total:.2f}",
            "received": f"{received:.2f}",
            "pending": f"{pending:.2f}",
            "remarks": r.get("remarks", "")
        })
    
    html = TPL_H + """
<h3>Payments Sheet — Received & Pending</h3>

<!-- Filter -->
<form method="get" class="top">
  <input name="inv_no" placeholder="Invoice #" value="{{request.args.get('inv_no','')}}" style="width:110px">
  <input name="name" placeholder="Customer Name" value="{{request.args.get('name','')}}" style="width:180px">
  <input name="address" placeholder="Address" value="{{request.args.get('address','')}}" style="width:180px">
  <input name="date" placeholder="Date (e.g. 31-12)" value="{{request.args.get('date','')}}" style="width:140px">
  <button class="btn">Filter</button> 
  <a class="link" href="{{url_for('payments')}}">Clear Filter</a>
</form>

<p style="font-size:18px; margin:15px 0;">
  <strong>Total Received:</strong> Rs {{'%.2f'|format(total_received_sum)}} | 
  <strong>Total Pending:</strong> <span style="color:#d32f2f;">Rs {{'%.2f'|format(total_pending_sum)}}</span>
</p>

<!-- Bulk Edit Form -->
<form method="post" onsubmit="return confirm('Save all changes? This will record adjustments with selected method.')">
  <input type="hidden" name="action" value="bulk_set">
  
  <div style="margin-bottom:15px;">
    <label><strong>Adjustment Method:</strong></label>
    <select name="payment_method" style="padding:10px; font-size:16px; margin-left:10px;">
      <option value="Cash">Cash</option>
      <option value="Bank Transfer">Bank Transfer</option>
      <option value="JazzCash">JazzCash</option>
      <option value="EasyPaisa">EasyPaisa</option>
      <option value="Cheque">Cheque</option>
      <option value="Online">Online</option>
      <option value="Adjustment">Adjustment Only</option>
    </select>
  </div>

  <table style="width:100%; border-collapse:collapse;">
    <thead style="background:#1976d2; color:white;">
      <tr>
        <th style="padding:12px;">Invoice</th>
        <th style="padding:12px;">Date</th>
        <th style="padding:12px;">Customer</th>
        <th style="padding:12px;">Address</th>
        <th style="padding:12px; text-align:right;">Total</th>
        <th style="padding:12px; text-align:center;">Received (Edit)</th>
        <th style="padding:12px; text-align:right; color:#d32f2f;">Pending</th>
        <th style="padding:12px; width:250px;">Manual Remark / Note</th>
      </tr>
    </thead>
    <tbody>
    {% for r in display_rows %}
      <tr {% if r.pending != '0.00' %}style="background:#fff3e0;"{% endif %}>
        <td style="padding:12px;">{{r.inv_no}}</td>
        <td style="padding:12px;">{{r.date}}</td>
        <td style="padding:12px;"><strong>{{r.customer}}</strong></td>
        <td style="padding:12px;">{{r.address}}</td>
        <td style="padding:12px; text-align:right;">Rs {{r.total}}</td>
        <td style="padding:12px; text-align:center;">
          <input name="set_received_{{r.inv_no}}" value="{{r.received}}" 
                 style="width:120px; padding:8px; text-align:right; font-weight:bold;" 
                 type="number" step="0.01">
        </td>
        <td style="padding:12px; text-align:right; font-size:18px; font-weight:bold;">Rs {{r.pending}}</td>
        <td style="padding:12px;">
  <input name="remark_{{r.inv_no}}" value="{{ r.remarks or '' }}" 
         placeholder="Type note..." 
         style="width:100%; padding:10px; border:1px solid #ccc; border-radius:6px; font-size:14px;">
</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <div style="margin-top:20px; text-align:center;">
    <button class="btn" style="background:#2e7d32; padding:14px 40px; font-size:18px;">Save All Changes</button>
    <button class="btn" name="action" value="export_csv" formaction="{{url_for('payments')}}" formmethod="post"
            style="background:#1565c0; margin-left:20px;">Export to CSV</button>
    <a class="link" href="{{url_for('home')}}" style="margin-left:30px;">← Back to Home</a>
  </div>
</form>

<p class="small" style="margin-top:30px; color:#666;">
  نوٹ: Received میں تبدیلی کرنے پر خود بخود Adjustment Payment ریکارڈ ہو جائے گا (date: آج کی، method: منتخب کردہ)
</p>
""" + TPL_F

    return render_template_string(html,
                                  display_rows=display_rows,
                                  total_received_sum=total_received_sum,
                                  total_pending_sum=total_pending_sum,
                                  request=request,
                                  project=get_setting("project_name"))
# ================================================
# ---------- Invoices List (with monthly sub-cards) ----------
# ---------- invoices list (shortened) ----------
@app.route("/invoices", methods=["GET","POST"])
@login_required
def invoices_list():

    # ================= POST ACTIONS =================
    if request.method == "POST":
        act = request.form.get("action","")

        if act == "delete":
            del_inv = request.form.get("inv_no_del","")
            if del_inv:
                all_lines = read_csv(LINES)
                prod_rows = read_csv(PRODUCTS)

                # restore stock
                for l in all_lines:
                    if str(l.get("inv_no")) == str(del_inv):
                        pname = l.get("product")
                        try: qty = float(l.get("qty","0") or 0)
                        except: qty = 0
                        for p in prod_rows:
                            if p["name"] == pname:
                                p["stock"] = f"{float(p.get('stock','0') or 0) + qty:.2f}"

                write_csv(PRODUCTS, prod_rows,
                          ["name","unit_price","purchase_price","stock","min_stock"])

                invs = [r for r in read_csv(INVOICES)
                        if str(r.get("inv_no")) != str(del_inv)]
                write_csv(INVOICES, invs,
                          ["inv_no","date","name","address","phone","tax","total",
                           "logo_path","pending_added","remarks"])

                lines = [l for l in all_lines
                         if str(l.get("inv_no")) != str(del_inv)]
                write_csv(LINES, lines, ["inv_no","product","qty","unit_price"])

                flash(f"Invoice {del_inv} deleted")
            return redirect(url_for("invoices_list"))

    # ================= GET LIST =================
    import datetime
    from collections import defaultdict

    rows = read_csv(INVOICES)

    def parse_date(d):
        try:
            return datetime.datetime.strptime(d, "%d-%m-%y")
        except:
            try:
                return datetime.datetime.strptime(d, "%d-%m-%Y")
            except:
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
            key=lambda x: datetime.datetime.strptime(x[0], "%B %Y"),
            reverse=True
        )
    )

    for m in monthly_sorted:
        monthly_sorted[m].sort(
            key=lambda r: (r["_dt"], int(r.get("inv_no",0))),
            reverse=True
        )

    # -------- SUMMARY --------
    summary = {
        m: {
            "count": len(invs),
            "total": sum(float(i.get("total","0") or 0) for i in invs)
        }
        for m, invs in monthly_sorted.items()
    }

    # ================= HTML =================
    html = TPL_H + """
<h3>All Invoices (Monthly)</h3>

<input type="text" id="invSearch"
 placeholder="🔍 Search invoice #, customer, address..."
 style="width:100%;max-width:520px;padding:10px;
        margin:15px 0;border-radius:8px;border:1px solid #ccc;">

{% for month, invs in monthly.items() %}
<div class="card month-card" style="margin-bottom:14px;">

  <div class="month-header"
       onclick="toggleMonth('{{ loop.index }}')"
       style="cursor:pointer;display:flex;
              justify-content:space-between;
              font-weight:bold;font-size:16px;">
    <span>📁 {{ month }}</span>
    <span>
      Invoices: {{ summary[month].count }}
      | Sales: Rs {{ '%.2f'|format(summary[month].total) }}
    </span>
  </div>

  <div id="month_{{ loop.index }}" class="month-body"
       style="display:none;margin-top:10px;">
    <table>
      <tr>
        <th>Inv#</th><th>Date</th><th>Customer</th>
        <th>Address</th><th>Total</th><th>PDF</th><th>Action</th>
      </tr>

      {% for r in invs %}
      <tr class="inv-row">
        <td>{{r.inv_no}}</td>
        <td>{{r.date}}</td>
        <td>{{r.name}}</td>
        <td>{{r.address}}</td>
        <td>{{r.total}}</td>
        <td>
          <a class="link" target="_blank"
             href="{{ url_for('find_view_pdf', inv=r.inv_no) }}">View</a>
        </td>
        <td>
          <form method="post" style="display:inline">
            <input type="hidden" name="action" value="delete">
            <input type="hidden" name="inv_no_del" value="{{r.inv_no}}">
            <button class="btn"
              onclick="return confirm('Delete invoice {{r.inv_no}}?')">
              Delete
            </button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>

</div>
{% endfor %}

<script>
function toggleMonth(id){
  const el = document.getElementById("month_" + id);
  el.style.display = (el.style.display === "none") ? "block" : "none";
}

// -------- LIVE SEARCH --------
document.getElementById("invSearch").addEventListener("input", function(){
  const q = this.value.toLowerCase();

  document.querySelectorAll(".inv-row").forEach(row => {
    row.style.display = row.innerText.toLowerCase().includes(q) ? "" : "none";
  });

  document.querySelectorAll(".month-body").forEach(m => {
    const visible = m.querySelectorAll(".inv-row:not([style*='display: none'])");
    m.style.display = visible.length ? "block" : "none";
  });
});
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
    for r in read_csv(INVOICES):
        if str(r.get("inv_no")) == str(inv):
            name_safe = safe_name(to_caps(r.get("name","")))
            addr_safe = safe_name(to_caps(r.get("address","")))
            fn = f"INV_{r['inv_no']}_{name_safe}_{addr_safe}.pdf"
            base = output_base() / "BusinessRecords"
            for p in base.rglob(fn):
                pdf_path = p
                break
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
    invoices = read_csv(INVOICES)
    invoice = next((r for r in invoices if int(r["inv_no"]) == inv_no), None)
    if not invoice:
        flash("Invoice not found")
        return redirect(url_for("invoices_list"))

    all_lines = read_csv(LINES)
    existing_lines = [r for r in all_lines if int(r["inv_no"]) == inv_no]
    tax_def = float(get_setting("tax_default", "0") or 0)

    # ================= POST =================
    if request.method == "POST":
        try:
            name  = to_caps(request.form.get("name", ""))
            addr  = to_caps(request.form.get("address", ""))
            phone = request.form.get("phone", "")
            tax   = float(request.form.get("tax", tax_def))
            date_str = request.form.get("date") or invoice["date"]
            pending_added = float(request.form.get("pending_amount", 0) or 0)

            # ---- READ ROWS (SAFE) ----
            new_lines = []
            used = set()

            keys = sorted(
                [k for k in request.form if k.startswith("prod_")],
                key=lambda x: int(x.split("_")[1])
            )

            for k in keys:
                i = k.split("_")[1]
                prod = request.form.get(f"prod_{i}", "").strip()
                if not prod:
                    continue

                # qty safe parse
                qty_raw = request.form.get(f"qty_{i}", "").strip()
                qty = float(qty_raw) if qty_raw != "" else 0.0
                if qty <= 0:
                    raise Exception("Quantity must be positive")

                if prod in used:
                    raise Exception(f"Duplicate product: {prod}")

                info = next((p for p in prods if p["name"] == prod), None)
                if not info:
                    raise Exception("Invalid product")

                # ---- PRICE: AUTO if EMPTY, EDITABLE if FILLED ----
                price_raw = request.form.get(f"price_{i}", "").strip()
                if price_raw == "":
                    price = float(info["unit_price"])   # AUTO PRICE
                else:
                    price = float(price_raw)             # USER EDITABLE

                new_lines.append({
                    "product": prod,
                    "qty": qty,
                    "unit_price": price
                })
                used.add(prod)

            if not new_lines:
                raise Exception("Add at least one product")

            # ---- REVERSE OLD STOCK ----
            prod_rows = read_csv(PRODUCTS)
            for l in existing_lines:
                for r in prod_rows:
                    if r["name"] == l["product"]:
                        r["stock"] = f"{float(r.get('stock',0)) + float(l['qty']):.2f}"

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM sales_log WHERE inv_no=?", (inv_no,))

            # ---- APPLY NEW STOCK ----
            low_stock = []
            for l in new_lines:
                for r in prod_rows:
                    if r["name"] == l["product"]:
                        stock = float(r.get("stock", 0))
                        min_stock = float(r.get("min_stock", 0) or 0)

                        if stock < l["qty"]:
                            raise Exception(f"Insufficient stock for {l['product']}")

                        if stock - l["qty"] <= min_stock:
                            low_stock.append(l["product"])

                        r["stock"] = f"{stock - l['qty']:.2f}"

            write_csv(PRODUCTS, prod_rows,
                      ["name","unit_price","purchase_price","stock","min_stock"])

            for l in new_lines:
                c.execute("""
                    INSERT INTO sales_log (date, inv_no, product, qty, sell_price)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str, inv_no, l["product"], l["qty"], l["unit_price"]))
            conn.commit()
            conn.close()

            # ---- UPDATE INVOICE ----
            subtotal = sum(l["qty"] * l["unit_price"] for l in new_lines)
            total = subtotal + subtotal * tax / 100 + pending_added

            invoices = [r for r in invoices if int(r["inv_no"]) != inv_no]
            invoices.append({
                "inv_no": inv_no,
                "date": date_str,
                "name": name,
                "address": addr,
                "phone": phone,
                "tax": f"{tax:.2f}",
                "total": f"{total:.2f}",
                "logo_path": invoice.get("logo_path",""),
                "pending_added": f"{pending_added:.2f}"
            })
            write_csv(INVOICES, invoices,
                ["inv_no","date","name","address","phone","tax","total","logo_path","pending_added"]
            )

            lines = [l for l in all_lines if int(l["inv_no"]) != inv_no]
            for l in new_lines:
                lines.append({
                    "inv_no": inv_no,
                    "product": l["product"],
                    "qty": l["qty"],
                    "unit_price": l["unit_price"]
                })
            write_csv(LINES, lines, ["inv_no","product","qty","unit_price"])

            # ---- PDF ----
            now = datetime.datetime.now()
            out_dir = ensure_out_dirs(now.year, now.strftime("%B"))
            pdf = out_dir / f"INV_{inv_no}_{safe_name(name)}_{safe_name(addr)}.pdf"
            draw_invoice_pdf(
                pdf,
                get_setting("company_name"),
                get_setting("logo_path") or None,
                get_setting("logo_show")=="1",
                inv_no, date_str, name, addr, phone,
                new_lines, tax, pending_added
            )

            if low_stock:
                flash("Low stock: " + ", ".join(low_stock))

            flash("Invoice updated successfully")
            return redirect(url_for("invoices_list"))

        except Exception as e:
            flash(str(e))
            return redirect(url_for("edit_invoice", inv_no=inv_no))

    # ================= GET =================
    html = TPL_H + """
<h3>Edit Invoice #{{inv_no}}</h3>
<form method="post">
<input name="name" value="{{invoice.name}}" required>
<input name="address" value="{{invoice.address}}" required>
<input name="phone" value="{{invoice.phone}}">
<input name="date" value="{{invoice.date}}">
<input name="tax" value="{{invoice.tax}}">
<input name="pending_amount" value="{{invoice.pending_added}}">

<table id="tbl" border="1">
<thead><tr><th>Product</th><th>Qty</th><th>Price</th><th></th></tr></thead>
<tbody>
{% for l in existing_lines %}
<tr>
<td>
<select name="prod_{{loop.index0}}">
{% for p in prods %}
<option value="{{p.name}}" {% if p.name==l.product %}selected{% endif %}>{{p.name}}</option>
{% endfor %}
</select>
</td>
<td><input name="qty_{{loop.index0}}" value="{{l.qty}}"></td>
<td><input name="price_{{loop.index0}}" value="{{l.unit_price}}"></td>
<td><button type="button" onclick="this.closest('tr').remove()">❌</button></td>
</tr>
{% endfor %}
</tbody>
</table>

<button type="button" onclick="addRow()">➕ Add Product</button>
<button type="submit">Update Invoice</button>
</form>

<script>
let row = {{ existing_lines|length }};
function addRow(){
  const tb=document.querySelector("#tbl tbody");
  const tr=document.createElement("tr");
  tr.innerHTML=`
    <td><select name="prod_${row}">
      <option value="">--select--</option>
      {% for p in prods %}<option value="{{p.name}}">{{p.name}}</option>{% endfor %}
    </select></td>
    <td><input name="qty_${row}"></td>
    <td><input name="price_${row}"></td>
    <td><button type="button" onclick="this.closest('tr').remove()">❌</button></td>
  `;
  tb.appendChild(tr);
  row++;
}
</script>
""" + TPL_F

    return render_template_string(
        html,
        prods=prods,
        invoice=invoice,
        existing_lines=existing_lines,
        inv_no=inv_no,
        project=get_setting("project_name")
    )


# ---------- find_view_pdf ----------
@app.route("/find_view_pdf/<inv>")
@login_required
def find_view_pdf(inv):
    for r in read_csv(INVOICES):
        if str(r.get("inv_no")) == str(inv):
            d = r.get("date","")
            try:
                if "-" in d and len(d.split("-")[2])==2:
                    dt = datetime.datetime.strptime(d,"%d-%m-%y")
                elif "-" in d and len(d.split("-")[2])==4:
                    dt = datetime.datetime.strptime(d,"%d-%m-%Y")
                else:
                    dt = datetime.datetime.strptime(d,"%Y-%m-%d")
            except:
                dt = datetime.datetime.now()
            name_safe = safe_name(to_caps(r.get("name","")))
            addr_safe = safe_name(to_caps(r.get("address","")))
            fn = f"INV_{r['inv_no']}_{name_safe}_{addr_safe}.pdf"
            return redirect(url_for("view_pdf", y=dt.year, m=dt.strftime("%B"), fn=fn))
    flash("Invoice not found")
    return redirect(url_for("reports"))
# ---------- reports ----------
@app.route("/reports", methods=["GET","POST"])
@login_required
def reports():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "build":
            now = datetime.datetime.now()
            out_dir = ensure_out_dirs(now.year, now.strftime("%B"))
            pdf_path = build_month_summary_pdf(now.year, now.strftime("%B"), out_dir)
            flash(f"Monthly summary PDF created: {pdf_path}")
            return redirect(url_for("reports"))
        if action == "delete_summary":
            fn = request.form.get("fn")
            if fn:
                p = Path(fn)
                try:
                    p.unlink()
                    flash(f"Deleted {p.name}")
                except Exception as e:
                    flash(f"Could not delete: {e}")
            return redirect(url_for("reports"))
        if action == "delete_invoice":
            inv_del = request.form.get("inv_no_del","").strip()
            if inv_del:
                all_lines = read_csv(LINES); prod_rows = read_csv(PRODUCTS)
                for l in all_lines:
                    if str(l.get("inv_no")) == str(inv_del):
                        pname = l.get("product")
                        try: qty = float(l.get("qty","0") or 0)
                        except: qty = 0.0
                        for pr in prod_rows:
                            if pr["name"] == pname:
                                pr["stock"] = f"{float(pr.get('stock','0') or 0) + qty:.2f}"
                write_csv(PRODUCTS, prod_rows, ["name","unit_price","purchase_price","stock","min_stock"])
                invs = read_csv(INVOICES)
                invs2 = [r for r in invs if str(r.get("inv_no")) != str(inv_del)]
                write_csv(INVOICES, invs2, ["inv_no","date","name","address","phone","tax","total","logo_path"])
                lines2 = [l for l in all_lines if str(l.get("inv_no")) != str(inv_del)]
                write_csv(LINES, lines2, ["inv_no","product","qty","unit_price"])
                base = output_base() / "BusinessRecords"
                if base.exists():
                    for p in base.rglob(f"INV_{inv_del}_*.pdf"):
                        try: p.unlink()
                        except: pass
                flash(f"Deleted invoice {inv_del} and restored stock")
            return redirect(url_for("reports"))
    inv_no_q = request.args.get("inv_no","").strip(); name_q = request.args.get("name","").strip(); addr_q = request.args.get("address","").strip()
    rows = read_csv(INVOICES)
    if inv_no_q: rows = [r for r in rows if str(r.get("inv_no","")) == inv_no_q]
    if name_q: rows = [r for r in rows if name_q.lower() in r.get("name","").lower()]
    if addr_q: rows = [r for r in rows if addr_q.lower() in r.get("address","").lower()]
    agg = {}
    for r in read_csv(INVOICES):
        d = r.get("date","")
        try:
            if "-" in d and len(d.split("-")[2]) == 2:
                dt = datetime.datetime.strptime(d, "%d-%m-%y")
            elif "-" in d and len(d.split("-")[2]) == 4:
                dt = datetime.datetime.strptime(d, "%d-%m-%Y")
            else:
                dt = datetime.datetime.strptime(d, "%Y-%m-%d")
        except:
            continue
        key = dt.strftime("%Y-%m"); agg.setdefault(key, 0.0); agg[key] += float(r.get("total","0") or 0)
    labels = sorted(agg.keys()); data = [round(agg[k], 2) for k in labels]
    total_sales = sum(float(r.get("total","0") or 0) for r in read_csv(INVOICES))
    base = output_base() / "BusinessRecords"
    summary_files = []
    if base.exists():
        for ydir in sorted([p for p in base.iterdir() if p.is_dir()], reverse=True):
            for mdir in sorted([p for p in ydir.iterdir() if p.is_dir()], reverse=True):
                for fn in mdir.glob("SUMMARY_*.pdf"):
                    summary_files.append({"path": str(fn), "year": ydir.name, "month": mdir.name, "fn": fn.name})
    html = TPL_H + """
<h3>Reports</h3>
<form method="post" class="top">
  <div><span class="small">Build monthly summary PDF</span></div>
  <button class="btn" name="action" value="build">Build Monthly PDF</button>
</form>

<form method="get" class="top">
  <input name="inv_no" placeholder="Invoice #" value="{{request.args.get('inv_no','')}}" style="width:120px">
  <input name="name" placeholder="Customer name" value="{{request.args.get('name','')}}" style="width:220px">
  <input name="address" placeholder="Address" value="{{request.args.get('address','')}}" style="width:220px">
  <button class="btn">Filter</button> <a class="link" href="{{url_for('reports')}}">Clear</a>
</form>

<p class="small">Showing: {{rows|length}} invoices | Total Sales: Rs {{'%.2f'|format(total_sales)}}</p>

<table>
<tr><th>Inv#</th><th>Date</th><th>Customer</th><th>Address</th><th>Total</th><th>PDF</th><th>Actions</th></tr>
{% for r in rows %}
<tr>
  <td>{{r.inv_no}}</td><td>{{r.date}}</td><td>{{r.name}}</td><td>{{r.address}}</td><td>{{r.total}}</td>
  <td><a class="link" target="_blank" href="{{ url_for('find_view_pdf', inv=r.inv_no) }}">View</a></td>
  <td>
    <form method="post" style="display:inline" onsubmit="return confirm('Delete invoice {{r.inv_no}}? This will restore stock and remove PDFs.')">
      <input type="hidden" name="action" value="delete_invoice">
      <input type="hidden" name="inv_no_del" value="{{r.inv_no}}">
      <button class="btn">Delete</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>

<h4 style="margin-top:12px">Summary PDFs</h4>
{% if summary_files %}
<table>
<tr><th>Year</th><th>Month</th><th>File</th><th>Action</th></tr>
{% for s in summary_files %}
<tr>
<td>{{s.year}}</td><td>{{s.month}}</td><td><a class="link" target="_blank" href="{{ url_for('open_summary', year=s.year, month=s.month, fn=s.fn) }}">{{s.fn}}</a></td>
<td>
  <form method="post" style="display:inline">
    <input type="hidden" name="action" value="delete_summary">
    <input type="hidden" name="fn" value="{{s.path}}">
    <button class="btn" onclick="return confirm('Delete summary {{s.fn}}?')">Delete</button>
  </form>
</td>
</tr>
{% endfor %}
</table>
{% else %}
<p class="small">No summary PDFs found.</p>
{% endif %}
""" + TPL_F
    return render_template_string(html, rows=rows, total_sales=total_sales, labels=labels, data=data, summary_files=summary_files, project=get_setting("project_name"))

@app.route("/open_summary/<year>/<month>/<path:fn>")
@login_required
def open_summary(year, month, fn):
    base = output_base() / "BusinessRecords" / str(year) / str(month)
    if not base.exists():
        flash("Folder not found"); return redirect(url_for("reports"))
    return send_from_directory(base, fn)

@app.route("/open/<int:y>/<m>/<path:fn>")
@login_required
def open_pdf_path(y, m, fn):
    base = output_base() / "BusinessRecords" / str(y) / m
    if not base.exists():
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            try:
                desktop = Path.home() / "Desktop" / "BusinessRecords" / str(y) / m
                desktop.mkdir(parents=True, exist_ok=True)
                base = desktop
            except Exception:
                flash("Folder not found and could not create folder"); return redirect(url_for("reports"))
    fp = base / fn
    if not fp.exists():
        flash(f"PDF not found: {fn} in {base}")
        return redirect(url_for("reports"))
    return send_from_directory(base, fn)

@app.route("/view_pdf/<int:y>/<m>/<path:fn>")
@login_required
def view_pdf(y,m,fn):
    html = """
<!doctype html><title>View Invoice</title>
<style>body{margin:0}</style>
<embed src="{{url_for('open_pdf_path', y=y, m=m, fn=fn)}}" type="application/pdf" width="100%" height="100%" id="pdfembed">
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
        # Save normal settings
        set_setting("project_name", request.form.get("project", get_setting("project_name")))
        set_setting("company_name", request.form.get("company", get_setting("company_name")))
        set_setting("tax_default", request.form.get("tax_default","0") or "0")
        set_setting("date_format", request.form.get("date_format","dd-mm-yy"))
        set_setting("invoice_start", request.form.get("invoice_start","100"))
        set_setting("output_folder", request.form.get("output_folder",""))
        set_setting("auto_create_folders", "1" if request.form.get("auto_create")=="on" else "0")
        set_setting("logo_show", "1" if request.form.get("logo_show")=="on" else "0")
        set_setting("show_pending", "1" if request.form.get("show_pending")=="on" else "0")

        # Logo upload
        f = request.files.get("logo")
        if f and f.filename:
            fn = secure_filename(f.filename)
            path = UPLOADS / fn
            f.save(path)
            set_setting("logo_path", str(path))

        # Update password with mandatory security question
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

    # GET request - فارم دکھائیں
    html = TPL_H + """
<h3>Settings</h3>
<form method="post" enctype="multipart/form-data">
  <div class="top" style="align-items:flex-start;">
    <div style="flex:1;">
      <input name="project" value="{{project}}" placeholder="Project name" style="width:200px;margin:5px;">
      <input name="company" value="{{company}}" placeholder="Company name" style="width:200px;margin:5px;">
      <input name="tax_default" value="{{tax}}" placeholder="Default Tax %" style="width:100px;margin:5px;">
      <select name="date_format" style="margin:5px;">
        {% for f in ["dd-mm-yy","dd-mm-yyyy","yyyy-mm-dd"] %}
          <option value="{{f}}" {% if f==date_format %}selected{% endif %}>{{f}}</option>
        {% endfor %}
      </select>
      <input name="invoice_start" value="{{invoice_start}}" placeholder="Invoice start no" style="width:120px;margin:5px;">
      <input name="output_folder" value="{{output_folder}}" placeholder="Output folder (optional)" style="width:300px;margin:5px;">
      <br>
      <label style="margin:5px;"><input type="checkbox" name="auto_create" {% if auto_create=='1' %}checked{% endif %}> Auto-create folders</label>
      <label style="margin:5px;"><input type="checkbox" name="logo_show" {% if logo_show=='1' %}checked{% endif %}> Show logo</label>
      
      <!-- یہ نیا چیک باکس ہے -->
      <label style="background:#fff3cd;padding:10px 12px;border-radius:8px;margin:10px 5px;display:inline-block;font-weight:bold;">
        <input type="checkbox" name="show_pending" {% if show_pending=='1' %}checked{% endif %}>
        Show Pending Amount in New Invoice
      </label>
      <br><br>
      <input type="file" name="logo" accept="image/*" style="margin:5px;">
    </div>
    <div>
      <button class="btn" style="padding:12px 30px;font-size:16px;">Save Settings</button>
    </div>
  </div>
</form>
<div class="card" style="background:#e3f2fd; padding:20px; border-radius:10px; margin-top:30px; border-left:6px solid #1976d2;">  
  <h4>Developer Information (Read-Only)</h4>  
  <p><strong>Name:</strong> {{ developer_name }}</p>  
  <p><strong>Phone:</strong> {{ developer_phone }}</p>  
  <p>{{ contact_msg }}</p>  
</div>  
<div class="card" style="margin-top:40px; padding:25px; background:#e8f5e8; border-left:8px solid #4caf50; border-radius:12px;">
  <h3 style="color:#2e7d32; margin-top:0;">🔑 Update App Login Password</h3>
  <p style="color:#666; margin-bottom:20px;">Change the password used to open the app. Security question is mandatory for recovery.</p>
  <form method="post">
    <div style="margin-bottom:15px;">
      <label style="font-weight:bold;">New Password:</label>
      <input name="new_password" type="password" placeholder="At least 4 characters" style="width:100%; padding:12px; margin-top:8px; border-radius:8px; border:1px solid #ccc;">
    </div>
    <div style="margin-bottom:15px;">
      <label style="font-weight:bold;">Security Question:</label>
      <input name="security_question" placeholder="e.g. What is your mother's maiden name?" required style="width:100%; padding:12px; margin-top:8px; border-radius:8px; border:1px solid #ccc;">
    </div>
    <div style="margin-bottom:15px;">
      <label style="font-weight:bold;">Answer:</label>
      <input name="security_answer" placeholder="Enter answer (case insensitive)" required style="width:100%; padding:12px; margin-top:8px; border-radius:8px; border:1px solid #ccc;">
    </div>
    <button class="btn" style="background:#4caf50; color:white; padding:12px 30px; font-size:18px; border-radius:8px;">
      Update Password & Question
    </button>
  </form>
</div>
<p class="small" style="margin-top:20px;">
  Current Logo: {% if logo_path %}<code>{{logo_path}}</code>{% else %}<i>None</i>{% endif %}
</p>
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
        show_pending=get_setting("show_pending", "0")   # یہ لازمی ہے!
    )
# ================== سیلز ریکارڈ ==================
# ================== SALES RECORD + MONTHLY TARGETS (بالکل درست اور خوبصورت) ==================
@app.route("/sales_record")
@login_required
def sales_record():
    # CSV سے ڈیٹا لوڈ کریں
    invoices = read_csv(INVOICES)
    lines = read_csv(LINES)

    monthly_data = {}  # month_name -> list of {'product': str, 'qty': float}
    grand_totals = {}  # month_name -> total qty

    for line in lines:
        inv_no = line.get("inv_no")
        inv = next((i for i in invoices if i.get("inv_no") == inv_no), None)
        if not inv:
            continue

        date_str = inv.get("date", "")
        try:
            # مختلف فارمیٹس کو ہینڈل کریں (dd-mm-yy, dd-mm-yyyy, yyyy-mm-dd)
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
            month_name = dt.strftime("%B %Y")  # e.g. January 2026
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

    # ہر مہینے کے لیے لسٹ بنائیں اور qty کے حساب سے سارٹ کریں
    result = {}
    for month, prods in monthly_data.items():
        items = [{"product": p, "qty": q} for p, q in sorted(prods.items(), key=lambda x: x[1], reverse=True)]
        result[month] = items

    # مہینوں کو نیا سے پرانا کی طرف سارٹ کریں
    sorted_months = sorted(result.keys(), key=lambda x: datetime.datetime.strptime(x, "%B %Y"), reverse=True)
    sorted_result = {m: result[m] for m in sorted_months}

    html = TPL_H + """
<h2>📊 Sales Record (Product-wise Monthly Quantity Sold)</h2>
<p class="small">Monthly Salw QTY (CSV based)</p>

<input type="text" id="globalSearch" placeholder="🔍 search product name" 
       style="width:100%;max-width:700px;padding:14px;font-size:16px;border-radius:10px;border:2px solid #1976d2;margin:20px 0;">

{% if sorted_result %}
  {% for month, items in sorted_result.items() %}
  <div class="card" style="margin-bottom:30px;box-shadow:0 4px 15px rgba(0,0,0,0.08);border-radius:12px;overflow:hidden;">
    <h3 style="background:#1976d2;color:white;padding:16px;margin:0;font-size:19px;">
      {{ month }}
      <span style="float:right;font-size:17px;">Total QTY: <strong>{{ "%.2f"|format(grand_totals[month]) }}</strong></span>
    </h3>
    <div style="padding:20px;">
      <table style="width:100%;border-collapse:collapse;">
        <thead style="background:#e3f2fd;">
          <tr>
            <th style="padding:12px;text-align:left;">Product Name</th>
            <th style="padding:12px;text-align:center;width:200px;">Saled QTY</th>
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
    <h3> No Record Found</h3>
    <p>Data will show after creating invoice۔</p>
  </div>
{% endif %}

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

# ================== Stock Entry (Final – Clean & Working) ==================
@app.route("/stock_entry", methods=["GET", "POST"])
@login_required
def stock_entry():
    msg = ""
    now = datetime.datetime.now()
    month_folder = ensure_out_dirs(now.year, now.strftime("%B"))
    stock_report_file = month_folder / f"Stock_Entry_{now.year}_{now.strftime('%B')}.csv"
    # اگر فائل نہیں تو بنائیں
    if not stock_report_file.exists():
        with open(stock_report_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Entry_ID", "Date", "Product", "Quantity", "Purchase_Price"])
    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            entry_id = request.form.get("entry_id")
            entries = []
            with open(stock_report_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                entries = list(reader)
            new_entries = []
            deleted = False
            for e in entries:
                if e["Entry_ID"] == entry_id:
                    try:
                        qty = float(e["Quantity"])
                        prod = e["Product"]
                        rows = read_csv(PRODUCTS)
                        for r in rows:
                            if r["name"] == prod:
                                r["stock"] = f"{max(0.0, float(r.get('stock',0) or 0) - qty):.2f}"
                        write_csv(PRODUCTS, rows, ["name","unit_price","purchase_price","stock","min_stock"])
                        deleted = True
                    except:
                        pass
                else:
                    new_entries.append(e)
            if deleted:
                with open(stock_report_file, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["Entry_ID", "Date", "Product", "Quantity", "Purchase_Price"])
                    writer.writeheader()
                    writer.writerows(new_entries)
                flash("Entry deleted successfully. Stock reduced.")
            return redirect(url_for("stock_entry"))
        # نارمل ایڈ
        product = to_caps(request.form.get("product", "").strip())
        qty_str = request.form.get("qty", "").strip()
        price_str = request.form.get("price", "").strip()
        if not product or not qty_str or not price_str:
            msg = "Please fill all fields"
        else:
            try:
                qty = float(qty_str)
                price = float(price_str)
                if qty <= 0:
                    raise ValueError
            except:
                msg = "Quantity and Price must be valid numbers"
            else:
                # products.csv میں سٹاک بڑھائیں
                rows = read_csv(PRODUCTS)
                found = False
                for r in rows:
                    if r["name"].lower() == product.lower():
                        r["stock"] = f"{float(r.get('stock',0) or 0) + qty:.2f}"
                        r["unit_price"] = f"{price:.2f}"
                        found = True
                        break
                if not found:
                    rows.append({"name": product, "unit_price": f"{price:.2f}", "stock": f"{qty:.2f}", "min_stock": "0"})
                write_csv(PRODUCTS, rows, ["name","unit_price","purchase_price","stock","min_stock"])
                # Monthly رپورٹ میں انٹری
                entries = []
                try:
                    with open(stock_report_file, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        entries = list(reader)
                except:
                    pass
                new_id = str(len(entries) + 1).zfill(4)
                entries.insert(0, {
                    "Entry_ID": new_id,
                    "Date": now.strftime("%d-%m-%Y"),
                    "Product": product,
                    "Quantity": qty,
                    "Purchase_Price": price
                })
                with open(stock_report_file, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["Entry_ID", "Date", "Product", "Quantity", "Purchase_Price"])
                    writer.writeheader()
                    writer.writerows(entries)
                # SQLite کی بجائے CSV سے product_list حاصل کریں
                product_list = sorted([p['name'] for p in load_products()])
 
                flash(f" {qty} × {product} Successfully Entered")
                return redirect(url_for("stock_entry"))
    # GET - ڈیٹا تیار کریں
    entries = []
    try:
        with open(stock_report_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            entries = list(reader)
    except:
        entries = []
    # Filters apply کریں
    product_filter = request.args.get("product_filter", "").strip().upper()
    from_date_str = request.args.get("from_date")
    to_date_str = request.args.get("to_date")
    filtered_entries = []
    totals = {} # پروڈکٹ وائز ٹوٹل
    for e in entries:
        match = True
        if product_filter and product_filter not in e["Product"].upper():
            match = False
        if from_date_str or to_date_str:
            try:
                entry_date = datetime.datetime.strptime(e["Date"], "%d-%m-%Y").date()
                if from_date_str:
                    f_date = datetime.datetime.strptime(from_date_str, "%Y-%m-%d").date()
                    if entry_date < f_date:
                        match = False
                if to_date_str:
                    t_date = datetime.datetime.strptime(to_date_str, "%Y-%m-%d").date()
                    if entry_date > t_date:
                        match = False
            except:
                match = False
        if match:
            filtered_entries.append(e)
            prod = e["Product"]
            qty = float(e["Quantity"])
            totals[prod] = totals.get(prod, 0.0) + qty
    # SQLite کی بجائے CSV سے product_list حاصل کریں
    product_list = sorted([p['name'] for p in load_products()])
    # HTML بالکل صاف — کوئی f-string میں Jinja نہیں
    html = TPL_H + """
<h2>Stock Entry + Monthly Report</h2>
{% if msg %}<div class="notice">{{ msg }}</div>{% endif %}
<p style="margin:20px 0;text-align:center;">
  <a href="{{ url_for('stock_summary') }}" class="btn" style="background:#1976d2;color:white;padding:14px 40px;font-size:18px;">
    📊 View Full Monthly Stock Summary
  </a>
</p>
<form method="post">
  <input name="product" list="allprods" placeholder="Product Name" required style="width:350px;padding:12px;font-size:16px">
  <datalist id="allprods">
    {% for p in product_list %}
      <option value="{{ p }}">
    {% endfor %}
  </datalist>
  <input name="qty" type="number" step="any" placeholder="Quantity" required style="width:180px;padding:12px;margin:0 10px">
  <input name="price" type="number" step="any" placeholder="Selling Price" required style="width:180px;padding:12px">
  <button class="btn" style="padding:14px 40px;font-size:18px;background:#1b5e20;color:white;">Add to Stock</button>
</form>
<h3 style="margin-top:40px;">Stock Entries – {{ month_name }} {{ year }}</h3>
<table style="width:100%;margin-top:10px;">
  <thead style="background:black;color:black;">
    <tr><th>ID</th><th>Date</th><th>Product</th><th>Qty</th><th>Price</th><th>Action</th></tr>
  </thead>
  <tbody>
    {% for e in entries %}
    <tr>
      <td>{{ e.Entry_ID }}</td>
      <td>{{ e.Date }}</td>
      <td><strong>{{ e.Product }}</strong></td>
      <td>{{ e.Quantity }}</td>
      <td>Rs {{ e.Purchase_Price }}</td>
      <td>
        <form method="post" style="display:inline;">
          <input type="hidden" name="action" value="delete">
          <input type="hidden" name="entry_id" value="{{ e.Entry_ID }}">
          <button class="btn" style="background:#c62828;padding:6px 12px;"
                  onclick="return confirm('Delete this entry? Stock will be reduced')">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% if not entries %}
<p style="text-align:center;color:#888;margin-top:20px;">کوئی انٹری نہیں</p>
{% endif %}
<p class="small" style="margin-top:20px;">
  رپورٹ محفوظ ہے: <code>{{ report_path }}</code>
</p>
""" + TPL_F
    return render_template_string(
        html,
        msg=msg,
        product_list=product_list,
        entries=entries,
        month_name=now.strftime("%B"),
        year=now.year,
        report_path=str(stock_report_file),
        project=get_setting("project_name")
    )
# ========================================
@app.route("/stock_summary")
@login_required
def stock_summary():
    base = output_base() / "BusinessRecords"
    if not base.exists():
        flash("No report folder found yet.")
        return redirect(url_for("stock_entry"))

    all_months = {}
    for year_dir in sorted(base.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir(), reverse=True):
            if not month_dir.is_dir():
                continue
            csv_files = list(month_dir.glob("Stock_Entry_*.csv"))
            if not csv_files:
                continue
            csv_file = csv_files[0]

            month_name = month_dir.name
            year_name = year_dir.name
            key = f"{month_name} {year_name}"

            totals = {}
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        prod = row.get("Product", "Unknown")
                        try:
                            qty = float(row.get("Quantity", 0))
                        except:
                            qty = 0.0
                        totals[prod] = totals.get(prod, 0.0) + qty
            except Exception as e:
                totals = {"Error reading file": 0.0}

            # صرف غیر خالی مہینے دکھائیں
            if totals:
                # سب سے زیادہ qty والے اوپر
                sorted_totals = dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))
                all_months[key] = {
                    "totals": sorted_totals,
                    "file": csv_file.name
                }

    if not all_months:
        flash("No stock entries found in any month yet.")
        return redirect(url_for("stock_entry"))

    html = TPL_H + """
<h2>📊 Monthly Stock Entry Summary</h2>
<p class="small">Total quantity entered per product in each month</p>

<input type="text" id="globalSearch" placeholder="Search any product across all months..." 
       style="width:100%;max-width:600px;padding:12px;font-size:16px;border-radius:10px;border:2px solid #1976d2;margin:20px 0;">

{% for month_key, data in all_months.items() %}
<div class="card" style="margin-bottom:30px;">
  <h3 style="background:#1976d2;color:white;padding:12px;border-radius:8px 8px 0 0;margin:0;">
    {{ month_key }} — {{ data.file }}
  </h3>
  <div style="padding:20px;">
    <table style="width:100%;border-collapse:collapse;">
      <thead style="background:#f5f5f5;">
        <tr>
          <th style="padding:12px;text-align:left;">Product Name</th>
          <th style="padding:12px;text-align:center;width:180px;">Total Quantity</th>
        </tr>
      </thead>
      <tbody>
        {% for prod, qty in data.totals.items() %}
        <tr class="search-row">
          <td style="padding:12px;font-weight:600;">{{ prod }}</td>
          <td style="padding:12px;text-align:center;font-weight:bold;font-size:18px;color:#1976d2;">
            {{ "%.2f"|format(qty) }}
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
  let val = this.value.toLowerCase();
  document.querySelectorAll('.search-row').forEach(row => {
    let text = row.textContent.toLowerCase();
    row.style.display = text.includes(val) ? '' : 'none';
  });
});
</script>

<p style="text-align:center;margin-top:40px;">
  <a href="{{ url_for('stock_entry') }}" class="btn" style="padding:14px 40px;font-size:18px;">
    ← Back to Stock Entry
  </a>
</p>
""" + TPL_F

    return render_template_string(html, all_months=all_months, project=get_setting("project_name"))
# 5 PROFESSIONAL ENGLISH CARDS - FINAL VERSION
# ========================================


# 3. Monthly Targets (ٹھیک شدہ)
# Replace the existing @app.route("/target") function with this updated version

@app.route("/target", methods=["GET", "POST"])
def target():
    import calendar
    prods = load_products()
    growth = float(get_setting("growth_rate", "10"))

    if request.method == "POST":
        act = request.form.get("action", "")

        if act == "delete":
            product_del = request.form.get("product_del", "").strip()
            month_del = request.form.get("month_del", "").strip()
            if product_del and month_del:
                targets = read_csv(TARGETS_CSV)
                new_targets = [t for t in targets if not (t.get("product") == product_del and t.get("month") == month_del)]
                write_csv(TARGETS_CSV, new_targets, ["month", "product", "qty"])
            return redirect(url_for("target"))

        # Save first month target
        product = request.form.get("product")
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
        base_qty = float(request.form.get("qty", 0))

        if not product or base_qty <= 0:
            flash("Invalid product or quantity")
            return redirect(url_for("target"))

        month_name = calendar.month_name[month] + f" {year}"

        targets = read_csv(TARGETS_CSV)
        found = False
        for t in targets:
            if t.get("month") == month_name and t.get("product") == product:
                t["qty"] = f"{base_qty:.2f}"
                found = True
        if not found:
            targets.append({
                "month": month_name,
                "product": product,
                "qty": f"{base_qty:.2f}"
            })
        write_csv(TARGETS_CSV, targets, ["month", "product", "qty"])
        flash(f"Target saved for {product} in {month_name}")

    # ================= AUTO CREATE NEXT MONTH TARGET =================
    today = datetime.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]

    if today.day == last_day:  # آج مہینے کا آخری دن ہے
        current_month = today.strftime("%B %Y")
        next_month_date = today.replace(day=28) + datetime.timedelta(days=4)  # اگلا مہینہ
        next_month_name = next_month_date.strftime("%B %Y")

        targets = read_csv(TARGETS_CSV)
        updated = False
        for t in targets:
            if t.get("month") == current_month:
                try:
                    current_qty = float(t.get("qty", 0))
                    new_qty = current_qty + (current_qty * growth / 100)
                    # اگلا مہینہ چیک کریں، اگر نہیں تو بنائیں
                    found_next = False
                    for nt in targets:
                        if nt.get("month") == next_month_name and nt.get("product") == t.get("product"):
                            nt["qty"] = f"{new_qty:.2f}"
                            found_next = True
                    if not found_next:
                        targets.append({
                            "month": next_month_name,
                            "product": t.get("product"),
                            "qty": f"{new_qty:.2f}"
                        })
                    updated = True
                except:
                    pass
        if updated:
            write_csv(TARGETS_CSV, targets, ["month", "product", "qty"])

    # ================= FETCH CURRENT MONTH TARGET + ACHIEVED (CSV سے) =================
    current_month = today.strftime("%B %Y")

    # تمام targets لوڈ کریں
    targets = read_csv(TARGETS_CSV)
    current_targets = {}
    for t in targets:
        if t.get("month") == current_month:
            try:
                current_targets[t.get("product")] = float(t.get("qty", 0))
            except:
                pass

    # اب achieved quantity نکالیں (invoices + lines سے)
    invoices = read_csv(INVOICES)
    lines = read_csv(LINES)

    achieved = {}
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
                    else:
                        dt = datetime.datetime.strptime(date_str, "%d-%m-%Y")
            else:
                continue
            if dt.strftime("%B %Y") != current_month:
                continue
        except:
            continue

        prod = to_caps(line.get("product", ""))
        try:
            qty = float(line.get("qty", 0) or 0)
        except:
            qty = 0.0
        if qty > 0:
            achieved[prod] = achieved.get(prod, 0.0) + qty

    # ڈیٹا تیار کریں
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

    # اگر کوئی ٹارگٹ نہیں تو خالی دکھائیں
    if not data:
        data = []

    html = TPL_H + """
<h3>Monthly Target Sheet</h3>

<form method="post" style="margin-bottom:30px;background:#f0f8ff;padding:20px;border-radius:12px;">
  <div style="display:grid;grid-template-columns:1fr 120px 120px 150px 150px;gap:15px;align-items:end;">
    <div>
      <label><strong>Product</strong></label>
      <select name="product" required style="width:100%;padding:10px;">
        {% for p in prods %}
          <option value="{{p.name}}">{{p.name}}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label><strong>Month</strong></label>
      <select name="month" required style="width:100%;padding:10px;">
        {% for m in range(1,13) %}
          <option value="{{m}}">{{ calendar.month_name[m] }}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label><strong>Year</strong></label>
      <input type="number" name="year" value="{{ now.year }}" required style="width:100%;padding:10px;">
    </div>
    <div>
      <label><strong>Target Qty</strong></label>
      <input type="number" name="qty" step="any" placeholder="Target quantity" required style="width:100%;padding:10px;">
    </div>
    <div>
      <button class="btn" style="padding:12px;background:#1976d2;color:white;">Save Target</button>
    </div>
  </div>
</form>

<div class="card">
  <h3 style="background:#1976d2;color:white;padding:14px;margin:0;border-radius:8px 8px 0 0;">
    Current Month Targets: {{ current_month }}
  </h3>
  <table style="width:100%;border-collapse:collapse;">
    <thead style="background:#e3f2fd;">
      <tr>
        <th style="padding:12px;text-align:left;">Product</th>
        <th style="padding:12px;text-align:center;">Target Qty</th>
        <th style="padding:12px;text-align:center;">Achieved Qty</th>
        <th style="padding:12px;text-align:center;">Achieved %</th>
        <th style="padding:12px;text-align:center;">Action</th>
      </tr>
    </thead>
    <tbody>
      {% if data %}
        {% for row in data %}
        <tr {% if row.percent < 80 %}style="background:#ffebee;"{% elif row.percent >= 100 %}style="background:#e8f5e9;"{% endif %}>
          <td style="padding:12px;font-weight:600;">{{ row.product }}</td>
          <td style="padding:12px;text-align:center;font-weight:bold;">{{ "%.2f"|format(row.target) }}</td>
          <td style="padding:12px;text-align:center;font-weight:bold;color:#1976d2;">{{ "%.2f"|format(row.achieved) }}</td>
          <td style="padding:12px;text-align:center;font-size:18px;font-weight:bold;
               color:{{"#c62828" if row.percent < 80 else "#ff9800" if row.percent < 100 else "#2e7d32"}};">
            {{ row.percent }} %
          </td>
          <td style="padding:12px;text-align:center;">
            <form method="post" style="display:inline;">
              <input type="hidden" name="action" value="delete">
              <input type="hidden" name="product_del" value="{{ row.product }}">
              <input type="hidden" name="month_del" value="{{ current_month }}">
              <button class="btn" style="background:#c62828;color:white;padding:8px 16px;"
                      onclick="return confirm('Delete target for {{ row.product }}?')">Delete</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      {% else %}
        <tr>
          <td colspan="5" style="text-align:center;padding:40px;color:#999;font-size:18px;">
            اس مہینے کے لیے کوئی ٹارگٹ سیٹ نہیں کیا گیا
          </td>
        </tr>
      {% endif %}
    </tbody>
  </table>
</div>

<p style="margin-top:20px;text-align:center;color:#666;">
  اگلا مہینہ کا ٹارگٹ خود بخود {{ growth }}% گروتھ کے ساتھ بن جائے گا (مہینے کے آخری دن)
</p>
""" + TPL_F

    return render_template_string(
        html,
        prods=prods,
        data=data,
        now=today,
        current_month=current_month,
        calendar=calendar,
        growth=growth,
        project=get_setting("project_name")
    )


# 4. Profit & Loss Report (بالکل ٹھیک اور چلنے والا)
@app.route("/profit_loss")
@login_required
def profit_loss():
    today = datetime.date.today()
    current_month = today.strftime("%Y-%m")        # e.g. 2026-01
    month_name = today.strftime("%B")
    year = today.year
    full_month_year = f"{month_name} {year}"

    # ==== Total Sales اس مہینے کی ====
    total_sales = 0.0
    invoices = read_csv(INVOICES)
    for inv in invoices:
        date_str = inv.get("date", "").strip()
        if not date_str:
            continue
        try:
            # مختلف فارمیٹس کو ہینڈل کریں
            if len(date_str.split("-")[2]) == 4:  # YYYY-MM-DD
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            elif len(date_str.split("-")[2]) == 2:  # dd-mm-yy یا dd-mm-yyyy
                parts = date_str.split("-")
                if len(parts) == 3:
                    day, mon, yr = parts
                    yr = "20" + yr if len(yr) == 2 else yr
                    date_str_normalized = f"{yr}-{mon.zfill(2)}-{day.zfill(2)}"
                    dt = datetime.datetime.strptime(date_str_normalized, "%Y-%m-%d")
                else:
                    continue
            else:
                continue
        except:
            continue

        if dt.strftime("%Y-%m") == current_month:
            try:
                total_sales += float(inv.get("total", "0") or 0)
            except:
                pass

    # ==== Total Expenses اس مہینے کی (CSV سے) ====
    total_expenses = 0.0
    try:
        expenses_list = read_csv(EXPENSES_CSV)
        for e in expenses_list:
            exp_date = e.get("date", "").strip()
            if not exp_date:
                continue
            try:
                # تاریخ کو چیک کرو
                dt = datetime.datetime.strptime(exp_date, "%Y-%m-%d")
                if dt.strftime("%Y-%m") == current_month:
                    amount = float(e.get("amount", 0) or 0)
                    total_expenses += amount
            except:
                continue
    except Exception as e:
        print("Expenses CSV error:", e)
        total_expenses = 0.0

    net_profit = total_sales - total_expenses

    # ==== Product-wise Gross Profit ====
    products = load_products()
    sales_qty = {}

    # اس مہینے کی تمام invoice lines جمع کریں
    for inv in invoices:
        date_str = inv.get("date", "").strip()
        if not date_str:
            continue
        try:
            # وہی تاریخ چیک
            if len(date_str.split("-")[2]) == 4:
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            else:
                parts = date_str.split("-")
                if len(parts) != 3:
                    continue
                day, mon, yr = parts
                yr = "20" + yr if len(yr) == 2 else yr
                dt = datetime.datetime.strptime(f"{yr}-{mon.zfill(2)}-{day.zfill(2)}", "%Y-%m-%d")
        except:
            continue

        if dt.strftime("%Y-%m") != current_month:
            continue

        inv_no = inv.get("inv_no")
        if not inv_no:
            continue

        for line in read_csv(LINES):
            if line.get("inv_no") == inv_no:
                prod = to_caps(line.get("product", ""))
                try:
                    qty = float(line.get("qty", 0) or 0)
                except:
                    qty = 0.0
                if qty > 0:
                    sales_qty[prod] = sales_qty.get(prod, 0.0) + qty

    # پروڈکٹ وائز رپورٹ تیار کریں
    rows = []
    total_gross_profit = 0.0
    for p in products:
        name = p["name"]
        sp = p["unit_price"]
        cp = p["purchase_price"]
        qty_sold = sales_qty.get(name, 0.0)
        gross = (sp - cp) * qty_sold
        total_gross_profit += gross
        profit_pct = round((gross / (cp * qty_sold) * 100), 1) if cp > 0 and qty_sold > 0 else 0.0

        rows.append({
            "product": name,
            "qty": qty_sold,
            "selling_price": sp,
            "cost_price": cp,
            "gross_profit": gross,
            "percent": profit_pct
        })

    rows.sort(key=lambda x: x["qty"], reverse=True)

    # HTML (کوئی تبدیلی نہیں، بس درست ڈیٹا پاس ہو گا)
    html = TPL_H + """
<h2>Profit & Loss – {{ full_month_year }}</h2>

<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px,1fr)); gap:20px; margin:30px 0;">
  <div class="card" style="text-align:center;padding:25px;background:#e3f2fd;border-left:6px solid #1976d2;">
    <h3>Total Sales (This Month)</h3>
    <p style="font-size:32px;font-weight:bold;color:#1976d2;">Rs {{ "%.2f"|format(total_sales) }}</p>
  </div>
  <div class="card" style="text-align:center;padding:25px;background:#fff3e0;border-left:6px solid #ff9800;">
    <h3>Gross Profit</h3>
    <p style="font-size:32px;font-weight:bold;color:#ff9800;">Rs {{ "%.2f"|format(total_gross_profit) }}</p>
  </div>
  <div class="card" style="text-align:center;padding:25px;background:#ffebee;border-left:6px solid #f44336;">
    <h3>Total Expenses</h3>
    <p style="font-size:32px;font-weight:bold;color:#f44336;">Rs {{ "%.2f"|format(total_expenses) }}</p>
  </div>
  <div class="card" style="text-align:center;padding:25px;background:{{'#e8f5e9' if net_profit>=0 else '#ffebee'}};border-left:6px solid {{'#4caf50' if net_profit>=0 else '#f44336'}};">
    <h3>Net {{ "Profit" if net_profit>=0 else "Loss" }}</h3>
    <p style="font-size:36px;font-weight:bold;color:{{'#2e7d32' if net_profit>=0 else '#c62828'}};">
      Rs {{ "%.2f"|format(net_profit|abs) }}
    </p>
  </div>
</div>

<h3 style="margin-top:40px;">Product-wise Report – {{ full_month_year }}</h3>
<table style="width:100%;border-collapse:collapse;">
  <thead style="background:#1976d2;color:white;">
    <tr>
      <th style="padding:12px;text-align:left;">Product Name</th>
      <th style="padding:12px;text-align:center;">Qty Sold</th>
      <th style="padding:12px;text-align:center;">Selling Price</th>
      <th style="padding:12px;text-align:center;">Cost Price</th>
      <th style="padding:12px;text-align:center;">Gross Profit</th>
      <th style="padding:12px;text-align:center;">Profit %</th>
    </tr>
  </thead>
  <tbody>
    {% for r in rows %}
    <tr {% if r.qty > 0 %}style="background:#fffde7;"{% endif %}>
      <td style="padding:10px;font-weight:600;">{{ r.product }}</td>
      <td style="padding:10px;text-align:center;font-weight:bold;color:{{"green" if r.qty>0 else "#999"}};">
        {{ "%.2f"|format(r.qty) }}
      </td>
      <td style="padding:10px;text-align:center;">Rs {{ "%.2f"|format(r.selling_price) }}</td>
      <td style="padding:10px;text-align:center;">Rs {{ "%.2f"|format(r.cost_price) }}</td>
      <td style="padding:10px;text-align:center;font-weight:bold;color:{{"#2e7d32" if r.gross_profit>0 else "#c62828"}};">
        Rs {{ "%.2f"|format(r.gross_profit) }}
      </td>
      <td style="padding:10px;text-align:center;font-weight:bold;color:{{"#2e7d32" if r.percent>=20 else "#c62828"}};">
        {{ r.percent }}%
      </td>
    </tr>
    {% endfor %}
    {% if not rows %}
    <tr><td colspan="6" style="text-align:center;padding:40px;color:#999;">
      اس مہینے کوئی سیل نہیں ہوئی
    </td></tr>
    {% endif %}
  </tbody>
</table>
""" + TPL_F

    return render_template_string(
        html,
        total_sales=total_sales,
        total_expenses=total_expenses,
        total_gross_profit=total_gross_profit,
        net_profit=net_profit,
        rows=rows,
        full_month_year=full_month_year,
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
    text = company_name.strip() if company_name.strip() else "SEIZE"

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
                expenses_list = read_csv(EXPENSES_CSV)
                new_list = [e for e in expenses_list if e.get("id") != exp_id]
                write_csv(EXPENSES_CSV, new_list, ["id", "date", "amount", "description"])
                flash("Expense deleted successfully")
            return redirect(url_for("expenses"))

        # Add new expense
        try:
            amount = float(request.form.get("amount", 0))
            desc = request.form.get("desc", "").strip()
            date = request.form.get("date", today_str)
            if amount > 0 and desc:
                expenses_list = read_csv(EXPENSES_CSV)
                # نیا ID بنائیں
                new_id = str(max([int(e.get("id", 0) or 0) for e in expenses_list] + [0]) + 1)
                expenses_list.append({
                    "id": new_id,
                    "date": date,
                    "amount": f"{amount:.2f}",
                    "description": desc
                })
                write_csv(EXPENSES_CSV, expenses_list, ["id", "date", "amount", "description"])
                flash(f"Added: Rs {amount:,.2f} - {desc}")
            else:
                flash("Please enter valid amount and description")
        except:
            flash("Invalid amount")
        return redirect(url_for("expenses"))

    # GET: تمام اخراجات لوڈ کریں
    all_exps = read_csv(EXPENSES_CSV)
    # اگر کوئی انٹری نہیں تو خالی لسٹ
    if not all_exps:
        all_exps = []

    # تاریخ کے لحاظ سے سارٹ کریں (نیا سے پرانا)
    try:
        all_exps.sort(key=lambda x: x.get("date", ""), reverse=True)
    except:
        pass

    # مہینہ وار گروپ کریں
    from collections import defaultdict
    monthly = defaultdict(list)
    monthly_totals = defaultdict(float)
    yearly_total = 0.0

    for e in all_exps:
        try:
            exp_date = e.get("date", "")
            amount = float(e.get("amount", 0) or 0)
            desc = e.get("description", "—")
            exp_id = e.get("id", "")

            # مہینہ کا نام بنائیں
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

    # مہینوں کو نیا سے پرانا سارٹ کریں
    sorted_months = sorted(monthly.keys(), key=lambda x: datetime.datetime.strptime(x, "%B %Y"), reverse=True)

    html = TPL_H + """
<h2>Expense Manager</h2>
{% with messages = get_flashed_messages() %}
  {% if messages %}
    {% for msg in messages %}
      <div class="notice">{{ msg }}</div>
    {% endfor %}
  {% endif %}
{% endwith %}

<form method="post" style="background:#f9f9f9;padding:20px;border-radius:10px;margin:20px 0;box-shadow:0 4px 10px rgba(0,0,0,0.1);">
  <div style="display:grid;grid-template-columns:200px 150px 1fr 120px;gap:15px;align-items:end;">
    <div>
      <label><strong>Date</strong></label>
      <input name="date" type="date" value="{{ today_str }}" required style="width:100%;padding:10px;">
    </div>
    <div>
      <label><strong>Amount</strong></label>
      <input name="amount" type="number" step="0.01" placeholder="0.00" required style="width:100%;padding:10px;">
    </div>
    <div>
      <label><strong>Description</strong></label>
      <input name="desc" placeholder="e.g. Electricity bill, Rent, etc." required style="width:100%;padding:10px;">
    </div>
    <div>
      <button class="btn" style="padding:12px 20px;font-size:16px;background:#d32f2f;color:white;">Add Expense</button>
    </div>
  </div>
</form>

<!-- Yearly Total -->
<div class="card" style="text-align:center;padding:20px;background:#fff3e0;border-left:6px solid #ff9800;margin:20px 0;">
  <h3>Yearly Total Expenses ({{ current_year }})</h3>
  <p style="font-size:36px;font-weight:bold;color:#ff9800;margin:10px 0;">
    Rs {{ "%.2f"|format(yearly_total) }}
  </p>
</div>

<!-- Monthly Sections -->
<div style="margin-top:30px;">
  {% if sorted_months %}
    {% for month in sorted_months %}
    <div class="card" style="margin-bottom:20px;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.08);">
      <div style="background:#d32f2f;color:white;padding:16px;cursor:pointer;font-size:18px;font-weight:bold;" 
           onclick="let body=this.nextElementSibling; body.style.display=(body.style.display==='none' || body.style.display==='') ? 'block' : 'none';">
        {{ month }} 
        <span style="float:right;">
          Total: Rs {{ "%.2f"|format(monthly_totals[month]) }}
          <i style="margin-left:10px;">▼</i>
        </span>
      </div>
      <div class="month-body" style="display:block;">
        <table style="width:100%;border-collapse:collapse;">
          <thead style="background:#ffebee;">
            <tr>
              <th style="padding:12px;text-align:left;">Date</th>
              <th style="padding:12px;text-align:right;">Amount</th>
              <th style="padding:12px;text-align:left;">Description</th>
              <th style="padding:12px;text-align:center;">Action</th>
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
                <form method="post" style="display:inline;" onsubmit="return confirm('Delete this expense?')">
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="exp_id" value="{{ e.id }}">
                  <button class="btn" style="background:#c62828;padding:8px 16px;font-size:14px;">Delete</button>
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
    <div class="card" style="text-align:center;padding:60px;color:#999;background:#f9f9f9;">
      <h3>No expenses recorded yet</h3>
      <p>Start adding expenses using the form above.</p>
    </div>
  {% endif %}
</div>

<script>
  // پہلا مہینہ کھلا رکھیں
  const firstBody = document.querySelector('.month-body');
  if (firstBody) firstBody.style.display = 'block';
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
def other_expenses():
    today = datetime.date.today()
    today_str = today.isoformat()
    current_year = today.year

    OTHER_EXPENSES_CSV = DATA / "other_expenses.csv"

    # اگر فائل نہیں تو بنائیں
    if not OTHER_EXPENSES_CSV.exists():
        with open(OTHER_EXPENSES_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "date", "name", "amount", "description"])

    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            exp_id = request.form.get("exp_id")
            if exp_id:
                entries = read_csv(OTHER_EXPENSES_CSV)
                new_entries = [e for e in entries if e["id"] != exp_id]
                write_csv(OTHER_EXPENSES_CSV, new_entries, ["id", "date", "name", "amount", "description"])
                flash("Entry deleted successfully")
            return redirect(url_for("other_expenses"))

        # Add new entry
        try:
            name = request.form.get("name", "").strip()
            amount_str = request.form.get("amount", "").strip()
            desc = request.form.get("desc", "").strip()
            date = request.form.get("date", today_str)

            if not name or not amount_str:
                flash("Name and Amount are required")
                return redirect(url_for("other_expenses"))

            amount = float(amount_str)
            if amount <= 0:
                flash("Amount must be greater than zero")
                return redirect(url_for("other_expenses"))

            # نیا ID بنائیں
            entries = read_csv(OTHER_EXPENSES_CSV)
            new_id = str(max([int(e.get("id", "0") or "0") for e in entries] or [0]) + 1)

            entries.insert(0, {
                "id": new_id,
                "date": date,
                "name": name,
                "amount": f"{amount:.2f}",
                "description": desc
            })

            write_csv(OTHER_EXPENSES_CSV, entries, ["id", "date", "name", "amount", "description"])
            flash(f"Added: {name} – Rs {amount:,.2f}")
        except ValueError:
            flash("Invalid amount entered")
        except Exception as e:
            flash("Error saving entry")
        return redirect(url_for("other_expenses"))

    # GET – تمام انٹریز لوڈ کریں
    all_entries = read_csv(OTHER_EXPENSES_CSV)

    # مہینے کے حساب سے گروپ کریں
    from collections import defaultdict
    monthly = defaultdict(list)
    monthly_totals = defaultdict(float)

    for e in all_entries:
        try:
            exp_date = datetime.datetime.strptime(e["date"], "%Y-%m-%d")
            month_key = exp_date.strftime("%B %Y")  # e.g., January 2026
            monthly[month_key].append(e)
            monthly_totals[month_key] += float(e.get("amount", 0) or 0)
        except:
            continue

    # نیا سے پرانے کی طرف ترتیب دیں
    sorted_months = sorted(monthly.keys(),
                           key=lambda x: datetime.datetime.strptime(x, "%B %Y"),
                           reverse=True)

    html = TPL_H + """
<h2>📑 Other Expenses / Miscellaneous Entries</h2>

<form method="post" style="background:#fff8e1;padding:25px;border-radius:12px;margin:25px 0;
     border:2px dashed #ff9800;box-shadow:0 6px 15px rgba(0,0,0,0.1);">
  <div style="display:grid;grid-template-columns:180px 150px 1fr 130px;gap:18px;align-items:end;">
    <div>
      <label><strong>Date</strong></label>
      <input name="date" type="date" value="{{ today_str }}" required style="width:100%;padding:12px;font-size:15px;">
    </div>
    <div>
      <label><strong>Name / Item</strong></label>
      <input name="name" placeholder="e.g. Transport, Marketing" required style="width:100%;padding:12px;font-size:15px;">
    </div>
    <div>
      <label><strong>Description</strong></label>
      <input name="desc" placeholder="Optional details" style="width:100%;padding:12px;font-size:15px;">
    </div>
    <div style="display:flex;gap:10px;align-items:end;">
      <div style="flex:1;">
        <label><strong>Amount</strong></label>
        <input name="amount" type="number" step="0.01" placeholder="0.00" required style="width:100%;padding:12px;font-size:15px;">
      </div>
      <button class="btn" style="padding:14px 20px;font-size:18px;background:#ff6d00;color:white;height:52px;">
        Add Entry
      </button>
    </div>
  </div>
</form>

<!-- Yearly Total Card -->
{% set yearly_total = monthly_totals.values() | map('float') | sum %}
<div class="card" style="text-align:center;padding:25px;background:#fff0e0;border-left:8px solid #ff6d00;margin:30px 0;">
  <h3>Yearly Total ({{ current_year }})</h3>
  <p style="font-size:38px;font-weight:bold;color:#d84315;margin:10px 0;">
    Rs {{ "%.2f"|format(yearly_total) }}
  </p>
</div>

<!-- Monthly Foldable Sections -->
<div style="margin-top:20px;">
  {% if sorted_months %}
    {% for month in sorted_months %}
    <div class="card" style="margin-bottom:22px;border-radius:14px;overflow:hidden;
         box-shadow:0 6px 16px rgba(0,0,0,0.1);border:1px solid #eee;">
      <div style="background:#ff6d00;color:white;padding:18px;cursor:pointer;font-size:19px;font-weight:bold;"
           onclick="this.nextElementSibling.style.display = (this.nextElementSibling.style.display === 'none' || this.nextElementSibling.style.display === '') ? 'block' : 'none';">
        {{ month }}
        <span style="float:right;">
          Total: Rs {{ "%.2f"|format(monthly_totals[month]) }}
          <i style="margin-left:12px;font-style:normal;">▼</i>
        </span>
      </div>
      <div class="month-body" style="display:block;">
        <table style="width:100%;border-collapse:collapse;">
          <thead style="background:#fff3e0;">
            <tr>
              <th style="padding:14px;text-align:left;width:120px;">Date</th>
              <th style="padding:14px;text-align:left;">Name / Item</th>
              <th style="padding:14px;text-align:left;">Description</th>
              <th style="padding:14px;text-align:right;width:150px;">Amount</th>
              <th style="padding:14px;text-align:center;width:100px;">Action</th>
            </tr>
          </thead>
          <tbody>
            {% for e in monthly[month] %}
            <tr style="border-bottom:1px solid #eee;">
              <td style="padding:14px;">{{ e.date }}</td>
              <td style="padding:14px;font-weight:600;">{{ e.name }}</td>
              <td style="padding:14px;color:#555;">{{ e.description or "—" }}</td>
              <td style="padding:14px;text-align:right;font-weight:bold;color:#d84315;">
                Rs {{ "%.2f"|format(e.amount|float) }}
              </td>
              <td style="padding:14px;text-align:center;">
                <form method="post" style="display:inline;" onsubmit="return confirm('Delete this entry permanently?')">
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="exp_id" value="{{ e.id }}">
                  <button class="btn" style="background:#c62828;padding:9px 18px;font-size:14px;">
                    Delete
                  </button>
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
    <div class="card" style="text-align:center;padding:70px;color:#999;background:#fafafa;">
      <h3>No entries added yet</h3>
      <p>Use the form above to start recording other expenses.</p>
    </div>
  {% endif %}
</div>

<script>
  // پہلے مہینے کو خود بخود کھلا رکھیں
  document.querySelectorAll('.month-body')[0]?.style?.display = 'block';
</script>
""" + TPL_F

    return render_template_string(
        html,
        today_str=today_str,
        current_year=current_year,
        sorted_months=sorted_months,
        monthly=monthly,
        monthly_totals=monthly_totals,
        project=get_setting("project_name")
    )



# ================== BACKUP & RESTORE ==================
# ================== BACKUP & RESTORE (with Delete Button) ==================
@app.route("/backup", methods=["GET", "POST"])
def backup_restore():
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    message = ""
    if request.method == "POST":
        action = request.form.get("action")
        # نئی بیک اپ بنائیں
        if action == "create_backup":
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_filename = f"SmartInvoice_Backup_{timestamp}.zip"
            backup_path = backup_dir / backup_filename
            import zipfile
            
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # تمام CSV فائلیں data/ کے ساتھ
                for csv_file in DATA.glob("*.csv"):
                    if csv_file.is_file():
                        arcname = f"data/{csv_file.name}"
                        zipf.write(csv_file, arcname=arcname)
                
                # SQLite ڈیٹا بیس data/ کے ساتھ
                if DB_FILE.exists() and DB_FILE.is_file():
                    arcname = f"data/{DB_FILE.name}"
                    zipf.write(DB_FILE, arcname=arcname)
                
                # لوگو فائل uploads/ کے ساتھ (اگر ہے تو)
                logo_path_str = get_setting("logo_path", "").strip()
                if logo_path_str:
                    logo_path = Path(logo_path_str).resolve()  # مکمل پاتھ حاصل کرو
                    if logo_path.exists() and logo_path.is_file():
                        arcname = f"uploads/{logo_path.name}"
                        zipf.write(logo_path, arcname=arcname)
            
            flash(f"Backup created: {backup_filename}")
            return send_from_directory(str(backup_dir), backup_filename, as_attachment=True)
        # ریسٹور (تمہارا پرانا کوڈ ویسے کا ویسا رکھا ہے)
        elif action == "restore" and 'restore_file' in request.files:
            file = request.files['restore_file']
            if file.filename == '' or not file.filename.lower().endswith('.zip'):
                flash("Please select a valid .zip backup file")
                return redirect(url_for("backup_restore"))
            temp_path = backup_dir / f"temp_restore_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
            file.save(temp_path)
            try:
                with zipfile.ZipFile(temp_path, 'r') as zipf:
                    for csv_file in DATA.glob("*.csv"):
                        try: csv_file.unlink()
                        except: pass
                    if DB_FILE.exists():
                        DB_FILE.unlink()
                    zipf.extractall(ROOT)
                extracted_logo = None
                for item in zipf.namelist():
                    if item.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')) and "logo" in item.lower():
                        extracted_logo = ROOT / item
                        break
                if extracted_logo and extracted_logo.exists():
                    new_logo_path = UPLOADS / extracted_logo.name
                    if extracted_logo != new_logo_path:
                        import shutil
                        shutil.move(str(extracted_logo), str(new_logo_path))
                    set_setting("logo_path", str(new_logo_path))
                init_db()
                flash("Backup restored successfully! Refreshing in 3 seconds...")
                message = "<script>setTimeout(() => location.reload(), 3000);</script>"
            except Exception as e:
                flash(f"Restore failed: {str(e)}")
            finally:
                try: temp_path.unlink()
                except: pass
            return redirect(url_for("backup_restore"))

        # بیک اپ ڈیلیٹ
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

    # موجودہ بیک اپس کی لسٹ
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
<p class="notice">تمام ڈیٹا (انوائسز، پروڈکٹس، کسٹمرز، سٹاک، ایکسپینسز، سیٹنگز) محفوظ طریقے سے بیک اپ اور بحال کیا جا سکتا ہے۔</p>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:30px;margin:30px 0;">
  <!-- Create Backup -->
  <div class="card" style="border-left:6px solid #4caf50; text-align:center;">
    <h3 style="color:#2e7d32;">📥 Create New Backup</h3>
    <p>فوری بیک اپ بنائیں اور ڈاؤن لوڈ کریں۔</p>
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
    <p><strong>خبردار:</strong> موجودہ تمام ڈیٹا مٹ جائے گا!</p>
    <form method="post" enctype="multipart/form-data">
      <input type="hidden" name="action" value="restore">
      <input type="file" name="restore_file" accept=".zip" required
             style="width:100%;padding:12px;margin:15px 0;border:2px dashed #ff9800;border-radius:8px;">
      <button type="submit" class="btn-3d" style="background:#ff6d00; {button_3d_style}"
              onmouseover="this.style.{button_3d_hover}"
              onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 8px 0 rgb(0,0,0,0.3), 0 12px 20px rgba(0,0,0,0.4)';"
              onclick="return confirm('یقینی ہیں؟ تمام موجودہ ڈیٹا ختم ہو جائے گا!')">
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
        <form method="post" style="display:inline;" onsubmit="return confirm('یہ بیک اپ مستقل طور پر ڈیلیٹ ہو جائے گا۔ یقینی ہیں؟')">
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
# ڈاؤن لوڈ کے لیے الگ روٹ
@app.route("/backup/download/<filename>")
@login_required
def download_backup(filename):
    backup_dir = ROOT / "backups"
    return send_from_directory(str(backup_dir), filename, as_attachment=True)

@app.route("/sales_history", methods=["GET", "POST"])
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


# ==== یہ 6 لائنیں بالکل آخر میں (run server سے پہلے) پیسٹ کر دو ==== 

@app.route("/inventory")
def inventory_redirect():        # صرف ری ڈائریکٹ، اصل روٹ پہلے سے ہے
    return redirect(url_for("inventory"))

@app.route("/sales_record")
def sales_record_redirect():
    return redirect(url_for("sales_record"))

@app.route("/profit_loss")
def profit_loss_redirect():
    return redirect(url_for("profit_loss"))

@app.route("/stock_entry")
def stock_entry_redirect():
    return redirect(url_for("stock_entry"))

@app.route("/target")
def target_redirect():
    return redirect(url_for("target"))

@app.route("/expenses")
def expenses_redirect():
    return redirect(url_for("expenses"))
# ---------- Run ----------
# ---------- Run ----------
if __name__ == "__main__":
    import webbrowser
    import time

    # company name (safe)
    company = get_setting("company_name", "SEIZE")

    # 🔥 SHOW SPLASH (BLOCKING)
    show_splash(company)

    # 🔥 OPEN BROWSER
    webbrowser.open("http://localhost:3345")

    # 🔥 START FLASK
    app.run(
        host="0.0.0.0",
        port=3345,
        debug=False,
        use_reloader=False
    )


