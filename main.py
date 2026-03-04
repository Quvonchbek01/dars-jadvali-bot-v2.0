import asyncio
import os
import logging
from datetime import datetime, time as dtime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReactionTypeEmoji,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiohttp import web
from dotenv import load_dotenv

from db import (
    get_pool, create_db, register_user, get_user, is_banned,
    ban_user, unban_user, get_all_users, search_user,
    get_full_stats, get_user_stats, get_growth_chart,
    save_feedback, get_recent_feedback,
    log_schedule_view, set_reminder, toggle_reminder, get_active_reminders
)
from keyboards import (
    main_menu, back_menu, admin_menu,
    start_inline, reminder_class_inline, stats_inline,
    feedback_rating_inline, admin_broadcast_confirm_inline,
    admin_user_actions_inline, back_inline
)
from middlewares import ThrottleMiddleware, BanMiddleware
from schedule_data import SCHEDULE, DAYS, DAY_MAP, format_schedule

# ── CONFIG ────────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

TOKEN       = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT        = int(os.getenv("PORT", 10000))
ADMIN_ID    = 5883662749

bot = Bot(token=TOKEN, parse_mode="HTML")
dp  = Dispatcher(storage=MemoryStorage())

# ── MIDDLEWARES ───────────────────────────────────────────────────────────────
dp.message.middleware(ThrottleMiddleware(rate_limit=0.8))
dp.callback_query.middleware(ThrottleMiddleware(rate_limit=0.5))
dp.message.middleware(BanMiddleware())
dp.callback_query.middleware(BanMiddleware())

# ── FSM STATES ────────────────────────────────────────────────────────────────
class FeedbackState(StatesGroup):
    rating  = State()
    text    = State()

class BroadcastState(StatesGroup):
    text    = State()
    confirm = State()

class AdminState(StatesGroup):
    search_user = State()
    dm_user     = State()
    dm_target   = State()


# ═══════════════════════════════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════════════════════════════
@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()

    # DB orqada — foydalanuvchi kutmaydi
    asyncio.create_task(
        register_user(msg.from_user.id, msg.from_user.full_name, msg.from_user.username)
    )

    # Reaction qo'shish (premium)
    try:
        await bot.set_message_reaction(
            msg.chat.id, msg.message_id,
            [ReactionTypeEmoji(emoji="👋")]
        )
    except Exception:
        pass

    text = (
        f"👋 Salom, <b>{msg.from_user.first_name}</b>!\n\n"
        f"🏫 <b>Forish IM</b> dars jadvali botiga xush kelibsiz!\n\n"
        f"📚 <i>Bot haqidagi eng so'nggi yangiliklarni quyidagi kanal orqali kuzatib borishingiz mumkin: t.me/+zg9gHcIqry40YzMy</i>"
    )
    await msg.answer(text, reply_markup=main_menu())


# ═══════════════════════════════════════════════════════════════════════════════
#  📊 Mening statistikam
# ═══════════════════════════════════════════════════════════════════════════════
@dp.message(F.text == "📊 Mening statistikam")
async def user_stats_msg(msg: Message):
    await _send_user_stats(msg.from_user.id, msg)

@dp.callback_query(F.data == "my_stats")
async def user_stats_cb(cb: CallbackQuery):
    await cb.answer()
    await _send_user_stats(cb.from_user.id, cb.message, edit=True)

