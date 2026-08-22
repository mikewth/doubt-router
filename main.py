"""
THE ENGINE. Run this one process — it's the whole automation.

Flow:
  - Student sends a plain text message to the bot (no buttons, no menu)
      -> spam/blacklist check
      -> Gemini parses subject/topic/priority AND picks the best-fit answerer
      -> new row written to Notion Requests, Status = Pending
      -> student gets an instant "got it, routed to X" acknowledgment
      -> the assigned answerer (if registered) gets a Telegram notification too
  - Student can send /status anytime to check their latest request
  - Every POLL_INTERVAL seconds, a background job checks Notion for
    Status = Approved requests -> sends the real reply via Telegram
    -> Status = Sent -> writes a Run Log row

Deploy this one process (Render/Railway/etc). If it's not running, nothing
in this system moves — new Notion rows stop appearing, approved ones never
get delivered. That's what makes Notion dependent on this repo.
"""
import os
from dotenv import load_dotenv

load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from app import notion_helper as nh
from app import ai_parser

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))

# username -> chat_id, so we know where to deliver replies/notifications later.
# Covers BOTH students and answerers — anyone who has messaged the bot at least once.
_chat_ids: dict[str, int] = {}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    _chat_ids[username] = update.effective_chat.id
    await update.message.reply_text(
        "You're registered! Just send me your question directly — no menu, "
        "no options. I'll figure out who can help.\n\n"
        "Send /status anytime to check your latest request."
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or str(update.effective_user.id)
    page = nh.get_latest_request_for_user(username)

    if not page:
        await update.message.reply_text("You haven't submitted any requests yet — just send me your question!")
        return

    status = nh.get_page_select(page, "Status")
    subject = nh.get_page_text(page, "Subject") or "not yet categorized"
    assigned = nh.get_page_text(page, "Assigned To") or "not yet assigned"

    status_messages = {
        "Processing": "Still being processed — check back in a moment.",
        "Pending": f"Waiting on @{assigned} to review it.",
        "Needs Manual Assignment": "Waiting for a volunteer to pick it up.",
        "Approved": "Approved! Your reply should arrive shortly.",
        "Sent": "Answered — check your messages above!",
        "Rejected": "This one was rejected. Feel free to rephrase and resend.",
        "Spam": "This was flagged as spam/off-topic.",
    }
    friendly = status_messages.get(status, status)

    await update.message.reply_text(f"Subject: {subject}\nStatus: {friendly}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """This is the trigger. A plain message IS the intake — no form, no buttons."""
    username = update.effective_user.username or str(update.effective_user.id)
    chat_id = update.effective_chat.id
    name = update.effective_user.first_name or username
    raw_text = update.message.text

    _chat_ids[username] = chat_id  # keep this fresh in case they didn't /start first

    if nh.is_blacklisted(username):
        await update.message.reply_text("Sorry, I can't process requests from this account.")
        nh.write_run_log("Blacklist check", f"Blocked message from @{username}")
        return

    page_id = nh.create_request(name, username, chat_id, raw_text)

    try:
        answerer_pool = nh.get_answerer_pool()
        parsed = ai_parser.parse_and_route(raw_text, answerer_pool)
    except Exception as e:
        nh.write_run_log("AI parsing", f"FAILED for page {page_id}: {e}")
        await update.message.reply_text("Something went wrong on my end — a human will check this shortly.")
        nh.update_request(page_id, status="Needs Manual Assignment")
        return

    if parsed.get("is_spam_or_offtopic"):
        nh.update_request(page_id, status="Spam")
        nh.write_run_log("Spam filter", f"Flagged message from @{username}")
        await update.message.reply_text("This didn't look like an academic help request — no action taken.")
        return

    assigned = parsed.get("assigned_to")
    status = "Pending" if assigned else "Needs Manual Assignment"

    nh.update_request(
        page_id,
        subject=parsed.get("subject", "General"),
        priority=parsed.get("priority", "Medium"),
        status=status,
        assigned_to=assigned,
    )
    nh.write_run_log(
        "AI parsing + routing",
        f"@{username} -> {parsed.get('subject')} -> assigned {assigned or 'UNASSIGNED'}",
    )

    if assigned:
        await update.message.reply_text(
            f"Got it! Categorized as '{parsed.get('subject')}' and routed to "
            f"@{assigned} for review. You'll hear back here once it's approved. "
            f"(Send /status anytime to check.)"
        )
        await notify_answerer(context, assigned, parsed.get("subject"), parsed.get("topic"), raw_text)
    else:
        await update.message.reply_text(
            "Got it! I couldn't confidently match this to a specific answerer, "
            "so it's waiting for manual assignment. You'll hear back here. "
            "(Send /status anytime to check.)"
        )
        nh.write_run_log("Routing", f"No confident match for page {page_id} — needs manual assignment")


async def notify_answerer(context: ContextTypes.DEFAULT_TYPE, answerer_username: str,
                           subject: str, topic: str, raw_text: str):
    """Pings the assigned answerer on Telegram, if they've registered with the bot."""
    chat_id = _chat_ids.get(answerer_username)
    if not chat_id:
        nh.write_run_log(
            "Answerer notification",
            f"SKIPPED — @{answerer_username} hasn't registered with the bot yet (no /start)",
        )
        return

    preview = raw_text if len(raw_text) <= 200 else raw_text[:200] + "..."
    message = (
        f"New request routed to you!\n\n"
        f"Subject: {subject}\nTopic: {topic}\n\n"
        f"\"{preview}\"\n\n"
        f"Open Notion to review and answer it."
    )
    await context.bot.send_message(chat_id=chat_id, text=message)
    nh.write_run_log("Answerer notification", f"Notified @{answerer_username}")


async def check_approved_requests(context: ContextTypes.DEFAULT_TYPE):
    """Background job — runs every POLL_INTERVAL seconds inside the bot's own
    event loop, no separate process needed."""
    for page in nh.get_approved_requests():
        page_id = page["id"]
        username = nh.get_page_text(page, "Telegram Username")
        subject = nh.get_page_text(page, "Subject")
        chat_id = _chat_ids.get(username)

        if not chat_id:
            nh.write_run_log("Telegram delivery", f"FAILED — no chat_id cached for @{username}")
            continue

        answer = nh.get_answer(page)
        reply_text = answer.strip() if answer.strip() else f"Your request about '{subject}' has been reviewed and approved!"

        await context.bot.send_message(chat_id=chat_id, text=reply_text)
        nh.update_request(page_id, status="Sent")
        nh.write_run_log("Telegram delivery", f"Sent reply to @{username}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(check_approved_requests, interval=POLL_INTERVAL, first=10)

    print("Doubt Router engine running. Students can message the bot directly.")
    app.run_polling()


if __name__ == "__main__":
    main()
