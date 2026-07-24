import streamlit as st
import psycopg2
import pandas as pd
import sqlite3
import re
from datetime import datetime, date, timedelta
from typing import List, Tuple
import time
import os

try:
    from streamlit_option_menu import option_menu
    HAS_OPTION_MENU = True
except ImportError:
    HAS_OPTION_MENU = False

try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# -----------------------------
# CONFIG / CONSTANTS
# -----------------------------
# Set USE_LOCAL_SQLITE=true to run entirely on a local SQLite file with zero
# setup - no CockroachDB / Docker / Postgres install needed. Great for
# quickly testing the UI. Switch back to CockroachDB later by unsetting it
# (or setting COCKROACH_INSECURE=true for local Cockroach, or DATABASE_URL
# for CockroachDB Cloud).
# Set USE_LOCAL_SQLITE=false only once you're ready to connect to a real
# CockroachDB instance (Cloud or local). By default (no env var needed at
# all) the app now runs on a local SQLite file with zero setup - this
# avoids relying on an environment variable actually reaching the process,
# which is an easy thing to get wrong on Windows.
USE_SQLITE = os.getenv('USE_LOCAL_SQLITE', 'true').lower() in ('1', 'true', 'yes')
SQLITE_PATH = os.getenv('SQLITE_PATH', 'sales_local.db')

# CockroachDB connection parameters - set these via environment variables
DB_CONFIG = {
    'host': os.getenv('COCKROACH_HOST', 'localhost'),
    'port': os.getenv('COCKROACH_PORT', '26257'),
    'database': os.getenv('COCKROACH_DATABASE', 'defaultdb'),
    'user': os.getenv('COCKROACH_USER', 'root'),
    'password': os.getenv('COCKROACH_PASSWORD', ''),
    'sslmode': os.getenv('COCKROACH_SSLMODE', 'require')
}

SALESPERSONS = ["ABCD", "SHREEJI", "MUKESH", "VSTOCK", "SAHAJANAND GRAPHIC", "WHATSAPP"]
BANKS = ["HDFC", "UNITY", "BOB", "PayPal"]
DEFAULT_PLATFORMS = [
    "Shutterstock", "123RF", "Stock Adobe", "DepositPhoto", "DreamsTime", "Envato Elements",
    "FreePik", "IstockPhoto", "PngTree", "Motion Array", "Creative Fabrica", "Deezy",
    "Pikbest", "Designi", "Flaticon", "IconScout", "RawPixel", "UI8", "Vecteezy",
    "Getty Images", "VectorStock", "Alamy", "Lovepik", "Adobestock Video", "Shutterstock Video",
    "Custom Design"
]
STATUS_OPTIONS = ["Paid", "Pending"]
PREPAID_TRANSACTION_TYPES = ["Credit", "Debit"]
ADD_NEW_CUSTOMER = "➕ Add New Customer"


# -----------------------------
# SQLite compatibility shim
# -----------------------------
# Lets all the existing psycopg2-style SQL (using %s placeholders and
# `id SERIAL PRIMARY KEY`) run unchanged against a local SQLite file.
# Subclassing sqlite3.Connection/Cursor (rather than wrapping) keeps
# isinstance(conn, sqlite3.Connection) true, which pandas.read_sql_query
# relies on.
_SERIAL_RE = re.compile(r'\bSERIAL\b', re.IGNORECASE)


class _CompatCursor(sqlite3.Cursor):
    def execute(self, sql, params=()):
        sql = sql.replace('%s', '?')
        sql = _SERIAL_RE.sub('INTEGER', sql)
        return super().execute(sql, params)


class _CompatConnection(sqlite3.Connection):
    def cursor(self, *args, **kwargs):
        return super().cursor(_CompatCursor)


def _get_sqlite_conn():
    conn = sqlite3.connect(
        SQLITE_PATH, check_same_thread=False, isolation_level=None, factory=_CompatConnection
    )
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



st.set_page_config(page_title="Sales Manager", page_icon="💼", layout="wide", initial_sidebar_state="expanded")

# -----------------------------
# GLOBAL STYLE (dark, card-based UI)
# -----------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* App background with subtle gradient */
[data-testid="stAppViewContainer"] {
    background: radial-gradient(circle at 0% 0%, #1a1f2e 0%, #0E1117 45%);
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #12151d;
    border-right: 1px solid rgba(255,255,255,0.06);
}
[data-testid="stSidebar"] .block-container {
    padding-top: 1.2rem;
}

/* Page title */
h1 {
    font-weight: 800 !important;
    letter-spacing: -0.5px;
    background: linear-gradient(90deg, #A29BFE 0%, #6C5CE7 60%, #00CEC9 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    padding-bottom: 4px;
}
h2, h3 {
    font-weight: 700 !important;
    color: #EDEDED !important;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: linear-gradient(145deg, #1b1f2b, #171a24);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    padding: 16px 18px 12px 18px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(108,92,231,0.18);
}
[data-testid="stMetricLabel"] {
    font-weight: 600 !important;
    opacity: 0.75;
}
[data-testid="stMetricValue"] {
    font-weight: 800 !important;
}

/* Buttons */
.stButton > button, .stDownloadButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    transition: all 0.15s ease;
}
.stButton > button[kind="primary"], .stDownloadButton > button {
    background: linear-gradient(90deg, #6C5CE7, #8E7CFB) !important;
    box-shadow: 0 4px 14px rgba(108,92,231,0.35);
}
.stButton > button[kind="primary"]:hover {
    box-shadow: 0 6px 18px rgba(108,92,231,0.55);
    transform: translateY(-1px);
}

/* Inputs, selects */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
div[data-baseweb="select"] > div {
    border-radius: 10px !important;
    background-color: #171a24 !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
}

/* Expanders as cards */
.streamlit-expanderHeader {
    background: #171a24;
    border-radius: 10px !important;
    font-weight: 600 !important;
}
div[data-testid="stExpander"] {
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 12px !important;
    overflow: hidden;
    margin-bottom: 10px;
}

/* Dataframes / tables */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.07);
}

/* Tabs */
button[data-baseweb="tab"] {
    font-weight: 600 !important;
    border-radius: 8px 8px 0 0 !important;
}

/* Info/success/warning/error boxes */
div[data-testid="stAlert"] {
    border-radius: 12px !important;
}

