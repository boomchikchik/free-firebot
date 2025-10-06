from bot import marimo as app
from db import *
from pyromod import Client
import re
from pyrogram import filters
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChatWriteForbidden
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton,ReplyKeyboardRemove
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ChatMemberStatus
from traceback import print_exc
from pyromod import listen
from typing import List, Tuple, Optional
from plugins.payout import add_funds_func
import asyncio 

# ===================== ADMIN NOTIFY HELPER =====================

def get_admin_ids():
    """Fetch admin IDs fresh every time (no global variable)."""
    try:
        admins = list_admins()   # from db
    except Exception:
        admins = []

    ids = []
    for a in admins or []:
        try:
            ids.append(int(a))
        except Exception:
            # if db returns dicts or strings
            if isinstance(a, dict) and "user_id" in a:
                ids.append(int(a["user_id"]))
    return list(dict.fromkeys(ids))  # unique

def tg_mention(u):
    name = (u.first_name or "User").replace("[", "").replace("]", "")
    return f"[{name}](tg://user?id={u.id})"

async def notify_admins_purchase(c, buyer, item_name: str, price: int, kind: str):
    """Send purchase info to all current admins."""
    admin_ids = get_admin_ids()
    if not admin_ids:
        return
    msg = (
        "🛍️ *New Purchase Confirmed*\n"
        f"👤 Buyer: {tg_mention(buyer)} (`{buyer.id}`)\n"
        f"🧾 Item: *{item_name}*\n"
        f"💸 Amount: ₹{price}\n"
        f"🏷️ Type: {kind}\n"
    )
    for aid in admin_ids:
        try:
            await c.send_message(aid, msg, disable_web_page_preview=True)
        except Exception:
            pass


# === tiny helper: build fsub message & keyboard ===
# ========= Force-sub checker (returns (bool, InlineKeyboardMarkup|None)) =========
async def check_user_channel_membership(client: Client, user_id: int, CHANNEL_IDS):
    not_joined = []

    for channel_id in CHANNEL_IDS:
        try:
            m = await client.get_chat_member(channel_id, user_id)
            status = getattr(m, "status", None)
            status = str(status)
            # consider these as joined
            if status not in ('ChatMemberStatus.MEMBER', 'ChatMemberStatus.ADMINISTRATOR', 'ChatMemberStatus.CREATOR'):
                not_joined.append(channel_id)
        except UserNotParticipant:
            print('block2')
            not_joined.append(channel_id)
        except (ChatAdminRequired, ChatWriteForbidden):
            # Bot lacks rights/visibility → treat as missing (safer) but still show best-effort link
            print('block3')
            not_joined.append(channel_id)
        except Exception as e:
            print(f"Error checking {channel_id}: {e}")
            # Be conservative: require explicit success to pass
            not_joined.append(channel_id)

    if not not_joined:
        return True, None  # All joined

    # Build the inline keyboard (2 buttons per row) + Try Again
    buttons, row = [], []
    for i, cid in enumerate(not_joined):
        try:
            chat = await client.get_chat(cid)
            title = chat.title or "Channel"
            if getattr(chat, "username", None):
                invite_link = f"https://t.me/{chat.username}"
            else:
                # Try to create a fresh invite link (bot must be admin)
                try:
                    link = await client.create_chat_invite_link(chat.id, creates_join_request=False)
                    invite_link = link.invite_link
                except Exception:
                    # last fallback
                    invite_link = "https://t.me/"
        except Exception:
            title = f"Channel {cid}"
            invite_link = "https://t.me/"

        row.append(InlineKeyboardButton(text=f"➕ Join {title}", url=invite_link))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # Add Try Again button (re-check membership)
    buttons.append([InlineKeyboardButton("🔁 Try Again", callback_data="fs_try_again")])

    return False, InlineKeyboardMarkup(buttons)





