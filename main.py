import os
import time
import logging
import requests
from io import BytesIO
from PIL import Image
from pypdf import PdfReader
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
import google.generativeai as genai

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID") # Admin Telegram User ID (Optional)

# Gemini Setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# In-Memory Databases
bill_data = {}
user_usage = {}   # Rate Limiting: {user_id: [timestamps]}
global_stats = {"total_requests": 0, "users": set()}

# --- HELPER FUNCTIONS ---

def check_rate_limit(user_id: int) -> bool:
    """1 မိနစ်လျှင် 5 ကြိမ်ထက် ပိုမေးပါက True (Limit) ပြန်မည်"""
    now = time.time()
    if user_id not in user_usage:
        user_usage[user_id] = []
    
    # 60 စက္ကန့်ထက် ကြာသော Timestamp များကို ဖယ်ထုတ်မည်
    user_usage[user_id] = [t for t in user_usage[user_id] if now - t < 60]
    
    if len(user_usage[user_id]) >= 5:
        return True
    
    user_usage[user_id].append(now)
    return False

def track_stats(user_id: int):
    """Admin Stats အတွက် သုံးစွဲမှု မှတ်တမ်းတင်မည်"""
    global_stats["total_requests"] += 1
    global_stats["users"].add(user_id)

def get_main_menu_keyboard():
    """UI Buttons Layout"""
    keyboard = [
        [
            InlineKeyboardButton("🤖 AI Chat", callback_data="help_chat"),
            InlineKeyboardButton("🎨 Image Gen", callback_data="help_gen")
        ],
        [
            InlineKeyboardButton("🎵 Song Lyrics", callback_data="help_lyrics"),
            InlineKeyboardButton("🎬 YouTube Summary", callback_data="help_yt")
        ],
        [
            InlineKeyboardButton("📄 PDF Reader", callback_data="help_pdf"),
            InlineKeyboardButton("🌐 Web Search", callback_data="help_search")
        ],
        [
            InlineKeyboardButton("💰 Bill Splitter", callback_data="help_bill"),
            InlineKeyboardButton("ℹ️ All Commands", callback_data="help_all")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- COMMAND HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_stats(update.effective_user.id)
    welcome_text = (
        "🤖 **Welcome to All-in-One Power AI Bot!**\n\n"
        "လိုရာ Feature များကို အောက်ပါ Button ခလုတ်များ နှိပ်၍ လေ့လာနိုင်ပါသည်။\n"
        "မေးချင်သော စာများကို မည်သည့် ဘာသာစကား (မြန်မာ၊ အင်္ဂလိပ်၊ တရုတ်) ဖြင့်မဆို တိုက်ရိုက် မေးမြန်းနိုင်ပါသည်။"
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode='Markdown')

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    text = ""
    
    if data == "help_chat":
        text = "💬 **AI Chat & Multilingual Support:**\nစာ သို့မဟုတ် အသံဖိုင် ပို့ပေးပါ။ မေးသည့် ဘာသာစကားအတိုင်း ပြန်လည်ဖြေကြားပေးပါမည်။"
    elif data == "help_gen":
        text = "🎨 **AI Image Generation:**\n`/generate <ပုံဖော်ပြချက်>` ဟု ရိုက်ပေးပါ။\nဥပမာ - `/generate a cute cat astronaut`"
    elif data == "help_lyrics":
        text = "🎵 **Song Lyrics Finder:**\n`/lyrics <သီချင်းအမည် သို့မဟုတ် စာသား>` ဟု ရိုက်ပေးပါ။\nဥပမာ - `/lyrics Perfect Ed Sheeran`"
    elif data == "help_yt":
        text = "🎬 **YouTube Video Summarizer:**\n`/yt <YouTube Link>` ဟု ရိုက်ပေးပါက ဗီဒီယိုအနှစ်ချုပ်ပေးပါမည်။"
    elif data == "help_pdf":
        text = "📄 **PDF Document Reader:**\nPDF ဖိုင်တစ်ခုခုကို Telegram သို့ ပို့လိုက်ပါက AI မှ ဖတ်ပြီး အနှစ်ချုပ်ပေးပါမည်။"
    elif data == "help_search":
        text = "🌐 **Google Web Search:**\n`/search <ရှာချင်သည့်အရာ>` ဟု ရိုက်ပေးပါ။"
    elif data == "help_bill":
        text = "💰 **Group Bill Splitter:**\n• `/addbill <အမည်> <ပမာဏ>`\n• `/showbill` - စာရင်းကြည့်ရန်\n• `/clearbill` - စာရင်းဖျက်ရန်"
    elif data == "help_all":
        text = (
            "📌 **Commands အားလုံး စာရင်း:**\n"
            "• `/generate <prompt>` - AI ပုံဆွဲရန်\n"
            "• `/lyrics <song>` - သီချင်းစာသား ရှာရန်\n"
            "• `/yt <url>` - YouTube ဗီဒီယို အနှစ်ချုပ်ရန်\n"
            "• `/search <topic>` - Google Search ရှာရန်\n"
            "• `/addbill <name> <amount>` - စရိတ်မှတ်ရန်\n"
            "• `/showbill` | `/clearbill` - စရိတ်ရှင်းရန်"
        )
        
    await query.message.reply_text(text, parse_mode='Markdown')

# --- NEW FEATURES (LYRICS & YOUTUBE) ---

async def handle_lyrics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id):
        await update.message.reply_text("⏱️ Rate limit exceeded. ၁ မိနစ်လျှင် ၅ ကြိမ်သာ မေးနိုင်ပါသည်။")
        return
    track_stats(user_id)

    if not context.args:
        await update.message.reply_text("❌ Usage: `/lyrics <သီချင်းအမည်>` (ဥပမာ - `/lyrics Perfect Ed Sheeran`)", parse_mode='Markdown')
        return

    song_query = ' '.join(context.args)
    status_msg = await update.message.reply_text(f"⏳ '{song_query}' ၏ စာသားကို ရှာဖွေနေပါပြီ...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    prompt = f"Please search for and provide the full song lyrics for '{song_query}'. Include song title and artist name. Respond clearly."
    try:
        response = model.generate_content(prompt)
        await update.message.reply_text(f"🎵 **Song Lyrics for '{song_query}':**\n\n{response.text}", parse_mode='Markdown')
    except Exception:
        await update.message.reply_text("⚠️ သီချင်းစာသား ရှာဖွေ၍ မရပါ။")
    finally:
        await status_msg.delete()

async def handle_yt_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id):
        await update.message.reply_text("⏱️ Rate limit exceeded.")
        return
    track_stats(user_id)

    if not context.args:
        await update.message.reply_text("❌ Usage: `/yt <YouTube URL>`", parse_mode='Markdown')
        return

    url = context.args[0]
    status_msg = await update.message.reply_text("⏳ YouTube ဗီဒီယိုကို ဖတ်ရှု အနှစ်ချုပ်နေပါပြီ...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Extract Video ID
        video_id = ""
        if "v=" in url:
            video_id = url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
            
        if not video_id:
            await update.message.reply_text("❌ မှန်ကန်သော YouTube URL ဖြစ်ရပါမည်။")
            await status_msg.delete()
            return

        # Fetch Transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([item['text'] for item in transcript_list[:100]]) # Limit text
        
        prompt = f"Summarize the main points of this YouTube video transcript in the same language as the transcript or Burmese:\n\n{full_text}"
        response = model.generate_content(prompt)
        await update.message.reply_text(f"🎬 **YouTube Video Summary:**\n\n{response.text}", parse_mode='Markdown')
    except Exception:
        await update.message.reply_text("⚠️ ဤဗီဒီယိုတွင် Subtitle/Transcript မပါဝင်သောကြောင့် အနှစ်ချုပ်၍ မရပါ။")
    finally:
        await status_msg.delete()

# --- AI CORE HANDLERS ---

async def handle_text_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id):
        await update.message.reply_text("⏱️ Rate limit exceeded.")
        return
    track_stats(user_id)

    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    prompt = f"Detect language of prompt and respond in the EXACT SAME language naturally:\n\nUser: {user_text}"
    try:
        response = model.generate_content(prompt)
        await update.message.reply_text(response.text)
    except Exception:
        await update.message.reply_text("⚠️ AI Processing Error.")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id): return
    track_stats(user_id)

    document = update.message.document
    if document.mime_type == "application/pdf":
        status_msg = await update.message.reply_text("⏳ PDF ဖိုင်ကို ဖတ်နေပါပြီ...")
        try:
            pdf_file = await document.get_file()
            pdf_bytes = await pdf_file.download_as_bytearray()
            
            reader = PdfReader(BytesIO(pdf_bytes))
            text = ""
            for page in reader.pages[:10]: # First 10 pages limit
                text += page.extract_text() or ""
                
            prompt = f"Summarize key points from this document in Burmese and English:\n\n{text[:4000]}"
            response = model.generate_content(prompt)
            await update.message.reply_text(f"📄 **PDF Summary:**\n\n{response.text}", parse_mode='Markdown')
        except Exception:
            await update.message.reply_text("⚠️ PDF ဖတ်ရှုရာတွင် အမှားတစ်ခု ရှိနေပါသည်။")
        finally:
            await status_msg.delete()

