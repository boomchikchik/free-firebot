# mongo_setup.py
from pymongo import MongoClient
from datetime import datetime
from vars import *

# --- 1) Connect ---
mongo_client = MongoClient(MONGO_URI)
dbb = mongo_client["botdb"]

# --- 2) Collections ---
users_col = dbb["users"]
balances_col = dbb["balances"]
settings_col = dbb["settings"]

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
    """
    Set user's status to 'ban' or 'unban'.
    Returns the new status string.
    """
    if status not in ("ban", "unban"):
        raise ValueError("status must be 'ban' or 'unban'")
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"status": status}},
        upsert=True
    )
    return status


def get_status(user_id):
    """
    Return the user's current status ('ban'/'unban'), or None if not found.
    """
    doc = users_col.find_one({"user_id": user_id}, {"status": 1, "_id": 0})
    return doc.get("status") if doc else None


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

def set_stock_message(text):
    settings_col.update_one(
        {"_id": "stock_message"},
        {"$set": {"value": text, "updated_at": datetime.utcnow()}},
        upsert=True
    )

def get_stock_message():
    doc = settings_col.find_one({"_id": "stock_message"})
    return doc["value"] if doc else "STOCK AVAILABLE"



# --- 3.1) User existence ---
def user_exists(user_id) -> bool:
    """Return True if the user document exists."""
    return users_col.count_documents({"user_id": user_id}, limit=1) > 0


# --- 3.2) Admin helpers ---
# We'll keep a single settings doc: {_id: "admins", ids: [user_id, ...]}
def is_admin(user_id) -> bool:
    """Check if user_id is in the admins list."""
    doc = settings_col.find_one({"_id": "admins"}, {"ids": 1})
    return bool(doc and user_id in set(doc.get("ids", [])))

def add_admin(user_id):
    """Add user_id to admins list (idempotent)."""
    settings_col.update_one(
        {"_id": "admins"},
        {"$addToSet": {"ids": user_id}},
        upsert=True
    )
    # (Optional) mirror a flag on user doc for quick filtering:
    users_col.update_one({"user_id": user_id}, {"$set": {"is_admin": True}}, upsert=True)

def remove_admin(user_id):
    """Remove user_id from admins list (no-op if not present)."""
    settings_col.update_one(
        {"_id": "admins"},
        {"$pull": {"ids": user_id}},
        upsert=True
    )
    users_col.update_one({"user_id": user_id}, {"$unset": {"is_admin": ""}})


# --- 3.3) Balance helpers ---
def add_balance(user_id, amount: float):
    """
    Atomically add to a user's balance.
    Creates the balance doc if missing.
    """
    balances_col.update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": float(amount)},
            "$set": {"updated_at": datetime.utcnow()}
        },
        upsert=True
    )

def remove_balance(user_id, amount: float, floor_zero: bool = True):
    """
    Subtract from a user's balance. If floor_zero=True, it won't go below 0.
    (Simple read-modify-write; fine for bots. For strict atomic clamp, use a transaction.)
    """
    doc = balances_col.find_one({"user_id": user_id}, {"balance": 1})
    current = float(doc.get("balance", 0) if doc else 0)
    new_amt = current - float(amount)
    if floor_zero and new_amt < 0:
        new_amt = 0.0

    balances_col.update_one(
        {"user_id": user_id},
        {"$set": {"balance": new_amt, "updated_at": datetime.utcnow()}},
        upsert=True
    )

# --- 3.4) List all admins ---
def list_admins():
    """
    Return a list of admin user_ids.
    Falls back to users_col.is_admin if settings doc missing.
    """
    doc = settings_col.find_one({"_id": "admins"}, {"ids": 1})
    if doc and "ids" in doc:
        return list(doc["ids"])
    # fallback
    return [u["user_id"] for u in users_col.find({"is_admin": True}, {"user_id": 1, "_id": 0})]


# --- 3.5) User details (user_id, username, status, balance, joined_at) ---
def get_user_details(user_id):
    """
    Return a compact dict of user info + balance.
    Example:
    {
      'user_id': 123, 'username': 'mehul',
      'status': 'unban', 'is_admin': True,
      'balance': 150.0, 'joined_at': datetime(...)
    }
    """
    u = users_col.find_one(
        {"user_id": user_id},
        {"_id": 0, "user_id": 1, "username": 1, "status": 1, "is_admin": 1, "joined_at": 1}
    ) or {"user_id": user_id, "username": None, "status": None, "is_admin": False, "joined_at": None}

    b = balances_col.find_one({"user_id": user_id}, {"_id": 0, "balance": 1})
    balance = float(b["balance"]) if (b and "balance" in b) else 0.0

    u["balance"] = balance
    return u


# --- 3.6) Force-sub channels (store once globally) ---
# Stored as: {_id: "force_subs", ids: [chat_id1, chat_id2, ...]}
def add_force_sub(channel_id):
    """Add a channel/chat id to the force-sub list (idempotent)."""
    settings_col.update_one(
        {"_id": "force_subs"},
        {"$addToSet": {"ids": channel_id}},
        upsert=True
    )

def remove_force_sub(channel_id):
    """Remove a channel/chat id from the force-sub list."""
    settings_col.update_one(
        {"_id": "force_subs"},
        {"$pull": {"ids": channel_id}},
        upsert=True
    )

def list_force_subs():
    """Return a list of all force-sub channel/chat ids."""
    doc = settings_col.find_one({"_id": "force_subs"}, {"ids": 1})
    return list(doc.get("ids", [])) if doc else []


