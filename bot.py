# -*- coding: utf-8 -*-
import os
import io
import logging

from PIL import Image, ExifTags
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("image-bot")

TOKEN = os.environ.get("TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def get_image_info(image_bytes: bytes) -> str:
    """استخراج المعلومات الفنية للصورة"""
    img = Image.open(io.BytesIO(image_bytes))
    width, height = img.size
    fmt = img.format or "غير معروف"
    mode = img.mode
    size_kb = len(image_bytes) / 1024

    lines = [
        "📷 <b>معلومات الصورة</b>",
        f"📐 الأبعاد: <code>{width} × {height}</code>",
        f"🗂 النوع: <code>{fmt}</code>",
        f"🎨 الألوان: <code>{mode}</code>",
        f"📦 الحجم: <code>{size_kb:.1f} KB</code>",
    ]

    # بيانات EXIF إن وجدت
    try:
        raw_exif = img._getexif()
        if raw_exif:
            interesting = []
            for tag_id, value in raw_exif.items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if name in (
                    "Model",
                    "Make",
                    "DateTime",
                    "DateTimeOriginal",
                    "Software",
                    "LensModel",
                ):
                    interesting.append(f"• {name}: {value}")
            if interesting:
                lines.append("\n📋 <b>بيانات EXIF:</b>")
                lines.extend(interesting[:8])
    except Exception:
        pass

    return "\n".join(lines)


def detect_mime(image_bytes: bytes) -> str:
    """تحديد نوع الصورة"""
    try:
        fmt = (Image.open(io.BytesIO(image_bytes)).format or "").upper()
        mapping = {
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
        }
        return mapping.get(fmt, "image/jpeg")
    except Exception:
        return "image/jpeg"


def describe_with_gemini(image_bytes: bytes) -> str:
    """وصف الصورة باستخدام Gemini"""
    if not GEMINI_API_KEY:
        return (
            "\n\nℹ️ وصف الذكاء الاصطناعي غير مفعّل.\n"
            "أضف المتغير GEMINI_API_KEY لتفعيله."
        )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        mime = detect_mime(image_bytes)

        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                "صف هذه الصورة باختصار بالعربية: ماذا يوجد فيها؟ وما أبرز التفاصيل؟",
            ],
        )

        text = (response.text or "").strip()
        if text:
            return f"\n\n🤖 <b>وصف الذكاء الاصطناعي:</b>\n{text}"
        return "\n\n⚠️ ما تم إنشاء وصف للصورة."
    except Exception as e:
        log.warning("Gemini error: %s", e)
        return f"\n\n⚠️ تعذر وصف الصورة بالذكاء الاصطناعي.\n<code>{e}</code>"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ai_status = "مفعّل ✅" if GEMINI_API_KEY else "غير مفعّل ⚪"
    await update.message.reply_text(
        "👋 أهلاً بك في بوت تحليل الصور\n\n"
        "أرسل أي صورة وسأعرض:\n"
        "• الأبعاد والنوع والحجم\n"
        "• بيانات EXIF إن وجدت\n"
        f"• وصف بالذكاء الاصطناعي ({ai_status})\n\n"
        "الأوامر:\n"
        "/start - بدء\n"
        "/help - مساعدة"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 المساعدة\n\n"
        "1) أرسل صورة مباشرة\n"
        "2) أو أرسل الصورة كملف\n\n"
        "البوت يحللها ويرجع المعلومات الفنية"
        + (" مع وصف AI." if GEMINI_API_KEY else ".")
    )


async def analyze_image(update: Update, image_bytes: bytes):
    msg = await update.message.reply_text("⏳ جاري تحليل الصورة...")
    try:
        info = get_image_info(image_bytes)
        ai_text = describe_with_gemini(image_bytes)
        await msg.edit_text(info + ai_text, parse_mode="HTML")
    except Exception as e:
        log.exception("analyze failed: %s", e)
        await msg.edit_text("❌ حدث خطأ أثناء تحليل الصورة.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]  # أعلى دقة
    file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    await analyze_image(update, image_bytes)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not (doc.mime_type or "").startswith("image/"):
        await update.message.reply_text("أرسل صورة فقط.")
        return

    file = await context.bot.get_file(doc.file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    await analyze_image(update, image_bytes)


def main():
    if not TOKEN:
        raise SystemExit("❌ متغير البيئة TOKEN غير موجود")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))

    log.info("Image bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
