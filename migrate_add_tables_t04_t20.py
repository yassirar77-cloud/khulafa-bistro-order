"""One-shot migration to seed tables T04..T20 into the production DB.

The original migrate_add_tables.py only seeded T01..T03. The live Render
DB still reflects that older seed, so /table/T04..T20 requests 404 with
"Table not found" even though QR codes have been printed for those tables.

This migration is idempotent (INSERT OR IGNORE) and safe to re-run.
"""
import sqlite3


def migrate():
    conn = sqlite3.connect('khulafa_bistro.db')
    cursor = conn.cursor()

    # Defensive: ensure the table exists (this migration may run before
    # migrate_add_tables.py on a fresh DB).
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS restaurant_tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_number TEXT UNIQUE NOT NULL,
        qr_url TEXT UNIQUE,
        status TEXT DEFAULT 'available',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    new_tables = [(f'T{n:02d}', f'/table/T{n:02d}') for n in range(4, 21)]
    for table_number, qr_url in new_tables:
        cursor.execute(
            'INSERT OR IGNORE INTO restaurant_tables (table_number, qr_url) VALUES (?, ?)',
            (table_number, qr_url),
        )

    conn.commit()
    count = cursor.execute(
        "SELECT COUNT(*) FROM restaurant_tables "
        "WHERE table_number IN (" + ",".join(f"'T{n:02d}'" for n in range(4, 21)) + ")"
    ).fetchone()[0]
    conn.close()
    print(f"Migration T04-T20 complete. Tables T04-T20 present: {count}/17")


if __name__ == '__main__':
    migrate()
