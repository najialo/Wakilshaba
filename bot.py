# -*- coding: utf-8 -*-
"""
بوت تلجرام - وكيل الشباب أوفيس
1) يرد تلقائي على استفسارات العملاء بالبحث الذكي في listings.csv
2) يتعرف على التحيات ويرد بالترحيب
3) يجمع بيانات العميل (اسم + رقم) ويخزنها في leads.csv ويرسلها للمالك فورًا
"""

import csv
import os
import re
import logging
from datetime import datetime
from difflib import SequenceMatcher
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ============ الإعدادات ============
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("لازم تحط BOT_TOKEN كـ Environment Variable قبل ما تشغل البوت")

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # آيدي حسابك بتلجرام لاستقبال طلبات الزباين

LISTINGS_FILE = "listings.csv"
LEADS_FILE = "leads.csv"
FIELDNAMES = ["نوع", "المنطقة", "المساحة", "السعر", "تفاصيل"]

logging.basicConfig(level=logging.INFO)

ASK_NAME, ASK_PHONE = range(2)


def ensure_files():
    if not os.path.exists(LISTINGS_FILE):
        with open(LISTINGS_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(FIELDNAMES)
    if not os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["الاسم", "الرقم", "طلب العميل", "التاريخ"])


def normalize_text(text: str) -> str:
    """توحيد الحروف المتشابهة عشان البحث يشتغل حتى لو اختلفت الكتابة"""
    text = text.strip()
    text = text.replace("ة", "ه")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    return text


# ============ قوائم الكلمات ============

_RAW_SYNONYMS = {
    "شقق": "شقة", "شقه": "شقة", "الشقق": "شقة", "الشقه": "شقة",
    "اراضي": "أرض", "أراضي": "أرض", "الاراضي": "أرض", "ارض": "أرض",
    "الارض": "أرض", "قطعة": "أرض", "قطع": "أرض", "محضر": "أرض",
    "منازل": "منزل", "بيوت": "منزل", "بيت": "منزل", "البيت": "منزل",
    "البيوت": "منزل", "دار": "منزل",
    "مزارع": "مزرعة",
}
SYNONYMS = {normalize_text(k): normalize_text(v) for k, v in _RAW_SYNONYMS.items()}

_RAW_STOPWORDS = {
    "موجود", "موجوده", "موجودة", "متوفر", "متوفره", "متوفرة",
    "شوفي", "شوف", "شوفلي", "ورجيني", "بدي", "بدك", "بدنا",
    "عندك", "عندكم", "في", "فيه", "فيك", "هل", "وش", "شو",
    "ممكن", "لو", "سمحت", "من", "فضلك", "اريد", "أريد",
    "ابحث", "أبحث", "دور", "دوري", "عن", "على", "لدي",
    "لديك", "لديكم", "يوجد", "عندي", "الرجاء", "بحاجة", "محتاج",
}
STOPWORDS = {normalize_text(w) for w in _RAW_STOPWORDS}

_RAW_CHEAP = {"رخيص", "رخيصه", "رخيصة", "بسيط", "اقتصادي", "قليل", "منخفض"}
_RAW_EXPENSIVE = {"غالي", "فاخر", "فخم", "مميز", "راقي", "عالي"}
_RAW_BIG = {"كبير", "كبيره", "كبيرة", "واسع", "واسعه", "واسعة"}
_RAW_SMALL = {"صغير", "صغيره", "صغيرة", "مضغوط"}

CHEAP_WORDS = {normalize_text(w) for w in _RAW_CHEAP}
EXPENSIVE_WORDS = {normalize_text(w) for w in _RAW_EXPENSIVE}
BIG_WORDS = {normalize_text(w) for w in _RAW_BIG}
SMALL_WORDS = {normalize_text(w) for w in _RAW_SMALL}
INTENT_WORDS = CHEAP_WORDS | EXPENSIVE_WORDS | BIG_WORDS | SMALL_WORDS

