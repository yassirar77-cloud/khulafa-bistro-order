# tests/conftest.py
"""
Shared fixtures for the Khulafa Bistro test suite.
Every test runs isolated — no production DB or external API calls.
"""
import pytest
import sqlite3
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Test database (in-memory, isolated per test) ──
@pytest.fixture(scope="function")
def test_db():
    """Fresh in-memory SQLite for each test. Never touches production DB."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    # Create base schema
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            available INTEGER DEFAULT 1
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            customer_telegram_id TEXT NOT NULL,
            customer_name TEXT,
            customer_phone TEXT,
            order_type TEXT NOT NULL,
            arrival_time TEXT,
            total_price REAL NOT NULL,
            payment_slip_url TEXT,
            payment_confirmed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            payment_method TEXT DEFAULT 'maybank',
            promo_code TEXT,
            discount_amount REAL DEFAULT 0,
            estimated_time INTEGER DEFAULT 20,
            table_number TEXT,
            order_source TEXT DEFAULT 'telegram'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            menu_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            note TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (menu_item_id) REFERENCES menu_items(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            discount_percentage INTEGER NOT NULL,
            min_order_amount REAL DEFAULT 0,
            max_uses INTEGER,
            current_uses INTEGER DEFAULT 0,
            valid_from TEXT,
            valid_until TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method_name TEXT UNIQUE NOT NULL,
            qr_code_url TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS restaurant_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number TEXT UNIQUE NOT NULL,
            qr_url TEXT UNIQUE,
            status TEXT DEFAULT 'available',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Seed some menu items
    menu_data = [
        ("Roti Canai", "ROTI CANAI", 1.50),
        ("Roti Telur", "ROTI CANAI", 2.50),
        ("Roti Canai Susu", "ROTI CANAI", 2.00),
        ("Naan Biasa", "NAAN", 3.00),
        ("Naan Butter Garlic", "NAAN", 5.00),
        ("Naan Cheese", "NAAN", 5.00),
        ("Teh Ais", "TEH", 2.20),
        ("Teh O Ais", "TEH", 1.80),
        ("Milo", "MILO", 2.80),
        ("Nasi Goreng Kampung", "NASI GORENG THAI", 6.50),
        ("Maggi Goreng", "MEE n MAGGIE", 6.00),
        ("Mee Goreng Mamak", "MEE n MAGGIE", 6.00),
        ("Briyani Ayam", "NASI BIRIYANI", 11.50),
        ("Ayam Goreng", "AYAM", 5.00),
        ("Nasi Ayam", "AYAM", 7.51),
    ]
    cursor.executemany(
        'INSERT INTO menu_items (name, category, price) VALUES (?, ?, ?)',
        menu_data
    )

    # Seed restaurant tables
    cursor.executemany(
        'INSERT INTO restaurant_tables (table_number, qr_url, status) VALUES (?, ?, ?)',
        [("T01", "/table/T01", "available"), ("T02", "/table/T02", "available")]
    )

    # Seed payment methods
    cursor.executemany(
        'INSERT INTO payment_methods (method_name, qr_code_url, is_active) VALUES (?, ?, ?)',
        [("maybank", "https://example.com/maybank.jpg", 1),
         ("touchngo", "https://example.com/tng.jpg", 1),
         ("grabpay", "", 1)]
    )

    # Seed settings
    cursor.executemany(
        'INSERT INTO settings (key, value) VALUES (?, ?)',
        [("restaurant_name", "Khulafa Bistro"), ("payment_qr_url", "")]
    )

    conn.commit()
    yield conn
    conn.close()


# ── OrderEngine fixture ──
@pytest.fixture
def engine():
    """Fresh OrderEngine instance."""
    from order_engine import OrderEngine
    return OrderEngine()


# ── Sample order fixture ──
@pytest.fixture
def sample_order():
    return [
        {"name": "Roti Canai", "qty": 1, "price": 2.00},
        {"name": "Nasi Goreng Kampung", "qty": 1, "price": 8.00},
    ]
