from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import json
from datetime import datetime
import requests
import httpx
import os
from pathlib import Path
from enhanced_routes import setup_enhanced_routes
from order_engine import get_engine, MENU, _SORTED_KEYS
from threading import Thread
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
import asyncio
from openai import OpenAI

# ========== DeepSeek API Setup (Extraction Only — No Conversation) ==========
_deepseek_client = None

def get_deepseek_client():
    """Lazy-init DeepSeek client (OpenAI-compatible)."""
    global _deepseek_client
    if _deepseek_client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        _deepseek_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _deepseek_client

# ========== OpenAI Whisper STT Setup ==========
_whisper_client = None

def get_whisper_client():
    """Lazy-init OpenAI Whisper client for audio transcription."""
    global _whisper_client
    if _whisper_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        _whisper_client = OpenAI(api_key=api_key)
    return _whisper_client

def transcribe_audio(audio_file_path):
    """Transcribe an audio file using OpenAI Whisper API with Khulafa menu hints."""
    client = get_whisper_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not set")
    with open(audio_file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ms",
            prompt=(
                "Pelanggan sedang membuat pesanan makanan di restoran Khulafa. "
                "Menu kami: roti canai, roti canai susu, roti telur, roti telur bawang, "
                "roti telur cheese, roti sardin, roti khawin, roti boom, roti boom kaya, "
                "roti tissue, roti pisang, roti pisang cheese, roti planta, roti cheese, "
                "roti bawang, roti jantan, roti special, roti special double, roti milo, "
                "roti kaya, roti bakar, roti bakar kaya, roti bakar cheese, "
                "murtabak ayam, murtabak daging, murtabak kambing, "
                "naan biasa, naan cheese, naan garlic, naan butter, naan butter garlic, "
                "naan cheese garlic, naan cheese double, naan mozzerella cheese, "
                "naan mumtaj, naan tajmahal, "
                "nasi ayam, nasi ayam bawang, nasi ayam sayur, nasi ayam bawang sayur, "
                "nasi ayam rendang, nasi putih, nasi daging, nasi lemak bungkus, "
                "briyani ayam, briyani ayam bawang, briyani ayam bawang set, "
                "briyani ayam goreng set, briyani kambing, briyani kambing set, "
                "briyani daging set, briyani lamb shank, "
                "nasi goreng kampung, nasi goreng biasa, nasi goreng mamak, "
                "nasi goreng pattaya, nasi goreng seafood, nasi goreng ayam, "
                "maggi goreng, maggi goreng mamak, maggi goreng basa, maggi goreng ayam, "
                "maggi goreng daging, maggi goreng kambing, maggi goreng telur mata, "
                "maggi tomyam, maggi sup, "
                "mee goreng, mee goreng mamak, mee goreng ayam, mee goreng daging, "
                "mee goreng seafood, mee goreng telur mata, mee campur bihun, "
                "mee rebus, mee sup, "
                "bihun goreng, bihun goreng mamak, bihun goreng telur mata, bihun sup, "
                "kuey teow goreng, kuey teow goreng mamak, kuey teow goreng basa, "
                "kuey teow tomyam, "
                "indomee goreng, indomee double, indomee kosong, "
                "kambing mysur, ayam goreng, ayam bawang, ayam tandoori, "
                "ayam rendang, ayam kari, daging rendang, "
                "milo ais, milo panas, teh tarik, teh ais, kopi ais, kopi panas, "
                "bandung, bandung ais, bandung panas, sirap ais, sirap panas, "
                "barli ais, barli panas, air kosong, air mineral, cincau, longan, "
                "tambah, kurang, pedas, manis, satu, dua, tiga, empat, lima, "
                "enam, tujuh, lapan, sembilan, sepuluh, itu saja, terima kasih, "
                "kurang manis, kurang ais, tak nak biji, tak nak sayur, tak nak sambal, "
                "tak nak pedas, tambah telur, tambah sambal, kaw, kow, pekat, cair, "
                "garing, lembut, panas, suam, besar, kecil, tabur, dinosaur, kosong, "
                "tarik, double, extra, lebih, sikit, banyak, tanpa, pedas gila, crispy, "
                "well done, setengah masak, tak nak bawang, tak nak cili, tak nak kuah, "
                "kering, tak nak kacang, tak nak timun"
            )
        )
    print(f"[Whisper] Transcribed: {transcript.text}")
    return transcript.text

def _build_menu_list() -> str:
    """Build a flat menu list string from the MENU dict for the system prompt."""
    lines = []
    for name, item in MENU.items():
        lines.append(f"- {name} (RM{item['price']:.2f})")
    return "\n".join(lines)

# DeepSeek extraction-only system prompt — no conversation, no Aisha personality
DEEPSEEK_EXTRACT_SYSTEM = "Extract menu items and quantities from Malay text. Return ONLY JSON array: [{\"item\": \"exact menu name\", \"qty\": number, \"modifiers\": []}]. No conversation."


