import os
import json
import logging
from datetime import datetime
from threading import Lock
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from hein_agent import HeinAgent
from whatsapp_service import WhatsAppService
import auto_followup

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - HEIN - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
hein_engine = HeinAgent()
wa_service = WhatsAppService()

# --- Real-time Log Store ---
dashboard_logs = []
log_lock = Lock()

def add_log(msg, log_type="info"):
    with log_lock:
        timestamp = datetime.now().strftime('%H:%M:%S')
        # Ensure message is string and ASCII-safe for some cloud consoles
        safe_msg = str(msg).encode('ascii', 'ignore').decode('ascii')
        dashboard_logs.insert(0, {
            "time": timestamp,
            "message": safe_msg,
            "type": log_type
        })
        if len(dashboard_logs) > 100:
            dashboard_logs.pop()

class DashboardLogger:
    def info(self, msg): logging.info(msg); add_log(msg, "info")
    def error(self, msg): logging.error(msg); add_log(f"ERROR: {msg}", "error")
    def warning(self, msg): logging.warning(msg); add_log(f"WARN: {msg}", "warning")

hein_engine.logger = DashboardLogger()
add_log("HEIN Intelligence Core initialized.", "core")
add_log(f"WhatsApp: {wa_service.get_status()['label']}", "info")

# ========================================================
#  PAGE ROUTES
# ========================================================

@app.route('/')
def dashboard():
    return render_template('index.html')

# ========================================================
#  API — ACTIVITY & STATS
# ========================================================

@app.route('/api/activity', methods=['GET'])
def get_activity():
    with log_lock:
        return jsonify(dashboard_logs)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    try:
        db = hein_engine.db_manager.db
        if db is None:
            return jsonify({
                "total_customers": 0,
                "orders_ready": 0,
                "vip_count": 0,
                "lead_count": 0,
                "today_interactions": 0,
                "whatsapp": wa_service.get_status(),
                "memory_ok": False
            })

        total_customers = db.customers.count_documents({})
        orders_ready = db.orders.count_documents({"status": "AWAITING_PAYMENT"})
        vip_count = db.customers.count_documents({"tier": "VIP"})
        lead_count = db.customers.count_documents({"tier": "Lead"})

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_interactions = db.interactions.count_documents({
            "timestamp": {"$gte": today_start}
        })

        return jsonify({
            "total_customers": total_customers,
            "orders_ready": orders_ready,
            "vip_count": vip_count,
            "lead_count": lead_count,
            "today_interactions": today_interactions,
            "projected_revenue": hein_engine.db_manager.get_projected_revenue(),
            "whatsapp": wa_service.get_status(),
            "memory_ok": True
        })
    except Exception as e:
        logger.error(f"Failed to fetch stats: {e}")
        return jsonify({
            "total_customers": 0, "orders_ready": 0, "vip_count": 0, "lead_count": 0, "today_interactions": 0,
            "whatsapp": {"provider": "error", "connected": False, "label": "API Error"},
            "memory_ok": False,
            "error": str(e)
        })

# ========================================================
#  API — CUSTOMERS / CRM
# ========================================================

@app.route('/api/customers', methods=['GET'])
def get_customers():
    db = hein_engine.db_manager.db
    if db is None:
        return jsonify({"error": "No database connection", "customers": []})

    search = request.args.get('search', '').strip()
    tier_filter = request.args.get('tier', '')
    limit = int(request.args.get('limit', 50))

    query = {}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}}
        ]
    if tier_filter and tier_filter != 'all':
        query["tier"] = tier_filter

    customers = list(db.customers.find(query, {"_id": 0}).sort("last_interaction", -1).limit(limit))

    # Convert datetime objects to strings
    for c in customers:
        if isinstance(c.get("last_interaction"), datetime):
            c["last_interaction"] = c["last_interaction"].strftime("%b %d, %Y %H:%M")
        if isinstance(c.get("created_at"), datetime):
            c["created_at"] = c["created_at"].strftime("%b %d, %Y")

    return jsonify({"customers": customers, "total": len(customers)})

