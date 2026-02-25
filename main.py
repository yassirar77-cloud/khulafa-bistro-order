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
from order_engine import get_engine, MENU
from threading import Thread
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
import asyncio
from openai import OpenAI

# ========== Qwen3 API Setup ==========
_qwen_client = None

def get_qwen_client():
    """Lazy-init Qwen3 client (OpenAI-compatible)."""
    global _qwen_client
    if _qwen_client is None:
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_url = os.getenv("QWEN_API_URL")
        if not api_key or not base_url:
            return None
        _qwen_client = OpenAI(api_key=api_key, base_url=base_url)
    return _qwen_client

# ========== DeepSeek API Setup (Intent Extraction) ==========
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

def _build_menu_list() -> str:
    """Build a flat menu list string from the MENU dict for the system prompt."""
    lines = []
    for name, item in MENU.items():
        lines.append(f"- {name} (RM{item['price']:.2f})")
    return "\n".join(lines)

AISHA_SYSTEM_PROMPT = f"""You are Aisha, the virtual waitress at Khulafa Bistro. Your role is strictly to take orders.

STRICT RULES:
1. NEVER recommend or suggest menu items on your own
2. ONLY confirm what customer ordered and say "Ada lagi?"
3. Keep responses SHORT - max 1 sentence
4. Example: "Baiklah, mee goreng satu. Ada lagi?"
5. NEVER say "Kami ada...", "Cuba juga...", "Mungkin nak try..."
6. NEVER list menu categories or suggest promotions
7. When the customer confirms the order ("tu je" / "cukup" / "dah" / "hantar" / "confirm" / "settle" / "setel" / "sekian"), reply with ONLY: CONFIRM_ORDER
8. Understand common Malay speech patterns, slang, and misspellings
9. CRITICAL: All mee goreng, maggi goreng, bihun, kuey teow, and indomee items ARE on the menu. NEVER say they are unavailable.

MENU ITEMS:
{_build_menu_list()}

RESPONSE FORMAT — Always respond in this EXACT JSON format, nothing else:

When customer orders items:
{{"items": ["roti canai", "maggi goreng"], "action": "add_items", "reply": "Roti Canai dan Maggi Goreng. Ada lagi?"}}

When customer confirms the order:
{{"items": [], "action": "confirm_order", "reply": "Terima kasih! Pesanan sudah dihantar."}}

When you cannot understand:
{{"items": [], "action": "unclear", "reply": "Maaf, boleh ulang sekali lagi?"}}

IMPORTANT:
- Item names in the "items" array MUST be lowercase and match the menu item names exactly when possible
- If the customer orders something not on the menu, still include it in the items array with best-guess name
- Always respond with valid JSON only — no extra text before or after"""

# Telegram Bot Configuration
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8278423751:AAEtdsFlIQMLYXHRUh_uoFsl3g-3EdO7P78")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
CASHIER_CHAT_ID = os.environ.get("CASHIER_CHAT_ID", "-1003483753298")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")

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
    
    print(f"Sending order to Telegram group with action buttons...")
    
    # Send message with buttons
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": CASHIER_CHAT_ID,
        "text": order_text,
        "reply_markup": inline_keyboard
    }

    try:
        response = requests.post(url, json=payload)
        print(f"Order sent to cashier with buttons: {response.text}")
    except Exception as e:
        print(f"Error sending order: {e}")

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
    try:
        with open(filepath, 'rb') as photo:
            requests.post(
                f"{TELEGRAM_API}/sendPhoto",
                data={
                    'chat_id': CASHIER_CHAT_ID,
                    'caption': f"💳 Payment Receipt\nOrder #{order['order_number']}\nCustomer: {order['customer_name']}\nTotal: RM{order['total_price']:.2f}"
                },
                files={'photo': photo}
            )
            print(f"Payment photo sent to group")
    except Exception as e:
        print(f"Error sending payment photo: {e}")

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
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    
    try:
        response = requests.post(url, json=payload)
        print(f"Telegram response: {response.text}")
        return response.json()
    except Exception as e:
        print(f"Telegram error: {e}")
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

# ========== Voice QR Ordering Routes ==========

