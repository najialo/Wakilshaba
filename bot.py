# -*- coding: utf-8 -*-
"""
بوت تلجرام - وكيل الشباب أوفيس
1) يرد تلقائي على استفسارات العملاء بالبحث في listings.csv
2) يجمع بيانات العميل (اسم + رقم) ويخزنها في leads.csv ويرسلها للمالك فورا
"""

import csv
import os
import logging
from datetime import datetime
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


# كلمات مرادفة/جموع - المفاتيح والقيم لازم تكون بصيغتها الطبيعية (رح تتطبع عليها normalize_text تلقائيًا تحت)
_RAW_SYNONYMS = {
    "شقق": "شقة", "شقه": "شقة", "الشقق": "شقة", "الشقه": "شقة",
    "اراضي": "أرض", "أراضي": "أرض", "الاراضي": "أرض", "ارض": "أرض",
    "الارض": "أرض", "قطعة": "أرض", "قطع": "أرض", "محضر": "أرض",
    "منازل": "منزل", "بيوت": "منزل", "بيت": "منزل", "البيت": "منزل",
    "البيوت": "منزل", "دار": "منزل",
    "مزارع": "مزرعة",
}
# نبني نسخة مطبّعة (normalized) من القاموس عشان تطابق شكل الكلام بعد normalize_text
SYNONYMS = {normalize_text(k): normalize_text(v) for k, v in _RAW_SYNONYMS.items()}

_RAW_STOPWORDS = {
    "موجود", "موجوده", "موجودة", "متوفر", "متوفره", "متوفرة",
    "شوفي", "شوف", "شوفلي", "ورجيني", "بدي", "بدك", "بدنا",
    "عندك", "عندكم", "في", "فيه", "فيك", "هل", "وش", "شو",
    "ممكن", "لو", "سمحت", "من", "فضلك", "اريد", "أريد",
    "ابحث", "أبحث", "دور", "دوري", "عن", "على", "لدي",
    "لديك", "لديكم", "يوجد", "عندي",
}
STOPWORDS = {normalize_text(w) for w in _RAW_STOPWORDS}


def preprocess_query(query: str):
    """يرجع لستة كلمات بحث نظيفة بعد التطبيع وحذف الحشو وتوحيد المرادفات"""
    normalized = normalize_text(query)
    words = [w for w in normalized.split() if w]
    cleaned = []
    for w in words:
        if w in STOPWORDS:
            continue
        cleaned.append(SYNONYMS.get(w, w))
    return cleaned


def search_listings(query: str):
    """
    كل كلمة من كلمات الاستعلام لحالها (مو الجملة كاملة كوحدة وحدة)
    بيلاقي أي عرض فيه كل الكلمات المطلوبة مع بعض، حتى لو ما كانوا جنب بعضن.
    """
    results = []
    search_words = preprocess_query(query)
    if not search_words:
        return results

    with open(LISTINGS_FILE, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            haystack_parts = []
            for key in FIELDNAMES:
                v = row.get(key)
                if v:
                    haystack_parts.append(str(v))
            haystack = normalize_text(" ".join(haystack_parts))

            if all(w in haystack for w in search_words):
                results.append(row)

    return results


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


# ============ أوامر البوت ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🏢 <b>أهلاً وسهلاً فيك في مكتب الشهباء العقاري</b> 🏢\n\n"
        "وكيلك الذكي لأفضل فرص العقارات والأراضي بحلب وريفها 🌆\n\n"
        "🔍 اكتبلي وش تدور عليه وبرد عليك فورًا بالعروض المتوفرة\n"
        "<i>مثلاً: أرض كفر حمرة، شقة الفرقان، بيت حريتان...</i>\n\n"
        "📋 أو اكتب /leave_info لتسجيل بياناتك وطلبك، وفريقنا بيتواصل معك بأسرع وقت\n\n"
        "✨ <b>ثقتك وسرعة خدمتك أولويتنا</b> ✨"
    )
    await update.message.reply_text(welcome, parse_mode="HTML")


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    results = search_listings(query)

    if not results:
        await update.message.reply_text(
            "😕 ما لقيت عروض مطابقة حاليًا\n"
            "تحب نسجل طلبك ونرجعلك أول ما يتوفر شي مناسب؟ اكتب /leave_info"
        )
        return

    await update.message.reply_text(f"✅ لقيت هاي العروض المطابقة ({len(results)}):")
    for row in results:
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

    # حفظ بالملف
    with open(LEADS_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([name, phone, request_text, now])

    # إرسال إشعار فوري ومنفصل للمالك بكل بيانات العميل
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
