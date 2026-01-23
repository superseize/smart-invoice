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

DB_FILE = str(DB_DIR / "smart_invoice.db")


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

        c.execute("""
        CREATE TABLE IF NOT EXISTS salesmen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
           role TEXT DEFAULT 'salesman',
           active INTEGER DEFAULT 1,
           permissions TEXT DEFAULT '{}'
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS sequences (
            key TEXT PRIMARY KEY,
            value INTEGER
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
        # payments
        c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inv_no INTEGER,
            amount REAL,
            method TEXT,
            date TEXT,
            note TEXT
        )
        """)


        # --- CUSTOMERS ---
        c.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            address TEXT,
            phone TEXT,
            UNIQUE(name, address)
        )
        """)

        # --- SALES LOG ---
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

        c.execute("""
            CREATE TABLE IF NOT EXISTS products (
                name TEXT PRIMARY KEY,
                stock REAL DEFAULT 0,
                unit_price REAL DEFAULT 0,
                purchase_price REAL DEFAULT 0
            )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
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

def migrate_salesmen_columns():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    
    # role کالم
    try:
        cur.execute("ALTER TABLE salesmen ADD COLUMN role TEXT DEFAULT 'salesman'")
        conn.commit()
        print("✅ Added 'role' column to salesmen table")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ 'role' column already exists")
        else:
            print("❌ Error adding role column:", e)
    
    # active کالم
    try:
        cur.execute("ALTER TABLE salesmen ADD COLUMN active INTEGER DEFAULT 1")
        conn.commit()
        print("✅ Added 'active' column to salesmen table")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ 'active' column already exists")
        else:
            print("❌ Error adding active column:", e)
    
    # permissions کالم (نیا اضافہ)
    try:
        cur.execute("ALTER TABLE salesmen ADD COLUMN permissions TEXT DEFAULT '{}'")
        conn.commit()
        print("✅ Added 'permissions' column to salesmen table")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ 'permissions' column already exists")
        else:
            print("❌ Error adding permissions column:", e)
    
    conn.close()

# اب اسے پروگرام شروع ہوتے ہی چلائیں
migrate_salesmen_columns()   # ← یہ لائن init_db() کے نیچے یا __main__ میں ڈالیں
# ===================== INIT DB (ON START) =====================
init_db()
def db():
    return sqlite3.connect(DB_FILE)
# ---------- DB MIGRATION (SAFE) ----------
def migrate_products_add_min_stock():
    con = db()
    cur = con.cursor()
    try:
        cur.execute(
            "ALTER TABLE products ADD COLUMN min_stock REAL DEFAULT 0"
        )
        con.commit()
        print("✅ min_stock column added")
    except Exception as e:
        print("ℹ️ min_stock already exists or skipped")
    con.close()

migrate_products_add_min_stock()
# ---------- MIGRATION : ADD remarks TO invoices ----------
def migrate_add_invoice_remarks():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    try:
        cur.execute("ALTER TABLE invoices ADD COLUMN remarks TEXT")
        con.commit()
        print("✅ invoices.remarks column added")
    except Exception:
        print("ℹ️ invoices.remarks already exists")
    con.close()

migrate_add_invoice_remarks()
def migrate_invoices_columns():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # name
    try:
        cur.execute("ALTER TABLE invoices ADD COLUMN name TEXT")
    except:
        pass

    # address
    try:
        cur.execute("ALTER TABLE invoices ADD COLUMN address TEXT")
    except:
        pass

    # phone
    try:
        cur.execute("ALTER TABLE invoices ADD COLUMN phone TEXT")
    except:
        pass

    # pending_added
    try:
        cur.execute("ALTER TABLE invoices ADD COLUMN pending_added REAL DEFAULT 0")
    except:
        pass

    conn.commit()
    conn.close()

#______
def migrate_invoices_columns():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    columns = [
        ("name", "TEXT"),
        ("address", "TEXT"),
        ("phone", "TEXT"),
        ("pending_added", "REAL DEFAULT 0")
    ]

    for col_name, col_type in columns:
        try:
            cur.execute(f"ALTER TABLE invoices ADD COLUMN {col_name} {col_type}")
            conn.commit()
            print(f"✅ '{col_name}' کالم invoices ٹیبل میں شامل ہو گیا")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"ℹ️ '{col_name}' کالم پہلے سے موجود ہے")
            else:
                print(f"❌ '{col_name}' شامل کرنے میں ایرر: {e}")

    conn.commit()
    conn.close()
init_db()
migrate_invoices_columns()   # ← یہ لائن ضرور ڈالیں
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

# ---------- SQLITE SEQUENCE ----------
def get_seq(key, start=1):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT value FROM sequences WHERE key=?",
        (key,)
    )
    row = cur.fetchone()

    if row:
        val = row[0] + 1
        cur.execute(
            "UPDATE sequences SET value=? WHERE key=?",
            (val, key)
        )
    else:
        val = start
        cur.execute(
            "INSERT INTO sequences (key, value) VALUES (?,?)",
            (key, val)
        )

    con.commit()
    con.close()
    return val

# ---------- Settings ----------
def get_setting(key, default=""):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else default


def set_setting(key, value):
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
    con.commit()
    con.close()


def init_settings():
    defaults = {
        "project_name": "Smart Invoice",
        "company_name": "COMPANY NAME",
        "tax_default": "0",
        "date_format": "dd-mm-yy",
        "invoice_start": "100",
        "logo_path": "",
        "logo_show": "1",
        "auto_create_folders": "1",
        "output_folder": "",
        "developer_name": "ISHTIAQ AHMAD MAGRAY",
        "developer_phone": "+923495820495",
        "contact_msg": "For new software development, contact the developer above.",
        "growth_rate": "10",
        "show_pending": "0",
        "app_password": "12345",
        "security_question": "What is your favorite color?",
        "security_answer": ""
    }

    con = db()
    cur = con.cursor()
    for k, v in defaults.items():
        cur.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO NOTHING
        """, (k, v))
    con.commit()
    con.close()

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
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT name, stock, unit_price, purchase_price, min_stock
        FROM products
    """)
    rows = cur.fetchall()
    con.close()

    return [{
        "name": r[0],
        "stock": r[1],
        "unit_price": r[2],
        "purchase_price": r[3],
        "min_stock": r[4]
    } for r in rows]

def load_customers():
    con = db()
    cur = con.cursor()
    cur.execute("SELECT name, address, phone FROM customers")
    rows = cur.fetchall()
    con.close()
    return [{
        "name": r[0],
        "address": r[1],
        "phone": r[2]
    } for r in rows]

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
<!doctype html><title>{{project}}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<link rel="manifest" href="/static/manifest.json">
<meta name="theme-color" content="#1e3a8a">

<script>
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/service-worker.js");
}
</script>
<style>
  :root {
    --bg: #fafafa;
    --text: #212529;
    --card-bg: #ffffff;
    --card-border: #e0e0e0;
    --header-bg: #f8f9fa;
    --btn-bg: #111111;
    --btn-text: #ffffff;
    --link: #0a58ca;
    --notice-bg: #eef8ee;
    --notice-border: #a6d8a6;
    --notice-text: #155724;
    --badge-bg: #eee;
    --dash-card-bg: linear-gradient(145deg, #ffffff, #f0f7ff);
    --dash-text: #1e293b;
    --dash-p: #1d4ed8;
    --heading: #1e3a8a;
  }

  body.dark {
    --bg: #1e1e1e;          /* soft dark background - کم brightness */
    --text: #f5f5f5;        /* ہلکا سفید ٹیکسٹ */
    --card-bg: #2d2d2d;     /* cards تھوڑے ہلکے گرے */
    --card-border: #444;
    --header-bg: #333333;
    --btn-bg: #444444;
    --btn-text: #ffffff;
    --link: #8ab4f8;
    --notice-bg: #1a331a;
    --notice-border: #3d7b3d;
    --notice-text: #a0e6a0;
    --badge-bg: #3a3a3a;
    --dash-card-bg: linear-gradient(145deg, #2a2a2a, #383838);
    --dash-text: #f0f0f0;
    --dash-p: #79b0ff;
    --heading: #b0d0ff;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: system-ui, Segoe UI, Arial;
    margin: 16px;
    transition: all 0.4s ease;
  }

  a.btn, button.btn { background: var(--btn-bg); color: var(--btn-text); padding: 8px 12px; border-radius: 8px; text-decoration: none; border: 0; cursor: pointer; }
  a.link { color: var(--link); text-decoration: none; }
  .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 10px; padding: 12px; color: var(--text); }
  .card h3 { margin: 0 0 8px; color: var(--heading); }
  .badge { background: var(--badge-bg); border-radius: 999px; padding: 2px 8px; margin-right: 6px; color: var(--text); }
  input, select, textarea { padding: 8px 10px; border: 1px solid var(--card-border); border-radius: 8px; background: var(--card-bg); color: var(--text); }
  table { border-collapse: collapse; width: 100%; color: var(--text); }
  th, td { border: 1px solid var(--card-border); padding: 6px; }
  th { background: var(--header-bg); color: var(--text); }
  .notice { background: var(--notice-bg); border: 1px solid var(--notice-border); padding: 8px 12px; border-radius: 8px; color: var(--notice-text); }
  .dash-card { background: var(--dash-card-bg); color: var(--dash-text); padding: 40px 30px; border-radius: 28px; text-align: center; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3); transition: all 0.6s; }
  .dash-card p { color: var(--dash-p); font-size: 22px; font-weight: bold; margin: 0; text-shadow: 1px 1px 3px rgba(0,0,0,0.6); }
  h2, h3, h4, h5 { color: var(--heading); }
</style>
<script src="/static/offline.js"></script>
<div class="top">
  <div><span class="badge">{{project}}</span><span class="badge">SMART INVOICE PRO</span></div>
  <div>
    <a class="link" href="{{url_for('home')}}">Home</a> |
    <a class="link" href="{{url_for('new_invoice')}}" id="nav_invoice">Invoice</a> |
    <a class="link" href="{{url_for('invoices_list')}}" id="nav_invoices">All Invoices</a> |
    <a class="link" href="{{url_for('products')}}">Products</a> |
    <a class="link" href="{{url_for('customers')}}">Customers</a> |
    <a class="link" href="{{url_for('payments')}}">Payments</a> |
    <a class="link" href="{{url_for('reports')}}">Reports</a> |
    <a class="link" href="{{url_for('settings')}}">Settings</a> |
    <!-- <a class="link" href="{{url_for('backup_restore')}}">Backup</a> |-->
    &nbsp;|&nbsp;
    {% if session.logged_in %}
      <span style="color:green; font-weight:bold;">✓ Login</span> |
      <a class="link" href="{{ url_for('logout') }}">Logout</a>
    {% else %}
      <a class="link" href="{{ url_for('login') }}">🔐 Log In</a>
    {% endif %}
    &nbsp;|&nbsp;
    <button id="themeToggle" class="btn" style="padding:8px 16px; font-size:14px; border-radius:20px;">
      🌙 Dark Mode
    </button>
  </div>
</div>
{% with m=get_flashed_messages() %}{% if m %}<p class="notice">{{m[0]}}</p>{% endif %}{% endwith %}
<div class="card">

"""
TPL_F = """
<script>
  const toggleBtn = document.getElementById('themeToggle');
  const body = document.body;

  // صفحہ لوڈ ہوتے ہی پچھلی تھیم لگائیں
  if (localStorage.getItem('theme') === 'dark') {
    body.classList.add('dark');
    toggleBtn.innerHTML = '☀️ Light Mode';
  } else {
    toggleBtn.innerHTML = '🌙 Dark Mode';
  }

  // کلک پر تھیم تبدیل کریں
  toggleBtn.addEventListener('click', () => {
    body.classList.toggle('dark');
    
    if (body.classList.contains('dark')) {
      localStorage.setItem('theme', 'dark');
      toggleBtn.innerHTML = '☀️ Light Mode';
    } else {
      localStorage.setItem('theme', 'light');
      toggleBtn.innerHTML = '🌙 Dark Mode';
    }
  });
</script>

</div>"""


# ---------- welcome page ----------

# ---------- Home ----------
@app.route("/")
@login_required
def home():
    now = datetime.datetime.now()
    cur_month = now.strftime("%B"); cur_year = now.year
    month_total = 0.0

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT date, total
        FROM invoices
    """)

    rows = cur.fetchall()
    con.close()

    for d, total in rows:
        try:
            dt = datetime.datetime.fromisoformat(d)
        except:
            continue

        if dt.year == cur_year and dt.strftime("%B") == cur_month:
            month_total += float(total or 0)

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

# ---------- Products (SQLITE) ----------
@app.route("/products", methods=["GET","POST"])
@login_required
def products():

    if request.method == "POST":
        act = request.form.get("action","")
        con = db()
        cur = con.cursor()

        # ---------- SAVE ----------
        if act == "save":
            name = to_caps(request.form.get("name","").strip())
            if not name:
                flash("Product name required")
                return redirect(url_for("products"))

            sell_price_input = request.form.get("unit_price","").strip()
            purchase_price_input = request.form.get("purchase_price","").strip()
            add_stock_input = request.form.get("stock","0").strip()
            min_stock_input = request.form.get("min_stock","0").strip()

            try:
                add_stock = float(add_stock_input or 0)
                min_stock = float(min_stock_input or 0)
            except:
                flash("Invalid stock values")
                return redirect(url_for("products"))

            cur.execute("""
                SELECT unit_price, purchase_price, stock
                FROM products WHERE name=?
            """, (name,))
            row = cur.fetchone()

            if row:
                unit_price, purchase_price, stock = row

                if sell_price_input:
                    unit_price = float(sell_price_input)
                if purchase_price_input:
                    purchase_price = float(purchase_price_input)

                stock = (stock or 0) + add_stock

                cur.execute("""
                    UPDATE products
                    SET unit_price=?, purchase_price=?, stock=?, min_stock=?
                    WHERE name=?
                """,(unit_price, purchase_price, stock, min_stock, name))
                flash(f"Updated: {name}")

            else:
                if not sell_price_input or not purchase_price_input:
                    flash("Selling & Purchase price required for new product")
                    return redirect(url_for("products"))

                cur.execute("""
                    INSERT INTO products
                    (name, unit_price, purchase_price, stock, min_stock)
                    VALUES (?,?,?,?,?)
                """,(name, float(sell_price_input),
                     float(purchase_price_input),
                     add_stock, min_stock))
                flash(f"New product added: {name}")

            con.commit()
            con.close()
            return redirect(url_for("products"))

        # ---------- DELETE ----------
        if act == "delete":
            name_del = to_caps(request.form.get("name_del",""))
            cur.execute("DELETE FROM products WHERE name=?", (name_del,))
            con.commit()
            con.close()
            flash(f"Deleted: {name_del}")
            return redirect(url_for("products"))

    # ---------- LOAD PRODUCTS ----------
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT name, unit_price, purchase_price, stock, min_stock
        FROM products ORDER BY name
    """)
    rows = cur.fetchall()
    con.close()

    prods = [{
        "name":r[0],
        "unit_price":r[1],
        "purchase_price":r[2],
        "stock":r[3],
        "min_stock":r[4]
    } for r in rows]

    html = TPL_H + """
<h3>Products / Stock Management</h3>

<button class="btn" onclick="history.back()">⬅ Back</button>

<input type="text" id="search" placeholder="🔍 Search product..."
       style="width:100%;padding:14px;margin:20px 0;">

<form method="post">
<input type="hidden" name="action" value="save">

<input name="name" list="plist" placeholder="Product name" required>
<datalist id="plist">
{% for p in prods %}
<option value="{{p.name}}">
{% endfor %}
</datalist>

<input name="unit_price" placeholder="Selling price">
<input name="purchase_price" placeholder="Purchase price">
<input name="stock" value="0" placeholder="Add stock">
<input name="min_stock" value="0" placeholder="Min stock">

<button class="btn" style="background:#2e7d32">Save</button>
</form>

<table id="ptable">
<tr>
<th>Name</th><th>Sell</th><th>Purchase</th>
<th>Stock</th><th>Min</th><th>Status</th><th>Del</th>
</tr>

{% for p in prods %}
<tr {% if p.stock <= p.min_stock %}style="background:#ffebee"{% endif %}>
<td>{{p.name}}</td>
<td>{{p.unit_price}}</td>
<td>{{p.purchase_price}}</td>
<td>{{p.stock}}</td>
<td>{{p.min_stock}}</td>
<td>{% if p.stock<=p.min_stock %}LOW{% else %}OK{% endif %}</td>
<td>
<form method="post">
<input type="hidden" name="action" value="delete">
<input type="hidden" name="name_del" value="{{p.name}}">
<button class="btn" style="background:#c62828">X</button>
</form>
</td>
</tr>
{% endfor %}
</table>