@app.route('/api/customers/<phone>/history', methods=['GET'])
def get_customer_history(phone):
    db = hein_engine.db_manager.db
    if db is None:
        return jsonify({"interactions": []})

    interactions = list(db.interactions.find(
        {"phone": phone}, {"_id": 0}
    ).sort("timestamp", -1).limit(20))

    for i in interactions:
        if isinstance(i.get("timestamp"), datetime):
            i["timestamp"] = i["timestamp"].strftime("%b %d %H:%M")

    return jsonify({"interactions": interactions})

@app.route('/api/customers/<phone>/update', methods=['POST'])
def update_customer(phone):
    db = hein_engine.db_manager.db
    if db is None:
        return jsonify({"error": "No database"})

    data = request.json
    update_fields = {}
    if "name" in data:
        update_fields["name"] = data["name"]
    if "tier" in data:
        update_fields["tier"] = data["tier"]
    if "notes" in data:
        update_fields["notes"] = data["notes"]

    db.customers.update_one({"phone": phone}, {"$set": update_fields})
    add_log(f"Customer {phone} updated manually by Director.", "core")
    return jsonify({"status": "updated"})

# ========================================================
#  API — TEST CHAT
# ========================================================

@app.route('/api/chat', methods=['POST'])
def test_chat():
    user_input = request.json.get('message', '')
    if not user_input:
        return jsonify({"error": "No message provided"}), 400

    add_log(f"Test inquiry: {user_input}", "whatsapp")
    reply = hein_engine.process_message(user_input, "DASHBOARD-TEST-USER")
    add_log(f"HEIN AI replied: {reply[:60]}...", "core")
    return jsonify({"reply": reply})

# ========================================================
#  API — BROADCAST
# ========================================================

@app.route('/api/broadcast', methods=['POST'])
def broadcast():
    data = request.json
    message = data.get("message", "")
    tier = data.get("tier", "all")
    custom_phones = data.get("phones", [])

    if not message:
        return jsonify({"error": "Message cannot be empty"}), 400

    db = hein_engine.db_manager.db

    if custom_phones:
        phone_list = custom_phones
    elif db is not None:
        query = {} if tier == "all" else {"tier": tier}
        customers = list(db.customers.find(query, {"phone": 1, "_id": 0}))
        phone_list = [c["phone"] for c in customers]
    else:
        phone_list = []

    if not phone_list:
        return jsonify({"error": "No recipients found"}), 400

    add_log(f"Broadcast initiated: {len(phone_list)} recipients | Tier: {tier}", "core")
    results = wa_service.send_broadcast(phone_list, message)

    sent = sum(1 for r in results if r.get("status") in ["sent", "simulated"])
    failed = len(results) - sent

    add_log(f"Broadcast complete: {sent} sent, {failed} failed.", "info")
    return jsonify({
        "status": "complete",
        "sent": sent,
        "failed": failed,
        "results": results[:10]  # Return only first 10 for brevity
    })

@app.route('/api/broadcast/preview', methods=['POST'])
def broadcast_preview():
    """Preview how many recipients will receive a broadcast."""
    data = request.json
    tier = data.get("tier", "all")

    db = hein_engine.db_manager.db
    if db is None:
        return jsonify({"count": 0})

    query = {} if tier == "all" else {"tier": tier}
    count = db.customers.count_documents(query)
    return jsonify({"count": count, "tier": tier})

# ========================================================
#  API — WHATSAPP / WEBHOOK
# ========================================================

@app.route('/api/whatsapp/status', methods=['GET'])
def whatsapp_status():
    status = wa_service.get_status()
    # If the provider is bridge, let's fetch the QR
    if status["provider"] == "bridge":
        import requests
        try:
            res = requests.get("http://127.0.0.1:5001/status", timeout=5).json()
            status["qr"] = res.get("qr")
            status["bridge_ready"] = res.get("ready")
        except:
            status["qr"] = None
            status["bridge_ready"] = False
    return jsonify(status)

