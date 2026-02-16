import sqlite3
import json

# Database initialization for Khulafa Bistro
def init_database():
    conn = sqlite3.connect('khulafa_bistro.db')
    cursor = conn.cursor()

    # Create tables
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
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    # Insert menu items - All 176 items from Khulafa Bistro
    menu_data = [
        # AIR TIN
        ("100 Plus", "AIR TIN", 2.60),
        ("Air Tin", "AIR TIN", 2.60),
        ("Bobo Boy", "AIR TIN", 3.00),
        ("Coke Tin", "AIR TIN", 2.60),
        ("Lychee Kota", "AIR TIN", 1.80),
        ("Mineral Water Big", "AIR TIN", 2.50),
        ("Mineral Water Small", "AIR TIN", 1.50),
        ("Soya Tin", "AIR TIN", 2.60),
        ("Teh Bunga", "AIR TIN", 2.60),

        # AYAM
        ("Ayam Bawang", "AYAM", 8.50),
        ("Ayam Goreng", "AYAM", 5.00),
        ("Ayam Rempah", "AYAM", 8.50),
        ("Ayam Rendang", "AYAM", 6.00),
        ("Nasi Ayam", "AYAM", 7.51),
        ("Nasi Ayam Bawang", "AYAM", 10.54),
        ("Nasi Ayam Bawang Sayur", "AYAM", 11.02),
        ("Nasi Ayam Rendang Sayur", "AYAM", 8.50),
        ("Nasi Ayam Sayur", "AYAM", 8.10),
        ("Nasi Putih Ayam Rempah", "AYAM", 10.58),
        ("Nasi Putih Ayam Rempah Sayur", "AYAM", 11.00),

        # BIHUN n KUEY TEOW
        ("Bihun G Telur Mata", "BIHUN n KUEY TEOW", 7.50),
        ("Bihun Goreng Mamak", "BIHUN n KUEY TEOW", 6.00),
        ("Kuey Teow G Mamak", "BIHUN n KUEY TEOW", 6.00),

        # BLENTED n SHAKE
        ("Jumbo Extra Jus", "BLENTED n SHAKE", 6.50),
        ("Jumbo Glass", "BLENTED n SHAKE", 1.50),
        ("Teh Ais Jumbo", "BLENTED n SHAKE", 5.90),

        # BUAH
        ("Buah 3.5", "BUAH", 3.50),
        ("Buah 4.5", "BUAH", 4.50),

        # CHAPPATI
        ("Chappathi", "CHAPPATI", 2.30),
        ("Chappathi Kua Sardin", "CHAPPATI", 2.80),
        ("Poori 1pc", "CHAPPATI", 1.80),
        ("Poori Set", "CHAPPATI", 3.42),

        # DAGING
        ("Nasi Daging", "DAGING", 9.50),

        # FRESH JUICE
        ("Fresh Orange", "FRESH JUICE", 6.00),
        ("Watermelon Juice", "FRESH JUICE", 6.00),

        # GULA GULA
        ("Kacang 2.00", "GULA GULA", 2.00),

        # HORLICKS
        ("Horlicks", "HORLICKS", 3.00),

        # ICE CREAM
        ("Tube Ais", "ICE CREAM", 1.80),

        # IDLI APPAM
        ("Appam", "IDLI APPAM", 2.00),
        ("Appam Telur", "IDLI APPAM", 3.00),
        ("Idly 1pc", "IDLI APPAM", 1.34),

        # IKAN
        ("Ikan Masak Kari", "IKAN", 8.00),
        ("Kepala Ikan Ikut Saiz", "IKAN", 55.00),
        ("Nasi Ikan Sayur", "IKAN", 10.50),
        ("Telur Ikan (b)", "IKAN", 10.57),
        ("Telur Ikan Ikut Saiz", "IKAN", 7.00),
        ("Telur Ikan Rm 12", "IKAN", 13.00),

        # INDOMEE
        ("Indomee Double", "INDOMEE", 8.50),
        ("Indomee Goreng", "INDOMEE", 5.50),
        ("Indomee Kosong", "INDOMEE", 4.50),

        # KAMBING
        ("Kambing Mysur", "KAMBING", 12.00),
        ("Kambing+nasi Putih", "KAMBING", 14.50),
        ("Kambing+nasi+sayur", "KAMBING", 15.00),

        # KARI LAUK
        ("Bendi", "KARI LAUK", 1.07),
        ("Chilli Hijau", "KARI LAUK", 1.00),
        ("Ext Sayur", "KARI LAUK", 2.00),
        ("Nasi Putih", "KARI LAUK", 2.53),
        ("Nasi Sayur", "KARI LAUK", 3.67),
        ("Nasi Tambah", "KARI LAUK", 1.00),
        ("Papadom", "KARI LAUK", 1.00),
        ("Sayur", "KARI LAUK", 1.50),
        ("Telur Rebus", "KARI LAUK", 1.50),
        ("Telur Sambal", "KARI LAUK", 2.00),

        # KOPI
        ("Kopi", "KOPI", 1.70),
        ("Kopi O", "KOPI", 1.50),
        ("Open DRINKS Rm", "KOPI", 1.60),

        # KUEY TEOW THAI
        ("Kueyteow Goreng Basa", "KUEY TEOW THAI", 7.00),

        # LEMON n ABC
        ("Abc Biasa", "LEMON n ABC", 5.00),
        ("Barli Lemon Panas", "LEMON n ABC", 3.50),
        ("Lemon Panas", "LEMON n ABC", 3.20),
        ("Lychee kang", "LEMON n ABC", 5.50),

        # MAGGIE G THAI
        ("Maggi Goreng Basa", "MAGGIE G THAI", 7.00),

        # MEE n MAGGIE
        ("Maggi G Ayam Mamak", "MEE n MAGGIE", 9.50),
        ("Maggi G Daging", "MEE n MAGGIE", 9.50),
        ("Maggi G Kambing", "MEE n MAGGIE", 13.00),
        ("Maggi Goreng", "MEE n MAGGIE", 6.00),
        ("Maggi Goreng Telur Mata", "MEE n MAGGIE", 7.50),
        ("Maggi Sup", "MEE n MAGGIE", 6.00),
        ("Mee C Bihun", "MEE n MAGGIE", 6.00),
        ("Mee G Ayam Mamak", "MEE n MAGGIE", 9.50),
        ("Mee G Ayam T Mata", "MEE n MAGGIE", 11.00),
        ("Mee Goreng Daging", "MEE n MAGGIE", 9.50),
        ("Mee Goreng Mamak", "MEE n MAGGIE", 6.00),
        ("Mee Goreng Telur Mata", "MEE n MAGGIE", 7.50),

        # MILO
        ("Milo", "MILO", 2.80),

        # NAAN
        ("Ayam Tandoori", "NAAN", 8.50),
        ("Naan Butter", "NAAN", 3.50),
        ("Naan Mozzerala Cheese", "NAAN", 7.00),
        ("Naan Biasa", "NAAN", 3.00),
        ("Naan Butter Garlic", "NAAN", 5.00),
        ("Naan Cheese", "NAAN", 5.00),

        # NASI BIRIYANI
        ("Biriyani Daging Set", "NASI BIRIYANI", 18.00),
        ("Biriyani Ikan Set", "NASI BIRIYANI", 15.00),
        ("Biriyani Kambing Set", "NASI BIRIYANI", 22.00),
        ("Briyani Ayam", "NASI BIRIYANI", 11.50),
        ("Briyani Ayam Bawang Set", "NASI BIRIYANI", 17.00),
        ("Briyani Ayam Goreng Set", "NASI BIRIYANI", 13.13),
        ("Nasi Biriyani Kosong", "NASI BIRIYANI", 6.89),
        ("Nasi Briyani Telur", "NASI BIRIYANI", 8.10),

        # NASI GORENG MAMAK
        ("Nasi G Ayam Mamak", "NASI GORENG MAMAK", 9.50),
        ("Nasi G Ayam Telur Mata", "NASI GORENG MAMAK", 11.00),
        ("Nasi G Kampung Mamak", "NASI GORENG MAMAK", 6.50),
        ("Nasi G Pathaya Mamak", "NASI GORENG MAMAK", 8.00),
        ("Nasi Goreng Cina Mamak", "NASI GORENG MAMAK", 6.00),
        ("Nasi Goreng Mamak", "NASI GORENG MAMAK", 6.00),
        ("Telur Dadar", "NASI GORENG MAMAK", 2.00),
        ("Telur Goreng", "NASI GORENG MAMAK", 1.50),
        ("Telur Mata", "NASI GORENG MAMAK", 1.50),

        # NASI GORENG THAI
        ("Nasi G Ayam", "NASI GORENG THAI", 9.50),
        ("Nasi Goreng Biasa", "NASI GORENG THAI", 6.00),
        ("Nasi Goreng Kampung", "NASI GORENG THAI", 6.50),

        # NESCAFE
        ("Bru Coffee", "NESCAFE", 3.00),
        ("Nescafe", "NESCAFE", 2.80),
        ("Nescafe C", "NESCAFE", 2.80),
        ("Nescafe O", "NESCAFE", 2.50),
        ("Nestlo", "NESCAFE", 3.00),

        # PACKET DRINKS
        ("Kopi Jantan", "PACKET DRINKS", 3.50),

        # ROJAK
        ("Rojak Biasa", "ROJAK", 5.50),

        # ROTI BAKAR n MURTABAK
        ("Murtabak Ayam", "ROTI BAKAR n MURTABAK", 9.00),
        ("Roti Bakar", "ROTI BAKAR n MURTABAK", 2.50),
        ("Roti Bakar Telur Cheese", "ROTI BAKAR n MURTABAK", 4.50),

        # ROTI CANAI
        ("Roti Cheese Double", "ROTI CANAI", 4.50),
        ("Roti Boom", "ROTI CANAI", 2.50),
        ("Roti Canai", "ROTI CANAI", 1.50),
        ("Roti Canai Susu", "ROTI CANAI", 2.00),
        ("Roti Jantan", "ROTI CANAI", 3.50),
        ("Roti Jantan Bawang", "ROTI CANAI", 4.00),
        ("Roti Khawin", "ROTI CANAI", 4.00),
        ("Roti Pisang", "ROTI CANAI", 3.00),
        ("Roti Planta", "ROTI CANAI", 2.50),
        ("Roti Tambal", "ROTI CANAI", 2.50),
        ("Roti Telur", "ROTI CANAI", 2.50),
        ("Roti Telur Bawang", "ROTI CANAI", 3.00),
        ("Roti Telur Bawang Cilli", "ROTI CANAI", 3.20),

        # ROTI SPECIAL
        ("Roti Khulafa Double", "ROTI SPECIAL", 6.00),
        ("Roti Khulafa Special", "ROTI SPECIAL", 4.50),
        ("Roti Sarang Burung", "ROTI SPECIAL", 4.50),
        ("Roti Sardin", "ROTI SPECIAL", 4.00),
        ("Roti Tissue", "ROTI SPECIAL", 4.50),

        # SIRAP
        ("Barli Panas", "SIRAP", 2.00),
        ("Limau Panas", "SIRAP", 1.80),
        ("Limau Asam Ais", "SIRAP", 2.80),
        ("Sirap Ais", "SIRAP", 2.00),

        # SOTONG
        ("Sotong Rm", "SOTONG", 6.00),
        ("Telur Sotong ( B )", "SOTONG", 10.50),

        # SUSU n CHAM
        ("Susu Lembu", "SUSU n CHAM", 4.00),
        ("Teh Susu Lembu", "SUSU n CHAM", 4.00),

        # TEH
        ("Air Panas", "TEH", 0.30),
        ("Air Suam", "TEH", 0.30),
        ("Ais Kosong", "TEH", 0.30),
        ("Tea Masala", "TEH", 3.70),
        ("Teh", "TEH", 1.70),
        ("Teh Halia", "TEH", 2.00),
        ("Teh O", "TEH", 1.50),
        ("Teh Ais", "TEH", 2.20),
        ("Teh Besar", "TEH", 2.20),
        ("Teh C", "TEH", 1.70),
        ("Teh Khulafa Big", "TEH", 2.50),
        ("Teh O Ais", "TEH", 1.80),
        ("Teh O Halia", "TEH", 1.70),
        ("Teh O Limau", "TEH", 1.70),
        ("Telur 1/2 Masak", "TEH", 2.60),
        ("Telur 1/2 Masak 1biji", "TEH", 1.30),
        ("Telur 3/4 Masak", "TEH", 2.60),

        # TELUR THAI
        ("Telur Mata", "TELUR THAI", 1.50),

        # TOM YAM
        ("Tomyam Campur", "TOM YAM", 9.00),

        # Tosai Morning
        ("Tosai Bawang", "Tosai Morning", 3.00),
        ("TOSAI BIASA", "Tosai Morning", 2.20),
        ("Tosai Jantan", "Tosai Morning", 4.20),
        ("Tosai Masala", "Tosai Morning", 4.00),
        ("Tosai Paper", "Tosai Morning", 3.20),
        ("Tosai Rawa", "Tosai Morning", 3.24),
        ("Tosai Sardin", "Tosai Morning", 4.50),
        ("Tosai Telur", "Tosai Morning", 3.20),

        # Vadai
        ("Puttu Mayam", "Vadai", 1.50),
        ("Samosa", "Vadai", 1.50),
        ("Vadai", "Vadai", 1.20),

        # WESTERN
        ("Chicken Chop", "WESTERN", 14.90),
        ("Onion Ring", "WESTERN", 6.00),
    ]

    # Insert menu items only if the table is empty (avoid duplicates on restart)
    cursor.execute('SELECT COUNT(*) FROM menu_items')
    if cursor.fetchone()[0] == 0:
        cursor.executemany('INSERT INTO menu_items (name, category, price) VALUES (?, ?, ?)', menu_data)
        print(f"Inserted {len(menu_data)} menu items.")
    else:
        print("Menu items already exist, skipping insert.")

    # Insert default settings
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
                   ('payment_qr_url', ''))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
                   ('restaurant_name', 'Khulafa Bistro'))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
                   ('restaurant_phone', ''))

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully with all 176 menu items!")

if __name__ == '__main__':
    init_database()