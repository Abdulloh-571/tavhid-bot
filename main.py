import asyncio
import json
import math
import os
import random
import re
import unicodedata
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
    WebAppInfo,
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
USE_OPENAI_FALLBACK = os.getenv("USE_OPENAI_FALLBACK", "false").lower() in {"1", "true", "yes"}

MINI_GAME_WEBAPP_URL = os.getenv("MINI_GAME_WEBAPP_URL") or "https://telegram.org/apps"

FAST_GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
OPENAI_MODEL = "gpt-4o-mini"

ADMIN_ID = 8929299595
SUPER_OWNER_IDS = {ADMIN_ID}

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN topilmadi. Kodga yoki terminalga kiriting.")

gemini_client = None
openai_client = None

if GEMINI_API_KEY:
    try:
        from google import genai
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        print("Tavhid: Gemini mijozi muvaffaqiyatli ulandi.")
    except Exception as error:
        print("Tavhid: Gemini kutubxonasi xatosi:", repr(error))
else:
    print("DIQQAT: GEMINI_API_KEY kiritilmagan.")

if OPENAI_API_KEY and USE_OPENAI_FALLBACK:
    try:
        from openai import AsyncOpenAI
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        print("Tavhid: OpenAI fallback mijozi ulandi.")
    except Exception as error:
        print("Tavhid: OpenAI mijozini ishga tushirib bolmadi:", repr(error))

bot = Bot(token=TOKEN)
dp = Dispatcher()
DATA_FILE = Path(__file__).with_name("tavhid_data.json")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = text.replace("‘", "").replace("’", "").replace("`", "").replace("'", "").replace("ʻ", "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def has_valid_pdf(pdf_file_id) -> bool:
    return bool(isinstance(pdf_file_id, str) and pdf_file_id.strip())


def default_data():
    return {
        "scores": {},
        "zakovat_wins": {},
        "used_tests": {},
        "used_zakovat": {},
        "used_group_tests": {},
        "used_rebus": {},
        "used_mazgila": {},
        "tracked": {},
        "chat_recent_msgs": {},
        "mazgila": {},
        "mazgila_targets": {},
        "owners": [],
        "book_contributions": {},
        "favorites": {},
        "xp": {},
        "messages_count": {},
        "custom_books": [],
        "custom_hadiths": [],
        "lang": {},
        "notes": {},
        "daily_topic": {},
        "settings": {},
    }


def save_data():
    temporary = DATA_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(DATA_FILE)


def load_data():
    base = default_data()
    if not DATA_FILE.exists():
        return base
    try:
        loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        for key, value in base.items():
            expected_type = list if isinstance(value, list) else dict
            if not isinstance(loaded.get(key), expected_type):
                loaded[key] = value
        return loaded
    except (OSError, json.JSONDecodeError):
        return base


data = load_data()


def user_key(user_id: int) -> str:
    return str(user_id)


def is_super_owner(user_id: int) -> bool:
    return user_id in SUPER_OWNER_IDS


def is_bot_owner(user_id: int) -> bool:
    return is_super_owner(user_id) or (user_id in data.get("owners", []))


def get_role_label(user_id: int) -> str:
    if is_super_owner(user_id):
        return "Super Ega"
    if user_id in data.get("owners", []):
        return "Ega"
    return "Foydalanuvchi"


def format_user_mention(user: types.User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name


def get_user_settings(uid: int) -> dict:
    ukey = user_key(uid)
    cfg = data["settings"].setdefault(ukey, {
        "lang": "🇺🇿 O‘zbek",
        "style": "Qisqa",
        "notifications": True,
    })
    cfg.setdefault("lang", "🇺🇿 O‘zbek")
    cfg.setdefault("style", "Qisqa")
    cfg.setdefault("notifications", True)
    return cfg


def add_xp(user_id: int, amount: int, messages_delta: int = 0):
    ukey = user_key(user_id)
    data["xp"][ukey] = data["xp"].get(ukey, 0) + amount
    if messages_delta:
        data["messages_count"][ukey] = data["messages_count"].get(ukey, 0) + messages_delta
    save_data()


def calc_level(xp: int) -> int:
    return max(1, int(math.floor((xp / 50) ** 0.5)) + 1)


main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🤖 AI"), KeyboardButton(text="📚 Kutubxona")],
        [KeyboardButton(text="🌍 Til o‘rganish"), KeyboardButton(text="📝 Test")],
        [KeyboardButton(text="🌐 Tarjimon"), KeyboardButton(text="🎮 O‘yinlar")],
        [KeyboardButton(text="👤 Profil"), KeyboardButton(text="❓ Yordam")],
        [KeyboardButton(text="⚙️ Sozlamalar")],
    ],
    resize_keyboard=True,
)

back_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⬅️ Orqaga"), KeyboardButton(text="🏠 Bosh menyu")],
    ],
    resize_keyboard=True,
)

library_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🤖 AI Kitob qidirish"), KeyboardButton(text="🔍 Oddiy qidirish")],
        [KeyboardButton(text="📂 Kategoriyalar"), KeyboardButton(text="🆕 Yangi kitoblar")],
        [KeyboardButton(text="❤️ Sevimlilar"), KeyboardButton(text="📖 Kitoblar")],
        [KeyboardButton(text="🕌 Hadislar"), KeyboardButton(text="➕ Kitob qo'shish")],
        [KeyboardButton(text="🇺🇿"), KeyboardButton(text="🇷🇺"), KeyboardButton(text="🇬🇧")],
        [KeyboardButton(text="⬅️ Orqaga"), KeyboardButton(text="🏠 Bosh menyu")],
    ],
    resize_keyboard=True,
)

test_subject_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔀 Aralash"), KeyboardButton(text="🧪 Kimyo")],
        [KeyboardButton(text="➗ Matematika"), KeyboardButton(text="⚛️ Fizika")],
        [KeyboardButton(text="🌍 Geografiya"), KeyboardButton(text="💻 Dasturlash")],
        [KeyboardButton(text="⬅️ Orqaga"), KeyboardButton(text="🏠 Bosh menyu")],
    ],
    resize_keyboard=True,
)

answer_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="A"), KeyboardButton(text="B"), KeyboardButton(text="C"), KeyboardButton(text="D")],
        [KeyboardButton(text="🔀 Aralash"), KeyboardButton(text="📚 Boshqa fan")],
        [KeyboardButton(text="🏠 Bosh menyu")],
    ],
    resize_keyboard=True,
)

help_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="❓ Ko'p beriladigan savollar")],
        [KeyboardButton(text="📩 Administratorga murojaat")],
        [KeyboardButton(text="💬 Taklif va shikoyatlar")],
        [KeyboardButton(text="🏠 Bosh menyu")],
    ],
    resize_keyboard=True,
)


def build_mini_games_inline() -> InlineKeyboardMarkup:
    clean_url = (MINI_GAME_WEBAPP_URL or "").strip()
    rows = [
        [
            InlineKeyboardButton(text="🧩 Mantiqiy Rebus (Miyani charxlab ko‘ring)", callback_data="mgame:rebus"),
        ]
    ]
    if clean_url.startswith(("https://", "http://")):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🕹 Mini-o‘yinlar markazi (Web App)",
                    web_app=WebAppInfo(url=clean_url),
                )
            ]
        )
    rows.extend([
        [
            InlineKeyboardButton(text="🎯 Basketbol Mini-o‘yini", callback_data="mgame:basket"),
            InlineKeyboardButton(text="🏀 Futbol Mini-o‘yini", callback_data="mgame:football"),
        ],
        [
            InlineKeyboardButton(text="🎳 Bowling Mini-o‘yini", callback_data="mgame:bowling"),
            InlineKeyboardButton(text="🎰 Slot Mini-o‘yini", callback_data="mgame:slot"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


mini_games_inline = build_mini_games_inline()

translator_inline = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="➡️ O‘zbek tiliga", callback_data="tr_dir:O‘zbek tili"),
            InlineKeyboardButton(text="➡️ Ingliz tiliga", callback_data="tr_dir:Ingliz tili"),
        ],
        [
            InlineKeyboardButton(text="➡️ Rus tiliga", callback_data="tr_dir:Rus tili"),
            InlineKeyboardButton(text="➡️ Arab tiliga", callback_data="tr_dir:Arab tili"),
        ],
        [
            InlineKeyboardButton(text="➡️ Turk tiliga", callback_data="tr_dir:Turk tili"),
            InlineKeyboardButton(text="➡️ Nemis tiliga", callback_data="tr_dir:Nemis tili"),
        ],
    ]
)

learn_lang_inline = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🇬🇧 Ingliz tili", callback_data="learn_lang:Ingliz tili"),
            InlineKeyboardButton(text="🇷🇺 Rus tili", callback_data="learn_lang:Rus tili"),
        ],
        [
            InlineKeyboardButton(text="🇸🇦 Arab tili", callback_data="learn_lang:Arab tili"),
            InlineKeyboardButton(text="🇹🇷 Turk tili", callback_data="learn_lang:Turk tili"),
        ],
        [
            InlineKeyboardButton(text="🇩🇪 Nemis tili", callback_data="learn_lang:Nemis tili"),
        ],
    ]
)


def learn_topic_inline(lang_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📖 Lug‘at", callback_data=f"learn_mod:{lang_name}:Lug‘at"),
                InlineKeyboardButton(text="✍️ Mashqlar", callback_data=f"learn_mod:{lang_name}:Mashqlar"),
            ],
            [
                InlineKeyboardButton(text="📐 Grammatika", callback_data=f"learn_mod:{lang_name}:Grammatika"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Tilni o‘zgartirish", callback_data="learn_back_lang"),
            ],
        ]
    )


def build_settings_inline(uid: int) -> InlineKeyboardMarkup:
    cfg = get_user_settings(uid)
    notif_label = "🔔 Bildirishnoma: Yoqilgan" if cfg["notifications"] else "🔕 Bildirishnoma: O‘chirilgan"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🌐 Til: {cfg['lang']}", callback_data="set:lang"),
                InlineKeyboardButton(text=f"✍️ Uslub: {cfg['style']}", callback_data="set:style"),
            ],
            [
                InlineKeyboardButton(text=notif_label, callback_data="set:notif"),
            ],
            [
                InlineKeyboardButton(text="🔄 Savollar tarixini yangilash", callback_data="set:reset_history"),
            ],
        ]
    )


def get_all_books():
    result = []
    for item in data.get("custom_books", []):
        if isinstance(item, dict):
            title = str(item.get("title", "")).strip()
            author = str(item.get("author", "Muallif ko‘rsatilmagan")).strip() or "Muallif ko‘rsatilmagan"
            cat = str(item.get("category", "Kutubxona")).strip() or "Kutubxona"
            summary = str(item.get("summary", "PDF kitob.")).strip() or "PDF kitob."
            pdf_id = item.get("pdf_file_id")
            if title and has_valid_pdf(pdf_id):
                result.append((title, author, cat, summary, pdf_id))
    return result


