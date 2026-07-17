"""Seed rich demo data. Idempotent: wipes and recreates the demo firms only.

Creates:
  - Zinda Law Group (billing_exempt, both modules comped) — the demo tenant
  - Coastal Injury Law — a second tenant proving cross-firm isolation
  - Staff, clients, cases across the full stage ladder, threads with real
    conversations, evidence files, escalations, Module B docs with facts.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import StaffUser
from apps.billing.models import ModuleEntitlement, ValueEvent
from apps.cases.models import CaseStageEvent, PortalCase
from apps.clients.models import ConsentLog, PortalClientUser
from apps.docintel.models import DocRecord, ExtractedFact, TimelineEntry
from apps.evidence.models import CustodyEvent, EvidenceFile
from apps.messaging.models import EscalationEvent, Message, Notification, Thread
from apps.tenants.context import firm_context
from apps.tenants.models import Firm

NOW = timezone.now()


def days_ago(n, hours=0):
    return NOW - timedelta(days=n, hours=hours)


class Command(BaseCommand):
    help = "Seed demo firms with realistic data (idempotent)."

    def handle(self, *args, **options):
        for slug in ("zinda-law-group", "coastal-injury-law"):
            Firm.objects.filter(slug=slug).delete()

        zlg = Firm.objects.create(
            name="Zinda Law Group",
            slug="zinda-law-group",
            billing_exempt=True,
            settings={
                "escalation_threshold_days": 7,
                "brand_color": "#1E3A5F",
                "quiet_hours": {"start": "21:00", "end": "08:00"},
            },
        )
        coastal = Firm.objects.create(
            name="Coastal Injury Law",
            slug="coastal-injury-law",
            settings={"escalation_threshold_days": 5},
        )

        for firm in (zlg, coastal):
            for module in ("portal", "reader"):
                ModuleEntitlement.objects_unscoped.create(
                    firm=firm,
                    module=module,
                    source="comp" if firm.billing_exempt else "trial",
                )

        # ------------------------------------------------------------------
        # Staff
        # ------------------------------------------------------------------
        def mk_staff(firm, email, first, last, title, role, color, password="demo1234"):
            u = StaffUser.objects.create_user(
                email=email,
                password=password,
                first_name=first,
                last_name=last,
                firm=firm,
                title=title,
                role=role,
                avatar_color=color,
            )
            return u

        sarah = mk_staff(
            zlg, "demo.staff@casebridge.app", "Sarah", "Mitchell",
            "Senior Case Manager", "case_manager", "#1E3A5F",
        )
        marcus = mk_staff(
            zlg, "marcus.demo@casebridge.app", "Marcus", "Webb",
            "Attorney", "attorney", "#7C3AED",
        )
        elena = mk_staff(
            zlg, "elena.demo@casebridge.app", "Elena", "Rodriguez",
            "Intake Specialist", "intake", "#0E7490",
        )
        mk_staff(
            coastal, "pat@coastal-demo.example", "Pat", "Rivera",
            "Case Manager", "case_manager", "#B45309",
        )

        # ------------------------------------------------------------------
        # ZLG clients + cases
        # ------------------------------------------------------------------
        with firm_context(zlg.id):
            demo_client = PortalClientUser.objects_unscoped.create(
                firm=zlg,
                name="Jordan Avery",
                email="demo.client@casebridge.app",
                phone="+15125550142",
                status="active",
            )
            ConsentLog.objects_unscoped.create(
                firm=zlg, client=demo_client, channel="sms", granted=True,
                source="portal",
            )

            others = [
                PortalClientUser.objects_unscoped.create(
                    firm=zlg, name=n, email=e, phone=p, status="active"
                )
                for n, e, p in [
                    ("Maria Gonzales", "maria.g@example.com", "+15125550171"),
                    ("DeShawn Carter", "dcarter@example.com", "+15125550183"),
                    ("Emily Tran", "emily.tran@example.com", "+15125550194"),
                    ("Robert Kowalski", "rkowalski@example.com", "+15125550115"),
                    ("Aisha Thompson", "aisha.t@example.com", "+15125550126"),
                    ("Luis Herrera", "lherrera@example.com", "+15125550137"),
                    ("Grace Kim", "grace.kim@example.com", "+15125550148"),
                ]
            ]

            case_specs = [
                # (client, title, type, stage, poc, attorney, incident_days_ago,
                #  opened_days_ago, touch_days_ago, next_step)
                (demo_client, "MVA — I-35 rear-end collision", "Motor Vehicle Accident",
                 "negotiation", sarah, marcus, 210, 195, 1,
                 "Reviewing the adjuster's counter-offer; response due Friday."),
                (others[0], "Slip and fall — HEB Riverside", "Premises Liability",
                 "treatment", sarah, marcus, 45, 40, 2,
                 "Client continuing PT; check in after next ortho visit."),
                (others[1], "MVA — delivery truck sideswipe", "Motor Vehicle Accident",
                 "records", elena, marcus, 90, 85, 9,
                 "Waiting on Seton Medical records (requested 6/28)."),
                (others[2], "Dog bite — apartment complex", "Animal Attack",
                 "demand", sarah, marcus, 150, 140, 3,
                 "Demand package in draft; finalizing medical chronology."),
                (others[3], "18-wheeler collision — US-290", "Commercial Vehicle",
                 "litigation", elena, marcus, 400, 380, 12,
                 "Depositions scheduled for August 12-14."),
                (others[4], "MVA — intersection T-bone", "Motor Vehicle Accident",
                 "intake", elena, None, 8, 5, 0,
                 "Welcome call complete; LOP paperwork out for signature."),
                (others[5], "Workplace fall — construction site", "Workplace Injury",
                 "settlement", sarah, marcus, 300, 290, 1,
                 "Settlement statement out for client signature."),
                (others[6], "MVA — highway pileup", "Motor Vehicle Accident",
                 "closed", sarah, marcus, 500, 480, 30, ""),
            ]

            stage_path = ["intake", "treatment", "records", "demand",
                          "negotiation", "litigation", "settlement", "closed"]
            cases = []
            for (cl, title, ctype, stage, poc, atty, inc, opened, touch, nxt) in case_specs:
                c = PortalCase.objects_unscoped.create(
                    firm=zlg, client=cl, title=title, case_type=ctype,
                    canonical_stage=stage,
                    status="closed" if stage == "closed" else "open",
                    point_of_contact=poc, attorney=atty,
                    date_of_incident=days_ago(inc).date(),
                    opened_at=days_ago(opened),
                    last_firm_touch_at=days_ago(touch),
                    next_step_note=nxt,
                )
                cases.append(c)
                # Stage history along the path
                idx = stage_path.index(stage)
                step = max(1, (opened - 2) // max(idx, 1)) if idx else opened
                prev = ""
                for i in range(idx + 1):
                    CaseStageEvent.objects_unscoped.create(
                        firm=zlg, case=c, from_stage=prev, to_stage=stage_path[i],
                        created_at=days_ago(opened - i * step),
                    )
                    prev = stage_path[i]

            demo_case = cases[0]

            # Conversation on the demo case
            thread = Thread.objects_unscoped.create(firm=zlg, case=demo_case)
            convo = [
                ("staff", sarah, "Hi Jordan! Quick update — we sent your demand "
                 "package to the insurance company today. They typically respond "
                 "within 30 days. I'll let you know the moment we hear back.", 24, None),
                ("client", None, "That's great news, thank you! Should I keep "
                 "going to my chiropractor appointments in the meantime?", 23, None),
                ("staff", sarah, "Yes — please keep every appointment. Consistent "
                 "treatment records strengthen your case. Let me know if any "
                 "provider gives you trouble.", 23, None),
                ("client", None, "Will do. Also, I found some photos from the "
                 "accident scene on my phone that I don't think I ever sent you.", 6, None),
                ("staff", sarah, "Perfect timing — you can upload them right here "
                 "in the portal under Documents. They'll go straight into your "
                 "case file.", 6, None),
                ("client", None, "Just uploaded them. Let me know if you need "
                 "anything else from me!", 5, None),
                ("system", None, "The insurance company responded with an initial "
                 "offer. Your legal team is reviewing it.", 2, None),
                ("staff", marcus, "Jordan, we received their first offer. It's "
                 "below what we believe your case is worth, so we're preparing a "
                 "counter. I'd like to walk you through the numbers this week — "
                 "Sarah will send a few times.", 1, None),
            ]
            for sender_type, staff, body, d_ago, _ in convo:
                Message.objects_unscoped.create(
                    firm=zlg, thread=thread, sender_type=sender_type,
                    sender_staff=staff,
                    sender_name=staff.get_full_name() if staff else (
                        "Jordan Avery" if sender_type == "client" else "CaseBridge"),
                    body=body, created_at=days_ago(d_ago),
                    read_by_client_at=days_ago(max(d_ago - 1, 0)) if sender_type != "client" and d_ago > 1 else None,
                    read_by_staff_at=days_ago(max(d_ago - 1, 0)) if sender_type == "client" else None,
                )

            # Threads + a message on other cases
            snippets = [
                ("client", "Do you know when my next appointment records will be in?"),
                ("staff", "We requested your records last week — following up today."),
                ("client", "The adjuster called me directly, what should I do?"),
                ("staff", "Never speak to the adjuster — refer them to us. Good catch."),
                ("client", "Is there any update on my case this month?"),
                ("staff", "Welcome to the firm! Your portal is now active."),
                ("staff", "Your settlement statement is ready for signature."),
            ]
            for i, c in enumerate(cases[1:], start=0):
                t = Thread.objects_unscoped.create(firm=zlg, case=c)
                sender_type, body = snippets[i % len(snippets)]
                Message.objects_unscoped.create(
                    firm=zlg, thread=t, sender_type=sender_type,
                    sender_staff=sarah if sender_type == "staff" else None,
                    sender_name=sarah.get_full_name() if sender_type == "staff" else c.client.name,
                    body=body, created_at=days_ago(2 + i * 2),
                )

            # Escalations for out-of-cadence cases
            for c in (cases[2], cases[4]):
                EscalationEvent.objects_unscoped.create(
                    firm=zlg, case=c,
                    days_without_touch=c.days_since_touch,
                    created_at=days_ago(1),
                )

            # Notifications for demo client
            for kind, title, body, d in [
                ("stage_move", "Your case moved to Negotiation",
                 "We're now negotiating with the insurance company on your behalf.", 14),
                ("message", "New message from Marcus Webb",
                 "Jordan, we received their first offer...", 1),
                ("check_in", "Checking in on you",
                 "How is your treatment going? Tap to reply to your case team.", 4),
            ]:
                Notification.objects_unscoped.create(
                    firm=zlg, case=demo_case, kind=kind, title=title, body=body,
                    created_at=days_ago(d),
                    read_at=days_ago(d - 1) if d > 7 else None,
                )

            # Evidence files on demo case
            for fname, mime, size, d in [
                ("accident-scene-photo-1.jpg", "image/jpeg", 2_400_000, 5),
                ("accident-scene-photo-2.jpg", "image/jpeg", 3_100_000, 5),
                ("insurance-card-front.png", "image/png", 890_000, 180),
                ("er-discharge-summary.pdf", "application/pdf", 1_200_000, 170),
            ]:
                f = EvidenceFile.objects_unscoped.create(
                    firm=zlg, case=demo_case, uploader_type="client",
                    uploader_name="Jordan Avery", filename=fname, mime_type=mime,
                    size_bytes=size, status="available",
                    s3_key=f"firm/{zlg.id}/case/{demo_case.id}/{fname}",
                    created_at=days_ago(d),
                )
                CustodyEvent.objects_unscoped.create(
                    firm=zlg, file=f, action="uploaded", actor="Jordan Avery",
                    created_at=days_ago(d),
                )

            # ----------------------------------------------------------
            # Module B: docs in various pipeline states
            # ----------------------------------------------------------
            docs_spec = [
                (demo_case, "seton-medical-records-jan.pdf", "medical_record", 0.97,
                 "in_review", 42,
                 "Records from Seton Medical Center covering the initial ER visit "
                 "and 6 weeks of follow-up orthopedic care for cervical strain and "
                 "lumbar disc herniation at L4-L5.",
                 [
                     ("date", "Date of first treatment", {"text": "ER admission", "date": str(days_ago(208).date())}, 0.98),
                     ("provider", "Treating facility", {"text": "Seton Medical Center Austin"}, 0.99),
                     ("diagnosis", "Primary diagnosis", {"text": "Lumbar disc herniation L4-L5"}, 0.93),
                     ("diagnosis", "Secondary diagnosis", {"text": "Cervical strain (whiplash)"}, 0.91),
                     ("amount", "Total billed charges", {"text": "$18,450.00", "amount": 18450.00}, 0.88),
                 ]),
                (demo_case, "austin-pd-crash-report.pdf", "police_report", 0.99,
                 "published", 4,
                 "Austin PD crash report: defendant vehicle struck plaintiff's "
                 "vehicle from behind on I-35 NB. Defendant cited for failure to "
                 "control speed. Road conditions dry, daylight.",
                 [
                     ("date", "Date of incident", {"text": "Crash date", "date": str(days_ago(210).date())}, 0.99),
                     ("party", "Defendant", {"text": "K. Bratton (cited: failure to control speed)"}, 0.97),
                     ("party", "Investigating officer", {"text": "Officer T. Nguyen, Austin PD"}, 0.95),
                 ]),
                (demo_case, "state-farm-liability-letter.pdf", "insurance_corr", 0.94,
                 "in_review", 2,
                 "State Farm letter accepting liability for their insured and "
                 "requesting medical documentation. Sets a response deadline.",
                 [
                     ("party", "Carrier", {"text": "State Farm — Claim #55-8842-JX1"}, 0.98),
                     ("deadline_candidate", "Response deadline", {"text": "Documentation requested by", "date": str((NOW + timedelta(days=12)).date())}, 0.85),
                 ]),
                (cases[3], "victoria-er-bill.pdf", "medical_bill", 0.96,
                 "in_review", 6,
                 "Emergency room billing statement for initial dog bite treatment "
                 "including rabies prophylaxis series.",
                 [
                     ("amount", "Total charges", {"text": "$6,212.75", "amount": 6212.75}, 0.97),
                     ("provider", "Billing provider", {"text": "St. David's South Austin ER"}, 0.98),
                     ("date", "Service date", {"text": "ER visit", "date": str(days_ago(149).date())}, 0.96),
                 ]),
                (cases[2], "seton-records-request-pending.pdf", "medical_record", 0.72,
                 "extracted", 15,
                 "Partial records received; OCR flagged low scan quality on 4 pages.",
                 [
                     ("provider", "Facility", {"text": "Seton Northwest"}, 0.74),
                 ]),
                (cases[4], "defendant-depo-notice.pdf", "demand_letter", 0.61,
                 "in_review", 3,
                 "Document classified with low confidence — may be a deposition "
                 "notice rather than a demand letter. Review classification.",
                 [
                     ("deadline_candidate", "Deposition date", {"text": "Corporate rep deposition", "date": str((NOW + timedelta(days=26)).date())}, 0.79),
                 ]),
            ]
            for case, fname, dtype, conf, dstatus, pages, summary, facts in docs_spec:
                d = DocRecord.objects_unscoped.create(
                    firm=zlg, case=case, filename=fname, doc_type=dtype,
                    classification_confidence=conf, status=dstatus,
                    page_count=pages, summary=summary,
                    extracted_text=summary,
                    created_at=days_ago(3),
                    published_at=days_ago(1) if dstatus == "published" else None,
                )
                for ftype, label, value, fconf in facts:
                    ExtractedFact.objects_unscoped.create(
                        firm=zlg, doc=d, fact_type=ftype, label=label,
                        value=value, confidence=fconf,
                        review_status="accepted" if dstatus == "published" else "pending",
                        page_ref=1,
                    )

            # Timeline for demo case
            for d, title, desc, etype in [
                (210, "Accident on I-35", "Rear-end collision, NB near Riverside Dr.", "fact"),
                (208, "Emergency room treatment", "Seton Medical Center — initial evaluation.", "fact"),
                (195, "Case opened", "Retainer signed with Zinda Law Group.", "stage"),
                (150, "MRI confirms disc herniation", "L4-L5 herniation documented.", "fact"),
                (60, "Treatment completed", "Released from orthopedic care.", "fact"),
                (30, "Demand package sent", "Full demand delivered to State Farm.", "stage"),
                (2, "Initial offer received", "Under review by your legal team.", "fact"),
            ]:
                TimelineEntry.objects_unscoped.create(
                    firm=zlg, case=demo_case, date=days_ago(d).date(),
                    title=title, description=desc, entry_type=etype,
                )

            # Value events for dashboard trends
            for i in range(40):
                ValueEvent.objects_unscoped.create(
                    firm=zlg, module="portal" if i % 3 else "reader",
                    event_type=["client_message_sent", "staff_message_sent",
                                "evidence_uploaded", "doc_published"][i % 4],
                    actor_type="client" if i % 4 == 0 else "staff",
                    created_at=days_ago(i % 28),
                )

        # ------------------------------------------------------------------
        # Coastal (isolation proof): one client, one case
        # ------------------------------------------------------------------
        with firm_context(coastal.id):
            cc = PortalClientUser.objects_unscoped.create(
                firm=coastal, name="Sam Field", email="sam@coastal-demo.example",
                phone="+18135550100", status="active",
            )
            PortalCase.objects_unscoped.create(
                firm=coastal, client=cc, title="Boating accident — Tampa Bay",
                case_type="Maritime Injury", canonical_stage="records",
                point_of_contact=StaffUser.objects.get(email="pat@coastal-demo.example"),
                opened_at=days_ago(60), last_firm_touch_at=days_ago(2),
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {Firm.objects.count()} firms | "
            f"{StaffUser.objects.exclude(firm=None).count()} staff | "
            f"{PortalClientUser.objects_unscoped.count()} clients | "
            f"{PortalCase.objects_unscoped.count()} cases | "
            f"{DocRecord.objects_unscoped.count()} docs"
        ))
        self.stdout.write("Demo staff:  demo.staff@casebridge.app / demo1234")
        self.stdout.write("Demo client: demo.client@casebridge.app (OTP 246810)")
