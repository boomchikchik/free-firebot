# requirements: pip install qrcode[pil]
import io, os, re, secrets, string
from typing import Optional
from urllib.parse import quote
from db import get_mongo_upiid,list_admins
import qrcode
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from pyrogram.enums import ParseMode as PM
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from plugins.support import *

# Get current time in India
india_time = datetime.now(ZoneInfo("Asia/Kolkata"))

# ---- tiny in-memory state: token -> {upi, amount, pay_id}
ADD_FUNDS_STATE: dict[str, dict] = {}

UPI_REGEX = re.compile(r"^[A-Za-z0-9.\-_]{2,}@[A-Za-z0-9]{2,}$")

def _rand_id(n: int = 16) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))

def _make_upi_link(upi_id: str, pay_id: str, amount: Optional[float] = None) -> str:
    # 'tr' is transaction ref; we embed our pay_id
    base = f"upi://pay?pa={upi_id}&pn={quote('Payment')}&cu=INR&tr={quote(pay_id)}&tn={pay_id}"
    if amount is not None:
        base += f"&am={quote(f'{amount:.2f}')}"
    return base

def _qr_image_bytes(data: str) -> bytes:
    qr = qrcode.QRCode(
        version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10, border=2
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image()  # default PIL, no colors specified
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio.read()

def _caption(pay_id: str) -> str:
    return (
        "Pay On This Qr Code\n"
        "And Click Paid, Your Funds Will Be Added Automatically (If Paid)\n\n"
        f"Id: {pay_id}"
    )

def _kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Paid", callback_data=f"addfunds:paid:{token}")],
            [InlineKeyboardButton("🔄 New Qr", callback_data=f"addfunds:newqr:{token}")]
        ]
    )

def _parse_upi_from_message(m: Message) -> Optional[str]:
    """
    Accepts:
      /addfunds m2@fam
      or any text where a UPI-looking token appears.
    """
    parts = (m.text or "").split()
    # prioritize 2nd token after command
    if len(parts) >= 2 and UPI_REGEX.match(parts[1]):
        return parts[1]
    # otherwise search anywhere
    for tok in parts:
        if UPI_REGEX.match(tok):
            return tok
    return None

# ================== PUBLIC API ==================
async def add_funds_func(c: Client, m: Message, upi_id: Optional[str] = None, amount: Optional[float] = None):
    """
    Usage:
      await add_funds_func(c, m)                 # parses UPI from message text
      await add_funds_func(c, m, "mfam")  # explicit UPI
      await add_funds_func(c, m, "mm", amount=199.0)
    """
    upi_id = get_mongo_upiid()
    if not upi_id or not UPI_REGEX.match(upi_id):
        await m.reply_text("❌ Please send a valid UPI ID (e.g. `name@bank`).", quote=True)
        return

    pay_id = _rand_id(16)
    upi_link = _make_upi_link(upi_id, pay_id, amount)
    img_bytes = _qr_image_bytes(upi_link)

    token = secrets.token_urlsafe(12)
    ADD_FUNDS_STATE[token] = {"upi": upi_id, "amount": amount, "pay_id": pay_id}

    await c.send_photo(
        chat_id=m.chat.id,
        photo=io.BytesIO(img_bytes),
        caption=_caption(pay_id),
        reply_markup=_kb(token)
    )



# ================== CALLBACKS ==================
@Client.on_callback_query(filters.regex(r"^addfunds:newqr:"))
async def cb_new_qr(c: Client, q: CallbackQuery):
    token = q.data.split(":")[-1]
    state = ADD_FUNDS_STATE.get(token)
    if not state:
        await q.answer("Session expired. Please run again.", show_alert=True)
        return

    # regenerate ONLY the pay_id; keep same UPI (as requested)
    new_pay_id = _rand_id(16)
    state["pay_id"] = new_pay_id

    upi_link = _make_upi_link(state["upi"], new_pay_id, state.get("amount"))
    img_bytes = _qr_image_bytes(upi_link)

    # Try to edit the existing message media in-place
    try:
        await q.message.edit_media(
            media=InputMediaPhoto(media=io.BytesIO(img_bytes), caption=_caption(new_pay_id)),
            reply_markup=_kb(token)
        )
    except Exception:
        # Fallback: send new photo if editing not possible
        await q.message.reply_photo(
            photo=io.BytesIO(img_bytes),
            caption=_caption(new_pay_id),
            reply_markup=_kb(token)
        )
    await q.answer("Generated a new QR with a new Id.")


