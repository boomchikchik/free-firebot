from bot import marimo as app
from db import *
from pyromod import Client
from pyrogram import filters
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChatWriteForbidden
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton,ReplyKeyboardRemove
from pyrogram.types import Message, CallbackQuery
from traceback import print_exc
from pyromod import listen
from typing import List, Tuple, Optional
import asyncio 


# === tiny helper: build fsub message & keyboard ===
# ========= Force-sub checker (returns (bool, InlineKeyboardMarkup|None)) =========
async def check_user_channel_membership(client: Client, user_id: int, CHANNEL_IDS):
    not_joined = []

    for channel_id in CHANNEL_IDS:
        try:
            m = await client.get_chat_member(channel_id, user_id)
            status = getattr(m, "status", None)
            # consider these as joined
            if str(status) not in ("member", "administrator", "creator"):
                not_joined.append(channel_id)
        except UserNotParticipant:
            not_joined.append(channel_id)
        except (ChatAdminRequired, ChatWriteForbidden):
            # Bot lacks rights/visibility → treat as missing (safer) but still show best-effort link
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
      username = user.username
    else:
      username = 'USER'
  except:
     print_exc()
     username= 'USER'
  try:
      keyboard = ReplyKeyboardMarkup(
          [[KeyboardButton('ADD FUNDS')],
                 [KeyboardButton('BUY DIAMONDS'),KeyboardButton('CHECK BALANCE')],
             [KeyboardButton('HOW TO USE'),KeyboardButton('STOCK')]],resize_keyboard=True
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


@Client.on_message(filters.private & filters.text)
async def reply_keyboard_handler(c: Client, m: Message):
    pass




