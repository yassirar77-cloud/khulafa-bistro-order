"""
Enhanced API Endpoints for Khulafa Order Bot
Add these endpoints to your main.py file
"""

from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
from datetime import datetime, timedelta
import json

# ============================================
# PYDANTIC MODELS
# ============================================

class PromoCodeValidate(BaseModel):
    code: str
    order_total: Optional[float] = 0

class PromoCodeCreate(BaseModel):
    code: str
    discount_percentage: int
    min_order_amount: float = 0
    max_uses: Optional[int] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None

class OrderItemWithNote(BaseModel):
    menu_item_id: int
    quantity: int
    note: Optional[str] = None

class EnhancedOrderCreate(BaseModel):
    customer_telegram_id: str
    customer_name: str
    customer_phone: str
    order_type: str
    arrival_time: Optional[str] = None
    payment_method: str = "maybank"
    promo_code: Optional[str] = None
    items: List[OrderItemWithNote]

class OrderStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None

class PaymentMethodUpdate(BaseModel):
    method_name: str
    qr_code_url: str

# ============================================
# DATABASE HELPER FUNCTIONS
# ============================================

def get_db_connection():
    conn = sqlite3.connect('khulafa_bistro.db')
    conn.row_factory = sqlite3.Row
    return conn

def calculate_estimated_time(items):
    """Calculate estimated preparation time based on items"""
    time_map = {
        'AIR TIN': 2,
        'NASI': 15,
        'MIE': 12,
        'AYAM': 20,
        'IKAN': 18,
        'KAMBING': 25,
    }
    
    max_time = 10  # default
    
    conn = get_db_connection()
    for item in items:
        menu_item = conn.execute(
            'SELECT category FROM menu_items WHERE id = ?', 
            (item.menu_item_id,)
        ).fetchone()
        
        if menu_item:
            category = menu_item['category'].upper()
            for key, time in time_map.items():
                if key in category:
                    max_time = max(max_time, time)
    
    conn.close()
    return max_time

# ============================================
# PROMO CODE ENDPOINTS
# ============================================

def setup_promo_endpoints(app: FastAPI):
    
    @app.post("/api/promo/validate")
    async def validate_promo_code(promo: PromoCodeValidate):
        """Validate a promo code"""
        conn = get_db_connection()
        
        try:
            # Get promo code details
            promo_data = conn.execute("""
                SELECT * FROM promo_codes 
                WHERE UPPER(code) = UPPER(?) AND is_active = 1
            """, (promo.code,)).fetchone()
            
            if not promo_data:
                raise HTTPException(status_code=404, detail="Invalid promo code")
            
            # Check if expired
            if promo_data['valid_until']:
                valid_until = datetime.fromisoformat(promo_data['valid_until'])
                if datetime.now() > valid_until:
                    raise HTTPException(status_code=400, detail="Promo code has expired")
            
            # Check if not yet valid
            if promo_data['valid_from']:
                valid_from = datetime.fromisoformat(promo_data['valid_from'])
                if datetime.now() < valid_from:
                    raise HTTPException(status_code=400, detail="Promo code not yet valid")
            
            # Check minimum order amount
            if promo.order_total < promo_data['min_order_amount']:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Minimum order amount is RM {promo_data['min_order_amount']}"
                )
            
            # Check max uses
            if promo_data['max_uses']:
                if promo_data['current_uses'] >= promo_data['max_uses']:
                    raise HTTPException(status_code=400, detail="Promo code usage limit reached")
            
            return {
                "valid": True,
                "code": promo_data['code'],
                "discount": promo_data['discount_percentage'],
                "message": f"{promo_data['discount_percentage']}% discount applied!"
            }
            
        finally:
            conn.close()
    
    @app.post("/api/promo/create")
    async def create_promo_code(promo: PromoCodeCreate):
        """Create a new promo code (admin only)"""
        conn = get_db_connection()
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO promo_codes 
                (code, discount_percentage, min_order_amount, max_uses, valid_from, valid_until)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                promo.code.upper(),
                promo.discount_percentage,
                promo.min_order_amount,
                promo.max_uses,
                promo.valid_from,
                promo.valid_until
            ))
            conn.commit()
            
            return {
                "success": True,
                "message": f"Promo code {promo.code} created successfully"
            }
            
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Promo code already exists")
        finally:
            conn.close()
    
    @app.get("/api/promo/list")
    async def list_promo_codes():
        """List all active promo codes"""
        conn = get_db_connection()
        
        try:
            promos = conn.execute("""
                SELECT code, discount_percentage, min_order_amount, 
                       max_uses, current_uses, valid_until
                FROM promo_codes 
                WHERE is_active = 1
                ORDER BY discount_percentage DESC
            """).fetchall()
            
            return [dict(promo) for promo in promos]
            
        finally:
            conn.close()

