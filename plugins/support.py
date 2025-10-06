# support.py
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from pyrogram import filters
from pyromod import Client
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.enums import ParseMode as PM

# IMPORTANT: somewhere in your app setup:
from pyromod import listen  # enables Client.ask()
from db import list_admins  # your existing helper

IST = timezone(timedelta(hours=5, minutes=30))
SUPPORT_TIMEOUT = 300  # seconds for ask()

# === small keyboards ===
def kb_user_after_send() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 Support again", callback_data="support:open")]
    ])

def kb_admin_reply(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ REPLY TO USER", callback_data=f"support:reply:{user_id}")]
    ])

def kb_admin_contact(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 CONTACT USER", url=f"tg://user?id={user_id}")]
    ])

# === helpers ===
async def _broadcast_user_msg_to_admins(c: Client, user_msg: Message):
    """Send a header + the user's message to all admins, with a REPLY button."""
    u = user_msg.from_user
    user_id = u.id
    uname = f"@{u.username}" if u and u.username else "(no username)"
    fname = u.first_name or "No"
    lname = u.last_name or "Name"
    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    header = (
        "<b>📩 Support Message</b>\n"
        f"• From: <a href='tg://user?id={user_id}'>{fname} {lname}</a> "
        f"(<code>{user_id}</code>)\n"
        f"• Username: {uname}\n"
        f"• Time (IST): <code>{ts}</code>"
    )

    for admin in list_admins():
        try:
            hdr = await c.send_message(
                chat_id=admin,
                text=header,
                parse_mode=PM.HTML,
                reply_markup=kb_admin_contact(user_id),
                disable_web_page_preview=True
            )
            # Copy the user's message (preserves media), and attach REPLY button
            copied = await c.copy_message(
                chat_id=admin,
                from_chat_id=user_msg.chat.id,
                message_id=user_msg.id,
                reply_to_message_id=hdr.id
            )
            await c.send_message(
                chat_id=admin,
                text="Tap to reply to user:",
                reply_to_message_id=copied.id,
                reply_markup=kb_admin_reply(user_id),
                parse_mode=PM.HTML
            )
        except Exception:
            pass  # ignore failures for specific admins

# === user entrypoint via callback ===
@Client.on_callback_query(filters.regex(r"^support:open$"))
async def cb_support_open(c: Client, q: CallbackQuery):
    uid = q.from_user.id
    await q.answer()  # dismiss spinner

    # Prompt + wait for the next message from the user (any type)
    try:
        prompt = await c.send_message(
            chat_id=uid,
            text=(
                "🆘 <b>Support</b>\n"
                "Send your message (text, photo, video, file, voice, etc.).\n"
                "Send <code>/cancel</code> to abort."
            ),
            parse_mode=PM.HTML
        )
        user_msg = await c.ask(
            chat_id=uid,
            text="⏳ Waiting for your support message…",
            timeout=SUPPORT_TIMEOUT
        )
    except asyncio.TimeoutError:
        await c.send_message(uid, "⌛ Timed out. Tap “Support again” to retry.", reply_markup=kb_user_after_send())
        return
    except Exception:
        await c.send_message(uid, "❌ Something went wrong. Try again.", reply_markup=kb_user_after_send())
        return

    # Handle cancel
    if user_msg.text and user_msg.text.strip().lower() in ("/cancel", "cancel"):
        await c.send_message(uid, "❎ Cancelled. Tap “Support again” to start over.", reply_markup=kb_user_after_send())
        return

    # Broadcast to admins
    await _broadcast_user_msg_to_admins(c, user_msg)

    # Ack to the user
    await c.send_message(
        chat_id=uid,
        text="📨 Sent to admins. You’ll receive a reply here.",
        reply_markup=kb_user_after_send()
    )

# === admin reply flow (button -> ask admin -> send to user) ===
@Client.on_callback_query(filters.regex(r"^support:reply:(\d+)$"))
async def cb_admin_reply(c: Client, q: CallbackQuery):
    user_id = int(q.matches[0].group(1))  # captured from regex
    admin_id = q.from_user.id

    # (Optional) guard: only allow admins
    try:
        from db import is_admin
        if not is_admin(admin_id):
            await q.answer("Admins only.", show_alert=True)
            return
    except Exception:
        pass

    await q.answer()  # dismiss spinner

    # Ask the admin for any message
    try:
        ask_msg = await c.send_message(
            chat_id=admin_id,
            text=(
                f"✍️ Send your reply for <code>{user_id}</code>.\n"
                "You can send text, media, files, or voice.\n"
                "Send <code>/cancel</code> to abort."
            ),
            parse_mode=PM.HTML
        )
        reply_msg = await c.ask(
            chat_id=admin_id,
            text="⏳ Waiting for your reply…",
            timeout=SUPPORT_TIMEOUT
        )
    except asyncio.TimeoutError:
        await c.send_message(admin_id, "⌛ Reply timed out.")
        return
    except Exception:
        await c.send_message(admin_id, "❌ Could not read your reply.")
        return

    # Handle cancel
    if reply_msg.text and reply_msg.text.strip().lower() in ("/cancel", "cancel"):
        await c.send_message(admin_id, "❎ Cancelled.")
        return

    # Relay admin message to the user (copy preserves media/captions)
    try:
        await c.send_message(
            chat_id=user_id,
            text="👨‍💼 <b>Admin replied.</b> You can respond below. THE MESSAGE BELOW IS SENT BY ADMIN",
            parse_mode=PM.HTML,
            reply_markup=kb_user_after_send()
        )
        await c.copy_message(
            chat_id=user_id,
            from_chat_id=admin_id,
            message_id=reply_msg.id
        )
        
        await c.send_message(admin_id, "✅ Sent to user.")
    except Exception:
        await c.send_message(admin_id, "❌ Failed to deliver to user.")