# كلمات/عبارات التحية - أي رسالة تتكون من هاي الكلمات بس بترد بالترحيب
_RAW_GREETINGS = {
    "السلام عليكم", "سلام عليكم", "عليكم السلام", "سلام",
    "مرحبا", "مرحبا", "مرحبتين", "هلا", "هلا فيك", "هلا وغلا",
    "كيفك", "كيفكم", "كيف الحال", "شلونك", "شخبارك",
    "صباح الخير", "مساء الخير", "صباح النور", "مساء النور",
    "هاي", "هلو", "hi", "hello",
    "أهلا", "اهلا", "اهلين", "أهلين",
}
GREETINGS = {normalize_text(g) for g in _RAW_GREETINGS}


def is_greeting(query: str) -> bool:
    """يتحقق إذا الرسالة كلها أو معظمها تحية (مو بحث عن عقار)"""
    normalized = normalize_text(query)
    if normalized in GREETINGS:
        return True
    words = [w for w in normalized.split() if w]
    if not words:
        return False
    # لو كل كلمات الرسالة تحيات (زي "مرحبا كيفك")
    if all(w in GREETINGS or w in {normalize_text("و"), normalize_text("و ")} for w in words):
        return True
    return False


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def extract_number(text: str):
    """يطلع أول رقم موجود بالنص (للمساحة أو السعر)"""
    if not text:
        return None
    cleaned = text.replace("$", "").replace("م²", "").replace("متر", "")
    match = re.search(r"[\d,.]+", cleaned)
    if match:
        try:
            return float(match.group().replace(",", ""))
        except ValueError:
            return None
    return None


