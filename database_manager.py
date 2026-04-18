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
        self.db_name = "hein_luxury_intelligence"
        self.client = None
        self.db = None
        
        if self.uri:
            try:
                # Use a fast 5-second timeout so it doesn't freeze Flask on boot
                self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
                # Force a connection test
                self.client.admin.command('ping')
                
                self.db = self.client[self.db_name]
                self._initialize_collections()
                logger.info("Connected to HEIN MongoDB Memory.")
            except Exception as e:
                logger.error(f"Failed to connect to MongoDB (Check Atlas IP Whitelist): {e}")
                self.client = None
                self.db = None

    def _initialize_collections(self):
        """Ensures index and base collections exist."""
        if self.db is not None:
            self.db.customers.create_index("phone", unique=True)
            self.db.orders.create_index("order_id", unique=True)
            self.db.interactions.create_index([("phone", 1), ("timestamp", -1)])

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

    def get_aging_leads(self, hours=24):
        """Finds leads who haven't responded in X hours."""
        if self.db is None: return []
        threshold = datetime.now() - timedelta(hours=hours)
        return list(self.db.customers.find({
            "last_interaction": {"$lt": threshold},
            "tier": "Lead"
        }))