@Client.on_message(filters.text & filters.private & filters.command('start'))
async def welcome_user(c: Client, m: Message):
  # user bootstrap
  if not user_exists(m.chat.id):
      add_user(m.chat.id)
      print('User Added')

  # ban gate
  if get_status(m.chat.id) == "ban":
      await m.reply_text("🚫 YOU ARE BANNED FROM USING THIS BOT. Please contact admin.")
      return

  # fetch your force-sub list
  try:
      F_SUB = list_force_subs()  # treat as CHANNEL_IDS
  except Exception:
      F_SUB = []

  if F_SUB:
      all_joined, keyboard = await check_user_channel_membership(c, m.from_user.id, F_SUB)
      print(all_joined)
      if not all_joined:
          await m.reply_text(
              "🚪 **Access Locked — Join to Use the Bot**\n\n"
              "Please join the required channel(s) below. After joining, tap **Try Again**.",
              reply_markup=keyboard,
              disable_web_page_preview=True
          )
          return
  try:
    user = await c.get_users(m.chat.id)
    if user.username:
      username = '@'+ user.username
    else:
      username = user.first_name
  except:
     print_exc()
     username= 'USER'
  try:
      keyboard = ReplyKeyboardMarkup(
          [[KeyboardButton('ADD FUNDS')],
                 [KeyboardButton('BUY DIAMONDS'),KeyboardButton('CHECK BALANCE')],
             [KeyboardButton('BUY MEMBERSHIP'),KeyboardButton('STOCK')]],resize_keyboard=True
      )
  except:
      print_exc()
      await message.reply_text('ERROR OCCURRED UNABLE TO OPEN KEYBOARD')
  if get_welcome_message().strip() == "👋 Welcome!":
    await m.reply_text(f"❤️ HEY {username}\n🔥 WELCOME TO \n OLD AND FRESH CCS SELLER BOT🔥",reply_markup = keyboard) 
  else:
    await m.reply_text(f"**❤️ HEY {username}\n{get_welcome_message()}**",reply_markup = keyboard)
    
    
    
  
# ========= Try Again handler (re-checks & proceeds if clear) =========
@Client.on_callback_query(filters.regex("^fs_try_again$"))
async def fs_try_again_handler(c: Client, q: CallbackQuery):
    try:
        await q.answer("Re-checking…")
    except Exception:
        pass

    try:
        F_SUB = list_force_subs()
    except Exception:
        F_SUB = []

    if F_SUB:
        all_joined, keyboard = await check_user_channel_membership(c, q.from_user.id, F_SUB)
        if not all_joined:
            # Still missing → update message in place
            try:
                await q.message.edit_text(
                    "⏳ **Still locked** — you haven’t joined all required channel(s) yet.\n\n"
                    "Join them below, then tap **Try Again**.",
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            except Exception:
                await q.message.reply_text(
                    "⏳ **Still locked** — you haven’t joined all required channel(s) yet.\n\n"
                    "Join them below, then tap **Try Again**.",
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            return

    # All good → unlock and proceed
    try:
        await q.message.edit_text("✅ You’re verified. Welcome!")
    except Exception:
        await q.message.reply_text("✅ You’re verified. Welcome!")
    await welcome_user(c,q.message)

@Client.on_callback_query(filters.regex("ADDADA FUNDS"))
async def fdghfgh_ddsgs(c,q):
    await add_funds_func(c,q.message)

from pyrogram.types import ReplyKeyboardMarkup

# ====== Data ======
DIAMOND_PACKS = [310, 520, 1060, 2180, 5600]
MEMBERSHIPS = [
    "Weekly + Weekly Lite",
    "Monthly",
    "Monthly + Weekly",
]

# ====== Helper ======
def chunk(seq, size):
    """Split list into sublists of 'size' elements."""
    return [seq[i:i+size] for i in range(0, len(seq), size)]

# ====== Handlers ======
async def buy_diamond_func(c, m):
    try:
        # 2 buttons per row
        keyboard = [[f"💎 {n} Diamond" for n in row] for row in chunk(DIAMOND_PACKS, 2)]
        keyboard.append(["🔙 Back"])  # Add back button

        await m.reply_text(
            "💎 Choose a Diamond Pack:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard,
                resize_keyboard=True,
                one_time_keyboard=False
            )
        )
    except Exception as e:
        await m.reply_text(f"⚠️ Error showing diamond options: {e}")

    try:
        pass
    except:
        pass


async def buy_membership_func(c, m):
    try:
        keyboard = [[name] for name in MEMBERSHIPS]
        keyboard.append(["🔙 Back"])  # Add back button

        await m.reply_text(
            "🪪 Choose a Membership:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard,
                resize_keyboard=True,
                one_time_keyboard=False
            )
        )
    except Exception as e:
        await m.reply_text(f"⚠️ Error showing membership options: {e}")