def search_listings(query: str):
    """
    بحث ذكي:
    - يوحّد المرادفات والجموع (شقق/شقة، بيوت/منزل...)
    - يفهم كلمات قريبة بالتشابه التقريبي (يتحمل أخطاء إملائية)
    - يفهم نية الزبون (رخيص/غالي/كبير/صغير) ويرتب النتائج على أساسها
    """
    normalized_query = normalize_text(query)
    all_words = [w for w in normalized_query.split() if w]

    wants_cheap = any(w in CHEAP_WORDS for w in all_words)
    wants_expensive = any(w in EXPENSIVE_WORDS for w in all_words)
    wants_big = any(w in BIG_WORDS for w in all_words)
    wants_small = any(w in SMALL_WORDS for w in all_words)

    search_words = [
        SYNONYMS.get(w, w)
        for w in all_words
        if w not in STOPWORDS and w not in INTENT_WORDS
    ]

    scored_results = []

    with open(LISTINGS_FILE, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            haystack_parts = [str(row.get(k, "")) for k in FIELDNAMES if row.get(k)]
            haystack_text = normalize_text(" ".join(haystack_parts))
            haystack_words = haystack_text.split()

            total_score = 0.0
            matched_words = 0

            for sw in search_words:
                if sw in haystack_text:
                    total_score += 1.0
                    matched_words += 1
                    continue
                best = max((similarity(sw, hw) for hw in haystack_words), default=0)
                if best >= 0.7:
                    total_score += best
                    matched_words += 1

            if search_words:
                required = max(1, len(search_words) - 1) if len(search_words) > 1 else 1
                if matched_words < required:
                    continue

            price = extract_number(row.get("السعر", ""))
            area = extract_number(row.get("المساحة", ""))

            scored_results.append({
                "row": row,
                "score": total_score,
                "price": price,
                "area": area,
            })

    if not scored_results:
        return []

    if wants_cheap and any(r["price"] is not None for r in scored_results):
        scored_results.sort(key=lambda r: (r["price"] if r["price"] is not None else float("inf")))
    elif wants_expensive and any(r["price"] is not None for r in scored_results):
        scored_results.sort(key=lambda r: (r["price"] if r["price"] is not None else -1), reverse=True)
    elif wants_big and any(r["area"] is not None for r in scored_results):
        scored_results.sort(key=lambda r: (r["area"] if r["area"] is not None else -1), reverse=True)
    elif wants_small and any(r["area"] is not None for r in scored_results):
        scored_results.sort(key=lambda r: (r["area"] if r["area"] is not None else float("inf")))
    else:
        scored_results.sort(key=lambda r: r["score"], reverse=True)

    return [r["row"] for r in scored_results]


def format_listing(row: dict) -> str:
    نوع = row.get("نوع", "")
    منطقة = row.get("المنطقة", "")
    مساحة = row.get("المساحة", "")
    سعر = row.get("السعر", "")
    تفاصيل = row.get("تفاصيل", "")

    emoji = "🏗️" if "أرض" in نوع else "🏠"

    return (
        f"{emoji} <b>{نوع} – {منطقة}</b>\n\n"
        f"📐 <b>المساحة:</b> {مساحة}\n"
        f"💰 <b>السعر:</b> {سعر}\n\n"
        f"📝 <b>التفاصيل:</b>\n{تفاصيل}\n\n"
        f"📞 للتواصل والمعاينة: راسلنا وبنرد عليك فورًا"
    )


WELCOME_MESSAGE = (
    "🏢 <b>أهلاً وسهلاً فيك في مكتب الشهباء العقاري</b> 🏢\n\n"
    "وكيلك الذكي لأفضل فرص العقارات والأراضي بحلب وريفها 🌆\n\n"
    "🔍 اكتبلي وش تدور عليه وبرد عليك فورًا بالعروض المتوفرة\n"
    "<i>مثلاً: أرض كفر حمرة، شقة رخيصة، بيت واسع بحريتان...</i>\n\n"
    "📋 أو اكتب /leave_info لتسجيل بياناتك وطلبك، وفريقنا بيتواصل معك بأسرع وقت\n\n"
    "✨ <b>ثقتك وسرعة خدمتك أولويتنا</b> ✨"
)


# ============ أوامر البوت ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode="HTML")


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text

    # لو الرسالة تحية، رد بالترحيب بدل البحث
    if is_greeting(query):
        await update.message.reply_text(WELCOME_MESSAGE, parse_mode="HTML")
        return

    results = search_listings(query)

    if not results:
        await update.message.reply_text(
            "😕 ما لقيت عروض مطابقة حاليًا\n"
            "تحب نسجل طلبك ونرجعلك أول ما يتوفر شي مناسب؟ اكتب /leave_info"
        )
        return

    await update.message.reply_text(f"✅ لقيت هاي العروض المطابقة ({len(results)}):")
    for row in results[:10]:
        await update.message.reply_text(format_listing(row), parse_mode="HTML")

    await update.message.reply_text(
        "لو حاب تفاصيل أكتر أو تسجل بياناتك، اكتب /leave_info"
    )


# ============ محادثة جمع بيانات العميل ============

async def leave_info_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["original_query"] = update.message.text if update.message.text != "/leave_info" else ""
    await update.message.reply_text("تمام 🙏 شو اسمك الكريم؟")
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("📱 وشو رقم تلفونك (منشان نتواصل معك)؟")
    return ASK_PHONE


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name", "")
    phone = update.message.text.strip()
    request_text = context.user_data.get("original_query", "") or "غير محدد"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(LEADS_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([name, phone, request_text, now])

    if ADMIN_CHAT_ID:
        admin_msg = (
            "🔔 <b>طلب جديد من زبون</b>\n\n"
            f"👤 <b>الاسم:</b> {name}\n"
            f"📱 <b>الرقم:</b> {phone}\n"
            f"📝 <b>الطلب:</b> {request_text}\n"
            f"🕒 <b>الوقت:</b> {now}"
        )
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="HTML")

    await update.message.reply_text(
        "✅ تم تسجيل بياناتك بنجاح، وفريقنا رح يتواصل معك بأسرع وقت ممكن 🙏"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END


# ============ التشغيل ============

def main():
    ensure_files()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("leave_info", leave_info_start),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))

    app.run_polling()


if __name__ == "__main__":
    main()
