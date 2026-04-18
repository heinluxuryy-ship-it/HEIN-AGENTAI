import os
import datetime
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks'
]

logger = logging.getLogger(__name__)

class GoogleProductivityManager:
    def __init__(self):
        self.creds = self._authenticate()
        self.calendar_service = build('calendar', 'v3', credentials=self.creds)
        self.tasks_service = build('tasks', 'v1', credentials=self.creds)

    def _authenticate(self):
        """Handles the OAuth2 flow for Google APIs."""
        creds = None
        # Support for Serverless Environment (Vercel/Render)
        env_token = os.getenv("GOOGLE_TOKEN_JSON")
        
        if env_token:
            import json
            token_data = json.loads(env_token)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        elif os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        # If there are no (valid) credentials available, let the user log in (Only locally).
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except:
                    creds = None
            
            if not creds:
                if os.path.exists('credentials.json'):
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                    creds = flow.run_local_server(port=0, open_browser=True)
                else:
                    # On Vercel, we can't run local_server, so we log it
                    logger.warning("Google Auth failed. In serverless modes, set GOOGLE_TOKEN_JSON env var.")
                    return None
            
            # Save the credentials locally (Won't work on Vercel disk, but helpful for local setup)
            try:
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())
            except:
                pass
        return creds

    # --- CALENDAR TOOLS ---

    def create_event(self, summary, description, start_time_iso, duration_minutes=30):
        """Schedules a new meeting in Google Calendar."""
        if not self.calendar_service: return {"error": "Service not initialized"}

        try:
            start = start_time_iso # Format: '2024-05-28T09:00:00Z'
            end_dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00')) + datetime.timedelta(minutes=duration_minutes)
            end = end_dt.isoformat().replace('+00:00', 'Z')

            event = {
                'summary': f"HEIN Luxury: {summary}",
                'description': description,
                'start': {'dateTime': start, 'timeZone': 'UTC'},
                'end': {'dateTime': end, 'timeZone': 'UTC'},
                'reminders': {'useDefault': True},
            }

            event = self.calendar_service.events().insert(calendarId='primary', body=event).execute()
            return {"status": "success", "link": event.get('htmlLink'), "id": event.get('id')}
        except Exception as e:
            logger.error(f"Calendar Event Error: {e}")
            return {"error": str(e)}

    def list_upcoming_events(self, max_results=5):
        """Lists the next upcoming events."""
        if not self.calendar_service: return []
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = self.calendar_service.events().list(
            calendarId='primary', timeMin=now, maxResults=max_results, 
            singleEvents=True, orderBy='startTime').execute()
        return events_result.get('items', [])

    # --- TASKS TOOLS ---

    def create_task(self, title, notes=None, due_date_iso=None):
        """Creates a new task in Google Tasks."""
        if not self.tasks_service: return {"error": "Service not initialized"}
        
        task = {
            'title': f"HEIN-AI: {title}",
            'notes': notes
        }
        if due_date_iso:
            task['due'] = due_date_iso

        try:
            result = self.tasks_service.tasks().insert(tasklist='@default', body=task).execute()
            return {"status": "success", "id": result.get('id')}
        except Exception as e:
            logger.error(f"Task Error: {e}")
            return {"error": str(e)}

    def get_pending_tasks(self):
        """Lists incomplete tasks."""
        if not self.tasks_service: return []
        try:
            results = self.tasks_service.tasks().list(tasklist='@default', showCompleted=False).execute()
            return results.get('items', [])
        except Exception as e:
            logger.error(f"List Tasks Error: {e}")
            return []
