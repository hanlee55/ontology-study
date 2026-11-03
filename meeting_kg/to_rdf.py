"""MeetingExtraction(JSON) → RDF 트리플.

- 모든 항목에 출처(회의, 근거 발언, 신뢰도, 추출 모델)를 붙인다.
- 기존 항목이 다시 언급되면 새로 만들지 않고 현재 상태를 갱신하며,
  변경 내역은 StatusUpdate 이벤트로 남긴다 (히스토리).
"""

import datetime as dt
import difflib
import re
from collections.abc import Sequence
from decimal import Decimal

from rdflib import RDF, RDFS, XSD, Graph, Literal, URIRef

from .catalog import PRIORITIES, STATUSES, TRACKED_CLASSES, build_alias_index, short_id, uri_subjects, uri_value
from .config import EX, ONT, SKOS
from .models import ActionItem, CustomerRequest, Issue, MeetingExtraction, Provenance, Status
from .transcript import Transcript

type NewTrackedItem = ActionItem | CustomerRequest | Issue

NEW_ENTITY_PREFIX = {
    "Feature": "feat",
    "CustomerContact": "contact",
    "Employee": "emp",
    "Customer": "cust",
    "Service": "svc",
}
NEW_ENTITY_PARENT = {
    "Feature": ONT.featureOf,
    "CustomerContact": ONT.worksFor,
    "Employee": ONT.memberOf,
}