@app.route('/webhook', methods=['GET'])
def webhook_verify():
    """Meta webhook verification."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "hein_luxury_verify")
    if mode == "subscribe" and token == verify_token:
        add_log("WhatsApp Webhook verified by Meta.", "info")
        return challenge, 200
    return "Forbidden", 403

@app.route('/webhook/wa_bridge', methods=['POST'])
def proxy_wa_bridge():
    """Receives payloads from the local wa_bridge.js proxy (Supports Images)"""
    data = request.json
    logger.info(f"[BRIDGE-WEBHOOK] Received payload: {data.get('type')} from {data.get('sender')}")
    
    try:
        sender = data.get("sender", "")
        text = data.get("text", "")
        msg_type = data.get("type", "text")
        image_base64 = data.get("image") # New: Multimodal image data
        
        if not sender or (not text and not image_base64):
            logger.warning(f"[BRIDGE-WEBHOOK] Missing content, ignoring. sender='{sender}'")
            return jsonify({"status": "ignored"}), 200
        
        log_label = f"📱 Bridge {msg_type.upper()} from {sender}: {text[:60]}"
        add_log(log_label, "whatsapp")
        
        # Step 2: Generate AI reply (now vision-capable)
        try:
            reply = hein_engine.process_message(text, sender, image_base64=image_base64)
            logger.info(f"[BRIDGE-WEBHOOK] AI generated reply.")
        except Exception as ai_err:
            logger.error(f"[BRIDGE-WEBHOOK] AI generation error: {ai_err}")
            reply = "Thank you for your message. Our team will get back to you shortly."
        
        add_log(f"🤖 AI Reply to {sender}: {reply[:60]}...", "core")
        
        # Step 3: Send reply via bridge
        try:
            result = wa_service.send_message(sender, reply)
            add_log(f"✅ Reply sent to {sender}", "core")
        except Exception as send_err:
            logger.error(f"[BRIDGE-WEBHOOK] Send error: {send_err}")
            add_log(f"❌ Failed to reply to {sender}: {send_err}", "error")
        
        return jsonify({"status": "ok", "reply_sent": True})
    except Exception as e:
        logger.error(f"[BRIDGE-WEBHOOK] FATAL ERROR: {e}", exc_info=True)
        add_log(f"Bridge webhook error: {e}", "error")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/api/whatsapp/internal-alert', methods=['POST'])
def internal_alert():
    """Trigger WhatsApp notifications to all recorded manager numbers."""
    data = request.json
    managers = data.get('managers', [])
    customer = data.get('customer', 'Unknown')
    reason = data.get('reason', 'Manual review needed')

    alert_msg = f"🚨 *HEIN AI ALERT*\n\n*Issue:* {reason}\n*Customer:* +{customer}\n*Action:* Please check the HEIN Dashboard to take over this conversation."

    count = 0
    for manager_phone in managers:
        try:
            wa_service.send_message(manager_phone, alert_msg)
            count += 1
        except:
            continue
    
    add_log(f"📣 Broadcasted alert to {count} managers.", "system")
    return jsonify({"status": "alerts_sent", "count": count})

# ========================================================
#  API — AUTOMATION & FOLLOW-UPS
# ========================================================

@app.route('/api/customers/<phone>/followup', methods=['POST'])
def manual_followup(phone):
    """Triggers a personalized AI follow-up for a specific customer."""
    try:
        db = hein_engine.db_manager.db
        customer = db.customers.find_one({"phone": phone})
        if not customer:
            return jsonify({"error": "Customer not found"}), 404
        
        name = customer.get("name", "Valued Client")
        add_log(f"Manual follow-up triggered for {name} (+{phone})", "core")
        
        msg = auto_followup.generate_followup(hein_engine, phone, name)
        wa_service.send_message(phone, msg)
        
        # Update interaction time
        db.customers.update_one({"phone": phone}, {"$set": {"last_interaction": datetime.now()}})
        
        return jsonify({"status": "sent", "message": msg})
    except Exception as e:
        logger.error(f"Manual followup error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/automation/run-followups', methods=['POST'])
def run_followups():
    """Triggers the automated cycle for all aging leads."""
    try:
        count = auto_followup.run_followup_cycle(hein_engine, wa_service)
        add_log(f"Automation: Sent {count} personalized follow-ups.", "core")
        return jsonify({"status": "complete", "count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/automation/run-restock-alerts', methods=['POST'])
def run_restock_alerts():
    """Checks the wishlist and notifies everyone whose items are back in stock."""
    try:
        candidates = hein_engine.db_manager.get_restock_candidates()
        if not candidates:
            return jsonify({"status": "no_restocks", "count": 0})
        
        count = 0
        for item in candidates:
            phone = item['phone']
            product = item['actual_name']
            
            prompt = (
                f"Notify user {phone} that the item they was waiting for, '{product}', is now back in stock and ready for procurement. "
                "Keep it elite, exclusive, and exciting. Tell them they are being notified before the general public."
            )
            msg = hein_engine.process_message(prompt, phone)
            wa_service.send_message(phone, msg)
            
            hein_engine.db_manager.mark_wishlist_notified(phone, item['product_name'])
            count += 1
            
        add_log(f"Restock Logic: Notified {count} exclusive clients.", "core")
        return jsonify({"status": "sent", "count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    """Production WhatsApp webhook entry point."""
    data = request.json
    try:
        incoming_msg = ""
        sender = ""

        if 'messages' in data.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}):
            msg_data = data['entry'][0]['changes'][0]['value']['messages'][0]
            incoming_msg = msg_data.get('text', {}).get('body', '')
            sender = msg_data.get('from', '')
        elif 'Body' in data:
            incoming_msg = data['Body']
            sender = data['From'].replace('whatsapp:', '').replace('+', '')

        if not incoming_msg or not sender:
            return jsonify({"status": "ignored"}), 200

        add_log(f"📱 Meta WA from {sender}: {incoming_msg[:40]}", "whatsapp")

        reply = hein_engine.process_message(incoming_msg, sender)
        wa_service.send_message(sender, reply)

        add_log(f"✅ Replied to {sender}", "core")
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        add_log(f"Webhook error: {e}", "error")
        return jsonify({"status": "error"}), 400

# ========================================================
#  API — ERP SYNC
# ========================================================

@app.route('/api/sync', methods=['POST'])
def sync_erp():
    add_log("Manual ERP Sync triggered.", "core")
    db = hein_engine.db_manager.db
    if db is not None:
        orders = list(db.orders.find({"status": "AWAITING_PAYMENT"}, {"_id": 0}).limit(5))
        add_log(f"ERP Sync: {len(orders)} pending orders found.", "info")
        return jsonify({"status": "synced", "pending_orders": len(orders)})
    return jsonify({"status": "no_db"})

# ========================================================
#  API — AI SETTINGS
# ========================================================

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Returns the current AI configuration (persona, languages, quick messages)."""
    db = hein_engine.db_manager.db
    if db is None:
        return jsonify({"error": "No database connection"}), 503
    try:
        cfg = db.settings.find_one({"key": "ai_config"}, {"_id": 0}) or {}
        return jsonify({
            "persona": cfg.get("persona", ""),
            "languages": cfg.get("languages", ["English"]),
            "quick_messages": cfg.get("quick_messages", [])
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def save_settings():
    """Saves AI configuration to MongoDB."""
    db = hein_engine.db_manager.db
    if db is None:
        return jsonify({"error": "No database connection"}), 503
    data = request.json
    try:
        update_data = {}
        if "persona" in data:
            update_data["persona"] = data["persona"]
        if "languages" in data:
            update_data["languages"] = data["languages"]
        if "quick_messages" in data:
            update_data["quick_messages"] = data["quick_messages"]
        update_data["updated_at"] = datetime.now()
        db.settings.update_one(
            {"key": "ai_config"},
            {"$set": update_data},
            upsert=True
        )
        add_log("AI settings updated by Director.", "core")
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========================================================
#  API — ERP INVENTORY (Read-Only)
# ========================================================

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    """Returns all inventory items from the ERP collection (read-only)."""
    db = hein_engine.db_manager.db
    if db is None:
        return jsonify({"error": "No database connection", "items": []}), 503
    try:
        search = request.args.get('search', '').strip()
        query = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"title": {"$regex": search, "$options": "i"}}, # Added title (common in ERPs)
                {"color": {"$regex": search, "$options": "i"}},
                {"type": {"$regex": search, "$options": "i"}},
            ]
        # Switching to 'products' collection as per user's live DB
        items = list(db.products.find(query, {"_id": 0}).limit(200))
        return jsonify({"items": items, "total": len(items)})
    except Exception as e:
        return jsonify({"error": str(e), "items": []}), 500

