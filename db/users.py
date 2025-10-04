# mongo_setup.py
from pymongo import MongoClient
from datetime import datetime
from vars import *

# --- 1) Connect ---
client = MongoClient(MONGO_URI)
db = client["botdb"]

# --- 2) Collections ---
users_col = db["users"]
balances_col = db["balances"]
settings_col = db["settings"]

# --- 3) Functions ---

# Users
def add_user(user_id, username=None, status="unban"):
    users_col.update_one(
        {"user_id": user_id},
        {"$setOnInsert": {"joined_at": datetime.utcnow()},
         "$set": {"username": username, "status": status}},
        upsert=True
    )

def set_status(user_id, status):
    users_col.update_one({"user_id": user_id}, {"$set": {"status": status}})

# Balances
def set_balance(user_id, amount):
    balances_col.update_one(
        {"user_id": user_id},
        {"$set": {"balance": amount, "updated_at": datetime.utcnow()}},
        upsert=True
    )

def get_balance(user_id):
    doc = balances_col.find_one({"user_id": user_id})
    return doc.get("balance", 0) if doc else 0

# Settings
def set_welcome_message(text):
    settings_col.update_one(
        {"_id": "welcome_message"},
        {"$set": {"value": text, "updated_at": datetime.utcnow()}},
        upsert=True
    )

def get_welcome_message():
    doc = settings_col.find_one({"_id": "welcome_message"})
    return doc["value"] if doc else "👋 Welcome!"