class VoiceOrderItem(BaseModel):
    name: str
    quantity: int
    price: float

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
    Dual AI Pipeline:
    STEP 1 - DeepSeek: Intent extraction & fuzzy menu matching from raw speech
    STEP 2 - Qwen Max: Natural Aisha conversation response

    Non-ordering messages (greetings, confirmations, cancel) skip DeepSeek
    and go straight to Qwen Max.
    """
    import json as json_lib
    import re

    body = await request.json()
    speech = body.get("message", "")
    alternatives = body.get("alternatives", [])
    current_order = body.get("order", [])
    table = body.get("table_number", "T01")

    from order_engine import MENU, AUDIO_RESPONSES

    qwen_client = get_qwen_client()
    model = os.getenv("QWEN_MODEL", "qwen-max")

    # ── Detect if this is an ordering message or a non-ordering message ──
    # Non-ordering: greetings, confirmations, cancellations, questions, etc.
    speech_lower = speech.lower().strip()

    NON_ORDER_PATTERNS = [
        # Confirmations / end-of-order
        r"\b(tu\s*je|tu\s*jer|itu\s*je|cukup|dah|sekian|confirm|settle|setel|hantar)\b",
        # Cancel / remove
        r"\b(cancel|batal|tak\s*jadi|tak\s*nak|remove|buang|padam)\b",
        # Greetings
        r"\b(hi|hello|helo|hey|assalamualaikum|salam|selamat)\b",
        # Questions about menu / recommendations
        r"\b(apa\s+yang|recommend|cadang|menu|senarai)\b",
        # Yes/No responses
        r"^(ya|yes|ok|okay|tidak|tak|no)\s*$",
        # Thank you
        r"\b(terima\s*kasih|thank|thanks|tq)\b",
    ]

    is_ordering = True
    for pattern in NON_ORDER_PATTERNS:
        if re.search(pattern, speech_lower):
            is_ordering = False
            break

    # ── STEP 1: DeepSeek Intent Extraction (only for ordering messages) ──
    deepseek_result = None

    if is_ordering:
        deepseek_client = get_deepseek_client()
        if deepseek_client:
            menu_list_str = "\n".join([f"- {name}" for name in MENU.keys()])

            # Build enhanced message with all speech alternatives
            if alternatives and len(alternatives) > 1:
                alt_text = " | ".join([
                    f'"{a["text"]}" ({a.get("confidence", 0):.0%})'
                    if isinstance(a, dict) else f'"{a}"'
                    for a in alternatives
                ])
                alt_section = f"\nSpeech recognition alternatives (use ALL to determine correct items):\n{alt_text}"
            else:
                alt_section = ""

            deepseek_prompt = f"""You are a food order extraction AI for Khulafa Bistro, a Malaysian mamak restaurant.

IMPORTANT: Customer is ordering via voice. Speech recognition may mishear words.
You will receive multiple speech alternatives — use ALL of them to determine the correct menu item.
Always match to the closest menu item. If unsure, ask customer to repeat. Never guess randomly.

Common mishearings in Malay speech recognition:
- "main"/"man"/"magic"/"major"/"mega" = "maggi"
- "going"/"goring" = "goreng"
- "camping"/"coming" = "kambing"
- "green"/"me going" = "mee goreng"
- "me"/"mi"/"mie"/"ming"/"meet"/"meer" = "mee"
- "queen teow"/"key toe"/"kway teow" = "kuey teow"
- "non"/"nun"/"nan"/"none" = "naan"
- "batu"/"batter" = "butter"
- "galic"/"gali" = "garlic"
- "aming"/"ayang"/"i am"/"eye am" = "ayam"
- "nancy"/"nan si" = "naan cheese"
- "non batu galic" = "naan butter garlic"
- "roti canal"/"roti cana"/"roti channel" = "roti canai"
- "teh tariq"/"the tarik"/"tea tarik"/"teh trick" = "teh tarik"
- "nasi lemak" = "nasi lemak bungkus"
- "mi goreng"/"mie goreng"/"minggu ring" = "mee goreng"
- "main goreng" = could be "maggi goreng" or "mee goreng" (use context to decide)
- "maggie"/"megi"/"meggi"/"mackey" = "maggi"
- "bee hun"/"bi hun"/"mihun" = "bihun"
- "kuay teow"/"koay teow"/"char kuey teow"/"kuey tiau" = "kuey teow goreng"
- "indo mee"/"indo mi"/"indomie" = "indomee"
- "die ging"/"dye ging" = "daging"
- "running"/"rending" = "rendang"
- "my sir"/"my sir" = "mysur"
- "roti channel"/"roti chenai" = "roti canai"
- "martabak" = "murtabak"
- "biryani"/"beriani" = "briyani"

