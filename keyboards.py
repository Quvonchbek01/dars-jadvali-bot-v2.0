from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)

WEB_URL = "https://imjadval.netlify.app"

# ── REPLY KEYBOARDS ───────────────────────────────────────────────────────────

def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📚 Dars jadvali", web_app=WebAppInfo(url=WEB_URL))],
        [KeyboardButton(text="📊 Mening statistikam"), KeyboardButton(text="⏰ Eslatma")],
        [KeyboardButton(text="💬 Fikr bildirish"), KeyboardButton(text="ℹ️ Yordam")],
    ], resize_keyboard=True)


def back_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Orqaga")]],
        resize_keyboard=True
    )


def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 To'liq statistika"), KeyboardButton(text="👥 Foydalanuvchilar")],
        [KeyboardButton(text="📨 Broadcast"), KeyboardButton(text="📝 So'nggi fikrlar")],
        [KeyboardButton(text="🔍 Foydalanuvchini qidirish"), KeyboardButton(text="⬅️ Orqaga")],
    ], resize_keyboard=True)


# ── INLINE KEYBOARDS ──────────────────────────────────────────────────────────

def start_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Dars jadvalini ochish", web_app=WebAppInfo(url=WEB_URL))],
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="my_stats"),
            InlineKeyboardButton(text="⏰ Eslatma", callback_data="reminder_menu"),
        ],
        [InlineKeyboardButton(text="💬 Fikr bildirish", callback_data="feedback_start")],
    ])


def reminder_class_inline(current_class: str = None):
    classes = [
        ["5-A","5-B","5-D"],
        ["6-A","6-B","6-D"],
        ["7-A","7-B","7-D"],
        ["8-A","8-B","8-D"],
        ["9-A","9-B","9-D"],
        ["10-A","10-B","10-D"],
        ["11-A","11-B","11-D"],
    ]
    buttons = []
    for row in classes:
        buttons.append([
            InlineKeyboardButton(
                text=f"{'✅ ' if c == current_class else ''}{c}",
                callback_data=f"set_reminder:{c}"
            ) for c in row
        ])
    buttons.append([InlineKeyboardButton(text="❌ Eslatmani o'chirish", callback_data="disable_reminder")])
    buttons.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stats_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="my_stats")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")],
    ])


def feedback_rating_inline():
    stars = []
    for i in range(1, 6):
        stars.append(InlineKeyboardButton(text="⭐" * i, callback_data=f"rate:{i*2}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        stars[:3],
        stars[3:],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")],
    ])


def admin_broadcast_confirm_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yuborish", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel"),
        ]
    ])


def admin_user_actions_inline(user_id: int, is_banned: bool):
    ban_btn = InlineKeyboardButton(
        text="🔓 Razban" if is_banned else "🚫 Ban",
        callback_data=f"{'unban' if is_banned else 'ban'}:{user_id}"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [ban_btn],
        [InlineKeyboardButton(text="📨 Xabar yuborish", callback_data=f"dm:{user_id}")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_users")],
    ])


def back_inline(cb: str = "back_main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=cb)]
    ])
