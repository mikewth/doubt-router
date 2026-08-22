# Doubt Router

Students message a Telegram bot directly with their academic question — no
menu, no buttons, just plain text. Gemini reads it, filters spam, categorizes
it, and picks the best-fit answerer from a pool of student volunteers. It
lands in Notion for that answerer to approve. Once approved, the reply is
delivered back on Telegram, and every step is logged.

**Notion's role:** every request, its AI categorization, who it's assigned to,
and its status live in Notion — this is where a human approves things and
where anyone can see what's pending, what's done, and what's stuck. Telegram
is just the conversational front door; the actual record-keeping, approval,
and audit trail all live in Notion, same as they would if the intake were a
form.

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt --break-system-packages
   ```

2. **Notion setup** — create 4 databases in one Notion page, share each with
   your integration (create one at https://www.notion.so/my-integrations):

   **Requests**
   | Property | Type |
   |---|---|
   | Name | Title |
   | Telegram Username | Text |
   | Chat ID | Text |
   | Raw Text | Text |
   | Subject | Text (AI-filled) |
   | Priority | Select (AI-filled) |
   | Assigned To | Text (AI-filled) |
   | Status | Select: Processing / Pending / Approved / Rejected / Needs Manual Assignment / Spam / Sent |
   | Answer | Text (the answerer types this in before approving) |

   **Run Log**
   | Property | Type |
   |---|---|
   | Timestamp | Date |
   | Action | Text |
   | Result | Text |

   **Blacklist**
   | Property | Type |
   |---|---|
   | Username | Title |
   | Reason | Text |
   | Date | Date |

   **Answerer Pool**
   | Property | Type |
   |---|---|
   | Telegram Username | Title |
   | Subjects | Multi-select (e.g. "Linear Algebra", "E&M", "Data Structures") |
   | Year | Select |

   Copy each database ID from its URL (the 32-char string in the link).

3. **Telegram bot** — message @BotFather → `/newbot` → copy the token.

4. **Gemini API key** — get one free at https://aistudio.google.com/app/apikey

5. Copy `.env.example` → `.env`, fill in all real values.

6. **Run it**
   ```bash
   python main.py
   ```
   This single process both listens for Telegram messages (the trigger) and
   checks Notion every `POLL_INTERVAL` seconds for approved requests to
   deliver. Keep it running — deploy to Render/Railway for a free always-on
   host. If this process stops, new messages never get processed and
   approved requests never get delivered — Notion alone can't do either.

## The flow

1. Student sends a message to the bot — no menu, just plain text
2. Blacklist check → Gemini call (spam check + categorize + pick an answerer from the pool) → new Notion row created, Status = Pending (or "Needs Manual Assignment" if AI wasn't confident)
3. Bot immediately acknowledges the student ("routed to @so-and-so")
4. The assigned answerer reviews it in Notion, types their reply into the Answer field, then changes Status to Approved
5. Within `POLL_INTERVAL` seconds, the bot delivers the reply on Telegram, sets Status = Sent, and logs it to Run Log

## My Notion Link
https://app.notion.com/p/Doubt-Router-3b9651c67d4880f0a7e4e5a1b2116aec?source=copy_link

## My Telegram Bot
@doubtdesk_bot