NOODLE ITEMS ON MENU (these are ALL valid - never say they are unavailable):
- maggi goreng, maggi goreng mamak, maggi goreng ayam, maggi goreng daging, maggi goreng kambing
- maggi tomyam, maggi sup
- mee goreng, mee goreng mamak, mee goreng ayam, mee goreng daging, mee goreng seafood
- mee rebus, mee sup, mee campur bihun
- bihun goreng, bihun goreng mamak, bihun sup
- kuey teow goreng, kuey teow goreng mamak, kuey teow tomyam
- indomee goreng, indomee double, indomee kosong

MALAY NUMBER WORDS: satu=1, dua=2, tiga=3, empat=4, lima=5, enam=6, tujuh=7, lapan=8, sembilan=9, sepuluh=10

MENU:
{menu_list_str}

Return ONLY a JSON array of matched items. Each element:
{{"matched_item": "exact menu item name", "quantity": number, "confidence": float 0-1}}

If multiple items are ordered, return multiple elements.
If unclear but you can guess, make your best guess - do NOT return empty.
Example: [{{"matched_item": "roti canai", "quantity": 2, "confidence": 0.95}}]

Customer said: "{speech}"{alt_section}
Pick the most likely correct menu items from these alternatives."""

            try:
                ds_response = deepseek_client.chat.completions.create(
                    model="deepseek-chat",
                    max_tokens=300,
                    messages=[
                        {"role": "system", "content": "You extract structured food orders from messy speech transcripts. The customer orders via voice and speech recognition may mishear Malay food words. You receive multiple speech alternatives — use ALL of them to determine the correct menu items. Return ONLY valid JSON arrays, nothing else."},
                        {"role": "user", "content": deepseek_prompt}
                    ]
                )

                ds_raw = ds_response.choices[0].message.content.strip()
                # Parse DeepSeek JSON response
                try:
                    deepseek_result = json_lib.loads(ds_raw)
                except json_lib.JSONDecodeError:
                    # Try extracting JSON array from response
                    arr_match = re.search(r'\[.*\]', ds_raw, re.DOTALL)
                    if arr_match:
                        deepseek_result = json_lib.loads(arr_match.group())

                # Normalize to list
                if isinstance(deepseek_result, dict):
                    deepseek_result = [deepseek_result]

                print(f"[DeepSeek] Extracted: {deepseek_result}")
            except Exception as e:
                print(f"[DeepSeek] Error: {e} - falling back to Qwen-only")
                deepseek_result = None

    # ── STEP 2: Qwen Max Conversation Response ──
    if deepseek_result and is_ordering:
        # Build a structured prompt for Qwen using DeepSeek's extraction
        extracted_items = []
        for item in deepseek_result:
            name = item.get("matched_item", "")
            qty = item.get("quantity", 1)
            confidence = item.get("confidence", 0)
            if name:
                qty_str = f" x{qty}" if qty > 1 else ""
                extracted_items.append(f"{name}{qty_str} (confidence: {confidence})")

        items_summary = ", ".join(extracted_items) if extracted_items else "unclear"

        qwen_prompt = f"""You are Aisha, AI waitress for Khulafa Bistro.

STRICT RULES:
- NEVER recommend or suggest menu items on your own
- ONLY confirm what customer ordered and say "Ada lagi?"
- Keep responses SHORT - max 1 sentence
- Example: "Baiklah, mee goreng satu. Ada lagi?"
- NEVER say "Kami ada...", "Cuba juga...", "Mungkin nak try..."

The customer said: "{speech}"
Our order extraction system detected these items: {items_summary}

MENU ITEMS AVAILABLE:
{chr(10).join([f"- {name}" for name in MENU.keys()])}