hadith_collections = {
    "Sahih al-Buxoriy": [
        ("Amallar niyatlarga bog‘liqdir.", "Sahih al-Buxoriy, 1-hadis", "https://sunnah.com/bukhari:1"),
        ("Iymon yetmish nechta sho‘badan iborat; eng afzali 'La ilaha illalloh' deyish, eng kichigi yo‘ldagi ozorni olib tashlashdir.", "Sahih al-Buxoriy, 9-hadis", "https://sunnah.com/bukhari:9"),
        ("O‘zingizga yaxshi ko‘rgan narsani birodaringizga ham yaxshi ko‘rmaguningizcha komil mo‘min bo‘lmaysiz.", "Sahih al-Buxoriy, 13-hadis", "https://sunnah.com/bukhari:13"),
        ("Din yengillikdir.", "Sahih al-Buxoriy, 39-hadis", "https://sunnah.com/bukhari:39"),
        ("Osonlashtiring, qiyinlashtirmang; xushxabar bering, nafratlantirmang.", "Sahih al-Buxoriy, 69-hadis", "https://sunnah.com/bukhari:69"),
        ("Kim biror kishiga Alloh xohlagan yaxshilikni bersa, uni dinda faqih qilib qo‘yadi.", "Sahih al-Buxoriy, 71-hadis", "https://sunnah.com/bukhari:71"),
        ("Qiyomat alomatlaridan biri ilm ko‘tarilib, jaholatning barqaror bo‘lishidir.", "Sahih al-Buxoriy, 80-hadis", "https://sunnah.com/bukhari:80"),
        ("Kim ertalab va kechqurun masjidga borsa, Alloh har safar unga jannatdan manzil tayyorlaydi.", "Sahih al-Buxoriy, 662-hadis", "https://sunnah.com/bukhari:662"),
        ("Sizlarning yaxshilaringiz Qur’onni o‘rganib, uni boshqalarga o‘rgatganingizdir.", "Sahih al-Buxoriy, 5027-hadis", "https://sunnah.com/bukhari:5027"),
        ("Onaga xizmat va ehtirom ulug‘ligi.", "Sahih al-Buxoriy, 5971-hadis", "https://sunnah.com/bukhari:5971"),
        ("Ekkan daraxtidan yoki ekinidan qush, inson yoki hayvon yesa, bu uning uchun sadaqadir.", "Sahih al-Buxoriy, 6012-hadis", "https://sunnah.com/bukhari:6012"),
        ("Rahm qilmagan kishiga rahm qilinmaydi.", "Sahih al-Buxoriy, 6013-hadis", "https://sunnah.com/bukhari:6013"),
        ("Kim Allohga va oxirat kuniga iymon keltirsa, yaxshi gapirsin yoki sukut saqlasin.", "Sahih al-Buxoriy, 6018-hadis", "https://sunnah.com/bukhari:6018"),
        ("Kuchli kishi kurashda yenggan emas, balki g‘azab paytida o‘zini tuta olgan kishidir.", "Sahih al-Buxoriy, 6114-hadis", "https://sunnah.com/bukhari:6114"),
        ("Allohga eng sevimli amallar oz bo‘lsa-da, davomli bo‘lganidir.", "Sahih al-Buxoriy, 6464-hadis", "https://sunnah.com/bukhari:6464"),
        ("Bandaning amallari yakuniga bog‘liqdir.", "Sahih al-Buxoriy, 6607-hadis", "https://sunnah.com/bukhari:6607"),
        ("Kim ikki suyukli narsasi — ko‘z nuridan ayrilganda sabr qilsa, uning evaziga jannat bo‘ladi.", "Sahih al-Buxoriy, 5653-hadis", "https://sunnah.com/bukhari:5653"),
        ("Musulmon kishi birodariga uch kundan ortiq arazlab yurishi halol emas.", "Sahih al-Buxoriy, 6077-hadis", "https://sunnah.com/bukhari:6077"),
        ("Qarzni chiroyli tarzda ado etish eng yaxshi amallardandir.", "Sahih al-Buxoriy, 2390-hadis", "https://sunnah.com/bukhari:2390"),
        ("Kim sahar vaqtida baraka so‘rab duo qilsa, ishi barakali bo‘ladi.", "Sahih al-Buxoriy, 6370-hadis", "https://sunnah.com/bukhari:6370"),
        ("Eng yaxshi sadaqa — o‘zingiz sog‘lom va molga ehtiyoj sezib turgan paytingizda qilgan sadaqangizdir.", "Sahih al-Buxoriy, 1419-hadis", "https://sunnah.com/bukhari:1419"),
        ("Kim Alloh yo‘lida bir kun ro‘za tutsa, Alloh uning yuzini do‘zaxdan yetmish yillik masofaga uzoqlashtiradi.", "Sahih al-Buxoriy, 2840-hadis", "https://sunnah.com/bukhari:2840"),
        ("Omonatni egasiga qaytaring, sizga xiyonat qilgan kimsaga ham xiyonat qilmang.", "Sunan Abu Dovud / Sahih al-Buxoriy mavzusidagi omonat hadislari (Sahih al-Buxoriy, 2749-hadis)", "https://sunnah.com/bukhari:2749"),
        ("Kim biror kishining qiyinchiligini yengillashtirsa, Alloh uning qiyinchiligini yengillashtiradi.", "Sahih al-Buxoriy, 2442-hadis", "https://sunnah.com/bukhari:2442"),
        ("Bemorlikka uchragan kishi gunohlarining mag‘firat qilinishiga sabab bo‘ladi.", "Sahih al-Buxoriy, 5640-hadis", "https://sunnah.com/bukhari:5640"),
        ("Kim o‘zini kamtar tutsa, Alloh uni yuksaltiradi.", "Sahih Muslim, 2588-hadis / Sahih al-Buxoriy, 72-hadis", "https://sunnah.com/bukhari:72"),
        ("Shoshqolchilik shaytondan, vazminlik Allohdandir.", "Jome’ at-Termiziy, 2012-hadis", "https://sunnah.com/tirmidhi:2012"),
        ("Kim biror yaxshi ishga bosh bo‘lsa, unga ham o‘sha ishning ajri yoziladi.", "Sahih Muslim, 1017-hadis", "https://sunnah.com/muslim:1017"),
        ("Barcha Payg‘ambarlar birodardirlar, ularning dini bittadir.", "Sahih al-Buxoriy, 3443-hadis", "https://sunnah.com/bukhari:3443"),
        ("Odamlarga rahm qilmasangiz, Alloh sizga rahm qilmaydi.", "Sahih al-Buxoriy, 7376-hadis", "https://sunnah.com/bukhari:7376"),
    ],
    "Sahih Muslim": [
        ("Musulmon — musulmonlar uning tili va qo‘lidan omonda bo‘lgan kishidir.", "Sahih Muslim, 42a-hadis", "https://sunnah.com/muslim:42a"),
        ("Kibr haqni inkor etish va odamlarni past sanashdir.", "Sahih Muslim, 91-hadis", "https://sunnah.com/muslim:91"),
        ("Poklik iymonning yarmidir.", "Sahih Muslim, 223-hadis", "https://sunnah.com/muslim:223"),
        ("Yo‘ldan ozor beruvchi narsani olib tashlagan kishining gunohi kechirildi.", "Sahih Muslim, 1914b-hadis", "https://sunnah.com/muslim:1914b"),
        ("Alloh sizlarning suratlaringiz va mollaringizga emas, balki qalblaringiz va amallaringizga qaraydi.", "Sahih Muslim, 2564-hadis", "https://sunnah.com/muslim:2564"),
        ("Alloh taolo: 'Bandam Men haqimda qanday gumon qilsa, Men uning yonida shundayman', deydi.", "Sahih Muslim, 2675-hadis", "https://sunnah.com/muslim:2675"),
        ("Sadaqa mol-dunyoni kamaytirmaydi.", "Sahih Muslim, 2588-hadis", "https://sunnah.com/muslim:2588"),
        ("Rostgo‘ylik yaxshilikka, yaxshilik esa jannatga yetaklaydi.", "Sahih Muslim, 2607c-hadis", "https://sunnah.com/muslim:2607c"),
        ("Birodaringizga ochiq chehra bilan yuzlanishingizdan ham biror yaxshilikni kichik sanamang.", "Sahih Muslim, 2626-hadis", "https://sunnah.com/muslim:2626"),
        ("Kim ilm izlab bir yo‘lga tushsa, Alloh unga jannat yo‘lini oson qiladi.", "Sahih Muslim, 2699-hadis", "https://sunnah.com/muslim:2699"),
        ("Duo ibodatning mag‘zidir.", "Sahih Muslim, 2735-hadis", "https://sunnah.com/muslim:2735"),
        ("Mo‘minning ishi ajablanarli: uning barcha ishi o‘zi uchun yaxshilikdir; quvonch yetsa shukr qiladi, musibat yetsa sabr qiladi.", "Sahih Muslim, 2999-hadis", "https://sunnah.com/muslim:2999"),
        ("Jannat mashaqqatlar bilan, do‘zax esa shahvatlar bilan o‘ralgan.", "Sahih Muslim, 2822-hadis", "https://sunnah.com/muslim:2822"),
        ("Kim bir musulmonning aybini yashirsa, Alloh dunyo va oxiratda uning aybini yashiradi.", "Sahih Muslim, 2699-hadis", "https://sunnah.com/muslim:2699"),
        ("Yaxshi so‘z ham sadaqadir.", "Sahih Muslim, 1009-hadis", "https://sunnah.com/muslim:1009"),
        ("Kim Allohga iymon keltirsa, qo‘shnisini ehtirom qilsin.", "Sahih Muslim, 47a-hadis", "https://sunnah.com/muslim:47a"),
        ("Kishi o‘zi yaxshi ko‘rgan insoni bilan birga bo‘ladi.", "Sahih Muslim, 2639-hadis", "https://sunnah.com/muslim:2639"),
        ("Tavba o‘zidan oldingi barcha gunohlarni o‘chiradi.", "Sahih Muslim, 121-hadis", "https://sunnah.com/muslim:121"),
        ("Kim ertalab va kechqurun Allohni zikr qilsa, qalbi tirik bo‘ladi.", "Sahih Muslim, 2688-hadis", "https://sunnah.com/muslim:2688"),
        ("Halol kasb talab qilish har bir musulmonga vojib amallardandir.", "Sahih Muslim, 1015-hadis", "https://sunnah.com/muslim:1015"),
    ],
    "Sunan Abu Dovud": [
        ("Kim o‘zini bir qavmga o‘xshatsa, u o‘shalardandir.", "Sunan Abu Dovud, 4031-hadis", "https://sunnah.com/abudawud:4031"),
        ("Eng komil iymonli mo‘min — xulqi eng go‘zal va oilasiga eng mehribon bo‘lganidir.", "Sunan Abu Dovud, 4682-hadis", "https://sunnah.com/abudawud:4682"),
        ("Kim g‘azabi kela turib, uni yutsa, Alloh qiyomat kuni uni xaloyiq oldida chaqiradi.", "Sunan Abu Dovud, 4777-hadis", "https://sunnah.com/abudawud:4777"),
        ("Kim biror kishining aybini yashirsa, Alloh dunyo va oxiratda uning aybini yashiradi.", "Sunan Abu Dovud, 4892-hadis", "https://sunnah.com/abudawud:4892"),
        ("Kichiklarimizga rahm qilmagan va kattalarimizning haqqini bilmagan bizdan emas.", "Sunan Abu Dovud, 4943-hadis", "https://sunnah.com/abudawud:4943"),
        ("Kim bir yaxshilikka dalolat qilsa, unga o‘sha amalni bajargan kishining ajricha ajr bo‘ladi.", "Sunan Abu Dovud, 5129-hadis", "https://sunnah.com/abudawud:5129"),
        ("Haqni aytishdan tortinmang.", "Sunan Abu Dovud, 4341-hadis", "https://sunnah.com/abudawud:4341"),
        ("Kim salom bersa, unga undan ham yaxshiroq yoki xuddi o‘zidek alik oling.", "Sunan Abu Dovud, 5196-hadis", "https://sunnah.com/abudawud:5196"),
        ("Safar paytidagi duo rad etilmaydigan duolardandir.", "Sunan Abu Dovud, 2549-hadis", "https://sunnah.com/abudawud:2549"),
        ("Omonatdor bo‘ling, xiyonat qilmang.", "Sunan Abu Dovud, 3535-hadis", "https://sunnah.com/abudawud:3535"),
        ("Kim kechirimli bo‘lsa, Alloh uning martabasini ko‘taradi.", "Sunan Abu Dovud, 4940-hadis", "https://sunnah.com/abudawud:4940"),
        ("Rizqni kengaytirish va umrni barakali qilishda silai rahmning o‘rni katta.", "Sunan Abu Dovud, 1693-hadis", "https://sunnah.com/abudawud:1693"),
        ("Dushman bilan to‘qnashishni orzu qilmang, Allohdan ofiyat so‘rang.", "Sunan Abu Dovud, 2631-hadis", "https://sunnah.com/abudawud:2631"),
        ("Yaxshi qo‘shni baxt-saodat belgilaridandir.", "Sunan Abu Dovud, 5152-hadis", "https://sunnah.com/abudawud:5152"),
        ("Kim birovning qiyinchiligini aritsa, Alloh unga yordam beradi.", "Sunan Abu Dovud, 4946-hadis", "https://sunnah.com/abudawud:4946"),
    ],
    "Jome' at-Termiziy": [
        ("Xulqi eng yaxshi bo‘lgan mo‘min iymoni eng komilidir.", "Jome’ at-Termiziy, 1162-hadis", "https://sunnah.com/tirmidhi:1162"),
        ("Birodaringiz yuziga tabassum qilishingiz ham siz uchun sadaqadir.", "Jome’ at-Termiziy, 1956-hadis", "https://sunnah.com/tirmidhi:1956"),
        ("Kim Allohga va oxirat kuniga ishonsa, qo‘shnisiga ozor bermasin.", "Jome’ at-Termiziy, 1967-hadis", "https://sunnah.com/tirmidhi:1967"),
        ("Har bir yaxshilik sadaqadir.", "Jome’ at-Termiziy, 1970-hadis", "https://sunnah.com/tirmidhi:1970"),
        ("Qayerda bo‘lsangiz ham Allohga taqvo qiling, yomonlik ortidan yaxshilik qiling — u yomonlikni o‘chiradi.", "Jome’ at-Termiziy, 1987-hadis", "https://sunnah.com/tirmidhi:1987"),
        ("Hayo faqat yaxshilik keltiradi.", "Jome’ at-Termiziy, 2007-hadis", "https://sunnah.com/tirmidhi:2007"),
        ("Odamlar orasini isloh qilish nafl ro‘za, namoz va sadaqadan ham afzalroq darajadir.", "Jome’ at-Termiziy, 2509-hadis", "https://sunnah.com/tirmidhi:2509"),
        ("Allohga eng yaqin vaqt — sajda holatidir, unda ko‘p duo qiling.", "Sahih Muslim, 482-hadis / Jome’ at-Termiziy, 3457-hadis", "https://sunnah.com/tirmidhi:3457"),
        ("Kim g‘am-tashvish paytida istig‘forni ko‘paytirsa, Alloh unga chiqish yo‘lini ochadi.", "Sunan Abu Dovud, 1518-hadis / Jome’ at-Termiziy, 3577-hadis", "https://sunnah.com/tirmidhi:3577"),
        ("Yaxshilikka chaqiruvchi kishi savobga sherik bo‘ladi.", "Jome’ at-Termiziy, 2670-hadis", "https://sunnah.com/tirmidhi:2670"),
        ("Qalbning qattiqligi ko‘p gapirish va g‘aflatdan keladi.", "Jome’ at-Termiziy, 2411-hadis", "https://sunnah.com/tirmidhi:2411"),
        ("Kim o‘zini hisob-kitob qilsa va o‘limdan keyingi hayotga tayyorlansa, u aqllidir.", "Jome’ at-Termiziy, 2459-hadis", "https://sunnah.com/tirmidhi:2459"),
        ("Alloh roziligi ota-onaning roziligidadir.", "Jome’ at-Termiziy, 1899-hadis", "https://sunnah.com/tirmidhi:1899"),
        ("Haqiqiy boylik mol-mulkning ko‘pligida emas, balki qalb to‘qligidadir.", "Sahih al-Buxoriy, 6446-hadis / Jome’ at-Termiziy, 2373-hadis", "https://sunnah.com/tirmidhi:2373"),
        ("Kim birovni Alloh yo‘lida yaxshi ko‘rsa, buni unga bildirsin.", "Jome’ at-Termiziy, 2392-hadis", "https://sunnah.com/tirmidhi:2392"),
    ],
    "Sunan Ibn Moja": [
        ("Ilm talab qilish har bir musulmonga farzdir.", "Sunan Ibn Moja, 224-hadis", "https://sunnah.com/ibnmajah:224"),
        ("Uch narsadan Allohdan panoh so‘rang: foydasiz ilmdan, qo‘rqmaydigan qalbdan va to‘ymaydigan nafsdan.", "Sunan Ibn Moja, 250-hadis", "https://sunnah.com/ibnmajah:250"),
        ("Uch kishining duosi rad etilmaydi: ro‘zadorning iftor paytidagi duosi, odil imomning duosi va mazlumning duosi.", "Sunan Ibn Moja, 1752-hadis", "https://sunnah.com/ibnmajah:1752"),
        ("Albatta, Alloh muloyimdir va barcha ishlarda muloyimlikni yaxshi ko‘radi.", "Sunan Ibn Moja, 3688-hadis", "https://sunnah.com/ibnmajah:3688"),
        ("Gunohdan chin dildan tavba qilgan kishi gunohi yo‘q kabi bo‘ladi.", "Sunan Ibn Moja, 4250-hadis", "https://sunnah.com/ibnmajah:4250"),
        ("Barcha odamlar xato qiluvchi, xato qiluvchilarning eng yaxshisi ko‘p tavba qiluvchidir.", "Jome’ at-Termiziy, 2499-hadis / Sunan Ibn Moja, 4251-hadis", "https://sunnah.com/ibnmajah:4251"),
        ("Kim ilmni Alloh roziligi uchun o‘rgansa, foydali ilmga erishadi.", "Sunan Ibn Moja, 252-hadis", "https://sunnah.com/ibnmajah:252"),
        ("Halol va pok rizq izlash ibodatning bir qismidir.", "Sunan Ibn Moja, 2139-hadis", "https://sunnah.com/ibnmajah:2139"),
        ("Kim odamlarga shukr qilmasa, Allohga ham shukr qilmagan bo‘ladi.", "Sunan Abu Dovud, 4811-hadis / Sunan Ibn Moja, 1795-hadis", "https://sunnah.com/ibnmajah:1795"),
        ("Yaxshi so‘z va kechirimlilik ozor beruvchi sadaqadan yaxshiroqdir.", "Sunan Ibn Moja, 1844-hadis", "https://sunnah.com/ibnmajah:1844"),
    ],
    "Riyozus-solihin": [
        ("Gunoh qilgan kishi darhol tavba qilsa va yaxshilikka yuzlansa, Alloh uni kechiradi.", "Riyozus-solihin, 17-hadis", "https://sunnah.com/riyadussalihin:17"),
        ("Allohga eng sevimli amallar oz bo‘lsa-da, davomli bo‘lganidir.", "Riyozus-solihin, 145-hadis", "https://sunnah.com/riyadussalihin:145"),
        ("Kim bir yaxshilikka dalolat qilsa, unga o‘sha amalni bajargan kishining ajricha ajr bo‘ladi.", "Riyozus-solihin, 173-hadis", "https://sunnah.com/riyadussalihin:173"),
        ("Kim birodarining hojatini chiqarsa, Alloh ham uning hojatini chiqaradi.", "Riyozus-solihin, 233-hadis", "https://sunnah.com/riyadussalihin:233"),
        ("Alloh taolo: 'Bandam Men haqimda qanday gumon qilsa, Men uning yonida shundayman', deydi.", "Riyozus-solihin, 439-hadis", "https://sunnah.com/riyadussalihin:439"),
        ("Kim Allohning roziligi uchun bir yo‘lga kirsa, Alloh unga jannat yo‘lini oson qiladi.", "Riyozus-solihin, 1388-hadis", "https://sunnah.com/riyadussalihin:1388"),
        ("Musofirning duosi, mazlumning duosi va ota-onaning farzandiga qilgan duosi mustajobdir.", "Riyozus-solihin, 1489-hadis", "https://sunnah.com/riyadussalihin:1489"),
        ("Tilingizni yolg‘on va g‘iybatdan saqlang, shunda salomat bo‘lasiz.", "Riyozus-solihin, 1510-hadis", "https://sunnah.com/riyadussalihin:1510"),
        ("O‘ziga keraksiz narsalarni tark etishi kishining musulmonligining go‘zalligidandir.", "Riyozus-solihin, 1712-hadis", "https://sunnah.com/riyadussalihin:1712"),
        ("Sabr musibatning ilk zarbasi paytidagi sabrdir.", "Sahih al-Buxoriy, 1302-hadis / Riyozus-solihin, 27-hadis", "https://sunnah.com/riyadussalihin:27"),
    ],
}

