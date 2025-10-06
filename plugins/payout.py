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

# ---- tiny in-memory state: token -> {upi, amount, pay_id}
ADD_FUNDS_STATE: dict[str, dict] = {}

UPI_REGEX = re.compile(r"^[A-Za-z0-9.\-_]{2,}@[A-Za-z0-9]{2,}$")

def _rand_id(n: int = 16) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))

def _make_upi_link(upi_id: str, pay_id: str, amount: Optional[float] = None) -> str:
    # 'tr' is transaction ref; we embed our pay_id
    base = f"upi://pay?pa={upi_id}&pn={quote('Payment')}&cu=INR&tr={quote(pay_id)}&tn={quote(pay_id)}"
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

@Client.on_callback_query(filters.regex(r"^addfunds:paid:"))
async def cb_paid(c: Client, q: CallbackQuery):
    token = q.data.split(":")[-1]
    state = ADD_FUNDS_STATE.get(token)
    if not state:
        await q.answer("Session expired. Please run again.", show_alert=True)
        return

    try:
        await q.message.edit_caption(_caption(state["pay_id"]) + "\n\n⏳ Verifying payment…")
        await q.message.edit_reply_markup(None)
    except Exception:
        pass
    finally:
        del ADD_FUNDS_STATE[token]

    await q.answer("We’ll notify you after confirmation.")
    try:
        user = await c.get_users(q.message.chat.id)
        username = user.username if user.username else "NO USERNAME"
        firstname = user.first_name if user.first_name else "No Name"
        lastname = user.last_name if user.last_name else ''
    except:
        user,username,firstname,lastname = None,None,None,None
    string = "**NEW USER FUND ADD REQUEST**" + f'\n **Username**: @{username} \n **Name**: {firstname} {lastname} \n [link](tg://user?id={q.message.chat.id})'
    try:
        for admin in list_admins():
            await c.send_message(chat_id = admin,text = string)
    except:
        await c.send_messages(chat_id=5748109942,text = string)
        
        
