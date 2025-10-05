import asyncio
import re
from typing import Optional, Tuple, List

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import PeerIdInvalid, FloodWait
from pyrogram.enums import ParseMode as PM
from db import *
# ------------- utils -------------

def admin_only(func):
    async def wrapper(c: Client, m: Message, *args, **kwargs):
        uid = m.from_user.id if m.from_user else m.chat.id
        # if not is_admin(uid):
        #     await m.reply_text("⛔ Admins only.", parse_mode=PM.HTML)
        #     return
        return await func(c, m, *args, **kwargs)
    return wrapper

async def _resolve_user_id(c: Client, m: Message, arg: Optional[str]) -> Optional[int]:
    """
    Resolve target user:
      1) If replying, use replied user id.
      2) If numeric, use as int.
      3) If @username, resolve via get_users.
    """
    if m.reply_to_message and m.reply_to_message.from_user:
        return m.reply_to_message.from_user.id

    if not arg:
        return None

    arg = arg.strip()
    if arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
        return int(arg)

    if arg.startswith("@"):
        try:
            u = await c.get_users(arg)
            return u.id
        except Exception:
            return None

    # Try as raw username (without @)
    try:
        u = await c.get_users(f"@{arg}")
        return u.id
    except Exception:
        return None

async def _resolve_chat_id(c: Client, token: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Resolve chat/channel by @username or numeric id string.
    Returns (chat_id, title)
    """
    try:
        if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
            chat = await c.get_chat(int(token))
        else:
            if not token.startswith("@"):
                token = "@" + token
            chat = await c.get_chat(token)
        return chat.id, (chat.title or (chat.username and f"@{chat.username}") or "Channel")
    except Exception:
        return None, None

def _split_cmd_args(m: Message) -> List[str]:
    return (m.text or "").split(maxsplit=2)

# ------------- /adminpanel -------------

@Client.on_message(filters.private & filters.command("adminpanel"))
@admin_only
async def admin_panel(c: Client, m: Message):
    try:
        total_users = users_col.count_documents({})
    except Exception:
        total_users = 0

    admins = list_admins()
    fsubs = list_force_subs()
    upi = get_mongo_upiid()
    welcome = get_welcome_message()
    stock = get_stock_message()

    txt = (
        "🛠️ <b>Admin Panel</b>\n"
        f"• Users: <b>{total_users}</b>\n"
        f"• Admins: <b>{len(admins)}</b>\n"
        f"• Force-Subs: <b>{len(fsubs)}</b>\n"
        f"• UPI: <code>{upi}</code>\n"
        f"• Welcome: <code>{welcome[:60]}{'…' if len(welcome)>60 else ''}</code>\n"
        f"• Stock: <code>{stock[:60]}{'…' if len(stock)>60 else ''}</code>\n\n"

        "<b>Admin Commands</b>\n"
        "👑 <u>Admins</u>\n"
        "• <code>/addadmin [id|@user] (or reply)</code> – add admin\n"
        "• <code>/deladmin [id|@user] (or reply)</code> – remove admin\n"
        "• <code>/admins</code> – list admins\n\n"

        "🚫 <u>Users</u>\n"
        "• <code>/ban [id|@user] (or reply)</code> – ban user\n"
        "• <code>/unban [id|@user] (or reply)</code> – unban user\n"
        "• <code>/user [id|@user] (or reply)</code> – show user details\n\n"

        "💰 <u>Balances</u>\n"
        "• <code>/balance [id|@user] (or reply)</code> – show balance\n"
        "• <code>/addbal [id|@user] amount</code> – add balance\n"
        "• <code>/rembal [id|@user] amount</code> – remove balance (floors at 0)\n\n"

        "⚙️ <u>Settings</u>\n"
        "• <code>/setwelcome Your welcome text…</code>\n"
        "• <code>/getwelcome</code>\n"
        "• <code>/setstock Your stock text…</code>\n"
        "• <code>/getstock</code>\n"
        "• <code>/setupiid name@bank</code>\n"
        "• <code>/getupi</code>\n\n"

        "📢 <u>Force-Sub</u>\n"
        "• <code>/fsub_add [@channel | id]</code>\n"
        "• <code>/fsub_del [@channel | id]</code>\n"
        "• <code>/fsub_list</code>\n\n"

        "📣 <u>Broadcast</u>\n"
        "• <code>/broadcast Your message…</code> (sends to all users)\n"
    )
    await m.reply_text(txt, parse_mode=PM.HTML, disable_web_page_preview=True)

# ------------- Admins -------------

@Client.on_message(filters.private & filters.command("addadmin"))
@admin_only
async def cmd_addadmin(c: Client, m: Message):
    args = _split_cmd_args(m)
    target = await _resolve_user_id(c, m, args[1] if len(args) > 1 else None)
    if not target:
        await m.reply_text("Usage: <code>/addadmin [id|@user] (or reply)</code>", parse_mode=PM.HTML)
        return
    add_admin(target)
    await m.reply_text(f"✅ Added admin: <code>{target}</code>", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("deladmin"))
@admin_only
async def cmd_deladmin(c: Client, m: Message):
    args = _split_cmd_args(m)
    target = await _resolve_user_id(c, m, args[1] if len(args) > 1 else None)
    if not target:
        await m.reply_text("Usage: <code>/deladmin [id|@user] (or reply)</code>", parse_mode=PM.HTML)
        return
    remove_admin(target)
    await m.reply_text(f"✅ Removed admin: <code>{target}</code>", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("admins"))
@admin_only
async def cmd_admins(c: Client, m: Message):
    ids = list_admins()
    if not ids:
        await m.reply_text("No admins set.", parse_mode=PM.HTML)
        return
    lines = "\n".join([f"• <code>{i}</code>" for i in ids])
    await m.reply_text(f"<b>Admins</b>\n{lines}", parse_mode=PM.HTML)

# ------------- Users: ban/unban/details -------------

@Client.on_message(filters.private & filters.command("ban"))
@admin_only
async def cmd_ban(c: Client, m: Message):
    args = _split_cmd_args(m)
    target = await _resolve_user_id(c, m, args[1] if len(args) > 1 else None)
    if not target:
        await m.reply_text("Usage: <code>/ban [id|@user] (or reply)</code>", parse_mode=PM.HTML)
        return
    set_status(target, "ban")
    await m.reply_text(f"🚫 Banned <code>{target}</code>", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("unban"))
@admin_only
async def cmd_unban(c: Client, m: Message):
    args = _split_cmd_args(m)
    target = await _resolve_user_id(c, m, args[1] if len(args) > 1 else None)
    if not target:
        await m.reply_text("Usage: <code>/unban [id|@user] (or reply)</code>", parse_mode=PM.HTML)
        return
    set_status(target, "unban")
    await m.reply_text(f"✅ Unbanned <code>{target}</code>", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("user"))
@admin_only
async def cmd_user(c: Client, m: Message):
    args = _split_cmd_args(m)
    target = await _resolve_user_id(c, m, args[1] if len(args) > 1 else None)
    if not target:
        await m.reply_text("Usage: <code>/user [id|@user] (or reply)</code>", parse_mode=PM.HTML)
        return
    info = get_user_details(target)
    txt = (
        "<b>User Details</b>\n"
        f"• id: <code>{info.get('user_id')}</code>\n"
        f"• username: <code>{info.get('username')}</code>\n"
        f"• status: <code>{info.get('status')}</code>\n"
        f"• is_admin: <code>{bool(info.get('is_admin'))}</code>\n"
        f"• balance: <code>{info.get('balance')}</code>\n"
        f"• joined_at: <code>{info.get('joined_at')}</code>"
    )
    await m.reply_text(txt, parse_mode=PM.HTML)

# ------------- Balances -------------

@Client.on_message(filters.private & filters.command("balance"))
@admin_only
async def cmd_balance(c: Client, m: Message):
    args = _split_cmd_args(m)
    target = await _resolve_user_id(c, m, args[1] if len(args) > 1 else None)
    if not target:
        await m.reply_text("Usage: <code>/balance [id|@user] (or reply)</code>", parse_mode=PM.HTML)
        return
    bal = get_balance(target)
    await m.reply_text(f"💰 Balance of <code>{target}</code>: <b>{bal}</b>", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("addbal"))
@admin_only
async def cmd_addbal(c: Client, m: Message):
    # /addbal <id|@user> <amount>
    parts = (m.text or "").split()
    if len(parts) < 3:
        await m.reply_text("Usage: <code>/addbal [id|@user] amount</code>", parse_mode=PM.HTML)
        return
    target = await _resolve_user_id(c, m, parts[1])
    if not target:
        await m.reply_text("❌ Invalid user.", parse_mode=PM.HTML)
        return
    try:
        amount = float(parts[2])
    except ValueError:
        await m.reply_text("❌ Amount must be a number.", parse_mode=PM.HTML)
        return
    add_balance(target, amount)
    await m.reply_text(f"✅ Added <b>{amount}</b> to <code>{target}</code>.", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("rembal"))
@admin_only
async def cmd_rembal(c: Client, m: Message):
    # /rembal <id|@user> <amount>
    parts = (m.text or "").split()
    if len(parts) < 3:
        await m.reply_text("Usage: <code>/rembal [id|@user] amount</code>", parse_mode=PM.HTML)
        return
    target = await _resolve_user_id(c, m, parts[1])
    if not target:
        await m.reply_text("❌ Invalid user.", parse_mode=PM.HTML)
        return
    try:
        amount = float(parts[2])
    except ValueError:
        await m.reply_text("❌ Amount must be a number.", parse_mode=PM.HTML)
        return
    remove_balance(target, amount, floor_zero=True)
    await m.reply_text(f"✅ Removed <b>{amount}</b> from <code>{target}</code>.", parse_mode=PM.HTML)

# ------------- Settings (welcome/stock/UPI) -------------

@Client.on_message(filters.private & filters.command("setwelcome"))
@admin_only
async def cmd_setwelcome(c: Client, m: Message):
    text = m.text.split(maxsplit=1)
    if len(text) < 2:
        await m.reply_text("Usage: <code>/setwelcome Your welcome text…</code>", parse_mode=PM.HTML)
        return
    set_welcome_message(text[1])
    await m.reply_text("✅ Updated welcome message.", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("getwelcome"))
@admin_only
async def cmd_getwelcome(c: Client, m: Message):
    await m.reply_text(f"📜 <b>Welcome:</b>\n{get_welcome_message()}", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("setstock"))
@admin_only
async def cmd_setstock(c: Client, m: Message):
    text = m.text.split(maxsplit=1)
    if len(text) < 2:
        await m.reply_text("Usage: <code>/setstock Your stock text…</code>", parse_mode=PM.HTML)
        return
    set_stock_message(text[1])
    await m.reply_text("✅ Updated stock message.", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("getstock"))
@admin_only
async def cmd_getstock(c: Client, m: Message):
    await m.reply_text(f"📦 <b>Stock:</b>\n{get_stock_message()}", parse_mode=PM.HTML)

UPI_REGEX = re.compile(r"^[A-Za-z0-9.\-_]{2,}@[A-Za-z0-9]{2,}$")

@Client.on_message(filters.private & filters.command("setupiid"))
@admin_only
async def cmd_setupiid(c: Client, m: Message):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2 or not UPI_REGEX.match(parts[1]):
        await m.reply_text("Usage: <code>/setupiid name@bank</code>", parse_mode=PM.HTML)
        return
    set_upi_id(parts[1])
    await m.reply_text(f"✅ UPI set to <code>{parts[1]}</code>", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("getupi"))
@admin_only
async def cmd_getupi(c: Client, m: Message):
    await m.reply_text(f"💳 <b>UPI:</b> <code>{get_mongo_upiid()}</code>", parse_mode=PM.HTML)

# ------------- Force-Sub management -------------

@Client.on_message(filters.private & filters.command("fsub_add"))
@admin_only
async def cmd_fsub_add(c: Client, m: Message):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.reply_text("Usage: <code>/fsub_add [@channel | id]</code>", parse_mode=PM.HTML)
        return

    chat_id, title = await _resolve_chat_id(c, parts[1].strip())
    if not chat_id:
        await m.reply_text("❌ Could not resolve channel.", parse_mode=PM.HTML)
        return
    add_force_sub(chat_id)
    await m.reply_text(f"✅ Added Force-Sub: <b>{title}</b> (<code>{chat_id}</code>)", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("fsub_del"))
@admin_only
async def cmd_fsub_del(c: Client, m: Message):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.reply_text("Usage: <code>/fsub_del [@channel | id]</code>", parse_mode=PM.HTML)
        return

    token = parts[1].strip()
    chat_id = None
    if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
        chat_id = int(token)
        title = "Channel"
    else:
        chat_id, title = await _resolve_chat_id(c, token)

    if not chat_id:
        await m.reply_text("❌ Could not resolve channel.", parse_mode=PM.HTML)
        return

    remove_force_sub(chat_id)
    await m.reply_text(f"🗑️ Removed Force-Sub: <b>{title}</b> (<code>{chat_id}</code>)", parse_mode=PM.HTML)

@Client.on_message(filters.private & filters.command("fsub_list"))
@admin_only
async def cmd_fsub_list(c: Client, m: Message):
    ids = list_force_subs()
    if not ids:
        await m.reply_text("No Force-Sub channels set.", parse_mode=PM.HTML)
        return

    # Try to enrich with titles
    lines = []
    for cid in ids:
        title = None
        try:
            chat = await c.get_chat(cid)
            title = chat.title or (chat.username and f"@{chat.username}")
        except Exception:
            pass
        if title:
            lines.append(f"• <b>{title}</b> — <code>{cid}</code>")
        else:
            lines.append(f"• <code>{cid}</code>")

    await m.reply_text("<b>Force-Sub Channels</b>\n" + "\n".join(lines), parse_mode=PM.HTML)

# ------------- Broadcast (optional) -------------

@Client.on_message(filters.private & filters.command("broadcast"))
@admin_only
async def cmd_broadcast(c: Client, m: Message):
    # /broadcast Your message...
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.reply_text("Usage: <code>/broadcast Your message…</code>", parse_mode=PM.HTML)
        return

    text = parts[1]
    cursor = users_col.find({}, {"user_id": 1, "_id": 0})
    sent = 0
    failed = 0

    await m.reply_text("📣 Broadcast started…", parse_mode=PM.HTML)

    for doc in cursor:
        uid = int(doc["user_id"])
        try:
            await c.send_message(uid, text)
            sent += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await c.send_message(uid, text)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)  # gentle throttle

    await m.reply_text(
        f"✅ Broadcast finished.\n• Sent: <b>{sent}</b>\n• Failed: <b>{failed}</b>",
        parse_mode=PM.HTML
    )