assert sum(len(v) for v in hadith_collections.values()) == 100

question_bank = {
    "🧪 Kimyo": [
        ("25°C da sof suvning pH qiymati qancha?", ["A) 0", "B) 7", "C) 10", "D) 14"], "B", "Neytral suvda vodorod va gidroksid ionlari konsentratsiyasi teng; 25°C da pH 7."),
        ("Avogadro doimiysining taxminiy qiymati qaysi?", ["A) 6.02×10²³", "B) 3.14×10⁸", "C) 9.81", "D) 1.60×10⁻¹⁹"], "A", "Bir mol modda taxminan 6.02×10²³ zarrachani oz ichiga oladi."),
        ("Qaysi elementning atom raqami 17?", ["A) Natriy", "B) Kalsiy", "C) Xlor", "D) Oltingugurt"], "C", "Xlorning atom raqami 17."),
        ("H₂SO₄ molekulasida oltingugurtning oksidlanish darajasi nechaga teng?", ["A) +2", "B) +4", "C) +6", "D) -2"], "C", "2(+1) + x + 4(-2) = 0, demak x = +6."),
        ("Katalizator reaksiyada nimani ozgartiradi?", ["A) Muvozanat konstantasini", "B) Aktivlanish energiyasini", "C) Reaksiya mahsulotini doim", "D) Atom massasini"], "B", "Katalizator muqobil yol berib, aktivlanish energiyasini kamaytiradi."),
    ],
    "➗ Matematika": [
        ("Agar x + 1/x = 3 bolsa, x² + 1/x² nechaga teng?", ["A) 5", "B) 7", "C) 9", "D) 11"], "B", "Kvadratga oshirsak: x² + 2 + 1/x² = 9, natija 7."),
        ("log₂(32) + log₃(27) qiymatini toping.", ["A) 6", "B) 8", "C) 7", "D) 9"], "B", "log₂32 = 5 va log₃27 = 3; jami 8."),
        ("Uchburchak burchaklari 2:3:4 nisbatda. Eng katta burchak nechaga teng?", ["A) 60°", "B) 70°", "C) 80°", "D) 90°"], "C", "9 ulush 180°; bir ulush 20°, eng kattasi 4×20° = 80°."),
        ("1 dan 100 gacha bolgan natural sonlar yigindisi qancha?", ["A) 5000", "B) 5050", "C) 5100", "D) 5500"], "B", "n(n+1)/2 = 100×101/2 = 5050."),
        ("f(x)=x²−4x+7 funksiyaning eng kichik qiymati qancha?", ["A) 2", "B) 3", "C) 4", "D) 7"], "B", "f(x)=(x−2)²+3, minimum 3."),
    ],
    "⚛️ Fizika": [
        ("Vakuumda yoruglik tezligi taxminan qancha?", ["A) 3×10⁶ m/s", "B) 3×10⁸ m/s", "C) 9.8 m/s", "D) 1.5×10⁸ m/s"], "B", "Yoruglik tezligi vakuumda taxminan 299 792 458 m/s."),
        ("Jism tezligi 2 baravar oshsa, massasi ozgarmasa kinetik energiyasi qanday ozgaradi?", ["A) 2 baravar", "B) 3 baravar", "C) 4 baravar", "D) Ozgarmaydi"], "C", "Kinetik energiya mv²/2 ga teng, tezlik kvadratiga proporsional."),
        ("Elektr qarshilikning SI birligi qaysi?", ["A) Volt", "B) Amper", "C) Om", "D) Vatt"], "C", "Qarshilik om bilan olchanadi."),
        ("Ideal gaz temperaturasi Kelvin boyicha 2 baravar oshsa, bosim ozgarmas hajmda qanday boladi?", ["A) 2 baravar oshadi", "B) 2 baravar kamayadi", "C) Ozgarmaydi", "D) 4 baravar oshadi"], "A", "Gay-Lyussak qonuniga kora doimiy hajmda bosim mutlaq temperaturaga proporsional."),
        ("Impulsning SI birligi qaysi?", ["A) kg·m/s", "B) N/m", "C) J/s", "D) kg/m³"], "A", "Impuls p=mv, birligi kg·m/s."),
    ],
    "🌍 Geografiya": [
        ("Dunyodagi eng chuqur okean botiqligi qaysi?", ["A) Tonga", "B) Mariana", "C) Puerto-Riko", "D) Java"], "B", "Mariana botigidagi Challenger Deep eng chuqur malum okean nuqtasidir."),
        ("Qaysi daryo ekvatorni ikki marta kesib otadi?", ["A) Nil", "B) Amazonka", "C) Kongo", "D) Missisipi"], "C", "Kongo daryosi ekvatorni ikki marta kesib otadi."),
        ("Dunyodagi eng katta issiq chol qaysi?", ["A) Gobi", "B) Sahara", "C) Kalahari", "D) Arabiston"], "B", "Sahara eng katta issiq chol hisoblanadi."),
        ("Yer yuzidagi eng katta orol qaysi?", ["A) Madagaskar", "B) Borneo", "C) Yangi Gvineya", "D) Grenlandiya"], "D", "Grenlandiya — Avstraliyani qita deb hisoblaganda eng katta orol."),
        ("Ozbekiston qaysi ikki davlat bilan Orol dengiziga tutash hududga ega?", ["A) Qozogiston va Turkmaniston", "B) Tojikiston va Qirgiziston", "C) Afganiston va Eron", "D) Xitoy va Rossiya"], "A", "Orolboyi mintaqasida Ozbekiston va Qozogiston tilga olinadi."),
    ],
    "💻 Dasturlash": [
        ("Python'da list va tuple orasidagi asosiy farq nima?", ["A) Tuple ozgarmas", "B) List faqat son saqlaydi", "C) Tuple faqat matn saqlaydi", "D) Farqi yoq"], "A", "Tuple yaratilgandan keyin elementlari ozgartirilmaydi, list esa ozgaruvchan."),
        ("Python'da dict kalitlari qanday bolishi kerak?", ["A) Har qanday obyekt", "B) Hashable bolishi kerak", "C) Faqat string", "D) Faqat integer"], "B", "Lugat kalitlari hashable bolishi kerak."),
        ("Quyidagi murakkabliklardan qaysi biri odatda eng tez osadi?", ["A) O(log n)", "B) O(n)", "C) O(n log n)", "D) O(2ⁿ)"], "D", "Eksponensial O(2ⁿ) osish katta n da ancha tez ortadi."),
        ("SQL'da jadvaldan takroriy qatorlarni olib tashlab korsatish uchun nima ishlatiladi?", ["A) UNIQUE()", "B) DISTINCT", "C) REMOVE", "D) GROUP"], "B", "SELECT DISTINCT takroriy natijalarni bitta korinishda chiqaradi."),
        ("HTTP 404 holat kodi nimani anglatadi?", ["A) Server xatosi", "B) Ruxsat yoq", "C) Resurs topilmadi", "D) Muvaffaqiyat"], "C", "404 — soralgan resurs topilmadi."),
    ],
}