class IdResolver:
    """LLM이 돌려준 ID 문자열을 그래프의 URI로 바꾼다."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.new_ids: dict[str, URIRef] = {}
        self.alias_index = build_alias_index(graph)
        self.known_ids = sorted({short_id(u) for u in self.alias_index.values()})
        self.warnings: list[str] = []

    def __call__(self, value: str | None) -> URIRef | None:
        if not value:
            return None
        key = value.strip().removeprefix("ex:")
        if key in self.new_ids:
            return self.new_ids[key]
        if key.startswith("new:"):
            self.warnings.append(f"알 수 없는 임시 ID '{value}' → 무시")
            return None

        if re.fullmatch(r"[\w-]+", key):
            candidate = EX[key]
            if (candidate, None, None) in self.graph or candidate in self.new_ids.values():
                return candidate
        # ID 대신 이름이나 별칭을 돌려준 경우 ("박지훈", "가온물산")
        if alias := self.alias_index.get(key.replace(" ", "")):
            return alias
        # 비슷한 ID를 지어낸 경우 ("emp-cs-yuna" → "emp-choi-yuna")
        prefix = key.split("-", 1)[0] + "-"
        candidates = [i for i in self.known_ids if i.startswith(prefix)]
        if match := difflib.get_close_matches(key, candidates, n=1, cutoff=0.7):
            self.warnings.append(f"ID 보정 '{value}' → '{match[0]}'")
            return EX[match[0]]
        self.warnings.append(f"알 수 없는 ID '{value}' → 무시")
        return None

    def customer(self, value: str | None) -> URIRef | None:
        """고객사 자리에 고객 담당자가 오면 그 사람의 근무 고객사로 바꾼다."""
        uri = self(value)
        if uri is not None and (uri, RDF.type, ONT.CustomerContact) in self.graph:
            return uri_value(self.graph, uri, ONT.worksFor)
        return uri

    def many(self, values: list[str]) -> list[URIRef]:
        return [uri for v in values if (uri := self(v)) is not None]


def slugify(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-").lower()
    return slug or "item"


def add_provenance(g: Graph, subject: URIRef, item: Provenance, meeting: URIRef, model: str) -> None:
    g.add((subject, ONT.evidence, Literal(item.evidence)))
    g.add((subject, ONT.confidence, Literal(Decimal(str(round(item.confidence, 2))), datatype=XSD.decimal)))
    g.add((subject, ONT.extractedBy, Literal(model)))
    g.add((subject, ONT.mentionedIn, meeting))


def similar(a: str, b: str, threshold: float = 0.85) -> bool:
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def find_duplicate(g: Graph, cls: URIRef, description: str) -> URIRef | None:
    for uri in uri_subjects(g, RDF.type, cls):
        if similar(str(g.value(uri, ONT.description) or ""), description):
            return uri
    return None


def parse_date(value: str | None) -> Literal | None:
    if not value:
        return None
    try:
        return Literal(dt.date.fromisoformat(value), datatype=XSD.date)
    except ValueError:
        return None


def apply_extraction(g: Graph, transcript: Transcript, extraction: MeetingExtraction, model: str) -> list[str]:
    """추출 결과를 그래프에 반영하고 경고 메시지 목록을 돌려준다."""
    resolve = IdResolver(g)
    meeting = EX[transcript.meeting_id]
    stamp = transcript.date.strftime("%Y%m%d")

    # ---- 회의 ----------------------------------------------------------------
    g.add((meeting, RDF.type, ONT.Meeting))
    g.add((meeting, RDFS.label, Literal(transcript.title)))
    g.add((meeting, ONT.meetingDate, Literal(transcript.date, datatype=XSD.date)))
    g.add((meeting, ONT.summary, Literal(extraction.summary)))
    g.add((meeting, ONT.sourceFile, Literal(f"samples/{transcript.path.name}")))

    # ---- 새 엔티티 (먼저 등록해야 다른 항목에서 참조 가능) ----------------------
    for entity in extraction.new_entities:
        uri = EX[f"{NEW_ENTITY_PREFIX[entity.type]}-{slugify(entity.label)}"]
        resolve.new_ids[entity.temp_id.removeprefix("ex:")] = uri
        if (uri, RDF.type, None) not in g:
            g.add((uri, RDF.type, ONT[entity.type]))
            g.add((uri, RDFS.label, Literal(entity.label)))
            g.add((uri, ONT.createdIn, meeting))
        for alias in entity.aliases:
            if alias != entity.label:
                g.add((uri, SKOS.altLabel, Literal(alias)))
        if (prop := NEW_ENTITY_PARENT.get(entity.type)) and (parent := resolve(entity.parent)):
            g.add((uri, prop, parent))

    # ---- 새 추적 항목의 URI를 먼저 발급 (서로 참조할 수 있도록) ------------------
    # LLM이 기존 항목을 새 항목으로 다시 만든 경우는 새로 만들지 않고 기존 항목에 병합한다.
    new_items: list[tuple[str, URIRef, NewTrackedItem]] = []
    merged: list[tuple[URIRef, NewTrackedItem]] = []  # (기존 항목, 중복으로 추출된 항목)
    groups: list[tuple[str, str, Sequence[NewTrackedItem]]] = [
        ("ActionItem", "ai", extraction.action_items),
        ("CustomerRequest", "req", extraction.customer_requests),
        ("Issue", "iss", extraction.issues),
    ]
    for kind, prefix, items in groups:
        cls = TRACKED_CLASSES[kind]
        for n, item in enumerate(items, 1):
            ref = item.ref.strip().removeprefix("ex:")
            duplicate = find_duplicate(g, cls, item.description)
            if duplicate is None:
                # updates에 이미 넣은 내용을 새 항목으로 한 번 더 만든 경우
                for update in extraction.updates:
                    target = resolve(update.existing_id)
                    if target and (target, RDF.type, cls) in g and similar(update.note, item.description):
                        duplicate = target
                        break
            if duplicate is not None:
                resolve.new_ids[ref] = duplicate
                merged.append((duplicate, item))
                resolve.warnings.append(f"중복 병합: 새 {kind} '{item.ref}' → 기존 '{short_id(duplicate)}'")
            else:
                uri = EX[f"{prefix}-{stamp}-{n:02d}"]
                resolve.new_ids[ref] = uri
                new_items.append((kind, uri, item))

    for person in resolve.many(extraction.participants):
        g.add((meeting, ONT.participant, person))
    for customer in resolve.many(extraction.customers):
        g.add((meeting, ONT.aboutCustomer, customer))

    # ---- 지식 메모 -------------------------------------------------------------
    for n, note in enumerate(extraction.knowledge, 1):
        about = resolve(note.about)
        if about is None:
            continue
        uri = EX[f"note-{stamp}-{n:02d}"]
        g.add((uri, RDF.type, ONT.KnowledgeNote))
        g.add((uri, ONT.about, about))
        g.add((uri, ONT.description, Literal(note.statement)))
        add_provenance(g, uri, note, meeting, model)

    # ---- 결정사항 --------------------------------------------------------------
    for n, decision in enumerate(extraction.decisions, 1):
        uri = EX[f"dec-{stamp}-{n:02d}"]
        g.add((uri, RDF.type, ONT.Decision))
        g.add((uri, ONT.description, Literal(decision.description)))
        g.add((uri, ONT.createdIn, meeting))
        for agent in resolve.many(decision.decided_by):
            g.add((uri, ONT.decidedBy, agent))
        for target in resolve.many(decision.relates_to):
            g.add((uri, ONT.relatesTo, target))
        add_provenance(g, uri, decision, meeting, model)

    # ---- 새 추적 항목 (할 일 / 고객 요청 / 이슈) -------------------------------
    for kind, uri, item in new_items:
        g.add((uri, RDF.type, TRACKED_CLASSES[kind]))
        g.add((uri, ONT.description, Literal(item.description)))
        g.add((uri, ONT.createdIn, meeting))
        add_provenance(g, uri, item, meeting, model)
        g.add((uri, ONT.status, STATUSES[item.status]))
        if item.priority:
            g.add((uri, ONT.priority, PRIORITIES[item.priority]))
        due = parse_date(item.due_date) if isinstance(item, ActionItem) else None
        if due is not None:
            g.add((uri, ONT.dueDate, due))
        add_status_update(g, uri, item.status, due, item.description, item, meeting, stamp, model)

        match item:
            case ActionItem():
                agents, related = item.assignees, item.relates_to
            case CustomerRequest():
                agents, related = [], item.concerns
                if requester := resolve.customer(item.requested_by):
                    g.add((uri, ONT.requestedBy, requester))
            case Issue():
                agents, related = item.assignees, []
                if reporter := resolve(item.reported_by):
                    g.add((uri, ONT.reportedBy, reporter))
                for affected in resolve.many(item.affects):
                    g.add((uri, ONT.affects, affected))
        for agent in resolve.many(agents):
            g.add((uri, ONT.assignedTo, agent))
        for obj in resolve.many(related):
            g.add((uri, ONT.relatesTo, obj))

    # ---- 기존 항목 업데이트 (히스토리) ------------------------------------------
    for update in extraction.updates:
        target = resolve(update.existing_id)
        if target is None or not any((target, RDF.type, cls) in g for cls in TRACKED_CLASSES.values()):
            resolve.warnings.append(f"업데이트 대상 '{update.existing_id}'가 추적 항목이 아님 → 무시")
            continue
        new_due = parse_date(update.due_date)
        if new_due == g.value(target, ONT.dueDate):
            new_due = None
        g.add((target, ONT.mentionedIn, meeting))
        g.set((target, ONT.status, STATUSES[update.status]))  # 현재 상태는 하나만 유지
        if new_due is not None:
            g.set((target, ONT.dueDate, new_due))
        add_status_update(g, target, update.status, new_due, update.note, update, meeting, stamp, model)

    # 중복으로 병합된 항목: 상태가 달라졌을 때만 이력을 남긴다
    for duplicate, item in merged:
        g.add((duplicate, ONT.mentionedIn, meeting))
        if STATUSES[item.status] != g.value(duplicate, ONT.status):
            g.set((duplicate, ONT.status, STATUSES[item.status]))
            merge_note = f"(중복 추출 병합) {item.description}"
            add_status_update(g, duplicate, item.status, None, merge_note, item, meeting, stamp, model)

    return resolve.warnings


def add_status_update(
    g: Graph,
    item_uri: URIRef,
    status: Status,
    due: Literal | None,
    note: str,
    prov: Provenance,
    meeting: URIRef,
    stamp: str,
    model: str,
) -> None:
    """상태 변경 이벤트. 항목의 현재 상태가 덮어써져도 이력은 남는다."""
    base = f"upd-{item_uri.removeprefix(str(EX))}-{stamp}"
    update, n = EX[base], 1
    while (update, None, None) in g:  # 한 회의에서 같은 항목이 여러 번 갱신된 경우
        n += 1
        update = EX[f"{base}-{n}"]
    g.add((update, RDF.type, ONT.StatusUpdate))
    g.add((update, ONT.updateOf, item_uri))
    g.add((update, ONT.newStatus, STATUSES[status]))
    g.add((update, ONT.recordedIn, meeting))
    g.add((update, ONT.note, Literal(note)))
    if due is not None:
        g.add((update, ONT.newDueDate, due))
    add_provenance(g, update, prov, meeting, model)
