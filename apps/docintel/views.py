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
    """Keyword search across published docs (pgvector semantic search later)."""
    q = (request.GET.get("q") or "").strip()
    if not q:
        return Response({"results": []})
    docs = DocRecord.objects.select_related("case", "case__client").filter(
        status="published"
    )
    results = []
    for d in docs:
        haystack = f"{d.filename} {d.summary} {d.extracted_text}".lower()
        if q.lower() in haystack:
            idx = haystack.find(q.lower())
            snippet = haystack[max(0, idx - 60) : idx + 120]
            results.append({**_doc_json(d), "snippet": f"...{snippet}..."})
    return Response({"results": results[:25]})