def get_all_questions_flat():
    items = []
    for subj, q_list in question_bank.items():
        for q, opts, ans, exp in q_list:
            items.append((subj, q, opts, ans, exp))
    return items


zakovat_questions = [
    ("Bir xonada 3 ta kalit, boshqa xonada 3 ta lampochka bor. Lampochkalar xonasiga faqat bir marta kirish mumkin. Qaysi kalit qaysi lampochkaniki ekanini qanday aniqlaysiz?", "kalit issiq sovuq yonib"),
    ("Sizda 8 ta bir xil korinishdagi shar bor. Bittasi boshqalaridan ogir. Pallali tarozida eng kamida necha tortishda topish mumkin?", "2 tortishda"),
    ("Bir kishi 10-qavatda yashaydi. Har kuni pastga lift bilan tushadi, qaytganda 7-qavatgacha chiqib, qolganini piyoda yuradi. Yomirli kuni esa 10-qavatga chiqadi. Nega?", "soyabon boyi past"),
    ("Soat 3:15 bolganda soat va minut millari orasidagi kichik burchak necha daraja?", "7.5 daraja"),
    ("12 ta tangadan bittasi soxta (yengil yoki ogirligi nomalum). Pallali tarozida eng kamida necha marta tortib, soxta tangani va uning ogir/yengilligini aniq topish mumkin?", "3 tortishda"),
    ("Qum soatlarida 4 daqiqalik va 7 daqiqalik ikkita soat bor. Ular yordamida aniq 9 daqiqani qanday olchash mumkin?", "4 va 7 birga aylantiriladi"),
    ("Bir qutida faqat qizil paypoqlar, ikkinchisida faqat kok, uchinchisida aralash. Uchala qutiga ham notogri yorliq yopishtirilgan. Qaysi qutidan bitta paypoq olib, hammasining togri yorligini aniqlash mumkin?", "aralash yorliqdan"),
    ("Daryo boyida bori, echki va karam bor. Qayiqda faqat bittasini olib otish mumkin. Agar bori bilan echki yoki echki bilan karam qarovsiz qolsa, biri ikkinchisini yeydi. Qanday otkaziladi?", "avval echki keyin karam echki qaytariladi"),
    ("Bir xonada 100 ta chiroq ochirilgan holda turibdi. 1-odam hammasini yoqadi, 2-odam 2-karralilarini ochiradi, 3-odam 3-karralilarini teskarisiga ozgartiradi... 100-odamgacha shunday davom etsa, oxirida nechta chiroq yoniq qoladi?", "10 ta"),
    ("Ikki shahar orasidagi masofa 120 km. Birinchi poyezd 60 km/soat tezlikda, ikkinchisi 40 km/soat tezlikda qarama-qarshi yonalishda yurdi. Ular uchrashguncha necha soat otadi?", "1.2 soat"),
    ("Bir odamda 3 ta shlyapa bor: 2 tasi qora, 1 tasi oq. Uch kishi qator turibdi: 3-odam 2-va 1-ni koradi, 2-odam faqat 1-ni koradi, 1-odam hech kimni kormaydi. 3-odam rangini bilmadi, 2-odam ham bilmadi, lekin 1-odam oz shlyapasining rangini topdi. Qaysi rang va nima uchun?", "qora chunki ikkisi oq bolsa bilardi"),
    ("100 ta mahbus bir qatorda turibdi. Har biriga qora yoki oq shlyapa kiydirilgan. Orqadagilar oldindagilarni koradi. Eng kamida nechta mahbus aniq oz shlyapasi rangini ayta oladi va qanday strategiya bilan?", "99 ta juftlik toqlik"),
    ("Bir xonada 3 ta sandiq bor: birida faqat olma, ikkinchisida faqat nok, uchinchisida ikkalasi. Barcha yorliqlar xato. Qanday qilib faqat bitta meva olish orqali barcha sandiqlarning ichini aniqlash mumkin?", "aralash sandiqdan"),
    ("Ota va oglining yoshlari yigindisi 66. Ota yoshining raqamlari ornini almashtirsak, oglining yoshi kelib chiqadi. Ularning yoshi necha bolishi mumkin?", "42 va 24"),
    ("Bir hovuzda nilufar gullari har kuni 2 baravar kopayadi. Agar hovuz 48-kuni toliq qoplansa, qaysi kuni yarmini qoplagan boladi?", "47 kuni"),
    ("5 ta qaroqchi 100 ta oltin tangani bolishishi kerak. Eng katta qaroqchi taqsimot taklif qiladi, kamida yarmi ovoz bersa otadi, aks holda tashlanadi. Eng katta qaroqchi nechta tanga olib, ozi tirik qolishi mumkin?", "98 ta"),
    ("Bir xonada 23 kishi bor. Kamida ikki kishining tugilgan kuni bir kunga togri kelish ehtimoli yuqorimi yoki yoqmi?", "ha yuqori"),
    ("3 litrlik va 5 litrlik idishlar yordamida 4 litr suvni qanday olchash mumkin?", "5 ni toldirib 3 ga quyiladi"),
    ("Bir odam 8 daqiqada 4 ta daraxt kesadi. Shu tezlikda 12 ta daraxtini necha daqiqada kesadi?", "24 daqiqada"),
    ("Bir sonning kvadratiga osha sonning ozini qoshsak 56 chiqadi. Bu musbat son necha?", "7"),
]

rebus_list = [
    (
        "Mantiqiy rebus:\n"
        "Bir so‘z bor: uning boshiga «KO‘» bo‘g‘ini, oxiriga esa «Z» harfi qo‘shilsa, "
        "atrofni ko‘rish vositasi hosil bo‘ladi; lekin o‘sha boshlang‘ich so‘zning o‘zi "
        "ko‘rish a’zosining asosiy qismi hisoblanadi.\n"
        "Bu qaysi so‘z?",
        "ko‘z",
        ["koz", "ko'z", "koʻz"],
    ),
    (
        "Mantiqiy rebus:\n"
        "Uchta quti bor: birida faqat olma, ikkinchisida faqat nok, uchinchisida aralash meva. "
        "Uchala qutining ham yozuvi noto‘g‘ri yopishtirilgan.\n"
        "Qaysi qutidan bitta meva olib qarash orqali barcha qutilarning haqiqiy ichini aniq bilish mumkin?",
        "aralash",
        ["aralash", "aralash yozuvi bor quti", "aralash quti"],
    ),
    (
        "Mantiqiy rebus:\n"
        "Men doim oldinga qarab yuraman, lekin na oyog‘im bor, na qanotim. "
        "Meni ushlab qolish ham, ortga qaytarish ham mumkin emas, lekin soatga qarasang, har soniya izimni ko‘rasan.\n"
        "Men nimaman?",
        "vaqt",
        ["vaqt", "zamon"],
    ),
    (
        "Mantiqiy rebus:\n"
        "«KITOB» so‘zining oxirgi harfini olib tashlab, o‘rniga «ILM» so‘zining oxirgi harfini qo‘shing, "
        "keyin esa insonni ilm va ma’rifatga yetaklaydigan asl narsani ayting.\n"
        "Asl so‘z qaysi?",
        "kitob",
        ["kitob", "kitoblar"],
    ),
    (
        "Mantiqiy rebus:\n"
        "Bir xonada 3 ta kalit, yon xonada esa ularga ulangan 3 ta lampochka bor. "
        "Lampochkalar turgan xonaga faqat bir marta kirish mumkin.\n"
        "Qaysi usul bilan qaysi kalit qaysi lampochkaniki ekanini aniq topish mumkin?",
        "kalitni yoqib issigini tekshirish",
        ["issiq", "kalit", "lampochka", "yonib turgan", "issigini"],
    ),
    (
        "Mantiqiy rebus:\n"
        "Bir kechada 2 ta soat bir vaqtda to‘g‘ri vaqtga sozlandi. Birinchisi har soatda 2 daqiqa oldinga ketadi, "
        "ikkinchisi esa har soatda 4 daqiqa ortda qoladi.\n"
        "Necha soatdan keyin ular yana bir-biriga nisbatan bir xil vaqtni ko‘rsatadi?",
        "120 soat",
        ["120", "120 soat", "120 soatdan keyin"],
    ),
    (
        "Mantiqiy rebus:\n"
        "Otasi 36 yoshda, o‘g‘li 12 yoshda. Otaning yoshi o‘g‘lining yoshidan necha baravar katta?\n"
        "Shu nisbat (otaning yoshi o‘g‘lining yoshidan 3 baravar katta bo‘lishi) yana necha yildan keyin takrorlanadi?",
        "hech qachon",
        ["hech qachon", "hech qachon bolmaydi", "yoq"],
    ),
    (
        "Mantiqiy rebus:\n"
        "Bir qog‘ozga ketma-ket 5 ta son yozilgan: 2, 6, 18, 54, ...\n"
        "Mantiqiy qonuniyatga ko‘ra keyingi son qaysi bo‘ladi?",
        "162",
        ["162"],
    ),
]

learn_guides = {
    ("Ingliz tili", "Lug‘at"): "Ingliz tili — Lug‘at\n• Consistency — izchillik\n• Opportunity — imkoniyat\n• Challenge — sinov, qiyinchilik\n• Achieve — erishmoq",
    ("Ingliz tili", "Mashqlar"): "Ingliz tili — Mashqlar\nBosh orinni toldiring: She ___ (go) to school every day.\nJavob: goes (Present Simple, 3-shaxs birlik).",
    ("Ingliz tili", "Grammatika"): "Ingliz tili — Grammatika\nPresent Simple oddiy takrorlanuvchi harakatlar uchun ishlatiladi: Subject + V1 (he/she/it + -s/-es).",
    ("Rus tili", "Lug‘at"): "Rus tili — Lug‘at\n• Знание — bilim\n• Усердие — tirishqoqlik\n• Решение — yechim\n• Развитие — rivojlanish",
    ("Rus tili", "Mashqlar"): "Rus tili — Mashqlar\nGapni toldiring: Я ___ книгу каждый вечер. (читать)\nJavob: читаю.",
    ("Rus tili", "Grammatika"): "Rus tili — Grammatika\nRus tilida fellar shaxs va sonda tuslanadi: я читаю, ты читаешь, он/она читает.",
    ("Arab tili", "Lug‘at"): "Arab tili — Lug‘at\n• علم (‘Ilmun) — ilm\n• صبر (Sabrun) — sabr\n• كتاب (Kitabun) — kitob\n• نور (Nurun) — nur",
    ("Arab tili", "Mashqlar"): "Arab tili — Mashqlar\n«طالب العلم» iborasining manosini toping.\nJavob: Ilm talab qiluvchi (talaba).",
    ("Arab tili", "Grammatika"): "Arab tili — Grammatika\nArab tilida sozlar ism (ot/sifat), fel va harf (komakchi/boglovchi)ga bolinadi.",
    ("Turk tili", "Lug‘at"): "Turk tili — Lug‘at\n• Çalışmak — ishlash / oqish\n• Hedef — maqsad\n• Başarı — muvaffaqiyat\n• Sabır — sabr",
    ("Turk tili", "Mashqlar"): "Turk tili — Mashqlar\nTogri shaklni toping: Ben her gün kitap ___ (okumak).\nJavob: okurum.",
    ("Turk tili", "Grammatika"): "Turk tilida unlilar uyg‘unligi (büyük ve küçük ünlü uyumu) qoshimcha tanlashda asosiy qoidadir.",
    ("Nemis tili", "Lug‘at"): "Nemis tili — Lug‘at\n• Das Buch — kitob\n• Lernen — organmoq\n• Das Ziel — maqsad\n• Der Erfolg — muvaffaqiyat",
    ("Nemis tili", "Mashqlar"): "Nemis tili — Mashqlar\nToldiring: Ich ___ Deutsch. (lernen)\nJavob: lerne.",
    ("Nemis tili", "Grammatika"): "Nemis tilida otlar der, die, das artikllari bilan keladi va darak gapda tuslangan fel odatda 2-orinda turadi.",
}

active_tests = {}
active_group_tests = {}
active_zakovat = {}
active_rebus_games = {}
add_book_states = {}
ai_users = set()
ai_history = {}
library_search_users = set()
ai_book_search_users = set()
translator_users = {}
learn_users = {}
feedback_users = set()
note_users = set()

