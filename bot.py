import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import sqlite3
from datetime import datetime
import requests

# Configuration
BOT_TOKEN = "8278423751:AAEtdsFlIQMLYXHRUh_uoFsl3g-3EdO7P78"
MINI_APP_URL = "https://khulafaorder.pythonanywhere.com/static/index.html"
KITCHEN_CHAT_ID = None
ADMIN_IDS = []

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database helper
def get_db():
    conn = sqlite3.connect('khulafa_bistro.db')
    conn.row_factory = sqlite3.Row
    return conn

# Command Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - Show Mini App to customers"""
    keyboard = [
        [InlineKeyboardButton("🍽️ Order Now", web_app=WebAppInfo(url=MINI_APP_URL))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌟 Welcome to Khulafa Bistro! 🌟\n\n"
        "Click the button below to browse our menu and place your order!",
        reply_markup=reply_markup
    )

async def kitchen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /kitchen command - Kitchen dashboard"""
    global KITCHEN_CHAT_ID
    KITCHEN_CHAT_ID = update.effective_chat.id
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM orders 
        WHERE status IN ('pending', 'preparing') 
        ORDER BY created_at ASC
    ''')
    orders = cursor.fetchall()
    
    if not orders:
        await update.message.reply_text("✅ No pending orders!")
        conn.close()
        return
    
    for order in orders:
        await send_kitchen_order_card(update.effective_chat.id, order, context)
    
    conn.close()

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command - Admin menu"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("📊 View Orders", callback_data="admin_orders")],
        [InlineKeyboardButton("📈 Sales Report", callback_data="admin_sales")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👨‍💼 *Admin Panel*\n\nChoose an option:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /orders command - View all orders"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM orders 
        ORDER BY created_at DESC 
        LIMIT 10
    ''')
    orders = cursor.fetchall()
    
    if not orders:
        await update.message.reply_text("No orders yet!")
        conn.close()
        return
    
    message = "📋 *Recent Orders*\n\n"
    
    for order in orders:
        status_emoji = {
            'pending': '⏳',
            'preparing': '🍳',
            'ready': '✅',
            'completed': '✔️'
        }.get(order['status'], '❓')
        
        message += f"{status_emoji} *{order['order_number']}*\n"
        message += f"   Type: {order['order_type']}\n"
        message += f"   Total: RM {order['total_price']:.2f}\n"
        message += f"   Status: {order['status']}\n"
        if order['arrival_time']:
            message += f"   Arrival: {order['arrival_time']}\n"
        message += "\n"
    
    conn.close()
    await update.message.reply_text(message, parse_mode="Markdown")

# Callback Handlers

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("mark_ready_"):
        order_id = int(data.split("_")[2])
        await mark_order_ready(query, order_id)
    
    elif data.startswith("confirm_payment_"):
        order_id = int(data.split("_")[2])
        await confirm_payment(query, order_id)
    
    elif data == "admin_orders":
        await show_admin_orders(query)
    
    elif data == "admin_sales":
        await show_sales_report(query)

async def mark_order_ready(query, order_id: int):
    """Mark order as ready"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('UPDATE orders SET status = ? WHERE id = ?', ('ready', order_id))
    conn.commit()
    
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()
    
    status_msg = "✅ Your order is ready for collection!" if order['order_type'] == 'pickup' else "✅ Your order is ready! Please come to your table!"
    
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": order['customer_telegram_id'],
                "text": f"{status_msg}\n\nOrder: {order['order_number']}\nTotal: RM {order['total_price']:.2f}"
            }
        )
    except Exception as e:
        logger.error(f"Failed to send customer notification: {e}")
    
    await query.edit_message_text(
        f"✅ Order {order['order_number']} marked as READY!\n"
        f"Customer has been notified."
    )

