import os
import requests
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Bot configuration — strictly from environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = os.environ.get("API_URL", "https://khulafa-bistro-order.onrender.com")
KITCHEN_GROUP_ID = os.environ.get("CASHIER_CHAT_ID", "")

if not BOT_TOKEN:
    print("⚠️ TELEGRAM_BOT_TOKEN is not set! Bot will not start.")
if not KITCHEN_GROUP_ID:
    print("⚠️ CASHIER_CHAT_ID is not set! Kitchen notifications will not work.")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start is used"""
    await update.message.reply_text(
        "🌟 Welcome to Khulafa Bistro!\n\n"
        "Use our ordering system to place your order.\n\n"
        "Commands:\n"
        "/help - Show help\n"
        "/menu - View menu"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    await update.message.reply_text(
        "📱 Khulafa Bistro Order Bot\n\n"
        "How to order:\n"
        "1. Use the order bot interface\n"
        "2. Select your items\n"
        "3. Make payment\n"
        "4. Upload payment proof\n\n"
        "For assistance, please contact the restaurant directly."
    )

# Button callback handler - THIS IS THE IMPORTANT PART!
async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks from kitchen staff"""
    query = update.callback_query
    
    # Answer the callback query immediately
    await query.answer()
    
    # Get the callback data (format: "action_orderid")
    callback_data = query.data
    print(f"Button clicked: {callback_data}")
    
    try:
        action, order_id = callback_data.split('_')
        
        if action == "cancel":
            # Call API to cancel order
            print(f"Cancelling order {order_id}...")
            response = requests.post(f"{API_URL}/api/orders/{order_id}/cancel")
            
            if response.status_code == 200:
                # Update the message to show it's cancelled
                await query.edit_message_text(
                    text=f"{query.message.text}\n\n❌ ORDER CANCELLED ❌\nCustomer has been notified."
                )
                print(f"✅ Order {order_id} cancelled successfully")
            else:
                await query.edit_message_text(
                    text=f"{query.message.text}\n\n⚠️ Error cancelling order. Please try again."
                )
                print(f"❌ Error cancelling order {order_id}")
        
        elif action == "remind":
            # Call API to send payment reminder
            print(f"Sending payment reminder for order {order_id}...")
            response = requests.post(f"{API_URL}/api/orders/{order_id}/remind")
            
            if response.status_code == 200:
                # Update the message to show reminder was sent
                await query.edit_message_text(
                    text=f"{query.message.text}\n\n🔔 PAYMENT REMINDER SENT ✅\nCustomer has been reminded."
                )
                print(f"✅ Payment reminder sent for order {order_id}")
            else:
                await query.edit_message_text(
                    text=f"{query.message.text}\n\n⚠️ Error sending reminder. Please try again."
                )
                print(f"❌ Error sending reminder for order {order_id}")
        
        elif action == "confirm":
            # Call API to confirm order
            print(f"Confirming order {order_id}...")
            response = requests.post(f"{API_URL}/api/orders/{order_id}/confirm_payment")
            
            if response.status_code == 200:
                # Update the message to show it's confirmed
                await query.edit_message_text(
                    text=f"{query.message.text}\n\n✅ ORDER CONFIRMED ✅\nPayment verified."
                )
                print(f"✅ Order {order_id} confirmed successfully")
            else:
                await query.edit_message_text(
                    text=f"{query.message.text}\n\n⚠️ Error confirming order. Please try again."
                )
                print(f"❌ Error confirming order {order_id}")
    
    except Exception as e:
        print(f"Error handling button callback: {e}")
        await query.edit_message_text(
            text=f"{query.message.text}\n\n⚠️ Error: {str(e)}"
        )

def main():
    """Start the bot"""
    print("🤖 Starting Khulafa Bistro Bot...")
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Add callback query handler for buttons - THIS IS CRITICAL!
    application.add_handler(CallbackQueryHandler(handle_button_callback))
    
    # Run the bot
    print("✅ Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