mazgila_replies = [
    "O‘ylading-u, lekin mantiq bilan sal kelisholmay qolding-ov 😏",
    "Bu gapingni eshitib klaviaturang ham bir zum o‘ylanib qoldi.",
    "Qitmir Tavhid qayd etdi: jasorat 100%, aniqlik hali yo‘lda.",
    "Yaxshi urinish, faqat javob boshqa ko‘chadan o‘tib ketibdi.",
    "Bugun xayolparastlik bo‘limi ortiqcha smena bilan ishlayapti shekilli.",
    "Gapga gap topishda zo‘rsan, endi mazmunini ham qo‘shib yuborsak.",
    "Bu safar ijodiy erkinlik chegaradan chiqib ketibdi-ku.",
    "To‘g‘ri yo‘l burchakda turibdi, sen esa qarama-qarshi tomonga qarayapsan.",
    "Shunaqa gaplar bilan guruhdagi hamma kulib yuborsa, javobgarlik o‘zingda.",
    "Fikring bor, lekin xaritasi boshqa davlatniki ekan.",
    "Tez javob berding, lekin bir soniya nafas rostlasang yutarding.",
    "Qitmir Tavhid kuzatuvida: bu safar mantiq ta’tilda.",
    "Gapni chiroyli o‘rading, ichini esa bo‘sh qoldiribsan.",
    "Buni topish uchun alohida ilhom kerak edi — sen esa uni boshqa joydan olib kelibsan.",
    "Javobing shunday noyobki, kitobga yozib qo‘ysa arziydi.",
    "Hozirgi xulosang bilan shaxmat taxtasida piyoda ham kuladi.",
    "Yana bir qadam tashlasang, to‘g‘ri javobga teskari tomondan yetib borasan.",
    "Senda ishonch bor, faqat dalil yetishmayapti.",
    "Bu gapga alohida sharh yozish ham bir san’at.",
    "O‘zingga ishonching zo‘r, lekin bu safar ishonch yolg‘iz qolibdi.",
]


def pick_unique_mazgila_reply(chat_id: str, target_uid: int) -> str:
    bucket_key = f"{chat_id}:{target_uid}"
    used = data["used_mazgila"].setdefault(bucket_key, [])
    available = [phrase for phrase in mazgila_replies if phrase not in used]
    if not available:
        used.clear()
        available = list(mazgila_replies)
    chosen = random.choice(available)
    used.append(chosen)
    save_data()
    return chosen


async def show_home(message: types.Message):
    uid = message.from_user.id
    ai_users.discard(uid)
    active_tests.pop(uid, None)
    active_rebus_games.pop(uid, None)
    add_book_states.pop(uid, None)
    library_search_users.discard(uid)
    ai_book_search_users.discard(uid)
    translator_users.pop(uid, None)
    learn_users.pop(uid, None)
    feedback_users.discard(uid)
    note_users.discard(uid)
    await message.answer("Bosh menyu:", reply_markup=main_menu)


@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: types.Message):
    add_xp(message.from_user.id, 1)
    await show_home(message)


@dp.message(F.text == "🏠 Bosh menyu", F.chat.type == "private")
async def go_home(message: types.Message):
    await show_home(message)


@dp.message(F.text == "⬅️ Orqaga", F.chat.type == "private")
async def go_back(message: types.Message):
    uid = message.from_user.id
    if uid in add_book_states:
        state = add_book_states[uid]
        step = state.get("step")
        if step == "author":
            state["step"] = "title"
            await message.answer("1/4. Kitob nomini qaytadan yozing:", reply_markup=back_menu)
            return
        if step == "summary":
            state["step"] = "author"
            await message.answer("2/4. Kitob muallifini qaytadan yozing:", reply_markup=back_menu)
            return
        if step == "pdf":
            state["step"] = "summary"
            await message.answer("3/4. Kitob haqida qisqacha tavsifni qaytadan yozing:", reply_markup=back_menu)
            return
        add_book_states.pop(uid, None)
        await message.answer("Kutubxona bo‘limi:", reply_markup=library_menu)
        return

    if uid in library_search_users or uid in ai_book_search_users:
        library_search_users.discard(uid)
        ai_book_search_users.discard(uid)
        await message.answer("Kutubxona bo‘limi:", reply_markup=library_menu)
        return

    if uid in translator_users:
        translator_users.pop(uid, None)
        await open_translator_menu(message)
        return

    if uid in learn_users:
        l_state = learn_users[uid]
        if l_state.get("step") == "active" and l_state.get("lang"):
            l_state["step"] = "module"
            await message.answer(
                f"🌍 {l_state['lang']}\n\nNimadan boshlashni xohlaysiz?",
                reply_markup=learn_topic_inline(l_state["lang"]),
            )
            return
        await open_learn_menu(message, uid)
        return

    if uid in active_rebus_games:
        active_rebus_games.pop(uid, None)
        await mini_games_menu(message)
        return

    await show_home(message)


@dp.message(F.text == "🤖 AI", F.chat.type == "private")
async def start_ai_mode(message: types.Message):
    uid = message.from_user.id
    ai_users.add(uid)
    await message.answer(
        "🤖 AI SUHBAT REJIMI\n\nSavol yoki mavzu yozing. Chiqish uchun «🏠 Bosh menyu» ni bosing.",
        reply_markup=back_menu,
    )


@dp.message(F.text == "📚 Kutubxona", F.chat.type == "private")
async def open_library(message: types.Message):
    total_books = len(get_all_books())
    await message.answer(
        f"📚 KUTUBXONA\n\nPDF kitoblar soni: {total_books} ta.\n"
        "Kerakli bo‘limni tanlang:",
        reply_markup=library_menu,
    )


@dp.message(F.text == "🔍 Oddiy qidirish", F.chat.type == "private")
async def search_books_prompt(message: types.Message):
    library_search_users.add(message.from_user.id)
    await message.answer("Kitob nomi yoki muallif bo‘yicha kalit so‘z yozing:", reply_markup=back_menu)


@dp.message(F.text == "🤖 AI Kitob qidirish", F.chat.type == "private")
async def ai_search_books_prompt(message: types.Message):
    ai_book_search_users.add(message.from_user.id)
    await message.answer("Qanday mavzu yoki kitob izlayotganingizni yozing, AI tavsiya beradi:", reply_markup=back_menu)


@dp.message(F.text == "📂 Kategoriyalar", F.chat.type == "private")
async def book_categories(message: types.Message):
    books = get_all_books()
    cats = sorted({b[2] for b in books})
    if not cats:
        await message.answer("Hozircha PDF kitoblar kategoriyasi topilmadi.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c, callback_data=f"bcat:{c}")] for c in cats
        ]
    )
    await message.answer("📂 Kategoriyani tanlang:", reply_markup=kb)


@dp.callback_query(F.data.startswith("bcat:"))
async def show_books_by_category(callback: types.CallbackQuery):
    cat_name = callback.data.split(":", 1)[1]
    matches = [b for b in get_all_books() if b[2] == cat_name]
    if not matches:
        await callback.message.answer("Bu kategoriyada PDF kitoblar topilmadi.")
        await callback.answer()
        return
    for title, author, cat, summary, pdf_id in matches:
        caption = f"📖 {title}\nMuallif: {author}\nKategoriya: {cat}\n\n{summary}"
        await callback.message.answer_document(document=pdf_id, caption=caption)
    await callback.answer()


@dp.message(F.text == "🆕 Yangi kitoblar", F.chat.type == "private")
async def newest_books(message: types.Message):
    books = get_all_books()[-5:]
    if not books:
        await message.answer("Hozircha PDF kitoblar mavjud emas.")
        return
    for title, author, cat, summary, pdf_id in books:
        caption = f"🆕 {title}\nMuallif: {author}\nKategoriya: {cat}\n\n{summary}"
        await callback.message.answer_document(document=pdf_id, caption=caption)


@dp.message(F.text == "❤️ Sevimlilar", F.chat.type == "private")
async def favorite_books(message: types.Message):
    ukey = user_key(message.from_user.id)
    favs = data["favorites"].get(ukey, [])
    if not favs:
        await message.answer("Sevimli PDF kitoblar ro‘yxati hozircha bo‘sh.")
        return
    await message.answer("❤️ Sevimli kitoblaringiz:\n\n" + "\n".join(f"• {item}" for item in favs))


@dp.message(F.text == "📖 Kitoblar", F.chat.type == "private")
async def list_all_books(message: types.Message):
    books = get_all_books()
    if not books:
        await message.answer("Hozircha PDF fayli bor kitoblar qo‘shilmagan.")
        return
    buttons = [
        [InlineKeyboardButton(text=f"{idx + 1}. {b[0]} — {b[1]}", callback_data=f"bitem:{idx}")]
        for idx, b in enumerate(books)
    ]
    await message.answer(
        f"📖 PDF Kitoblar ro‘yxati ({len(books)} ta):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("bitem:"))
async def pick_single_book(callback: types.CallbackQuery):
    idx = int(callback.data.split(":", 1)[1])
    books = get_all_books()
    if 0 <= idx < len(books):
        title, author, cat, summary, pdf_id = books[idx]
        add_xp(callback.from_user.id, 2)
        fav_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❤️ Sevimlilarga qo‘shish", callback_data=f"bfav:{idx}")]
            ]
        )
        caption = f"📖 {title}\nMuallif: {author}\nKategoriya: {cat}\n\n{summary}"
        await callback.message.answer_document(document=pdf_id, caption=caption, reply_markup=fav_kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("bfav:"))
async def add_book_favorite(callback: types.CallbackQuery):
    idx = int(callback.data.split(":", 1)[1])
    books = get_all_books()
    if 0 <= idx < len(books):
        title, author, *_ = books[idx]
        label = f"{title} — {author}"
        ukey = user_key(callback.from_user.id)
        favs = data["favorites"].setdefault(ukey, [])
        if label not in favs:
            favs.append(label)
            save_data()
        await callback.answer("Sevimlilarga qo‘shildi!", show_alert=True)
        return
    await callback.answer()


@dp.message(F.text == "➕ Kitob qo'shish", F.chat.type == "private")
async def add_book_start(message: types.Message):
    uid = message.from_user.id
    if not is_bot_owner(uid):
        await message.answer(
            "Kitob qo‘shish huquqi faqat Ega va Super Ega uchun berilgan.",
            reply_markup=library_menu,
        )
        return
    add_book_states[uid] = {"step": "title"}
    await message.answer("1/4. Kitob nomini yozing:", reply_markup=back_menu)


@dp.message(F.document, F.chat.type == "private")
async def receive_book_pdf(message: types.Message):
    uid = message.from_user.id
    state = add_book_states.get(uid)
    if not state or state.get("step") != "pdf":
        return

    if not is_bot_owner(uid):
        add_book_states.pop(uid, None)
        await message.answer("Kitob qo‘shish huquqi faqat Ega va Super Ega uchun.", reply_markup=library_menu)
        return

    doc = message.document
    is_pdf = (doc.mime_type == "application/pdf") or (doc.file_name or "").lower().endswith(".pdf")
    if not is_pdf:
        await message.answer("Iltimos, faqat .pdf formatdagi fayl yuboring.")
        return

    title = state["title"]
    author = state["author"]
    summary = state["summary"]

    add_book_states.pop(uid, None)
    data["custom_books"].append({
        "title": title,
        "author": author,
        "category": "Kutubxona",
        "summary": summary,
        "pdf_file_id": doc.file_id,
        "added_by": uid,
    })
    ukey = user_key(uid)
    data["book_contributions"][ukey] = data["book_contributions"].get(ukey, 0) + 1
    add_xp(uid, 30)
    await message.answer(
        f"«{title}» ({author}) kitobi PDF fayli bilan ro‘yxatga qo‘shildi! (+30 XP)",
        reply_markup=library_menu,
    )


@dp.message(F.text.in_({"🇺🇿", "🇷🇺", "🇬🇧"}), F.chat.type == "private")
async def library_lang_badge(message: types.Message):
    lang_map = {"🇺🇿": "O‘zbekcha", "🇷🇺": "Ruscha", "🇬🇧": "Inglizcha"}
    await message.answer(f"Kutubxona tili: {lang_map.get(message.text, message.text)}", reply_markup=library_menu)