def fuzzy_match_menu_item(item_text: str) -> list:
    """
    Fuzzy-match a text string to one or more MENU items.
    Handles partial names (e.g. 'min bandung' -> 'bandung') and compound
    inputs (e.g. 'sirap ais barli' -> ['sirap ais', 'barli ais']).
    Returns a list of matched menu keys.
    """
    item_text = item_text.lower().strip()

    # Exact match
    if item_text in MENU:
        return [item_text]

    # Phase 1: Greedy substring matching — find all MENU keys within item_text
    length = len(item_text)
    used = [False] * length
    matches = []

    for key in _SORTED_KEYS:
        klen = len(key)
        start = 0
        while start <= length - klen:
            idx = item_text.find(key, start)
            if idx == -1:
                break
            if not any(used[idx:idx + klen]):
                matches.append(key)
                for i in range(idx, idx + klen):
                    used[i] = True
                start = idx + klen
            else:
                start = idx + 1

    # Phase 2: For remaining unmatched words, try prefix matching
    # e.g. "barli" leftover -> matches "barli ais" (shortest prefix match)
    remaining_words = []
    current_word = []
    for i in range(length):
        if not used[i]:
            if item_text[i] != ' ':
                current_word.append(item_text[i])
            else:
                if current_word:
                    remaining_words.append("".join(current_word))
                    current_word = []
        else:
            if current_word:
                remaining_words.append("".join(current_word))
                current_word = []
    if current_word:
        remaining_words.append("".join(current_word))

    for word in remaining_words:
        if len(word) >= 3:
            candidates = [k for k in _SORTED_KEYS if k.startswith(word + " ") or k == word]
            if candidates:
                best = min(candidates, key=len)
                if best not in matches:
                    matches.append(best)

    if matches:
        return matches

    # Phase 3: item_text is contained within a MENU key
    for key in _SORTED_KEYS:
        if item_text in key:
            return [key]

    return []


# Telegram Bot Configuration — strictly from environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CASHIER_CHAT_ID = os.environ.get("CASHIER_CHAT_ID", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")

if not BOT_TOKEN:
    print("⚠️ TELEGRAM_BOT_TOKEN is not set! Telegram notifications will not work.")
if not CASHIER_CHAT_ID:
    print("⚠️ CASHIER_CHAT_ID is not set! Order notifications will not be sent.")
if not OWNER_CHAT_ID:
    print("⚠️ OWNER_CHAT_ID is not set! Owner will not receive notifications.")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Startup diagnostic: show configured Telegram recipients
print(f"[Telegram Config] BOT_TOKEN: {'SET ✅' if BOT_TOKEN else 'NOT SET ❌'}")
print(f"[Telegram Config] CASHIER_CHAT_ID: {CASHIER_CHAT_ID if CASHIER_CHAT_ID else 'NOT SET ❌'}")
print(f"[Telegram Config] OWNER_CHAT_ID: {OWNER_CHAT_ID if OWNER_CHAT_ID else 'NOT SET ❌'}")
if CASHIER_CHAT_ID and OWNER_CHAT_ID and CASHIER_CHAT_ID == OWNER_CHAT_ID:
    print("[Telegram Config] ⚠️ CASHIER_CHAT_ID and OWNER_CHAT_ID are the SAME — owner will NOT receive duplicate messages")

app = FastAPI(title="Khulafa Bistro API")

# Mount audio files for Aisha voice system
if os.path.exists("static/audio"):
    app.mount("/audio", StaticFiles(directory="static/audio"), name="audio")


# Auto-run database migration on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database and run migrations on startup, then start Telegram bot"""
    # First, initialize the database (creates base tables + menu items)
    try:
        print("Initializing database...")
        import init_db
        init_db.init_database()
        print("Database initialized!")
    except Exception as e:
        print(f"Database initialization error: {e}")

    # Then run migrations (adds columns, extra tables, seed data)
    try:
        print("Running database migration...")
        import migrate_database
        migrate_database.migrate_database()
        print("Migration completed!")
    except Exception as e:
        print(f"Migration error (may already be done): {e}")

    try:
        print("Running voice tables migration...")
        import migrate_add_tables
        migrate_add_tables.migrate()
        print("Voice tables migration completed!")
    except Exception as e:
        print(f"Voice tables migration error (may already be done): {e}")

    # Start Telegram bot in background thread for button handling
    try:
        print("🚀 Starting Telegram bot in background...")
        bot_thread = Thread(target=run_telegram_bot, daemon=True)
        bot_thread.start()
        print("✅ Telegram bot started!")
    except Exception as e:
        print(f"❌ Error starting Telegram bot: {e}")

# CORS - Allow Telegram Mini App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve frontend directly
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

@app.get("/static/index.html")
def read_index():
    return FileResponse("static/index.html")

# Create uploads directory
if not os.path.exists("uploads"):
    os.makedirs("uploads")

# Database helper
def get_db():
    conn = sqlite3.connect('khulafa_bistro.db')
    conn.row_factory = sqlite3.Row
    return conn

# Pydantic Models
class MenuItem(BaseModel):
    id: int
    name: str
    category: str
    price: float
    available: bool

class OrderItem(BaseModel):
    menu_item_id: int
    quantity: int
    note: Optional[str] = None

class CreateOrder(BaseModel):
    customer_telegram_id: str
    customer_name: str
    customer_phone: str
    order_type: str
    arrival_time: Optional[str] = None
    items: List[OrderItem]

class UpdateOrderStatus(BaseModel):
    status: str

# API Endpoints

@app.get("/api/")
async def root():
    return {"message": "Khulafa Bistro API is running!"}

