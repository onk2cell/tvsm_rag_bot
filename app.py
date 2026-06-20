"""FastAPI webhook. Verifies, dedupes, and enqueues — returns 200 fast."""
from fastapi import FastAPI, HTTPException, Request, Response
from google.genai import errors as genai_errors
from redis import Redis
from rq import Queue

import config
import memory
from rag import ask
from tasks import handle_message
from whatsapp import send_text, verify_signature

app = FastAPI()
queue = Queue(connection=Redis.from_url(config.REDIS_URL))


@app.get("/health")
def health():
    return {"status": "ok"}


# Direct RAG test endpoint — bypasses WhatsApp/Redis. Hit it from /docs or the browser:
#   GET /ask?q=What is the range of the King EV MAX?
@app.get("/ask")
def ask_endpoint(q: str):
    try:
        answer, citations = ask(q)
    except genai_errors.ClientError as e:
        if e.code == 429:
            raise HTTPException(
                status_code=429,
                detail="Gemini rate limit / quota exceeded. Wait a bit and retry, "
                       "or switch GEMINI_MODEL / enable billing.",
            )
        raise HTTPException(status_code=e.code or 500, detail=str(e))
    return {"question": q, "answer": answer, "citations": citations}


# Meta calls this once to verify your webhook URL.
@app.get("/webhook")
def verify(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == config.VERIFY_TOKEN:
        return Response(content=p.get("hub.challenge"), media_type="text/plain")
    return Response(status_code=403)


# Incoming messages arrive here.
@app.post("/webhook")
async def incoming(request: Request):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
        return Response(status_code=403)

    data = await request.json()
    try:
        value = data["entry"][0]["changes"][0]["value"]
        for msg in value.get("messages", []):
            sender = msg["from"]
            mid = msg["id"]
            if memory.already_processed(mid):      # skip Meta's duplicate deliveries
                continue
            if msg.get("type") == "text":
                queue.enqueue(handle_message, sender, msg["text"]["body"], mid)
            else:
                send_text(sender, "Please send your question as a text message.")
    except (KeyError, IndexError):
        pass
    return {"status": "ok"}                          # always ack quickly with 200
