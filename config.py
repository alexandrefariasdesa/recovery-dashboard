from dotenv import load_dotenv
import os

load_dotenv()

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")

# SendFlow
SENDFLOW_TOKEN = os.getenv("SENDFLOW_TOKEN", "")
SENDFLOW_BASE_URL = os.getenv("SENDFLOW_BASE_URL", "https://api.sendflow.app/v1")
SENDFLOW_GROUP_ID = os.getenv("SENDFLOW_GROUP_ID", "")

# Produto low ticket
LOW_TICKET_PRODUCT = os.getenv("LOW_TICKET_PRODUCT", "Posições Secretas")
