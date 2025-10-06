# support.py
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple

from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.enums import ParseMode as PM

from db import list_admins  # <-- your helper

# ====== Config ======
IST = timezone(timedelta(hours=5, minutes=30))
SUPPORT_LINK_TEXT = "🆘 Support"
SUPPORT_ACTIVE_TEXT = (
    "🆘 <b>Support mode is ON</b>\n"
    "Send any text, photos, videos, files, or voice messages.\n"
    "An admin will reply here.\n\n"
    "Tap <b>Close</b> to end support mode."
)

# Optional external support link (e.g., group or handle).
SUPPORT_EXTERNAL_URL = None  # e.g. "https://t.me/YourSupportHandle"

# ====== Runtime state ======
# Users in active support mode
SUPPORT_ACTIVE_USERS: set[int] = set()

# Map (admin_chat_id, admin_message_id) -> user_id
# When admin replies to one of these messages, we know which user to send to.
SUPPORT_LINKS: Dict[Tuple[int, int], int] = {}

# ====== Small keyboards ======
def kb_user_support_open() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🟢 Open Support", callback_data="support:open")]]
    if SUPPORT_EXTERNAL_URL:
        rows.append([InlineKeyboardButton("🔗 External Support", url=SUPPORT_EXTERNAL_URL)])
    return InlineKeyboardMarkup(rows)

def kb_user_support_active() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🔴 Close", callback_data="support:close")]]
    if SUPPORT_EXTERNAL_URL:
        rows.append([InlineKeyboardButton("🔗 External Support", url=SUPPORT_EXTERNAL_URL)])
    return InlineKeyboardMarkup(rows)

def kb_user_after_admin_reply() -> InlineKeyboardMarkup:
    # Shown to user after admin replies, so they can keep chatting
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 Reply to Support", callback_data="support:open"),
         InlineKeyboardButton("🔴 Close", callback_data="support:close")]
    ])

def kb_admin_contact_user(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Contact User", url=f"tg://user?id={user_id}")]
    ])

# ====== Helpers ======
async def _broadcast_to_admins(c: Client, m: Message):
    """Send user's message to all admins with a header. Store reply mapping."""
    user = m.from_user
    user_id = user.id
    uname = f"@{user.username}" if user and user.username else "(no username)"
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "No Name"
    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    header_text = (
        "<b>📩 Support Message</b>\n"
        f"• From: <a href='tg://user?id={user_id}'>{full_name}</a> "
        f"(<code>{user_id}</code>)\n"
        f"• Username: {uname}\n"
        f"• Time (IST): <code>{ts}</code>"
    )

    for admin in list_admins():
        try:
            # 1) Send header
            hdr = await c.send_message(
                chat_id=admin,
                text=header_text,
                parse_mode=PM.HTML,
                disable_web_page_preview=True,
                reply_markup=kb_admin_contact_user(user_id)
            )
            # 2) Copy user's message as a reply to header (preserves media)
            copied = await c.copy_message(
                chat_id=admin,
                from_chat_id=m.chat.id,
                message_id=m.id,
                reply_to_message_id=hdr.id
            )
            # Map both header and copied message to the user for reply detection
            SUPPORT_LINKS[(admin, hdr.id)] = user_id
            SUPPORT_LINKS[(admin, copied.id)] = user_id
        except Exception:
            # Ignore delivery failures to specific admins
            pass

# ====== Public entry points ======

# 1) User: start/continue support via command
@Client.on_message(filters.private & filters.command("support"))
async def support_cmd(c: Client, m: Message):
    SUPPORT_ACTIVE_USERS.add(m.from_user.id)
    await m.reply_text(
        SUPPORT_ACTIVE_TEXT,
        parse_mode=PM.HTML,
        reply_markup=kb_user_support_active()
    )

# 2) User: open/close via inline buttons
@Client.on_callback_query(filters.regex(r"^support:(open|close)$"))
async def support_toggle_cb(c: Client, q: CallbackQuery):
    action = q.data.split(":")[1]
    uid = q.from_user.id

    if action == "open":
        SUPPORT_ACTIVE_USERS.add(uid)
        try:
            await q.message.edit_text(
                SUPPORT_ACTIVE_TEXT,
                parse_mode=PM.HTML,
                reply_markup=kb_user_support_active()
            )
        except Exception:
            await q.message.reply_text(
                SUPPORT_ACTIVE_TEXT,
                parse_mode=PM.HTML,
                reply_markup=kb_user_support_active()
            )
        await q.answer("Support mode enabled.")
    else:
        SUPPORT_ACTIVE_USERS.discard(uid)
        try:
            await q.message.edit_text("✅ Support mode closed.", parse_mode=PM.HTML)
        except Exception:
            await q.message.reply_text("✅ Support mode closed.", parse_mode=PM.HTML)
        await q.answer("Closed.")

# 3) User: any message while in support mode → relay to admins
#    (ignore commands starting with '/')
@Client.on_message(filters.private & ~filters.via_bot & ~filters.bot)
async def user_support_router(c: Client, m: Message):
    if m.text and m.text.startswith("/"):
        return  # let commands be handled elsewhere
    uid = m.from_user.id if m.from_user else m.chat.id
    if uid not in SUPPORT_ACTIVE_USERS:
        return  # not in support mode
    # Relay message to admins
    await _broadcast_to_admins(c, m)
    # Optional ack to user
    if m.text or m.caption:
        await m.reply_text("📨 Sent to support. Please wait for a reply.", quote=True)

# 4) Admin: reply to the forwarded/copy message to respond to user
@Client.on_message(filters.private & filters.reply)
async def admin_reply_router(c: Client, m: Message):
    # Only handle if admin and replying to one of the bot's mapped messages
    admin_id = m.from_user.id if m.from_user else m.chat.id
    key = (admin_id, m.reply_to_message.id if m.reply_to_message else -1)

    # Check admin privileges — optional if your bot is only used by admins
    # from db import is_admin
    try:
        from db import is_admin
        if not is_admin(admin_id):
            return
    except Exception:
        pass

    user_id = SUPPORT_LINKS.get(key)
    if not user_id:
        return  # not a tracked support reply

    # Ensure user is in active mode (so they can keep chatting)
    SUPPORT_ACTIVE_USERS.add(user_id)

    # Relay admin's reply to the user (copy to preserve media)
    try:
        await c.copy_message(
            chat_id=user_id,
            from_chat_id=m.chat.id,
            message_id=m.id
        )
        # Also send a tiny prompt so the user can continue easily
        await c.send_message(
            chat_id=user_id,
            text="👨‍💼 <b>Admin replied.</b> You can respond below.",
            parse_mode=PM.HTML,
            reply_markup=kb_user_after_admin_reply()
        )
        # Optional ack back to the admin
        await m.reply_text("✅ Sent to user.", quote=True)
    except Exception:
        await m.reply_text("❌ Failed to deliver to user.", quote=True)