# ============================================
# ENHANCED ORDER ENDPOINTS
# ============================================

def setup_order_endpoints(app: FastAPI):
    
    @app.post("/api/orders")
    async def create_enhanced_order(order: EnhancedOrderCreate):
        """Create order with promo code and notes support"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Calculate totals
            subtotal = 0
            for item in order.items:
                menu_item = conn.execute(
                    'SELECT price FROM menu_items WHERE id = ?', 
                    (item.menu_item_id,)
                ).fetchone()
                
                if menu_item:
                    subtotal += menu_item['price'] * item.quantity
            
            # Apply promo code if provided
            discount_amount = 0
            if order.promo_code:
                promo = conn.execute("""
                    SELECT * FROM promo_codes 
                    WHERE UPPER(code) = UPPER(?) AND is_active = 1
                """, (order.promo_code,)).fetchone()
                
                if promo:
                    if subtotal >= promo['min_order_amount']:
                        discount_amount = (subtotal * promo['discount_percentage']) / 100
                        
                        # Increment promo usage
                        cursor.execute("""
                            UPDATE promo_codes 
                            SET current_uses = current_uses + 1 
                            WHERE code = ?
                        """, (order.promo_code,))
            
            total_price = subtotal - discount_amount
            
            # Calculate estimated time
            estimated_time = calculate_estimated_time(order.items)
            
            # Generate order number
            order_number = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Insert order
            cursor.execute("""
                INSERT INTO orders (
                    order_number, customer_telegram_id, customer_name, 
                    customer_phone, order_type, arrival_time, 
                    total_price, status, payment_method, promo_code,
                    discount_amount, estimated_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order_number,
                order.customer_telegram_id,
                order.customer_name,
                order.customer_phone,
                order.order_type,
                order.arrival_time,
                total_price,
                'pending',
                order.payment_method,
                order.promo_code,
                discount_amount,
                estimated_time
            ))
            
            order_id = cursor.lastrowid
            
            # Insert order items with notes
            for item in order.items:
                cursor.execute("""
                    INSERT INTO order_items (order_id, menu_item_id, quantity, note)
                    VALUES (?, ?, ?, ?)
                """, (order_id, item.menu_item_id, item.quantity, item.note))
            
            # Create initial tracking entry
            cursor.execute("""
                INSERT INTO order_tracking (order_id, status, notes)
                VALUES (?, 'pending', 'Order received')
            """, (order_id,))
            
            conn.commit()
            
            return {
                "order_id": order_id,
                "order_number": order_number,
                "total_price": total_price,
                "discount_amount": discount_amount,
                "estimated_time": estimated_time,
                "status": "pending"
            }
            
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()
    
    @app.get("/api/orders/history/{customer_id}")
    async def get_order_history(customer_id: str):
        """Get order history for a customer"""
        conn = get_db_connection()

        try:
            # First get orders
            orders = conn.execute("""
                SELECT * FROM orders
                WHERE customer_telegram_id = ?
                ORDER BY created_at DESC
                LIMIT 20
            """, (customer_id,)).fetchall()

            result = []
            for order in orders:
                order_dict = dict(order)

                # Get items for this order
                items = conn.execute("""
                    SELECT oi.menu_item_id, mi.name, oi.quantity, mi.price, oi.note
                    FROM order_items oi
                    LEFT JOIN menu_items mi ON oi.menu_item_id = mi.id
                    WHERE oi.order_id = ?
                """, (order['id'],)).fetchall()

                order_dict['items'] = [
                    {
                        'menu_item_id': item['menu_item_id'],
                        'name': item['name'] or 'Unknown Item',
                        'quantity': item['quantity'],
                        'price': item['price'] or 0,
                        'note': item['note']
                    }
                    for item in items
                ]

                result.append(order_dict)

            return result

        finally:
            conn.close()
    
    @app.get("/api/orders/latest/{customer_id}")
    async def get_latest_order(customer_id: str):
        """Get latest active order for tracking"""
        conn = get_db_connection()
        
        try:
            order = conn.execute("""
                SELECT * FROM orders 
                WHERE customer_telegram_id = ? 
                AND status NOT IN ('completed', 'cancelled')
                ORDER BY created_at DESC
                LIMIT 1
            """, (customer_id,)).fetchone()
            
            if not order:
                return None
            
            return dict(order)
            
        finally:
            conn.close()
    
    @app.patch("/api/orders/{order_id}/status")
    async def update_order_status(order_id: int, status_update: OrderStatusUpdate):
        """Update order status (admin only)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Update order status
            cursor.execute("""
                UPDATE orders 
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (status_update.status, order_id))
            
            # Add tracking entry
            cursor.execute("""
                INSERT INTO order_tracking (order_id, status, notes)
                VALUES (?, ?, ?)
            """, (order_id, status_update.status, status_update.notes))
            
            conn.commit()
            
            return {
                "success": True,
                "message": f"Order status updated to {status_update.status}"
            }
            
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            conn.close()