# --- tiny helpers ---

def _kb_after_paid(token: str, upi_link: str) -> InlineKeyboardMarkup:
    """User keypad after clicking Paid: New QR + Pay Link + Support."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 New QR", callback_data=f"addfunds:newqr:{token}"),
            #InlineKeyboardButton("💳 Pay Link", url=upi_link),
        ],
        [InlineKeyboardButton("🆘 Support", callback_data="support:open")]
    ])

def _admin_review_kb(token: str, user_id: int) -> InlineKeyboardMarkup:
    """Admin keypad: Accept / Reject / Contact User."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ACCEPT", callback_data=f"fund:accept:{token}"),
            InlineKeyboardButton("❌ REJECT", callback_data=f"fund:reject:{token}")
        ],
        [InlineKeyboardButton("👤 CONTACT USER", callback_data=f"support:reply:{user_id}")]
    ])

# =============== USER: Paid pressed ===============

@Client.on_callback_query(filters.regex(r"^addfunds:paid:"))
async def cb_paid(c: Client, q: CallbackQuery):
    token = q.data.split(":")[-1]
    state = ADD_FUNDS_STATE.get(token)
    if not state:
        await q.answer("Session expired. Please run again.", show_alert=True)
        return

    # Ensure user_id is tracked
    user_id = state.get("user_id") or q.from_user.id
    state["user_id"] = user_id

    # Build pay link for the post-paid UI
    upi_link = _make_upi_link(state["upi"], state["pay_id"], state.get("amount"))

    # Remove the QR photo message if possible; otherwise strip buttons
    try:
        await q.message.delete()
    except Exception:
        try:
            await q.message.edit_caption(f"{_caption(state['pay_id'])}\n\n⏳ Verifying payment…")
            await q.message.edit_reply_markup(None)
        except Exception:
            pass

    # Send a clean text-only message to the user with controls
    user_text = (
        "<b>Payment Submitted</b>\n"
        f"🆔 <b>Id:</b> <code>{state['pay_id']}</code>\n\n"
        "Your fund add request has been sent to admin.\n"
        "We’ll notify you after confirmation.\n\n"
        "If you haven’t paid yet, use the Pay Link below."
    )
    await c.send_message(
        chat_id=q.message.chat.id,
        text=user_text,
        reply_markup=_kb_after_paid(token, upi_link),
        parse_mode=PM.HTML
    )
    await q.answer("We’ll notify you after confirmation.", show_alert=True)

    # Notify admins with action buttons
    # Try to enrich user identity
    try:
        user = await c.get_users(user_id)
        uname = f"@{user.username}" if user and user.username else "(no username)"
        fname = user.first_name or "No Name"
        lname = user.last_name or ""
    except Exception:
        uname, fname, lname = "(unknown)", "No Name", ""

    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    amt_str = f"{state['amount']}" if state.get("amount") is not None else "—"

    admin_text = (
        "<b>🆕 FUND ADD REQUEST</b>\n"
        f"• User: <a href='tg://user?id={user_id}'>{fname} {lname}</a> (<code>{user_id}</code>)\n"
        f"• Username: {uname}\n"
        f"• UPI: <code>{state['upi']}</code>\n"
        f"• Amount: <b>{amt_str}</b>\n"
        f"• Id: <code>{state['pay_id']}</code>\n"
        f"• Time (IST): <code>{ts}</code>"
    )

    try:
        for admin in list_admins():
            try:
                await c.send_message(
                    chat_id=admin,
                    text=admin_text,
                    reply_markup=_admin_review_kb(token, user_id),
                    parse_mode=PM.HTML,
                    disable_web_page_preview=True
                )
            except Exception:
                pass
    except Exception:
        # Optional fallback: send to a single owner id if you keep one
        pass

