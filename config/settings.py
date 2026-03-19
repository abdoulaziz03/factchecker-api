import os
from dotenv import load_dotenv
load_dotenv()

# --- MongoDB ---
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB  = os.environ.get("MONGO_DB", "factchecker")
COLLECTION_RAW   = "posts_bruts"
COLLECTION_CLEAN = "posts_propres"

# --- Bluesky API ---
BLUESKY_USERNAME = os.environ.get("BLUESKY_USERNAME", "")
BLUESKY_PASSWORD = os.environ.get("BLUESKY_PASSWORD", "")

# --- Mots-clés à surveiller ---
KEYWORDS = [
    "fake news",
    "rumeur",
    "intox",
    "vérification",
    "fact check",
]

# --- Machine Learning ---
NB_CLUSTERS  = 3
MAX_FEATURES = 5000

# --- API ---
API_HOST = "0.0.0.0"
API_PORT = 8000
