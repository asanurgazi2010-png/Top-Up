import os, sqlite3, html, secrets
from datetime import datetime
import telebot
from telebot import types

# ============================================================
# TOPUP BOT — Manual Deposit + Force Join + Channel Orders
# Python file: topup_bot.py
# Admin ID: 8015166775
# No paid/third-party API required for manual mode.
# ============================================================

BOT_TOKEN=os.getenv("TOPUP_BOT_TOKEN","8890835649:AAHSwBgji-yXF-EhGzJAy68WTs8ZkDyxDnU")
ADMIN_ID=7631178809
DB="topup_bot.db"

if not BOT_TOKEN:
    raise SystemExit("Set TOPUP_BOT_TOKEN first.")

bot=telebot.TeleBot(BOT_TOKEN,parse_mode="HTML")
state={}

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT,
        balance REAL DEFAULT 0, joined_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS force_channels(
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT UNIQUE,
        title TEXT, invite_link TEXT NOT NULL, enabled INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS games(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
        enabled INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS packages(
        id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER,
        title TEXT, price REAL, enabled INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        game_id INTEGER, package_id INTEGER, player_id TEXT,
        zone_id TEXT DEFAULT '', price REAL, status TEXT DEFAULT 'Pending',
        created_at TEXT NOT NULL, channel_message_id INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS deposits(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
        method TEXT, sender TEXT, trx_id TEXT, status TEXT DEFAULT 'Pending',
        created_at TEXT NOT NULL, admin_message_id INTEGER DEFAULT 0)""")
    c.commit(); c.close()

def setting(key,default=""):
    c=db(); r=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone(); c.close()
    return r["value"] if r else default

def set_setting(key,value):
    c=db(); c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,value)); c.commit(); c.close()

def register(m):
    u=m.from_user; c=db()
    c.execute("INSERT OR IGNORE INTO users(user_id,first_name,username,joined_at) VALUES(?,?,?,?)",
              (u.id,u.first_name or "",u.username or "",datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    c.execute("UPDATE users SET first_name=?,username=? WHERE user_id=?",(u.first_name or "",u.username or "",u.id))
    c.commit(); c.close()

def admin(m): return m.from_user.id==ADMIN_ID

def force_channels():
    c=db(); rows=c.execute("SELECT * FROM force_channels WHERE enabled=1 ORDER BY id").fetchall(); c.close(); return rows

def is_joined(user_id,chat_id):
    try:
        member=bot.get_chat_member(chat_id,user_id)
        return member.status in ("member","administrator","creator")
    except Exception:
        return False

def joined_all(user_id):
    rows=force_channels()
    return all(is_joined(user_id,r["chat_id"]) for r in rows)

def join_keyboard():
    k=types.InlineKeyboardMarkup(row_width=1)
    for r in force_channels():
        k.add(types.InlineKeyboardButton("📢 "+(r["title"] or "Jᴏɪɴ Cʜᴀɴɴᴇʟ"),url=r["invite_link"]))
    k.add(types.InlineKeyboardButton("✅ Cʜᴇᴄᴋ Jᴏɪɴ",callback_data="check_join"))
    return k

def main_kb():
    k=types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton("👤 Pʀᴏғɪʟᴇ",style="primary"),types.KeyboardButton("💳 Dᴇᴘᴏsɪᴛ",style="success"))
    k.row(types.KeyboardButton("🎮 Tᴏᴘᴜᴘ",style="success"),types.KeyboardButton("🛒 Mʏ Oʀᴅᴇʀs",style="primary"))
    k.row(types.KeyboardButton("🎁 Rᴇғᴇʀ",style="success"),types.KeyboardButton("🎫 Sᴜᴘᴘᴏʀᴛ",style="primary"))
    return k

def admin_kb():
    k=types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton("📊 Dᴀsʜʙᴏᴀʀᴅ",style="primary"),types.KeyboardButton("🎮 Gᴀᴍᴇs",style="success"))
    k.row(types.KeyboardButton("📦 Pᴀᴄᴋᴀɢᴇs",style="success"),types.KeyboardButton("📢 Fᴏʀᴄᴇ Jᴏɪɴ",style="primary"))
    k.row(types.KeyboardButton("⚙️ Sᴇᴛᴛɪɴɢs",style="success"),types.KeyboardButton("📢 Bʀᴏᴀᴅᴄᴀsᴛ",style="primary"))
    k.row(types.KeyboardButton("🏠 Uѕᴇʀ Mᴇɴᴜ",style="danger"))
    return k

def deposit_admin_keyboard(did):
    k=types.InlineKeyboardMarkup(row_width=2)
    k.add(types.InlineKeyboardButton("✅ Aᴘᴘʀᴏᴠᴇ",callback_data=f"dep_ok:{did}"),
          types.InlineKeyboardButton("❌ Cᴀɴᴄᴇʟ",callback_data=f"dep_no:{did}"))
    return k

def order_admin_keyboard(oid):
    k=types.InlineKeyboardMarkup(row_width=2)
    k.add(types.InlineKeyboardButton("🟢 Cᴏᴍᴘʟᴇᴛᴇ",callback_data=f"ord_ok:{oid}"),
          types.InlineKeyboardButton("🔴 Cᴀɴᴄᴇʟ",callback_data=f"ord_no:{oid}"))
    return k

def send_order_channel(oid):
    channel=setting("order_channel","")
    if not channel:return
    c=db()
    o=c.execute("""SELECT o.*,u.first_name,u.username,g.name game,p.title package
                   FROM orders o JOIN users u ON u.user_id=o.user_id
                   JOIN games g ON g.id=o.game_id JOIN packages p ON p.id=o.package_id
                   WHERE o.id=?""",(oid,)).fetchone()
    c.close()
    if not o:return
    text=("🛒 <b>Nᴇᴡ Tᴏᴘᴜᴘ Oʀᴅᴇʀ</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
          f"🧾 Order: <code>#{oid}</code>\n"
          f"👤 User: {html.escape(o['first_name'] or 'User')}\n"
          f"🔗 @{html.escape(o['username']) if o['username'] else 'N/A'}\n"
          f"🆔 User ID: <code>{o['user_id']}</code>\n"
          f"🎮 Game: <b>{html.escape(o['game'])}</b>\n"
          f"📦 Package: <b>{html.escape(o['package'])}</b>\n"
          f"🆔 Player ID: <code>{html.escape(o['player_id'])}</code>\n"
          f"🌐 Zone ID: <code>{html.escape(o['zone_id'])}</code>\n"
          f"💰 Price: <code>{o['price']}৳</code>\n"
          f"🕐 {o['created_at']}\n\n🟡 <b>Pending</b>")
    try:
        sent=bot.send_message(channel,text,reply_markup=order_admin_keyboard(oid))
        c=db(); c.execute("UPDATE orders SET channel_message_id=? WHERE id=?",(sent.message_id,oid)); c.commit(); c.close()
    except Exception:
        pass

@bot.message_handler(commands=["start"])
def start(m):
    register(m)
    if force_channels() and not joined_all(m.from_user.id):
        bot.send_message(m.chat.id,
            "📢 <b>Cʜᴀɴɴᴇʟ Jᴏɪɴ Rᴇǫᴜɪʀᴇᴅ</b>\n\n"
            "Bot ব্যবহার করতে নিচের Channel-গুলোতে Join করুন।\n"
            "তারপর <b>✅ Cʜᴇᴄᴋ Jᴏɪɴ</b> চাপুন।",reply_markup=join_keyboard())
        return
    bot.send_message(m.chat.id,"🏠 <b>Wᴇʟᴄᴏᴍᴇ Tᴏ Tᴏᴘᴜᴘ Bᴏᴛ</b>\n\nআপনার service নির্বাচন করুন।",reply_markup=main_kb())

@bot.callback_query_handler(func=lambda c:c.data=="check_join")
def check_join(cq):
    if joined_all(cq.from_user.id):
        bot.answer_callback_query(cq.id,"✅ Join verified!")
        bot.send_message(cq.message.chat.id,"🎉 <b>Vᴇʀɪғɪᴇᴅ!</b>\nআপনি এখন Bot ব্যবহার করতে পারবেন।",reply_markup=main_kb())
    else:
        bot.answer_callback_query(cq.id,"❌ সব Channel-এ Join করুন।",show_alert=True)

def guarded(m):
    if force_channels() and not joined_all(m.from_user.id):
        bot.send_message(m.chat.id,"❌ আগে required Channel-এ Join করুন।",reply_markup=join_keyboard()); return False
    return True

@bot.message_handler(func=lambda m:m.text=="👤 Pʀᴏғɪʟᴇ")
def profile(m):
    if not guarded(m):return
    c=db(); u=c.execute("SELECT * FROM users WHERE user_id=?",(m.from_user.id,)).fetchone(); c.close()
    bot.send_message(m.chat.id,f"👤 <b>Pʀᴏғɪʟᴇ</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🆔 ID: <code>{u['user_id']}</code>\n👤 Name: {html.escape(u['first_name'])}\n🔗 @{html.escape(u['username']) if u['username'] else 'N/A'}\n💰 Balance: <code>{u['balance']:.2f}৳</code>")

@bot.message_handler(func=lambda m:m.text=="💳 Dᴇᴘᴏsɪᴛ")
def deposit(m):
    if not guarded(m):return
    method=setting("payment_method","bKash")
    number=setting("payment_number","Not set")
    minimum=float(setting("minimum_deposit","50"))
    state[m.from_user.id]={"step":"dep_amount"}
    bot.send_message(m.chat.id,f"💳 <b>Dᴇᴘᴏsɪᴛ</b>\n\n📱 Method: <b>{html.escape(method)}</b>\n📞 Number: <code>{html.escape(number)}</code>\n💰 Minimum: <code>{minimum:.0f}৳</code>\n\nকত টাকা Deposit করবেন?",reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m:m.text=="🎮 Tᴏᴘᴜᴘ")
def topup(m):
    if not guarded(m):return
    c=db(); rows=c.execute("SELECT * FROM games WHERE enabled=1 ORDER BY id").fetchall(); c.close()
    if not rows:bot.send_message(m.chat.id,"📭 কোনো Game এখনো যোগ করা হয়নি।");return
    k=types.InlineKeyboardMarkup(row_width=1)
    for r in rows:k.add(types.InlineKeyboardButton("🎮 "+r["name"],callback_data=f"game:{r['id']}"))
    bot.send_message(m.chat.id,"🎮 <b>Sᴇʟᴇᴄᴛ Gᴀᴍᴇ</b>",reply_markup=k)

@bot.callback_query_handler(func=lambda c:c.data.startswith("game:"))
def game(cq):
    if not joined_all(cq.from_user.id):return
    gid=int(cq.data.split(":")[1]); c=db(); rows=c.execute("SELECT * FROM packages WHERE game_id=? AND enabled=1 ORDER BY id",(gid,)).fetchall(); c.close()
    if not rows:bot.answer_callback_query(cq.id,"No packages.",show_alert=True);return
    k=types.InlineKeyboardMarkup(row_width=1)
    for r in rows:k.add(types.InlineKeyboardButton(f"📦 {r['title']} — {r['price']}৳",callback_data=f"pkg:{r['id']}"))
    bot.answer_callback_query(cq.id);bot.send_message(cq.message.chat.id,"📦 <b>Sᴇʟᴇᴄᴛ Pᴀᴄᴋᴀɢᴇ</b>",reply_markup=k)

@bot.callback_query_handler(func=lambda c:c.data.startswith("pkg:"))
def package(cq):
    if not joined_all(cq.from_user.id):return
    pid=int(cq.data.split(":")[1]); c=db(); p=c.execute("SELECT p.*,g.name game FROM packages p JOIN games g ON g.id=p.game_id WHERE p.id=?",(pid,)).fetchone(); c.close()
    if not p:return
    state[cq.from_user.id]={"step":"player","package_id":pid}
    bot.answer_callback_query(cq.id);bot.send_message(cq.message.chat.id,f"🎮 <b>{html.escape(p['game'])}</b>\n📦 {html.escape(p['title'])}\n💰 {p['price']}৳\n\n🆔 Player ID পাঠান।",reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m:m.text=="🛒 Mʏ Oʀᴅᴇʀs")
def orders(m):
    if not guarded(m):return
    c=db(); rows=c.execute("""SELECT o.*,g.name game,p.title package FROM orders o
        JOIN games g ON g.id=o.game_id JOIN packages p ON p.id=o.package_id
        WHERE o.user_id=? ORDER BY o.id DESC LIMIT 20""",(m.from_user.id,)).fetchall();c.close()
    if not rows:bot.send_message(m.chat.id,"🛒 <b>Mʏ Oʀᴅᴇʀs</b>\n\n📭 কোনো Order নেই।");return
    out=["🛒 <b>Mʏ Oʀᴅᴇʀs</b>\n━━━━━━━━━━━━━━━━━━━━"]
    for r in rows:out.append(f"\n🧾 <code>#{r['id']}</code> • {html.escape(r['game'])}\n📦 {html.escape(r['package'])}\n💰 {r['price']}৳ • <b>{r['status']}</b>")
    bot.send_message(m.chat.id,"\n".join(out))

@bot.message_handler(func=lambda m:m.text=="🎁 Rᴇғᴇʀ")
def refer(m):
    if not guarded(m):return
    bot.send_message(m.chat.id,"🎁 <b>Rᴇғᴇʀ</b>\n\nReferral system ready for expansion.")

@bot.message_handler(func=lambda m:m.text=="🎫 Sᴜᴘᴘᴏʀᴛ")
def support(m):
    if not guarded(m):return
    bot.send_message(m.chat.id,"🎫 <b>Sᴜᴘᴘᴏʀᴛ</b>\n\nAdmin-এর সাথে যোগাযোগ করুন।")

# ----------------------- ADMIN -----------------------

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    if admin(m):bot.send_message(m.chat.id,"👑 <b>Aᴅᴍɪɴ Pᴀɴᴇʟ</b>",reply_markup=admin_kb())

@bot.message_handler(func=lambda m:m.text=="📊 Dᴀsʜʙᴏᴀʀᴅ")
def dashboard(m):
    if not admin(m):return
    c=db();u=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"];o=c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"];d=c.execute("SELECT COUNT(*) n FROM deposits WHERE status='Pending'").fetchone()["n"];c.close()
    bot.send_message(m.chat.id,f"📊 <b>Dᴀsʜʙᴏᴀʀᴅ</b>\n\n👥 Users: <code>{u}</code>\n🛒 Orders: <code>{o}</code>\n💳 Pending Deposits: <code>{d}</code>",reply_markup=admin_kb())

@bot.message_handler(func=lambda m:m.text=="📢 Fᴏʀᴄᴇ Jᴏɪɴ")
def fj(m):
    if not admin(m):return
    state[ADMIN_ID]={"step":"fj"}
    bot.send_message(m.chat.id,"📢 Format:\n<code>Channel ID | Invite Link | Channel Name</code>\n\nExample: <code>-1001234567890 | https://t.me/example | Example Channel</code>",reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m:m.text=="⚙️ Sᴇᴛᴛɪɴɢs")
def settings(m):
    if not admin(m):return
    bot.send_message(m.chat.id,"⚙️ <b>Sᴇᴛᴛɪɴɢs</b>\n\n💳 Deposit settings এবং Order Channel configure করতে command ব্যবহার করুন:\n\n<code>/setpayment bKash | 01XXXXXXXXX | 50</code>\n<code>/setorderchannel @channelusername</code>",reply_markup=admin_kb())

@bot.message_handler(commands=["setpayment"])
def setpayment(m):
    if not admin(m):return
    p=[x.strip() for x in m.text.split(" ",1)[1].split("|",2)] if " " in m.text else []
    if len(p)!=3:bot.reply_to(m,"Format: /setpayment Method | Number | Minimum");return
    set_setting("payment_method",p[0]);set_setting("payment_number",p[1]);set_setting("minimum_deposit",p[2])
    bot.reply_to(m,"✅ Payment settings updated.")

@bot.message_handler(commands=["setorderchannel"])
def setorderchannel(m):
    if not admin(m):return
    if len(m.text.split(maxsplit=1))<2:bot.reply_to(m,"Format: /setorderchannel @channelusername");return
    set_setting("order_channel",m.text.split(maxsplit=1)[1].strip());bot.reply_to(m,"✅ Order Channel updated.")

@bot.message_handler(func=lambda m:m.text=="🎮 Gᴀᴍᴇs")
def games(m):
    if not admin(m):return
    state[ADMIN_ID]={"step":"game"};bot.send_message(m.chat.id,"🎮 Game Name পাঠান।",reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m:m.text=="📦 Pᴀᴄᴋᴀɢᴇs")
def packages_admin(m):
    if not admin(m):return
    state[ADMIN_ID]={"step":"package"};bot.send_message(m.chat.id,"📦 Format:\n<code>Game Name | Package Name | Price</code>",reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m:m.text=="📢 Bʀᴏᴀᴅᴄᴀѕᴛ")
def broadcast(m):
    if admin(m):state[ADMIN_ID]={"step":"broadcast"};bot.send_message(m.chat.id,"📢 Broadcast text পাঠান।")

@bot.message_handler(func=lambda m:m.text=="🏠 Uѕᴇʀ Mᴇɴᴜ")
def um(m):
    if admin(m):state.pop(ADMIN_ID,None);bot.send_message(m.chat.id,"🏠 User Menu",reply_markup=main_kb())

# ----------------------- DEPOSIT CALLBACKS -----------------------

@bot.callback_query_handler(func=lambda c:c.data.startswith("dep_ok:") or c.data.startswith("dep_no:"))
def deposit_decision(cq):
    if cq.from_user.id!=ADMIN_ID:return
    approve=cq.data.startswith("dep_ok:"); did=int(cq.data.split(":")[1])
    c=db();d=c.execute("SELECT * FROM deposits WHERE id=?",(did,)).fetchone()
    if not d or d["status"]!="Pending":c.close();bot.answer_callback_query(cq.id,"Already processed.",show_alert=True);return
    status="Approved" if approve else "Cancelled"
    c.execute("UPDATE deposits SET status=? WHERE id=?",(status,did))
    if approve:c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(d["amount"],d["user_id"]))
    c.commit();c.close()
    bot.answer_callback_query(cq.id,"✅ Approved!" if approve else "❌ Cancelled!",show_alert=True)
    try:bot.edit_message_reply_markup(cq.message.chat.id,cq.message.message_id,reply_markup=None)
    except Exception:pass
    bot.send_message(d["user_id"],f"💳 <b>Dᴇᴘᴏsɪᴛ {status.upper()}</b>\n\n💰 Amount: <code>{d['amount']}৳</code>\n🧾 TRX: <code>{html.escape(d['trx_id'])}</code>")

# ----------------------- ORDER CALLBACKS -------------------------

@bot.callback_query_handler(func=lambda c:c.data.startswith("ord_ok:") or c.data.startswith("ord_no:"))
def order_decision(cq):
    if cq.from_user.id!=ADMIN_ID:return
    complete=cq.data.startswith("ord_ok:");oid=int(cq.data.split(":")[1]);status="Completed" if complete else "Cancelled"
    c=db();o=c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
    if not o or o["status"]!="Pending":c.close();bot.answer_callback_query(cq.id,"Already processed.",show_alert=True);return
    c.execute("UPDATE orders SET status=? WHERE id=?",(status,oid));c.commit();c.close()
    bot.answer_callback_query(cq.id,"🟢 Completed!" if complete else "🔴 Cancelled!",show_alert=True)
    try:bot.edit_message_reply_markup(cq.message.chat.id,cq.message.message_id,reply_markup=None)
    except Exception:pass
    bot.send_message(o["user_id"],f"🛒 <b>Oʀᴅᴇʀ #{oid} {status.upper()}</b>\n\nআপনার Order status update হয়েছে।")

# ----------------------- STATE HANDLER --------------------------

@bot.message_handler(content_types=["text"])
def states(m):
    uid=m.from_user.id;s=state.get(uid)
    if not s:return

    if s["step"]=="dep_amount":
        try:amount=float(m.text.strip())
        except:bot.send_message(m.chat.id,"❌ সঠিক Amount দিন।");return
        minimum=float(setting("minimum_deposit","50"))
        if amount<minimum:bot.send_message(m.chat.id,f"❌ Minimum Deposit {minimum:.0f}৳");return
        state[uid]={"step":"dep_sender","amount":amount}
        bot.send_message(m.chat.id,"📞 যে Number থেকে টাকা পাঠিয়েছেন সেটি দিন।");return

    if s["step"]=="dep_sender":
        state[uid]["sender"]=m.text.strip();state[uid]["step"]="dep_trx";bot.send_message(m.chat.id,"🧾 Transaction ID দিন।");return

    if s["step"]=="dep_trx":
        amount=s["amount"];sender=s["sender"];trx=m.text.strip()
        c=db();cur=c.execute("""INSERT INTO deposits(user_id,amount,method,sender,trx_id,created_at)
            VALUES(?,?,?,?,?,?)""",(uid,amount,setting("payment_method","bKash"),sender,trx,datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        did=cur.lastrowid;c.commit();c.close();state.pop(uid,None)
        c=db();d=c.execute("""SELECT d.*,u.first_name,u.username FROM deposits d JOIN users u ON u.user_id=d.user_id WHERE d.id=?""",(did,)).fetchone();c.close()
        text=("💳 <b>Nᴇᴡ Dᴇᴘᴏsɪᴛ Rᴇǫᴜᴇsᴛ</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
              f"🧾 Request: <code>#{did}</code>\n👤 {html.escape(d['first_name'])}\n🔗 @{html.escape(d['username']) if d['username'] else 'N/A'}\n"
              f"🆔 User ID: <code>{uid}</code>\n💰 Amount: <code>{amount}৳</code>\n📱 Method: <b>{html.escape(d['method'])}</b>\n"
              f"📞 Sender: <code>{html.escape(sender)}</code>\n🧾 TRX: <code>{html.escape(trx)}</code>\n🕐 {d['created_at']}\n\n🟡 <b>Pending</b>")
        try:
            sent=bot.send_message(ADMIN_ID,text,reply_markup=deposit_admin_keyboard(did))
            c=db();c.execute("UPDATE deposits SET admin_message_id=? WHERE id=?",(sent.message_id,did));c.commit();c.close()
        except Exception:pass
        bot.send_message(uid,"✅ <b>Deposit Request Submitted!</b>\n\nAdmin verification-এর পর Balance add হবে।",reply_markup=main_kb());return

    if s["step"]=="player":
        pid=s["package_id"];c=db();p=c.execute("SELECT * FROM packages WHERE id=?",(pid,)).fetchone();u=c.execute("SELECT balance FROM users WHERE user_id=?",(uid,)).fetchone();c.close()
        if not p:return
        if u["balance"]<p["price"]:
            state.pop(uid,None);bot.send_message(m.chat.id,"❌ পর্যাপ্ত Balance নেই। আগে Deposit করুন।",reply_markup=main_kb());return
        state[uid]={"step":"zone","package_id":pid,"player_id":m.text.strip()}
        bot.send_message(m.chat.id,"🌐 Zone/Server ID পাঠান। না থাকলে <code>0</code> লিখুন।");return

    if s["step"]=="zone":
        pid=s["package_id"];player=s["player_id"];zone=m.text.strip()
        c=db();p=c.execute("SELECT * FROM packages WHERE id=?",(pid,)).fetchone();u=c.execute("SELECT balance FROM users WHERE user_id=?",(uid,)).fetchone()
        if not p or u["balance"]<p["price"]:c.close();state.pop(uid,None);bot.send_message(m.chat.id,"❌ Balance পরিবর্তিত হয়েছে। আবার চেষ্টা করুন।",reply_markup=main_kb());return
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",(p["price"],uid,p["price"]))
        cur=c.execute("""INSERT INTO orders(user_id,game_id,package_id,player_id,zone_id,price,created_at)
            VALUES(?,?,?,?,?,?,?)""",(uid,p["game_id"],pid,player,zone,p["price"],datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        oid=cur.lastrowid;c.commit();c.close();state.pop(uid,None)
        send_order_channel(oid)
        bot.send_message(uid,f"🛒 <b>Oʀᴅᴇʀ Pʟᴀᴄᴇᴅ!</b>\n\n🧾 Order: <code>#{oid}</code>\n💰 Paid: <code>{p['price']}৳</code>\n🟡 Status: <b>Pending</b>",reply_markup=main_kb());return

    if uid==ADMIN_ID and s["step"]=="fj":
        p=[x.strip() for x in m.text.split("|",2)]
        if len(p)!=3:bot.send_message(m.chat.id,"❌ Format ভুল।");return
        c=db();c.execute("INSERT OR REPLACE INTO force_channels(chat_id,title,invite_link,enabled) VALUES(?,?,?,1)",(p[0],p[2],p[1]));c.commit();c.close();state.pop(uid,None)
        bot.send_message(m.chat.id,"✅ Force Join Channel added.",reply_markup=admin_kb());return

    if uid==ADMIN_ID and s["step"]=="game":
        c=db();c.execute("INSERT OR IGNORE INTO games(name) VALUES(?)",(m.text.strip(),));c.commit();c.close();state.pop(uid,None);bot.send_message(m.chat.id,"✅ Game added.",reply_markup=admin_kb());return

    if uid==ADMIN_ID and s["step"]=="package":
        p=[x.strip() for x in m.text.split("|",2)]
        if len(p)!=3:bot.send_message(m.chat.id,"❌ Format ভুল।");return
        try:price=float(p[2])
        except:bot.send_message(m.chat.id,"❌ Price ভুল।");return
        c=db();g=c.execute("SELECT id FROM games WHERE name=?",(p[0],)).fetchone()
        if not g:c.close();bot.send_message(m.chat.id,"❌ Game আগে Add করুন।");return
        c.execute("INSERT INTO packages(game_id,title,price) VALUES(?,?,?)",(g["id"],p[1],price));c.commit();c.close();state.pop(uid,None);bot.send_message(m.chat.id,"✅ Package added.",reply_markup=admin_kb());return

    if uid==ADMIN_ID and s["step"]=="broadcast":
        c=db();rows=c.execute("SELECT user_id FROM users").fetchall();c.close();ok=bad=0
        for r in rows:
            try:bot.send_message(r["user_id"],m.text);ok+=1
            except:bad+=1
        state.pop(uid,None);bot.send_message(m.chat.id,f"📢 Broadcast Done\n✅ {ok} / ❌ {bad}",reply_markup=admin_kb())

if __name__=="__main__":
    init_db()
    print("🚀 Topup Bot started")
    bot.infinity_polling(skip_pending=True,timeout=60,long_polling_timeout=60)