@app.get("/api/menu")
async def get_menu():
    """Get all menu items grouped by category"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM menu_items WHERE available = 1 ORDER BY category, name')
    items = cursor.fetchall()

    # Group by category
    menu_by_category = {}
    for item in items:
        category = item['category']
        if category not in menu_by_category:
            menu_by_category[category] = []

        menu_by_category[category].append({
            'id': item['id'],
            'name': item['name'],
            'price': item['price'],
            'available': bool(item['available'])
        })

    conn.close()
    return {"menu": menu_by_category}

@app.post("/api/orders")
async def create_order(order: CreateOrder):
    """Create a new order"""
    conn = get_db()
    cursor = conn.cursor()

    # Generate order number
    order_number = f"KB{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Calculate total price
    total_price = 0
    order_items_data = []

    for item in order.items:
        cursor.execute('SELECT price FROM menu_items WHERE id = ?', (item.menu_item_id,))
        menu_item = cursor.fetchone()
        if not menu_item:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Menu item {item.menu_item_id} not found")

        item_total = menu_item['price'] * item.quantity
        total_price += item_total
        order_items_data.append({
            'menu_item_id': item.menu_item_id,
            'quantity': item.quantity,
            'price': menu_item['price'],
            'note': item.note
        })

    # Insert order
    cursor.execute('''
        INSERT INTO orders (order_number, customer_telegram_id, customer_name, customer_phone,
                           order_type, arrival_time, total_price, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_number, order.customer_telegram_id, order.customer_name, order.customer_phone,
          order.order_type, order.arrival_time, total_price, 'pending'))

    order_id = cursor.lastrowid

    # Insert order items
    for item_data in order_items_data:
        cursor.execute('''
            INSERT INTO order_items (order_id, menu_item_id, quantity, price, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, item_data['menu_item_id'], item_data['quantity'],
              item_data['price'], item_data['note']))

    conn.commit()
    conn.close()

    # Send order to Telegram group WITH BUTTONS
    order_text = f"🆕 NEW ORDER!\n\n"
    order_text += f"Order #: {order_number}\n"
    order_text += f"Customer: {order.customer_name}\n"
    order_text += f"Phone: {order.customer_phone}\n"
    order_text += f"Type: {order.order_type}\n\n"
    order_text += f"Items:\n"
    
    conn2 = get_db()
    cursor2 = conn2.cursor()
    for item_data in order_items_data:
        cursor2.execute('SELECT name FROM menu_items WHERE id = ?', (item_data['menu_item_id'],))
        menu_name = cursor2.fetchone()
        order_text += f"• {item_data['quantity']}x {menu_name['name']} - RM{item_data['price']*item_data['quantity']:.2f}"
        if item_data.get('note'):
            order_text += f"\n  📝 Note: {item_data['note']}"
        order_text += "\n"
    conn2.close()
    
    order_text += f"\nTOTAL: RM{total_price:.2f}"
    
    # Create inline keyboard with action buttons
    inline_keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Confirm Order",
                    "callback_data": f"confirm_{order_id}"
                },
                {
                    "text": "❌ Cancel Order",
                    "callback_data": f"cancel_{order_id}"
                }
            ],
            [
                {
                    "text": "🔔 Remind Payment",
                    "callback_data": f"remind_{order_id}"
                }
            ]
        ]
    }
    
    print(f"Sending order {order_number} to Telegram...")

    # Send to cashier with action buttons
    if CASHIER_CHAT_ID:
        send_message(CASHIER_CHAT_ID, order_text, reply_markup=inline_keyboard)

    # Also send to owner if configured and different from cashier
    if OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        send_message(OWNER_CHAT_ID, order_text, reply_markup=inline_keyboard)

    return {
        "success": True,
        "order_id": order_id,
        "order_number": order_number,
        "total_price": total_price
    }

@app.get("/api/orders/{order_id}")
async def get_order(order_id: int):
    """Get order details"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()

    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")

    # Get order items
    cursor.execute('''
        SELECT oi.*, mi.name as item_name
        FROM order_items oi
        JOIN menu_items mi ON oi.menu_item_id = mi.id
        WHERE oi.order_id = ?
    ''', (order_id,))
    items = cursor.fetchall()

    conn.close()

    return {
        "order": dict(order),
        "items": [dict(item) for item in items]
    }

# NEW FEATURE: Cancel Order
@app.post("/api/orders/{order_id}/cancel")
async def cancel_order(order_id: int):
    """Cancel an order - for fake or unpaid receipts"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get order details
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Update order status to cancelled
    cursor.execute('''
        UPDATE orders 
        SET status = 'cancelled', 
            updated_at = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (order_id,))
    conn.commit()
    conn.close()
    
    # Send cancellation notice to customer
    cancel_message = f"""❌ Order Cancelled

We're sorry, but your order has been cancelled.

Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}

Reason: Payment not verified

If you believe this is an error or have already paid, please contact us directly with your payment proof.

Thank you for your understanding.
Khulafa Bistro 🌟"""
    
    try:
        send_message(order['customer_telegram_id'], cancel_message)
        print(f"✅ Cancellation notice sent to customer")
    except Exception as e:
        print(f"Error sending cancellation notice: {e}")
    
    return {"success": True, "message": "Order cancelled successfully"}

# NEW FEATURE: Remind Payment
@app.post("/api/orders/{order_id}/remind")
async def remind_payment(order_id: int):
    """Send payment reminder to customer"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    
    conn.close()
    
    # Send payment reminder to customer
    reminder_message = f"""🔔 Payment Reminder

Hi {order['customer_name']},

We noticed your order is still pending payment verification.

📋 Order Details:
Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}
Type: {order['order_type']}

⚠️ Please upload your payment receipt as soon as possible.

If you have already paid, please upload a clear screenshot of your payment confirmation in the chat.

Thank you for choosing Khulafa Bistro! 🌟"""
    
    try:
        send_message(order['customer_telegram_id'], reminder_message)
        print(f"✅ Payment reminder sent to customer")
        return {"success": True, "message": "Payment reminder sent successfully"}
    except Exception as e:
        print(f"Error sending payment reminder: {e}")
        raise HTTPException(status_code=500, detail="Failed to send reminder")