/* Custom KPI card component (used on Dashboard) */
.kpi-card {
    background: linear-gradient(145deg, #1b1f2b, #171a24);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 16px;
    padding: 18px 20px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25);
    height: 100%;
}
.kpi-card .kpi-icon { font-size: 26px; opacity: 0.9; }
.kpi-card .kpi-label { font-size: 13px; font-weight: 600; opacity: 0.65; margin-top: 6px; }
.kpi-card .kpi-value { font-size: 26px; font-weight: 800; margin-top: 2px; }
.kpi-card .kpi-accent-purple { color: #A29BFE; }
.kpi-card .kpi-accent-teal { color: #00CEC9; }
.kpi-card .kpi-accent-pink { color: #FD79A8; }
.kpi-card .kpi-accent-orange { color: #FDCB6E; }

.section-divider {
    border: none;
    height: 1px;
    background: linear-gradient(90deg, rgba(108,92,231,0.5), rgba(255,255,255,0.02));
    margin: 18px 0 18px 0;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def kpi_card(col, icon: str, label: str, value: str, accent: str = "purple"):
    with col:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-icon">{icon}</div>
                <div class="kpi-label">{label}</div>
                <div class="kpi-value kpi-accent-{accent}">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# -----------------------------
# DB HELPERS
# -----------------------------
def get_conn():
    if USE_SQLITE:
        return _get_sqlite_conn()

    insecure = os.getenv('COCKROACH_INSECURE', 'false').lower() in ('1', 'true', 'yes')
    try:
        database_url = os.getenv('DATABASE_URL')

        if insecure:
            # Local single-node CockroachDB started with --insecure: no SSL, no cert needed.
            if database_url:
                conn = psycopg2.connect(database_url)
            else:
                conn = psycopg2.connect(
                    host=DB_CONFIG['host'],
                    port=DB_CONFIG['port'],
                    database=DB_CONFIG['database'],
                    user=DB_CONFIG['user'],
                    password=DB_CONFIG['password'],
                    sslmode='disable',
                )
        else:
            # Get the path to the certificate file (needed for CockroachDB Cloud / secure clusters)
            cert_path = os.path.join(os.path.dirname(__file__), 'root.crt')

            if database_url:
                # Add certificate path to connection string
                if '?' in database_url:
                    database_url += f'&sslrootcert={cert_path}'
                else:
                    database_url += f'?sslrootcert={cert_path}'
                conn = psycopg2.connect(database_url)
            else:
                conn = psycopg2.connect(
                    host=DB_CONFIG['host'],
                    port=DB_CONFIG['port'],
                    database=DB_CONFIG['database'],
                    user=DB_CONFIG['user'],
                    password=DB_CONFIG['password'],
                    sslmode='verify-full',
                    sslrootcert=cert_path
                )
        conn.autocommit = True
        return conn
    except psycopg2.Error as e:
        st.error(f"Database connection failed: {e}")
        st.stop()

def get_next_sequential_id(table_name: str, id_column: str = 'sequential_id') -> int:
    """Get the next sequential ID for a table"""
    conn = get_conn()
    c = conn.cursor()
    try:
        # Get the maximum current sequential ID
        c.execute(f"SELECT COALESCE(MAX({id_column}), 0) + 1 FROM {table_name}")
        next_id = c.fetchone()[0]
        return next_id
    except Exception as e:
        st.error(f"Error getting next sequential ID: {e}")
        return 1
    finally:
        conn.close()

@st.cache_data(show_spinner=False)
def init_db():
    conn = get_conn()
    c = conn.cursor()
    
    try:
        # Create customers table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            )
            """
        )
        
        # Create platforms table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS platforms (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            )
            """
        )
        
        # Create sales table with sequential_id
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sales (
                id SERIAL PRIMARY KEY,
                sequential_id INTEGER UNIQUE NOT NULL,
                date TEXT NOT NULL,
                salesperson TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                status TEXT NOT NULL,
                bank TEXT NOT NULL,
                remark TEXT,
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            )
            """
        )
        
        # Create sale_platforms table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sale_platforms (
                id SERIAL PRIMARY KEY,
                sale_id INTEGER NOT NULL,
                platform_id INTEGER NOT NULL,
                platform_account_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                is_archived BOOLEAN NOT NULL DEFAULT FALSE,
                FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
                FOREIGN KEY(platform_id) REFERENCES platforms(id)
            )
            """
        )

        # Create prepaid_balances table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS prepaid_balances (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER UNIQUE NOT NULL,
                balance DECIMAL(10,2) NOT NULL DEFAULT 0,
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            )
            """
        )

        # Create prepaid_transactions table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS prepaid_transactions (
                id SERIAL PRIMARY KEY,
                date TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                description TEXT,
                salesperson TEXT,
                bank TEXT,
                remark TEXT,
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            )
            """
        )

        # Create prepaid_sales table with sequential_id
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS prepaid_sales (
                id SERIAL PRIMARY KEY,
                sequential_id INTEGER UNIQUE NOT NULL,
                date TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                salesperson TEXT NOT NULL,
                total_amount DECIMAL(10,2) NOT NULL,
                quantity INTEGER NOT NULL,
                remark TEXT,
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            )
            """
        )

        # Create prepaid_sale_platforms table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS prepaid_sale_platforms (
                id SERIAL PRIMARY KEY,
                prepaid_sale_id INTEGER NOT NULL,
                platform_id INTEGER NOT NULL,
                platform_account_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                is_archived BOOLEAN NOT NULL DEFAULT FALSE,
                FOREIGN KEY(prepaid_sale_id) REFERENCES prepaid_sales(id) ON DELETE CASCADE,
                FOREIGN KEY(platform_id) REFERENCES platforms(id)
            )
            """
        )

        # Check if sequential_id column exists, if not add it
        try:
            c.execute("ALTER TABLE sales ADD COLUMN sequential_id INTEGER")
            c.execute("CREATE UNIQUE INDEX sales_sequential_id_idx ON sales(sequential_id)")
            # Update existing records with sequential IDs
            c.execute("SELECT id FROM sales ORDER BY id")
            existing_sales = c.fetchall()
            for i, (sale_id,) in enumerate(existing_sales, 1):
                c.execute("UPDATE sales SET sequential_id = %s WHERE id = %s", (i, sale_id))
        except (psycopg2.Error, sqlite3.Error):
            # Column already exists or other error, continue
            pass

        try:
            c.execute("ALTER TABLE prepaid_sales ADD COLUMN sequential_id INTEGER")
            c.execute("CREATE UNIQUE INDEX prepaid_sales_sequential_id_idx ON prepaid_sales(sequential_id)")
            # Update existing records with sequential IDs
            c.execute("SELECT id FROM prepaid_sales ORDER BY id")
            existing_prepaid_sales = c.fetchall()
            for i, (sale_id,) in enumerate(existing_prepaid_sales, 1):
                c.execute("UPDATE prepaid_sales SET sequential_id = %s WHERE id = %s", (i, sale_id))
        except (psycopg2.Error, sqlite3.Error):
            # Column already exists or other error, continue
            pass

        # Insert default platforms
        for p in DEFAULT_PLATFORMS:
            try:
                c.execute("INSERT INTO platforms(name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (p,))
            except Exception:
                pass
                
        conn.commit()
    except (psycopg2.Error, sqlite3.Error) as e:
        st.error(f"Database initialization failed: {e}")
    finally:
        conn.close()

# Utility cached getters
@st.cache_data(ttl=5)
def get_customers() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM customers ORDER BY name", conn)
        return df
    except Exception as e:
        st.error(f"Error fetching customers: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

@st.cache_data(ttl=5)
def get_platforms() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM platforms ORDER BY name", conn)
        return df
    except Exception as e:
        st.error(f"Error fetching platforms: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

@st.cache_data(ttl=5)
def get_sales() -> pd.DataFrame:
    conn = get_conn()
    try:
        # Regular sales with NULL handling for sequential_id
        regular_df = pd.read_sql_query(
            """
            SELECT s.id, 
                   COALESCE(s.sequential_id, s.id) as sequential_id, 
                   s.date, s.salesperson, c.name AS customer, s.quantity, s.amount,
                   s.status, s.bank, s.remark, 'Regular' as sale_type
            FROM sales s
            JOIN customers c ON s.customer_id = c.id
            """,
            conn,
        )
        
        # Prepaid sales with NULL handling
        prepaid_df = pd.read_sql_query(
            """
            SELECT ps.id, 
                   COALESCE(ps.sequential_id, ps.id) as sequential_id, 
                   ps.date, ps.salesperson, c.name AS customer, ps.quantity, 
                   ps.total_amount as amount, 'Paid' as status, '' as bank, ps.remark, 'Prepaid' as sale_type
            FROM prepaid_sales ps
            JOIN customers c ON ps.customer_id = c.id
            """,
            conn,
        )
        
        # Combine both
        if not prepaid_df.empty:
            combined_df = pd.concat([regular_df, prepaid_df], ignore_index=True)
        else:
            combined_df = regular_df
        
        # Ensure sequential_id is never null and is integer
        if not combined_df.empty:
            combined_df['sequential_id'] = combined_df['sequential_id'].fillna(combined_df['id'])
            combined_df['sequential_id'] = combined_df['sequential_id'].astype(int)
        
        return combined_df.sort_values(by=['date', 'sequential_id'], ascending=[False, False])
    except Exception as e:
        st.error(f"Error fetching sales: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

@st.cache_data(ttl=5)
def get_sale_platforms_df() -> pd.DataFrame:
    conn = get_conn()
    try:
        # Regular sale platforms
        regular_df = pd.read_sql_query(
            """
            SELECT sp.id AS sale_platform_id, sp.sale_id, p.name AS platform, sp.platform_account_id, sp.quantity, sp.is_archived, 'Regular' as sale_type
            FROM sale_platforms sp
            JOIN platforms p ON sp.platform_id = p.id
            ORDER BY sp.sale_id
            """,
            conn,
        )
        
        # Prepaid sale platforms
        prepaid_df = pd.read_sql_query(
            """
            SELECT psp.id AS sale_platform_id, psp.prepaid_sale_id as sale_id, p.name AS platform, 
                   psp.platform_account_id, psp.quantity, psp.is_archived, 'Prepaid' as sale_type
            FROM prepaid_sale_platforms psp
            JOIN platforms p ON psp.platform_id = p.id
            ORDER BY psp.prepaid_sale_id
            """,
            conn,
        )
        
        # Combine both
        if not prepaid_df.empty:
            combined_df = pd.concat([regular_df, prepaid_df], ignore_index=True)
        else:
            combined_df = regular_df
        
        return combined_df
    except Exception as e:
        st.error(f"Error fetching sale platforms: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

# New prepaid-related getters
@st.cache_data(ttl=5)
def get_prepaid_balances() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql_query(
            """
            SELECT pb.id, c.name AS customer, pb.balance
            FROM prepaid_balances pb
            JOIN customers c ON pb.customer_id = c.id
            ORDER BY c.name
            """,
            conn,
        )
        return df
    except Exception as e:
        st.error(f"Error fetching prepaid balances: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

@st.cache_data(ttl=5)
def get_prepaid_transactions() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql_query(
            """
            SELECT pt.id, pt.date, c.name AS customer, pt.transaction_type, pt.amount,
                   pt.description, pt.salesperson, pt.bank, pt.remark
            FROM prepaid_transactions pt
            JOIN customers c ON pt.customer_id = c.id
            ORDER BY pt.date DESC, pt.id DESC
            """,
            conn,
        )
        return df
    except Exception as e:
        st.error(f"Error fetching prepaid transactions: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

@st.cache_data(ttl=5)
def get_prepaid_sales() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql_query(
            """
            SELECT ps.id, ps.sequential_id, ps.date, c.name AS customer, ps.salesperson, ps.total_amount,
                   ps.quantity, ps.remark
            FROM prepaid_sales ps
            JOIN customers c ON ps.customer_id = c.id
            ORDER BY ps.date DESC, ps.sequential_id DESC
            """,
            conn,
        )
        return df
    except Exception as e:
        st.error(f"Error fetching prepaid sales: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

@st.cache_data(ttl=5)
def get_prepaid_sale_platforms_df() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql_query(
            """
            SELECT psp.id AS prepaid_sale_platform_id, psp.prepaid_sale_id, p.name AS platform, 
                   psp.platform_account_id, psp.quantity, psp.is_archived
            FROM prepaid_sale_platforms psp
            JOIN platforms p ON psp.platform_id = p.id
            ORDER BY psp.prepaid_sale_id
            """,
            conn,
        )
        return df
    except Exception as e:
        st.error(f"Error fetching prepaid sale platforms: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

@st.cache_data(ttl=5)
def get_all_activity() -> pd.DataFrame:
    conn = get_conn()
    try:
        # Regular sales
        regular_df = pd.read_sql_query("""
            SELECT s.sequential_id as id, s.date, s.salesperson, c.name AS customer,
                   s.quantity, s.amount, s.status, s.bank, s.remark, 'Regular Sale' as type
            FROM sales s
            JOIN customers c ON s.customer_id = c.id
        """, conn)

        # Only Prepaid Transaction Credits (fund additions)
        prepaid_txn_df = pd.read_sql_query("""
            SELECT pt.id, pt.date, pt.salesperson, c.name AS customer,
                   0 as quantity, pt.amount,
                   'Credit' as status, pt.bank, pt.remark, 'Prepaid Transaction' as type
            FROM prepaid_transactions pt
            JOIN customers c ON pt.customer_id = c.id
            WHERE pt.transaction_type = 'Credit'
        """, conn)

        combined_df = pd.concat([regular_df, prepaid_txn_df], ignore_index=True)
        return combined_df.sort_values(by=['date', 'id'], ascending=[False, False])
    except Exception as e:
        st.error(f"Error fetching activity: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def get_last_salesperson_for_customer(customer_id: int) -> str | None:
    """
    Return the last salesperson who sold to this customer
    (looks at both regular and prepaid sales).
    """
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT salesperson, date, seq
            FROM (
                SELECT salesperson, date, sequential_id AS seq
                FROM sales
                WHERE customer_id = %s

                UNION ALL

                SELECT salesperson, date, sequential_id AS seq
                FROM prepaid_sales
                WHERE customer_id = %s
            ) AS combined
            ORDER BY date DESC, seq DESC
            LIMIT 1
            """,
            (customer_id, customer_id),
        )
        res = c.fetchone()
        return res[0] if res else None
    except Exception as e:
        st.error(f"Error getting last salesperson: {e}")
        return None
    finally:
        conn.close()

def invalidate_all_caches():
    get_customers.clear()
    get_platforms.clear()
    get_sales.clear()
    get_sale_platforms_df.clear()
    get_prepaid_balances.clear()
    get_prepaid_transactions.clear()
    get_prepaid_sales.clear()
    get_prepaid_sale_platforms_df.clear()
    get_all_activity.clear()

# CRUD helpers
def ensure_customer(name: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO customers(name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name.strip(),))
        c.execute("SELECT id FROM customers WHERE name=%s", (name.strip(),))
        result = c.fetchone()
        if result:
            cid = result[0]
            conn.commit()
            invalidate_all_caches()
            return cid
        else:
            raise ValueError("Failed to create or find customer")
    except Exception as e:
        st.error(f"Error ensuring customer: {e}")
        return -1
    finally:
        conn.close()

def ensure_platform(name: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO platforms(name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name.strip(),))
        c.execute("SELECT id FROM platforms WHERE name=%s", (name.strip(),))
        result = c.fetchone()
        if result:
            pid = result[0]
            conn.commit()
            invalidate_all_caches()
            return pid
        else:
            raise ValueError("Failed to create or find platform")
    except Exception as e:
        st.error(f"Error ensuring platform: {e}")
        return -1
    finally:
        conn.close()

def insert_sale(date_str: str, salesperson: str, customer_id: int, total_quantity: int, amount: float,
                status: str, bank: str, remark: str, platform_map: List[Tuple[int, str, int]]) -> int:
    conn = get_conn()
    c = conn.cursor()
    try:
        # Get next sequential ID
        next_seq_id = get_next_sequential_id('sales', 'sequential_id')
        
        c.execute(
            "INSERT INTO sales(sequential_id, date, salesperson, customer_id, quantity, amount, status, bank, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (next_seq_id, date_str, salesperson, customer_id, total_quantity, amount, status, bank, remark),
        )
        sale_id = c.fetchone()[0]
        
        for platform_id, platform_account_id, quantity in platform_map:
            c.execute(
                "INSERT INTO sale_platforms(sale_id, platform_id, platform_account_id, quantity) VALUES (%s,%s,%s,%s)",
                (sale_id, platform_id, platform_account_id.strip(), quantity),
            )
        
        conn.commit()
        invalidate_all_caches()
        return next_seq_id  # Return sequential ID instead of database ID
    except Exception as e:
        conn.rollback()
        st.error(f"Error inserting sale: {e}")
        return -1
    finally:
        conn.close()

def update_sale(sequential_id: int, date_str: str, salesperson: str, customer_id: int,
                 total_quantity: int, amount: float, status: str, bank: str, remark: str,
                 platform_map: List[Tuple[int, str, int]]):
    conn = get_conn()
    c = conn.cursor()
    try:
        # Get database ID from sequential ID
        c.execute("SELECT id FROM sales WHERE sequential_id=%s", (sequential_id,))
        result = c.fetchone()
        if not result:
            raise ValueError(f"Sale with sequential ID {sequential_id} not found")
        sale_id = result[0]
        
        c.execute(
            "UPDATE sales SET date=%s, salesperson=%s, customer_id=%s, quantity=%s, amount=%s, status=%s, bank=%s, remark=%s WHERE id=%s",
            (date_str, salesperson, customer_id, total_quantity, amount, status, bank, remark, sale_id),
        )
        c.execute("DELETE FROM sale_platforms WHERE sale_id=%s", (sale_id,))
        
        for platform_id, platform_account_id, quantity in platform_map:
            c.execute(
                "INSERT INTO sale_platforms(sale_id, platform_id, platform_account_id, quantity) VALUES (%s,%s,%s,%s)",
                (sale_id, platform_id, platform_account_id.strip(), quantity),
            )
        
        conn.commit()
        invalidate_all_caches()
    except Exception as e:
        conn.rollback()
        st.error(f"Error updating sale: {e}")
    finally:
        conn.close()

def delete_sale(sequential_id: int):
    conn = get_conn()
    c = conn.cursor()
    try:
        # Get database ID from sequential ID
        c.execute("SELECT id FROM sales WHERE sequential_id=%s", (sequential_id,))
        result = c.fetchone()
        if not result:
            raise ValueError(f"Sale with sequential ID {sequential_id} not found")
        sale_id = result[0]
        
        c.execute("DELETE FROM sale_platforms WHERE sale_id=%s", (sale_id,))
        c.execute("DELETE FROM sales WHERE id=%s", (sale_id,))
        conn.commit()
        invalidate_all_caches()
    except Exception as e:
        conn.rollback()
        st.error(f"Error deleting sale: {e}")
    finally:
        conn.close()

def mark_sale_paid(sequential_id: int):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE sales SET status='Paid' WHERE sequential_id=%s", (sequential_id,))
        conn.commit()
        invalidate_all_caches()
    except Exception as e:
        conn.rollback()
        st.error(f"Error marking sale as paid: {e}")
    finally:
        conn.close()

def archive_platform_id(sale_platform_id: int, is_archived: bool):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE sale_platforms SET is_archived=%s WHERE id=%s", (is_archived, sale_platform_id))
        conn.commit()
        invalidate_all_caches()
    except Exception as e:
        conn.rollback()
        st.error(f"Error archiving platform ID: {e}")
    finally:
        conn.close()

# New prepaid-related functions
def get_customer_balance(customer_id: int) -> float:
    conn = get_conn()
    c = conn.cursor()
    try:
        # Ensure balance record exists
        c.execute("INSERT INTO prepaid_balances(customer_id, balance) VALUES (%s, 0) ON CONFLICT (customer_id) DO NOTHING", (customer_id,))
        
        # Get current balance
        c.execute("SELECT balance FROM prepaid_balances WHERE customer_id=%s", (customer_id,))
        result = c.fetchone()
        return float(result[0]) if result else 0.0
    except Exception as e:
        st.error(f"Error getting customer balance: {e}")
        return 0.0
    finally:
        conn.close()

def ensure_prepaid_balance(customer_id: int):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO prepaid_balances(customer_id, balance) VALUES (%s, 0) ON CONFLICT (customer_id) DO NOTHING", (customer_id,))
        conn.commit()
    except Exception as e:
        st.error(f"Error ensuring prepaid balance: {e}")
    finally:
        conn.close()

def add_prepaid_funds(customer_id: int, amount: float, date_str: str, description: str, 
                      salesperson: str = None, bank: str = None, remark: str = None):
    conn = get_conn()
    c = conn.cursor()
    try:
        ensure_prepaid_balance(customer_id)
        
        # Add transaction record
        c.execute(
            "INSERT INTO prepaid_transactions(date, customer_id, transaction_type, amount, description, salesperson, bank, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (date_str, customer_id, "Credit", amount, description, salesperson, bank, remark)
        )
        
        # Update balance
        c.execute("UPDATE prepaid_balances SET balance = balance + %s WHERE customer_id = %s", (amount, customer_id))
        conn.commit()
        invalidate_all_caches()
    except Exception as e:
        conn.rollback()
        st.error(f"Error adding prepaid funds: {e}")
    finally:
        conn.close()

def deduct_prepaid_funds(customer_id: int, amount: float, date_str: str, salesperson: str, 
                        total_quantity: int, remark: str, platform_map: List[Tuple[int, str, int]]) -> int:
    conn = get_conn()
    c = conn.cursor()
    try:
        ensure_prepaid_balance(customer_id)
        
        # Get next sequential ID for prepaid sales
        next_seq_id = get_next_sequential_id('prepaid_sales', 'sequential_id')
        
        # Create prepaid sale record
        c.execute(
            "INSERT INTO prepaid_sales(sequential_id, date, customer_id, salesperson, total_amount, quantity, remark) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (next_seq_id, date_str, customer_id, salesperson, amount, total_quantity, remark)
        )
        prepaid_sale_id = c.fetchone()[0]
        
        # Add platform details
        for platform_id, platform_account_id, quantity in platform_map:
            c.execute(
                "INSERT INTO prepaid_sale_platforms(prepaid_sale_id, platform_id, platform_account_id, quantity) VALUES (%s,%s,%s,%s)",
                (prepaid_sale_id, platform_id, platform_account_id.strip(), quantity)
            )
        
        # Add transaction record
        c.execute(
            "INSERT INTO prepaid_transactions(date, customer_id, transaction_type, amount, description, salesperson, remark) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (date_str, customer_id, "Debit", amount, f"Purchase - Sale #P{next_seq_id:02d}", salesperson, remark)
        )
        
        # Update balance (allow negative balance)
        c.execute("UPDATE prepaid_balances SET balance = balance - %s WHERE customer_id = %s", (amount, customer_id))
        conn.commit()
        invalidate_all_caches()
        return next_seq_id  # Return sequential ID instead of database ID
    except Exception as e:
        conn.rollback()
        st.error(f"Error deducting prepaid funds: {e}")
        return -1
    finally:
        conn.close()

def archive_prepaid_platform_id(prepaid_sale_platform_id: int, is_archived: bool):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE prepaid_sale_platforms SET is_archived=%s WHERE id=%s", (is_archived, prepaid_sale_platform_id))
        conn.commit()
        invalidate_all_caches()
    except Exception as e:
        conn.rollback()
        st.error(f"Error archiving prepaid platform ID: {e}")
    finally:
        conn.close()

def update_prepaid_sale(sequential_id: int, date_str: str, salesperson: str, customer_id: int,
                       total_quantity: int, amount: float, remark: str,
                       platform_map: List[Tuple[int, str, int]]):
    conn = get_conn()
    c = conn.cursor()
    try:
        # Get database ID from sequential ID
        c.execute("SELECT id, customer_id, total_amount FROM prepaid_sales WHERE sequential_id=%s", (sequential_id,))
        result = c.fetchone()
        if not result:
            raise ValueError(f"Prepaid sale with sequential ID {sequential_id} not found")
        prepaid_sale_id, old_customer_id, old_amount = result
        
        # Ensure both customers have prepaid balance records
        ensure_prepaid_balance(old_customer_id)
        ensure_prepaid_balance(customer_id)
        
        # Calculate balance adjustment if customer or amount changed
        if old_customer_id != customer_id or float(old_amount) != float(amount):
            # Reverse old transaction (add back to old customer)
            c.execute("UPDATE prepaid_balances SET balance = balance + %s WHERE customer_id = %s", (float(old_amount), old_customer_id))
            
            # Apply new transaction (deduct from new customer)
            c.execute("UPDATE prepaid_balances SET balance = balance - %s WHERE customer_id = %s", (float(amount), customer_id))
            
            # Update transaction record
            c.execute(
                "UPDATE prepaid_transactions SET customer_id=%s, amount=%s, date=%s, salesperson=%s, remark=%s WHERE description = %s",
                (customer_id, amount, date_str, salesperson, remark, f"Purchase - Sale #P{sequential_id:02d}")
            )
        
        # Update prepaid sale record
        c.execute(
            "UPDATE prepaid_sales SET date=%s, salesperson=%s, customer_id=%s, quantity=%s, total_amount=%s, remark=%s WHERE id=%s",
            (date_str, salesperson, customer_id, total_quantity, amount, remark, prepaid_sale_id),
        )
        
        # Update platform details
        c.execute("DELETE FROM prepaid_sale_platforms WHERE prepaid_sale_id=%s", (prepaid_sale_id,))
        for platform_id, platform_account_id, quantity in platform_map:
            c.execute(
                "INSERT INTO prepaid_sale_platforms(prepaid_sale_id, platform_id, platform_account_id, quantity) VALUES (%s,%s,%s,%s)",
                (prepaid_sale_id, platform_id, platform_account_id.strip(), quantity),
            )
        
        conn.commit()
        # Clear all caches to ensure fresh data
        invalidate_all_caches()
        # Also clear Streamlit's cache specifically for prepaid data
        get_prepaid_balances.clear()
        get_prepaid_transactions.clear()
        get_prepaid_sales.clear()
        
    except Exception as e:
        conn.rollback()
        st.error(f"Error updating prepaid sale: {e}")
        raise e
    finally:
        conn.close()

def delete_prepaid_sale(sequential_id: int):
    conn = get_conn()
    c = conn.cursor()
    try:
        # Get database ID and details from sequential ID
        c.execute("SELECT id, customer_id, total_amount FROM prepaid_sales WHERE sequential_id=%s", (sequential_id,))
        result = c.fetchone()
        if not result:
            raise ValueError(f"Prepaid sale with sequential ID {sequential_id} not found")
        prepaid_sale_id, customer_id, amount = result
        
        # Ensure customer has prepaid balance record
        ensure_prepaid_balance(customer_id)
        
        # Reverse the balance deduction (add back to customer)
        c.execute("UPDATE prepaid_balances SET balance = balance + %s WHERE customer_id = %s", (float(amount), customer_id))
        
        # Delete related records
        c.execute("DELETE FROM prepaid_sale_platforms WHERE prepaid_sale_id=%s", (prepaid_sale_id,))
        c.execute("DELETE FROM prepaid_transactions WHERE description = %s", (f"Purchase - Sale #P{sequential_id:02d}",))
        c.execute("DELETE FROM prepaid_sales WHERE id=%s", (prepaid_sale_id,))
        
        conn.commit()
        # Clear all caches to ensure fresh data
        invalidate_all_caches()
        # Also clear Streamlit's cache specifically for prepaid data
        get_prepaid_balances.clear()
        get_prepaid_transactions.clear()
        get_prepaid_sales.clear()
        
    except Exception as e:
        conn.rollback()
        st.error(f"Error deleting prepaid sale: {e}")
        raise e
    finally:
        conn.close()
        
# -----------------------------
# UI SECTIONS
# -----------------------------
init_db()

# -----------------------------
# SESSION STATE INITIALIZATION
# -----------------------------
if 'platform_id_data_df' not in st.session_state:
    try:
        all_platforms_df = get_sale_platforms_df()
        all_sales_df = get_sales()
        
        if not all_platforms_df.empty and not all_sales_df.empty:
            full_df = all_platforms_df.merge(all_sales_df, left_on="sale_id", right_on="id", how="left")
            full_df = full_df.sort_values(by="date", ascending=False).reset_index(drop=True)
            full_df.rename(columns={'quantity_x': 'Quantity', 'id_x': 'sale_platform_id'}, inplace=True)
            full_df = full_df[['sale_platform_id', 'sale_id', 'date', 'customer', 'platform', 'platform_account_id', 'Quantity', 'is_archived']]
            st.session_state.platform_id_data_df = full_df.set_index('sale_platform_id')
        else:
            # Initialize with empty DataFrame if no data
            st.session_state.platform_id_data_df = pd.DataFrame()
    except Exception:
        # Initialize with empty DataFrame if there's an error
        st.session_state.platform_id_data_df = pd.DataFrame()
    
    st.session_state.data_has_changed = False
    st.session_state.edited_rows_to_process = {}

MENU_ITEMS = [
    "Dashboard",
    "Add Sales",
    "View Sales",
    "Edit Sales",
    "Delete Sales",
    "Pending Payment",
    "Customer History",
    "Report",
    "Platform ID List",
    "Prepaid Customer",
]
MENU_ICONS = [
    "speedometer2", "plus-circle", "table", "pencil-square", "trash3",
    "hourglass-split", "person-lines-fill", "bar-chart-line", "key", "wallet2",
]

with st.sidebar:
    st.markdown(
        "<div style='padding:6px 4px 14px 4px;'>"
        "<span style='font-size:26px;font-weight:800;'>💼 Sales</span>"
        "<span style='font-size:26px;font-weight:800;color:#A29BFE;'> Manager</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    if HAS_OPTION_MENU:
        menu = option_menu(
            menu_title=None,
            options=MENU_ITEMS,
            icons=MENU_ICONS,
            default_index=0,
            styles={
                "container": {"padding": "0", "background-color": "transparent"},
                "icon": {"color": "#A29BFE", "font-size": "16px"},
                "nav-link": {
                    "font-size": "14px",
                    "font-weight": "600",
                    "text-align": "left",
                    "margin": "3px 0",
                    "border-radius": "10px",
                    "padding": "10px 12px",
                    "color": "#E6E6E6",
                    "--hover-color": "#1b1f2b",
                },
                "nav-link-selected": {
                    "background": "linear-gradient(90deg, #6C5CE7, #8E7CFB)",
                    "color": "white",
                },
            },
        )
    else:
        menu = st.radio("Menu", MENU_ITEMS, label_visibility="collapsed")

    st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)
    if USE_SQLITE:
        st.markdown(
            f"<div style='font-size:12px;padding:8px 10px;border-radius:8px;"
            f"background:rgba(0,206,201,0.12);color:#00CEC9;border:1px solid rgba(0,206,201,0.3);'>"
            f"🟢 DB: SQLite (local file)<br><code>{SQLITE_PATH}</code></div>",
            unsafe_allow_html=True,
        )
    else:
        _insecure = os.getenv('COCKROACH_INSECURE', 'false').lower() in ('1', 'true', 'yes')
        _target = os.getenv('DATABASE_URL', f"{DB_CONFIG['host']}:{DB_CONFIG['port']}")
        st.markdown(
            f"<div style='font-size:12px;padding:8px 10px;border-radius:8px;"
            f"background:rgba(253,203,110,0.12);color:#FDCB6E;border:1px solid rgba(253,203,110,0.3);'>"
            f"🟠 DB: CockroachDB ({'insecure' if _insecure else 'secure'})<br><code>{_target}</code></div>",
            unsafe_allow_html=True,
        )

st.title("📋 Sales Record System")

# --- Utility UI pieces ---
def customer_selector(key_suffix: str = "", default_customer: str = None) -> Tuple[int, str]:
    customers_df = get_customers()
    customer_names = customers_df["name"].tolist()
    
    options = customer_names + [ADD_NEW_CUSTOMER]
    default_index = 0
    if default_customer and default_customer in customer_names:
        default_index = customer_names.index(default_customer)
    elif default_customer is None:
        default_index = 0
    else:
        options = [default_customer] + customer_names + [ADD_NEW_CUSTOMER]
        default_index = 0
        
    selection = st.selectbox(
        "Customer Name / Contact",
        options=options,
        index=default_index,
        key=f"cust_sel_{key_suffix}",
    )
    if selection == ADD_NEW_CUSTOMER:
        new_name = st.text_input("Enter New Customer / Contact", key=f"new_cust_{key_suffix}")
        return (-1, new_name)
    else:
        cid = int(customers_df.loc[customers_df["name"] == selection, "id"].values[0])
        return (cid, selection)

def platform_inputs(key_suffix: str = "", default_data: pd.DataFrame = None) -> List[Tuple[int, str, int]]:
    """Return list of tuples: (platform_id, platform_account_id, quantity)"""
    platforms_df = get_platforms()
    platform_names = platforms_df["name"].tolist()
    
    final_inputs = []

    st.markdown("---")
    st.subheader("Platform Details")

    if default_data is not None:
        for i, row in default_data.iterrows():
            platform_name = row['platform']
            quantity = row['quantity']
            acc_id = row['platform_account_id']
            
            with st.expander(f"Platform: **{platform_name}**", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    selected_platform = st.selectbox(
                        "Platform Name",
                        options=platform_names,
                        index=platform_names.index(platform_name),
                        key=f"plat_name_{i}_{key_suffix}"
                    )
                with col2:
                    edited_quantity = st.number_input(
                        "Quantity",
                        min_value=1,
                        step=1,
                        value=int(quantity),
                        key=f"plat_qty_{i}_{key_suffix}"
                    )
                edited_acc_id = st.text_input(
                    "Platform ID",
                    value=acc_id,
                    key=f"plat_id_{i}_{key_suffix}"
                )
            
            pid = int(platforms_df.loc[platforms_df["name"] == selected_platform, "id"].values[0])
            final_inputs.append((pid, edited_acc_id, edited_quantity))
    else:
        selected_platforms = st.multiselect(
            "Select Platform(s)",
            options=platform_names,
            key=f"plat_ms_{key_suffix}"
        )
        
        for platform_name in selected_platforms:
            quantity = st.number_input(f"Quantity for **{platform_name}**", min_value=1, step=1, key=f"plat_qty_{platform_name}_{key_suffix}")
            st.markdown(f"Enter **{quantity}** Platform ID(s) for **{platform_name}**:")
            for i in range(int(quantity)):
                account_id = st.text_input(f"Platform ID {i+1}", key=f"plat_{platform_name}_{i}_{key_suffix}")
                pid = int(platforms_df.loc[platforms_df["name"] == platform_name, "id"].values[0])
                final_inputs.append((pid, account_id, 1))
    
    return final_inputs


# --- Add Sales ---
if menu == "Dashboard":
    sales_df = get_sales()
    customers_df = get_customers()
    balances_df = get_prepaid_balances()
    platforms_df = get_sale_platforms_df()

    total_revenue = float(sales_df["amount"].sum()) if not sales_df.empty else 0.0
    pending_amount = float(sales_df.loc[sales_df["status"] == "Pending", "amount"].sum()) if not sales_df.empty else 0.0
    total_sales_count = len(sales_df)
    total_customers = len(customers_df)
    total_prepaid_balance = float(balances_df["balance"].sum()) if not balances_df.empty else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    kpi_card(c1, "💰", "Total Revenue", f"₹{total_revenue:,.0f}", "purple")
    kpi_card(c2, "⏳", "Pending Amount", f"₹{pending_amount:,.0f}", "orange")
    kpi_card(c3, "🧾", "Total Sales", f"{total_sales_count}", "teal")
    kpi_card(c4, "👥", "Customers", f"{total_customers}", "pink")
    kpi_card(c5, "👛", "Prepaid Balance", f"₹{total_prepaid_balance:,.0f}", "teal")

    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1.4, 1])

    with col_left:
        st.subheader("📈 Revenue Trend")
        if not sales_df.empty:
            trend_df = sales_df.copy()
            trend_df["date"] = pd.to_datetime(trend_df["date"])
            daily = trend_df.groupby(trend_df["date"].dt.date)["amount"].sum().reset_index()
            daily.columns = ["Date", "Amount"]
            if HAS_PLOTLY:
                fig = px.area(daily, x="Date", y="Amount", template="plotly_dark")
                fig.update_traces(line_color="#6C5CE7", fillcolor="rgba(108,92,231,0.25)")
                fig.update_layout(
                    margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    height=320,
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.line_chart(daily.set_index("Date"))
        else:
            st.info("No sales data yet - add a sale to see the trend.")

    with col_right:
        st.subheader("🏆 Top Platforms")
        if not platforms_df.empty:
            top_platforms = platforms_df.groupby("platform")["quantity"].sum().sort_values(ascending=False).head(8).reset_index()
            top_platforms.columns = ["Platform", "Quantity"]
            if HAS_PLOTLY:
                fig2 = px.bar(top_platforms, x="Quantity", y="Platform", orientation="h", template="plotly_dark",
                              color="Quantity", color_continuous_scale=["#00CEC9", "#6C5CE7"])
                fig2.update_layout(
                    margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    height=320,
                    coloraxis_showscale=False,
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.bar_chart(top_platforms.set_index("Platform"))
        else:
            st.info("No platform data yet.")

    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("👤 Top Customers")
        if not sales_df.empty:
            top_cust = sales_df.groupby("customer")["amount"].sum().sort_values(ascending=False).head(5).reset_index()
            top_cust.columns = ["Customer", "Amount"]
            st.dataframe(top_cust, use_container_width=True, hide_index=True)
        else:
            st.info("No customer sales yet.")
    with col_b:
        st.subheader("🕘 Recent Sales")
        if not sales_df.empty:
            recent = sales_df.head(5)[["date", "customer", "salesperson", "amount", "status"]]
            recent.columns = ["Date", "Customer", "Salesperson", "Amount", "Status"]
            st.dataframe(recent, use_container_width=True, hide_index=True)
        else:
            st.info("No recent sales yet.")

elif menu == "Add Sales":
    st.subheader("➕ Add Sales")

    if 'add_sales_key' not in st.session_state:
        st.session_state.add_sales_key = 0
    
    container_key = f'add_sales_container_{st.session_state.add_sales_key}'
    with st.container(key=container_key):
        # 1) Date first
        dt = st.date_input(
            "Date",
            value=date.today(),
            max_value=date.today(),
            key=f'add_date_{st.session_state.add_sales_key}'
        )

        # 2) Customer selection
        cid, cust_name = customer_selector(f"add_{st.session_state.add_sales_key}")

        # 3) Decide default salesperson based on last sale
        if cid != -1:  # existing customer selected
            last_sp = get_last_salesperson_for_customer(cid)
        else:
            last_sp = None

        if last_sp and last_sp in SALESPERSONS:
            default_sp_index = SALESPERSONS.index(last_sp)
        else:
            default_sp_index = 0  # fallback

        # Use customer ID in key so it resets when you change customer
        salesperson = st.selectbox(
            "Salesperson",
            SALESPERSONS,
            index=default_sp_index,
            key=f'add_salesperson_{st.session_state.add_sales_key}_{cid}'
        )

        # Platforms after salesperson
        plats = platform_inputs(f"add_{st.session_state.add_sales_key}")


        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1:
            amount = st.number_input("Amount", min_value=0.0, step=1.0, format="%0.2f", key=f'add_amount_{st.session_state.add_sales_key}')
        with c2:
            bank = st.selectbox("Bank", BANKS, key=f'add_bank_{st.session_state.add_sales_key}')
        with c3:
            status = st.selectbox("Status", STATUS_OPTIONS, key=f'add_status_{st.session_state.add_sales_key}')

        remark = st.text_area("Remark (optional)", key=f'add_remark_{st.session_state.add_sales_key}')

        if st.button("Save Sale", type="primary"):
            errors = []
            if not dt: errors.append("Date is required")
            if not salesperson: errors.append("Salesperson is required")
            if cid == -1 and not cust_name: errors.append("New customer name is required")
            
            final_cid = cid
            if cid == -1 and cust_name:
                final_cid = ensure_customer(cust_name)
            
            if final_cid == -1:
                errors.append("Customer selection is required")
            if not plats:
                errors.append("At least one platform is required")
            else:
                for (_p_id, acc, _qty) in plats:
                    if not acc: errors.append("Platform ID required for all selected platforms")
            
            total_quantity = sum(p[2] for p in plats)
            if total_quantity < 1: errors.append("Total quantity must be at least 1")

            if amount is None or amount <= 0: errors.append("Amount must be positive")
            if not status: errors.append("Status is required")
            if not bank: errors.append("Bank is required")

            if errors:
                st.error("\n".join(["❌ " + e for e in errors]))
            else:
                sequential_id = insert_sale(
                    dt.strftime("%Y-%m-%d"), salesperson, final_cid, int(total_quantity),
                    float(amount), status, bank, remark, plats
                )
                if sequential_id > 0:
                    st.success(f"✅ Sale saved with ID #{sequential_id:02d}")
                    time.sleep(2)
                    st.session_state.add_sales_key += 1
                    st.rerun()

# --- View Sales ---
elif menu == "View Sales":
    st.subheader("📄 All Sales")
    sales_df = get_sales()
    if not sales_df.empty:
        sp_df = get_sale_platforms_df()
        if not sp_df.empty:
            # FIXED: Properly aggregating platforms by sale_id and sale_type
            agg = sp_df.groupby(['sale_id', 'sale_type'])['platform'].apply(
                lambda x: ", ".join(sorted(list(set(x))))
            ).reset_index()
            
            # Merge based on id and sale_type
            sales_df = sales_df.merge(
                agg, 
                left_on=['id', 'sale_type'], 
                right_on=['sale_id', 'sale_type'], 
                how='left'
            ).fillna({"platform": "-"})
            
            # Clean up extra columns
            if 'sale_id' in sales_df.columns:
                sales_df = sales_df.drop('sale_id', axis=1)
        else:
            sales_df["platform"] = "-"

        # FIXED: Safe formatting of sale IDs with proper null/None handling
        def format_sale_id_safe(row):
            try:
                seq_id = row['sequential_id']
                # Handle None, NaN, or invalid values
                if pd.isna(seq_id) or seq_id is None:
                    # Use the database ID as fallback
                    seq_id = row['id'] if 'id' in row and not pd.isna(row['id']) else 0
                
                seq_id = int(float(seq_id))  # Handle both int and float conversion
                
                if row['sale_type'] == 'Prepaid':
                    return f"#P{seq_id:02d}"
                else:
                    return f"#{seq_id:02d}"
            except (ValueError, TypeError, KeyError):
                # Fallback for any conversion errors
                fallback_id = row.get('id', 0)
                return f"#{int(fallback_id) if fallback_id else 0:02d}"
        
        sales_df['formatted_id'] = sales_df.apply(format_sale_id_safe, axis=1)

        c1, c2, c3 = st.columns(3)
        with c1:
            f_status = st.selectbox("Filter Status", ["All"] + STATUS_OPTIONS)
        with c2:
            f_salesperson = st.selectbox("Filter Salesperson", ["All"] + SALESPERSONS)
        with c3:
            f_date = st.date_input("Filter Date (optional)", value=None)

        df = sales_df.copy()
        if f_status != "All":
            df = df[df["status"] == f_status]
        if f_salesperson != "All":
            df = df[df["salesperson"] == f_salesperson]
        if isinstance(f_date, date):
            df = df[df["date"] == f_date.strftime("%Y-%m-%d")]
            
        # Display the dataframe with proper column ordering
        display_columns = ['formatted_id', 'date', 'salesperson', 'customer', 'quantity', 'amount', 'status', 'bank', 'remark', 'platform', 'sale_type']
        df_display = df[display_columns].copy()
        df_display.columns = ['ID', 'Date', 'Salesperson', 'Customer', 'Quantity', 'Amount', 'Status', 'Bank', 'Remark', 'Platforms', 'Type']
        st.dataframe(df_display, use_container_width=True)
    else:
        st.info("No sales to display.")

# --- Edit Sales ---
elif menu == "Edit Sales":
    st.subheader("✏️ Edit Sales")
    sales_df = get_sales()
    if sales_df.empty:
        st.info("No sales to edit.")
    else:
        # Show both regular and prepaid sales for editing
        formatted_options = []
        for idx, row in sales_df.iterrows():
            try:
                seq_id = row['sequential_id']
                if pd.isna(seq_id) or seq_id is None:
                    seq_id = row['id'] if 'id' in row and not pd.isna(row['id']) else idx + 1
                
                seq_id = int(float(seq_id))
                if row['sale_type'] == 'Prepaid':
                    formatted_id = f"#P{seq_id:02d}"
                else:
                    formatted_id = f"#{seq_id:02d}"
            except (ValueError, TypeError):
                formatted_id = f"#{int(row.get('id', idx + 1)):02d}"
            
            formatted_options.append(f"{formatted_id} - {row['customer']} - {row['date']} - {row['sale_type']}")
        
        sel_option = st.selectbox("Select Sale", formatted_options)
        
        try:
            # Extract details from selection
            parts = sel_option.split(" - ")
            formatted_id = parts[0]
            sale_type = parts[3]
            
            # Extract sequential ID
            if formatted_id.startswith("#P"):
                selected_sequential_id = int(formatted_id.replace("#P", ""))
                is_prepaid = True
            else:
                selected_sequential_id = int(formatted_id.replace("#", ""))
                is_prepaid = False
            
            # Find the matching row
            matching_rows = sales_df[
                (sales_df["sequential_id"] == selected_sequential_id) & 
                (sales_df["sale_type"] == sale_type)
            ]
            if matching_rows.empty:
                selected_index = formatted_options.index(sel_option)
                row = sales_df.iloc[selected_index]
            else:
                row = matching_rows.iloc[0]
                
        except (ValueError, IndexError):
            st.error("Error selecting sale. Please try again.")
            st.stop()
        
        # Get platform data based on sale type
        if row["sale_type"] == "Prepaid":
            sp_df = get_prepaid_sale_platforms_df()
            my_plats = sp_df[sp_df["prepaid_sale_id"] == row['id']]
            # Rename columns to match expected format
            my_plats = my_plats.rename(columns={'prepaid_sale_id': 'sale_id'})
        else:
            sp_df = get_sale_platforms_df()
            my_plats = sp_df[(sp_df["sale_id"] == row['id']) & (sp_df["sale_type"] == "Regular")]

        col1, col2 = st.columns(2)
        with col1:
            dt = st.date_input("Date", value=datetime.strptime(row["date"], "%Y-%m-%d").date(), max_value=date.today())
        with col2:
            salesperson = st.selectbox("Salesperson", SALESPERSONS, index=SALESPERSONS.index(row["salesperson"]))

        # Use a unique key suffix per sale so Streamlit doesn't reuse the previous customer
        if pd.isna(row["sequential_id"]):
            sale_key_id = int(row["id"])
        else:
            sale_key_id = int(row["sequential_id"])

        cust_key_suffix = f"edit_{row['sale_type']}_{sale_key_id}"

        cid, cust_name = customer_selector(cust_key_suffix, default_customer=row['customer'])

        if cid == -1 and cust_name:
            cid = ensure_customer(cust_name)
        elif cid == -1:
            customers_df = get_customers()
            cid = int(customers_df.loc[customers_df["name"] == row['customer'], "id"].values[0])

        plats = platform_inputs("edit", default_data=my_plats)
        
        st.markdown("---")
        
        if row["sale_type"] == "Prepaid":
            # For prepaid sales, only show amount (no bank/status)
            amount = st.number_input("Amount", min_value=0.0, step=1.0, format="%0.2f", value=float(row["amount"]))
            remark = st.text_area("Remark (optional)", value=row["remark"] or "")
            
            if st.button("Update Prepaid Sale", type="primary"):
                errs = []
                if not dt: errs.append("Date required")
                if not salesperson: errs.append("Salesperson required")
                if not cid or cid == -1: errs.append("Customer required")
                if not plats: errs.append("At least one platform required")
                
                total_quantity = sum(p[2] for p in plats)
                if total_quantity < 1: errs.append("Total quantity must be at least 1")

                for (_pid, acc, qty) in plats:
                    if not acc: errs.append("Platform ID for all selected platforms is required")
                    if qty is None or qty < 0: errs.append("Quantity must be 0 or more")
                
                if amount is None or amount <= 0: errs.append("Amount must be a positive value")

                if errs:
                    st.error("\n".join(["❌ " + e for e in errs]))
                else:
                    actual_sequential_id = row['sequential_id'] if not pd.isna(row['sequential_id']) else row['id']
                    update_prepaid_sale(int(actual_sequential_id), dt.strftime("%Y-%m-%d"), salesperson, cid, int(total_quantity), float(amount), remark, plats)
                    st.success("✅ Prepaid sale updated.")
                    time.sleep(1)
                    st.rerun()
        else:
            # For regular sales, show full form
            c1, c2, c3 = st.columns(3)
            with c1:
                amount = st.number_input("Amount", min_value=0.0, step=1.0, format="%0.2f", value=float(row["amount"]))
            with c2:
                bank = st.selectbox("Bank", BANKS, index=BANKS.index(row["bank"]))
            with c3:
                status = st.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(row["status"]))

            remark = st.text_area("Remark (optional)", value=row["remark"] or "")
            
            if st.button("Update Sale", type="primary"):
                errs = []
                if not dt: errs.append("Date required")
                if not salesperson: errs.append("Salesperson required")
                if not cid or cid == -1: errs.append("Customer required")
                if not plats: errs.append("At least one platform required")
                
                total_quantity = sum(p[2] for p in plats)
                if total_quantity < 1: errs.append("Total quantity must be at least 1")

                for (_pid, acc, qty) in plats:
                    if not acc: errs.append("Platform ID for all selected platforms is required")
                    if qty is None or qty < 0: errs.append("Quantity must be 0 or more")
                
                if amount is None or amount <= 0: errs.append("Amount must be a positive value")
                if not bank: errs.append("Bank required")

                if errs:
                    st.error("\n".join(["❌ " + e for e in errs]))
                else:
                    platform_map = plats
                    actual_sequential_id = row['sequential_id'] if not pd.isna(row['sequential_id']) else row['id']
                    update_sale(int(actual_sequential_id), dt.strftime("%Y-%m-%d"), salesperson, cid, int(total_quantity), float(amount), status, bank, remark, platform_map)
                    st.success("✅ Sale updated.")
                    time.sleep(1)
                    st.rerun()
                
# --- Delete Sales ---
elif menu == "Delete Sales":
    st.subheader("🗑️ Delete Sales")
    sales_df = get_sales()
    if sales_df.empty:
        st.info("No sales to delete.")
    else:
        # Show both regular and prepaid sales for deletion
        formatted_options = []
        for idx, row in sales_df.iterrows():
            try:
                seq_id = row['sequential_id']
                if pd.isna(seq_id) or seq_id is None:
                    seq_id = row['id'] if 'id' in row and not pd.isna(row['id']) else idx + 1
                
                seq_id = int(float(seq_id))
                if row['sale_type'] == 'Prepaid':
                    formatted_id = f"#P{seq_id:02d}"
                else:
                    formatted_id = f"#{seq_id:02d}"
            except (ValueError, TypeError):
                formatted_id = f"#{int(row.get('id', idx + 1)):02d}"
            
            formatted_options.append(f"{formatted_id} - {row['customer']} - {row['date']} - {row['sale_type']}")
        
        sel_option = st.selectbox("Select Sale", formatted_options)
        
        try:
            # Extract details from selection
            parts = sel_option.split(" - ")
            formatted_id = parts[0]
            sale_type = parts[3]
            
            # Extract sequential ID
            if formatted_id.startswith("#P"):
                selected_sequential_id = int(formatted_id.replace("#P", ""))
                is_prepaid = True
            else:
                selected_sequential_id = int(formatted_id.replace("#", ""))
                is_prepaid = False
            
            # Find the matching row
            matching_rows = sales_df[
                (sales_df["sequential_id"] == selected_sequential_id) & 
                (sales_df["sale_type"] == sale_type)
            ]
            if matching_rows.empty:
                selected_index = formatted_options.index(sel_option)
                row = sales_df.iloc[selected_index]
                actual_sequential_id = row['sequential_id'] if not pd.isna(row['sequential_id']) else row['id']
            else:
                row = matching_rows.iloc[0]
                actual_sequential_id = selected_sequential_id
            
        except (ValueError, IndexError):
            st.error("Error selecting sale. Please try again.")
            st.stop()
        
        # Show different warning messages based on sale type
        if row["sale_type"] == "Prepaid":
            st.warning(f"You are about to delete prepaid sale #P{int(actual_sequential_id):02d} for {row['customer']} on {row['date']} amount ₹{row['amount']}. This will add ₹{row['amount']} back to the customer's prepaid balance.")
        else:
            st.warning(f"You are about to delete regular sale #{int(actual_sequential_id):02d} for {row['customer']} on {row['date']} amount ₹{row['amount']}")
        
        if st.button("Confirm Delete", type="primary"):
            if row["sale_type"] == "Prepaid":
                delete_prepaid_sale(int(actual_sequential_id))
                st.success("✅ Prepaid sale deleted successfully. Balance has been restored.")
            else:
                delete_sale(int(actual_sequential_id))
                st.success("✅ Regular sale deleted successfully.")
                
# --- Pending Payment ---
elif menu == "Pending Payment":
    st.subheader("⏳ Pending Payments")
    sales_df = get_sales()
    # Filter for regular sales that are pending
    pending_df = sales_df[(sales_df["status"] == "Pending") & (sales_df["sale_type"] == "Regular")].copy()
    
    if not pending_df.empty:
        # Create a list to hold records for display
        display_records = []

        for _, row in pending_df.iterrows():
            record = row.to_dict()
            record['formatted_id'] = f"#{int(row['sequential_id']):02d}"
            display_records.append(record)

        # Display header
        col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([0.8, 1, 1.2, 1.5, 1, 1, 1, 1, 1.5, 1, 1])
        with col1:
            st.write("**ID**")
        with col2:
            st.write("**Date**")
        with col3:
            st.write("**Salesperson**")
        with col4:
            st.write("**Customer**")
        with col5:
            st.write("**Quantity**")
        with col6:
            st.write("**Amount**")
        with col7:
            st.write("**Status**")
        with col8:
            st.write("**Bank**")
        with col9:
            st.write("**Remark**")
        with col10:
            st.write("**Type**")
        with col11:
            st.write("**Action**")
        
        st.markdown("---")
        
        # Display records with Streamlit components
        for row_data in display_records:
            col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([0.8, 1, 1.2, 1.5, 1, 1, 1, 1, 1.5, 1, 1])
            
            with col1:
                st.write(row_data['formatted_id'])
            with col2:
                st.write(row_data['date'])
            with col3:
                st.write(row_data['salesperson'])
            with col4:
                st.write(row_data['customer'])
            with col5:
                st.write(str(row_data['quantity']))
            with col6:
                st.write(f"₹{row_data['amount']:.2f}")
            with col7:
                st.write(row_data['status'])
            with col8:
                st.write(row_data['bank'])
            with col9:
                st.write(row_data['remark'] if row_data['remark'] else '')
            with col10:
                st.write(row_data['sale_type'])
            with col11:
                if st.button("Mark Paid", key=f"mark_paid_pending_{row_data['sequential_id']}", type="primary"):
                    mark_sale_paid(row_data['sequential_id'])
                    st.success(f"✅ Sale #{row_data['sequential_id']:02d} marked as Paid!")
                    st.rerun()

        # Display total pending amount
        pending_total = pending_df["amount"].sum()
        if pending_total > 0:
            st.metric("Total Pending Amount", f"₹{pending_total:,.2f}")
        else:
            st.info("No pending payments for this customer.")

    else:
        st.info("No pending payments.")


# --- Customer History ---
elif menu == "Customer History":
    st.subheader("👤 Customer History")
    customers_df = get_customers()
    if customers_df.empty:
        st.info("No customers yet.")
    else:
        cust_name = st.selectbox("Select Customer", customers_df["name"].tolist())
        cid = int(customers_df.loc[customers_df["name"] == cust_name, "id"].values[0])
        
        # Get both regular and prepaid sales for this customer
        sales_df = get_sales()
        customer_sales = sales_df[sales_df["customer"] == cust_name].copy()

        if not customer_sales.empty:
            # Format ID display based on sale type
            def format_sale_id(row):
                if row['sale_type'] == 'Prepaid':
                    return f"#P{int(row['sequential_id']):02d}"
                else:
                    return f"#{int(row['sequential_id']):02d}"
            
            customer_sales['formatted_id'] = customer_sales.apply(format_sale_id, axis=1)
            
            # Display header
            col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([0.8, 1, 1.2, 1.5, 1, 1, 1, 1, 1.5, 1, 1])
            with col1:
                st.write("**ID**")
            with col2:
                st.write("**Date**")
            with col3:
                st.write("**Salesperson**")
            with col4:
                st.write("**Customer**")
            with col5:
                st.write("**Quantity**")
            with col6:
                st.write("**Amount**")
            with col7:
                st.write("**Status**")
            with col8:
                st.write("**Bank**")
            with col9:
                st.write("**Remark**")
            with col10:
                st.write("**Type**")
            with col11:
                st.write("**Action**")
            
            st.markdown("---")
            
            # Display records
            for _, row in customer_sales.iterrows():
                col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([0.8, 1, 1.2, 1.5, 1, 1, 1, 1, 1.5, 1, 1])
                
                with col1:
                    st.write(row['formatted_id'])
                with col2:
                    st.write(row['date'])
                with col3:
                    st.write(row['salesperson'])
                with col4:
                    st.write(row['customer'])
                with col5:
                    st.write(str(row['quantity']))
                with col6:
                    st.write(f"₹{row['amount']:.2f}")
                with col7:
                    st.write(row['status'])
                with col8:
                    st.write(row['bank'])
                with col9:
                    st.write(row['remark'] if row['remark'] else '')
                with col10:
                    st.write(row['sale_type'])
                with col11:
                    if row["status"] == "Pending" and row["sale_type"] == "Regular":
                        if st.button("Mark Paid", key=f"mark_paid_history_{row['sequential_id']}", type="primary"):
                            mark_sale_paid(row['sequential_id'])
                            st.success(f"✅ Sale #{row['sequential_id']:02d} marked as Paid!")
                            st.rerun()
                    else:
                        if row["sale_type"] == "Prepaid":
                            st.write("Prepaid Sale")
                        else:
                            st.write("✅ Paid")

            # Pending total (only regular sales)
            regular_pending = customer_sales[(customer_sales["status"] == "Pending") & (customer_sales["sale_type"] == "Regular")]
            pending_total = regular_pending["amount"].sum()
            if pending_total > 0:
                st.metric("Pending Total", f"{pending_total:,.2f}")
            else:
                st.info("No pending payments for this customer.")
                
            # Show prepaid balance if customer has prepaid transactions
            current_balance = get_customer_balance(cid)
            if current_balance != 0:
                balance_color = "green" if current_balance >= 0 else "red"
                st.markdown(f"**Prepaid Balance:** <span style='color:{balance_color}'>₹{current_balance:.2f}</span>", unsafe_allow_html=True)
        else:
            st.info("No sales found for this customer.")


# --- Report ---
elif menu == "Report":
    st.subheader("📊 Reports")
    mode = st.radio("Report Type", ["Daily", "Monthly", "Custom"], horizontal=True)

    if mode == "Daily":
        d = st.date_input("Pick a day", value=date.today())
        start = end = d
    elif mode == "Monthly":
        d = st.date_input("Pick any day in the month", value=date.today())
        start = d.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
    else:
        c1, c2 = st.columns(2)
        with c1:
            start = st.date_input("Start date", value=date.today().replace(day=1))
        with c2:
            end = st.date_input("End date", value=date.today())

    # Get all activity (Regular Sales + Prepaid Add Funds only)
    activity_df = get_all_activity()

    filtered_df = activity_df[
        (activity_df["date"] >= start.strftime("%Y-%m-%d")) &
        (activity_df["date"] <= end.strftime("%Y-%m-%d"))
    ].copy()

    st.markdown(f"**From:** {start}  **To:** {end}")

    if not filtered_df.empty:
        display_columns = ['id', 'date', 'salesperson', 'customer', 'quantity',
                           'amount', 'status', 'bank', 'remark', 'type']
        df_display = filtered_df[display_columns].copy()
        df_display.columns = ['ID', 'Date', 'Salesperson', 'Customer', 'Quantity',
                              'Amount', 'Status/Type', 'Bank', 'Remark', 'Entry Type']
        st.dataframe(df_display, use_container_width=True)

        # Totals (no prepaid deductions, only credits + regular sales)
        total = filtered_df["amount"].sum()
        credits = filtered_df[filtered_df["status"] == "Credit"]["amount"].sum()
        paid = filtered_df[filtered_df["status"] == "Paid"]["amount"].sum()
        pending = filtered_df[filtered_df["status"] == "Pending"]["amount"].sum()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Amount", f"₹{total:.2f}")
        col2.metric("Credits (Funds In)", f"₹{credits:.2f}")
        col3.metric("Paid Sales", f"₹{paid:.2f}")
        col4.metric("Pending Sales", f"₹{pending:.2f}")

        st.markdown("### By Salesperson")
        grp = filtered_df.groupby("salesperson")["amount"].sum().reset_index().sort_values("amount", ascending=False)
        st.dataframe(grp, use_container_width=True)

        st.markdown("### Sales by Platform")
        conn = get_conn()
        try:
            # Fixed query with proper NULL handling and UNION for both regular and prepaid sales
            platform_sales_df = pd.read_sql_query(
                """
                WITH regular_platform_sales AS (
                    SELECT p.name AS platform, 
                           COALESCE(SUM(sp.quantity), 0) AS total_quantity,
                           COALESCE(SUM((s.amount * sp.quantity) / NULLIF(s.quantity, 0)), 0) AS total_amount
                    FROM platforms p
                    LEFT JOIN sale_platforms sp ON p.id = sp.platform_id
                    LEFT JOIN sales s ON sp.sale_id = s.id 
                    WHERE s.date BETWEEN %s AND %s OR s.id IS NULL
                    GROUP BY p.name
                ),
                prepaid_platform_sales AS (
                    SELECT p.name AS platform,
                           COALESCE(SUM(psp.quantity), 0) AS total_quantity,
                           COALESCE(SUM((ps.total_amount * psp.quantity) / NULLIF(ps.quantity, 0)), 0) AS total_amount
                    FROM platforms p
                    LEFT JOIN prepaid_sale_platforms psp ON p.id = psp.platform_id
                    LEFT JOIN prepaid_sales ps ON psp.prepaid_sale_id = ps.id
                    WHERE ps.date BETWEEN %s AND %s OR ps.id IS NULL
                    GROUP BY p.name
                )
                SELECT rps.platform,
                       (rps.total_quantity + COALESCE(pps.total_quantity, 0)) AS total_quantity,
                       (rps.total_amount + COALESCE(pps.total_amount, 0)) AS total_amount
                FROM regular_platform_sales rps
                LEFT JOIN prepaid_platform_sales pps ON rps.platform = pps.platform
                WHERE (rps.total_amount + COALESCE(pps.total_amount, 0)) > 0
                ORDER BY total_amount DESC
                """,
                conn,
                params=(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), 
                        start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            )
        except Exception as e:
            st.warning(f"Could not load platform sales data: {e}")
            # Fallback to simpler query for regular sales only
            try:
                platform_sales_df = pd.read_sql_query(
                    """
                    SELECT p.name AS platform, 
                           COALESCE(SUM(sp.quantity), 0) AS total_quantity,
                           COALESCE(COUNT(sp.id), 0) AS total_sales
                    FROM platforms p
                    LEFT JOIN sale_platforms sp ON p.id = sp.platform_id
                    LEFT JOIN sales s ON sp.sale_id = s.id AND s.date BETWEEN %s AND %s
                    WHERE s.id IS NOT NULL
                    GROUP BY p.name
                    HAVING COUNT(sp.id) > 0
                    ORDER BY total_quantity DESC
                    """,
                    conn,
                    params=(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
                )
            except:
                platform_sales_df = pd.DataFrame(columns=["platform", "total_quantity"])
        finally:
            conn.close()
        
        if not platform_sales_df.empty:
            st.dataframe(platform_sales_df, use_container_width=True)
        else:
            st.info("No platform sales data found for the selected date range.")
    else:
        st.info("No data found for the selected date range.")

    st.markdown("---")
    st.subheader("📅 Inactive Customers Report")

    # Add user input for days
    inactive_days = st.number_input(
        "Show customers inactive for more than (days):", 
        min_value=1, 
        max_value=365, 
        value=45,  # default value
        step=1
    )

    st.write(f"Customers who haven't purchased in the last {inactive_days} days")

    # Calculate date threshold based on user input
    threshold_date = (date.today() - timedelta(days=inactive_days)).strftime("%Y-%m-%d")
    
    # Database connection
    conn = get_conn()
    try:
        if USE_SQLITE:
            inactive_query = """
            WITH latest_sales AS (
                SELECT customer_id, MAX(date) as last_sale_date
                FROM (
                    SELECT customer_id, date FROM sales
                    UNION ALL
                    SELECT customer_id, date FROM prepaid_sales
                ) combined_sales
                GROUP BY customer_id
            )
            SELECT
                c.name AS customer,
                ls.last_sale_date,
                CAST(julianday('now') - julianday(ls.last_sale_date) AS INTEGER) AS days_since_last_sale
            FROM customers c
            LEFT JOIN latest_sales ls ON c.id = ls.customer_id
            WHERE ls.last_sale_date < %s OR ls.last_sale_date IS NULL
            ORDER BY (ls.last_sale_date IS NULL) DESC, ls.last_sale_date ASC
            """
        else:
            inactive_query = """
            WITH latest_sales AS (
                SELECT customer_id, MAX(date) as last_sale_date
                FROM (
                    SELECT customer_id, date FROM sales
                    UNION ALL
                    SELECT customer_id, date FROM prepaid_sales
                ) combined_sales
                GROUP BY customer_id
            )
            SELECT 
                c.name AS customer,
                ls.last_sale_date,
                CURRENT_DATE - ls.last_sale_date::date AS days_since_last_sale
            FROM customers c
            LEFT JOIN latest_sales ls ON c.id = ls.customer_id
            WHERE ls.last_sale_date < %s OR ls.last_sale_date IS NULL
            ORDER BY ls.last_sale_date ASC NULLS FIRST
            """
        inactive_customers_df = pd.read_sql_query(
            inactive_query,
            conn,
            params=(threshold_date,)
        )
        
        if not inactive_customers_df.empty:
            # Format the dataframe
            inactive_customers_df['last_sale_date'] = inactive_customers_df['last_sale_date'].fillna('Never')
            inactive_customers_df['days_since_last_sale'] = inactive_customers_df['days_since_last_sale'].fillna('N/A')
            
            # Display the dataframe
            st.dataframe(inactive_customers_df, use_container_width=True)
            
            # Show count
            st.metric("Inactive Customers", len(inactive_customers_df))
            
            # Export functionality
            if st.button("Export Inactive Customers"):
                csv = inactive_customers_df.to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv,
                    file_name=f"inactive_customers_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
        else:
            st.success(f"✅ All customers are active! No customers inactive for more than {inactive_days} days.")
    
    except Exception as e:
        st.error(f"Error fetching inactive customers: {e}")
    finally:
        conn.close()


# --- Platform ID List ---
elif menu == "Platform ID List":
    st.title("Platform ID Management")

    # Get platform data with a simple, direct approach
    conn = get_conn()
    
    # Query to get all platform entries with their associated sale and customer info
    try:
        query = """
        SELECT 
            sp.id as platform_id,
            COALESCE(s.sequential_id, s.id) as sale_sequential_id,
            sp.platform_account_id,
            sp.quantity,
            sp.is_archived,
            s.date,
            c.name as customer,
            p.name as platform,
            'Regular' as sale_type
        FROM sale_platforms sp
        JOIN sales s ON sp.sale_id = s.id
        JOIN customers c ON s.customer_id = c.id
        JOIN platforms p ON sp.platform_id = p.id
        
        UNION ALL
        
        SELECT 
            psp.id as platform_id,
            COALESCE(ps.sequential_id, ps.id) as sale_sequential_id,
            psp.platform_account_id,
            psp.quantity,
            psp.is_archived,
            ps.date,
            c.name as customer,
            p.name as platform,
            'Prepaid' as sale_type
        FROM prepaid_sale_platforms psp
        JOIN prepaid_sales ps ON psp.prepaid_sale_id = ps.id
        JOIN customers c ON ps.customer_id = c.id
        JOIN platforms p ON psp.platform_id = p.id
        
        ORDER BY date DESC, sale_sequential_id DESC, platform_id DESC
        """
        
        df = pd.read_sql_query(query, conn)
        
        # Additional safety: ensure no NULL values in critical columns
        if not df.empty:
            df['sale_sequential_id'] = df['sale_sequential_id'].fillna(df['platform_id'])
            df['quantity'] = df['quantity'].fillna(1)
            df['is_archived'] = df['is_archived'].fillna(False)
            
    except Exception as e:
        st.warning(f"Could not load prepaid data: {e}")
        # Fallback to regular sales only
        try:
            query = """
            SELECT 
                sp.id as platform_id,
                COALESCE(s.sequential_id, s.id) as sale_sequential_id,
                sp.platform_account_id,
                sp.quantity,
                sp.is_archived,
                s.date,
                c.name as customer,
                p.name as platform,
                'Regular' as sale_type
            FROM sale_platforms sp
            JOIN sales s ON sp.sale_id = s.id
            JOIN customers c ON s.customer_id = c.id
            JOIN platforms p ON sp.platform_id = p.id
            ORDER BY s.date DESC, s.id DESC, sp.id DESC
            """
            df = pd.read_sql_query(query, conn)
            
            if not df.empty:
                df['sale_sequential_id'] = df['sale_sequential_id'].fillna(df['platform_id'])
                df['quantity'] = df['quantity'].fillna(1)
                df['is_archived'] = df['is_archived'].fillna(False)
        except Exception as e2:
            st.error(f"Could not load platform data: {e2}")
            df = pd.DataFrame()
    
    conn.close()

    if df.empty:
        st.info("No platform data found.")
        st.stop()

    # ----------------- FILTERS -----------------
    platforms_df = get_platforms()
    platform_names = platforms_df["name"].tolist()

    colf1, colf2 = st.columns(2)
    with colf1:
        selected_platform = st.selectbox(
            "Filter by Platform", 
            options=["All"] + platform_names,
            key="platform_filter_main"
        )
    with colf2:
        archive_filter = st.selectbox(
            "Show",
            ["All", "Unarchived", "Archived"],
            key="archive_filter_main"
        )

    # Apply filters
    filtered_df = df.copy()

    # Platform filter
    if selected_platform != "All":
        filtered_df = filtered_df[filtered_df["platform"] == selected_platform]

    # Archive filter
    if archive_filter == "Archived":
        filtered_df = filtered_df[filtered_df["is_archived"] == True]
    elif archive_filter == "Unarchived":
        filtered_df = filtered_df[filtered_df["is_archived"] == False]

    if filtered_df.empty:
        st.info("No data found for the selected filters.")
        st.stop()

    # ----------------- TABLE -----------------
    st.subheader("Platform ID List")
    st.write("Use checkboxes to mark items as archived/done:")

    # Create header
    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(
        [0.8, 1, 1.2, 1.5, 1.2, 1.8, 0.8, 1.2]
    )
    with col1:
        st.write("**Archive**")
    with col2:
        st.write("**Sale ID**")
    with col3:
        st.write("**Date**")
    with col4:
        st.write("**Customer**")
    with col5:
        st.write("**Platform**")
    with col6:
        st.write("**Platform ID**")
    with col7:
        st.write("**Qty**")
    with col8:
        st.write("**Status**")

    st.markdown("---")

    # Display data rows
    for index, row in filtered_df.iterrows():
        col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(
            [0.8, 1, 1.2, 1.5, 1.2, 1.8, 0.8, 1.2]
        )
        
        platform_id = row['platform_id']
        current_archived = bool(row['is_archived'])
        
        with col1:
            archived = st.checkbox(
                "", 
                value=current_archived, 
                key=f"archive_{platform_id}_{index}"
            )
            
            # Update archive status if changed
            if archived != current_archived:
                sale_type = row['sale_type']
                
                try:
                    if sale_type == 'Prepaid':
                        archive_prepaid_platform_id(platform_id, archived)
                    else:
                        archive_platform_id(platform_id, archived)

                    status_text = "Done" if archived else "Pending"
                    st.toast(f"✅ {row['platform_account_id']} → {status_text}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error updating status: {str(e)}")

        with col2:
            # Safe formatting of sale ID using sequential ID
            try:
                sale_sequential_id = row['sale_sequential_id']
                if pd.isna(sale_sequential_id) or sale_sequential_id is None:
                    sale_sequential_id = platform_id
                sale_sequential_id = int(float(sale_sequential_id))
                
                if row['sale_type'] == 'Prepaid':
                    st.write(f"#P{sale_sequential_id:02d}")
                else:
                    st.write(f"#{sale_sequential_id:02d}")
            except (ValueError, TypeError, KeyError):
                st.write(f"#ERR{platform_id}")

        with col3:
            st.write(row['date'])

        with col4:
            st.write(row['customer'])

        with col5:
            st.write(row['platform'])

        with col6:
            st.write(row['platform_account_id'])

        with col7:
            try:
                quantity = int(float(row['quantity'])) if not pd.isna(row['quantity']) else 1
                st.write(quantity)
            except (ValueError, TypeError):
                st.write("1")

        with col8:
            if archived:
                st.success("✅ Done")
            else:
                st.write("⏳ Pending")

  # ----------------- SUMMARY (OVERALL, NOT FILTERED) -----------------
    st.subheader("Summary (All Data)")

    total_items_all = len(df)
    archived_items_all = len(df[df['is_archived'] == True])
    unarchived_items_all = total_items_all - archived_items_all

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Items", total_items_all)
    with col2:
        st.metric("Archived (Done)", archived_items_all)
    with col3:
        st.metric("Unarchived (Pending)", unarchived_items_all)

    # (optional) summary for current filter view
    st.subheader("Current Filter View")

    total_items_filtered = len(filtered_df)
    archived_items_filtered = len(filtered_df[filtered_df['is_archived'] == True])
    unarchived_items_filtered = total_items_filtered - archived_items_filtered

    colf1, colf2, colf3 = st.columns(3)
    with colf1:
        st.metric("Filtered Items", total_items_filtered)
    with colf2:
        st.metric("Filtered Archived", archived_items_filtered)
    with colf3:
        st.metric("Filtered Unarchived", unarchived_items_filtered)


    # Platform breakdown if filtered
    if selected_platform != "All":
        st.subheader(f"{selected_platform} Statistics")
        platform_data = filtered_df[filtered_df['platform'] == selected_platform]
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Platform Items", len(platform_data))
        with col2:
            archived_platform_items = len(platform_data[platform_data['is_archived'] == True])
            st.metric("Archived", archived_platform_items)

    # Sale type breakdown
    if 'sale_type' in filtered_df.columns:
        st.subheader("Sale Type Breakdown")
        regular_count = len(filtered_df[filtered_df['sale_type'] == 'Regular'])
        prepaid_count = len(filtered_df[filtered_df['sale_type'] == 'Prepaid'])
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Regular Sales", regular_count)
        with col2:
            st.metric("Prepaid Sales", prepaid_count)

    # Export functionality
    if st.button("Export Platform Data"):
        export_df = filtered_df.copy()
        
        # Format for export
        export_df['Status'] = export_df['is_archived'].apply(lambda x: "Done" if x else "Pending")
        export_df['Sale_ID'] = export_df.apply(
            lambda row: f"#P{row['sale_sequential_id']:02d}" if row['sale_type'] == 'Prepaid' else f"#{row['sale_sequential_id']:02d}",
            axis=1
        )

        # Select and rename columns for export
        export_columns = {
            'Sale_ID': 'Sale ID',
            'date': 'Date',
            'customer': 'Customer', 
            'platform': 'Platform',
            'platform_account_id': 'Platform ID',
            'quantity': 'Quantity',
            'Status': 'Status',
            'sale_type': 'Sale Type'
        }
        
        export_df = export_df[list(export_columns.keys())].rename(columns=export_columns)
        
        csv = export_df.to_csv(index=False)
        st.download_button(
            label="Download Platform CSV",
            data=csv,
            file_name=f"platform_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )



# --- Prepaid Customer ---
elif menu == "Prepaid Customer":
    st.title("💳 Prepaid Customer Management")
    
    prepaid_submenu = st.selectbox(
        "Choose Action",
        ["Add Funds", "Deduct Funds", "View Balances", "Transaction History", "Prepaid Platform ID List"]
    )
    
    # --- Add Funds ---
    if prepaid_submenu == "Add Funds":
        st.subheader("💰 Add Funds to Prepaid Customer")
        
        if 'add_funds_key' not in st.session_state:
            st.session_state.add_funds_key = 0
        
        container_key = f'add_funds_container_{st.session_state.add_funds_key}'
        with st.container(key=container_key):
            col1, col2 = st.columns(2)
            with col1:
                dt = st.date_input("Date", value=date.today(), max_value=date.today(), key=f'add_funds_date_{st.session_state.add_funds_key}')
            with col2:
                salesperson = st.selectbox("Received By", SALESPERSONS, key=f'add_funds_salesperson_{st.session_state.add_funds_key}')
            
            cid, cust_name = customer_selector(f"add_funds_{st.session_state.add_funds_key}")
            
            col1, col2 = st.columns(2)
            with col1:
                amount = st.number_input("Amount to Add", min_value=0.0, step=1.0, format="%0.2f", key=f'add_funds_amount_{st.session_state.add_funds_key}')
            with col2:
                bank = st.selectbox("Bank", BANKS, key=f'add_funds_bank_{st.session_state.add_funds_key}')
            
            description = st.text_input("Description", value="Fund Addition", key=f'add_funds_desc_{st.session_state.add_funds_key}')
            remark = st.text_area("Remark (optional)", key=f'add_funds_remark_{st.session_state.add_funds_key}')
            
            if st.button("Add Funds", type="primary"):
                errors = []
                if not dt: errors.append("Date is required")
                if cid == -1 and not cust_name: errors.append("Customer name is required")
                
                final_cid = cid
                if cid == -1 and cust_name:
                    final_cid = ensure_customer(cust_name)
                
                if final_cid == -1: errors.append("Customer selection is required")
                if amount is None or amount <= 0: errors.append("Amount must be positive")
                if not description: errors.append("Description is required")
                
                if errors:
                    st.error("\n".join(["❌ " + e for e in errors]))
                else:
                    add_prepaid_funds(final_cid, float(amount), dt.strftime("%Y-%m-%d"), 
                                      description, salesperson, bank, remark)
                    st.success(f"✅ Added ₹{amount:.2f} to {cust_name if cust_name else 'customer'} account")
                    
                    time.sleep(2)
                    st.session_state.add_funds_key += 1
                    st.rerun()
    
    # --- Deduct Funds ---
    elif prepaid_submenu == "Deduct Funds":
        st.subheader("🛒 Deduct Funds (Sale)")
        
        if 'deduct_funds_key' not in st.session_state:
            st.session_state.deduct_funds_key = 0

        container_key = f'deduct_funds_container_{st.session_state.deduct_funds_key}'
        with st.container(key=container_key):
            col1, col2 = st.columns(2)
            with col1:
                dt = st.date_input("Date", value=date.today(), max_value=date.today(), key=f'deduct_funds_date_{st.session_state.deduct_funds_key}')
            with col2:
                salesperson = st.selectbox("Salesperson", SALESPERSONS, key=f'deduct_funds_salesperson_{st.session_state.deduct_funds_key}')
            
            cid, cust_name = customer_selector(f"deduct_funds_{st.session_state.deduct_funds_key}")
            
            # Show current balance
            if cid != -1:
                current_balance = get_customer_balance(cid)
                balance_color = "green" if current_balance >= 0 else "red"
                st.markdown(f"💰 **Current Balance:** <span style='color:{balance_color}'>₹{current_balance:.2f}</span>", unsafe_allow_html=True)
            elif cust_name:
                try:
                    temp_cid = ensure_customer(cust_name)
                    current_balance = get_customer_balance(temp_cid)
                    balance_color = "green" if current_balance >= 0 else "red"
                    st.markdown(f"💰 **Current Balance:** <span style='color:{balance_color}'>₹{current_balance:.2f}</span>", unsafe_allow_html=True)
                except:
                    st.info("💰 New customer - Balance: ₹0.00")
            
            plats = platform_inputs(f"deduct_funds_{st.session_state.deduct_funds_key}")
            
            amount = st.number_input("Amount to Deduct", min_value=0.0, step=1.0, format="%0.2f", key=f'deduct_funds_amount_{st.session_state.deduct_funds_key}')
            remark = st.text_area("Remark (optional)", key=f'deduct_funds_remark_{st.session_state.deduct_funds_key}')
            
            if st.button("Process Sale", type="primary"):
                errors = []
                if not dt:
                    errors.append("Date is required")
                if not salesperson:
                    errors.append("Salesperson is required")
                if cid == -1 and not cust_name:
                    errors.append("Customer name is required")
                
                final_cid = cid
                if cid == -1 and cust_name:
                    final_cid = ensure_customer(cust_name)

                if final_cid == -1:
                    errors.append("Customer selection is required")
                if not plats:
                    errors.append("At least one platform is required")
                else:
                    for (_p_id, acc, _qty) in plats:
                        if not acc:
                            errors.append("Platform ID required for all selected platforms")

                total_quantity = sum(p[2] for p in plats)
                if total_quantity < 1:
                    errors.append("Total quantity must be at least 1")
                if amount is None or amount <= 0:
                    errors.append("Amount must be positive")

                if errors:
                    st.error("\n".join(["❌ " + e for e in errors]))
                else:
                    prepaid_sequential_id = deduct_prepaid_funds(
                        final_cid, float(amount), dt.strftime("%Y-%m-%d"),
                        salesperson, int(total_quantity), remark, plats
                    )
                    if prepaid_sequential_id > 0:
                        remaining_balance = get_customer_balance(final_cid)
                        st.success(f"✅ Sale processed! Sale ID: #P{prepaid_sequential_id:02d}")
                        balance_color = "green" if remaining_balance >= 0 else "red"
                        st.markdown(f"💰 **Remaining Balance:** <span style='color:{balance_color}'>₹{remaining_balance:.2f}</span>", unsafe_allow_html=True)
                        
                        time.sleep(2)
                        st.session_state.deduct_funds_key += 1
                        st.rerun()

    # --- View Balances ---
    elif prepaid_submenu == "View Balances":
        st.subheader("💰 Prepaid Customer Balances")

        # Add refresh button to force cache clear
        if st.button("🔄 Refresh Balances"):
            get_prepaid_balances.clear()
            st.rerun()

        balances_df = get_prepaid_balances()
        
        # Filter to only show customers with non-zero balances OR customers who have had prepaid transactions
        if not balances_df.empty:
            # Get list of customers who have had prepaid transactions
            transactions_df = get_prepaid_transactions()
            customers_with_transactions = set()
            if not transactions_df.empty:
                customers_with_transactions = set(transactions_df['customer'].unique())
                
            # Filter balances to show only:
            # 1. Customers with non-zero balances, OR
            # 2. Customers who have had prepaid transactions (even if balance is now zero)
            prepaid_customers_df = balances_df[
                (balances_df['balance'] != 0) | (balances_df['customer'].isin(customers_with_transactions))
            ]
            
            if not prepaid_customers_df.empty:
                # Format balance column with colors
                def format_balance(balance):
                    if balance >= 0:
                        return f"<span style='color:green'>₹{balance:.2f}</span>"
                    else:
                        return f"<span style='color:red'>₹{balance:.2f}</span>"

                prepaid_customers_df['formatted_balance'] = prepaid_customers_df['balance'].apply(format_balance)
                display_df = prepaid_customers_df[['customer', 'formatted_balance']].copy()
                display_df.columns = ['Customer', 'Balance']

                st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)
                
                # Summary
                total_balance = prepaid_customers_df['balance'].sum()
                positive_balance = prepaid_customers_df[prepaid_customers_df['balance'] >= 0]['balance'].sum()
                negative_balance = prepaid_customers_df[prepaid_customers_df['balance'] < 0]['balance'].sum()
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("💎 Total Balance", f"₹{total_balance:.2f}")
                with col2:
                    st.metric("💚 Positive Balance", f"₹{positive_balance:.2f}")
                with col3:
                    st.metric("❤️ Negative Balance", f"₹{negative_balance:.2f}")
            
                # Show count of prepaid customers
                st.info(f"Showing {len(prepaid_customers_df)} customers with prepaid activity")
            else:
                st.info("No customers with prepaid activity found.")
        else:
            st.info("No prepaid customers found.")
            
        # Show last updated time
        st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
        
    # --- Transaction History ---
    elif prepaid_submenu == "Transaction History":
        st.subheader("📜 Prepaid Transaction History")
        
        customers_df = get_customers()
        if not customers_df.empty:
            col1, col2 = st.columns(2)
            with col1:
                selected_customer = st.selectbox("Select Customer (optional)", ["All"] + customers_df["name"].tolist())
            with col2:
                selected_type = st.selectbox("Transaction Type", ["All"] + PREPAID_TRANSACTION_TYPES)
            
            transactions_df = get_prepaid_transactions()
            
            if not transactions_df.empty:
                # Apply filters
                filtered_df = transactions_df.copy()
                if selected_customer != "All":
                    filtered_df = filtered_df[filtered_df["customer"] == selected_customer]
                if selected_type != "All":
                    filtered_df = filtered_df[filtered_df["transaction_type"] == selected_type]
                
                if not filtered_df.empty:
                    # Format amount column with colors
                    def format_amount(row):
                        amt = row['amount']
                        if row['transaction_type'] == 'Credit':
                            return f"🟢 +₹{amt:.2f}"
                        else:
                            return f"🔴 -₹{amt:.2f}"
                    
                    display_df = filtered_df.copy()
                    display_df['Amount'] = display_df.apply(format_amount, axis=1)
                    
                    # Choose columns to show
                    columns_to_show = ['date', 'customer', 'transaction_type', 'Amount', 'description', 'salesperson', 'bank', 'remark']
                    display_df = display_df[columns_to_show].copy()
                    display_df.columns = ['Date', 'Customer', 'Type', 'Amount', 'Description', 'Salesperson', 'Bank', 'Remark']
                    
                    # Display clean table
                    st.dataframe(display_df, use_container_width=True)
                    
                    # Summary metrics
                    credit_total = filtered_df[filtered_df['transaction_type'] == 'Credit']['amount'].sum()
                    debit_total = filtered_df[filtered_df['transaction_type'] == 'Debit']['amount'].sum()
                    net_amount = credit_total - debit_total
                    net_color = "green" if net_amount >= 0 else "red"
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("💚 Total Credits", f"₹{credit_total:.2f}")
                    col2.metric("❤️ Total Debits", f"₹{debit_total:.2f}")
                    col3.markdown(f"**💙 Net:** <span style='color:{net_color}'>₹{net_amount:.2f}</span>", unsafe_allow_html=True)
                else:
                    st.info("No transactions found for the selected filters.")
            else:
                st.info("No prepaid transactions found.")
        else:
            st.info("No customers found.")
            
    
    # --- Prepaid Platform ID List ---
    elif prepaid_submenu == "Prepaid Platform ID List":
        st.subheader("🧾 Prepaid Platform ID Management")
        
        # Get prepaid platform data
        prepaid_platforms_df = get_prepaid_sale_platforms_df()
        prepaid_sales_df = get_prepaid_sales()
        
        if not prepaid_platforms_df.empty and not prepaid_sales_df.empty:
            # Merge platform data with sales data using sequential_id
            full_df = prepaid_platforms_df.merge(prepaid_sales_df, left_on="prepaid_sale_id", right_on="id", how="left")
            full_df = full_df.sort_values(by="date", ascending=False).reset_index(drop=True)
            full_df.rename(columns={'quantity_x': 'Quantity', 'id_x': 'prepaid_sale_platform_id'}, inplace=True)
            full_df = full_df[['prepaid_sale_platform_id', 'sequential_id', 'date', 'customer',
                               'platform', 'platform_account_id', 'Quantity', 'is_archived']]
            
            platforms_df = get_platforms()
            platform_names = platforms_df["name"].tolist()
            
            # Platform filter
            selected_platform_name = st.selectbox("Filter by Platform", options=["All"] + platform_names, key="prepaid_platform_filter")
            
            filtered_df = full_df.copy()
            if selected_platform_name != "All":
                filtered_df = filtered_df[filtered_df["platform"] == selected_platform_name]
            
            if not filtered_df.empty:
                st.write("Use checkboxes to mark items as archived/done:")
                
                # Header row
                col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([0.8, 1, 1.2, 1.5, 1.2, 1.8, 0.8, 1.2])
                with col1:
                    st.write("**Archive**")
                with col2:
                    st.write("**Sale ID**")
                with col3:
                    st.write("**Date**")
                with col4:
                    st.write("**Customer**")
                with col5:
                    st.write("**Platform**")
                with col6:
                    st.write("**Platform ID**")
                with col7:
                    st.write("**Qty**")
                with col8:
                    st.write("**Status**")
                
                st.markdown("---")
                
                # Display rows
                for _, row in filtered_df.iterrows():
                    prepaid_sale_platform_id = row['prepaid_sale_platform_id']
                    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([0.8, 1, 1.2, 1.5, 1.2, 1.8, 0.8, 1.2])
                    
                    with col1:
                        current_archived = bool(row['is_archived'])
                        archived = st.checkbox("", value=current_archived, key=f"prepaid_archive_{prepaid_sale_platform_id}")
                        
                        if archived != current_archived:
                            archive_prepaid_platform_id(prepaid_sale_platform_id, archived)
                            status_text = "Done" if archived else "Pending"
                            st.toast(f"✅ {row['platform_account_id']} → {status_text}")
                            st.rerun()
            
                    with col2:
                        st.write(f"#P{row['sequential_id']:02d}")
                    with col3:
                        st.write(row['date'])
                    with col4:
                        st.write(row['customer'])
                    with col5:
                        st.write(row['platform'])
                    with col6:
                        st.write(row['platform_account_id'])
                    with col7:
                        st.write(int(row['Quantity']))
                    with col8:
                        if archived:
                            st.success("✅ Done")
                        else:
                            st.write("⏳ Pending")
            
                # Summary statistics
                st.subheader("📊 Prepaid Platform Summary")
                col1, col2, col3 = st.columns(3)
                
                total_items = len(filtered_df)
                archived_items = len(filtered_df[filtered_df['is_archived'] == True])
                pending_items = total_items - archived_items
                
                with col1:
                    st.metric("Total Items", total_items)
                with col2:
                    st.metric("Archived Items", archived_items)
                with col3:
                    st.metric("Pending Items", pending_items)
            else:
                st.info("No prepaid platform data found for the selected filter.")
        else:
            st.info("No prepaid sales data found.")