@dp.message(F.text == "🕌 Hadislar", F.chat.type == "private")
async def hadiths_menu(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text=f"{name} ({len(items)} ta)", callback_data=f"hcol:{name}")]
        for name, items in hadith_collections.items()
    ]
    await message.answer(
        "🕌 HADISLAR TO‘PLAMI\n\nTo‘plamni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("hcol:"))
async def pick_hadith_collection(callback: types.CallbackQuery):
    col_name = callback.data.split(":", 1)[1]
    items = hadith_collections.get(col_name, [])
    if not items:
        await callback.answer("Hadislar topilmadi.", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(text=f"#{i + 1}: {h[0][:40]}...", callback_data=f"hitem:{col_name}:{i}")]
        for i, h in enumerate(items)
    ]
    await callback.message.answer(
        f"🕌 {col_name} — hadisni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("hitem:"))
async def pick_single_hadith(callback: types.CallbackQuery):
    _, col_name, idx_str = callback.data.split(":", 2)
    idx = int(idx_str)
    items = hadith_collections.get(col_name, [])
    if 0 <= idx < len(items):
        text, source, url = items[idx]
        add_xp(callback.from_user.id, 3)
        await callback.message.answer(
            f"🕌 {col_name} — #{idx + 1}\n\n«{text}»\n\nManba: {source}\nHavola: {url}",
        )
    await callback.answer()


def pick_unique_private_question(uid: int, subject: str):
    bucket_key = f"priv:{uid}:{subject}"
    if subject == "🔀 Aralash":
        pool = [(subj, idx, item) for subj, q_list in question_bank.items() for idx, item in enumerate(q_list)]
        all_ids = [f"{subj}:{idx}" for subj, idx, _ in pool]
    else:
        pool = [(subject, idx, item) for idx, item in enumerate(question_bank[subject])]
        all_ids = [f"{subject}:{idx}" for idx, _ in enumerate(question_bank[subject])]

    used = data["used_tests"].setdefault(bucket_key, [])
    unused_indices = [i for i, qid in enumerate(all_ids) if qid not in used]
    if not unused_indices:
        return None

    chosen_pos = random.choice(unused_indices)
    chosen_qid = all_ids[chosen_pos]
    used.append(chosen_qid)
    save_data()

    subj_label, _, (q, options, correct, explanation) = pool[chosen_pos]
    return subj_label, q, options, correct, explanation


async def send_next_question(message: types.Message, uid: int, subject: str):
    picked = pick_unique_private_question(uid, subject)
    if picked is None:
        active_tests.pop(uid, None)
        await message.answer(
            f"🎉 {subject} bo‘yicha barcha savollar berib bo‘lindi! "
            "Boshqa fanni tanlang yoki «⚙️ Sozlamalar» -> «🔄 Savollar tarixini yangilash» orqali qayta boshlang.",
            reply_markup=test_subject_menu,
        )
        return

    subj_label, q, options, correct, explanation = picked
    active_tests[uid] = {
        "subject": subject,
        "correct": correct,
        "explanation": explanation,
        "question": q,
    }
    await message.answer(
        f"📝 {subj_label}\n\n{q}\n\n" + "\n".join(options) + "\n\nJavobni tanlang:",
        reply_markup=answer_menu,
    )


@dp.message(F.text == "📝 Test", F.chat.type == "private")
async def start_test(message: types.Message):
    active_tests.pop(message.from_user.id, None)
    await message.answer("📝 TEST\n\nFanni yoki Aralash rejimini tanlang:", reply_markup=test_subject_menu)


@dp.message(F.text == "📚 Boshqa fan", F.chat.type == "private")
async def switch_test_subject(message: types.Message):
    active_tests.pop(message.from_user.id, None)
    await message.answer("Fanni tanlang:", reply_markup=test_subject_menu)


@dp.message(F.text.in_(set(question_bank.keys()) | {"🔀 Aralash"}), F.chat.type == "private")
async def choose_test_subject(message: types.Message):
    await send_next_question(message, message.from_user.id, message.text)


@dp.message(F.text.in_({"A", "B", "C", "D", "a", "b", "c", "d"}), F.chat.type == "private")
async def answer_test(message: types.Message):
    uid = message.from_user.id
    test = active_tests.get(uid)
    if not test:
        return
    answer = message.text.upper()
    ukey = user_key(uid)
    if answer == test["correct"]:
        data["scores"][ukey] = data["scores"].get(ukey, 0) + 1
        add_xp(uid, 15)
        result = "Togri javob! +1 ball, +15 XP."
    else:
        add_xp(uid, 3)
        result = f"Notogri. Togri javob: {test['correct']}."

    await message.answer(
        f"{result}\n\nIzoh: {test['explanation']}\n\nKeyingi savol yuborilmoqda...",
    )
    await send_next_question(message, uid, test["subject"])


async def send_group_test_question(message: types.Message, chat_key: str):
    flat = get_all_questions_flat()
    used = data["used_group_tests"].setdefault(chat_key, [])
    available = [i for i in range(len(flat)) if i not in used]
    if not available:
        active_group_tests.pop(chat_key, None)
        await message.answer("Guruhda barcha test savollari berib bo‘lindi!")
        return
    idx = random.choice(available)
    used.append(idx)
    save_data()

    subj, q, opts, ans, exp = flat[idx]
    active_group_tests[chat_key] = {
        "subject": subj,
        "question": q,
        "options": opts,
        "correct": ans,
        "explanation": exp,
    }
    await message.answer(
        f"📝 GURUH TESTI ({subj})\n\n{q}\n\n" + "\n".join(opts) + "\n\nJavobni (A, B, C yoki D) yozing. Toxtatish: *stop",
    )


async def open_translator_menu(message: types.Message):
    await message.answer(
        "🌐 TARJIMON\n\nQaysi tilga tarjima qilish kerakligini tanlang:",
        reply_markup=translator_inline,
    )


@dp.message(F.text == "🌐 Tarjimon", F.chat.type == "private")
async def translator(message: types.Message):
    await open_translator_menu(message)


@dp.callback_query(F.data.startswith("tr_dir:"))
async def select_translator_direction(callback: types.CallbackQuery):
    target_lang = callback.data.split(":", 1)[1]
    translator_users[callback.from_user.id] = target_lang
    await callback.message.answer(
        f"Yonalish tanlandi: {target_lang}\n\nEndi tarjima qilinadigan matnni yuboring.",
        reply_markup=back_menu,
    )
    await callback.answer()


async def open_learn_menu(message: types.Message, uid: int):
    learn_users[uid] = {"step": "language"}
    await message.answer(
        "🌍 TIL O‘RGANISH\n\n1-qadam: Qaysi tilni organmoqchisiz?",
        reply_markup=learn_lang_inline,
    )


@dp.message(F.text == "🌍 Til o‘rganish", F.chat.type == "private")
async def learn_language_start(message: types.Message):
    await open_learn_menu(message, message.from_user.id)


@dp.callback_query(F.data.startswith("learn_lang:"))
async def learn_pick_language(callback: types.CallbackQuery):
    lang_name = callback.data.split(":", 1)[1]
    uid = callback.from_user.id
    learn_users[uid] = {"step": "module", "lang": lang_name}
    await callback.message.edit_text(
        f"🌍 {lang_name}\n\n2-qadam: Nimadan boshlashni xohlaysiz?",
        reply_markup=learn_topic_inline(lang_name),
    )
    await callback.answer()


@dp.callback_query(F.data == "learn_back_lang")
async def learn_back_language(callback: types.CallbackQuery):
    learn_users[callback.from_user.id] = {"step": "language"}
    await callback.message.edit_text(
        "🌍 TIL O‘RGANISH\n\n1-qadam: Qaysi tilni organmoqchisiz?",
        reply_markup=learn_lang_inline,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("learn_mod:"))
async def learn_pick_module(callback: types.CallbackQuery):
    _, lang_name, module_name = callback.data.split(":", 2)
    uid = callback.from_user.id
    learn_users[uid] = {"step": "active", "lang": lang_name, "module": module_name}
    add_xp(uid, 5)
    guide = learn_guides.get(
        (lang_name, module_name),
        f"🌍 {lang_name} — {module_name}\n\nBoshlash uchun savol yoki mavzu yozing.",
    )
    await callback.message.answer(
        guide + "\n\nShu til va yonalish boyicha savol bersangiz, batafsil tushuntirib beraman.",
        reply_markup=back_menu,
    )
    await callback.answer()


async def start_rebus_game(message: types.Message, uid: int):
    bucket = f"rebus:{uid}"
    used = data["used_rebus"].setdefault(bucket, [])
    available = [i for i in range(len(rebus_list)) if i not in used]
    if not available:
        used.clear()
        available = list(range(len(rebus_list)))
    idx = random.choice(available)
    used.append(idx)
    save_data()

    rebus_text, answer, variants = rebus_list[idx]
    active_rebus_games[uid] = {"answer": answer, "variants": variants}
    await message.answer(
        f"🧩 MANTIQIY REBUS #{idx + 1}/{len(rebus_list)}\n\n{rebus_text}\n\nJavobni yozib yuboring:",
        reply_markup=back_menu,
    )


@dp.message(F.text == "🎮 O‘yinlar", F.chat.type == "private")
async def mini_games_menu(message: types.Message):
    await message.answer(
        "🎮 O‘YINLAR BO‘LIMI\n\n"
        "Mantiqiy rebus yoki Telegram mini-o‘yinlaridan birini tanlang:",
        reply_markup=mini_games_inline,
    )


@dp.callback_query(F.data.startswith("mgame:"))
async def launch_telegram_mini_game(callback: types.CallbackQuery):
    kind = callback.data.split(":", 1)[1]
    if kind == "rebus":
        await callback.answer()
        await start_rebus_game(callback.message, callback.from_user.id)
        return

    dice_map = {
        "basket": ("🏀", "Basketbol Mini-o‘yini"),
        "football": ("⚽", "Futbol Mini-o‘yini"),
        "bowling": ("🎳", "Bowling Mini-o‘yini"),
        "slot": ("🎰", "Slot Mini-o‘yini"),
    }
    emoji, title = dice_map.get(kind, ("🎲", "Mini-o‘yin"))
    dice_msg = await callback.message.answer_dice(emoji=emoji)
    val = dice_msg.dice.value if dice_msg.dice else 0
    if val >= 4:
        add_xp(callback.from_user.id, 15)
        outcome = f"Zo‘r natija ({val})! +15 XP"
    else:
        add_xp(callback.from_user.id, 5)
        outcome = f"Natija: {val}. +5 XP"
    await callback.message.answer(f"🎮 {title}\n{outcome}", reply_markup=mini_games_inline)
    await callback.answer()


@dp.message(F.text == "👤 Profil", F.chat.type == "private")
async def user_profile(message: types.Message):
    uid = message.from_user.id
    ukey = user_key(uid)
    role_txt = get_role_label(uid)
    xp = data["xp"].get(ukey, 0)
    level = calc_level(xp)
    msgs = data["messages_count"].get(ukey, 0)
    score = data["scores"].get(ukey, 0)
    wins = data["zakovat_wins"].get(ukey, 0)
    books = data["book_contributions"].get(ukey, 0)
    favs = len(data["favorites"].get(ukey, []))
    notes = data["notes"].get(ukey, [])
    notes_txt = "\n".join(f"• {n}" for n in notes[-5:]) if notes else "Hozircha eslatma yoq."

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Eslatma qoshish", callback_data="prof:add_note"),
                InlineKeyboardButton(text="🗑 Eslatmalarni tozalash", callback_data="prof:clear_notes"),
            ]
        ]
    )
    await message.answer(
        f"👤 SHAXSIY PROFIL — {message.from_user.full_name}\n"
        f"🛡 Maqom: {role_txt}\n\n"
        f"🏅 Daraja: {level} | ✨ XP: {xp}\n"
        f"💬 Xabarlar: {msgs}\n"
        f"📝 Test ballari: {score}\n"
        f"🧠 Zakovat galabalari: {wins}\n"
        f"📚 Qoshgan kitoblar: {books} | ❤️ Sevimlilar: {favs}\n\n"
        f"📌 Eslatmalar:\n{notes_txt}",
        reply_markup=kb,
    )


@dp.callback_query(F.data == "prof:add_note")
async def profile_add_note(callback: types.CallbackQuery):
    note_users.add(callback.from_user.id)
    await callback.message.answer("Yangi eslatma yoki vazifa matnini yozing:", reply_markup=back_menu)
    await callback.answer()


@dp.callback_query(F.data == "prof:clear_notes")
async def profile_clear_notes(callback: types.CallbackQuery):
    data["notes"][user_key(callback.from_user.id)] = []
    save_data()
    await callback.message.answer("Eslatmalar tozalandi.", reply_markup=main_menu)
    await callback.answer()


@dp.message(F.text == "⚙️ Sozlamalar", F.chat.type == "private")
async def settings_menu(message: types.Message):
    uid = message.from_user.id
    await message.answer(
        "⚙️ SOZLAMALAR\n\nShaxsiy parametrlarni boshqaring:",
        reply_markup=build_settings_inline(uid),
    )


@dp.callback_query(F.data.startswith("set:"))
async def settings_action(callback: types.CallbackQuery):
    uid = callback.from_user.id
    action = callback.data.split(":", 1)[1]
    cfg = get_user_settings(uid)

    if action == "lang":
        langs = ["🇺🇿 O‘zbek", "🇷🇺 Русский", "🇬🇧 English"]
        cur_idx = langs.index(cfg["lang"]) if cfg["lang"] in langs else 0
        cfg["lang"] = langs[(cur_idx + 1) % len(langs)]
        save_data()
    elif action == "style":
        cfg["style"] = "Batafsil" if cfg["style"] == "Qisqa" else "Qisqa"
        save_data()
    elif action == "notif":
        cfg["notifications"] = not bool(cfg["notifications"])
        save_data()
    elif action == "reset_history":
        ukey = user_key(uid)
        for bucket in ("used_tests", "used_rebus"):
            for k in [k for k in data[bucket] if k.endswith(f":{uid}")]:
                data[bucket].pop(k, None)
        ai_history.pop(uid, None)
        data["favorites"].setdefault(ukey, [])
        save_data()
        await callback.answer("Savollar va suhbat tarixi yangilandi!", show_alert=True)

    await callback.message.edit_reply_markup(reply_markup=build_settings_inline(uid))
    await callback.answer()


