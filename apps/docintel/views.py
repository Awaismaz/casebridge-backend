"""Module B: document review queue (aud=firm-staff only)."""

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.authentication import IsFirmStaff
from apps.billing.models import ValueEvent
from apps.docintel.models import DOC_TYPES, DocRecord, ExtractedFact, TimelineEntry


def _doc_json(d, with_facts=False):
    out = {
        "id": str(d.id),
        "case_id": str(d.case_id),
        "case_title": d.case.title,
        "client_name": d.case.client.name,
        "filename": d.filename,
        "doc_type": d.doc_type,
        "doc_type_label": dict(DOC_TYPES).get(d.doc_type, d.doc_type),
        "classification_confidence": d.classification_confidence,
        "status": d.status,
        "page_count": d.page_count,
        "summary": d.summary,
        "created_at": d.created_at.isoformat(),
        "facts_pending": d.facts.filter(review_status="pending").count(),
        "facts_total": d.facts.count(),
    }
    if with_facts:
        out["extracted_text"] = d.extracted_text
        out["facts"] = [
            {
                "id": f.id,
                "fact_type": f.fact_type,
                "label": f.label,
                "value": f.value,
                "original_value": f.original_value,
                "page_ref": f.page_ref,
                "confidence": f.confidence,
                "review_status": f.review_status,
            }
            for f in d.facts.all()
        ]
    return out


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def review_queue(request):
    qs = DocRecord.objects.select_related("case", "case__client").all()
    status_f = request.GET.get("status")
    if status_f:
        qs = qs.filter(status=status_f)
    doc_type = request.GET.get("doc_type")
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    docs = sorted(qs, key=lambda d: d.classification_confidence)
    return Response(
        {
            "docs": [_doc_json(d) for d in docs[:100]],
            "counts": {
                "in_review": DocRecord.objects.filter(status="in_review").count(),
                "published": DocRecord.objects.filter(status="published").count(),
                "processing": DocRecord.objects.filter(
                    status__in=["queued", "ocr", "classified", "extracted"]
                ).count(),
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def doc_detail(request, doc_id):
    try:
        d = DocRecord.objects.select_related("case", "case__client").get(id=doc_id)
    except DocRecord.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    return Response(_doc_json(d, with_facts=True))


@api_view(["POST"])
@permission_classes([IsFirmStaff])
def fact_review(request, fact_id):
    try:
        f = ExtractedFact.objects.select_related("doc").get(id=fact_id)
    except ExtractedFact.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    action = request.data.get("action")
    if action == "accept":
        f.review_status = "accepted"
    elif action == "reject":
        f.review_status = "rejected"
    elif action == "correct":
        f.original_value = f.value
        f.value = request.data.get("value", f.value)
        f.review_status = "corrected"
    else:
        return Response({"detail": "action must be accept|reject|correct"}, status=400)
    f.reviewed_by = request.user
    f.reviewed_at = timezone.now()
    f.save()
    ValueEvent.objects_unscoped.create(
        firm_id=f.firm_id,
        module="reader",
        event_type=f"fact_{f.review_status}",
        actor_type="staff",
    )
    return Response({"ok": True, "review_status": f.review_status})


@api_view(["POST"])
@permission_classes([IsFirmStaff])
def doc_publish(request, doc_id):
    try:
        d = DocRecord.objects.get(id=doc_id)
    except DocRecord.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    # Auto-accept anything still pending, then publish confirmed facts
    d.facts.filter(review_status="pending").update(
        review_status="accepted", reviewed_by=request.user, reviewed_at=timezone.now()
    )
    for f in d.facts.filter(fact_type__in=["date", "deadline_candidate"]).exclude(
        review_status="rejected"
    ):
        date_val = (f.value or {}).get("date")
        if date_val:
            TimelineEntry.objects_unscoped.get_or_create(
                firm_id=d.firm_id,
                case=d.case,
                date=date_val,
                title=f.label,
                defaults={
                    "description": (f.value or {}).get("text", ""),
                    "source_doc": d,
                    "entry_type": "deadline"
                    if f.fact_type == "deadline_candidate"
                    else "fact",
                },
            )
    d.status = "published"
    d.published_at = timezone.now()
    d.save(update_fields=["status", "published_at"])
    ValueEvent.objects_unscoped.create(
        firm_id=d.firm_id,
        module="reader",
        event_type="doc_published",
        actor_type="staff",
        metadata={"doc_type": d.doc_type, "pages": d.page_count},
    )
    return Response({"ok": True, "status": d.status})


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def search(request):
    """Semantic search across published + in-review docs. Embeds the query and
    ranks by cosine against each doc's stored embedding; falls back to keyword
    matching for anything without an embedding."""
    from casebridge import ai

    q = (request.GET.get("q") or "").strip()
    if not q:
        return Response({"results": [], "mode": "semantic" if ai.is_enabled() else "lexical"})

    docs = list(
        DocRecord.objects.select_related("case", "case__client").exclude(status="queued")
    )
    qvec = ai.embed(q)
    ql = q.lower()
    scored = []
    for d in docs:
        emb = d.embedding
        if emb:
            score = ai.cosine(qvec, emb)
        else:
            hay = f"{d.filename} {d.summary} {d.extracted_text}".lower()
            score = 0.5 if ql in hay else 0.0
        if score > 0.12:
            snippet = (d.summary or d.extracted_text or "")[:180]
            scored.append((score, {**_doc_json(d), "snippet": snippet, "score": round(score, 3)}))
    scored.sort(key=lambda x: x[0], reverse=True)
    return Response({
        "results": [r for _, r in scored[:25]],
        "mode": "semantic" if ai.is_enabled() else "lexical",
    })


@api_view(["POST"])
@permission_classes([IsFirmStaff])
def analyze_text(request):
    """Run the real AI pipeline on pasted/uploaded document text: classify →
    summarize → extract → embed, and persist a DocRecord tied to a case.
    This is the live Smart Document Reader capability (uses OpenAI when keyed)."""
    from casebridge import ai

    from apps.cases.models import PortalCase

    text = (request.data.get("text") or "").strip()
    case_id = request.data.get("case_id")
    filename = (request.data.get("filename") or "pasted-document.txt").strip()
    if len(text) < 20:
        return Response({"detail": "Provide at least a short paragraph of document text."}, status=400)
    case = PortalCase.objects.filter(id=case_id).first() if case_id else PortalCase.objects.first()
    if case is None:
        return Response({"detail": "No case available to attach to."}, status=400)

    cls = ai.classify_document(text)
    summ = ai.summarize_document(text, cls["doc_type"])
    facts = ai.extract_facts(text, cls["doc_type"])
    emb = ai.embed(f"{summ['summary']} {text}")

    doc = DocRecord.objects_unscoped.create(
        firm_id=case.firm_id, case=case, filename=filename,
        doc_type=cls["doc_type"], classification_confidence=cls["confidence"],
        status="in_review", page_count=max(1, len(text) // 2500),
        summary=summ["summary"], extracted_text=text[:20000],
        embedding=emb, ai_processed=cls["ai"],
    )
    for f in facts["facts"]:
        ExtractedFact.objects_unscoped.create(
            firm_id=case.firm_id, doc=doc, fact_type=f["fact_type"], label=f["label"],
            value=f["value"], confidence=f["confidence"], page_ref=f.get("page_ref", 1),
        )
    ValueEvent.objects_unscoped.create(
        firm_id=case.firm_id, module="reader", event_type="doc_ai_analyzed",
        actor_type="staff", metadata={"ai": cls["ai"], "doc_type": cls["doc_type"]},
    )
    return Response({
        "doc_id": str(doc.id),
        "ai_enabled": ai.is_enabled(),
        "classification": cls,
        "summary": summ["summary"],
        "facts_extracted": len(facts["facts"]),
    }, status=201)