async def confirm_payment(query, order_id: int):
    """Confirm payment"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE orders SET payment_confirmed = 1, status = ? WHERE id = ?', 
                   ('preparing', order_id))
    conn.commit()
    
    cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()
    
    await query.edit_message_text(
        f"✅ Payment confirmed for {order['order_number']}!\n"
        f"Order moved to kitchen queue."
    )

async def show_admin_orders(query):
    """Show orders to admin"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as total FROM orders')
    total = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as pending FROM orders WHERE status = 'pending'")
    pending = cursor.fetchone()['pending']
    
    cursor.execute("SELECT COUNT(*) as ready FROM orders WHERE status = 'ready'")
    ready = cursor.fetchone()['ready']
    
    cursor.execute("SELECT SUM(total_price) as revenue FROM orders WHERE payment_confirmed = 1")
    revenue_row = cursor.fetchone()
    revenue = revenue_row['revenue'] if revenue_row['revenue'] else 0
    
    conn.close()
    
    message = f"📊 *Order Statistics*\n\n"
    message += f"Total Orders: {total}\n"
    message += f"Pending: {pending}\n"
    message += f"Ready: {ready}\n"
    message += f"Total Revenue: RM {revenue:.2f}"
    
    await query.edit_message_text(message, parse_mode="Markdown")

async def show_sales_report(query):
    """Show sales report"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as count, SUM(total_price) as total
        FROM orders
        WHERE DATE(created_at) = DATE('now') AND payment_confirmed = 1
    ''')
    today = cursor.fetchone()
    
    cursor.execute('''
        SELECT COUNT(*) as count, SUM(total_price) as total
        FROM orders
        WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now') AND payment_confirmed = 1
    ''')
    month = cursor.fetchone()
    
    conn.close()
    
    message = f"📈 *Sales Report*\n\n"
    message += f"*Today*\n"
    message += f"Orders: {today['count'] or 0}\n"
    message += f"Revenue: RM {today['total'] or 0:.2f}\n\n"
    message += f"*This Month*\n"
    message += f"Orders: {month['count'] or 0}\n"
    message += f"Revenue: RM {month['total'] or 0:.2f}"
    
    await query.edit_message_text(message, parse_mode="Markdown")

async def send_kitchen_order_card(chat_id: int, order, context):
    """Send order card to kitchen"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT oi.quantity, oi.note, mi.name
        FROM order_items oi
        JOIN menu_items mi ON oi.menu_item_id = mi.id
        WHERE oi.order_id = ?
    ''', (order['id'],))
    items = cursor.fetchall()
    conn.close()
    
    order_type_emoji = "📦" if order['order_type'] == 'pickup' else "🍽️"
    order_type_text = "PICKUP" if order['order_type'] == 'pickup' else "DINE-IN"
    
    message = f"🔔 *NEW ORDER*\n\n"
    message += f"{order_type_emoji} *{order_type_text}*\n"
    message += f"Order: *{order['order_number']}*\n"
    message += f"Customer: {order['customer_name']}\n"
    message += f"Phone: {order['customer_phone']}\n"
    
    if order['arrival_time']:
        message += f"⏰ Arrival Time: {order['arrival_time']}\n"
    
    message += f"\n📝 *Items:*\n"
    for item in items:
        message += f"  {item['quantity']}x {item['name']}\n"
        if item['note']:
            message += f"     Note: _{item['note']}_\n"
    
    message += f"\n💰 Total: *RM {order['total_price']:.2f}*\n"
    
    payment_status = "✅ PAID" if order['payment_confirmed'] else "⏳ Pending"
    message += f"Payment: {payment_status}"
    
    keyboard = []
    if not order['payment_confirmed'] and order['payment_slip_url']:
        keyboard.append([InlineKeyboardButton("✅ Confirm Payment", callback_data=f"confirm_payment_{order['id']}")])
    
    if order['status'] != 'ready':
        keyboard.append([InlineKeyboardButton("✅ Mark Ready", callback_data=f"mark_ready_{order['id']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Failed to send kitchen notification: {e}")

def main():
    """Start the bot"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("kitchen", kitchen))
    application.add_handler(CommandHandler("admin", admin_menu))
    application.add_handler(CommandHandler("orders", view_orders))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()