# ====== Price maps (from your image) ======
DIAMOND_PRICE = {
    310: 135,
    520: 175,
    1060: 375,
    2180: 669,
    5600: 1249,
}

MEMBERSHIP_PRICE = {
    "weekly + weekly lite": 135,
    "monthly": 499,
    "monthly + weekly": 599,
}

def _clean(s: str) -> str:
    """Basic normalizer for membership text."""
    return re.sub(r"\s+", " ", s).strip().lower()

def _extract_int(s: str) -> int | None:
    """Get the first integer in a string, e.g. '💎 310 Diamond' -> 310."""
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None

# ===== Pending purchase context (in-memory) =====
PENDING_PURCHASE = {}   # { user_id: {"item": str, "price": int, "kind": "diamond|membership"} }

def _deduct_balance_safe(user_id: int, price: int):
    """Deduct `price` from user's wallet using whatever setter you have."""
    bal = int(get_balance(user_id))
    new_bal = bal - int(price)
    # Try common setter names in your codebase:
    try:
        set_balance(user_id, new_bal); return new_bal
    except Exception:
        pass
    try:
        update_user_balance(user_id, new_bal); return new_bal
    except Exception:
        pass
    # Fallback via delta functions if available
    try:
        deduct_balance(user_id, int(price)); return int(get_balance(user_id))
    except Exception:
        pass
    try:
        add_balance(user_id, -int(price)); return int(get_balance(user_id))
    except Exception:
        pass
    raise RuntimeError("No balance setter found — implement set_balance/update_user_balance/deduct_balance/add_balance.")

async def _ask_confirm_keyboard(m: Message, item_name: str, price: int):
    kb = ReplyKeyboardMarkup(
        [["✅ Confirm Purchase"], ["❌ Cancel"], ["🔙 Back"]],
        resize_keyboard=True
    )
    await m.reply_text(
        f"🛒 *You are purchasing:*\n• {item_name}\n\n💰 *Price:* ₹{price}\n\nProceed?",
        reply_markup=kb
    )

async def _start_purchase(c, m, *, item_name: str, price: int, kind: str):
    user_id = m.from_user.id
    bal = int(get_balance(user_id))
    if bal < int(price):
        kb = ReplyKeyboardMarkup([["ADD FUNDS"], ["🔙 Back"]], resize_keyboard=True)
        await m.reply_text(
            f"❌ *Insufficient balance!*\n\n💰 Your balance: ₹{bal}\n🧾 Required: ₹{price}\n\nPlease *ADD FUNDS* and try again.",
            reply_markup=kb
        )
        return
    # save pending
    PENDING_PURCHASE[user_id] = {"item": item_name, "price": int(price), "kind": kind}
    await _ask_confirm_keyboard(m, item_name, price)


# ============ CONFIRMATION HANDLERS ============
async def diamond_confirmation(c, m, _):
    """
    _: e.g. '💎 310 Diamond', '310 Diamond', 'Diamond 520', etc.
    Replies: 'Price for 310 Diamond is ₹135'
    """
    try:
        qty = _extract_int(_ or "")
        if qty and qty in DIAMOND_PRICE:
            price = DIAMOND_PRICE[qty]
            await _start_purchase(c, m, item_name=f"{qty} Diamond", price=price, kind="diamond")
            # await m.reply_text(
            #     f"💎 Price for {qty} Diamond is ₹{price}"
            # )
        else:
            await m.reply_text("Please pick a valid diamond pack from the keyboard.")
    except Exception as e:
        await m.reply_text(f"⚠️ Couldn't fetch diamond price. Error: {e}")


