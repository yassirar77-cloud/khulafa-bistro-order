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
import anthropic

# ========== Claude API Setup ==========
_claude_client = None

def get_claude_client():
    """Lazy-init Anthropic client."""
    global _claude_client
    if _claude_client is None:
        api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        _claude_client = anthropic.Anthropic(api_key=api_key)
    return _claude_client

def _build_menu_list() -> str:
    """Build a flat menu list string from the MENU dict for the system prompt."""
    lines = []
    for name, item in MENU.items():
        lines.append(f"- {name} (RM{item['price']:.2f})")
    return "\n".join(lines)

AISHA_SYSTEM_PROMPT = f"""You are Aisha, a restaurant order taker at Khulafa Bistro. You ONLY do these things:

RULES:
1. Extract menu item names from customer speech (even if misspelled, slang, or unclear Malay)
2. Reply with ONLY the item names and 'Ada lagi?' - nothing else
3. NEVER suggest other menu items
4. NEVER recommend anything unless customer asks 'apa sedap?' or 'recommend apa?'
5. When customer says 'tu je/cukup/dah/hantar/confirm/settle/setel/sekian', reply with ONLY: CONFIRM_ORDER
6. Keep response under 15 words maximum
7. Understand common Malay speech patterns, slang, misspellings (e.g. 'minggu ring' = 'mi goreng', 'teh o aih' = 'teh o ais', 'rotikan ai' = 'roti canai')

MENU ITEMS:
{_build_menu_list()}

RESPONSE FORMAT - Always respond in this EXACT JSON format, nothing else:

For ordering items:
{{"items": ["roti canai", "maggi goreng"], "action": "add_items", "reply": "Roti Canai dan Maggi Goreng. Ada lagi?"}}

If customer confirms order:
{{"items": [], "action": "confirm_order", "reply": "Terima kasih! Order dihantar."}}

If you cannot understand:
{{"items": [], "action": "unclear", "reply": "Maaf, boleh ulang?"}}

IMPORTANT:
- Item names in the "items" array MUST be lowercase and match the menu item names exactly when possible
- If customer orders something not on the menu, still include it in items array with best-guess name
- Always respond with valid JSON only, no extra text before or after"""

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
    import anthropic
    import json as json_lib

    body = await request.json()
    speech = body.get("message", "")
    current_order = body.get("order", [])
    table = body.get("table_number", "T01")

    # Get menu items list
    menu_names = list(MENU.keys()) if 'MENU' in dir() else []
    if not menu_names:
        from order_engine import MENU
        menu_names = list(MENU.keys())

    menu_list = ", ".join(menu_names)

    client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=80,
        system=f"""You extract food orders. Reply ONLY in JSON.

MENU: {menu_list}

RULES:
- Extract item names customer ordered from their speech
- Match to closest menu item even if misspelled
- NEVER suggest or recommend other items
- NEVER mention items customer did not say

If customer orders items, reply:
{{"items":["item1","item2"],"action":"add","reply":"Item1 dan Item2. Ada lagi?"}}

If customer says tu je/cukup/dah/hantar/confirm/settle:
{{"items":[],"action":"confirm","reply":"Terima kasih!"}}

If unclear:
{{"items":[],"action":"unclear","reply":"Maaf, boleh ulang?"}}

JSON only. No other text.""",
        messages=[{"role": "user", "content": speech}]
    )

    # Parse response
    raw = response.content[0].text.strip()
    try:
        data = json_lib.loads(raw)
    except:
        # Try to extract JSON from response
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json_lib.loads(match.group())
        else:
            data = {"items": [], "action": "unclear", "reply": "Maaf, boleh ulang?"}

    items = data.get("items", [])
    action = data.get("action", "unclear")
    reply = data.get("reply", "")

    # Look up audio for matched items
    from order_engine import MENU, AUDIO_RESPONSES
    audio_matches = []
    new_items = []

    for item_name in items:
        item_lower = item_name.lower().strip()
        if item_lower in MENU:
            menu_item = MENU[item_lower]
            audio_matches.append({"audio_path": f"/audio/wavs/{menu_item['audio_id']}.wav", "audio_exists": True})
            new_items.append({"name": item_name.title(), "qty": 1, "price": menu_item["price"]})

    # Add "ada lagi?" audio only for add action
    if action == "add" and new_items:
        audio_matches.append({"audio_path": "/audio/wavs/0043.wav", "audio_exists": True})

    # Add terima kasih audio for confirm
    if action == "confirm":
        audio_matches.append({"audio_path": "/audio/wavs/0021.wav", "audio_exists": True})

    # Update order
    updated_order = list(current_order)
    for ni in new_items:
        existing = next((i for i in updated_order if i["name"].lower() == ni["name"].lower()), None)
        if existing:
            existing["qty"] += 1
        else:
            updated_order.append(ni)

    total = sum(i["price"] * i["qty"] for i in updated_order)

    return {
        "text": reply,
        "audio_matches": audio_matches,
        "has_audio": len(audio_matches) > 0,
        "action": action,
        "new_items": new_items,
        "order": updated_order,
        "total": total
    }

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
async def voice_order(request: Request):
    """Send confirmed voice order to Telegram via httpx (async, no DB)."""
    body = await request.json()
    table_number = body.get("table_number", "T01")
    items = body.get("items", [])
    total = body.get("total", 0)

    if not items:
        return {"success": False, "error": "No items"}

    items_text = "\n".join([
        f"• {i['name']} x{i.get('quantity', i.get('qty', 1))} "
        f"- RM{i.get('price', 0) * i.get('quantity', i.get('qty', 1)):.2f}"
        for i in items
    ])

    message = (
        f"🎤 VOICE ORDER - TABLE {table_number}\n"
        f"⏰ {datetime.now().strftime('%I:%M %p')}\n\n"
        f"{items_text}\n\n"
        f"💰 TOTAL: RM{total:.2f}"
    )

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    cashier_id = os.getenv("CASHIER_CHAT_ID", CASHIER_CHAT_ID)
    owner_id = os.getenv("OWNER_CHAT_ID", OWNER_CHAT_ID)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            if cashier_id:
                resp = await client.post(url, json={"chat_id": cashier_id, "text": message})
                print(f"Telegram voice order sent to cashier: {resp.status_code}")
            if owner_id and owner_id != cashier_id:
                resp = await client.post(url, json={"chat_id": owner_id, "text": message})
                print(f"Telegram voice order sent to owner: {resp.status_code}")
    except Exception as e:
        print(f"Error sending voice order to Telegram: {e}")
        return {"success": False, "error": str(e)}

    return {"success": True, "message": message}

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