@app.post("/api/orders/{order_id}/upload_payment")
async def upload_payment_slip(order_id: int, file: UploadFile = File(...)):
    """Upload payment slip"""
    # Save file
    file_ext = file.filename.split('.')[-1]
    filename = f"payment_{order_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file_ext}"
    filepath = f"uploads/{filename}"

    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    # Update order
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE orders SET payment_slip_url = ? WHERE id = ?', (filepath, order_id))
    conn.commit()

    # Get order details
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()

    # Send payment screenshot to Telegram group
    if TELEGRAM_API and CASHIER_CHAT_ID:
        print(f"[Telegram] Sending payment photo to CASHIER: {CASHIER_CHAT_ID}")
        try:
            with open(filepath, 'rb') as photo:
                resp = requests.post(
                    f"{TELEGRAM_API}/sendPhoto",
                    data={
                        'chat_id': CASHIER_CHAT_ID,
                        'caption': f"💳 Payment Receipt\nOrder #{order['order_number']}\nCustomer: {order['customer_name']}\nTotal: RM{order['total_price']:.2f}"
                    },
                    files={'photo': photo}
                )
                result = resp.json()
                if result.get("ok"):
                    print(f"[Telegram] ✅ Payment photo sent to CASHIER ({CASHIER_CHAT_ID})")
                else:
                    print(f"[Telegram] ❌ FAILED sending photo to CASHIER ({CASHIER_CHAT_ID}): "
                          f"[{result.get('error_code', '?')}] {result.get('description', 'Unknown error')}")
        except Exception as e:
            print(f"[Telegram] ❌ Exception sending payment photo to CASHIER ({CASHIER_CHAT_ID}): {e}")

    # Also send payment photo to owner if configured and different from cashier
    if TELEGRAM_API and OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        print(f"[Telegram] Sending payment photo to OWNER: {OWNER_CHAT_ID}")
        try:
            with open(filepath, 'rb') as photo:
                resp = requests.post(
                    f"{TELEGRAM_API}/sendPhoto",
                    data={
                        'chat_id': OWNER_CHAT_ID,
                        'caption': f"💳 Payment Receipt\nOrder #{order['order_number']}\nCustomer: {order['customer_name']}\nTotal: RM{order['total_price']:.2f}"
                    },
                    files={'photo': photo}
                )
                result = resp.json()
                if result.get("ok"):
                    print(f"[Telegram] ✅ Payment photo sent to OWNER ({OWNER_CHAT_ID})")
                else:
                    print(f"[Telegram] ❌ FAILED sending photo to OWNER ({OWNER_CHAT_ID}): "
                          f"[{result.get('error_code', '?')}] {result.get('description', 'Unknown error')}")
        except Exception as e:
            print(f"[Telegram] ❌ Exception sending payment photo to OWNER ({OWNER_CHAT_ID}): {e}")

    # Send confirmation to customer
    customer_message = f"""✅ Payment Receipt Received!

Thank you for your payment!

📋 Order Details:
Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}
Type: {order['order_type']}

Your order is now being prepared! 🍳

We will notify you when it's ready.

Thank you for choosing Khulafa Bistro! 🌟"""
    
    try:
        send_message(order['customer_telegram_id'], customer_message)
        print(f"Confirmation sent to customer")
    except Exception as e:
        print(f"Error sending customer confirmation: {e}")

    return {"success": True, "filepath": filepath, "message": "Payment received! You will be notified when your order is ready."}

@app.get("/api/settings/{key}")
async def get_setting(key: str):
    """Get a setting value"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="Setting not found")

    return {"key": key, "value": result['value']}

@app.put("/api/settings/{key}")
async def update_setting(key: str, value: str):
    """Update a setting value"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

    return {"success": True, "key": key, "value": value}

@app.post("/api/orders/{order_id}/status")
async def update_order_status(order_id: int, update: UpdateOrderStatus):
    """Update order status"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                   (update.status, order_id))
    conn.commit()

    # Get order details
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()

    # Send notification to customer
    if order:
        send_customer_notification(order['customer_telegram_id'], order, update.status)

    return {"success": True}

@app.post("/api/orders/{order_id}/confirm_payment")
async def confirm_payment(order_id: int):
    """Confirm payment"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE orders SET payment_confirmed = 1 WHERE id = ?', (order_id,))
    conn.commit()
    conn.close()

    return {"success": True}

# Telegram Helper Functions
def send_message(chat_id, text, reply_markup=None):
    """Send a Telegram message"""
    if not BOT_TOKEN:
        print("❌ Cannot send Telegram message: TELEGRAM_BOT_TOKEN not set")
        return None
    if not chat_id:
        print("❌ Cannot send Telegram message: chat_id is empty")
        return None

    # Identify which recipient this is for
    recipient_label = "unknown"
    if str(chat_id) == str(CASHIER_CHAT_ID):
        recipient_label = "CASHIER"
    elif str(chat_id) == str(OWNER_CHAT_ID):
        recipient_label = "OWNER"
    else:
        recipient_label = "CUSTOMER"

    print(f"[Telegram] Sending to {recipient_label}: {chat_id}")

    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(url, json=payload)
        result = response.json()
        if result.get("ok"):
            print(f"[Telegram] ✅ Message sent successfully to {recipient_label} ({chat_id})")
        else:
            error_code = result.get("error_code", "?")
            description = result.get("description", "Unknown error")
            print(f"[Telegram] ❌ FAILED to send to {recipient_label} ({chat_id}): [{error_code}] {description}")
            if error_code == 403:
                print(f"[Telegram] ⚠️ Bot was blocked or /start was never sent by chat_id {chat_id}. "
                      f"The user must send /start to the bot first!")
        return result
    except Exception as e:
        print(f"[Telegram] ❌ Exception sending to {recipient_label} ({chat_id}): {e}")
        return None