async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id): return
    track_stats(user_id)

    if not context.args:
        await update.message.reply_text("❌ Usage: `/generate <description>`", parse_mode='Markdown')
        return

    prompt = ' '.join(context.args)
    status_msg = await update.message.reply_text("⏳ Generating image...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")

    try:
        image_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}"
        response = requests.get(image_url)
        if response.status_code == 200:
            await update.message.reply_photo(photo=BytesIO(response.content), caption=f"🎨 **Prompt:** _{prompt}_", parse_mode='Markdown')
        else:
            await update.message.reply_text("⚠️ Image Generation Failed.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")
    finally:
        await status_msg.delete()

# --- ADMIN STATS HANDLER ---

async def handle_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ADMIN_ID and user_id != str(ADMIN_ID):
        await update.message.reply_text("🚫 Admin သီးသန့် Command ဖြစ်ပါသည်။")
        return
        
    unique_users = len(global_stats["users"])
    total_reqs = global_stats["total_requests"]
    
    stats_msg = (
        "📊 **Bot System Analytics (Admin Only):**\n\n"
        f"👥 **Total Unique Users:** {unique_users}\n"
        f"💬 **Total Requests Processed:** {total_reqs}"
    )
    await update.message.reply_text(stats_msg, parse_mode='Markdown')