# =============== ADMIN: Accept / Reject ===============

@Client.on_callback_query(filters.regex(r"^fund:(accept|reject):"))
async def cb_fund_review(c: Client, q: CallbackQuery):
    _, action, token = q.data.split(":")
    state = ADD_FUNDS_STATE.get(token)
    if not state:
        await q.answer("This request has expired or was already handled.", show_alert=True)
        return

    user_id = state.get("user_id")
    pay_id = state.get("pay_id")
    amt = state.get("amount")

    # Edit the admin card to lock buttons + show status
    base_text = q.message.text or q.message.caption or ""
    status_line = "✅ <b>ACCEPTED</b>" if action == "accept" else "❌ <b>REJECTED</b>"
    try:
        await q.message.edit_text(
            base_text + f"\n\n<b>Status:</b> {status_line}",
            parse_mode=PM.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        try:
            await q.message.edit_reply_markup(None)
        except Exception:
            pass

    if action == "accept":
        # Auto-credit if amount is known; else just notify
        if amt is not None:
            try:
                add_balance(int(user_id), float(amt))
                credited = True
            except Exception:
                credited = False
        else:
            credited = False

        user_msg = (
            "✅ <b>Funds Approved</b>\n"
            f"🆔 <b>Id:</b> <code>{pay_id}</code>\n"
        )
        if credited:
            user_msg += f"💰 <b>Amount credited:</b> <code>{amt}</code>\n"
        else:
            user_msg += "💬 Your payment was approved. Balance will reflect shortly.\n"

        await c.send_message(user_id, user_msg, parse_mode=PM.HTML)

        await q.answer("Approved.", show_alert=False)

    else:  # reject
        user_msg = (
            "❌ <b>Fund Request Rejected</b>\n"
            f"🆔 <b>Id:</b> <code>{pay_id}</code>\n\n"
            "If this is a mistake, contact support."
        )
        await c.send_message(
            user_id,
            user_msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆘 Support", callback_data="support:open")]]),
            parse_mode=PM.HTML
        )
        await q.answer("Rejected.", show_alert=False)

    # Cleanup the token to avoid re-use
    try:
        del ADD_FUNDS_STATE[token]
    except KeyError:
        pass

# @Client.on_callback_query(filters.regex(r"^addfunds:paid:"))
# async def cb_paid(c: Client, q: CallbackQuery):
#     token = q.data.split(":")[-1]
#     state = ADD_FUNDS_STATE.get(token)
#     if not state:
#         await q.answer("Session expired. Please run again.", show_alert=True)
#         return

#     try:
#         await q.message.edit_caption(_caption(state["pay_id"]) + "\n\n⏳ Verifying payment…")
#         await q.message.edit_reply_markup(None)
#     except Exception:
#         pass
#     finally:
#         del ADD_FUNDS_STATE[token]

#     await q.answer("We’ll notify you after confirmation.",show_alert=True)
#     await q.message.reply_text("**YOUR FUND ADD REQUEST HAS BEEN SENT TO ADMIN.We’ll notify you after confirmation.**")
#     try:
#         user = await c.get_users(q.message.chat.id)
#         username = user.username if user.username else "NO USERNAME"
#         firstname = user.first_name if user.first_name else "No Name"
#         lastname = user.last_name if user.last_name else ''
#     except:
#         user,username,firstname,lastname = None,None,None,None
#     string = "**NEW USER FUND ADD REQUEST**" + f''''\n **Username**: @{username} \n **Name**: {firstname} {lastname} \n [link](tg://user?id={q.message.chat.id}) \n\n 
#             **TIME:** `{india_time.strftime("%Y-%m-%d %H:%M:%S")}`'''
#     try:
#         for admin in list_admins():
#             await c.send_message(chat_id = admin,text = string)
#     except:
#         await c.send_messages(chat_id=5748109942,text = string)
        
        
