import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class WhatsAppService:
    """
    Unified WhatsApp messaging layer.
    Supports: Meta Cloud API, Twilio, or Simulation Mode (no credentials).
    """

    def __init__(self):
        logger.info(f"WhatsApp Service initialized.")

    @property
    def provider(self):
        """Returns the active WhatsApp provider (meta, twilio, bridge, or None)."""
        return self._detect_provider()

    def _detect_provider(self):
        """Auto-detects which WhatsApp provider is configured."""
        wa_token = os.getenv("WHATSAPP_TOKEN", "")
        wa_phone = os.getenv("WHATSAPP_PHONE_ID", "")
        twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "")

        # 1. Check Meta Cloud API FIRST (Production Priority)
        if wa_token and wa_phone and not wa_token.startswith("EAAP") and wa_phone != "xxxxxxxxxxxxxxx":
            return "meta"

        # 2. Check Twilio NEXT
        if twilio_sid and twilio_token and not twilio_sid.startswith("AC.") and twilio_sid != "AC...":
            return "twilio"

        # 3. Fallback to Local Node Bridge (Baileys)
        # We check both if it's reachable AND if it's authenticated
        try:
            res = requests.get("http://127.0.0.1:5001/status", timeout=2)
            if res.status_code == 200:
                data = res.json()
                if data.get("ready"):
                    return "bridge"
        except Exception:
            pass

        return None  # Simulation mode or awaiting connection

    def get_status(self):
        """Returns connection status for the dashboard with granular labels."""
        is_vercel = os.getenv('VERCEL') == '1'
        p = self.provider
        
        # Determine specific label
        if p == "meta":
            label = "Meta Cloud API ✅"
        elif p == "twilio":
            label = "Twilio ✅"
        elif p == "bridge":
            label = "WhatsApp Direct ✅"
        else:
            if is_vercel:
                label = "Meta API Required (Vercel Mode)"
                return {"provider": "vercel_limited", "connected": False, "label": label}
            
            # Check if bridge is actually running but not ready (needs QR)
            try:
                res = requests.get("http://127.0.0.1:5001/status", timeout=1)
                if res.status_code == 200:
                    label = "Awaiting QR Scan 📱"
                    return {"provider": "bridge", "connected": True, "label": label}
            except:
                pass
            label = "Not Configured"

        return {
            "provider": p or "not_configured",
            "connected": p is not None,
            "label": label
        }

    def send_message(self, to_number, message_body):
        """
        Sends a WhatsApp message to a given phone number.
        Falls back to simulation if no provider is set.
        """
        # Normalize number
        to_number = str(to_number).replace("+", "").replace(" ", "").replace("-", "")

        if self.provider == "bridge":
            return self._send_bridge(to_number, message_body)
        elif self.provider == "meta":
            return self._send_meta(to_number, message_body)
        elif self.provider == "twilio":
            return self._send_twilio(to_number, message_body)
        else:
            logger.warning(f"[SIMULATION] Would send to {to_number}: {message_body[:50]}...")
            return {
                "status": "simulated",
                "to": to_number,
                "message": message_body,
                "note": "WhatsApp not configured. Add credentials to .env to send real messages."
            }

    def _send_bridge(self, to_number, message_body):
        """Sends via local Node.js bridge."""
        try:
            response = requests.post("http://127.0.0.1:5001/send", json={
                "to": to_number,
                "message": message_body
            }, timeout=10)
            response.raise_for_status()
            logger.info(f"[BRIDGE] Message sent to {to_number}")
            return {"status": "sent", "provider": "bridge", "response": response.json()}
        except Exception as e:
            logger.error(f"[BRIDGE] Send failed: {e}")
            return {"status": "error", "error": str(e)}

    def _send_meta(self, to_number, message_body):
        """Sends via Meta Cloud API."""
        token = os.getenv("WHATSAPP_TOKEN")
        phone_id = os.getenv("WHATSAPP_PHONE_ID")
        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message_body}
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"[META] Message sent to {to_number}")
            return {"status": "sent", "provider": "meta", "response": response.json()}
        except Exception as e:
            logger.error(f"[META] Send failed: {e}")
            return {"status": "error", "error": str(e)}

    def _send_twilio(self, to_number, message_body):
        """Sends via Twilio API."""
        from twilio.rest import Client
        try:
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            from_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

            client = Client(account_sid, auth_token)
            message = client.messages.create(
                body=message_body,
                from_=from_number,
                to=f"whatsapp:+{to_number}"
            )
            logger.info(f"[TWILIO] Message sent to {to_number}, SID: {message.sid}")
            return {"status": "sent", "provider": "twilio", "sid": message.sid}
        except Exception as e:
            logger.error(f"[TWILIO] Send failed: {e}")
            return {"status": "error", "error": str(e)}

    def send_broadcast(self, phone_list, message_body):
        """Sends a broadcast message to a list of phone numbers."""
        results = []
        for phone in phone_list:
            result = self.send_message(phone, message_body)
            result["phone"] = phone
            results.append(result)
        return results