def send_customer_notification(customer_telegram_id: str, order, status: str):
    """Send status update to customer"""
    status_messages = {
        "preparing": "🍳 Your order is being prepared!",
        "ready": "✅ Your order is ready!",
        "completed": "✅ Order completed. Thank you!"
    }

    message = status_messages.get(status, f"Status updated: {status}")
    message += f"\n\nOrder: {order['order_number']}"
    message += f"\nTotal: RM {order['total_price']:.2f}"

    if status == "ready":
        if order['order_type'] == "pickup":
            message += "\n\n📍 Please come to collect your order!"
        else:
            message += "\n\n🍽️ Your table is ready! Please come in!"

    send_message(customer_telegram_id, message)

# Telegram Bot Handler for Buttons
async def handle_telegram_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks from Telegram group"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    print(f"🔘 Button clicked: {callback_data}")
    
    try:
        action, order_id = callback_data.split('_')
        order_id = int(order_id)
        
        if action == "cancel":
            print(f"Cancelling order {order_id}...")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
            order = cursor.fetchone()
            
            if order:
                cursor.execute('UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', 
                             ('cancelled', order_id))
                conn.commit()
                conn.close()
                
                # Notify customer
                cancel_msg = f"""❌ Order Cancelled

We're sorry, your order has been cancelled.

Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}

Reason: Payment not verified

Please contact us if you have questions.
Khulafa Bistro 🌟"""
                
                send_message(order['customer_telegram_id'], cancel_msg)
                await query.edit_message_text(text=f"{query.message.text}\n\n❌ ORDER CANCELLED ❌\nCustomer notified.")
                print(f"✅ Order {order_id} cancelled")
        
        elif action == "remind":
            print(f"Sending reminder for order {order_id}...")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
            order = cursor.fetchone()
            conn.close()
            
            if order:
                reminder_msg = f"""🔔 Payment Reminder

Hi {order['customer_name']},

Your order is pending payment verification.

Order #: {order['order_number']}
Total: RM{order['total_price']:.2f}

⚠️ Please upload your payment receipt ASAP.

Thank you!
Khulafa Bistro 🌟"""
                
                send_message(order['customer_telegram_id'], reminder_msg)
                await query.edit_message_text(text=f"{query.message.text}\n\n🔔 REMINDER SENT ✅\nCustomer reminded.")
                print(f"✅ Reminder sent for order {order_id}")
        
        elif action == "confirm":
            print(f"Confirming order {order_id}...")
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE orders SET payment_confirmed = 1 WHERE id = ?', (order_id,))
            conn.commit()
            conn.close()
            
            await query.edit_message_text(text=f"{query.message.text}\n\n✅ ORDER CONFIRMED ✅\nPayment verified.")
            print(f"✅ Order {order_id} confirmed")
    
    except Exception as e:
        print(f"❌ Error handling button: {e}")
        await query.edit_message_text(text=f"{query.message.text}\n\n⚠️ Error: {str(e)}")

# Run Telegram Bot in Background
def run_telegram_bot():
    """Run Telegram bot to handle button clicks"""
    if not BOT_TOKEN:
        print("❌ Cannot start Telegram bot: TELEGRAM_BOT_TOKEN not set")
        return

    async def start_bot():
        try:
            application = Application.builder().token(BOT_TOKEN).build()
            application.add_handler(CallbackQueryHandler(handle_telegram_buttons))
            print("🤖 Telegram bot started - Ready to handle button clicks!")
            # Use stop_signals=None to avoid signal handler issues in background thread
            await application.initialize()
            await application.start()
            await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            # Keep running
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            print(f"❌ Bot error: {e}")

    # Run in new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot())

# ========== Cached Menu for Fast Frontend Load ==========

@app.get("/api/menu/voice")
async def get_voice_menu():
    """Return full menu dict for frontend caching. Called once on app load."""
    return {
        "menu": {name: {"price": item["price"]} for name, item in MENU.items()},
        "categories": _build_menu_categories(),
    }

def _build_menu_categories():
    """Group menu items by category prefix for display."""
    cats = {}
    for name, item in MENU.items():
        prefix = name.split()[0].upper()
        if prefix not in cats:
            cats[prefix] = []
        cats[prefix].append({"name": name, "price": item["price"]})
    return cats

# ========== Voice QR Ordering Routes ==========

class VoiceOrderItem(BaseModel):
    name: str
    quantity: int
    price: float
    modifiers: List[str] = []

class VoiceSubmitOrder(BaseModel):
    table_number: str
    items: List[VoiceOrderItem]
    total: float

