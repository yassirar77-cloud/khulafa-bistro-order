import sqlite3
from datetime import datetime


def migrate():
    conn = sqlite3.connect('khulafa_bistro.db')
    cursor = conn.cursor()

    # Create restaurant_tables table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS restaurant_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_number TEXT UNIQUE NOT NULL,
        qr_url TEXT UNIQUE,
        status TEXT DEFAULT 'available',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Insert tables T01..T20 (idempotent — INSERT OR IGNORE keeps existing rows).
    # Extend the range here when more tables are added; production DBs will also
    # pick up the new rows on the next startup.
    test_tables = [(f'T{n:02d}', f'/table/T{n:02d}') for n in range(1, 21)]
    for table_number, qr_url in test_tables:
        cursor.execute(
            'INSERT OR IGNORE INTO restaurant_tables (table_number, qr_url) VALUES (?, ?)',
            (table_number, qr_url)
        )

    # Add table_number column to orders (nullable)
    try:
        cursor.execute('ALTER TABLE orders ADD COLUMN table_number TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add order_source column to orders (default 'telegram')
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN order_source TEXT DEFAULT 'telegram'")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.commit()
    conn.close()
    print("Migration completed: restaurant_tables created, orders table updated.")


if __name__ == '__main__':
    migrate()
