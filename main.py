from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import json
from datetime import datetime
import requests
import os
from pathlib import Path
from enhanced_routes import setup_enhanced_routes

# Telegram Bot Configuration
BOT_TOKEN = "8278423751:AAEtdsFlIQMLYXHRUh_uoFsl3g-3EdO7P78"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Khulafa Bistro API")

# Auto-run database migration on startup
@app.on_event("startup")
async def startup_event():
    """Run database migration on startup"""
    try:
        print("Running database migration...")
        import migrate_database
        migrate_database.migrate_database()
        print("Migration completed!")
        
        # Update payment QR codes
        print("Updating payment QR codes...")
        import update_qr_codes
        update_qr_codes.update_payment_qr_codes()
        print("QR codes updated!")
    except Exception as e:
        print(f"Migration error (may already be done): {e}")

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
    conn.commit()
    conn.close()

    # Send order to Telegram group
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
    
    print(f"Sending order to Telegram group...")
    send_message(-1003483753298, order_text)
    print(f"Order sent to group!")

    return {
        "success": True,
        "order_id": order_id,
        "order_number": order_number,
        "total_price": total_price
    }
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
                    'chat_id': -1003483753298,
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

# Setup all enhanced features
setup_enhanced_routes(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