@app.get("/table/{table_number}")
async def serve_voice_page(table_number: str):
    """Verify table exists and serve voice ordering page."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM restaurant_tables WHERE table_number = ?', (table_number,))
    table = cursor.fetchone()
    conn.close()

    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    return FileResponse("static/voice.html")

@app.post("/api/voice/chat")
async def voice_chat(request: Request):
    """
    SPEED-OPTIMIZED PIPELINE — No conversation, extraction only.
    Voice → Whisper STT → DeepSeek extraction (JSON) → Display order instantly.
    Non-ordering intents (confirm, cancel) handled locally — ZERO API calls.
    """
    import json as json_lib
    import re
    import time

    t0 = time.time()

    body = await request.json()
    speech = body.get("message", "")
    alternatives = body.get("alternatives", [])
    current_order = body.get("order", [])
    table = body.get("table_number", "T01")

    from order_engine import MENU, AUDIO_RESPONSES, END_PHRASES, MALAY_NUMBERS

    speech_lower = speech.lower().strip()

    # ── LOCAL INTENT DETECTION — No LLM needed ──

    # 1. Confirm / end-of-order
    from order_engine import END_PHRASES as _end
    for phrase in _end:
        if phrase in speech_lower:
            if not current_order:
                return {"action": "no_items", "new_items": [], "order": [], "total": 0, "ms": _ms(t0)}
            total = sum(i["price"] * i["qty"] for i in current_order)
            return {"action": "confirm_order", "new_items": [], "order": current_order, "total": total, "ms": _ms(t0)}

    # 2. Cancel all
    if re.search(r'\b(cancel\s*semua|buang\s*semua|mula\s*balik|start\s*over|batalkan\s*semua)\b', speech_lower):
        return {"action": "cancel_all", "new_items": [], "order": [], "total": 0, "ms": _ms(t0)}

    # 3. Cancel by index ("nombor 2", "yang kedua")
    idx_match = re.search(r'(?:nombor|number|item|yang)\s*(?:ke)?(\d+|satu|dua|tiga|empat|lima)', speech_lower)
    if idx_match and re.search(r'\b(cancel|batal|buang|remove|tak\s*nak)\b', speech_lower):
        malay_ord = {"satu": 0, "dua": 1, "tiga": 2, "empat": 3, "lima": 4}
        val = idx_match.group(1)
        cancel_index = malay_ord.get(val, int(val) - 1 if val.isdigit() else None)
        updated = list(current_order)
        if cancel_index is not None and 0 <= cancel_index < len(updated):
            updated.pop(cancel_index)
        total = sum(i["price"] * i["qty"] for i in updated)
        return {"action": "cancel_by_index", "cancel_index": cancel_index, "new_items": [], "order": updated, "total": total, "ms": _ms(t0)}

    # 4. Cancel specific item
    cancel_match = re.search(r'\b(?:cancel|batal|buang|remove|tak\s*nak)\s+(.+)', speech_lower)
    if cancel_match:
        remove_name = cancel_match.group(1).strip()
        updated = [i for i in current_order if remove_name not in i["name"].lower()]
        total = sum(i["price"] * i["qty"] for i in updated)
        return {"action": "cancel_item", "remove_item": remove_name, "new_items": [], "order": updated, "total": total, "ms": _ms(t0)}

    # 5. General cancel request
    if re.search(r'\b(cancel|batal|buang|remove)\b', speech_lower):
        return {"action": "cancel_request", "new_items": [], "order": current_order, "total": sum(i["price"] * i["qty"] for i in current_order), "ms": _ms(t0)}

    # 6. Greeting (no LLM needed)
    if re.search(r'\b(hi|hello|helo|hey|assalamualaikum|salam|selamat)\b', speech_lower) and not any(k in speech_lower for k in MENU):
        return {"action": "greeting", "new_items": [], "order": current_order, "total": sum(i["price"] * i["qty"] for i in current_order), "ms": _ms(t0)}

    # ── STEP 1: Try local rule-based extraction first (instant, zero cost) ──
    engine = get_engine()
    local_result = engine.process(speech, current_order)

    if local_result["action"] == "add_items" and local_result["new_items"]:
        # Local engine matched — skip DeepSeek entirely
        local_result["ms"] = _ms(t0)
        local_result["pipeline"] = "local"
        print(f"[SPEED] Local extraction: {_ms(t0)}ms")
        return local_result

    # ── STEP 2: DeepSeek extraction — JSON only, no conversation ──
    deepseek_client = get_deepseek_client()
    if not deepseek_client:
        # No DeepSeek configured — return local result as-is
        local_result["ms"] = _ms(t0)
        local_result["pipeline"] = "local-only"
        return local_result

    menu_list_str = "\n".join([f"- {name} (RM{item['price']:.2f})" for name, item in MENU.items()])

    # Build speech alternatives section
    alt_section = ""
    if alternatives and len(alternatives) > 1:
        alt_text = " | ".join([
            f'"{a["text"]}"' if isinstance(a, dict) else f'"{a}"'
            for a in alternatives[:5]
        ])
        alt_section = f"\nAlternatives: {alt_text}"

    user_prompt = f"""MENU:
{menu_list_str}

MISHEARINGS: magic/main/man=maggi, going/goring=goreng, queen teow/key toe=kuey teow, roti canal/channel=roti canai, the tarik/tea tarik=teh tarik, copy/coffee=kopi, my low/mellow=milo, banding/bandong=bandung, sir up/serap=sirap, barley/bali=barli, chin chow=cincau, martabak=murtabak, biryani/beriani=briyani, bee hun/mihun=bihun, indo mee/indomie=indomee, running/rending=rendang, camping/coming=kambing
DEFAULTS: milo→milo ais, kopi→kopi panas, barli→barli ais, sirap→sirap ais, teh→teh tarik
NUMBERS: satu=1,dua=2,tiga=3,empat=4,lima=5,enam=6,tujuh=7,lapan=8,sembilan=9,sepuluh=10
MODIFIERS: kurang manis,kaw,garing,pedas,tambah telur,tak nak sayur,etc → capture in modifiers array