# --- OTHER HANDLERS (Search, Image Vision, Voice, Bill) ---

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id): return
    track_stats(user_id)

    if not context.args: return
    query = ' '.join(context.args)
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        snippets = [g.get_text() for g in soup.find_all('div', class_='BNeawe s3v9rd AP7Wnd')][:3]
        
        prompt = f"Summarize search results for '{query}' in same language:\n\n" + "\n".join(snippets)
        response = model.generate_content(prompt)
        await update.message.reply_text(f"🌐 **Search Summary:**\n\n{response.text}", parse_mode='Markdown')
    except Exception:
        await update.message.reply_text("⚠️ Search Error.")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id): return
    track_stats(user_id)

    caption = update.message.caption or "Analyze this image."
    try:
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        image = Image.open(BytesIO(image_bytes))
        response = model.generate_content([f"Analyze and respond in same language as caption: {caption}", image])
        await update.message.reply_text(response.text)
    except Exception:
        await update.message.reply_text("⚠️ Image Error.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_rate_limit(user_id): return
    track_stats(user_id)

    try:
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()
        audio_data = {"mime_type": "audio/ogg", "data": bytes(voice_bytes)}
        response = model.generate_content(["Summarize this audio in spoken language:", audio_data])
        await update.message.reply_text(f"🎙️ **Audio Summary:**\n\n{response.text}", parse_mode='Markdown')
    except Exception:
        await update.message.reply_text("⚠️ Voice Error.")

async def add_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        name, amount = context.args[0], float(context.args[1])
        if chat_id not in bill_data: bill_data[chat_id] = {}
        bill_data[chat_id][name] = bill_data[chat_id].get(name, 0) + amount
        await update.message.reply_text(f"✅ Added **{name}**: **{amount:,.0f}**", parse_mode='Markdown')
    except Exception: await update.message.reply_text("❌ Format: `/addbill Name 5000`", parse_mode='Markdown')

async def show_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in bill_data or not bill_data[chat_id]:
        await update.message.reply_text("ℹ️ No records found.")
        return
    records = bill_data[chat_id]
    total, people = sum(records.values()), len(records)
    per = total / people if people > 0 else 0
    resp = "📊 **Expense Summary:**\n\n" + "\n".join([f"• **{n}**: {a:,.0f}" for n, a in records.items()])
    resp += f"\n\n💵 **Total:** {total:,.0f}\n⚖️ **Per Person:** {per:,.0f}"
    await update.message.reply_text(resp, parse_mode='Markdown')

async def clear_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bill_data[update.effective_chat.id] = {}
    await update.message.reply_text("🗑️ Cleared all bills.")

# --- MAIN APP STARTUP ---
def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("CRITICAL ERROR: Keys missing.")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commands & Callbacks
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("generate", generate_image))
    app.add_handler(CommandHandler("lyrics", handle_lyrics))
    app.add_handler(CommandHandler("yt", handle_yt_summary))
    app.add_handler(CommandHandler("search", handle_search))
    app.add_handler(CommandHandler("addbill", add_bill))
    app.add_handler(CommandHandler("showbill", show_bill))
    app.add_handler(CommandHandler("clearbill", clear_bill))
    app.add_handler(CommandHandler("stats", handle_admin_stats))
    app.add_handler(CallbackQueryHandler(button_click))

    # Media & Document Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_chat))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 All-in-One Bot 100% Ready...")
    app.run_polling()

if __name__ == '__main__':
    main()