TASK:
- Match the extracted items to the closest menu item names
- Confirm items in 1 short sentence + "Ada lagi?"
- IMPORTANT: If the item exists in the menu list above, NEVER say it is unavailable

RESPONSE FORMAT - Always respond in this EXACT JSON, nothing else:
{{"items": ["item1", "item2"], "quantities": [1, 2], "action": "add", "reply": "Baiklah, [items]. Ada lagi?"}}

IMPORTANT:
- "items" array = lowercase exact menu item names
- "quantities" array = quantity for each item (same order as items array)
- "action" must be "add"
- Always respond with valid JSON only"""

    else:
        # Non-ordering: greetings, confirmations, cancel etc go straight to Qwen
        qwen_prompt = f"""You are Aisha, AI waitress for Khulafa Bistro.

STRICT RULES:
- NEVER recommend or suggest menu items on your own
- ONLY confirm what customer ordered and say "Ada lagi?"
- Keep responses SHORT - max 1 sentence
- NEVER say "Kami ada...", "Cuba juga...", "Mungkin nak try..."

CURRENT ORDER: {json_lib.dumps(current_order) if current_order else "empty"}

The customer said: "{speech}"

Handle this naturally:
- Greetings: "Hai! Nak order apa?"
- Confirmations (tu je/cukup/dah/hantar/confirm/settle/setel/sekian): "Terima kasih! Pesanan sudah dihantar."
- Cancel/remove: acknowledge briefly
- Questions: answer briefly
- If ordering food, match to menu items

RESPONSE FORMAT - Always respond in this EXACT JSON, nothing else:

When customer orders items:
{{"items": ["roti canai"], "quantities": [1], "action": "add", "reply": "Baiklah, Roti Canai. Ada lagi?"}}

When customer confirms order:
{{"items": [], "quantities": [], "action": "confirm", "reply": "Terima kasih! Pesanan sudah dihantar."}}

When customer cancels:
{{"items": [], "quantities": [], "action": "cancel", "reply": "Okay, pesanan dibatalkan."}}

When greeting or unclear:
{{"items": [], "quantities": [], "action": "greeting", "reply": "your response"}}

