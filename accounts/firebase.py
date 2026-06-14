import firebase_admin
from firebase_admin import credentials
from laundrymart import settings
print("Initializing Firebase Admin SDK with credentials from:", settings.FIREBASE_CREDENTIALS_PATH)
if not firebase_admin._apps:
  cred = credentials.Certificate(
    settings.FIREBASE_CREDENTIALS_PATH
  )

  firebase_admin.initialize_app(cred)