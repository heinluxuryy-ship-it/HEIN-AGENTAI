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

def run_followup_cycle():
    """
    Scans for aging leads and sends personalized AI follow-ups.
    """
    agent = HeinAgent()
    db = agent.db_manager
    wa_service = WhatsAppService()
    
    logger.info("Starting Follow-up scan...")
    logger.info(f"WhatsApp Interface: {wa_service.get_status()['label']}")
    
    # 1. Identify leads who haven't interacted in more than 24 hours
    leads = db.get_aging_leads(hours=24)
    
    if not leads:
        logger.info("No leads require follow-up at this time.")
        return

    logger.info(f"Found {len(leads)} leads for follow-up.")

    for lead in leads:
        phone = lead['phone']
        name = lead.get('name', 'Valued Client')
        
        # 2. Ask the AI to generate a personalized follow-up based on history
        prompt = f"The customer {name} hasn't replied to our luxury watch proposal in 24 hours. Send a polite, high-end follow-up message to check if they have any further questions or if they are ready to proceed with the purchase."
        
        logger.info(f"Generating follow-up for {phone}...")
        followup_msg = agent.process_message(prompt, phone)
        
        # 3. Code to SEND the message via WhatsApp API
        results = wa_service.send_message(phone, followup_msg)
        logger.info(f"Follow-up sent for {phone}: {followup_msg[:50]}... Status: {results.get('status')}")
        
        # 4. Mark as followed up in DB to avoid double texting
        db.db.customers.update_one(
            {"phone": phone},
            {"$set": {"followup_needed": False, "last_interaction": datetime.now()}} # Resetting interaction time
        )
        
        # Avoid rate limiting/spamming
        time.sleep(2)

if __name__ == "__main__":
    # This script can be run as a daily cron job
    try:
        run_followup_cycle()
        logger.info("Automation cycle complete.")
    except Exception as e:
        logger.error(f"Automation failed: {e}")