async def membership_confirmation(c, m, _):
    """
    _: one of 'Weekly + Weekly Lite', 'Monthly', 'Monthly + Weekly'
    Replies: 'Price for Weekly + Weekly Lite is ₹135'
    """
    try:
        key = _clean(_ or "")
        # try exact
        if key in MEMBERSHIP_PRICE:
            price = MEMBERSHIP_PRICE[key]
            shown = _  # original text as typed by the user
            await _start_purchase(c, m, item_name=shown, price=price, kind="membership")
            # await m.reply_text(
            #     f"🪪 Price for {shown} is ₹{price}"
            # )
            return

        # try fuzzy (starts with or contains)
        for name, price in MEMBERSHIP_PRICE.items():
            if key.startswith(name) or name in key:
                # await m.reply_text(
                #     f"🪪 Price for {_} is ₹{price}"
                # )
                await _start_purchase(c, m, item_name=_, price=price, kind="membership")
                return

        await m.reply_text("Please pick a valid membership from the keyboard.")
    except Exception as e:
        await m.reply_text(f"⚠️ Couldn't fetch membership price. Error: {e}")

async def show_stock_message(c,m):
    await m.reply_text(get_stock_message())
    
@Client.on_message(filters.private & filters.text)
async def reply_keyboard_handler(c: Client, m: Message):
    text = m.text.strip().lower()

    if text == 'add funds':
        await add_funds_func(c,m)
    elif text == 'buy diamonds':
        await buy_diamond_func(c,m)
    elif text == 'check balance':
        keyboard_in = InlineKeyboardMarkup([[InlineKeyboardButton(text='➕ADD FUNDS', callback_data="ADDADA FUNDS") ]])
        await m.reply_text("**💳 YOUR BALANCE \n 💰 Available:**"+f" `{get_balance(m.chat.id)}` Rs"+"\n🔄 Click below to add funds ",reply_markup=keyboard_in)
    elif text == 'buy membership':
        await buy_membership_func(c,m)
    elif text == 'stock':
        await m.reply_text(get_stock_message())
    elif text.startswith('💎') and text.endswith('diamond'):
        await diamond_confirmation(c,m,m.text.strip())
    elif any(k in m.text.strip() for k in MEMBERSHIPS):
        await membership_confirmation(c,m,m.text.strip())
        # === Confirm / Cancel purchase ===
    if m.text == "✅ Confirm Purchase":
        uid = m.from_user.id
        ctx = PENDING_PURCHASE.get(uid)
        if not ctx:
            await m.reply_text("No pending purchase found.", reply_markup=ReplyKeyboardRemove())
            return
        item_name = ctx["item"]
        price = int(ctx["price"])
        kind = ctx["kind"]
        # re-check balance
        bal = int(get_balance(uid))
        if bal < price:
            kb = ReplyKeyboardMarkup([["ADD FUNDS"], ["🔙 Back"]], resize_keyboard=True)
            await m.reply_text(
                f"❌ Balance changed — not enough funds.\n\n💰 Balance: ₹{bal}\n🧾 Required: ₹{price}",
                reply_markup=kb
            )
            PENDING_PURCHASE.pop(uid, None)
            return
        # deduct
        try:
            new_bal = _deduct_balance_safe(uid, price)
        except Exception as e:
            await m.reply_text(f"⚠️ Could not debit your wallet. Error: {e}", reply_markup=ReplyKeyboardRemove())
            return
# (optional) log_purchase(uid, item_name, price)
        await m.reply_text(
            f"✅ *Purchase Successful!*\n\n🧾 Item: {item_name}\n💸 Paid: ₹{price}\n💰 New Balance: ₹{new_bal}",
            reply_markup=ReplyKeyboardRemove()
        )# notify admins (you already have notify_admins_purchase in your file)
        try:
            await notify_admins_purchase(c, m.from_user, item_name, price, kind)
        except Exception:
            pass
        PENDING_PURCHASE.pop(uid, None)
        return
    if m.text == "❌ Cancel":
        PENDING_PURCHASE.pop(m.from_user.id, None)
        await m.reply_text("❎ Purchase cancelled.", reply_markup=ReplyKeyboardRemove())
        return
    



