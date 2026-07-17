"""Dict builders for case payloads (shared by portal + console)."""

from apps.cases.models import CANONICAL_STAGES, STAGE_ORDER


def staff_json(u):
    if u is None:
        return None
    return {
        "id": u.id,
        "name": u.get_full_name() or u.email,
        "title": u.title,
        "email": u.email,
        "phone": u.phone,
        "avatar_color": u.avatar_color,
    }


def stage_history_json(case):
    return [
        {
            "from_stage": e.from_stage,
            "to_stage": e.to_stage,
            "note": e.note,
            "created_at": e.created_at.isoformat(),
        }
        for e in case.stage_events.all()
    ]


def case_summary_json(case):
    return {
        "id": str(case.id),
        "title": case.title,
        "case_type": case.case_type,
        "client_name": case.client.name,
        "client_id": str(case.client_id),
        "canonical_stage": case.canonical_stage,
        "stage_label": dict(CANONICAL_STAGES)[case.canonical_stage],
        "stage_index": case.stage_index,
        "stage_count": len(STAGE_ORDER),
        "status": case.status,
        "point_of_contact": staff_json(case.point_of_contact),
        "attorney": staff_json(case.attorney),
        "date_of_incident": case.date_of_incident.isoformat()
        if case.date_of_incident
        else None,
        "opened_at": case.opened_at.isoformat(),
        "last_firm_touch_at": case.last_firm_touch_at.isoformat(),
        "days_since_touch": case.days_since_touch,
        "next_step_note": case.next_step_note,
    }


def portal_case_bundle(case):
    """Everything the client's My Case screen needs in one call."""
    return {
        "case": case_summary_json(case),
        "stage_history": stage_history_json(case),
        "timeline": [
            {
                "date": t.date.isoformat(),
                "title": t.title,
                "description": t.description,
                "entry_type": t.entry_type,
            }
            for t in case.timeline.all()
        ],
    }