@dp.message(F.text == "❓ Yordam", F.chat.type == "private")
async def help_center(message: types.Message):
    await message.answer(
        "❓ YORDAM — TAVHID BOT\n\n"
        "Guruh buyruqlari: *test, *zakovat, *stop, *men, *vse, *top, *mavzu.\n"
        "Adminlar uchun: *admin, *unadmin, *mute, *unmute, *ban, *unban, *mazgila.\n"
        "Ega va Super Ega uchun: *say, *pin, *unpin, *clean, *status.\n"
        "Faqat Super Ega uchun: *ega, *unega, *egalar.",
        reply_markup=help_menu,
    )


@dp.message(F.text == "❓ Ko'p beriladigan savollar", F.chat.type == "private")
async def faq(message: types.Message):
    await message.answer(
        "❓ KO‘P BERILADIGAN SAVOLLAR\n\n"
        "• Testlar shaxsiy chatda va *test buyrugi bilan guruhda ishlaydi.\n"
        "• Zakovat guruhda *zakovat bilan oynaladi, *top reytingni korsatadi, *mavzu kun mavzusini beradi.\n"
        "• Kitoblarni faqat Ega va Super Ega qo‘sha oladi.\n"
        "• *vse faqat Tavhid kuzatgan va ochirish mumkin bolgan oz xabarlaringizni ochiradi.\n"
        "• Guruhda 'Tavhid' deb chaqirsangiz yoki Tavhid xabariga javob qilib yozsangiz, bot javob beradi.",
        reply_markup=help_menu,
    )


@dp.message(F.text.in_({"📩 Administratorga murojaat", "💬 Taklif va shikoyatlar"}), F.chat.type == "private")
async def feedback_start(message: types.Message):
    feedback_users.add(message.from_user.id)
    await message.answer("Murojaat yoki taklifingizni yozing. U administratorga yuboriladi.", reply_markup=back_menu)


def build_prompt(uid: int, question: str) -> str:
    cfg = get_user_settings(uid)
    style_hint = "qisqa va londa" if cfg.get("style") == "Qisqa" else "batafsil va tushunarli"
    prompt = f"Sen Tavhid nomli yordamchisan. Ozbek tilida {style_hint} javob ber.\n"
    for old_q, old_a in ai_history.get(uid, [])[-4:]:
        prompt += f"Foydalanuvchi: {old_q}\nTavhid: {old_a}\n"
    return prompt + f"Foydalanuvchi: {question}\nTavhid:"


async def ask_ai(prompt: str) -> str:
    errors = []

    if gemini_client:
        for model_name in FAST_GEMINI_MODELS:
            for attempt in range(3):
                try:
                    response = await gemini_client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    if response and response.text:
                        return response.text
                    errors.append(f"{model_name}: bo‘sh javob")
                    break
                except Exception as err:
                    err_repr = repr(err)
                    errors.append(f"{model_name} (urinish {attempt + 1}): {err_repr}")
                    print("Tavhid Gemini xatosi ->", f"{model_name}: {err_repr}")
                    is_temp_overload = ("503" in err_repr) or ("UNAVAILABLE" in err_repr) or ("429" in err_repr)
                    if is_temp_overload and attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    break
    else:
        errors.append("Gemini mijozi ulanmagan (GEMINI_API_KEY tekshiring)")

    if openai_client and USE_OPENAI_FALLBACK:
        try:
            resp = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            content = resp.choices[0].message.content
            if content:
                return content
            errors.append(f"{OPENAI_MODEL}: bo‘sh javob")
        except Exception as err:
            err_msg = f"{OPENAI_MODEL}: {repr(err)}"
            errors.append(err_msg)
            print("Tavhid OpenAI xatosi ->", err_msg)

    raise RuntimeError(" | ".join(errors))


@dp.message(F.text, F.chat.type == "private")
async def private_text_router(message: types.Message):
    uid = message.from_user.id
    text_raw = message.text.strip()
    if not text_raw:
        return

    if uid in note_users:
        note_users.discard(uid)
        notes = data["notes"].setdefault(user_key(uid), [])
        notes.append(text_raw)
        data["notes"][user_key(uid)] = notes[-20:]
        save_data()
        await message.answer("Eslatma saqlandi!", reply_markup=main_menu)
        return

    if uid in add_book_states:
        if not is_bot_owner(uid):
            add_book_states.pop(uid, None)
            await message.answer("Kitob qo‘shish huquqi faqat Ega va Super Ega uchun.", reply_markup=library_menu)
            return

        state = add_book_states[uid]
        if state["step"] == "title":
            state["title"] = text_raw
            state["step"] = "author"
            await message.answer("2/4. Kitob muallifini yozing:", reply_markup=back_menu)
            return
        if state["step"] == "author":
            state["author"] = text_raw
            state["step"] = "summary"
            await message.answer("3/4. Kitob haqida qisqacha tavsif yozing:", reply_markup=back_menu)
            return
        if state["step"] == "summary":
            state["summary"] = text_raw
            state["step"] = "pdf"
            await message.answer(
                "4/4. Endi kitobning PDF (.pdf) faylini yuboring:",
                reply_markup=back_menu,
            )
            return
        if state["step"] == "pdf":
            await message.answer("Iltimos, kitobning PDF (.pdf) faylini yuboring.")
            return

    if uid in library_search_users:
        library_search_users.discard(uid)
        query = normalize(text_raw)
        all_books = get_all_books()
        matches = [b for b in all_books if query in normalize(b[0]) or query in normalize(b[1]) or query in normalize(b[2])]
        if matches:
            for title, author, cat, summary, pdf_id in matches:
                caption = f"📖 {title}\nMuallif: {author}\nKategoriya: {cat}\n\n{summary}"
                await message.answer_document(document=pdf_id, caption=caption)
        else:
            await message.answer("Bu sorov boyicha PDF kitob topilmadi.")
        await message.answer("Kutubxona bolimiga qaytingiz.", reply_markup=library_menu)
        return

    if uid in ai_book_search_users:
        ai_book_search_users.discard(uid)
        if not gemini_client and not (openai_client and USE_OPENAI_FALLBACK):
            await message.answer("AI hozircha faol emas (GEMINI_API_KEY tekshiring).", reply_markup=library_menu)
            return
        await bot.send_chat_action(message.chat.id, "typing")
        try:
            prompt = (
                f"Foydalanuvchi kutubxonadan quyidagi mavzu/kitob boyicha qidiruv qildi: '{text_raw}'. "
                "Ozbek tilida eng mos 3-4 ta kitobni (nomi, muallifi va qisqa tavsifi bilan) tavsiya qiling."
            )
            ans = await ask_ai(prompt)
            await message.answer(f"Tavhid AI Kitob tavsiyasi\n\n{ans}", reply_markup=library_menu)
        except Exception as err:
            await message.answer(f"AI qidiruvda xatolik: {err}", reply_markup=library_menu)
        return

    if uid in translator_users:
        target_lang = translator_users[uid]
        if not gemini_client and not (openai_client and USE_OPENAI_FALLBACK):
            await message.answer("AI tarjimon hozircha faol emas (GEMINI_API_KEY tekshiring).", reply_markup=back_menu)
            return
        await bot.send_chat_action(message.chat.id, "typing")
        try:
            prompt = (
                f"Quyidagi matnni faqat {target_lang} tiliga aniq va tabiiy tarjima qilib ber. "
                f"Ortiqcha kirish sozlarsiz faqat tarjimani yoz:\n\n{text_raw}"
            )
            translated = await ask_ai(prompt)
            add_xp(uid, 2)
            await message.answer(f"Tarjima ({target_lang}):\n\n{translated}")
        except Exception as err:
            await message.answer(f"Tarjima xatosi: {err}")
        return

    if uid in learn_users and learn_users[uid].get("step") == "active":
        l_state = learn_users[uid]
        if gemini_client or (openai_client and USE_OPENAI_FALLBACK):
            await bot.send_chat_action(message.chat.id, "typing")
            try:
                prompt = (
                    f"Foydalanuvchi '{l_state['lang']}' tilini '{l_state['module']}' yonalishi boyicha organmoqda. "
                    f"Savol/sorov: {text_raw}. Ozbek tilida tushunarli, amaliy va aniq javob bering."
                )
                reply_txt = await ask_ai(prompt)
                add_xp(uid, 3)
                await message.answer(reply_txt)
            except Exception as err:
                await message.answer(f"Xatolik: {err}")
        return

    if uid in feedback_users:
        feedback_users.discard(uid)
        user_info = f"{message.from_user.full_name} (ID: {uid}"
        if message.from_user.username:
            user_info += f", @{message.from_user.username}"
        user_info += ")"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"Yangi murojaat (Tavhid)\nKimdan: {user_info}\n\n{text_raw}",
            )
            await message.answer("Murojaatingiz administratorga yuborildi!", reply_markup=main_menu)
        except Exception as err:
            print("Adminga yuborishda xato:", repr(err))
            await message.answer("Murojaatni yuborishda xatolik yuz berdi.", reply_markup=main_menu)
        return

    if uid in active_rebus_games:
        game = active_rebus_games[uid]
        ans = game["answer"]
        accepted = [ans] + game.get("variants", [])
        norm_user = normalize(text_raw)
        is_correct = any(
            norm_user == normalize(v) or (len(normalize(v)) >= 3 and normalize(v) in norm_user)
            for v in accepted
        )
        if is_correct:
            active_rebus_games.pop(uid, None)
            add_xp(uid, 25)
            await message.answer(f"Barakalla! Mantiqiy rebus javobi '{ans}' edi! (+25 XP)", reply_markup=main_menu)
        else:
            await message.answer("Javob notogri, yana urinib koring (yoki '⬅️ Orqaga' bosing).")
        return

    if uid not in ai_users:
        return

    await bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await ask_ai(build_prompt(uid, text_raw))
        ai_history.setdefault(uid, []).append((text_raw, answer))
        ai_history[uid] = ai_history[uid][-8:]
        add_xp(uid, 2)
        await message.answer(answer)
    except Exception as error:
        print("Tavhid AI xatosi:", repr(error))
        await message.answer(f"AI javob bera olmadi.\nSabab: {error}")


