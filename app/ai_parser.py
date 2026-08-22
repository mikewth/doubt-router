"""
One Gemini call that parses the request, flags spam, AND picks the best-fit
answerer from your current Answerer Pool.
"""
import os
import json
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-3.6-flash"

PROMPT_TEMPLATE = """You triage academic help requests from university students.

Here is the current pool of student answerers available, as JSON:
{answerer_pool}

Given the raw student request below, return ONLY a JSON object (no markdown,
no commentary) with these fields:

{{
  "subject": "short subject name, e.g. 'Linear Algebra', 'Electricity and Magnetism', 'General'",
  "topic": "short topic within the subject, e.g. 'Gauss's Law'",
  "priority": "Low" | "Medium" | "High",
  "is_spam_or_offtopic": true | false,
  "assigned_to": "the username of the best-fit answerer from the pool above, or null if no confident match, or if is_spam_or_offtopic is true"
}}

Only assign a confident match. If no answerer's tagged subjects clearly fit,
set assigned_to to null rather than guessing.

Student request:
\"\"\"{raw_text}\"\"\"
"""


def parse_and_route(raw_text: str, answerer_pool: list[dict]) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        answerer_pool=json.dumps(answerer_pool),
        raw_text=raw_text,
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )
    return json.loads(response.text)
