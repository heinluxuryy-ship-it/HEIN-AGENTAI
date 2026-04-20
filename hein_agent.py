import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai

# Import Local Modules
from google_integration import GoogleProductivityManager
from database_manager import HeinDatabaseManager

# Load environment variables
load_dotenv()

# Configure Global Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - HEIN-AI - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_PERSONA = """You are the HEIN Luxury Executive AI. Your tone is elite, professional, and highly exclusive.
Your goal is to handle the entire business workload autonomously for the HEIN luxury brand with absolute precision.

CAPABILITIES:
1. SALES: Manage WhatsApp inquiries with a "concierge" level of service, suggest elite watches/accessories, and record orders.
2. VIP MEMORY: You automatically remember customer preferences and history using MongoDB to provide personalized attention.
3. PRODUCTIVITY: You schedule private viewings in Google Calendar and manage executive tasks in Google Tasks.
4. RESEARCH: You provide real-time market insights on luxury assets.
5. STOCK MANAGEMENT: You track customer desired items and offer to notify them when exclusive inventory returns.

GUIDELINES:
- When a new customer says "Hi", check their history first to acknowledge their VIP status if applicable.
- If they express purchase intent, use 'register_sale' to lock in the acquisition.
- If they want a meeting or private viewing, use 'schedule_meeting'.
- ALWAYS respond in a way that reflects extreme luxury, wealth, and exclusivity. Use sophisticated vocabulary.
- If an item is out of stock, offer to 'subscribe_restock_alert' so they are first in line when it returns."""


class HeinAgent:
    def __init__(self):
        # AI Setup
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")

        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self.model_type = "gemini"
            logger.info("Using Google Gemini (Free Tier)")
        else:
            self.ai_client = OpenAI(api_key=self.openai_key)
            self.model_type = "openai"
            logger.info("Using OpenAI Core")

        self.model_name = os.getenv("MODEL_NAME", "gpt-4o" if not self.gemini_key else "gemini-1.5-pro")

        # System Setup
        self.db_manager = HeinDatabaseManager()
        try:
            self.google_manager = GoogleProductivityManager()
        except Exception as e:
            logger.error(f"Google Integration skipped: {e}")
            self.google_manager = None

        self.current_phone = None

    # ─── Dynamic Prompt Builder ─────────────────────────────────────────────
    def _build_system_prompt(self):
        """Reads from MongoDB settings to build a dynamic system prompt."""
        base_persona = DEFAULT_PERSONA
        language_block = ""
        quickmsg_block = ""

        if self.db_manager.db is not None:
            try:
                cfg = self.db_manager.db.settings.find_one({"key": "ai_config"})
                if cfg:
                    if cfg.get("persona"):
                        base_persona = cfg["persona"]
                    if cfg.get("languages"):
                        langs = cfg["languages"]
                        language_block = f"\n\nLANGUAGE RULES:\nYou MUST detect and respond in the same language the customer writes in.\nSupported languages: {', '.join(langs)}.\nIf the customer writes in Somali, reply fully in Somali. Same for all other configured languages."
                    if cfg.get("quick_messages"):
                        rules = "\n".join(f"- {r}" for r in cfg["quick_messages"])
                        quickmsg_block = f"\n\nQUICK RESPONSE RULES (always follow these):\n{rules}"
            except Exception as e:
                logger.error(f"Failed to load AI settings from DB: {e}")

        return base_persona + language_block + quickmsg_block

    # ─── ERP Inventory Tool ──────────────────────────────────────────────────
    def check_inventory(self, product_query: str):
        """Query the ERP inventory to check if a product is in stock. Use this to find models, colors, and sizes. Search broadly by name or title."""
        if self.db_manager.db is None:
            return {"error": "Inventory ERP system is currently disconnected."}

        # Search broadly using regex across multiple fields
        query = {
            "$or": [
                {"name": {"$regex": product_query, "$options": "i"}},
                {"title": {"$regex": product_query, "$options": "i"}},
                {"color": {"$regex": product_query, "$options": "i"}},
                {"type": {"$regex": product_query, "$options": "i"}},
            ]
        }

        try:
            # Pointing to 'products' collection as per user's live ERP
            results = list(self.db_manager.db.products.find(query, {"_id": 0}).limit(5))
            if not results:
                return {
                    "status": "out_of_stock",
                    "message": f"I couldn't find '{product_query}' in our live inventory. I can request the Director to check our back-stock for you."
                }

            stock_list = []
            for item in results:
                name = item.get('name') or item.get('title') or 'Product'
                stock_list.append(
                    f"{name} | Color: {item.get('color', 'N/A')} | Size/Specs: {item.get('size', 'N/A')} | Available: {item.get('quantity', 0)}"
                )
            return {"status": "in_stock", "available_items": stock_list}
        except Exception as e:
            logger.error(f"Inventory query error: {e}")
            return {"error": "Failed to read inventory. Please try again."}

    # ─── Team Alert Tool ──────────────────────────────────────────────────
    def request_human_support(self, reason: str):
        """Use this tool when a customer explicitly asks for a 'real person', 'director', or 'manager', or if you are completely unable to identify a product/color. This will alert the business owners."""
        if not self.current_phone: return {"error": "No active session"}

        managers = self.db_manager.get_managers()
        if not managers:
            return {"status": "flagged", "message": "The Director has been notified via the dashboard flag."}

        # Tag the customer in DB
        if self.db_manager.db is not None:
            self.db_manager.db.customers.update_one(
                {"phone": self.current_phone},
                {"$set": {"awaiting_human": True, "handoff_reason": reason}}
            )

        # Notify via WhatsApp (Simulated/Relayed via wa_bridge)
        # Note: In a real flow, we'd trigger a POST to wa_bridge /send for each manager
        try:
            import requests
            bridge_url = f"http://127.0.0.1:{os.getenv('PORT', 5000)}/api/whatsapp/internal-alert"
            payload = {
                "managers": [m['phone'] for m in managers],
                "customer": self.current_phone,
                "reason": reason
            }
            # We call an internal Flask route that will handle the broadcast
            requests.post(bridge_url, json=payload, timeout=5)
        except:
            pass

        return {"status": "notified", "message": "Manager alert sent to all 24/7 notification numbers."}

    def subscribe_restock_alert(self, product_name: str):
        """Use this tool when a customer is interested in a product that is currently out of stock. It will notify them automatically once the product arrives."""
        if not self.current_phone: return {"error": "No active session"}
        self.db_manager.record_wishlist(self.current_phone, product_name)
        return {"status": "subscribed", "message": f"Successfully added to the exclusive waitlist for {product_name}."}

    # ─── Sales Tool ──────────────────────────────────────────────────────────
    def register_sale(self, product_name: str, variant: str = None, price: float = 0, quantity: int = 1):
        """Log a sale in the ERP and MongoDB. Use when a client confirms purchase intent."""
        args = {"product_name": product_name, "variant": variant, "price": price, "quantity": quantity}
        order_id = self.db_manager.record_order(self.current_phone, args)
        return {"status": "order_locked", "order_id": order_id}

    # ─── Calendar Tool ───────────────────────────────────────────────────────
    def schedule_meeting(self, summary: str, date_time_iso: str, description: str = "", duration_min: int = 30):
        """Schedule a business meeting in Google Calendar."""
        if not self.google_manager:
            return {"error": "Google Calendar not connected"}
        return self.google_manager.create_event(summary, description, date_time_iso, duration_min)

    # ─── Task Tool ───────────────────────────────────────────────────────────
    def add_business_task(self, title: str, notes: str = ""):
        """Add a task to the Director's to-do list."""
        if not self.google_manager:
            return {"error": "Google Tasks not connected"}
        return self.google_manager.create_task(title, notes)

    # ─── Message Processing ──────────────────────────────────────────────────
    def process_message(self, user_input, phone_number, image_base64=None):
        """Processes message + optional image using Gemini 1.5 Flash."""
        self.current_phone = phone_number
        customer = self.db_manager.get_or_create_customer(phone_number)
        
        # Log content
        log_msg = user_input if not image_base64 else f"[IMAGE] {user_input}"
        self.db_manager.log_interaction(phone_number, log_msg, "inbound")

        if self.model_type == "gemini":
            return self._process_gemini(user_input, customer, image_base64)
        else:
            # Fallback for OpenAI (Text only for now)
            return self._process_openai(user_input, customer)

    def _process_gemini(self, user_input, customer, image_base64=None):
        """Multimodal Gemini Processing (Vision + Tools)."""
        system_prompt = self._build_system_prompt()
        try:
            # Always use 1.5 Flash for vision + performance
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                tools=[self.register_sale, self.schedule_meeting, self.add_business_task,
                       self.check_inventory, self.request_human_support, self.subscribe_restock_alert],
                system_instruction=system_prompt
            )

            # Build multimodal prompt
            prompt_parts = []
            if image_base64:
                prompt_parts.append({
                    "mime_type": "image/jpeg",
                    "data": image_base64
                })
            
            prefs_json = json.dumps(customer.get("preferences", {}))
            prompt_parts.append(f"Customer Profile: {prefs_json}\nMessage: {user_input}")

            chat = model.start_chat(enable_automatic_function_calling=True)
            response = chat.send_message(prompt_parts)

            ai_reply = response.text
            self.db_manager.log_interaction(self.current_phone, ai_reply, "outbound")
            return ai_reply

        except Exception as e:
            logger.error(f"Gemini processing error: {e}")
            # If it's an image request that fails, retry as text-only
            if image_base64:
                logger.warning("Vision processing failed, retrying as text-only...")
                try:
                    model_text = genai.GenerativeModel(
                        model_name="gemini-1.5-flash",
                        tools=[self.register_sale, self.schedule_meeting, self.add_business_task,
                               self.check_inventory, self.request_human_support, self.subscribe_restock_alert],
                        system_instruction=system_prompt
                    )
                    prefs_json = json.dumps(customer.get("preferences", {}))
                    chat = model_text.start_chat(enable_automatic_function_calling=True)
                    fallback_msg = f"Customer Profile: {prefs_json}\nMessage: {user_input or 'Customer sent an image of a product they are interested in.'}"
                    response = chat.send_message(fallback_msg)
                    ai_reply = response.text
                    self.db_manager.log_interaction(self.current_phone, ai_reply, "outbound")
                    return ai_reply
                except Exception as e2:
                    logger.error(f"Gemini text fallback also failed: {e2}")
                    return "Thank you for your message. Our team will be in touch with you shortly."
            # For pure text failures, give a professional generic response
            return "Thank you for reaching out to HEIN Luxury. We are experiencing a brief moment of high demand. Please resend your message and our concierge will assist you immediately."

    def _process_openai(self, user_input, customer):
        """Standard OpenAI Tool Calling Flow with dynamic system prompt."""
        system_prompt = self._build_system_prompt()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "register_sale",
                    "description": "Log a sale in the ERP and MongoDB.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "variant": {"type": "string"},
                            "price": {"type": "number"},
                            "quantity": {"type": "integer"}
                        },
                        "required": ["product_name", "price"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_meeting",
                    "description": "Schedule a business meeting in Google Calendar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "date_time_iso": {"type": "string"},
                            "duration_min": {"type": "integer"}
                        },
                        "required": ["summary", "date_time_iso"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_inventory",
                    "description": "Query the ERP inventory to check if a product is in stock.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_type": {"type": "string"},
                            "color": {"type": "string"},
                            "size": {"type": "string"}
                        },
                        "required": ["product_type"]
                    }
                }
            }
        ]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Customer Profile: {json.dumps(customer.get('preferences', {}))}\nMessage: {user_input}"}
        ]

        response = self.ai_client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )

        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        if tool_calls:
            messages.append(response_message)
            for tool_call in tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                result = ""
                if func_name == "register_sale":
                    result = json.dumps(self.register_sale(**args))
                elif func_name == "schedule_meeting":
                    result = json.dumps(self.schedule_meeting(**args))
                elif func_name == "check_inventory":
                    result = json.dumps(self.check_inventory(**args))
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": func_name,
                    "content": result,
                })

            final_response = self.ai_client.chat.completions.create(
                model=self.model_name,
                messages=messages
            )
            ai_reply = final_response.choices[0].message.content
        else:
            ai_reply = response_message.content

        self.db_manager.log_interaction(self.current_phone, ai_reply, "outbound")
        return ai_reply


if __name__ == "__main__":
    agent = HeinAgent()
    print("HEIN AI READY. (Terminal Simulation)")
    while True:
        msg = input("\nClient: ")
        if msg.lower() in ['exit', 'quit']:
            break
        reply = agent.process_message(msg, "+123456789")
        print(f"\nHEIN AI: {reply}")