<script>
document.getElementById('search').oninput=e=>{
 let q=e.target.value.toLowerCase();
 document.querySelectorAll('#ptable tr').forEach((r,i)=>{
  if(i==0) return;
  r.style.display=r.innerText.toLowerCase().includes(q)?'':'none';
 });
}
</script>
""" + TPL_F

    return render_template_string(html, prods=prods, project=get_setting("project_name"))



# ---------- Customers ----------
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    con = db()
    cur = con.cursor()

    selected_customer = None
    ledger_data = None

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "save":
            name = request.form.get("name", "").strip().title()
            address = request.form.get("address", "").strip().title()
            phone = request.form.get("phone", "").strip()

            if not name or not address:
                flash("Name and Address are required")
                return redirect(url_for("customers"))

            cur.execute("""
                INSERT INTO customers (name, address, phone)
                VALUES (?, ?, ?)
                ON CONFLICT(name, address) DO UPDATE SET
                    phone = excluded.phone
            """, (name, address, phone))
            con.commit()
            flash("Customer saved / updated")

        elif action == "delete":
            name_del = request.form.get("name_del", "").strip().title()
            addr_del = request.form.get("addr_del", "").strip().title()

            if name_del and addr_del:
                cur.execute(
                    "DELETE FROM customers WHERE name = ? AND address = ?",
                    (name_del, addr_del)
                )
                if cur.rowcount > 0:
                    con.commit()
                    flash("Customer deleted successfully")
                else:
                    flash("Customer not found")
            else:
                flash("Select both name and address to delete")

        elif action == "show_ledger":
            name = request.form.get("ledger_name", "").strip().title()
            address = request.form.get("ledger_address", "").strip().title()

            if name and address:
                cur.execute(
                    "SELECT name, address, phone FROM customers WHERE name=? AND address=?",
                    (name, address)
                )
                cust = cur.fetchone()
                if cust:
                    selected_customer = {"name": cust[0], "address": cust[1], "phone": cust[2]}

                    # Invoices
                    cur.execute("""
                        SELECT inv_no, date, total
                        FROM invoices
                        WHERE customer = ? AND customer_address = ?
                        ORDER BY date DESC
                    """, (name, address))
                    invoices = cur.fetchall()

                    # Payments (if you have payments table)
                    cur.execute("""
                        SELECT date, amount, method
                        FROM payments
                        WHERE inv_no IN (
                            SELECT inv_no FROM invoices 
                            WHERE customer = ? AND customer_address = ?
                        )
                        ORDER BY date DESC
                    """, (name, address))
                    payments = cur.fetchall()

                    ledger_data = {
                        "invoices": invoices,
                        "payments": payments,
                        "pending": get_pending(name, address)
                    }

    # Load all customers
    cur.execute("SELECT name, address, phone FROM customers ORDER BY name, address")
    all_customers = [{"name": r[0], "address": r[1], "phone": r[2]} for r in cur.fetchall()]

    con.close()

    html = TPL_H + """
