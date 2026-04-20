import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from hein_agent import HeinAgent
from whatsapp_service import WhatsAppService

load_dotenv()

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - HEIN-FOLLOWUP - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_followup(agent, phone, name):
    """Generates a high-end personalized follow-up."""
    prompt = (
        f"The prestigious client {name} (contact: {phone}) has not replied to our latest luxury acquisition proposal. "
        "Draft an exceptionally elite, polite, and exclusive follow-up message. "
        "Acknowledge their status and inquire if they desire to finalize the procurement or require further concierge assistance. "
        "Do not sound pushy; sound like a private executive assistant."
    )
    return agent.process_message(prompt, phone)

def run_followup_cycle(agent=None, wa_service=None):
    """
    Scans for aging leads and sends personalized AI follow-ups.
    """
    if not agent: agent = HeinAgent()
    if not wa_service: wa_service = WhatsAppService()
    
    db = agent.db_manager
    logger.info("Starting Elite Follow-up scan...")
    
    # 1. Identify leads who haven't interacted in more than 24 hours
    leads = db.get_aging_leads(hours=24)
    
    if not leads:
        logger.info("No leads require follow-up at this time.")
        return 0
    
    count = 0
    for lead in leads:
        phone = lead['phone']
        name = lead.get('name', 'Valued Client')
        
        followup_msg = generate_followup(agent, phone, name)
        wa_service.send_message(phone, followup_msg)
        
        db.db.customers.update_one(
            {"phone": phone},
            {"$set": {"followup_needed": False, "last_interaction": datetime.now()}}
        )
        count += 1
        time.sleep(1) # Gentle pacing
    
    return count

if __name__ == "__main__":
    try:
        sent_count = run_followup_cycle()
        logger.info(f"Automation cycle complete. Sent {sent_count} follow-ups.")
    except Exception as e:
        logger.error(f"Automation failed: {e}")