async def is_chat_admin(chat_id: int, user_id: int) -> bool:
    if is_bot_owner(user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {"administrator", "creator"}
    except (TelegramBadRequest, TelegramForbiddenError):
        return False


async def track_group_message(message: types.Message):
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    chat_str = str(message.chat.id)
    key = f"{chat_str}:{message.from_user.id}"
    items = data["tracked"].setdefault(key, [])
    if message.message_id not in items:
        items.append(message.message_id)
    data["tracked"][key] = items[-500:]

    recent_list = data.setdefault("chat_recent_msgs", {}).setdefault(chat_str, [])
    if message.message_id not in recent_list:
        recent_list.append(message.message_id)
    data["chat_recent_msgs"][chat_str] = recent_list[-100:]

    add_xp(message.from_user.id, 1, messages_delta=1)


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def group_handler(message: types.Message):
    if message.new_chat_members:
        for member in message.new_chat_members:
            await message.answer(f"Xush kelibsiz, {member.full_name}! Tavhid guruhiga xush kelibsiz.")
        return
    if message.left_chat_member:
        await message.answer(f"{message.left_chat_member.full_name} guruhni tark etdi.")
        return
    if not message.from_user or message.from_user.is_bot:
        return

    await track_group_message(message)
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    uid = user_key(message.from_user.id)
    chat_id = str(message.chat.id)
    parts = text.split()
    cmd_lower = parts[0].lower()

    if cmd_lower in {"*ega", "*unega", "*egalar"}:
        if not is_super_owner(message.from_user.id):
            await message.reply("Bu buyruq faqat Super Ega uchun.")
            return

        if cmd_lower == "*egalar":
            super_txt = ", ".join(str(x) for x in sorted(SUPER_OWNER_IDS)) or "Yo‘q"
            owners_txt = ", ".join(str(x) for x in data.get("owners", [])) or "Hozircha yo‘q"
            await message.reply(
                f"🛡 TAVHID ROLLARI RO‘YXATI\n\n"
                f"👑 Super Ega: {super_txt}\n"
                f"⭐ Ega: {owners_txt}"
            )
            return

        target_user = message.reply_to_message.from_user if message.reply_to_message else None
        target_id = target_user.id if target_user else None
        if not target_id and len(parts) > 1 and parts[1].isdigit():
            target_id = int(parts[1])
        if not target_id:
            await message.reply("Foydalanuvchi xabariga javob bering yoki ID yozing: *ega <id> / *unega <id>")
            return
        if is_super_owner(target_id):
            await message.reply("Super Ega maqomini o‘zgartirib bo‘lmaydi.")
            return

        owners_list = data.setdefault("owners", [])
        target_label = format_user_mention(target_user) if target_user else f"ID {target_id}"
        if cmd_lower == "*ega":
            if target_id not in owners_list:
                owners_list.append(target_id)
                save_data()
            await message.reply(f"🛡 {target_label} Tavhid botida Ega etib tayinlandi.")
        else:
            if target_id in owners_list:
                owners_list.remove(target_id)
                save_data()
            await message.reply(f"🛡 {target_label} dan Ega maqomi olindi.")
        return

    if cmd_lower in {"*say", "*pin", "*unpin", "*clean", "*status"}:
        if not is_bot_owner(message.from_user.id):
            await message.reply("Bu buyruq faqat Ega va Super Ega uchun.")
            return

        if cmd_lower == "*say":
            say_text = text[len(parts[0]):].strip()
            if not say_text:
                await message.reply("Foydalanish: *say <xabar matni>")
                return
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
            await message.answer(say_text)
            return

        if cmd_lower == "*pin":
            if not message.reply_to_message:
                await message.reply("Qadash uchun biror xabarga javob qilib *pin yozing.")
                return
            try:
                await bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id, disable_notification=False)
                await message.reply("📌 Xabar guruhda qadandi.")
            except (TelegramBadRequest, TelegramForbiddenError) as err:
                await message.reply(f"Qadab bo‘lmadi: {err}")
            return

        if cmd_lower == "*unpin":
            try:
                if message.reply_to_message:
                    await bot.unpin_chat_message(message.chat.id, message_id=message.reply_to_message.message_id)
                else:
                    await bot.unpin_chat_message(message.chat.id)
                await message.reply("📍 Qadalgan xabar olindi.")
            except (TelegramBadRequest, TelegramForbiddenError) as err:
                await message.reply(f"Yechib bo‘lmadi: {err}")
            return

        if cmd_lower == "*clean":
            limit = 10
            if len(parts) > 1 and parts[1].isdigit():
                limit = max(1, min(50, int(parts[1])))
            recent_ids = list(reversed(data.get("chat_recent_msgs", {}).get(chat_id, [])))
            deleted_cnt = 0
            for mid in recent_ids:
                if mid == message.message_id:
                    continue
                try:
                    await bot.delete_message(message.chat.id, mid)
                    deleted_cnt += 1
                except TelegramBadRequest:
                    pass
                except TelegramForbiddenError:
                    break
                if deleted_cnt >= limit:
                    break
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
            status_msg = await message.answer(f"🧹 {deleted_cnt} ta xabar tozalandi.")
            await asyncio.sleep(3)
            try:
                await bot.delete_message(message.chat.id, status_msg.message_id)
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
            return

        if cmd_lower == "*status":
            role_txt = get_role_label(message.from_user.id)
            active_m = data.get("mazgila_targets", {}).get(chat_id) or ("Yoqilgan" if chat_id in data.get("mazgila", {}) else "Yo‘q")
            await message.reply(
                f"📊 TAVHID HOLATI\n\n"
                f"Sizning maqomingiz: {role_txt}\n"
                f"PDF kitoblar: {len(get_all_books())} ta\n"
                f"Mazgilash rejimi: {active_m}\n"
                f"Faol test: {'Ha' if chat_id in active_group_tests else 'Yo‘q'}\n"
                f"Faol zakovat: {'Ha' if chat_id in active_zakovat else 'Yo‘q'}"
            )
            return

    if text.startswith("*men"):
        score = data["scores"].get(uid, 0)
        wins = data["zakovat_wins"].get(uid, 0)
        books_count = data["book_contributions"].get(uid, 0)
        xp = data["xp"].get(uid, 0)
        level = calc_level(xp)
        msgs = data["messages_count"].get(uid, 0)
        role_txt = get_role_label(message.from_user.id)
        await message.reply(
            f"{message.from_user.full_name} ({role_txt})\n"
            f"Level: {level} | XP: {xp}\n"
            f"Xabarlar: {msgs}\n"
            f"Test ballari: {score}\n"
            f"Zakovat galabalari: {wins}\n"
            f"Qoshgan kitoblari: {books_count}"
        )
        return

    if text.strip().lower() == "*top":
        top_users = sorted(data["xp"].items(), key=lambda item: item[1], reverse=True)[:10]
        if not top_users:
            await message.reply("Hozircha reyting malumotlari yoq.")
            return
        lines = ["🏆 TAVHID GURUH REYTINGI (TOP XP)\n"]
        for pos, (u_str, u_xp) in enumerate(top_users, 1):
            lines.append(f"{pos}. ID {u_str} — {u_xp} XP (Lv.{calc_level(u_xp)})")
        await message.reply("\n".join(lines))
        return

    if text.strip().lower() == "*mavzu":
        topics = [
            "Bugungi muhokama mavzusi: Ilm va intizom hayotda qaysi holatda ko‘proq natija beradi?",
            "Bugungi muhokama mavzusi: Kitob o‘qishda eng samarali odat qaysi?",
            "Bugungi muhokama mavzusi: Jamoada ishonchni saqlab qolishning asosiy sharti nima?",
            "Bugungi muhokama mavzusi: Qiyin qaror oldida mantiq muhimmi yoki tajriba?",
        ]
        chosen_topic = random.choice(topics)
        data["daily_topic"][chat_id] = chosen_topic
        save_data()
        await message.answer(f"💬 {chosen_topic}\n\nFikringizni izohda qoldiring!")
        return

    if text.strip().lower() == "*vse":
        key = f"{chat_id}:{uid}"
        ids = [mid for mid in data["tracked"].get(key, []) if mid != message.message_id]
        deleted = 0
        for message_id in reversed(ids):
            try:
                await bot.delete_message(message.chat.id, message_id)
                deleted += 1
            except TelegramBadRequest:
                pass
            except TelegramForbiddenError:
                break
        data["tracked"][key] = []
        save_data()
        await message.answer(
            f"🧹 {message.from_user.full_name}: {deleted} ta Tavhid qayd etgan xabar o‘chirildi."
        )
        return

    if text.lower().startswith("*test"):
        if chat_id in active_group_tests:
            await message.reply("Guruhda test allaqachon davom etmoqda. Toxtatish: *stop")
            return
        await send_group_test_question(message, chat_id)
        return

    if text.lower().startswith("*zakovat"):
        if chat_id in active_zakovat:
            await message.reply("Zakovat allaqachon davom etmoqda. Toxtatish: *stop")
            return
        used = data["used_zakovat"].setdefault(chat_id, [])
        available = [i for i in range(len(zakovat_questions)) if i not in used]
        if not available:
            used.clear()
            available = list(range(len(zakovat_questions)))
        index = random.choice(available)
        used.append(index)
        save_data()
        active_zakovat[chat_id] = {"index": index, "answer": zakovat_questions[index][1], "winner": False}
        await message.answer(
            f"ZAKOVAT BOSHLANDI! (Savol #{index + 1}/{len(zakovat_questions)})\n\n"
            + zakovat_questions[index][0]
            + "\n\nJavobingizni oddiy xabar qilib yozing. Toxtatish: *stop",
        )
        return

    if text.strip().lower() == "*stop":
        stopped = False
        if chat_id in active_group_tests:
            active_group_tests.pop(chat_id, None)
            stopped = True
        if chat_id in active_zakovat:
            active_zakovat.pop(chat_id, None)
            stopped = True
        if stopped:
            await message.reply("Faol oyun/test toxtatildi.")
        else:
            await message.reply("Hozir faol test yoki Zakovat yoq.")
        return

    if text.startswith(("*admin", "*unadmin", "*mute", "*unmute", "*ban", "*unban", "*mazgila")):
        if not await is_chat_admin(message.chat.id, message.from_user.id):
            await message.reply("Bu buyruq faqat guruh adminlari uchun.")
            return

        command = cmd_lower
        target = message.reply_to_message.from_user if message.reply_to_message else None

        if command == "*mazgila":
            if len(parts) > 1 and parts[1].lower() == "off":
                prev_uid = data["mazgila"].pop(chat_id, None)
                saved_label = data.get("mazgila_targets", {}).pop(chat_id, None)
                save_data()
                target_label = "foydalanuvchi"
                if target:
                    target_label = format_user_mention(target)
                elif saved_label:
                    target_label = saved_label
                elif prev_uid is not None:
                    try:
                        prev_member = await bot.get_chat_member(message.chat.id, prev_uid)
                        target_label = format_user_mention(prev_member.user)
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
                await message.reply(f"😇 Mazgilash rejimi o‘chirildi: {target_label}")
            elif target:
                user_label = format_user_mention(target)
                data["mazgila"][chat_id] = target.id
                data.setdefault("mazgila_targets", {})[chat_id] = user_label
                data["used_mazgila"][f"{chat_id}:{target.id}"] = []
                save_data()
                await message.reply(
                    f"😈 AI mazgilash rejimi yoqildi: {user_label}\n"
                    f"Qitmir Tavhid ishga tushdi 😏"
                )
            else:
                await message.reply("Foydalanuvchining xabariga javob qilib *mazgila yozing (o‘chirish uchun: *mazgila off).")
            return

        if not target:
            await message.reply("Bu buyruqni ishlatish uchun foydalanuvchining xabariga javob bering.")
            return

        if command in {"*mute", "*ban"} and (is_bot_owner(target.id) or await is_chat_admin(message.chat.id, target.id)):
            await message.reply("Administrator yoki Ega/Super Ega ustidan *mute yoki *ban qilib bolmaydi!")
            return

        try:
            if command == "*admin":
                await bot.promote_chat_member(
                    message.chat.id,
                    target.id,
                    can_manage_chat=True,
                    can_delete_messages=True,
                    can_manage_video_chats=True,
                    can_restrict_members=True,
                    can_promote_members=False,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=True,
                    can_post_messages=False,
                    can_edit_messages=False,
                )
                await message.reply(f"{target.full_name} administrator qilindi.")
            elif command == "*unadmin":
                await bot.promote_chat_member(
                    message.chat.id,
                    target.id,
                    can_manage_chat=False,
                    can_delete_messages=False,
                    can_manage_video_chats=False,
                    can_restrict_members=False,
                    can_promote_members=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                    can_post_messages=False,
                    can_edit_messages=False,
                )
                await message.reply(f"{target.full_name} administratorlikdan olindi.")
            elif command == "*mute":
                await bot.restrict_chat_member(
                    message.chat.id,
                    target.id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
                await message.reply(f"{target.full_name} guruhda yozishdan cheklandi (*mute).")
            elif command == "*unmute":
                await bot.restrict_chat_member(
                    message.chat.id,
                    target.id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    ),
                )
                await message.reply(f"{target.full_name} uchun cheklov olib tashlandi (*unmute).")
            elif command == "*ban":
                await bot.ban_chat_member(message.chat.id, target.id)
                await message.reply(f"{target.full_name} guruhdan chiqarildi (*ban).")
            elif command == "*unban":
                await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
                await message.reply(f"{target.full_name} blokdan chiqarildi (*unban).")
        except (TelegramBadRequest, TelegramForbiddenError) as err:
            await message.reply(f"Amal bajarilmadi: {err}")
        return

    g_test = active_group_tests.get(chat_id)
    if g_test and text.upper() in {"A", "B", "C", "D"}:
        if text.upper() == g_test["correct"]:
            active_group_tests.pop(chat_id, None)
            data["scores"][uid] = data["scores"].get(uid, 0) + 1
            add_xp(message.from_user.id, 15)
            await message.reply(
                f"Togri javob, {message.from_user.full_name}! (+1 ball, +15 XP)\nIzoh: {g_test['explanation']}",
            )
            await send_group_test_question(message, chat_id)
            return

    z_game = active_zakovat.get(chat_id)
    if z_game and not z_game["winner"]:
        norm_msg = normalize(text)
        ans_tokens = [w for w in normalize(z_game["answer"]).split() if len(w) >= 2]
        if ans_tokens and all(tok in norm_msg for tok in ans_tokens):
            z_game["winner"] = True
            active_zakovat.pop(chat_id, None)
            data["zakovat_wins"][uid] = data["zakovat_wins"].get(uid, 0) + 1
            add_xp(message.from_user.id, 25)
            await message.reply(
                f"Tabriklaymiz, {message.from_user.full_name}! Zakovat savolini topdingiz! (+1 galaba, +25 XP)",
            )
            return

    if data["mazgila"].get(chat_id) == message.from_user.id:
        await message.reply(pick_unique_mazgila_reply(chat_id, message.from_user.id))
        return

    if re.search(r"\btavhid\b", normalize(text)):
        caller_name = message.from_user.full_name
        await message.reply(f"Labbay, {caller_name}! Qanday yordam bera olaman?")
        return

    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == bot.id:
            if not gemini_client and not (openai_client and USE_OPENAI_FALLBACK):
                await message.reply("AI hozircha faol emas (GEMINI_API_KEY kiritilmagan).")
                return
            await bot.send_chat_action(message.chat.id, "typing")
            try:
                reply_ctx = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
                prompt = (
                    "Sen Tavhid nomli guruh yordamchisisisan. Foydalanuvchi sening xabaringga javob qilib "
                    "savol berdi. Ozbek tilida aniq, foydali va qisqa javob ber.\n"
                )
                if reply_ctx:
                    prompt += f"Sening avvalgi xabaring: {reply_ctx}\n"
                prompt += f"Savol: {text}\nJavob:"
                answer = await ask_ai(prompt)
                await message.reply(answer)
            except Exception as err:
                print("Tavhid guruh AI xatosi:", repr(err))
                await message.reply(f"AI javob bera olmadi.\nSabab: {err}")


async def main():
    me = await bot.get_me()
    print(f"Tavhid bot ishga tushdi: @{me.username} (ID: {me.id})")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())