Customer: "{speech}"{alt_section}"""

    try:
        ds_response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=200,
            temperature=0,
            messages=[
                {"role": "system", "content": DEEPSEEK_EXTRACT_SYSTEM},
                {"role": "user", "content": user_prompt}
            ]
        )

        ds_raw = ds_response.choices[0].message.content.strip()
        # Parse JSON
        try:
            ds_items = json_lib.loads(ds_raw)
        except json_lib.JSONDecodeError:
            arr_match = re.search(r'\[.*\]', ds_raw, re.DOTALL)
            ds_items = json_lib.loads(arr_match.group()) if arr_match else []

        if isinstance(ds_items, dict):
            ds_items = [ds_items]

        print(f"[DeepSeek] Extracted: {ds_items} ({_ms(t0)}ms)")

    except Exception as e:
        print(f"[DeepSeek] Error: {e}")
        local_result["ms"] = _ms(t0)
        local_result["pipeline"] = "local-fallback"
        return local_result

    # ── Build order from DeepSeek extraction ──
    new_items = []
    for ds_item in ds_items:
        raw_name = ds_item.get("matched_item", ds_item.get("item", "")).lower().strip()
        qty = ds_item.get("quantity", ds_item.get("qty", 1))
        modifiers = ds_item.get("modifiers", [])
        if not raw_name:
            continue

        # Exact match
        if raw_name in MENU:
            new_items.append({"name": raw_name.title(), "qty": qty, "price": MENU[raw_name]["price"], "modifiers": modifiers})
        else:
            # Fuzzy match
            fuzzy = fuzzy_match_menu_item(raw_name)
            for matched_key in fuzzy:
                new_items.append({"name": matched_key.title(), "qty": qty, "price": MENU[matched_key]["price"], "modifiers": modifiers})

    if not new_items:
        local_result["ms"] = _ms(t0)
        local_result["pipeline"] = "deepseek-empty"
        return local_result

    # Merge into current order
    updated_order = list(current_order)
    for ni in new_items:
        existing = None
        for i in updated_order:
            if i["name"].lower() == ni["name"].lower() and i.get("modifiers", []) == ni.get("modifiers", []):
                existing = i
                break
        if existing:
            existing["qty"] += ni["qty"]
        else:
            updated_order.append(ni)

    total = sum(i["price"] * i["qty"] for i in updated_order)

    print(f"[SPEED] DeepSeek pipeline: {_ms(t0)}ms")

    return {
        "action": "add_items",
        "new_items": new_items,
        "order": updated_order,
        "total": total,
        "pipeline": "deepseek",
        "ms": _ms(t0),
    }


def _ms(t0):
    """Milliseconds since t0."""
    import time
    return round((time.time() - t0) * 1000)

@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    """
    Whisper-based server-side speech-to-text endpoint (upgrade path for scale).

    Accepts audio blob from frontend MediaRecorder, transcribes using OpenAI
    Whisper API with Malay language + food vocabulary hints, then returns the
    accurate transcript. Frontend should then call /api/voice/chat with the text.

    Usage:
      1. Frontend records audio via MediaRecorder
      2. POST audio blob to this endpoint
      3. Get back accurate Malay transcript
      4. Frontend calls /api/voice/chat with the transcript as message

    Cost: ~$0.006/min — affordable for 100+ restaurants.
    Set OPENAI_API_KEY env var to enable.
    """
    form = await request.form()
    audio_file = form.get("audio")
    table_number = form.get("table_number", "T01")

    if not audio_file:
        raise HTTPException(status_code=400, detail="No audio file provided")

    if not get_whisper_client():
        raise HTTPException(status_code=500, detail="Whisper API not configured (set OPENAI_API_KEY)")

    try:
        import io
        import tempfile
        audio_content = await audio_file.read()

        # Write to a temp file so transcribe_audio can open it by path
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_content)
            tmp_path = tmp.name

        transcribed_text = transcribe_audio(tmp_path).strip()
        os.unlink(tmp_path)

        print(f"[Whisper] Transcribed: '{transcribed_text}'")

        return {
            "text": transcribed_text,
            "table_number": table_number,
            "source": "whisper"
        }

    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"[Whisper] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Whisper transcription failed: {str(e)}")


@app.get("/api/voice/greeting")
async def voice_greeting():
    """Return time-based greeting with pre-recorded audio."""
    engine = get_engine()
    result = engine.get_greeting()
    audio_matches = [
        {"audio_path": f"/audio/wavs/{aid}.wav", "audio_exists": True}
        for aid in result["audio_ids"]
    ]
    return {
        "text": result["text"],
        "audio_matches": audio_matches,
        "has_audio": True,
    }

@app.post("/api/voice/order")
async def submit_voice_order(request: Request):
    body = await request.json()
    table = body.get("table_number", "T01")
    items = body.get("items", [])
    total = body.get("total", 0)

    if not items:
        return {"status": "error", "message": "No items"}

    # Save order to database
    conn = get_db()
    cursor = conn.cursor()
    order_number = f"KB{datetime.now().strftime('%Y%m%d%H%M%S')}"

    total_price = sum(i.get('price', 0) * i.get('qty', 1) for i in items)

    cursor.execute('''
        INSERT INTO orders (order_number, customer_telegram_id, customer_name, customer_phone,
                           order_type, total_price, status, table_number, order_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_number, 'voice_qr', f'Table {table}', '',
          'dine_in', total_price, 'pending', table, 'voice_qr'))

    order_id = cursor.lastrowid

    for i in items:
        cursor.execute('SELECT id, price FROM menu_items WHERE name = ? AND available = 1', (i['name'],))
        menu_item = cursor.fetchone()
        menu_item_id = menu_item['id'] if menu_item else 0
        item_price = menu_item['price'] if menu_item else i.get('price', 0)
        item_note = ', '.join(i.get('modifiers', [])) if i.get('modifiers') else None

        cursor.execute('''
            INSERT INTO order_items (order_id, menu_item_id, quantity, price, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, menu_item_id, i.get('qty', 1), item_price, item_note))

    conn.commit()
    conn.close()

    # Build Telegram message
    def _format_item_line(i):
        mod_str = f" ({', '.join(i['modifiers'])})" if i.get('modifiers') else ""
        return f"  • {i['name']}{mod_str} x{i.get('qty', 1)} - RM{i.get('price', 0) * i.get('qty', 1):.2f}"
    items_text = "\n".join([_format_item_line(i) for i in items])

    message = (
        f"🎤 VOICE ORDER - MEJA {table}\n"
        f"📋 Order #: {order_number}\n"
        f"⏰ {datetime.now().strftime('%I:%M %p')}\n\n"
        f"{items_text}\n\n"
        f"💰 TOTAL: RM{total_price:.2f}\n\n"
        f"➡️ Sila key into POS"
    )

    # Create inline keyboard with action buttons
    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm Order", "callback_data": f"confirm_{order_id}"},
                {"text": "❌ Cancel Order", "callback_data": f"cancel_{order_id}"}
            ],
            [
                {"text": "🔔 Remind Payment", "callback_data": f"remind_{order_id}"}
            ]
        ]
    }

    # Send to cashier using module-level BOT_TOKEN and CASHIER_CHAT_ID
    print(f"Sending voice order {order_number} to Telegram...")
    if CASHIER_CHAT_ID:
        send_message(CASHIER_CHAT_ID, message, reply_markup=inline_keyboard)

    # Send to owner if configured and different from cashier
    if OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        send_message(OWNER_CHAT_ID, message, reply_markup=inline_keyboard)

    return {"status": "sent", "table": table, "total": total_price, "order_id": order_id, "order_number": order_number}

@app.post("/api/voice/submit-order")
async def voice_submit_order(req: VoiceSubmitOrder):
    """Submit a voice order to the database and notify via Telegram."""
    conn = get_db()
    cursor = conn.cursor()

    # Verify table
    cursor.execute('SELECT * FROM restaurant_tables WHERE table_number = ?', (req.table_number,))
    table = cursor.fetchone()
    if not table:
        conn.close()
        raise HTTPException(status_code=404, detail="Table not found")

    order_number = f"KB{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Calculate total from items
    total_price = sum(item.price * item.quantity for item in req.items)

    # Insert order
    cursor.execute('''
        INSERT INTO orders (order_number, customer_telegram_id, customer_name, customer_phone,
                           order_type, total_price, status, table_number, order_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (order_number, 'voice_qr', f'Table {req.table_number}', '',
          'dine_in', total_price, 'pending', req.table_number, 'voice_qr'))

    order_id = cursor.lastrowid

    # Insert order items - match to menu items by name
    for item in req.items:
        cursor.execute('SELECT id, price FROM menu_items WHERE name = ? AND available = 1', (item.name,))
        menu_item = cursor.fetchone()
        menu_item_id = menu_item['id'] if menu_item else 0
        item_price = menu_item['price'] if menu_item else item.price
        item_note = ', '.join(item.modifiers) if item.modifiers else None

        cursor.execute('''
            INSERT INTO order_items (order_id, menu_item_id, quantity, price, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, menu_item_id, item.quantity, item_price, item_note))

    conn.commit()
    conn.close()

    # Send Telegram notification
    send_voice_order_telegram(order_id, req.table_number, req.items, total_price)

    return {"success": True, "order_id": order_id, "order_number": order_number}


def send_voice_order_telegram(order_id, table_number, items, total):
    """Send voice order notification to Telegram."""
    now = datetime.now().strftime('%H:%M %d/%m/%Y')

    items_text = ""
    for item in items:
        line_total = item.price * item.quantity
        mod_str = ""
        if hasattr(item, 'modifiers') and item.modifiers:
            mod_str = f" ({', '.join(item.modifiers)})"
        items_text += f"  • {item.name}{mod_str} x{item.quantity} - RM{line_total:.2f}\n"

    message = (
        f"🔔 TABLE {table_number} - NEW ORDER\n"
        f"⏰ {now}\n\n"
        f"Items:\n{items_text}\n"
        f"💰 TOTAL: RM{total:.2f}\n\n"
        f"Please key into POS."
    )

    # Send to cashier
    if CASHIER_CHAT_ID:
        send_message(CASHIER_CHAT_ID, message)

    # Send to owner if different
    if OWNER_CHAT_ID and OWNER_CHAT_ID != CASHIER_CHAT_ID:
        send_message(OWNER_CHAT_ID, message)


# Setup all enhanced features
setup_enhanced_routes(app)

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