# ========================================================
#  API — TEAM / MANAGER ALERTS
# ========================================================

@app.route('/api/managers', methods=['GET'])
def get_managers():
    """Returns the list of enabled manager numbers for alerts."""
    managers = hein_engine.db_manager.get_managers()
    # Serialize for JSON
    for m in managers: m.pop('_id', None)
    return jsonify({"managers": managers})

@app.route('/api/managers', methods=['POST'])
def add_manager():
    """Adds a new manager number to the alert list."""
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    if not name or not phone:
        return jsonify({"error": "Name and Phone required"}), 400
    
    # Clean phone (remove +, spaces)
    phone = ''.join(filter(str.isdigit, phone))
    hein_engine.db_manager.add_manager(name, phone)
    add_log(f"New manager added: {name} (+{phone})", "core")
    return jsonify({"status": "added"})

@app.route('/api/managers/delete', methods=['POST'])
def remove_manager():
    """Removes a manager number from alerts."""
    data = request.json
    phone = data.get('phone')
    if not phone:
        return jsonify({"error": "Phone required"}), 400
    
    hein_engine.db_manager.remove_manager(phone)
    add_log(f"Manager removed (+{phone})", "core")
    return jsonify({"status": "removed"})

@app.route('/api/customers/flag', methods=['POST'])
def flag_customer():
    """Manually flag/unflag a customer for intervention."""
    try:
        db = hein_engine.db_manager.db
        if db is None: return jsonify({"error": "No DB"}), 503
        data = request.json
        phone = data.get('phone')
        flag = data.get('flag', True)
        
        db.customers.update_one({"phone": phone}, {"$set": {"awaiting_human": flag}})
        return jsonify({"status": "updated"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========================================================
#  API — AGENTS STATUS (Dynamic)
# ========================================================

@app.route('/api/agents', methods=['GET'])
def get_agents_status():
    db = hein_engine.db_manager.db
    agents = [
        {
            "id": "calendar",
            "name": "Calendar Agent",
            "avatar": "C",
            "color": "cal",
            "status": "online" if hein_engine.google_manager else "idle",
            "task": "Google Calendar connected." if hein_engine.google_manager else "No Google credentials."
        },
        {
            "id": "research",
            "name": "Research Agent",
            "avatar": "R",
            "color": "res",
            "status": "online",
            "task": "Gemini-powered market research active."
        },
        {
            "id": "memory",
            "name": "Memory Agent (MongoDB)",
            "avatar": "M",
            "color": "mail",
            "status": "online" if db is not None else "idle",
            "task": f"{db.customers.count_documents({})} customers in memory." if db is not None else "No DB connection."
        },
        {
            "id": "whatsapp",
            "name": "WhatsApp Gateway",
            "avatar": "W",
            "color": "wp",
            "status": "online" if wa_service.provider else "idle",
            "task": wa_service.get_status()["label"]
        }
    ]
    return jsonify(agents)

# ========================================================
#  MAIN
# ========================================================

if __name__ == "__main__":
    import sys
    # Forcing utf-8 encoding for standard output if needed, but safer to just use ascii
    print("\n" + "=" * 55)
    print("   [READY] HEIN AI COMMAND CENTER - FULLY OPERATIONAL")
    print("=" * 55)
    print(f"   Dashboard:  http://127.0.0.1:5000")
    print(f"   WhatsApp:   http://127.0.0.1:5000/webhook")
    # ASCII Clean for WA Status
    try:
        wa_label = wa_service.get_status()['label']
        safe_label = str(wa_label).encode('ascii', 'ignore').decode('ascii')
        print(f"   WA Status:  {safe_label}")
    except:
        print("   WA Status:  [UNKNOWN]")
        
    if hein_engine.db_manager.db is not None:
        print(f"   MongoDB:    [CONNECTED]")
    else:
        print(f"   MongoDB:    [DISCONNECTED]")
    print("=" * 55 + "\n")
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