IMPORTANT: Always respond with valid JSON only - no extra text."""

    # Build user message with structured alternatives for better accuracy
    user_msg = speech
    if alternatives:
        # Handle both new format [{text, confidence}] and legacy [string] format
        alt_parts = []
        for a in alternatives:
            if isinstance(a, dict):
                text = a.get("text", "")
                conf = a.get("confidence", 0)
                if text and text != speech:
                    alt_parts.append(f'"{text}" ({conf:.0%})')
            elif a and a != speech:
                alt_parts.append(f'"{a}"')
        if alt_parts:
            user_msg = f'{speech} (speech alternatives: {" | ".join(alt_parts)})'

    response = qwen_client.chat.completions.create(
        model=model,
        max_tokens=100,  # Short responses = faster
        messages=[
            {"role": "system", "content": qwen_prompt},
            {"role": "user", "content": user_msg}
        ],
        extra_body={"enable_thinking": False}
    )

    # Parse Qwen response
    raw = response.choices[0].message.content.strip()
    try:
        data = json_lib.loads(raw)
    except json_lib.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                data = json_lib.loads(match.group())
            except json_lib.JSONDecodeError:
                data = {"items": [], "quantities": [], "action": "unclear", "reply": "Maaf, boleh ulang?"}
        else:
            data = {"items": [], "quantities": [], "action": "unclear", "reply": "Maaf, boleh ulang?"}

    items = data.get("items", [])
    quantities = data.get("quantities", [])
    action = data.get("action", "unclear")
    reply = data.get("reply", "")

    # Pad quantities to match items length (default qty=1)
    while len(quantities) < len(items):
        quantities.append(1)

    # Look up audio and build new_items with quantities
    audio_matches = []
    new_items = []

    for idx, item_name in enumerate(items):
        item_lower = item_name.lower().strip()
        qty = quantities[idx] if idx < len(quantities) else 1
        if item_lower in MENU:
            menu_item = MENU[item_lower]
            if menu_item['audio_id']:
                audio_matches.append({"audio_path": f"/audio/wavs/{menu_item['audio_id']}.wav", "audio_exists": True})
            new_items.append({"name": item_name.title(), "qty": qty, "price": menu_item["price"]})

    # Normalize action names for frontend consistency
    if action == "add" and new_items:
        action = "add_items"
    if action == "confirm":
        action = "confirm_order"

    # Add "ada lagi?" audio for add action
    if action == "add_items" and new_items:
        audio_matches.append({"audio_path": "/audio/wavs/0043.wav", "audio_exists": True})

    # Add terima kasih audio for confirm
    if action == "confirm_order":
        audio_matches.append({"audio_path": "/audio/wavs/0021.wav", "audio_exists": True})

    # Update order
    updated_order = list(current_order)
    for ni in new_items:
        existing = next((i for i in updated_order if i["name"].lower() == ni["name"].lower()), None)
        if existing:
            existing["qty"] += ni["qty"]
        else:
            updated_order.append(ni)

    total = sum(i["price"] * i["qty"] for i in updated_order)

    # Build extracted_items list for frontend upsell checking
    extracted_items = [ni["name"].lower() for ni in new_items]

    return {
        "text": reply,
        "audio_matches": audio_matches,
        "has_audio": len(audio_matches) > 0,
        "action": action,
        "new_items": new_items,
        "extracted_items": extracted_items,
        "order": updated_order,
        "total": total,
        "pipeline": "deepseek+qwen" if (deepseek_result and is_ordering) else "qwen-only"
    }

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

    # Use OpenAI Whisper API for accurate Malay speech-to-text
    whisper_api_key = os.getenv("OPENAI_API_KEY")
    if not whisper_api_key:
        raise HTTPException(status_code=500, detail="Whisper API not configured (set OPENAI_API_KEY)")

    from order_engine import MENU

    whisper_client = OpenAI(api_key=whisper_api_key)

    # Build food vocabulary prompt to help Whisper recognize Malay food terms
    menu_items_hint = ", ".join(list(MENU.keys())[:50])
    whisper_prompt = f"Malay food order: {menu_items_hint}"

    try:
        import io
        audio_content = await audio_file.read()

        # Whisper API expects a file-like object with a name
        audio_buffer = io.BytesIO(audio_content)
        audio_buffer.name = "recording.webm"

        transcript = whisper_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_buffer,
            language="ms",
            prompt=whisper_prompt
        )

        transcribed_text = transcript.text.strip()
        print(f"[Whisper] Transcribed: '{transcribed_text}'")

        return {
            "text": transcribed_text,
            "table_number": table_number,
            "source": "whisper"
        }

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
    import httpx

    body = await request.json()
    table = body.get("table_number", "T01")
    items = body.get("items", [])
    total = body.get("total", 0)

    if not items:
        return {"status": "error", "message": "No items"}

    items_text = "\n".join([f"  • {i['name']} x{i['qty']} - RM{i['price'] * i['qty']:.2f}" for i in items])

    message = f"""🎤 VOICE ORDER - MEJA {table}
⏰ {datetime.now().strftime('%I:%M %p')}

{items_text}

💰 TOTAL: RM{total:.2f}

➡️ Sila key into POS"""

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    cashier_id = os.getenv("CASHIER_CHAT_ID")
    owner_id = os.getenv("OWNER_CHAT_ID")

    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            r1 = await client.post(url, json={"chat_id": cashier_id, "text": message})
            print(f"Telegram cashier: {r1.status_code} {r1.text}")

            if owner_id and str(owner_id) != str(cashier_id):
                r2 = await client.post(url, json={"chat_id": owner_id, "text": message})
                print(f"Telegram owner: {r2.status_code} {r2.text}")
    except Exception as e:
        print(f"Telegram error: {e}")
        return {"status": "error", "message": str(e)}

    return {"status": "sent", "table": table, "total": total}

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

        cursor.execute('''
            INSERT INTO order_items (order_id, menu_item_id, quantity, price)
            VALUES (?, ?, ?, ?)
        ''', (order_id, menu_item_id, item.quantity, item_price))

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
        items_text += f"  • {item.name} x{item.quantity} - RM{line_total:.2f}\n"

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