# ============================================
# PAYMENT METHOD ENDPOINTS
# ============================================

def setup_payment_endpoints(app: FastAPI):
    
    @app.get("/api/settings/tng_qr_url")
    async def get_tng_qr():
        """Get Touch n Go QR code URL"""
        conn = get_db_connection()
        
        try:
            result = conn.execute("""
                SELECT qr_code_url FROM payment_methods 
                WHERE method_name = 'touchngo' AND is_active = 1
            """).fetchone()
            
            if result and result['qr_code_url']:
                return {"value": result['qr_code_url']}
            return {"value": None}
            
        finally:
            conn.close()
    
    @app.get("/api/settings/grabpay_qr_url")
    async def get_grabpay_qr():
        """Get GrabPay QR code URL"""
        conn = get_db_connection()
        
        try:
            result = conn.execute("""
                SELECT qr_code_url FROM payment_methods 
                WHERE method_name = 'grabpay' AND is_active = 1
            """).fetchone()
            
            if result and result['qr_code_url']:
                return {"value": result['qr_code_url']}
            return {"value": None}
            
        finally:
            conn.close()
    
    @app.post("/api/settings/payment_method")
    async def update_payment_method(payment: PaymentMethodUpdate):
        """Update payment method QR code (admin only)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE payment_methods 
                SET qr_code_url = ?
                WHERE method_name = ?
            """, (payment.qr_code_url, payment.method_name))
            
            conn.commit()
            
            return {
                "success": True,
                "message": f"Payment method {payment.method_name} updated"
            }
            
        finally:
            conn.close()

# ============================================
# SALES ANALYTICS ENDPOINTS
# ============================================

