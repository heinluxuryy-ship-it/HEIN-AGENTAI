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

DEFAULT_PERSONA = """You are the HEIN Luxury Executive AI. Your tone is elite, professional, and helpful.
Your goal is to handle the entire business workload autonomously for the HEIN brand.

CAPABILITIES:
1. SALES: Manage WhatsApp inquiries, suggest luxury watches/accessories, and record orders.
2. VIP MEMORY: You automatically remember customer preferences and history using MongoDB.
3. PRODUCTIVITY: You schedule meetings in Google Calendar and create tasks in Google Tasks.
4. RESEARCH: You provide real-time market insights.

GUIDELINES:
- When a new customer says "Hi", check their history first.
- If they express purchase intent, use 'register_sale' to lock it in.
- If they want a meeting, use 'schedule_meeting' to book it in the Director's calendar.
- Always respond in a way that reflects luxury and exclusivity."""


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
    def check_inventory(self, product_type: str, color: str = None, size: str = None):
        """Query the ERP Inventory to check if a specific product is in stock. Use this whenever a customer asks about availability, colors, or sizes."""
        if self.db_manager.db is None:
            return {"error": "Inventory ERP system is currently disconnected."}

        query = {"type": {"$regex": product_type, "$options": "i"}}
        if color:
            query["color"] = {"$regex": color, "$options": "i"}
        if size:
            query["size"] = size

        try:
            results = list(self.db_manager.db.inventory.find(query, {"_id": 0}))
            if not results:
                return {
                    "status": "out_of_stock",
                    "message": f"We currently do not have {color or ''} {product_type}{' in size ' + size if size else ''}. I can suggest alternatives or place a special order."
                }

            stock_list = []
            for item in results:
                stock_list.append(
                    f"{item.get('name', product_type)} | Size: {item.get('size', 'N/A')} | Color: {item.get('color', 'N/A')} | In Stock: {item.get('quantity', 0)}"
                )
            return {"status": "in_stock", "available_items": stock_list}
        except Exception as e:
            return {"error": f"Failed to read inventory: {e}"}

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

    # ─── Research Tool ───────────────────────────────────────────────────────
    def perform_market_research(self, query: str):
        """Get real-time insights on luxury market trends from the web."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
                if not results:
                    return {"result": "No data found for the query."}
                summaries = [f"Source: {r.get('href')} | Info: {r.get('body')}" for r in results]
                return {"trend_data": summaries, "region": "Global"}
        except ImportError:
            return {"error": "Research module offline."}
        except Exception as e:
            logger.error(f"Search error: {e}")
            return {"error": "Failed to look up information."}

    # ─── Message Processing ──────────────────────────────────────────────────
    def process_message(self, user_input, phone_number):
        """Processes message via OpenAI or Gemini with a dynamically loaded system prompt."""
        self.current_phone = phone_number
        customer = self.db_manager.get_or_create_customer(phone_number)
        self.db_manager.log_interaction(phone_number, user_input, "inbound")

        if self.model_type == "gemini":
            return self._process_gemini(user_input, customer)
        else:
            return self._process_openai(user_input, customer)

    def _process_gemini(self, user_input, customer):
        """Native Gemini Processing with dynamic system prompt."""
        system_prompt = self._build_system_prompt()
        try:
            if not hasattr(self, 'available_gemini_model'):
                available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                if not available:
                    raise Exception("No Gemini models found on this account.")
                flash_models = [m for m in available if 'flash' in m.lower()]
                self.available_gemini_model = flash_models[0] if flash_models else available[0]
                logger.info(f"Auto-selected Gemini Model: {self.available_gemini_model}")

            model = genai.GenerativeModel(
                model_name=self.available_gemini_model,
                tools=[self.register_sale, self.schedule_meeting, self.add_business_task,
                       self.perform_market_research, self.check_inventory],
                system_instruction=system_prompt
            )
        except Exception as e:
            logger.error(f"Gemini Auto-Discovery failed: {e}")
            return "AI Configuration Error. Please check your Gemini API credits/region."

        chat = model.start_chat(enable_automatic_function_calling=True)
        prefs_json = json.dumps(customer.get("preferences", {}))
        response = chat.send_message(f"Customer Profile: {prefs_json}\nMessage: {user_input}")

        ai_reply = response.text
        self.db_manager.log_interaction(self.current_phone, ai_reply, "outbound")
        return ai_reply

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
