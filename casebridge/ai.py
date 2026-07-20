"""AI service for CaseBridge — document intelligence, sentiment, narrative.

Uses OpenAI when OPENAI_API_KEY is set; otherwise falls back to deterministic
heuristics so local dev, tests, and demos work with no key and no cost. Every
function returns the same shape in both modes, and marks whether AI ran.
"""

import hashlib
import json
import math
import os
import re

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = 256  # fallback vector width

DOC_TYPES = ["medical_record", "medical_bill", "police_report", "demand_letter",
             "insurance_corr", "other"]

_client = None
_checked = False


def _openai():
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI

        _client = OpenAI(api_key=key)
    except Exception:  # noqa: BLE001
        _client = None
    return _client


def is_enabled() -> bool:
    return _openai() is not None


def _chat_json(system, user, max_tokens=700):
    client = _openai()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=max_tokens,
    )
    return json.loads(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# Document classification
# ---------------------------------------------------------------------------

_KEYWORDS = {
    "police_report": ["crash report", "officer", "citation", "collision", "traffic"],
    "medical_bill": ["billing", "amount due", "charges", "invoice", "statement of account"],
    "medical_record": ["diagnosis", "treatment", "patient", "mri", "physician", "orthopedic"],
    "demand_letter": ["demand", "settlement", "policy limits", "hereby demand"],
    "insurance_corr": ["claim number", "adjuster", "insured", "liability", "coverage"],
}


def classify_document(text: str) -> dict:
    if is_enabled():
        try:
            data = _chat_json(
                "You classify legal/medical documents for a personal-injury law firm. "
                f"Return JSON {{\"doc_type\": one of {DOC_TYPES}, \"confidence\": 0..1}}.",
                text[:6000],
            )
            dt = data.get("doc_type")
            if dt in DOC_TYPES:
                return {"doc_type": dt, "confidence": float(data.get("confidence", 0.8)), "ai": True}
        except Exception:  # noqa: BLE001
            pass
    # Heuristic fallback
    low = (text or "").lower()
    best, score = "other", 0
    for dt, kws in _KEYWORDS.items():
        hits = sum(1 for k in kws if k in low)
        if hits > score:
            best, score = dt, hits
    return {"doc_type": best, "confidence": min(0.6 + 0.1 * score, 0.95) if score else 0.5, "ai": False}


def summarize_document(text: str, doc_type: str) -> dict:
    if is_enabled():
        try:
            data = _chat_json(
                "Summarize this personal-injury case document in 2-3 sentences for a case "
                "manager. Focus on what matters to the case. Return JSON {\"summary\": string}.",
                f"Document type: {doc_type}\n\n{text[:8000]}",
            )
            if data.get("summary"):
                return {"summary": data["summary"], "ai": True}
        except Exception:  # noqa: BLE001
            pass
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return {"summary": " ".join(sentences[:2])[:400] or "No text extracted.", "ai": False}


def extract_facts(text: str, doc_type: str) -> dict:
    if is_enabled():
        try:
            data = _chat_json(
                "Extract key facts from this personal-injury document. Return JSON "
                "{\"facts\": [{\"fact_type\": one of "
                "[date,provider,party,amount,diagnosis,deadline_candidate], "
                "\"label\": short label, \"text\": the value, \"date\": YYYY-MM-DD or null, "
                "\"confidence\": 0..1}]}. Max 8 facts.",
                f"Document type: {doc_type}\n\n{text[:8000]}",
                max_tokens=900,
            )
            facts = []
            for f in data.get("facts", [])[:8]:
                value = {"text": f.get("text", "")}
                if f.get("date"):
                    value["date"] = f["date"]
                facts.append({
                    "fact_type": f.get("fact_type", "party"),
                    "label": f.get("label", "Fact"),
                    "value": value,
                    "confidence": float(f.get("confidence", 0.8)),
                    "page_ref": 1,
                })
            return {"facts": facts, "ai": True}
        except Exception:  # noqa: BLE001
            pass
    # Heuristic: pull dates and dollar amounts
    facts = []
    for m in re.findall(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", text or "")[:3]:
        facts.append({"fact_type": "date", "label": "Date mentioned",
                      "value": {"text": m}, "confidence": 0.6, "page_ref": 1})
    for m in re.findall(r"\$[\d,]+(?:\.\d{2})?", text or "")[:3]:
        facts.append({"fact_type": "amount", "label": "Amount", "value": {"text": m},
                      "confidence": 0.6, "page_ref": 1})
    return {"facts": facts, "ai": False}


# ---------------------------------------------------------------------------
# Embeddings + semantic search
# ---------------------------------------------------------------------------

def embed(text: str) -> list:
    if is_enabled():
        try:
            resp = _openai().embeddings.create(model=EMBED_MODEL, input=(text or "")[:8000])
            return resp.data[0].embedding
        except Exception:  # noqa: BLE001
            pass
    # Deterministic hashing bag-of-words fallback → real-ish similarity offline
    vec = [0.0] * EMBED_DIM
    for tok in re.findall(r"[a-z]{3,}", (text or "").lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % EMBED_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

_NEG_WORDS = ["angry", "upset", "frustrated", "unacceptable", "ridiculous", "ignored",
              "no one", "nobody", "terrible", "worst", "fire", "lawyer up", "complaint",
              "bar", "sue you", "disappointed", "waiting", "never call", "fed up"]


def score_sentiment(text: str) -> dict:
    if is_enabled():
        try:
            data = _chat_json(
                "You monitor client messages at a law firm for dissatisfaction. Classify the "
                "sentiment. Return JSON {\"sentiment\": one of [positive,neutral,negative], "
                "\"flag\": true if a manager should review before this becomes a complaint}.",
                (text or "")[:2000],
            )
            s = data.get("sentiment", "neutral")
            if s not in ("positive", "neutral", "negative"):
                s = "neutral"
            return {"sentiment": s, "flagged": bool(data.get("flag")) or s == "negative", "ai": True}
        except Exception:  # noqa: BLE001
            pass
    low = (text or "").lower()
    neg = sum(1 for w in _NEG_WORDS if w in low)
    if neg >= 1:
        return {"sentiment": "negative", "flagged": True, "ai": False}
    return {"sentiment": "neutral", "flagged": False, "ai": False}


# ---------------------------------------------------------------------------
# Case narrative
# ---------------------------------------------------------------------------

def generate_narrative(case_title: str, stage_label: str, events: list) -> dict:
    """events: list of {date, title, description}."""
    lines = [f"{e.get('date','')} — {e.get('title','')}: {e.get('description','')}" for e in events]
    joined = "\n".join(lines)
    if is_enabled() and lines:
        try:
            data = _chat_json(
                "Write a concise, professional running case narrative (a 'case log') for a "
                "personal-injury matter, from the timeline events. 4-7 sentences, past-to-present, "
                "plain language a paralegal would write. Return JSON {\"narrative\": string}.",
                f"Case: {case_title}\nCurrent stage: {stage_label}\nEvents:\n{joined}",
                max_tokens=500,
            )
            if data.get("narrative"):
                return {"text": data["narrative"], "ai": True}
        except Exception:  # noqa: BLE001
            pass
    # Fallback: assemble a readable log from the events
    if not lines:
        return {"text": f"{case_title} is currently in {stage_label}. No timeline events recorded yet.", "ai": False}
    body = " ".join(f"On {e.get('date','')}, {e.get('title','').lower()}." for e in events)
    return {"text": f"{case_title} (currently: {stage_label}). {body}", "ai": False}
