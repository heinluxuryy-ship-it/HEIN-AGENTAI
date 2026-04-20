import os
import logging
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class HeinDatabaseManager:
    def __init__(self):
        self.uri = os.getenv("MONGODB_URI")
        # Switch to the main business database
        self.db_name = "hein_luxury"
        self.client = None
        self.db = None
        
        if self.uri:
            try:
                self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
                # self.client.admin.command('ping') # Removed blocking ping for faster cloud startup
                
                self.db = self.client[self.db_name]
                self._initialize_collections()
                logger.info(f"Connected to HEIN MongoDB: {self.db_name}")
            except Exception as e:
                # Fallback to intelligence DB if main one fails (for dev safety)
                logger.warning(f"Could not connect to {self.db_name}, trying fallback...")
                try:
                    self.db = self.client["hein_luxury_intelligence"]
                    logger.info("Connected to HEIN Intelligence (Fallback).")
                except:
                    logger.error(f"Failed to connect to MongoDB: {e}")
                    self.db = None

    def _initialize_collections(self):
        """Ensures index and base collections exist."""
        if self.db is not None:
            self.db.customers.create_index("phone", unique=True)
            self.db.orders.create_index("order_id", unique=True)
            self.db.interactions.create_index([("phone", 1), ("timestamp", -1)])
            # Collection for team members who receive alerts
            self.db.managers.create_index("phone", unique=True)

    # --- MANAGER / TEAM ALERTS ---

    def add_manager(self, name, phone):
        if self.db is None: return
        self.db.managers.update_one(
            {"phone": phone},
            {"$set": {"name": name, "active": True}},
            upsert=True
        )

    def remove_manager(self, phone):
        if self.db is None: return
        self.db.managers.delete_one({"phone": phone})

    def get_managers(self):
        if self.db is None: return []
        return list(self.db.managers.find({"active": True}))

    # --- CUSTOMER MEMORY ---

    def get_or_create_customer(self, phone, name=None):
        """Retrieves customer profile or creates a new entry for a lead."""
        if self.db is None: return {"phone": phone, "status": "new"}
        
        customer = self.db.customers.find_one({"phone": phone})
        if not customer:
            customer = {
                "phone": phone,
                "name": name or "Valued Client",
                "tier": "Lead",
                "preferences": {},
                "created_at": datetime.now(),
                "last_interaction": datetime.now(),
                "total_spend": 0,
                "followup_needed": False
            }
            self.db.customers.insert_one(customer)
        return customer

    def update_preferences(self, phone, preferences_dict):
        """Updates specific preferences (e.g., {'favorite_color': 'Rose Gold'})."""
        if self.db is None: return
        self.db.customers.update_one(
            {"phone": phone},
            {"$set": {f"preferences.{k}": v for k, v in preferences_dict.items()},
             "$set": {"last_interaction": datetime.now()}}
        )

    # --- SALES & ORDERS ---

    def record_order(self, phone, product_data):
        """Logs a new sales order and updates customer spend metrics."""
        if self.db is None: return None
        
        order_id = f"HE-{datetime.now().strftime('%y%m%d%H%M')}"
        order = {
            "order_id": order_id,
            "phone": phone,
            "product": product_data.get('product_name'),
            "variant": product_data.get('variant'),
            "price": product_data.get('price', 0),
            "status": "AWAITING_PAYMENT",
            "timestamp": datetime.now()
        }
        
        self.db.orders.insert_one(order)
        # Update total spend
        self.db.customers.update_one(
            {"phone": phone},
            {"$inc": {"total_spend": order['price']}, "$set": {"tier": "VIP"}}
        )
        return order_id

    # --- FOLLOW-UP LOGIC ---

    def log_interaction(self, phone, message, direction="inbound"):
        """Logs every message for future analysis and triggers follow-up flags."""
        if self.db is None: return
        self.db.interactions.insert_one({
            "phone": phone,
            "message": message,
            "direction": direction,
            "timestamp": datetime.now()
        })
        # Reset follow-up timer on interaction
        self.db.customers.update_one(
            {"phone": phone},
            {"$set": {"last_interaction": datetime.now(), "followup_needed": False}}
        )

    def set_manual_mode(self, phone, status=True):
        """Toggles manual override for a customer (stops AI from talking)."""
        if self.db is None: return
        self.db.customers.update_one(
            {"phone": phone},
            {"$set": {"is_manual": status}}
        )
        mode = "MANUAL" if status else "AI-ENABLED"
        logger.info(f"Customer {phone} switched to {mode} mode.")

    def is_manual_active(self, phone):
        """Checks if a customer is currently in manual override mode."""
        if self.db is None: return False
        customer = self.db.customers.find_one({"phone": phone}, {"is_manual": 1})
        return customer.get("is_manual", False) if customer else False

    def get_aging_leads(self, hours=24):
        """Finds leads who haven't responded in X hours."""
        if self.db is None: return []
        threshold = datetime.now() - timedelta(hours=hours)
        return list(self.db.customers.find({
            "last_interaction": {"$lt": threshold},
            "tier": "Lead"
        }))

    # --- WISHLIST & RESTOCK LOGIC ---

    def record_wishlist(self, phone, product_name):
        """Logs a customer's interest in an out-of-stock item."""
        if self.db is None: return
        self.db.wishlist.update_one(
            {"phone": phone, "product_name": product_name},
            {"$set": {"timestamp": datetime.now(), "notified": False}},
            upsert=True
        )
        logger.info(f"Recorded wishlist item for {phone}: {product_name}")

    def get_restock_candidates(self):
        """Finds wishlist items that are now back in stock in the products collection."""
        if self.db is None: return []
        
        candidates = list(self.db.wishlist.find({"notified": False}))
        restocked = []
        
        for item in candidates:
            product_name = item.get("product_name")
            # Check current inventory
            product = self.db.products.find_one({
                "$or": [
                    {"name": {"$regex": product_name, "$options": "i"}},
                    {"title": {"$regex": product_name, "$options": "i"}}
                ],
                "quantity": {"$gt": 0}
            })
            
            if product:
                restocked.append({
                    "phone": item["phone"],
                    "product_name": product_name,
                    "actual_name": product.get("name") or product.get("title")
                })
        
        return restocked

    def mark_wishlist_notified(self, phone, product_name):
        if self.db is None: return
        self.db.wishlist.update_one(
            {"phone": phone, "product_name": product_name},
            {"$set": {"notified": True, "notified_at": datetime.now()}}
        )

    # --- REVENUE INTELLIGENCE ---

    def get_projected_revenue(self):
        """Calculates total value of orders in AWAITING_PAYMENT status."""
        if self.db is None: return 0.0
        pipeline = [
            {"$match": {"status": "AWAITING_PAYMENT"}},
            {"$group": {"_id": None, "total": {"$sum": "$price"}}}
        ]
        result = list(self.db.orders.aggregate(pipeline))
        # Ensure it returns a standard float to prevent JSON serialization errors
        return float(result[0]['total']) if result else 0.0
