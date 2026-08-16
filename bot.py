# -*- coding: utf-8 -*-
"""
بوت تلجرام - وكيل الشباب أوفيس
1) يرد تلقائي على استفسارات العملاء بالبحث في listings.csv
2) يجمع بيانات العميل (اسم + رقم + طلبه) ويخزنها في leads.csv
"""

import csv
import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardRemove
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
            writer.writerow(["أرض", "حلب - الراموسة", "500م", "25000$", "أرض سكنية صك أخضر"])
    if not os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["الاسم", "الرقم", "طلب العميل", "التاريخ"])


def normalize_text(text: str) -> str:
    """توحيد الحروف المتشابهة عشان البحث يشتغل حتى لو اختلفت الكتابة"""
    text = text.replace("ة", "ه")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    return text


def search_listings(query: str):
    """
    يبحث بكل كلمة من كلمات الاستعلام لحالها (مو الجملة كاملة كوحدة وحدة).
    مثال: "شقة الفرقان" بيلاقي أي عرض فيه كلمة "شقة" وكلمة "الفرقان" مع بعض،
    حتى لو ما كانوا جنب بعض بالنص.
    """
    results = []
    query = normalize_text(query.strip())
    if not query:
        return results

    search_words = [w for w in query.split() if w]
    if not search_words:
        return results

    with open(LISTINGS_FILE, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                values = []
                for key in FIELDNAMES:
                    v = row.get(key)
                    if v is None:
                        continue
                    if isinstance(v, list):
                        values.extend(str(x) for x in v if x)
                    else:
                        values.append(str(v))
                combined = normalize_text(" ".join(values))
                if all(word in combined for word in search_words):
                    clean_row = {k: (row.get(k) if isinstance(row.get(k), str) else "") for k in FIELDNAMES}
                    results.append(clean_row)
            except Exception as e:
                logging.warning(f"سطر فيه مشكلة بملف listings.csv، تم تجاهله: {e}")
                continue
    return results


def format_listing(row: dict, idx: int) -> str:
    return (
        f"{idx}️⃣ {row.get('نوع', '')} - {row.get('المنطقة', '')}\n"
        f"   المساحة: {row.get('المساحة', '')} | السعر: {row.get('السعر', '')}\n"
        f"   {row.get('تفاصيل', '')}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً فيك 👋\n"
        "اكتبلي وش تدور عليه (مثلاً: أرض حلب، شقة الفرقان...) وبرد عليك بالعروض المتوفرة.\n"
        "أو اكتب /leave_info لو حاب نسجل بياناتك وبنرجعلك بأسرع وقت."
    )


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    context.user_data["last_query"] = query
    try:
        results = search_listings(query)
    except Exception as e:
        logging.error(f"خطأ أثناء البحث: {e}")
        await update.message.reply_text(
            "صار خطأ تقني بسيط أثناء البحث 🙁 جرب تكتب كلمة أبسط، أو اكتب /leave_info لنسجل طلبك."
        )
        return

    if not results:
        await update.message.reply_text(
            "ما لقيت عروض مطابقة حاليًا 🙁\n"
            "تحب نسجل طلبك ونرجعلك أول ما يتوفر شي مناسب؟ اكتب /leave_info"
        )
        return

    reply_lines = ["لقيت هاي العروض المطابقة:\n"]
    for i, row in enumerate(results[:5], start=1):
        reply_lines.append(format_listing(row, i))
    reply_lines.append("\nلو حاب تفاصيل أكتر أو تسجل بياناتك، اكتب /leave_info")
    await update.message.reply_text("\n\n".join(reply_lines))


async def leave_info_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تمام، وش اسمك الكريم؟")
    return ASK_NAME


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("ممتاز، رقم تلفونك لنقدر نتواصل معك؟")
    return ASK_PHONE


async def save_lead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    name = context.user_data.get("name", "")
    last_query = context.user_data.get("last_query", "غير محدد")

    with open(LEADS_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([name, phone, last_query, datetime.now().strftime("%Y-%m-%d %H:%M")])

    await update.message.reply_text(
        f"يعطيك العافية {name} 🙏 سجلنا بياناتك وبنتواصل معك قريبًا.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main():
    ensure_files()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("leave_info", leave_info_start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_lead)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))

    print("البوت شغال...")
    app.run_polling()


if __name__ == "__main__":
    main()