def setup_analytics_endpoints(app: FastAPI):
    
    @app.get("/api/analytics/sales/daily")
    async def get_daily_sales(date: Optional[str] = None):
        """Get daily sales report"""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        
        try:
            # Total sales
            total = conn.execute("""
                SELECT 
                    COUNT(*) as order_count,
                    SUM(total_price) as total_sales,
                    AVG(total_price) as avg_order_value,
                    SUM(discount_amount) as total_discounts
                FROM orders
                WHERE DATE(created_at) = ?
            """, (date,)).fetchone()
            
            # Sales by payment method
            by_payment = conn.execute("""
                SELECT 
                    payment_method,
                    COUNT(*) as count,
                    SUM(total_price) as total
                FROM orders
                WHERE DATE(created_at) = ?
                GROUP BY payment_method
            """, (date,)).fetchall()
            
            # Top selling items
            top_items = conn.execute("""
                SELECT 
                    mi.name,
                    SUM(oi.quantity) as total_quantity,
                    SUM(oi.quantity * mi.price) as revenue
                FROM order_items oi
                JOIN menu_items mi ON oi.menu_item_id = mi.id
                JOIN orders o ON oi.order_id = o.id
                WHERE DATE(o.created_at) = ?
                GROUP BY mi.name
                ORDER BY total_quantity DESC
                LIMIT 10
            """, (date,)).fetchall()
            
            # Promo code usage
            promo_usage = conn.execute("""
                SELECT 
                    promo_code,
                    COUNT(*) as usage_count,
                    SUM(discount_amount) as total_discount
                FROM orders
                WHERE DATE(created_at) = ? AND promo_code IS NOT NULL
                GROUP BY promo_code
            """, (date,)).fetchall()
            
            return {
                "date": date,
                "summary": dict(total) if total else {},
                "by_payment_method": [dict(row) for row in by_payment],
                "top_items": [dict(row) for row in top_items],
                "promo_usage": [dict(row) for row in promo_usage]
            }
            
        finally:
            conn.close()
    
    @app.get("/api/analytics/sales/weekly")
    async def get_weekly_sales():
        """Get weekly sales report"""
        conn = get_db_connection()
        
        try:
            # Last 7 days
            weekly = conn.execute("""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as order_count,
                    SUM(total_price) as total_sales
                FROM orders
                WHERE created_at >= date('now', '-7 days')
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """).fetchall()
            
            return [dict(row) for row in weekly]
            
        finally:
            conn.close()
    
    @app.get("/api/analytics/sales/monthly")
    async def get_monthly_sales(year: int, month: int):
        """Get monthly sales report"""
        conn = get_db_connection()
        
        try:
            monthly = conn.execute("""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as order_count,
                    SUM(total_price) as total_sales,
                    SUM(discount_amount) as total_discounts
                FROM orders
                WHERE strftime('%Y', created_at) = ? 
                AND strftime('%m', created_at) = ?
                GROUP BY DATE(created_at)
                ORDER BY date
            """, (str(year), f"{month:02d}")).fetchall()
            
            # Monthly summary
            summary = conn.execute("""
                SELECT 
                    COUNT(*) as total_orders,
                    SUM(total_price) as total_revenue,
                    AVG(total_price) as avg_order_value,
                    SUM(discount_amount) as total_discounts
                FROM orders
                WHERE strftime('%Y', created_at) = ? 
                AND strftime('%m', created_at) = ?
            """, (str(year), f"{month:02d}")).fetchone()
            
            return {
                "year": year,
                "month": month,
                "daily_sales": [dict(row) for row in monthly],
                "summary": dict(summary) if summary else {}
            }
            
        finally:
            conn.close()

# ============================================
# SETUP FUNCTION
# ============================================

def setup_enhanced_routes(app: FastAPI):
    """Setup all enhanced routes"""
    setup_promo_endpoints(app)
    setup_order_endpoints(app)
    setup_payment_endpoints(app)
    setup_analytics_endpoints(app)
    
    print("✅ Enhanced routes setup complete!")
    print("   - Promo codes")
    print("   - Order notes")
    print("   - Order history")
    print("   - Order tracking")
    print("   - Payment methods")
    print("   - Sales analytics")
