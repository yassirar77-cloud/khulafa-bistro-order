"""
Database Migration Script for New Features
Run this to add new tables and columns
"""

import sqlite3
from datetime import datetime

def migrate_database():
    conn = sqlite3.connect('khulafa_bistro.db')
    cursor = conn.cursor()
    
    print("Starting database migration...")
    
    try:
        # 1. Add new columns to orders table
        print("Adding new columns to orders table...")
        
        # Add payment_method column
        try:
            cursor.execute("""
                ALTER TABLE orders 
                ADD COLUMN payment_method TEXT DEFAULT 'maybank'
            """)
            print("✓ Added payment_method column")
        except sqlite3.OperationalError:
            print("- payment_method column already exists")
        
        # Add promo_code column
        try:
            cursor.execute("""
                ALTER TABLE orders 
                ADD COLUMN promo_code TEXT
            """)
            print("✓ Added promo_code column")
        except sqlite3.OperationalError:
            print("- promo_code column already exists")
        
        # Add discount_amount column
        try:
            cursor.execute("""
                ALTER TABLE orders 
                ADD COLUMN discount_amount REAL DEFAULT 0
            """)
            print("✓ Added discount_amount column")
        except sqlite3.OperationalError:
            print("- discount_amount column already exists")
        
        # Add estimated_time column
        try:
            cursor.execute("""
                ALTER TABLE orders 
                ADD COLUMN estimated_time INTEGER DEFAULT 20
            """)
            print("✓ Added estimated_time column")
        except sqlite3.OperationalError:
            print("- estimated_time column already exists")
        
        # 2. Add note column to order_items table
        print("\nAdding note column to order_items table...")
        try:
            cursor.execute("""
                ALTER TABLE order_items 
                ADD COLUMN note TEXT
            """)
            print("✓ Added note column to order_items")
        except sqlite3.OperationalError:
            print("- note column already exists in order_items")
        
        # 3. Create promo_codes table
        print("\nCreating promo_codes table...")
        cursor.execute("""
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created promo_codes table")
        
        # 4. Create payment_methods table
        print("\nCreating payment_methods table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method_name TEXT UNIQUE NOT NULL,
                qr_code_url TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Created payment_methods table")
        
        # 5. Create order_tracking table
        print("\nCreating order_tracking table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (id)
            )
        """)
        print("✓ Created order_tracking table")
        
        # 6. Insert default promo codes
        print("\nInserting default promo codes...")
        default_promos = [
            ('WELCOME10', 10, 0, 100, None, '2025-12-31'),
            ('SAVE20', 20, 50, 50, None, '2025-12-31'),
            ('FIRST15', 15, 0, None, None, '2025-12-31'),
            ('STUDENT10', 10, 0, 200, None, '2025-12-31'),
        ]
        
        for code, discount, min_amount, max_uses, valid_from, valid_until in default_promos:
            try:
                cursor.execute("""
                    INSERT INTO promo_codes (code, discount_percentage, min_order_amount, max_uses, valid_from, valid_until)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (code, discount, min_amount, max_uses, valid_from, valid_until))
                print(f"✓ Added promo code: {code} ({discount}% off)")
            except sqlite3.IntegrityError:
                print(f"- Promo code {code} already exists")
        
        # 7. Insert default payment methods
        print("\nInserting default payment methods...")
        default_payments = [
            ('maybank', None),
            ('touchngo', None),
            ('grabpay', None),
        ]
        
        for method, qr_url in default_payments:
            try:
                cursor.execute("""
                    INSERT INTO payment_methods (method_name, qr_code_url)
                    VALUES (?, ?)
                """, (method, qr_url))
                print(f"✓ Added payment method: {method}")
            except sqlite3.IntegrityError:
                print(f"- Payment method {method} already exists")
        
        # 8. Add payment_qr_url setting
        print("\nAdding payment QR URL setting...")
        try:
            cursor.execute("""
                INSERT INTO settings (key, value)
                VALUES ('payment_qr_url', '/static/maybank-qr.jpg')
            """)
            print("✓ Added payment_qr_url setting")
        except sqlite3.IntegrityError:
            print("- payment_qr_url setting already exists")
        except sqlite3.OperationalError:
            # Settings table might not exist, create it
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute("""
                INSERT OR REPLACE INTO settings (key, value)
                VALUES ('payment_qr_url', '/static/maybank-qr.jpg')
            """)
            print("✓ Created settings table and added payment_qr_url")

        conn.commit()
        print("\n✅ Database migration completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        conn.rollback()
        
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()