<style>
    .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .action-buttons { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 20px; }
    .action-buttons button { flex: 1; min-width: 140px; padding: 12px; font-size: 1rem; }
    .ledger-card { background: #f8f9fa; border-radius: 12px; padding: 20px; margin: 25px 0; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }
    .table-responsive { overflow-x: auto; }
    .summary { background: #e3f2fd; padding: 16px; border-radius: 10px; margin-bottom: 20px; font-size: 1.1rem; }
    @media (max-width: 768px) {
        .form-grid { grid-template-columns: 1fr; }
        .action-buttons { flex-direction: column; }
        h2 { font-size: 1.6rem; text-align: center; }
    }
</style>

<h2>Customers Management</h2>

<!-- Add / Update Customer -->
<form method="post" class="card" style="padding: 20px;">
    <input type="hidden" name="action" value="save">
    <div class="form-grid">
        <div>
            <label>Name *</label>
            <input name="name" required placeholder="Customer name">
        </div>
        <div>
            <label>Address *</label>
            <input name="address" required placeholder="Full address">
        </div>
        <div>
            <label>Phone</label>
            <input name="phone" placeholder="Phone number">
        </div>
    </div>
    <div class="action-buttons">
        <button type="submit" class="btn" style="background: #1976d2; color: white;">Save Customer</button>
    </div>
</form>

<!-- View Ledger -->
<form method="post" class="card" style="margin: 25px 0; padding: 20px;">
    <h3>View Customer Ledger</h3>
    <input type="hidden" name="action" value="show_ledger">
    <div class="form-grid">
        <div>
            <label>Customer Name</label>
            <input list="cust_names" name="ledger_name" placeholder="Type name">
            <datalist id="cust_names">
                {% for c in all_customers %}
                <option value="{{ c.name }}"></option>
                {% endfor %}
            </datalist>
        </div>
        <div>
            <label>Address</label>
            <input list="cust_addresses" name="ledger_address" placeholder="Type address">
            <datalist id="cust_addresses">
                {% for c in all_customers %}
                <option value="{{ c.address }}"></option>
                {% endfor %}
            </datalist>
        </div>
    </div>
    <div class="action-buttons">
        <button type="submit" class="btn" style="background: #2e7d32; color: white;">Show Ledger</button>
    </div>
</form>

<!-- Ledger Display -->
{% if ledger_data %}
<div class="ledger-card">
    <h3>Ledger for: {{ selected_customer.name }} - {{ selected_customer.address }}</h3>
    
    <div class="summary">
        <strong>Current Pending Balance:</strong> Rs {{ "%.2f"|format(ledger_data.pending) }}
    </div>

    <h4>Invoices</h4>
    <div class="table-responsive">
        <table style="width:100%; border-collapse: collapse;">
            <thead style="background: #e3f2fd;">
                <tr>
                    <th>Invoice No</th>
                    <th>Date</th>
                    <th>Total</th>
                </tr>
            </thead>
            <tbody>
                {% for inv in ledger_data.invoices %}
                <tr style="border-bottom: 1px solid #eee;">
                    <td>{{ inv[0] }}</td>
                    <td>{{ inv[1] }}</td>
                    <td style="text-align: right;">Rs {{ "%.2f"|format(inv[2]) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    {% if ledger_data.payments %}
    <h4 style="margin-top: 25px;">Payments</h4>
    <div class="table-responsive">
        <table style="width:100%; border-collapse: collapse;">
            <thead style="background: #e8f5e9;">
                <tr>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>Method</th>
                </tr>
            </thead>
            <tbody>
                {% for p in ledger_data.payments %}
                <tr style="border-bottom: 1px solid #eee;">
                    <td>{{ p[0] }}</td>
                    <td style="text-align: right;">Rs {{ "%.2f"|format(p[1]) }}</td>
                    <td>{{ p[2] or 'Cash' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}
</div>
{% endif %}

<!-- All Customers List -->
<h3>All Customers</h3>
<div class="table-responsive">
    <table style="width:100%; border-collapse: collapse;">
        <thead style="background: #f0f0f0;">
            <tr>
                <th>Name</th>
                <th>Address</th>
                <th>Phone</th>
            </tr>
        </thead>
        <tbody>
            {% for c in all_customers %}
            <tr style="border-bottom: 1px solid #eee;">
                <td>{{ c.name }}</td>
                <td>{{ c.address }}</td>
                <td>{{ c.phone or '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<script>
// Optional: simple client-side search if needed later
</script>
""" + TPL_F

    return render_template_string(html, all_customers=all_customers, selected_customer=selected_customer, ledger_data=ledger_data, project=get_setting("project_name"))

@app.route("/salesmen", methods=["GET","POST"])
@login_required
def salesmen():

    con = db()
    cur = con.cursor()

    if request.method == "POST":
        name = request.form.get("name","").strip().title()
        if name:
            try:
                cur.execute("INSERT INTO salesmen(name) VALUES (?)", (name,))
                con.commit()
            except:
                pass

    cur.execute("SELECT id, name FROM salesmen ORDER BY name")
    rows = cur.fetchall()
    con.close()

    html = TPL_H + """
    <h3>Salesmen</h3>

    <form method="post">
      <input name="name" placeholder="Salesman name" required>
      <button class="btn">Add</button>
    </form>

    <table>
      <tr><th>ID</th><th>Name</th></tr>
      {% for r in rows %}
      <tr><td>{{r[0]}}</td><td>{{r[1]}}</td></tr>
      {% endfor %}
    </table>
    """ + TPL_F

    return render_template_string(html, rows=rows, project=get_setting("project_name"))

# ---------- New Invoice ----------
# ================== NEW & EDIT INVOICE - FINAL WORKING VERSION ==================
@app.route("/invoice/new", methods=["GET", "POST"])
@login_required
def new_invoice():
    today_iso = datetime.date.today().isoformat()

    # Load products and salesmen
    con = db()
    cur = con.cursor()
    cur.execute("SELECT name, stock, unit_price FROM products ORDER BY name")
    products = [{"name": r[0], "stock": r[1] or 0, "price": r[2] or 0} for r in cur.fetchall()]

    cur.execute("SELECT name FROM salesmen ORDER BY name")
    salesmen = [r[0] for r in cur.fetchall()]

    con.close()

    # POST handling
    if request.method == "POST":
        try:
            customer = request.form.get("customer", "").strip().title()
            address = request.form.get("address", "").strip().title()
            phone = request.form.get("phone", "").strip()
            salesman = request.form.get("salesman", "").strip()
            date_str = request.form.get("date") or today_iso
            pending_added = float(request.form.get("pending_added", "0") or "0")

            # Basic validation
            if not customer or not address:
                flash("Customer name and address are required")
                return redirect(url_for("new_invoice"))

            if not salesman:
                flash("Salesman is required")
                return redirect(url_for("new_invoice"))

            # Items with strict checks
            items = []
            seen_products = set()
            i = 0
            while True:
                prod_name = request.form.get(f"prod_{i}")
                if not prod_name:
                    break
                qty_str = request.form.get(f"qty_{i}", "0")
                price_str = request.form.get(f"price_{i}", "0")
                qty = float(qty_str) if qty_str else 0
                price = float(price_str) if price_str else 0

                if qty <= 0 or not prod_name:
                    i += 1
                    continue

                # Duplicate check
                if prod_name in seen_products:
                    flash(f"Duplicate product '{prod_name}' not allowed in one invoice")
                    return redirect(url_for("new_invoice"))
                seen_products.add(prod_name)

                # Stock check - prevent add if low
                prod = next((p for p in products if p["name"] == prod_name), None)
                if prod and qty > prod["stock"]:
                    flash(f"Cannot add {prod_name}: Only {prod['stock']} in stock, requested {qty}")
                    return redirect(url_for("new_invoice"))

                items.append({"product": prod_name, "qty": qty, "price": price})
                i += 1

            if not items:
                flash("At least 1 product is required")
                return redirect(url_for("new_invoice"))

            total = sum(it["qty"] * it["price"] for it in items)

            # Invoice Number from settings (auto increase)
            start_seq = int(get_setting("invoice_start", "1"))
            ym = date_str[:7]
            con = db()
            cur = con.cursor()
            cur.execute("SELECT MAX(CAST(SUBSTR(inv_no, 8) AS INTEGER)) FROM invoices WHERE inv_no LIKE ?", (ym + "-%",))
            max_seq = cur.fetchone()[0] or (start_seq - 1)
            next_seq = max_seq + 1
            inv_no = f"{ym}-{next_seq:03d}"

            # Save invoice
            cur.execute("""
                INSERT INTO invoices
                (inv_no, date, customer, customer_address,phone,  salesman, total, pending_added)
                VALUES (?,?,?,?,?,?,?,?)
            """, (inv_no, date_str, customer, address, phone, salesman, total, pending_added))

            for it in items:
                cur.execute("INSERT INTO invoice_items (inv_no, product, qty, price) VALUES (?,?,?,?)",
                            (inv_no, it["product"], it["qty"], it["price"]))

                # Stock decrease
                cur.execute("UPDATE products SET stock = COALESCE(stock, 0) - ? WHERE name = ?",
                            (it["qty"], it["product"]))

                # Sales log entry
                cur.execute("""
                    INSERT INTO sales_log (date, inv_no, product, qty, sell_price)
                    VALUES (?,?,?,?,?)
                """, (date_str, inv_no, it["product"], it["qty"], it["price"]))

            # Pending update
            current_pending = get_pending(customer, address)
            new_pending = current_pending + pending_added - total
            update_pending(customer, address, max(0, new_pending))

            # Add new customer
            cur.execute("INSERT OR IGNORE INTO customers (name, address, phone) VALUES (?, ?, ?)",
                        (customer, address, phone))

            con.commit()
            con.close()

            # PDF Generation
            dt = datetime.datetime.fromisoformat(date_str)
            base_dir = ensure_out_dirs(dt.year, dt.strftime("%B"))
            fn = f"INV_{inv_no}_{safe_name(customer)}_{safe_name(address)}.pdf"
            pdf_path = base_dir / fn

            salesman_dir = base_dir / safe_name(salesman)
            salesman_dir.mkdir(exist_ok=True)
            pdf_salesman = salesman_dir / fn

            draw_invoice_pdf(
                out_path=pdf_path,
                company=get_setting("company_name", "COMPANY NAME"),
                logo_path=get_setting("logo_path", ""),
                show_logo=get_setting("logo_show", "1") == "1",
                inv_no=inv_no,
                date_str_display=fmt_date(dt.date()),
                cust_name=customer,
                cust_addr=address,
                cust_phone=phone,
                lines=[{"product": it["product"], "qty": it["qty"], "unit_price": it["price"]} for it in items],
                tax_pct=float(get_setting("tax_default", 0)),
                pending_added=pending_added
            )

            import shutil
            shutil.copy(pdf_path, pdf_salesman)

            flash(f"Invoice {inv_no} saved successfully!")
            return f"""
            <script>
                localStorage.removeItem('invoice_draft');
                window.open('{pdf_path}', '_blank');
                window.print();
                setTimeout(() => window.location = '/invoices', 1500);
            </script>
            """

        except Exception as e:
            flash(f"Error: {str(e)}")
            return redirect(url_for("new_invoice"))

    # GET - Form
    html = TPL_H + """
<h2>New Invoice</h2>

<div style="margin-bottom:15px;">
  <a href="{{ url_for('home') }}" class="btn" style="background:#757575; color:white;">← Back</a>
  <button type="button" onclick="clearForm()" class="btn" style="background:#9e9e9e; color:white; margin-left:10px;">Clear Form</button>
</div>

<form method="post" id="invForm" class="card" style="padding:20px; background:white; border-radius:8px; box-shadow:0 2px 10px rgba(0,0,0,0.1);">

  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:16px;">
    <div>
      <label>Customer Name *</label>
      <input name="customer" required placeholder="Enter name" autofocus>
    </div>
    <div>
      <label>Address *</label>
      <input name="address" required placeholder="Full address">
    </div>
    <div>
      <label>Phone</label>
      <input name="phone" placeholder="0300-xxxxxxx">
    </div>
    <div>
      <label>Date</label>
      <input type="date" name="date" value="{{ today }}">
    </div>
    <div>
      <label>Salesman *</label>
      <select name="salesman" required>
        <option value="">-- Select --</option>
        {% for s in salesmen %}
          <option value="{{ s }}">{{ s }}</option>
        {% endfor %}
      </select>
    </div>
  </div>

  <div id="pendingSection" style="display:none; background:#fff8e1; border-left:6px solid #ffb300; padding:16px; margin:20px 0; border-radius:4px;">
    <strong>Previous Pending:</strong> Rs <span id="pendingAmt">0.00</span><br>
    <label style="margin-top:8px;">Add/Adjust:</label>
    <input type="number" step="0.01" name="pending_added" id="pendingInput" value="0.00" style="width:140px; padding:8px;">
    <small>(Positive = add to bill, Negative = reduce)</small>
  </div>

  <table id="itemTable" style="width:100%; margin:20px 0; border-collapse:collapse;">
    <thead style="background:#e8f5e9;">
      <tr>
        <th>Product</th>
        <th>Qty</th>
        <th>Price</th>
        <th>Total</th>
        <th></th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

  <div style="text-align:right; font-size:1.5em; font-weight:bold; margin:20px 0;">
    Grand Total: Rs <span id="totalDisplay">0.00</span>
  </div>

  <div style="display:flex; gap:10px; flex-wrap:wrap;">
    <button type="button" onclick="addRow()" class="btn" style="background:#43a047; color:white;">+ Add Item</button>
    <button type="button" onclick="previewInvoice()" class="btn" style="background:#ff9800; color:white;">Preview</button>
    <button type="submit" class="btn" style="background:#1976d2; color:white;">Save & Print</button>
  </div>

</form>

<script>
// Global variables
const products = {{ products | tojson | safe }};
let rowId = 0;

// Title Case
function titleCase(str) {
  return (str || "").replace(/\\w\\S*/g, t => t.charAt(0).toUpperCase() + t.substr(1).toLowerCase());
}
['customer','address'].forEach(n => {
  const el = document.querySelector(`[name="${n}"]`);
  if (el) el.addEventListener('input', () => el.value = titleCase(el.value));
});

// Add Row
function addRow() {
  const tbody = document.querySelector("#itemTable tbody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input list="pdl${rowId}" name="prod_${rowId}" placeholder="Type product..." required style="width:100%;">
        <datalist id="pdl${rowId}"></datalist></td>
    <td><input type="number" name="qty_${rowId}" min="0.01" step="any" value="1" style="width:80px;" oninput="calc(this)"></td>
    <td><input type="number" name="price_${rowId}" step="0.01" style="width:80px;" oninput="calc(this)"></td>
    <td class="rtotal" style="text-align:right; font-weight:bold;">0.00</td>
    <td><button type="button" onclick="this.parentElement.parentElement.remove(); calcGrand()" style="background:#ef5350;color:white;border:none;padding:4px 8px;border-radius:4px;">×</button></td>
  `;
  tbody.appendChild(tr);

  const dl = document.getElementById(`pdl${rowId}`);
  products.forEach(p => {
    let opt = document.createElement("option");
    opt.value = p.name;
    opt.dataset.price = p.price;
    opt.dataset.stock = p.stock;
    opt.text = `${p.name} (Stock: ${p.stock})`;
    dl.appendChild(opt);
  });

  const prodIn = tr.querySelector('input[list^="pdl"]');
  prodIn.addEventListener("input", function(){
    let match = products.find(p => p.name === this.value.trim());
    if (match) {
      let priceEl = this.closest("tr").querySelector('[name^="price_"]');
      priceEl.value = match.price.toFixed(2);
      calc(priceEl);
      let qtyEl = this.closest("tr").querySelector('[name^="qty_"]');
      if (parseFloat(qtyEl.value) > parseFloat(match.stock)) {
        alert(`Low Stock! Available: ${match.stock}, Requested: ${qtyEl.value}`);
      }
    }
  });

  rowId++;
}

// Calculations
function calc(el) {
  let tr = el.closest("tr");
  let q = parseFloat(tr.querySelector('[name^="qty_"]').value) || 0;
  let p = parseFloat(tr.querySelector('[name^="price_"]').value) || 0;
  tr.querySelector(".rtotal").textContent = (q * p).toFixed(2);
  calcGrand();
}

function calcGrand() {
  let sum = 0;
  document.querySelectorAll(".rtotal").forEach(td => sum += parseFloat(td.textContent)||0);
  document.getElementById("totalDisplay").textContent = sum.toFixed(2);
}

// Pending Fetch
async function fetchPending() {
  let c = document.querySelector('[name="customer"]').value.trim();
  let a = document.querySelector('[name="address"]').value.trim();
  if (!c || !a) return;

  try {
    let resp = await fetch(`/api/pending?customer=${encodeURIComponent(c)}&address=${encodeURIComponent(a)}`);
    let data = await resp.json();
    let pend = data.pending || 0;

    let sec = document.getElementById("pendingSection");
    let amt = document.getElementById("pendingAmt");
    let inp = document.getElementById("pendingInput");

    if (pend > 0) {
      amt.textContent = pend.toFixed(2);
      inp.value = pend.toFixed(2);
      sec.style.display = "block";
    } else {
      sec.style.display = "none";
      inp.value = "0.00";
    }
  } catch(e) {
    console.log("Pending fetch failed:", e);
  }
}

// Draft Save
const draftKeys = ["customer","address","phone","salesman","date"];
window.addEventListener("load", () => {
  draftKeys.forEach(k => {
    let el = document.querySelector(`[name="${k}"]`);
    if (el) {
      let v = localStorage.getItem("invDraft_" + k);
      if (v) el.value = v;
    }
  });
  addRow();
  fetchPending();
});

draftKeys.forEach(k => {
  let el = document.querySelector(`[name="${k}"]`);
  if (el) el.addEventListener("input", () => localStorage.setItem("invDraft_" + k, el.value));
});

document.querySelector('[name="customer"]').addEventListener("change", fetchPending);
document.querySelector('[name="address"]').addEventListener("change", fetchPending);

document.getElementById("invForm").addEventListener("submit", () => {
  draftKeys.forEach(k => localStorage.removeItem("invDraft_" + k));
}); 

// Clear Form
function clearForm() {
  if (confirm("Clear all fields?")) {
    document.getElementById("invForm").reset();
    document.querySelector("#itemTable tbody").innerHTML = "";
    rowId = 0;
    addRow();
    draftKeys.forEach(k => localStorage.removeItem("invDraft_" + k));
    document.getElementById("pendingSection").style.display = "none";
    calcGrand();
  }
}

// Preview (simulate preview)
function previewInvoice() {
  alert("Preview: Invoice ready for review.\\n\\nCustomer: " + document.querySelector('[name="customer"]').value + "\\nTotal: Rs " + document.getElementById("totalDisplay").textContent + "\\n\\nActual PDF will generate on Save.");
}
</script>
    """ + TPL_F

    return render_template_string(html, products=products, salesmen=salesmen, today=today_iso, project=get_setting("project_name"))

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

    name = to_caps(request.args.get("name","").strip())
    addr = to_caps(request.args.get("address","").strip())

    con = db()
    cur = con.cursor()

    # invoices + payments join
    cur.execute("""
        SELECT
            i.inv_no,
            i.date,
            i.total,
            IFNULL(SUM(p.amount), 0)
        FROM invoices i
        LEFT JOIN payments p ON p.inv_no = i.inv_no
        WHERE i.customer = ? AND i.customer_address = ?
        GROUP BY i.inv_no
        ORDER BY i.inv_no DESC
        LIMIT 50
    """, (name, addr))

    rows = cur.fetchall()
    con.close()

    out = []
    total_pending = 0.0

    for inv_no, date, total, received in rows:
        pending = max((total or 0) - (received or 0), 0)
        total_pending += pending

        # year / month for pdf path
        try:
            dt = datetime.datetime.strptime(date, "%Y-%m-%d")
        except:
            dt = datetime.datetime.now()

        y = dt.year
        m = dt.strftime("%B")

        fn = f"INV_{inv_no}_{safe_name(name)}_{safe_name(addr)}.pdf"

        out.append({
            "inv_no": inv_no,
            "date": date,
            "total": total,
            "received": received,
            "pending": pending,
            "pdf": url_for(
                "open_pdf_path",
                y=y,
                m=m,
                fn=fn
            )
        })

    return jsonify({
        "rows": out,
        "pending": round(total_pending, 2)
    })
@app.route("/api/pending")
@login_required
def api_pending():

    name = to_caps(request.args.get("name","").strip())
    addr = to_caps(request.args.get("address","").strip())

    if not name or not addr:
        return jsonify({"pending": 0.0})

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            SUM(i.total - IFNULL(paid.total_paid,0))
        FROM invoices i
        LEFT JOIN (
            SELECT inv_no, SUM(amount) total_paid
            FROM payments
            GROUP BY inv_no
        ) paid ON paid.inv_no = i.inv_no
        WHERE i.customer = ? AND i.customer_address = ?
    """, (name, addr))

    val = cur.fetchone()[0]
    con.close()

    return jsonify({
        "pending": round(val or 0.0, 2)
    })


# ---------- Payments ----------
# ================================================
# ---------- PAYMENTS (SQLITE) ----------
@app.route("/payments", methods=["GET"])
@login_required
def payments():
    con = db()
    cur = con.cursor()

    # -------- Filters --------
    inv_no_q = request.args.get("inv_no","").strip()
    name_q   = request.args.get("name","").strip().lower()
    addr_q   = request.args.get("address","").strip().lower()
    date_q   = request.args.get("date","").strip()

    sql = """
    SELECT
        i.inv_no,
        i.date,
        i.customer,
        i.customer_address,
        i.total,
        IFNULL(SUM(p.amount),0) AS received,
        (i.total - IFNULL(SUM(p.amount),0)) AS pending,
        i.remarks
    FROM invoices i
    LEFT JOIN payments p ON p.inv_no = i.inv_no
    WHERE 1=1
    """

    params = []

    if inv_no_q:
        sql += " AND i.inv_no = ?"
        params.append(inv_no_q)

    if name_q:
        sql += " AND LOWER(i.customer) LIKE ?"
        params.append(f"%{name_q}%")

    if addr_q:
        sql += " AND LOWER(i.customer_address) LIKE ?"
        params.append(f"%{addr_q}%")

    if date_q:
        sql += " AND i.date LIKE ?"
        params.append(f"%{date_q}%")

    sql += """
    GROUP BY i.inv_no
    ORDER BY i.inv_no DESC
    """

    cur.execute(sql, params)
    rows = cur.fetchall()
    con.close()

    display_rows = []
    total_received = 0.0
    total_pending  = 0.0

    for r in rows:
        pending = round(max(r[6], 0), 2)
        total_received += r[5]
        total_pending  += pending

        display_rows.append({
            "inv_no":       r[0],
            "date":         r[1],
            "customer":     r[2],
            "address":      r[3],
            "total":        f"{r[4]:.2f}",
            "received":     f"{r[5]:.2f}",
            "received_raw": r[5],                    # ← added for <input value>
            "pending":      f"{pending:.2f}",
            "remarks":      r[7] or ""
        })

    html = TPL_H + """
<h3>💰 Payments / Customer Ledger</h3>

<form method="get" class="top">
  <input name="inv_no" placeholder="Invoice #" value="{{request.args.get('inv_no','')}}">
  <input name="name" placeholder="Customer" value="{{request.args.get('name','')}}">
  <input name="address" placeholder="Address" value="{{request.args.get('address','')}}">
  <input name="date" placeholder="Date" value="{{request.args.get('date','')}}">
  <button class="btn">Filter</button>
  <a class="link" href="{{url_for('payments')}}">Clear</a>
</form>

<p style="font-size:18px;margin:15px 0;">
  <strong>Total Received:</strong> Rs {{'%.2f'|format(total_received)}} |
  <strong>Total Pending:</strong>
  <span style="color:#c62828;">Rs {{'%.2f'|format(total_pending)}}</span>
</p>

<div style="overflow-x:auto;">
<table>
<thead style="background:#1976d2;color:white;">
<tr>
  <th>Inv#</th>
  <th>Date</th>
  <th>Customer</th>
  <th>Address</th>
  <th>Total</th>
  <th>Received</th>
  <th>Pending</th>
  <th>Remarks</th>
  <th></th>  <!-- new small column for save button -->
</tr>
</thead>
<tbody>
{% for r in rows %}
<tr {% if r.pending != '0.00' %}style="background:#fff3e0;"{% endif %}>
  <td>{{r.inv_no}}</td>
  <td>{{r.date}}</td>
  <td><strong>{{r.customer}}</strong></td>
  <td>{{r.address}}</td>
  <td>Rs {{r.total}}</td>

  <td>
    <form method="post" action="{{ url_for('payments_update') }}" style="margin:0;">
      <input type="hidden" name="inv_no" value="{{ r.inv_no }}">
      <input type="number" step="0.01" name="received" value="{{ r.received_raw }}" 
             style="width:110px; text-align:right; border:1px solid #ccc; padding:3px;">
  </td>

  <td style="font-weight:bold;color:#c62828;">Rs {{r.pending}}</td>

  <td>
    <input type="text" name="remarks" value="{{ r.remarks }}" 
           style="width:200px; border:1px solid #ccc; padding:3px;" placeholder="...">
  </td>

  <td style="padding:4px; text-align:center;">
    <button type="submit" class="btn" style="padding:4px 10px; font-size:13px;">Save</button>
    </form>
  </td>
</tr>
{% endfor %}
</tbody>
</table>
</div>

<div style="margin-top:25px;text-align:center;">
  <a class="btn" href="{{url_for('home')}}">← Back</a>
</div>
""" + TPL_F

    return render_template_string(
        html,
        rows=display_rows,
        total_received=total_received,
        total_pending=total_pending,
        request=request,
        project=get_setting("project_name")
    )


# ── Add this new route anywhere in your app (preferably after the payments route) ──
@app.route("/payments/update", methods=["POST"])
@login_required
def payments_update():
    inv_no   = request.form.get("inv_no")
    received = request.form.get("received", "").strip()
    remarks  = request.form.get("remarks", "").strip()

    if not inv_no:
        return "Missing invoice number", 400

    con = db()
    cur = con.cursor()

    try:
        con.execute("BEGIN")

        # Update / insert received amount
        if received:
            try:
                amount = float(received)
                if amount < 0:
                    raise ValueError("Amount cannot be negative")

                cur.execute("SELECT 1 FROM payments WHERE inv_no = ?", (inv_no,))
                if cur.fetchone():
                    cur.execute("UPDATE payments SET amount = ? WHERE inv_no = ?", (amount, inv_no))
                else:
                    cur.execute("INSERT INTO payments (inv_no, amount) VALUES (?, ?)", (inv_no, amount))
            except ValueError:
                con.rollback()
                return "Invalid amount format", 400

        # Update remarks (even if empty)
        cur.execute("UPDATE invoices SET remarks = ? WHERE inv_no = ?", (remarks, inv_no))

        con.commit()
        return redirect(url_for("payments", **request.args.to_dict(flat=False)))

    except Exception as e:
        con.rollback()
        return f"Database error: {str(e)}", 500

    finally:
        con.close()

# ================================================
# ---------- Invoices List (with monthly sub-cards) ----------
# ---------- INVOICES (SQLITE | FOLDABLE | FILTER | BUTTONS) ----------
@app.route("/invoices", methods=["GET","POST"])
@login_required
def invoices_list():

    # ---------- POST : DELETE / EDIT ----------
    if request.method == "POST":
        act = request.form.get("action","")
        con = db()
        cur = con.cursor()

        # ----- DELETE INVOICE -----
        if act == "delete":
            inv_no = request.form.get("inv_no_del")

            # restore stock
            cur.execute("""
                SELECT product, qty FROM invoice_items WHERE inv_no=?
            """, (inv_no,))
            for p, q in cur.fetchall():
                cur.execute("""
                    UPDATE products SET stock = stock + ? WHERE name=?
                """, (q, p))

            # delete invoice + items
            cur.execute("DELETE FROM invoice_items WHERE inv_no=?", (inv_no,))
            cur.execute("DELETE FROM invoices WHERE inv_no=?", (inv_no,))
            con.commit()
            con.close()

            # delete pdf
            base = output_base() / "BusinessRecords"
            for p in base.rglob(f"INV_{inv_no}*.pdf"):
                try: p.unlink()
                except: pass

            flash(f"Deleted invoice {inv_no}")
            return redirect(url_for("invoices_list"))

        # ----- EDIT CUSTOMER -----
        if act == "edit":
            inv_no = request.form.get("inv_no_edit")
            name = to_caps(request.form.get("name_edit",""))
            addr = to_caps(request.form.get("address_edit",""))

            cur.execute("""
                UPDATE invoices
                SET customer=?, customer_address=?
                WHERE inv_no=?
            """, (name, addr, inv_no))

            con.commit()
            con.close()
            flash("Invoice updated")
            return redirect(url_for("invoices_list"))

    # ---------- FILTERS ----------
    q = request.args.get("q","").strip().lower()

    con = db()
    cur = con.cursor()

    # ---------- MONTH GROUP ----------
    cur.execute("""
        SELECT substr(date,1,7) ym,
               COUNT(*),
               SUM(total)
        FROM invoices
        GROUP BY ym
        ORDER BY ym DESC
    """)
    months = cur.fetchall()

    data = []
    for ym, cnt, total in months:
        sql = """
            SELECT inv_no, date, customer, customer_address, total
            FROM invoices
            WHERE substr(date,1,7)=?
        """
        params = [ym]

        if q:
            sql += " AND (inv_no LIKE ? OR customer LIKE ? OR customer_address LIKE ?)"
            params += [f"%{q}%", f"%{q}%", f"%{q}%"]

        sql += " ORDER BY date DESC, inv_no DESC"
        cur.execute(sql, params)

        data.append({
            "month": ym,
            "count": cnt,
            "total": total or 0,
            "rows": cur.fetchall()
        })

    con.close()

    # ---------- UI ----------
    html = TPL_H + """
<h3>Invoices</h3>

<button class="btn" onclick="history.back()">⬅ Back</button>
<a class="btn" href="/reports/salesman-month">
  Salesman Month Report
</a>

<a class="btn" href="{{ url_for('report_salesman_month') }}">
  📊 Salesman Month
</a>


<form method="get" class="top" style="margin-top:15px;">
  <input name="q" placeholder="Search invoice / customer / address"
         value="{{request.args.get('q','')}}" style="width:320px;">
  <button class="btn">Search</button>
  <a class="link" href="{{url_for('invoices_list')}}">Clear</a>
</form>

{% for m in data %}
<details open style="margin-top:25px;">
  <summary style="font-size:18px;font-weight:bold;cursor:pointer">
    📁 {{m.month}}
    | Invoices: {{m.count}}
    | Total: Rs {{'%.2f'|format(m.total)}}
  </summary>

  <div style="overflow-x:auto">
  <table>
    <tr>
      <th>Inv#</th><th>Date</th><th>Name</th><th>Address</th>
      <th>Total</th><th>Actions</th>
    </tr>

    {% for r in m.rows %}
    <tr>
      <td>{{r[0]}}</td>
      <td>{{r[1]}}</td>
      <td>{{r[2]}}</td>
      <td>{{r[3]}}</td>
      <td>{{r[4]}}</td>
      <td>
        <a class="btn" target="_blank"
           href="{{ url_for('find_view_pdf', inv=r[0]) }}">View</a>

        <a class="btn" target="_blank"
           href="{{ url_for('find_view_pdf', inv=r[0]) }}"
           style="background:#4caf50;">Download</a>

        <a class="btn" target="_blank"
           href="{{ url_for('share_pdf', inv=r[0]) }}"
           style="background:#25d366;">WhatsApp</a>

        <a class="btn"
           onclick="showEdit('{{r[0]}}','{{r[2]}}','{{r[3]}}')"
           style="background:#1976d2;">Edit</a>

        <form method="post" style="display:inline">
          <input type="hidden" name="action" value="delete">
          <input type="hidden" name="inv_no_del" value="{{r[0]}}">
          <button class="btn" style="background:#c62828"
            onclick="return confirm('Delete invoice {{r[0]}}?')">
            Delete
          </button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
  </div>
</details>
{% endfor %}

<div id="editbox" style="display:none;margin-top:15px" class="card">
  <h4>Edit Invoice</h4>
  <form method="post">
    <input type="hidden" name="action" value="edit">
    <input name="inv_no_edit" id="inv_no_edit" hidden>
    <input name="name_edit" id="name_edit" placeholder="Customer name">
    <input name="address_edit" id="address_edit" placeholder="Address">
    <button class="btn">Save</button>
    <button type="button" class="btn"
      onclick="document.getElementById('editbox').style.display='none'">
      Cancel
    </button>
  </form>
</div>

<script>
function showEdit(inv,name,addr){
  document.getElementById('inv_no_edit').value=inv;
  document.getElementById('name_edit').value=name;
  document.getElementById('address_edit').value=addr;
  document.getElementById('editbox').style.display='block';
}
</script>
""" + TPL_F

    return render_template_string(
        html,
        data=data,
        request=request,
        project=get_setting("project_name")
    )


# ---------- SHARE PDF (SQLITE) ----------
@app.route("/share_pdf")
@app.route("/share_pdf/<inv>")
@login_required
def share_pdf(inv=None):

    # ----- safety: inv missing -----
    if not inv:
        flash("Invoice number missing for WhatsApp")
        return redirect(url_for("invoices_list"))

    # ----- build public link (no gdrive dependency) -----
    link = url_for("find_view_pdf", inv=inv, _external=True)

    # ----- redirect to WhatsApp -----
    return redirect(
        f"https://wa.me/?text=Invoice%20{inv}%20{link}"
    )


# ---------- Edit Invoice (new route) ----------
@app.route("/invoice/edit/<int:inv_no>", methods=["GET", "POST"])
@login_required
def edit_invoice(inv_no):
    prods = load_products()
    custs = load_customers()
    invoices = read_csv(INVOICES)
    invoice = next((r for r in invoices if int(r["inv_no"]) == inv_no), None)
    if not invoice:
        flash("Invoice not found")
        return redirect(url_for("invoices_list"))
    all_lines = read_csv(LINES)
    existing_lines = [r for r in all_lines if int(r["inv_no"]) == inv_no]
    company = get_setting("company_name", "Smart Invoice")
    tax_def = float(get_setting("tax_default", "0") or "0")
    show_logo = (get_setting("logo_show", "1") == "1")
    logo = get_setting("logo_path", "") or None

    if request.method == "POST":
        try:
            name = to_caps(request.form.get("name", ""))
            addr = to_caps(request.form.get("address", ""))
            phone = request.form.get("phone", "")
            tax = float(request.form.get("tax", tax_def))

            # === دستی pending_amount لے کر pending_added سیٹ کرو ===
            pending_input = request.form.get("pending_amount", "").strip()
            try:
                pending_added = float(pending_input) if pending_input else 0.0
            except:
                pending_added = 0.0

            # اگر خالی چھوڑا تو تازہ pending خود ڈال دو
            if pending_added == 0.0 and get_setting("show_pending", "0") == "1":
                pending_added = get_pending(name, addr)
            # =========================================================

            # نئی لائنز جمع کرو
            new_lines = []
            used = set()
            idx = 0
            while True:
                prod = request.form.get(f"prod_{idx}")
                qty_str = request.form.get(f"qty_{idx}")
                if not prod or not qty_str:
                    break
                qty = float(qty_str)
                if qty <= 0:
                    flash("Quantity must be positive")
                    return redirect(url_for("edit_invoice", inv_no=inv_no))
                if prod in used:
                    flash("Same product added twice")
                    return redirect(url_for("edit_invoice", inv_no=inv_no))
                info = next((p for p in prods if p["name"] == prod), None)
                if not info:
                    flash("Invalid product selected")
                    return redirect(url_for("edit_invoice", inv_no=inv_no))
                new_lines.append({"product": prod, "qty": qty, "unit_price": info["unit_price"]})
                used.add(prod)
                idx += 1
            if not new_lines:
                flash("Add at least one item")
                return redirect(url_for("edit_invoice", inv_no=inv_no))

            # درست Grand Total حساب (pending_added شامل)
            gross = sum(l["qty"] * l["unit_price"] for l in new_lines)
            subtotal = gross
            tax_amount = subtotal * (tax / 100.0)
            grand_total = subtotal + tax_amount + pending_added
            # INVOICES کو دوبارہ پڑھو تاکہ تازہ کاپی ملے
            invoices = read_csv(INVOICES)
            # پرانی qty واپس سٹاک میں ڈالو
            prod_rows = read_csv(PRODUCTS)
            for old_line in existing_lines:
                old_prod = old_line["product"]
                old_qty = float(old_line["qty"])
                for r in prod_rows:
                    if r["name"] == old_prod:
                        r["stock"] = f"{float(r.get('stock', '0') or 0) + old_qty:.2f}"
                        break

            # نئی qty کم کرو سٹاک سے
            for new_line in new_lines:
                prod = new_line["product"]
                qty = new_line["qty"]
                info = next((p for p in prod_rows if p["name"] == prod), None)
                if info and qty > info["stock"]:
                    flash(f"Insufficient stock for {prod}")
                    return redirect(url_for("edit_invoice", inv_no=inv_no))
                for r in prod_rows:
                    if r["name"] == prod:
                        r["stock"] = f"{float(r.get('stock', '0') or 0) - qty:.2f}"
                        break
            write_csv(PRODUCTS, prod_rows, ["name","unit_price","purchase_price","stock","min_stock"])

            # ===== INVOICES CSV FULL REPLACE (BY inv_no) =====
            fresh = []
            for r in invoices:
                if int(r["inv_no"]) != inv_no:
                    fresh.append(r)

            fresh.append({
                "inv_no": inv_no,
                "date": invoice["date"],
                "name": name,
                "address": addr,
                "phone": phone,
                "tax": f"{tax:.2f}",
                "total": f"{grand_total:.2f}",
                "logo_path": invoice.get("logo_path",""),
                "pending_added": f"{pending_added:.2f}"
            })

            write_csv(
                INVOICES,
                fresh,
                ["inv_no","date","name","address","phone","tax","total","logo_path","pending_added"]
            )
            # ===============================================

            # LINES کو مکمل تبدیل کرو
            all_lines = read_csv(LINES)  # fresh reload
            remaining_lines = [r for r in all_lines if int(r["inv_no"]) != inv_no]
            for line in new_lines:
                remaining_lines.append({
                    "inv_no": inv_no,
                    "product": line["product"],
                    "qty": f"{line['qty']}",
                    "unit_price": f"{line['unit_price']}"
                })
            write_csv(LINES, remaining_lines, ["inv_no","product","qty","unit_price"])

            # sales_log کو بھی اپ ڈیٹ کرو
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM sales_log WHERE inv_no = ?", (inv_no,))
            date_str = invoice["date"]
            for line in new_lines:
                c.execute("""INSERT INTO sales_log (date, inv_no, product, qty, sell_price)
                             VALUES (?, ?, ?, ?, ?)""",
                          (date_str, inv_no, line["product"], line["qty"], line["unit_price"]))
            conn.commit()
            conn.close()

            # نیا PDF جنریٹ کرو (pending_added پاس کرو)
            now = datetime.datetime.now()
            out_dir = ensure_out_dirs(now.year, now.strftime("%B"))
            pdf_name = f"INV_{inv_no}_{safe_name(name)}_{safe_name(addr)}.pdf"
            out_path = out_dir / pdf_name
            draw_invoice_pdf(out_path, company, logo, show_logo, inv_no, date_str, name, addr, phone, new_lines, tax, pending_added)

            flash(f"Invoice #{inv_no} successfully updated!")
            return redirect(url_for("invoices_list"))
        except Exception as e:
            flash(f"Error updating invoice: {str(e)}")
            return redirect(url_for("edit_invoice", inv_no=inv_no))

    # GET request - ایڈیٹ فارم دکھاؤ
    html = TPL_H + """
<h3>Edit Invoice #{{ inv_no }}</h3>
<div class="flex">
  <div style="flex:1">
    <form method="post" id="invoiceForm">
      <div class="top">
        <div>
          <input name="name" value="{{ invoice.name }}" list="cust_names" required>
          <datalist id="cust_names">{% for c in custs %}<option value="{{ c.name }}">{% endfor %}</datalist>
          <input name="address" value="{{ invoice.address }}" list="cust_addr" required>
          <datalist id="cust_addr">{% for c in custs %}<option value="{{ c.address }}">{% endfor %}</datalist>
          <input name="phone" value="{{ invoice.phone }}" placeholder="Phone">
          <input name="tax" value="{{ invoice.tax }}" type="number" step="0.01" placeholder="Tax %">
          <input name="pending_amount" value="{{ invoice.pending_added }}" type="number" step="any" min="0" placeholder="Pending Amount (manual edit allowed)" style="width:250px; margin-left:10px;">
        </div>
      </div>
      <table id="tbl">
        <thead><tr><th>Product</th><th>Qty</th><th>Unit Price</th><th>Total</th><th></th></tr></thead>
        <tbody>
          {% for line in existing_lines %}
          <tr>
            <td><select name="prod_{{ loop.index0 }}" required style="width:100%">
                <option value="{{ line.product }}" selected>{{ line.product }}</option>
                {% for p in prods %}<option value="{{ p.name }}">{{ p.name }}</option>{% endfor %}
            </select></td>
            <td><input name="qty_{{ loop.index0 }}" value="{{ line.qty }}" type="number" step="any" min="0" required></td>
            <td><input value="{{ line.unit_price }}" disabled></td>
            <td><input value="{{ (line.qty|float * line.unit_price|float)|round(2) }}" disabled></td>
            <td><button type="button" class="btn" onclick="this.closest('tr').remove()">X</button></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <p>
        <button type="button" class="btn" onclick="addRow()">+ Add Item</button>
        <button class="btn" style="background:#1976d2;">Update Invoice</button>
        <a class="link" href="{{ url_for('invoices_list') }}">Cancel</a>
      </p>
    </form>
  </div>
</div>
<script>
let row = {{ existing_lines|length }};
function addRow() {
  const tb = document.querySelector("#tbl tbody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><select name="prod_${row}" required style="width:100%">
        <option value="">-- select --</option>
        {% for p in prods %}<option value="{{ p.name }}">{{ p.name }}</option>{% endfor %}
    </select></td>
    <td><input name="qty_${row}" type="number" step="any" min="0" required></td>
    <td><input disabled></td>
    <td><input disabled></td>
    <td><button type="button" class="btn" onclick="this.closest('tr').remove()">X</button></td>
  `;
  tb.appendChild(tr);
  row++;
}
</script>
""" + TPL_F
    return render_template_string(
        html,
        prods=prods,
        custs=custs,
        invoice=invoice,
        existing_lines=existing_lines,
        inv_no=inv_no,
        project=get_setting("project_name")
    )
# ---------- find_view_pdf ----------
@app.route("/find_view_pdf")
@app.route("/find_view_pdf/<inv>")
@login_required
def find_view_pdf(inv=None):

    # ---------- Safety check ----------
    if not inv:
        flash("Invoice number missing")
        return redirect(url_for("invoices_list"))

    # ---------- Fetch invoice from SQLITE ----------
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT inv_no, date, customer, customer_address
        FROM invoices
        WHERE inv_no = ?
    """, (inv,))
    row = cur.fetchone()
    con.close()

    if not row:
        flash("Invoice not found")
        return redirect(url_for("invoices_list"))

    inv_no, d, customer, address = row

    # ---------- Date parsing (safe) ----------
    try:
        if "-" in d and len(d.split("-")[2]) == 2:
            dt = datetime.datetime.strptime(d, "%d-%m-%y")
        elif "-" in d and len(d.split("-")[2]) == 4:
            dt = datetime.datetime.strptime(d, "%d-%m-%Y")
        else:
            dt = datetime.datetime.strptime(d, "%Y-%m-%d")
    except:
        dt = datetime.datetime.now()

    # ---------- Safe filename ----------
    name_safe = safe_name(to_caps(customer))
    addr_safe = safe_name(to_caps(address))
    fn = f"INV_{inv_no}_{name_safe}_{addr_safe}.pdf"

    # ---------- Redirect to PDF viewer ----------
    return redirect(
        url_for(
            "view_pdf",
            y=dt.year,
            m=dt.strftime("%B"),
            fn=fn
        )
    )


# ---------- reports ----------
@app.route("/reports", methods=["GET", "POST"])
@login_required
def reports():
    today = datetime.date.today()
    today_str = today.isoformat()
    current_month = today.strftime("%B %Y")

    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()

    # 1. آج کی سیلز
    cur.execute("""
        SELECT COALESCE(SUM(total), 0) AS today_sales
        FROM invoices
        WHERE date = ?
    """, (today_str,))
    today_sales = cur.fetchone()[0] or 0.0

    # 2. آج کے اخراجات
    cur.execute("""
        SELECT COALESCE(SUM(amount), 0) AS today_expenses
        FROM expenses
        WHERE date = ?
    """, (today_str,))
    today_expenses = cur.fetchone()[0] or 0.0

    # 3. ٹاپ 10 سیلنگ پروڈکٹس (تمام وقت یا موجودہ مہینہ - آپ منتخب کر سکتے ہیں)
    cur.execute("""
        SELECT p.name, SUM(ii.qty) as total_qty, SUM(ii.qty * ii.price) as total_amount
        FROM invoice_items ii
        JOIN products p ON p.name = ii.product
        JOIN invoices i ON i.inv_no = ii.inv_no
        WHERE i.date LIKE ? || '%'
        GROUP BY p.name
        ORDER BY total_amount DESC
        LIMIT 10
    """, (today.strftime("%Y-%m"),))
    top_products = cur.fetchall()

    # 4. ٹاپ 10 کسٹمرز (تمام وقت یا موجودہ مہینہ)
    cur.execute("""
        SELECT customer, customer_address, SUM(total) as total_spent
        FROM invoices
        WHERE date LIKE ? || '%'
        GROUP BY customer, customer_address
        ORDER BY total_spent DESC
        LIMIT 10
    """, (today.strftime("%Y-%m"),))
    top_customers = cur.fetchall()

    con.close()

    # PDF سمری والا حصہ (اگر رکھنا چاہتے ہیں تو رکھیں، ورنہ ہٹا دیں)
    base_dir = output_base() / "BusinessRecords" / str(today.year) / current_month.split()[0]
    base_dir.mkdir(parents=True, exist_ok=True)
    pdf_filename = f"SUMMARY_{today.year}_{current_month.split()[0]}.pdf"
    pdf_exists = (base_dir / pdf_filename).exists()

    html = TPL_H + """
<style>
  .accordion {
    background: #f8f9fa;
    border-radius: 8px;
    margin-bottom: 16px;
    overflow: hidden;
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  }
  .accordion summary {
    padding: 16px;
    font-size: 18px;
    font-weight: 600;
    background: #1976d2;
    color: white;
    cursor: pointer;
    user-select: none;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .accordion summary::after {
    content: '▼';
    transition: transform 0.3s;
  }
  .accordion[open] summary::after {
    transform: rotate(180deg);
  }
  .accordion .content {
    padding: 16px;
    background: white;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th, td {
    padding: 10px;
    text-align: left;
    border-bottom: 1px solid #eee;
  }
  th {
    background: #f0f0f0;
  }
  @media (max-width: 600px) {
    .accordion summary { font-size: 16px; padding: 14px; }
    th, td { font-size: 14px; padding: 8px; }
  }
</style>

<h2>📊 Reports Dashbord </h2>

<a href="{{ url_for('home') }}" class="btn" style="margin-bottom:20px;">← Back</a>

<!-- آج کا خلاصہ -->
<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:16px; margin-bottom:24px;">
  <div class="card" style="background:#e3f2fd; border-left:5px solid #1976d2;">
    <h4>Today Sale</h4>
    <p style="font-size:28px; font-weight:bold; color:#1565c0;">
      Rs {{ "%.2f"|format(today_sales) }}
    </p>
  </div>
  <div class="card" style="background:#ffebee; border-left:5px solid #c62828;">
    <h4>Today Expence </h4>
    <p style="font-size:28px; font-weight:bold; color:#c62828;">
      Rs {{ "%.2f"|format(today_expenses) }}
    </p>
  </div>
  <div class="card" style="background:#e8f5e9; border-left:5px solid #2e7d32;">
    <h4>Today Profit </h4>
    <p style="font-size:28px; font-weight:bold; color:#2e7d32;">
      Rs {{ "%.2f"|format(today_sales - today_expenses) }}
    </p>
  </div>
</div>

<!-- فولڈ ایبل سیکشنز -->
<details class="accordion">
  <summary>Top 10 Salling Product(Current Month)</summary>
  <div class="content">
    {% if top_products %}
    <table>
      <tr><th>Product</th><th>Total qty</th><th>Total Amount</th></tr>
      {% for p in top_products %}
      <tr>
        <td>{{ p[0] }}</td>
        <td style="text-align:center;">{{ "%.2f"|format(p[1]) }}</td>
        <td style="text-align:right; font-weight:bold;">Rs {{ "%.2f"|format(p[2]) }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p style="color:#777;">There have been no sales so far this month.</p>
    {% endif %}
  </div>
</details>

<details class="accordion">
  <summary>Top 10 Customers (Current Month)</summary>
  <div class="content">
    {% if top_customers %}
    <table>
      <tr><th>Customers</th><th>Adress</th><th>Total Expence</th></tr>
      {% for c in top_customers %}
      <tr>
        <td>{{ c[0] }}</td>
        <td>{{ c[1] }}</td>
        <td style="text-align:right; font-weight:bold;">Rs {{ "%.2f"|format(c[2]) }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p style="color:#777;">No customers have visited so far this month.</p>
    {% endif %}
  </div>
</details>

<!-- اگر آپ چاہتے ہیں کہ PDF جنریشن کا بٹن بھی رہے تو یہاں شامل کریں -->
<div style="margin-top:30px; text-align:center;">
  <form method="post">
    <button type="submit" name="action" value="build" class="btn" 
            style="background:#ff9800; padding:12px 40px; font-size:17px;">
      Current Month Summary PDF
    </button>
  </form>
</div>

<script>
  // فولڈ ایبل کو ایک وقت میں صرف ایک کھلا رکھنے کا آپشن (اختیاری)
  document.querySelectorAll('details.accordion').forEach(d => {
    d.addEventListener('toggle', function() {
      if (this.open) {
        document.querySelectorAll('details.accordion').forEach(other => {
          if (other !== this) other.open = false;
        });
      }
    });
  });
</script>
""" + TPL_F

    return render_template_string(
        html,
        today_sales=today_sales,
        today_expenses=today_expenses,
        top_products=top_products,
        top_customers=top_customers,
        project=get_setting("project_name")
    )

@app.route("/reports/salesman-month")
@login_required
def report_salesman_month():
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT 
            i.salesman,
            i.inv_no,
            i.date,
            i.customer,
            i.customer_address,
            i.total
        FROM invoices i
        WHERE i.salesman != '' AND i.salesman IS NOT NULL
        ORDER BY salesman ASC, date DESC
    """)
    rows = cur.fetchall()
    con.close()

    # سیلزمین وائز گروپنگ
    from collections import defaultdict
    salesman_data = defaultdict(list)

    for salesman, inv_no, date, customer, address, total in rows:
        salesman_data[salesman].append({
            "inv_no": inv_no,
            "date": date,
            "customer": customer,
            "address": address,
            "total": float(total or 0)
        })

    html = TPL_H + """
<style>
  .salesman-section {
    margin: 20px 0;
    border: 1px solid #ccc;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  }
  .salesman-header {
    background: #1976d2;
    color: white;
    padding: 16px;
    font-size: 20px;
    font-weight: bold;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .salesman-header::after {
    content: '▼';
    transition: transform 0.3s;
  }
  details[open] .salesman-header::after {
    transform: rotate(180deg);
  }
  .invoice-table {
    padding: 15px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th, td {
    padding: 10px;
    text-align: left;
    border-bottom: 1px solid #eee;
  }
  th {
    background: #1976d2;
    color: white;
  }
  .total {
    background: #e8f5e9;
    font-weight: bold;
    text-align: right;
    padding: 12px;
  }
  @media (max-width: 768px) {
    thead { display: none; }
    tr {
      display: block;
      margin-bottom: 12px;
      border: 1px solid #ddd;
      border-radius: 6px;
      background: white;
    }
    td {
      display: block;
      text-align: right;
      position: relative;
      padding-left: 50%;
      border: none;
    }
    td:before {
      content: attr(data-label);
      position: absolute;
      left: 10px;
      width: 45%;
      font-weight: bold;
      text-align: left;
    }
  }
</style>

<h3>📊 Salesman Wise Invoices Report</h3>

<button class="btn" onclick="history.back()" style="margin-bottom:20px;">← Back</button>

{% for salesman, invoices in salesman_data.items() %}
<details class="salesman-section">
  <summary class="salesman-header">
    {{ salesman }} — {{ invoices|length }} Invoices — 
    Total Sales: Rs {{ "%.2f"|format(invoices|sum(attribute='total')) }}
  </summary>

  <div class="invoice-table">
    <table>
      <thead>
        <tr>
          <th>Invoice No</th>
          <th>Date</th>
          <th>Customer</th>
          <th>Address</th>
          <th>Total Amount</th>
        </tr>
      </thead>
      <tbody>
        {% for inv in invoices %}
        <tr>
          <td data-label="Invoice No">{{ inv.inv_no }}</td>
          <td data-label="Date">{{ inv.date }}</td>
          <td data-label="Customer">{{ inv.customer }}</td>
          <td data-label="Address">{{ inv.address }}</td>
          <td data-label="Total Amount" style="font-weight:bold; color:#2e7d32;">
            Rs {{ "%.2f"|format(inv.total) }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <div class="total">
      Grand Total for {{ salesman }}: Rs {{ "%.2f"|format(invoices|sum(attribute='total')) }}
    </div>
  </div>
</details>
{% endfor %}

{% if not salesman_data %}
<p style="text-align:center; padding:40px; color:#777;">
  No invoices with salesman assigned yet.
</p>
{% endif %}

<script>
// ایک وقت میں صرف ایک سیلزمین کھلا رکھنے کا آپشن (اختیاری)
document.querySelectorAll('.salesman-header').forEach(header => {
  header.addEventListener('click', function(e) {
    if (e.target.tagName !== 'SUMMARY') return;
    document.querySelectorAll('details.salesman-section').forEach(d => {
      if (d !== this.parentElement) d.open = false;
    });
  });
});
</script>
""" + TPL_F

    return render_template_string(
        html,
        salesman_data=salesman_data,
        project=get_setting("project_name")
    )


@app.route("/reports/salesman")
@login_required
def report_salesman():

    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT salesman,
               COUNT(*) AS invs,
               SUM(total) AS total
        FROM invoices
        GROUP BY salesman
        ORDER BY salesman
    """)
    rows = cur.fetchall()
    con.close()

    html = TPL_H + """
    <h3>Salesman Wise Sales</h3>
    <button class="btn" onclick="history.back()">⬅ Back</button>
    <table>
      <tr><th>Salesman</th><th>Invoices</th><th>Total</th></tr>
      {% for r in rows %}
      <tr>
        <td>{{r[0]}}</td>
        <td>{{r[1]}}</td>
        <td>Rs {{'%.2f'|format(r[2] or 0)}}</td>
      </tr>
      {% endfor %}
    </table>
    """ + TPL_F

    return render_template_string(html, rows=rows, project=get_setting("project_name"))

#---saleman list
@app.route("/settings/salesmen", methods=["GET", "POST"])
@login_required
def settings_salesmen():
    conn = db()
    cur = conn.cursor()

    message = ""
    search_query = request.args.get("search", "").strip().lower()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            name = request.form.get("name", "").strip()
            role = request.form.get("role", "salesman").strip().lower()
            if name:
                try:
                    cur.execute(
                        "INSERT INTO salesmen (name, role, active, permissions) VALUES (?, ?, 1, ?)",
                        (name, role, json.dumps({}))
                    )
                    conn.commit()
                    message = f"Salesman '{name}' added with role '{role}'"
                except sqlite3.IntegrityError:
                    message = f"'{name}' already exists"
            else:
                message = "Name is required"

        elif action == "update_role":
            sid = request.form.get("sid")
            new_role = request.form.get("new_role", "salesman").strip().lower()
            if sid:
                cur.execute("UPDATE salesmen SET role = ? WHERE id = ?", (new_role, sid))
                conn.commit()
                message = "Role updated"

        elif action == "update_permissions":
            sid = request.form.get("sid")
            if sid:
                permissions = {
                    "view_all_invoices": "view_all_invoices" in request.form,
                    "view_own_invoices": "view_own_invoices" in request.form,
                    "view_stock": "view_stock" in request.form,
                    "view_sale_record": "view_sale_record" in request.form,
                    "view_expenses": "view_expenses" in request.form,
                    "create_order_sheet": "create_order_sheet" in request.form,
                    "convert_order_sheet": "convert_order_sheet" in request.form,
                    "edit_records": "edit_records" in request.form
                }
                cur.execute("UPDATE salesmen SET permissions = ? WHERE id = ?",
                            (json.dumps(permissions), sid))
                conn.commit()
                message = "Permissions saved successfully"

        elif action == "delete":
            sid = request.form.get("sid")
            if sid:
                cur.execute("DELETE FROM salesmen WHERE id = ?", (sid,))
                conn.commit()
                message = "Salesman deleted"

    # Load salesmen with permissions
    query = "SELECT id, name, role, active, permissions FROM salesmen"
    params = []
    if search_query:
        query += " WHERE LOWER(name) LIKE ?"
        params.append(f"%{search_query}%")
    query += " ORDER BY name ASC"

    cur.execute(query, params)
    salesmen = []
    for row in cur.fetchall():
        permissions = json.loads(row[4]) if row[4] else {}
        salesmen.append({
            "id": row[0],
            "name": row[1],
            "role": row[2],
            "active": row[3],
            "permissions": permissions
        })

    conn.close()

    html = TPL_H + """
<h2>Settings - Salesmen Management</h2>

{% if message %}
<div style="padding:12px; background:#e8f5e9; border-left:5px solid #4caf50; margin:15px 0; border-radius:4px;">
    {{ message }}
</div>
{% endif %}

<!-- Search -->
<form method="get" style="margin-bottom:20px;">
    <input type="text" name="search" value="{{ request.args.get('search', '') }}" placeholder="Search by name..." style="padding:10px; width:300px; border:1px solid #ccc; border-radius:4px;">
    <button type="submit" style="background:#2196f3; color:white; padding:10px 16px; border:none; border-radius:4px;">Search</button>
    <a href="{{ url_for('settings_salesmen') }}" style="margin-left:10px; color:#555;">Clear</a>
</form>

<!-- Add New -->
<div style="background:white; padding:20px; border-radius:8px; box-shadow:0 2px 10px rgba(0,0,0,0.08); margin-bottom:30px;">
    <h3>Add New Salesman</h3>
    <form method="post">
        <input type="hidden" name="action" value="add">
        <div style="display:flex; gap:16px; flex-wrap:wrap; align-items:center;">
            <input name="name" placeholder="Salesman Name" required style="flex:1; padding:10px; min-width:220px; border:1px solid #ccc; border-radius:4px;">
            <select name="role" style="padding:10px; min-width:160px; border:1px solid #ccc; border-radius:4px;">
                <option value="salesman">Salesman</option>
                <option value="manager">Manager</option>
                <option value="admin">Admin</option>
            </select>
            <button type="submit" style="background:#4caf50; color:white; padding:10px 20px; border:none; border-radius:4px;">Add</button>
        </div>
    </form>
</div>

<!-- List -->
<h3>Current Salesmen ({{ salesmen|length }})</h3>

{% if salesmen %}
<table style="width:100%; border-collapse:collapse; background:white; box-shadow:0 2px 10px rgba(0,0,0,0.08);">
    <thead style="background:#f5f5f5;">
        <tr>
            <th style="padding:12px; text-align:left;">Name</th>
            <th style="padding:12px; text-align:center;">Role</th>
            <th style="padding:12px; text-align:center; width:300px;">Permissions</th>
            <th style="padding:12px; text-align:center;">Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for s in salesmen %}
        <tr style="border-bottom:1px solid #eee;">
            <td style="padding:12px; font-weight:500;">{{ s.name }}</td>
            <td style="padding:12px; text-align:center;">
                <form method="post" style="margin:0;">
                    <input type="hidden" name="action" value="update_role">
                    <input type="hidden" name="sid" value="{{ s.id }}">
                    <select name="new_role" onchange="this.form.submit()" style="padding:6px; border-radius:4px;">
                        <option value="salesman" {% if s.role == 'salesman' %}selected{% endif %}>Salesman</option>
                        <option value="manager" {% if s.role == 'manager' %}selected{% endif %}>Manager</option>
                        <option value="admin" {% if s.role == 'admin' %}selected{% endif %}>Admin</option>
                    </select>
                </form>
            </td>
            <td style="padding:12px; text-align:left;">
                <form method="post" style="margin:0;">
                    <input type="hidden" name="action" value="update_permissions">
                    <input type="hidden" name="sid" value="{{ s.id }}">
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:0.9em;">
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="view_all_invoices" {% if s.permissions.get('view_all_invoices') %}checked{% endif %}>
                            View All Invoices
                        </label>
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="view_own_invoices" {% if s.permissions.get('view_own_invoices') %}checked{% endif %}>
                            View Own Invoices
                        </label>
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="view_stock" {% if s.permissions.get('view_stock') %}checked{% endif %}>
                            View Stock
                        </label>
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="view_sale_record" {% if s.permissions.get('view_sale_record') %}checked{% endif %}>
                            View Sale Record
                        </label>
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="view_expenses" {% if s.permissions.get('view_expenses') %}checked{% endif %}>
                            View Expenses
                        </label>
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="create_order_sheet" {% if s.permissions.get('create_order_sheet') %}checked{% endif %}>
                            Create Order Sheet
                        </label>
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="convert_order_sheet" {% if s.permissions.get('convert_order_sheet') %}checked{% endif %}>
                            Convert Order Sheet
                        </label>
                        <label style="display:flex; align-items:center; gap:6px;">
                            <input type="checkbox" name="edit_records" {% if s.permissions.get('edit_records') %}checked{% endif %}>
                            Edit Records
                        </label>
                    </div>
                    <button type="submit" style="margin-top:12px; background:#2196f3; color:white; padding:8px 16px; border:none; border-radius:4px; cursor:pointer;">Save Permissions</button>
                </form>
            </td>
            <td style="padding:12px; text-align:center;">
                <form method="post" onsubmit="return confirm('Delete {{ s.name }}?');" style="display:inline;">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="sid" value="{{ s.id }}">
                    <button type="submit" style="background:#f44336; color:white; padding:8px 14px; border:none; border-radius:4px; cursor:pointer;">Delete</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<div style="text-align:center; padding:40px; color:#777; background:#fafafa; border-radius:8px;">
    No salesmen added yet.
</div>
{% endif %}

<a href="{{ url_for('home') }}" class="btn" style="margin-top:30px; display:inline-block;">← Back to Home</a>
    """ + TPL_F

    return render_template_string(html, salesmen=salesmen, message=message, project=get_setting("project_name"))


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

from flask import send_file, abort

@app.route("/view_pdf/<int:y>/<m>/<path:fn>")
@login_required
def view_pdf(y, m, fn):
    # مکمل فائل کا پاتھ بنائیں (آپ کے output_base() فنکشن کے مطابق)
    pdf_dir = output_base() / "BusinessRecords" / str(y) / m
    pdf_path = pdf_dir / fn

    # سیکیورٹی چیک: فائل موجود ہے؟ اور PDF ہے؟
    if not pdf_path.exists() or not pdf_path.is_file() or not fn.lower().endswith('.pdf'):
        abort(404, description="PDF file not found or invalid format")

    # اگر ?print=1 ہے تو براہ راست پرنٹ کرنے کے لیے send_file استعمال کریں
    if request.args.get('print') == '1':
        return send_file(
            pdf_path,
            mimetype='application/pdf',
            as_attachment=False,
            conditional=True
        )

    # نارمل ویو: ایمبیڈ کے ساتھ HTML
    html = """
<!doctype html>
<html lang="ur" dir="rtl">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PDF دیکھیں – {{ fn }}</title>
    <style>
        body, html { margin:0; padding:0; height:100%; overflow:hidden; font-family: system-ui, sans-serif; }
        #pdf-container { height:100vh; width:100vw; }
        #pdfembed { width:100%; height:100%; border:none; }
        #toolbar {
            position: fixed;
            top: 10px;
            right: 10px;
            z-index: 1000;
            background: rgba(0,0,0,0.6);
            color: white;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 14px;
        }
        #toolbar a { color: #4fc3f7; text-decoration: none; margin-left: 12px; }
    </style>
</head>
<body>
    <div id="pdf-container">
        <embed src="{{ url_for('serve_pdf_file', path=pdf_path.relative_to(output_base())) }}" 
               type="application/pdf" 
               width="100%" 
               height="100%" 
               id="pdfembed">
    </div>

    <div id="toolbar">
        <strong>فائل:</strong> {{ fn }} &nbsp;|&nbsp;
        <a href="{{ url_for('view_pdf', y=y, m=m, fn=fn, print=1) }}" target="_blank">🖨️ پرنٹ کریں</a>
    </div>

    <script>
        // اگر موبائل ہے تو ایمبیڈ کو بہتر بنائیں
        if (/Mobi|Android/i.test(navigator.userAgent)) {
            document.getElementById('pdfembed').setAttribute('src', 
                '{{ url_for('serve_pdf_file', path=pdf_path.relative_to(output_base())) }}');
        }
    </script>
</body>
</html>
    """

    return render_template_string(
        html,
        y=y,
        m=m,
        fn=fn,
        pdf_path=pdf_path,  # اگر ضرورت ہو تو
        output_base=output_base
    )

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
<a href="/settings/salesmen" class="btn">Salesmen</a>
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
    from collections import defaultdict
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # ماہانہ پروڈکٹ وائز سیلڈ مقدار (SQLite سے)
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
    rows = c.fetchall()
    conn.close()

    # ڈیٹا کو گروپ کریں
    monthly_data = defaultdict(list)
    grand_totals = defaultdict(float)

    for ym, month_name, product, qty in rows:
        if not month_name:  # خالی مہینہ چھوڑ دیں
            continue
        monthly_data[month_name].append({
            "sr_no": 0,  # بعد میں اپ ڈیٹ کریں گے
            "product": to_caps(product),
            "qty": float(qty or 0)
        })
        grand_totals[month_name] += float(qty or 0)

    # ہر مہینے میں Sr No شامل کریں (نمبرنگ)
    for month_name, items in monthly_data.items():
        for index, item in enumerate(items, start=1):
            item["sr_no"] = index

    # مہینوں کو ڈیٹ کے لحاظ سے ترتیب دیں (سب سے نیا پہلے)
    sorted_months = sorted(
        monthly_data.keys(),
        key=lambda m: datetime.datetime.strptime(m, "%B %Y") if isinstance(m, str) else datetime.datetime.min,
        reverse=True
    )

    html = TPL_H + """
<style>
  .month-card {
    margin-bottom: 25px;
    border: 1px solid #ddd;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }
  .month-header {
    background: #1976d2;
    color: white;
    padding: 16px;
    font-size: 19px;
    font-weight: bold;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .month-header::after {
    content: '▼';
    transition: transform 0.3s;
  }
  details[open] .month-header::after {
    transform: rotate(180deg);
  }
  .table-container {
    padding: 15px;
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th, td {
    padding: 10px;
    text-align: left;
    border-bottom: 1px solid #eee;
  }
  th {
    background: #1976d2;
    color: white;
  }
  .total-row {
    background: #e8f5e9;
    font-weight: bold;
    text-align: right;
  }
  .search-box {
    width: 100%;
    max-width: 700px;
    padding: 14px;
    font-size: 16px;
    border-radius: 10px;
    border: 2px solid #1976d2;
    margin: 20px 0;
  }
  @media (max-width: 768px) {
    thead { display: none; }
    tr {
      display: block;
      margin-bottom: 12px;
      border: 1px solid #ddd;
      border-radius: 6px;
      background: white;
    }
    td {
      display: block;
      text-align: right;
      position: relative;
      padding-left: 50%;
      border: none;
    }
    td:before {
      content: attr(data-label);
      position: absolute;
      left: 10px;
      width: 45%;
      font-weight: bold;
      text-align: left;
    }
  }
</style>

<h2>📊 Sales Record (Monthly Product-wise)</h2>

<input type="text" id="globalSearch" class="search-box"
       placeholder="🔍 Search product name...">

{% if sorted_months %}
  {% for month in sorted_months %}
  <details class="month-card">
    <summary class="month-header">
      {{ month }} — Total Sold Qty: {{ "%.2f"|format(grand_totals[month]) }} ⬇
    </summary>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Sr No</th>
            <th>Product</th>
            <th>Sold Qty</th>
          </tr>
        </thead>
        <tbody>
          {% for item in monthly_data[month] %}
          <tr class="searchable">
            <td data-label="Sr No">{{ item.sr_no }}</td>
            <td data-label="Product">{{ item.product }}</td>
            <td data-label="Sold Qty" style="font-weight:bold; color:#1565c0; text-align:center;">
              {{ "%.2f"|format(item.qty) }}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </details>
  {% endfor %}
{% else %}
  <div class="card" style="text-align:center; padding:50px; color:#666;">
    <h3>No Sales Record Found</h3>
    <p>Data will appear after sales are recorded.</p>
  </div>
{% endif %}

<div style="text-align:center; margin-top:40px;">
  <a href="{{ url_for('home') }}" class="btn" style="padding:14px 45px; font-size:18px;">
    ⬅ Back to Home
  </a>
</div>

<script>
// Global Search Filter
document.getElementById('globalSearch').addEventListener('keyup', function() {
  let val = this.value.toLowerCase().trim();
  document.querySelectorAll('.searchable').forEach(row => {
    row.style.display = row.innerText.toLowerCase().includes(val) ? '' : 'none';
  });
});
</script>
""" + TPL_F

    return render_template_string(
        html,
        sorted_months=sorted_months,
        monthly_data=monthly_data,
        grand_totals=grand_totals,
        project=get_setting("project_name")
    )

# ================== Stock Entry (Final – Clean & Working) ==================
# ---------- STOCK ENTRY (SQLITE + SMART AUTOSUGGEST) ----------
@app.route("/stock_entry", methods=["GET", "POST"])
@login_required
def stock_entry():

    msg = ""
    now = datetime.datetime.now()

    # ---------- POST ----------
    if request.method == "POST":
        action = request.form.get("action","")

        con = db()
        cur = con.cursor()

        # ----- DELETE ENTRY -----
        if action == "delete":
            eid = request.form.get("entry_id")

            cur.execute("SELECT product, qty FROM purchases WHERE id=?", (eid,))
            row = cur.fetchone()
            if row:
                product, qty = row
                cur.execute("""
                    UPDATE products
                    SET stock = MAX(0, stock - ?)
                    WHERE name=?
                """, (qty, product))
                cur.execute("DELETE FROM purchases WHERE id=?", (eid,))
                con.commit()
                flash("Entry deleted & stock updated")

            con.close()
            return redirect(url_for("stock_entry"))

        # ----- ADD ENTRY -----
        product = to_caps(request.form.get("product","").strip())
        qty_str = request.form.get("qty","").strip()
        price_str = request.form.get("price","").strip()

        try:
            qty = float(qty_str)
            if qty <= 0:
                raise ValueError
        except:
            msg = "Quantity invalid"
        else:
            # check product
            cur.execute("SELECT unit_price FROM products WHERE name=?", (product,))
            row = cur.fetchone()

            if row:
                # old product → price optional
                price = float(price_str) if price_str else (row[0] or 0.0)
            else:
                # new product → price required
                if not price_str:
                    msg = "New product ke liye price lazmi hai"
                    con.close()
                    return redirect(url_for("stock_entry"))
                price = float(price_str)

            # upsert product
            cur.execute("""
                INSERT INTO products (name, stock, unit_price)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    stock = stock + excluded.stock,
                    unit_price = excluded.unit_price
            """, (product, qty, price))

            # save purchase
            cur.execute("""
                INSERT INTO purchases (date, product, qty, price)
                VALUES (date('now'), ?, ?, ?)
            """, (product, qty, price))

            con.commit()
            con.close()
            flash(f"{qty} × {product} added to stock")
            return redirect(url_for("stock_entry"))

    # ---------- FILTERS ----------
    product_filter = request.args.get("product_filter","").strip().upper()
    from_date = request.args.get("from_date","")
    to_date = request.args.get("to_date","")

    con = db()
    cur = con.cursor()

    # ---------- PRODUCTS (for autosuggest + price) ----------
    cur.execute("SELECT name, unit_price FROM products ORDER BY name")
    product_list = [{"name":r[0], "price":r[1]} for r in cur.fetchall()]

    # ---------- MONTH GROUP ----------
    cur.execute("""
        SELECT substr(date,1,7) ym,
               COUNT(*),
               SUM(qty)
        FROM purchases
        GROUP BY ym
        ORDER BY ym DESC
    """)
    months = cur.fetchall()

    data = []
    for ym, cnt, total in months:
        sql = """
            SELECT id, date, product, qty, price
            FROM purchases
            WHERE substr(date,1,7)=?
        """
        params = [ym]

        if product_filter:
            sql += " AND UPPER(product) LIKE ?"
            params.append(f"%{product_filter}%")
        if from_date:
            sql += " AND date >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND date <= ?"
            params.append(to_date)

        sql += " ORDER BY date DESC, id DESC"
        cur.execute(sql, params)

        data.append({
            "month": ym,
            "count": cnt,
            "total": total or 0,
            "rows": cur.fetchall()
        })

    con.close()

    # ---------- UI ----------
    html = TPL_H + """
<h2>Stock Entry</h2>
<button class="btn" onclick="history.back()">⬅ Back</button>
<a href="{{ url_for('stock_summary') }}" class="btn">
  📦 Stock Summary
</a>


{% if msg %}<div class="notice">{{ msg }}</div>{% endif %}

<form method="post" style="margin-top:20px;position:relative;">
  <input id="product" name="product" placeholder="Product name"
         oninput="filterProducts(this.value)" autocomplete="off" required>

  <div id="suggestions"
       style="border:1px solid #ccc;max-height:180px;overflow:auto;
              display:none;position:absolute;background:white;z-index:999;"></div>

  <input name="qty" type="number" step="any" placeholder="Quantity" required>
  <input id="price" name="price" type="number" step="any"
         placeholder="Purchase price (new product ke liye zaroori)">
  <button class="btn" style="background:#1b5e20">Add Stock</button>
</form>

<form method="get" style="margin-top:20px;">
  <input name="product_filter" placeholder="Filter product">
  <input type="date" name="from_date">
  <input type="date" name="to_date">
  <button class="btn">Filter</button>
</form>

{% for m in data %}
<details open style="margin-top:30px;">
  <summary style="font-size:18px;font-weight:bold;cursor:pointer">
    📁 {{m.month}} | Entries: {{m.count}} | Total Qty: {{m.total}}
  </summary>

  <table style="width:100%;margin-top:10px;">
    <tr><th>ID</th><th>Date</th><th>Product</th><th>Qty</th><th>Price</th><th>Action</th></tr>
    {% for r in m.rows %}
    <tr>
      <td>{{r[0]}}</td>
      <td>{{r[1]}}</td>
      <td>{{r[2]}}</td>
      <td>{{r[3]}}</td>
      <td>{{r[4]}}</td>
      <td>
        <form method="post" style="display:inline;">
          <input type="hidden" name="action" value="delete">
          <input type="hidden" name="entry_id" value="{{r[0]}}">
          <button class="btn" style="background:#c62828"
            onclick="return confirm('Delete this entry? Stock reduce hoga')">
            Delete
          </button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
</details>
{% endfor %}

<script>
const products = {{ product_list|tojson }};

function filterProducts(q){
  q=q.toLowerCase();
  let box=document.getElementById("suggestions");
  box.innerHTML="";
  if(!q){box.style.display="none";return;}
  products.forEach(p=>{
    if(p.name.toLowerCase().includes(q)){
      let d=document.createElement("div");
      d.innerText=p.name;
      d.style.padding="6px";
      d.style.cursor="pointer";
      d.onclick=()=>{
        document.getElementById("product").value=p.name;
        document.getElementById("price").value=p.price||"";
        box.style.display="none";
      };
      box.appendChild(d);
    }
  });
  box.style.display=box.children.length?"block":"none";
}
</script>
""" + TPL_F

    return render_template_string(
        html,
        msg=msg,
        data=data,
        product_list=product_list,
        project=get_setting("project_name")
    )

# ========================================
@app.route("/stock_summary")
@login_required
def stock_summary():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # ---------- Get monthly product totals ----------
    c.execute("""
        SELECT
            substr(date,1,7) AS ym,   -- YYYY-MM
            product,
            SUM(qty) AS total_qty
        FROM purchases
        WHERE date IS NOT NULL AND date != ''
        GROUP BY ym, product
        ORDER BY ym DESC, total_qty DESC
    """)
    rows = c.fetchall()
    conn.close()

    monthly_data = {}   # month_name -> list
    grand_totals = {}   # month_name -> total qty

    for ym, prod, qty in rows:
        if not ym:
            continue

        # ✅ SAFE month name generation
        try:
            month_name = datetime.datetime.strptime(ym, "%Y-%m").strftime("%B %Y")
        except:
            continue

        if month_name not in monthly_data:
            monthly_data[month_name] = []
            grand_totals[month_name] = 0.0

        monthly_data[month_name].append({
            "product": prod,
            "qty": float(qty)
        })
        grand_totals[month_name] += float(qty)

    if not monthly_data:
        flash("No stock entry data found yet.")
        return redirect(url_for("stock_entry"))

    # sort months (latest first)
    sorted_months = sorted(
        monthly_data.keys(),
        key=lambda x: datetime.datetime.strptime(x, "%B %Y"),
        reverse=True
    )
    sorted_result = {m: monthly_data[m] for m in sorted_months}

    # ================= UI =================
    html = TPL_H + """
<h2>📦 Stock Summary (Monthly)</h2>
<p class="small">Stock entered via Stock Entry</p>

<input type="text" id="globalSearch"
       placeholder="🔍 Type product name..."
       style="width:100%;max-width:650px;padding:14px;font-size:16px;
              border-radius:10px;border:2px solid #1976d2;margin:20px 0;">

{% for month, items in sorted_result.items() %}
<div class="card" style="margin-bottom:25px;border-radius:12px;overflow:hidden;">

  <!-- Foldable Header -->
  <button onclick="toggleMonth('{{ loop.index }}')"
          style="width:100%;background:#1976d2;color:white;
                 border:none;padding:16px;font-size:18px;text-align:left;">
    {{ month }}
    <span style="float:right;">
      Total Qty: {{ "%.2f"|format(grand_totals[month]) }} ⬇
    </span>
  </button>

  <!-- Foldable Body -->
  <div id="month_{{ loop.index }}" style="display:none;padding:20px;">
    <table style="width:100%;border-collapse:collapse;">
      <thead style="background:#e3f2fd;">
        <tr>
          <th style="padding:12px;text-align:left;">Product</th>
          <th style="padding:12px;text-align:center;width:180px;">Total Qty</th>
        </tr>
      </thead>
      <tbody>
        {% for item in items %}
        <tr class="search-row">
          <td style="padding:12px;font-weight:600;">{{ item.product }}</td>
          <td style="padding:12px;text-align:center;font-weight:bold;">
            {{ "%.2f"|format(item.qty) }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

</div>
{% endfor %}

<div style="text-align:center;margin-top:40px;">
  <a href="{{ url_for('stock_entry') }}" class="btn"
     style="padding:14px 45px;font-size:18px;">
    ⬅ Back to Stock Entry
  </a>
</div>

<script>
// strong typing filter
document.getElementById('globalSearch').addEventListener('keyup', function() {
  let v = this.value.toLowerCase();
  document.querySelectorAll('.search-row').forEach(r => {
    r.style.display = r.innerText.toLowerCase().includes(v) ? '' : 'none';
  });
});

// fold / unfold
function toggleMonth(i){
  let el = document.getElementById("month_" + i);
  el.style.display = el.style.display === "none" ? "block" : "none";
}
</script>
""" + TPL_F

    return render_template_string(
        html,
        sorted_result=sorted_result,
        grand_totals=grand_totals,
        project=get_setting("project_name")
    )



# 5 PROFESSIONAL ENGLISH CARDS - FINAL VERSION
# ========================================


@app.route("/target", methods=["GET", "POST"])
@login_required
def target():

    import calendar

    today = datetime.date.today()
    current_month = today.strftime("%B %Y")

    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()

    # ---------- SETTINGS ----------
    growth = float(get_setting("growth_rate", "10"))

    # ---------- PRODUCTS ----------
    cur.execute("SELECT name FROM products ORDER BY name")
    products = [r[0] for r in cur.fetchall()]

    # ---------- SAVE / DELETE MANUAL TARGET ----------
    if request.method == "POST":
        action = request.form.get("action","")

        # DELETE
        if action == "delete":
            cur.execute(
                "DELETE FROM targets WHERE product=? AND month=?",
                (request.form["product_del"], request.form["month_del"])
            )
            con.commit()
            return redirect(url_for("target"))

        # SAVE (FIRST MONTH MANUAL)
        product = request.form.get("product")
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
        qty = float(request.form.get("qty",0))

        if not product or qty <= 0:
            flash("Invalid product or quantity")
            return redirect(url_for("target"))

        month_name = f"{calendar.month_name[month]} {year}"

        cur.execute("""
            INSERT INTO targets (month, product, qty)
            VALUES (?, ?, ?)
            ON CONFLICT(month,product)
            DO UPDATE SET qty=excluded.qty
        """,(month_name, product, qty))
        con.commit()

    # ---------- AUTO CREATE CURRENT MONTH FROM SALES (IF NOT EXISTS) ----------
    cur.execute("SELECT DISTINCT product FROM sales_log")
    sold_products = [r[0] for r in cur.fetchall()]

    for prod in sold_products:
        cur.execute("""
            SELECT 1 FROM targets
            WHERE month=? AND product=?
        """,(current_month,prod))
        if cur.fetchone():
            continue

        # sales based qty
        cur.execute("""
            SELECT SUM(qty)
            FROM sales_log
            WHERE product=?
              AND strftime('%B %Y',date)=?
        """,(prod,current_month))
        s = cur.fetchone()[0] or 0

        if s > 0:
            cur.execute("""
                INSERT INTO targets (month,product,qty)
                VALUES (?,?,?)
            """,(current_month,prod,s))

    con.commit()

    # ---------- AUTO CREATE NEXT MONTH (LAST DAY ONLY) ----------
    last_day = calendar.monthrange(today.year,today.month)[1]
    if today.day == last_day:

        next_month = (today.replace(day=28)+datetime.timedelta(days=4)).strftime("%B %Y")

        cur.execute("SELECT product, qty FROM targets WHERE month=?",(current_month,))
        for p,q in cur.fetchall():
            new_qty = q + (q * growth / 100)

            cur.execute("""
                INSERT INTO targets (month,product,qty)
                VALUES (?,?,?)
                ON CONFLICT(month,product)
                DO NOTHING
            """,(next_month,p,new_qty))

        con.commit()

    # ---------- FETCH ALL TARGETS ----------
    cur.execute("SELECT month, product, qty FROM targets")
    targets = cur.fetchall()

    # ---------- ACHIEVED FROM SALES ----------
    cur.execute("""
        SELECT product, SUM(qty)
        FROM sales_log
        WHERE strftime('%B %Y',date)=?
        GROUP BY product
    """,(current_month,))
    achieved = {r[0]:r[1] for r in cur.fetchall()}

    con.close()

    # ---------- GROUP MONTHS ----------
    months = {}
    for m,p,q in targets:
        if m not in months:
            months[m]=[]
        ach = achieved.get(p,0)
        percent = (ach/q*100) if q>0 else 0
        months[m].append({
            "product":p,
            "target":q,
            "achieved":ach,
            "percent":round(percent,1)
        })

    # ---------- SORT MONTHS ----------
    months = dict(sorted(
        months.items(),
        key=lambda x: datetime.datetime.strptime(x[0],"%B %Y"),
        reverse=True
    ))

    # ================= UI =================
    html = TPL_H + """
<h2>🎯 Monthly Targets</h2>

<input id="search" placeholder="🔍 type product..."
       style="width:100%;max-width:500px;padding:14px;border-radius:10px;
              border:2px solid #1976d2;margin:15px 0;">

<form method="post" style="margin-bottom:25px;">
  <select name="product">{% for p in products %}<option>{{p}}</option>{% endfor %}</select>
  <select name="month">{% for m in range(1,13) %}<option value="{{m}}">{{calendar.month_name[m]}}</option>{% endfor %}</select>
  <input name="year" type="number" value="{{today.year}}">
  <input name="qty" type="number" step="any" placeholder="Target Qty">
  <button class="btn">Save</button>
</form>

{% for month,rows in months.items() %}
<div class="card" style="margin-bottom:20px;">
  <button onclick="toggle('{{loop.index}}')"
          style="width:100%;background:#1976d2;color:white;padding:14px;font-size:18px;">
    {{month}}
  </button>

  <div id="m{{loop.index}}"
       style="display:{% if month==current_month %}block{% else %}none{% endif %};padding:20px;">
    <table style="width:100%">
      <tr>
        <th>#</th><th>Product</th><th>Target</th><th>Achieved</th><th>%</th><th></th>
      </tr>
      {% for r in rows %}
      <tr class="row">
        <td>{{loop.index}}</td>
        <td>{{r.product}}</td>
        <td>{{r.target}}</td>
        <td>{{r.achieved}}</td>
        <td style="font-weight:bold;
          color:{{'#c62828' if r.percent<80 else '#ff9800' if r.percent<100 else '#2e7d32'}}">
          {{r.percent}}%
        </td>
        <td>
          <form method="post">
            <input type="hidden" name="action" value="delete">
            <input type="hidden" name="product_del" value="{{r.product}}">
            <input type="hidden" name="month_del" value="{{month}}">
            <button class="btn" style="background:#c62828">Delete</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>
</div>
{% endfor %}

<a href="{{url_for('home')}}" class="btn" style="margin-top:30px;">⬅ Back</a>

<script>
document.getElementById("search").onkeyup=function(){
 let v=this.value.toLowerCase();
 document.querySelectorAll(".row").forEach(r=>{
   r.style.display=r.innerText.toLowerCase().includes(v)?'':'none';
 });
}
function toggle(i){
 let e=document.getElementById("m"+i);
 e.style.display=e.style.display=='none'?'block':'none';
}
</script>
""" + TPL_F

    return render_template_string(
        html,
        products=products,
        months=months,
        today=today,
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
    current_month = today.strftime("%Y-%m")
    full_month_year = today.strftime("%B %Y")

    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()

    # ================= TOTAL SALES (CURRENT MONTH) =================
    cur.execute("""
        SELECT SUM(total)
        FROM invoices
        WHERE substr(date,1,7)=?
    """, (current_month,))
    total_sales = cur.fetchone()[0] or 0.0

    # ================= TOTAL EXPENSES =================
    cur.execute("""
        SELECT SUM(amount)
        FROM expenses
        WHERE substr(date,1,7)=?
    """, (current_month,))
    total_expenses = cur.fetchone()[0] or 0.0

    net_profit = total_sales - total_expenses

    # ================= CURRENT MONTH PRODUCT QTY =================
    cur.execute("""
        SELECT product, SUM(qty)
        FROM sales_log
        WHERE substr(date,1,7)=?
        GROUP BY product
    """, (current_month,))
    sales_qty = {r[0]: r[1] for r in cur.fetchall()}

    # ================= PRODUCTS =================
    cur.execute("SELECT name, unit_price, purchase_price FROM products")
    products = cur.fetchall()

    rows = []
    total_gross_profit = 0.0
    for name, sp, cp in products:
        qty = sales_qty.get(name, 0.0)
        gross = (sp - cp) * qty
        total_gross_profit += gross
        pct = (gross / (cp * qty) * 100) if cp > 0 and qty > 0 else 0
        rows.append({
            "product": name,
            "qty": qty,
            "selling_price": sp,
            "cost_price": cp,
            "gross_profit": gross,
            "percent": round(pct, 1)
        })

    rows.sort(key=lambda x: x["qty"], reverse=True)

    # ================= MONTHLY SALES (ALL MONTHS) =================
    cur.execute("""
        SELECT substr(date,1,7), SUM(total)
        FROM invoices
        GROUP BY substr(date,1,7)
        ORDER BY substr(date,1,7)
    """)
    monthly_sales = cur.fetchall()

    # ================= MONTHLY GROSS PROFIT (ALL MONTHS) =================
    cur.execute("""
        SELECT substr(s.date,1,7) ym,
               SUM((p.unit_price - p.purchase_price) * s.qty)
        FROM sales_log s
        JOIN products p ON p.name = s.product
        GROUP BY ym
        ORDER BY ym
    """)
    monthly_gross = cur.fetchall()

    con.close()

    # ================= UI =================
    html = TPL_H + """
<style>
  @media (max-width: 600px) {
    table { font-size: 14px; }
    th, td { padding: 8px 5px; }
    summary { font-size: 16px !important; }
    .card { padding: 15px; }
  }
</style>

<h2>📊 Profit & Loss – {{ full_month_year }}</h2>

<!-- ===== SUMMARY ===== -->
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;margin:30px 0;">
  <div class="card" style="background:#e3f2fd;border-left:6px solid #1976d2;">
    <h3>Total Sales</h3>
    <p style="font-size:30px;font-weight:bold;">Rs {{ "%.2f"|format(total_sales) }}</p>
  </div>
  <div class="card" style="background:#fff3e0;border-left:6px solid #ff9800;">
    <h3>Gross Profit</h3>
    <p style="font-size:30px;font-weight:bold;">Rs {{ "%.2f"|format(total_gross_profit) }}</p>
  </div>
  <div class="card" style="background:#ffebee;border-left:6px solid #f44336;">
    <h3>Total Expenses</h3>
    <p style="font-size:30px;font-weight:bold;">Rs {{ "%.2f"|format(total_expenses) }}</p>
  </div>
  <div class="card" style="background:{{ '#e8f5e9' if net_profit>=0 else '#ffebee' }};">
    <h3>Net {{ "Profit" if net_profit>=0 else "Loss" }}</h3>
    <p style="font-size:34px;font-weight:bold;">
      Rs {{ "%.2f"|format(net_profit|abs) }}
    </p>
  </div>
</div>

<a href="{{ url_for('home') }}" class="btn" style="margin-top:30px;">⬅ Back</a>

<!-- ===== GRAPH BUTTON ===== -->
<button class="btn" onclick="openGraph()" style="margin-bottom:25px;">
  📈 View Monthly Graph
</button>

<!-- ===== GRAPH MODAL ===== -->
<div id="graphModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:999;">
  <div style="background:white;max-width:900px;margin:40px auto;padding:25px;border-radius:14px;">
    <h3 style="margin-top:0;">Monthly Analysis</h3>
    <div style="margin-bottom:15px;">
      <button class="btn" onclick="showSales()">Total Sales</button>
      <button class="btn" onclick="showGross()">Gross Profit</button>
      <button class="btn" onclick="closeGraph()" style="float:right;background:#c62828;">
        ✖ Close
      </button>
    </div>
    <canvas id="chart"></canvas>
  </div>
</div>

<!-- ===== FILTER ===== -->
<input id="search" placeholder="🔍 type product name..."
       style="width:100%;max-width:500px;padding:14px;border-radius:10px;
              border:2px solid #1976d2;margin:20px 0;">

<!-- ===== PRODUCT REPORT ===== -->
<details open>
  <summary style="font-size:18px;font-weight:bold;cursor:pointer;">
    📦 Product-wise Gross Profit – {{ full_month_year }}
  </summary>
  <table style="width:100%;margin-top:15px;">
    <thead style="background:#1976d2;color:white;">
      <tr>
        <th>Product</th>
        <th>Qty</th>
        <th>SP</th>
        <th>CP</th>
        <th>Gross</th>
        <th>%</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr class="row">
        <td>{{ r.product }}</td>
        <td>{{ "%.2f"|format(r.qty) }}</td>
        <td>{{ "%.2f"|format(r.selling_price) }}</td>
        <td>{{ "%.2f"|format(r.cost_price) }}</td>
        <td style="font-weight:bold;color:{{ '#2e7d32' if r.gross_profit >= 0 else '#c62828' }};">
          {{ "%.2f"|format(r.gross_profit) }}
        </td>
        <td>{{ r.percent }}%</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</details>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const labels = {{ monthly_sales|map(attribute=0)|list|tojson }};
const salesData = {{ monthly_sales|map(attribute=1)|list|tojson }};
const grossData = {{ monthly_gross|map(attribute=1)|list|tojson }};

let chart;

function openGraph(){
  document.getElementById("graphModal").style.display="block";
  showSales();
}

function closeGraph(){
  document.getElementById("graphModal").style.display="none";
}

function render(data, label, color){
  if(chart) chart.destroy();
  chart = new Chart(document.getElementById("chart"), {
    type: "line",
    data: { labels: labels, datasets: [{ label: label, data: data, borderColor: color, fill: false }] }
  });
}

function showSales(){ render(salesData, "Monthly Sales", "#1976d2"); }
function showGross(){ render(grossData, "Monthly Gross Profit", "#2e7d32"); }

// product name filter
document.getElementById("search").onkeyup = function(){
  let v = this.value.toLowerCase();
  document.querySelectorAll(".row").forEach(r => {
    r.style.display = r.innerText.toLowerCase().includes(v) ? '' : 'none';
  });
}
</script>
""" + TPL_F

    return render_template_string(
        html,
        total_sales=total_sales,
        total_expenses=total_expenses,
        total_gross_profit=total_gross_profit,
        net_profit=net_profit,
        rows=rows,
        monthly_sales=monthly_sales,
        monthly_gross=monthly_gross,
        full_month_year=full_month_year,
        project=get_setting("project_name")
    )

# 5. Expenses Sheet
# 5. Expenses Sheet - مکمل درست اور چلنے والا
@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():

    today = datetime.date.today()
    today_str = today.isoformat()
    current_year = today.year

    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()

    # ================= POST =================
    if request.method == "POST":
        action = request.form.get("action","")

        # DELETE
        if action == "delete":
            exp_id = request.form.get("exp_id")
            if exp_id:
                cur.execute("DELETE FROM expenses WHERE id=?", (exp_id,))
                con.commit()
                flash("Expense deleted successfully")
            con.close()
            return redirect(url_for("expenses"))

        # ADD
        try:
            amount = float(request.form.get("amount",0))
            desc = request.form.get("desc","").strip()
            date = request.form.get("date", today_str)

            if amount>0 and desc:
                cur.execute("""
                    INSERT INTO expenses (date, amount, description)
                    VALUES (?,?,?)
                """,(date,amount,desc))
                con.commit()
                flash(f"Added: Rs {amount:,.2f} – {desc}")
            else:
                flash("Please enter valid amount and description")
        except:
            flash("Invalid amount")

        con.close()
        return redirect(url_for("expenses"))

    # ================= GET =================
    cur.execute("SELECT id,date,amount,description FROM expenses ORDER BY date DESC")
    rows = cur.fetchall()
    con.close()

    from collections import defaultdict
    monthly = defaultdict(list)
    monthly_totals = defaultdict(float)
    yearly_total = 0.0

    for i,d,a,desc in rows:
        try:
            dt = datetime.datetime.strptime(d,"%Y-%m-%d")
            month_key = dt.strftime("%B %Y")
            monthly[month_key].append({
                "id":i,
                "date":d,
                "amount":a,
                "desc":desc
            })
            monthly_totals[month_key]+=a
            if dt.year==current_year:
                yearly_total+=a
        except:
            continue

    sorted_months = sorted(
        monthly.keys(),
        key=lambda x: datetime.datetime.strptime(x,"%B %Y"),
        reverse=True
    )

    # ================= UI =================
    html = TPL_H + """
<h2>💸 Expense Manager</h2>
<a href="{{url_for('home')}}" class="btn" style="margin-top:30px;">⬅ Back</a>
{% with messages=get_flashed_messages() %}
{% for m in messages %}
<div class="notice">{{m}}</div>
{% endfor %}
{% endwith %}

<!-- ===== ADD EXPENSE ===== -->
<form method="post" style="background:#f9f9f9;padding:20px;border-radius:12px;margin:20px 0;">
  <div style="display:grid;grid-template-columns:180px 150px 1fr 140px;gap:15px;">
    <input type="date" name="date" value="{{today_str}}" required>
    <input type="number" name="amount" step="0.01" placeholder="Amount" required>
    <input name="desc" placeholder="Description" required>
    <button class="btn" style="background:#d32f2f;">Add Expense</button>
  </div>
</form>

<!-- ===== YEAR TOTAL ===== -->
<div class="card" style="text-align:center;background:#fff3e0;border-left:6px solid #ff9800;">
  <h3>Yearly Expenses – {{current_year}}</h3>
  <p style="font-size:32px;font-weight:bold;">Rs {{ "%.2f"|format(yearly_total) }}</p>
</div>

<!-- ===== FILTER ===== -->
<input id="search" placeholder="🔍 search expense..."
       style="width:100%;max-width:500px;padding:14px;border-radius:10px;
              border:2px solid #d32f2f;margin:25px 0;">

<!-- ===== MONTHLY ===== -->
{% for month in sorted_months %}
<div class="card" style="margin-bottom:20px;">
  <button onclick="toggle('{{loop.index}}')"
          style="width:100%;background:#d32f2f;color:white;
                 padding:16px;font-size:18px;text-align:left;">
    {{month}}
    <span style="float:right;">
      Rs {{ "%.2f"|format(monthly_totals[month]) }} ▼
    </span>
  </button>

  <div id="m{{loop.index}}"
       style="display:{% if loop.first %}block{% else %}none{% endif %};padding:20px;">
    <table style="width:100%;">
      <tr>
        <th>Date</th><th>Amount</th><th>Description</th><th></th>
      </tr>
      {% for e in monthly[month] %}
      <tr class="row">
        <td>{{e.date}}</td>
        <td style="font-weight:bold;color:#d32f2f;">
          Rs {{ "%.2f"|format(e.amount) }}
        </td>
        <td>{{e.desc}}</td>
        <td>
          <form method="post" onsubmit="return confirm('Delete this expense?')">
            <input type="hidden" name="action" value="delete">
            <input type="hidden" name="exp_id" value="{{e.id}}">
            <button class="btn" style="background:#c62828;">Delete</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>
</div>
{% endfor %}



<script>
// filter
document.getElementById("search").onkeyup=function(){
 let v=this.value.toLowerCase();
 document.querySelectorAll(".row").forEach(r=>{
   r.style.display=r.innerText.toLowerCase().includes(v)?'':'none';
 });
}
// fold
function toggle(i){
 let e=document.getElementById("m"+i);
 e.style.display=e.style.display=='none'?'block':'none';
}
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

    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()

    # ---------- ENSURE TABLE ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS other_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            name TEXT,
            amount REAL,
            description TEXT
        )
    """)
    con.commit()

    # ---------- POST ----------
    if request.method == "POST":
        action = request.form.get("action","")

        # DELETE
        if action == "delete":
            exp_id = request.form.get("exp_id")
            if exp_id:
                cur.execute("DELETE FROM other_expenses WHERE id=?", (exp_id,))
                con.commit()
                flash("Entry deleted")
            con.close()
            return redirect(url_for("other_expenses"))

        # ADD ENTRY (NO REQUIRED FIELDS)
        try:
            name = request.form.get("name","").strip()
            desc = request.form.get("desc","").strip()
            date = request.form.get("date") or today_str
            amount_str = request.form.get("amount","").strip()
            amount = float(amount_str) if amount_str else 0.0

            cur.execute("""
                INSERT INTO other_expenses (date, name, amount, description)
                VALUES (?,?,?,?)
            """,(date,name,amount,desc))
            con.commit()
            flash("Entry added")
        except:
            flash("Error saving entry")

        con.close()
        return redirect(url_for("other_expenses"))

    # ---------- GET ----------
    cur.execute("""
        SELECT id,date,name,amount,description
        FROM other_expenses
        ORDER BY date DESC, id DESC
    """)
    rows = cur.fetchall()
    con.close()

    from collections import defaultdict
    monthly = defaultdict(list)
    monthly_totals = defaultdict(float)
    yearly_total = 0.0

    for i,d,n,a,desc in rows:
        try:
            dt = datetime.datetime.strptime(d,"%Y-%m-%d")
            month_key = dt.strftime("%B %Y")
        except:
            month_key = "Unknown"

        monthly[month_key].append({
            "id":i,
            "date":d or "—",
            "name":n or "—",
            "amount":a or 0,
            "description":desc or ""
        })
        monthly_totals[month_key] += a or 0
        if d and d.startswith(str(current_year)):
            yearly_total += a or 0

    sorted_months = sorted(
        monthly.keys(),
        key=lambda x: datetime.datetime.strptime(x,"%B %Y") if x!="Unknown" else datetime.datetime.min,
        reverse=True
    )

    # ---------- UI ----------
    html = TPL_H + """
<!-- BACK BUTTON (TOP) -->
<a href="{{ url_for('home') }}" class="btn" style="margin-bottom:18px;">⬅ Back</a>

<h2>📑 Other Expenses</h2>

<!-- ================= FORM ================= -->
<form method="post" id="expenseForm"
      style="background:#fff8e1;padding:22px;border-radius:12px;margin:20px 0;">

  <div style="display:grid;grid-template-columns:160px 180px 1fr 140px;gap:15px;">
    <input type="date" name="date" value="{{ today_str }}">
    <input name="name" placeholder="Name / Item">
    <input name="desc" placeholder="Description (optional)">
    <input name="amount" type="number" step="0.01" placeholder="Amount">
  </div>

  <button class="btn" style="margin-top:15px;background:#ff6d00;">
    Add Entry
  </button>
</form>

<!-- YEARLY TOTAL -->
<div class="card" style="text-align:center;background:#fff0e0;border-left:8px solid #ff6d00;margin:25px 0;">
  <h3>Yearly Total – {{ current_year }}</h3>
  <p style="font-size:32px;font-weight:bold;">
    Rs {{ "%.2f"|format(yearly_total) }}
  </p>
</div>

<!-- MONTHLY FOLDABLE -->
{% for month in sorted_months %}
<div class="card" style="margin-bottom:18px;border-radius:14px;overflow:hidden;">
  <button onclick="toggle('{{loop.index}}')"
          style="width:100%;background:#ff6d00;color:white;padding:16px;font-size:18px;text-align:left;">
    {{ month }}
    <span style="float:right;">Rs {{ "%.2f"|format(monthly_totals[month]) }} ▼</span>
  </button>

  <div id="m{{loop.index}}" style="display:{% if loop.first %}block{% else %}none{% endif %};padding:15px;">
    {% for e in monthly[month] %}
    <div style="border-bottom:1px solid #eee;padding:12px 0;">

      <!-- SINGLE LINE -->
      <div style="display:flex;flex-wrap:wrap;gap:15px;align-items:center;">
        <strong>{{ e.name }}</strong>
        <span style="color:#666;">{{ e.date }}</span>
        <span style="font-weight:bold;color:#d84315;">
          Rs {{ "%.2f"|format(e.amount) }}
        </span>

        <form method="post" style="margin-left:auto;" onsubmit="return confirm('Delete this entry?')">
          <input type="hidden" name="action" value="delete">
          <input type="hidden" name="exp_id" value="{{ e.id }}">
          <button class="btn" style="background:#c62828;padding:6px 14px;">Delete</button>
        </form>
      </div>

      <!-- DESCRIPTION BELOW -->
      {% if e.description %}
      <div style="margin-top:6px;color:#555;font-size:14px;">
        {{ e.description }}
      </div>
      {% endif %}

    </div>
    {% endfor %}
  </div>
</div>
{% endfor %}

<script>
/* ========= FOLD ========= */
function toggle(i){
 let e=document.getElementById("m"+i);
 e.style.display=e.style.display=='none'?'block':'none';
}

/* ========= DRAFT SAVE ========= */
const form=document.getElementById("expenseForm");
const fields=["date","name","desc","amount"];

window.addEventListener("load",()=>{
 fields.forEach(f=>{
  let el=form.querySelector(`[name="${f}"]`);
  let v=localStorage.getItem("draft_"+f);
  if(el && v!==null){el.value=v;}
 });
});

fields.forEach(f=>{
 let el=form.querySelector(`[name="${f}"]`);
 if(el){
  el.addEventListener("input",()=>{
   localStorage.setItem("draft_"+f,el.value);
  });
 }
});

form.addEventListener("submit",()=>{
 fields.forEach(f=>localStorage.removeItem("draft_"+f));
});
</script>
""" + TPL_F

    return render_template_string(
        html,
        today_str=today_str,
        current_year=current_year,
        sorted_months=sorted_months,
        monthly=monthly,
        monthly_totals=monthly_totals,
        yearly_total=yearly_total,
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

    # ---------- All products (for auto typing filter) ----------
    c.execute("SELECT name FROM products ORDER BY name")
    all_products = [r[0] for r in c.fetchall()]

    # ---------- Monthly data ----------
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
        monthly_data[month_name].append({
            "product": prod,
            "qty": float(qty)
        })
        grand_totals[month_name] += float(qty)

    # ---------- Date range filter ----------
    filtered_result = None
    filtered_grand = 0.0

    if request.method == "POST":
        from_date = request.form.get("from_date")
        to_date   = request.form.get("to_date")
        prod_f    = request.form.get("product_filter","").strip()

        q = """
            SELECT product, SUM(qty)
            FROM sales_log
            WHERE date BETWEEN ? AND ?
        """
        params = [from_date, to_date]

        if prod_f:
            q += " AND product = ?"
            params.append(prod_f)

        q += " GROUP BY product ORDER BY SUM(qty) DESC"

        c.execute(q, params)
        rows = c.fetchall()

        filtered_result = []
        for r in rows:
            filtered_result.append({
                "product": r[0],
                "qty": float(r[1])
            })
            filtered_grand += float(r[1])

    conn.close()

    # ======================= HTML =======================
    html = TPL_H + """
<h2>📊 Product Sales History</h2>

<!-- ================= FILTER ================= -->
<form method="post" class="card" style="margin-bottom:30px;">
  <h3>📅 Filter</h3>
  <div style="display:flex;flex-wrap:wrap;gap:15px;align-items:end;">
    <div>
      <label>From</label><br>
      <input type="date" name="from_date" required>
    </div>
    <div>
      <label>To</label><br>
      <input type="date" name="to_date" required>
    </div>
    <div>
      <label>Product</label><br>
      <input list="plist" name="product_filter" placeholder="Type product name">
      <datalist id="plist">
        {% for p in all_products %}
          <option value="{{p}}">
        {% endfor %}
      </datalist>
    </div>
    <div>
      <button class="btn">Apply</button>
    </div>
    <div>
      <button type="button" onclick="exportCSV()" class="btn"
              style="background:#2e7d32;">⬇ Export CSV</button>
    </div>
  </div>
</form>

<!-- ================= FILTER RESULT ================= -->
{% if filtered_result is not none %}
<div class="card" style="background:#e8f5e9;margin-bottom:30px;">
  <h3>Filtered Result</h3>
  <p><strong>Total Qty:</strong> {{ "%.2f"|format(filtered_grand) }}</p>
  <table style="width:100%;">
    <thead><tr><th>Product</th><th style="text-align:center;">Qty</th></tr></thead>
    <tbody>
      {% for r in filtered_result %}
      <tr>
        <td>{{ r.product }}</td>
        <td style="text-align:center;font-weight:bold;">{{ "%.2f"|format(r.qty) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

<!-- ================= SEARCH ================= -->
<input type="text" id="gsearch" placeholder="🔍 Search product..."
       style="width:100%;max-width:600px;padding:14px;
              border-radius:10px;border:2px solid #1976d2;margin-bottom:25px;">

<!-- ================= CHART ================= -->
<div class="card" style="margin-bottom:35px;">
  <h3>📈 Monthly Chart</h3>
  <canvas id="chart" height="120"></canvas>
</div>

<!-- ================= MONTHLY DATA ================= -->
{% for month, items in monthly_data.items() %}
<div class="card" style="margin-bottom:25px;">
  <button onclick="toggleMonth('{{ loop.index }}')"
          class="mbtn"
          data-month="{{ month }}"
          style="width:100%;background:#1976d2;color:white;
                 border:none;padding:16px;font-size:18px;
                 text-align:left;border-radius:10px;">
    {{ month }}
    <span style="float:right;">
      Total: {{ "%.2f"|format(grand_totals[month]) }} ⬇
    </span>
  </button>

  <div id="m{{ loop.index }}" style="display:none;padding-top:15px;">
    <table style="width:100%;">
      <thead>
        <tr><th>Product</th><th style="text-align:center;">Qty</th></tr>
      </thead>
      <tbody>
        {% for it in items %}
        <tr class="srow">
          <td>{{ it.product }}</td>
          <td style="text-align:center;font-weight:bold;">
            {{ "%.2f"|format(it.qty) }}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endfor %}

<!-- ================= BACK ================= -->
<div style="text-align:center;margin-top:40px;">
  <a href="{{ url_for('products') }}" class="btn"
     style="padding:14px 50px;">⬅ Back</a>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
// search
document.getElementById('gsearch').addEventListener('keyup',e=>{
  let v=e.target.value.toLowerCase();
  document.querySelectorAll('.srow').forEach(r=>{
    r.style.display=r.innerText.toLowerCase().includes(v)?'':'none';
  });
});

// fold
function toggleMonth(i){
  let d=document.getElementById('m'+i);
  d.style.display=d.style.display==='none'?'block':'none';
}

// auto open current month
(function(){
  let cm=new Date().toLocaleString('en-US',{month:'long',year:'numeric'});
  document.querySelectorAll('.mbtn').forEach((b,i)=>{
    if(b.dataset.month===cm){toggleMonth(i+1);}
  });
})();

// export
function exportCSV(){
  let r=[["Month","Product","Qty"]];
  document.querySelectorAll('.mbtn').forEach((b,i)=>{
    let m=b.dataset.month;
    document.querySelectorAll('#m'+(i+1)+' tbody tr').forEach(tr=>{
      let t=tr.children;
      r.push([m,t[0].innerText,t[1].innerText]);
    });
  });
  let c=r.map(x=>x.join(',')).join('\\n');
  let a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([c],{type:'text/csv'}));
  a.download='sales_history.csv'; a.click();
}

// chart
new Chart(document.getElementById('chart'),{
  type:'bar',
  data:{
    labels: {{ monthly_data.keys()|list|tojson }},
    datasets:[{
      data: {{ grand_totals.values()|list|tojson }},
      label:'Total Qty'
    }]
  },
  options:{responsive:true,plugins:{legend:{display:false}}}
});
</script>
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
if __name__ == "__main__":
    import webbrowser
    import threading
    import time

    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:3345")

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="0.0.0.0", port=3345, debug=False, use_reloader=False)