async def _send_user_stats(user_id: int, target, edit: bool = False):
    user, views, fav = await get_user_stats(user_id)
    if not user:
        text = "📊 Ma'lumot topilmadi."
    else:
        joined = user['joined_at'].strftime('%d.%m.%Y')
        last   = user['last_active'].strftime('%d.%m.%Y %H:%M')
        fav_cls = fav['class_name'] if fav else "—"

        # Mini progress bar
        level = min(user['usage_count'] // 10, 10)
        bar = "█" * level + "░" * (10 - level)

        text = (
            f"📊 <b>Sizning statistikangiz</b>\n\n"
            f"👤 Foydalanish soni: <b>{user['usage_count']}</b> marta\n"
            f"👁 Ko'rilgan jadvallar: <b>{views}</b> ta\n"
            f"🏆 Eng ko'p: <b>{fav_cls}</b>\n\n"
            f"📅 Ro'yxatdan o'tgan: <b>{joined}</b>\n"
            f"🕐 So'nggi faollik: <b>{last}</b>\n\n"
            f"<b>Faollik darajasi:</b>\n"
            f"<code>[{bar}]</code> {level * 10}%"
        )

    kb = stats_inline()
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass
    else:
        await target.answer(text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════════════════
#  ⏰ Eslatma
# ═══════════════════════════════════════════════════════════════════════════════
@dp.message(F.text == "⏰ Eslatma")
async def reminder_msg(msg: Message):
    await _show_reminder_menu(msg.from_user.id, msg)

@dp.callback_query(F.data == "reminder_menu")
async def reminder_cb(cb: CallbackQuery):
    await cb.answer()
    await _show_reminder_menu(cb.from_user.id, cb.message, edit=True)

async def _show_reminder_menu(user_id: int, target, edit: bool = False):
    from db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rem = await conn.fetchrow("SELECT class_name, enabled FROM reminders WHERE user_id=$1", user_id)

    status = "✅ Yoqilgan" if (rem and rem['enabled']) else "❌ O'chirilgan"
    cls = rem['class_name'] if rem else None

    text = (
        f"⏰ <b>Kunlik eslatma</b>\n\n"
        f"Har kuni ertalab <b>07:30</b> da bugungi dars jadvalingiz yuboriladi.\n\n"
        f"Holat: {status}\n"
        f"{'Sinf: <b>' + cls + '</b>' if cls else ''}\n\n"
        f"<i>Sinfingizni tanlang:</i>"
    )

    kb = reminder_class_inline(cls)
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass
    else:
        await target.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("set_reminder:"))
async def set_reminder_cb(cb: CallbackQuery):
    cls = cb.data.split(":")[1]
    await set_reminder(cb.from_user.id, cls)
    await cb.answer(f"✅ {cls} sinfi uchun eslatma yoqildi!", show_alert=True)
    await _show_reminder_menu(cb.from_user.id, cb.message, edit=True)

@dp.callback_query(F.data == "disable_reminder")
async def disable_reminder_cb(cb: CallbackQuery):
    result = await toggle_reminder(cb.from_user.id)
    if result is False:
        await cb.answer("⚠️ Avval sinfni tanlang", show_alert=True)
        return
    status = "yoqildi ✅" if result else "o'chirildi ❌"
    await cb.answer(f"Eslatma {status}", show_alert=True)
    await _show_reminder_menu(cb.from_user.id, cb.message, edit=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  💬 Fikr bildirish
# ═══════════════════════════════════════════════════════════════════════════════
@dp.message(F.text == "💬 Fikr bildirish")
async def feedback_start_msg(msg: Message, state: FSMContext):
    await state.set_state(FeedbackState.rating)
    await msg.answer(
        "⭐ <b>Botni baholang</b>\n\n"
        "Quyidagilardan birini tanlang: \n(Fikr bildirish funksiyasiga yaqin orada o'zgartirishlar kiritiladi.)",
        reply_markup=feedback_rating_inline()
    )

@dp.callback_query(F.data == "feedback_start")
async def feedback_start_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(FeedbackState.rating)
    await cb.message.edit_text(
        "⭐ <b>Botni baholang</b>\n\nQuyidagilardan birini tanlang:",
        reply_markup=feedback_rating_inline()
    )

@dp.callback_query(F.data.startswith("rate:"))
async def handle_rating(cb: CallbackQuery, state: FSMContext):
    rating = int(cb.data.split(":")[1])
    await state.update_data(rating=rating)
    await state.set_state(FeedbackState.text)
    await cb.answer()
    await cb.message.edit_text(
        f"{'⭐' * (rating // 2)} <b>Rahmat!</b>\n\n"
        f"✍️ Endi fikringizni yozing:\n"
        f"<i>Sizga botimizdagi nima yoqdi, yoki yoqmadi? Botimizni yanada yaxshiroq qilish uchun nimalar qila olamiz?</i>",
        reply_markup=back_inline("back_main")
    )

@dp.message(FeedbackState.text)
async def handle_feedback_text(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.clear()
        await msg.answer("🔙 Asosiy menyu", reply_markup=main_menu())
        return

    data = await state.get_data()
    rating = data.get('rating')

    await asyncio.gather(
        save_feedback(msg.from_user.id, msg.text, rating),
        bot.send_message(
            ADMIN_ID,
            f"💬 <b>Yangi fikr!</b>\n\n"
            f"👤 <a href='tg://user?id={msg.from_user.id}'>{msg.from_user.full_name}</a>\n"
            f"⭐ Baho: <b>{'⭐' * (rating // 2) if rating else 'Berilmagan'}</b>\n\n"
            f"📝 {msg.text}"
        )
    )

    # Reaction
    try:
        await bot.set_message_reaction(
            msg.chat.id, msg.message_id,
            [ReactionTypeEmoji(emoji="🙏")]
        )
    except Exception:
        pass

    await msg.answer(
        "✅ <b>Fikringiz qabul qilindi!</b>\n\nRahmat, tez orada javob beramiz. 🙏",
        reply_markup=main_menu()
    )
    await state.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  ℹ️ Yordam
# ═══════════════════════════════════════════════════════════════════════════════
@dp.message(F.text == "ℹ️ Yordam")
async def help_msg(msg: Message):
    await msg.answer(
        "ℹ️ <b>Yordam</b>\n\n"
        "📚 <b>Dars jadvali</b> — Web ilova orqali dars jadvalini ko'rish\n"
        "📊 <b>Statistika</b> — Faollik statistikangiz haqida ma'lumot\n"
        "⏰ <b>Eslatma</b> — Kunlik bildirishnoma (daily reminder)\n"
        "💬 <b>Fikr bildirish</b> — Taklif va shikoyatlar uchun\n\n"
        "📞 Admin: @from_america\n"
        "🌐 Kanal: t.me/+zg9gHcIqry40YzMy",
        reply_markup=main_menu()
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  ⬅️ Orqaga / back callbacks
# ═══════════════════════════════════════════════════════════════════════════════
@dp.message(F.text == "⬅️ Orqaga")
async def go_back(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🔙 Asosiy menyu", reply_markup=main_menu())

@dp.callback_query(F.data == "back_main")
async def back_main_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await cb.message.edit_text(
        f"👋 <b>{cb.from_user.first_name}</b>, asosiy menyu:",
        reply_markup=start_inline()
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  🛡 ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════
def admin_only(func):
    async def wrapper(event, *args, **kwargs):
        user_id = event.from_user.id

        if user_id != ADMIN_ID:
            if isinstance(event, types.Message):
                await event.answer("⛔ Siz admin emassiz.")
            elif isinstance(event, types.CallbackQuery):
                await event.answer("⛔ Siz admin emassiz.", show_alert=True)
            return

        return await func(event, *args, **kwargs)

    return wrapper

@dp.message(Command("admin"))
@admin_only
async def admin_panel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🛡 <b>Admin panel</b>", reply_markup=admin_menu())


# ── 📊 TO'LIQ STATISTIKA ──────────────────────────────────────────────────────
@dp.message(F.text == "📊 To'liq statistika")
@admin_only
async def admin_full_stats(msg: Message):
    stats = await get_full_stats()
    growth = await get_growth_chart()

    # Mini chart
    if growth:
        max_cnt = max(r['cnt'] for r in growth) or 1
        chart_lines = []
        for r in growth:
            bar_len = round(r['cnt'] / max_cnt * 12)
            bar = "█" * bar_len + "░" * (12 - bar_len)
            day_str = r['day'].strftime('%d.%m')
            chart_lines.append(f"<code>{day_str} │{bar}│ {r['cnt']}</code>")
        chart = "\n".join(chart_lines)
    else:
        chart = "<i>Ma'lumot yo'q</i>"

    top = ""
    if stats['top_classes']:
        for i, row in enumerate(stats['top_classes'], 1):
            top += f"  {i}. {row['class_name']} — {row['cnt']} marta\n"

    text = (
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['total']}</b>\n"
        f"📅 Bugun faol: <b>{stats['today']}</b>\n"
        f"📆 Hafta ichida: <b>{stats['week']}</b>\n"
        f"🚫 Banned: <b>{stats['banned']}</b>\n\n"
        f"📈 <b>So'nggi 7 kun o'sishi:</b>\n{chart}\n\n"
        f"🏆 <b>Eng ko'p ko'rilgan sinflar (7 kun):</b>\n{top or '  —'}"
    )
    await msg.answer(text)


# ── 👥 FOYDALANUVCHILAR ───────────────────────────────────────────────────────
@dp.message(F.text == "👥 Foydalanuvchilar")
@admin_only
async def admin_users(msg: Message):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, full_name, username, usage_count, last_active FROM users ORDER BY last_active DESC LIMIT 10"
        )

    lines = ["👥 <b>So'nggi 10 foydalanuvchi:</b>\n"]
    for r in rows:
        uname = f"@{r['username']}" if r['username'] else "—"
        last = r['last_active'].strftime('%d.%m %H:%M')
        lines.append(f"• <b>{r['full_name']}</b> ({uname})\n  ID: <code>{r['user_id']}</code> · {r['usage_count']}x · {last}")

    await msg.answer("\n".join(lines))


# ── 🔍 FOYDALANUVCHI QIDIRISH ─────────────────────────────────────────────────
@dp.message(F.text == "🔍 Foydalanuvchi qidirish")
@admin_only
async def admin_search_start(msg: Message, state: FSMContext):
    await state.set_state(AdminState.search_user)
    await msg.answer("🔍 Ism, username yoki ID kiriting:", reply_markup=back_menu())

@dp.message(AdminState.search_user)
@admin_only
async def admin_search_exec(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.clear()
        await msg.answer("🛡 Admin panel", reply_markup=admin_menu())
        return

    results = await search_user(msg.text)
    if not results:
        await msg.answer("❌ Topilmadi.")
        return

    for r in results:
        uname = f"@{r['username']}" if r['username'] else "—"
        last = r['last_active'].strftime('%d.%m.%Y %H:%M')
        status = "🚫 Banned" if r['is_banned'] else "✅ Faol"
        text = (
            f"👤 <b>{r['full_name']}</b>\n"
            f"🔗 {uname} · ID: <code>{r['user_id']}</code>\n"
            f"📊 Faollik: {r['usage_count']}x\n"
            f"🕐 So'nggi: {last}\n"
            f"Holat: {status}"
        )
        await msg.answer(text, reply_markup=admin_user_actions_inline(r['user_id'], r['is_banned']))

    await state.clear()


# ── BAN / UNBAN ───────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("ban:"))
@admin_only
async def admin_ban(cb: CallbackQuery):
    uid = int(cb.data.split(":")[1])
    await ban_user(uid)
    await cb.answer("🚫 Foydalanuvchi banned!", show_alert=True)
    try:
        await bot.send_message(uid, "🚫 Siz botdan chiqarib yuborldingiz.")
    except Exception:
        pass
    u = await get_user(uid)
    if u:
        await cb.message.edit_reply_markup(
            reply_markup=admin_user_actions_inline(uid, True)
        )

@dp.callback_query(F.data.startswith("unban:"))
@admin_only
async def admin_unban(cb: CallbackQuery):
    uid = int(cb.data.split(":")[1])
    await unban_user(uid)
    await cb.answer("✅ Foydalanuvchi ruxsat berildi!", show_alert=True)
    await cb.message.edit_reply_markup(
        reply_markup=admin_user_actions_inline(uid, False)
    )


# ── DM TO USER ────────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("dm:"))
@admin_only
async def admin_dm_start(cb: CallbackQuery, state: FSMContext):
    uid = int(cb.data.split(":")[1])
    await state.set_state(AdminState.dm_user)
    await state.update_data(dm_target=uid)
    await cb.answer()
    await cb.message.answer(
        f"✍️ <code>{uid}</code> ga yuboriladigan xabarni kiriting:",
        reply_markup=back_menu()
    )

@dp.message(AdminState.dm_user)
@admin_only
async def admin_dm_send(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.clear()
        await msg.answer("🛡 Admin panel", reply_markup=admin_menu())
        return
    data = await state.get_data()
    uid = data.get('dm_target')
    try:
        await bot.send_message(uid, f"📨 <b>Admin xabari:</b>\n\n{msg.text}")
        await msg.answer("✅ Xabar yuborildi.", reply_markup=admin_menu())
    except Exception as e:
        await msg.answer(f"❌ Xatolik: {e}", reply_markup=admin_menu())
    await state.clear()


# ── 📝 SO'NGGI FIKRLAR ────────────────────────────────────────────────────────
@dp.message(F.text == "📝 So'nggi fikrlar")
@admin_only
async def admin_feedbacks(msg: Message):
    rows = await get_recent_feedback(8)
    if not rows:
        await msg.answer("📭 Hozircha fikr yo'q.")
        return
    lines = ["📝 <b>So'nggi fikrlar:</b>\n"]
    for r in rows:
        stars = "⭐" * (r['rating'] // 2) if r['rating'] else "—"
        date = r['sent_at'].strftime('%d.%m %H:%M')
        lines.append(f"• <b>{r['full_name']}</b> · {stars} · {date}\n  <i>{r['feedback_text'][:120]}</i>\n")
    await msg.answer("\n".join(lines))


# ── 📨 BROADCAST ──────────────────────────────────────────────────────────────
@dp.message(F.text == "📨 Broadcast")
@admin_only
async def broadcast_start(msg: Message, state: FSMContext):
    await state.set_state(BroadcastState.text)
    await msg.answer(
        "✍️ Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:\n\n"
        "<i>HTML formatlash ishlaydi: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;</i>",
        reply_markup=back_menu()
    )

@dp.message(BroadcastState.text)
@admin_only
async def broadcast_preview(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.clear()
        await msg.answer("🛡 Admin panel", reply_markup=admin_menu())
        return
    await state.update_data(bc_text=msg.text)
    await state.set_state(BroadcastState.confirm)
    total = await get_full_stats()
    await msg.answer(
        f"👀 <b>Ko'rib chiqing:</b>\n\n{msg.text}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📤 {total['total']} ta foydalanuvchiga yuboriladi.\n"
        f"Tasdiqlaysizmi?",
        reply_markup=admin_broadcast_confirm_inline()
    )

@dp.callback_query(F.data == "broadcast_confirm")
@admin_only
async def broadcast_exec(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get('bc_text', '')
    await state.clear()
    await cb.answer()

    users = await get_all_users()
    status_msg = await cb.message.edit_text(
        f"⏳ Yuborilmoqda... 0 / {len(users)}"
    )

    sent = fail = 0
    tasks = []

    async def send_one(uid):
        nonlocal sent, fail
        try:
            await bot.send_message(uid, text)
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            fail += 1
        except Exception:
            fail += 1

    # Batch: 25 ta bir vaqtda
    batch_size = 25
    for i in range(0, len(users), batch_size):
        batch = users[i:i+batch_size]
        await asyncio.gather(*[send_one(u) for u in batch])
        await asyncio.sleep(0.05)
        if i % 100 == 0 and i > 0:
            try:
                await status_msg.edit_text(f"⏳ {sent + fail} / {len(users)} ...")
            except Exception:
                pass

    await status_msg.edit_text(
        f"✅ <b>Broadcast yakunlandi!</b>\n\n"
        f"📤 Yuborildi: <b>{sent}</b>\n"
        f"❌ Xatolik: <b>{fail}</b>"
    )

@dp.callback_query(F.data == "broadcast_cancel")
@admin_only
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Bekor qilindi")
    await cb.message.edit_text("❌ Broadcast bekor qilindi.")


# ═══════════════════════════════════════════════════════════════════════════════
#  ⏰ DAILY REMINDER SCHEDULER (07:30 har kuni)
# ═══════════════════════════════════════════════════════════════════════════════
async def daily_reminder_job():
    """Har kuni 07:30 da ishga tushadi"""
    while True:
        now = datetime.now()
        # Keyingi 07:30 gacha kutish
        target = now.replace(hour=7, minute=30, second=0, microsecond=0)
        if now >= target:
            # Ertaga
            from datetime import timedelta
            target += timedelta(days=1)
        wait_secs = (target - now).total_seconds()
        await asyncio.sleep(wait_secs)

        # Haftaning kuni (0=Dush, 4=Juma, 5-6=dam)
        today_idx = datetime.now().isoweekday()  # 1=Mon...7=Sun
        today_name = DAY_MAP.get(today_idx)
        if not today_name:
            continue  # Dam olish kuni — yubormaslik

        reminders = await get_active_reminders()
        log.info(f"Daily reminder: {len(reminders)} ta foydalanuvchi, kun: {today_name}")

        for rem in reminders:
            try:
                text = format_schedule(rem['class_name'], today_name)
                if text:
                    header = f"☀️ <b>Xayrli tong!</b> Bugun <b>{today_name}</b>\n\n"
                    await bot.send_message(rem['user_id'], header + text)
                    await asyncio.sleep(0.05)
            except (TelegramForbiddenError, TelegramBadRequest):
                pass
            except Exception as e:
                log.error(f"Reminder error {rem['user_id']}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  STARTUP / SERVER
# ═══════════════════════════════════════════════════════════════════════════════
async def on_startup():
    await create_db()
    await get_pool()   # Pool oldindan isitish
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    log.info(f"✅ Webhook o'rnatildi: {WEBHOOK_URL}/webhook")

    # Reminder scheduler background task
    asyncio.create_task(daily_reminder_job())
    log.info("⏰ Daily reminder scheduler ishga tushdi")

async def health_check(request):
    return web.Response(text="✅ Bot ishlayapti!", content_type="text/plain")

app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
setup_application(app, dp)
app.router.add_get("/", health_check)

async def main():
    await on_startup()
    await web._run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    asyncio.run(main())
