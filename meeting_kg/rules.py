"""RDF 그래프 → wirelog Datalog 사실 → 점검 규칙(rules/checks.dl) 실행.

RDF/OWL은 스키마·저장·질의를 맡고, wirelog는 이벤트 이력에서 현재 상태를 계산하고
모순·이상 징후를 찾는 규칙 계층을 맡는다.
"""

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pyrewire import EasySession
from rdflib import RDF, Graph, Literal, URIRef

from .catalog import STATUS_NAMES, TRACKED_CLASSES, short_id, update_seq, uri_subjects, uri_value
from .config import ONT, RULES_FILE

type Fact = tuple[str | int, ...]
type Facts = dict[str, list[Fact]]

# check 명령이 보여 주는 결과 관계: (설명, 열 이름). 출력 순서대로.
CHECKS: dict[str, tuple[str, list[str]]] = {
    "status_mismatch": ("저장된 현재 상태와 이벤트로 계산한 상태가 다름 (변환 코드 오류)", ["항목", "저장", "계산"]),
    "due_mismatch": ("저장된 기한과 이벤트로 계산한 기한이 다름 (변환 코드 오류)", ["항목", "저장", "계산"]),
    "status_conflict": ("같은 회의 안에서 상태가 엇갈림", ["항목", "회의", "먼저", "나중"]),
    "due_conflict": ("같은 회의 안에서 기한이 엇갈림", ["항목", "회의", "먼저", "나중"]),
    "unattended_change": ("담당자가 아무도 참석하지 않은 회의에서 상태·기한이 바뀜", ["항목", "회의"]),
    "reopened": ("완료됐던 일이 나중에 다시 열림", ["항목", "완료 시점", "재개 시점", "상태"]),
    "overdue": ("마지막 회의 기준으로 기한이 지났는데 끝나지 않음", ["항목", "기한", "상태"]),
    "weekend_due": ("기한이 주말 (상대 날짜 계산 오류 가능성)", ["항목", "기한"]),
    "duplicate_candidate": (
        "같은 고객사·같은 기능에 대해 다른 회의에서 또 만들어진 요청·이슈",
        ["먼저", "나중", "고객사", "기능"],
    ),
}


def date_int(day: dt.date) -> int:
    return day.year * 10000 + day.month * 100 + day.day


def _date(g: Graph, subject: URIRef, predicate: URIRef) -> dt.date | None:
    value = g.value(subject, predicate)
    if isinstance(value, Literal) and isinstance(value.toPython(), dt.date):
        day: dt.date = value.toPython()
        return day
    return None


@dataclass(frozen=True)
class MeetingFacts:
    meeting: str
    date: dt.date
    facts: Facts


def export_facts(g: Graph) -> list[MeetingFacts]:
    """그래프를 회의별 사실 묶음으로 내보낸다. 회의 순서대로 넣으면 증분 계산을 볼 수 있다."""
    meetings: dict[URIRef, MeetingFacts] = {}
    for m in uri_subjects(g, RDF.type, ONT.Meeting):
        day = _date(g, m, ONT.meetingDate)
        if day is None:
            continue
        facts: Facts = {"meeting": [(short_id(m), date_int(day))]}
        facts["attended"] = [(short_id(m), short_id(p)) for p in uri_subjects_of(g, m, ONT.participant)]
        meetings[m] = MeetingFacts(short_id(m), day, facts)

    def add(m: URIRef | None, relation: str, row: Fact) -> None:
        if m in meetings:
            meetings[m].facts.setdefault(relation, []).append(row)

    for kind, cls in TRACKED_CLASSES.items():
        for item in uri_subjects(g, RDF.type, cls):
            created = uri_value(g, item, ONT.createdIn)
            iid = short_id(item)
            add(created, "created", (iid, kind, short_id(created) if created else ""))
            for agent in uri_subjects_of(g, item, ONT.assignedTo):
                add(created, "assigned", (iid, short_id(agent)))
            for prop in (ONT.requestedBy, ONT.reportedBy):
                cust = uri_value(g, item, prop)
                if cust is not None and (cust, RDF.type, ONT.Customer) in g:
                    add(created, "customer", (iid, short_id(cust)))
            for prop in (ONT.relatesTo, ONT.affects):
                for x in uri_subjects_of(g, item, prop):
                    add(created, "target", (iid, short_id(x)))

            for update in uri_subjects(g, ONT.updateOf, item):
                recorded = uri_value(g, update, ONT.recordedIn)
                status = uri_value(g, update, ONT.newStatus)
                day = _date(g, recorded, ONT.meetingDate) if recorded else None
                if recorded is None or day is None or status not in STATUS_NAMES:
                    continue
                seq = date_int(day) * 10 + update_seq(update)
                add(recorded, "status_event", (iid, seq, STATUS_NAMES[status], short_id(recorded)))
                if due := _date(g, update, ONT.newDueDate):
                    add(recorded, "due_event", (iid, seq, date_int(due), short_id(recorded)))
                    if due.weekday() >= 5:
                        add(recorded, "weekend", (date_int(due),))

    ordered = sorted(meetings.values(), key=lambda mf: mf.date)
    if not ordered:
        return []

    # 회의와 관계없는 사실은 첫 묶음에 넣는다: 조직도, 기능 목록, 저장된 현재 값
    base = ordered[0].facts
    for person in uri_subjects(g, RDF.type, ONT.Employee):
        for dept in uri_subjects_of(g, person, ONT.memberOf):
            base.setdefault("member", []).append((short_id(person), short_id(dept)))
    base["feature"] = [(short_id(x),) for x in uri_subjects(g, RDF.type, ONT.Feature)]
    return ordered


def stored_values(g: Graph) -> Facts:
    """to_rdf가 그래프에 저장한 '현재 값'. 이벤트로 계산한 값과 대조하는 데 쓴다."""
    facts: Facts = {"stored_status": [], "stored_due": []}
    for cls in TRACKED_CLASSES.values():
        for item in uri_subjects(g, RDF.type, cls):
            status = uri_value(g, item, ONT.status)
            if status in STATUS_NAMES:
                facts["stored_status"].append((short_id(item), STATUS_NAMES[status]))
            if due := _date(g, item, ONT.dueDate):
                facts["stored_due"].append((short_id(item), date_int(due)))
    return facts


def uri_subjects_of(g: Graph, subject: URIRef, predicate: URIRef) -> list[URIRef]:
    """(subject, predicate, ?)의 값 중 URI만 정렬해서 돌려준다."""
    return sorted(o for o in g.objects(subject, predicate) if isinstance(o, URIRef))


def _fact(row: tuple[object, ...]) -> Fact:
    """엔진이 돌려준 행. 이 규칙 파일의 열은 symbol(str)과 int64(int)뿐이다."""
    return tuple(v if isinstance(v, int) else str(v) for v in row)


def _insert(session: EasySession, facts: Facts) -> None:
    for relation, rows in facts.items():
        for row in rows:
            session.insert(relation, list(row))


def run_checks(g: Graph, rules: Path = RULES_FILE) -> dict[str, list[Fact]]:
    """모든 사실을 넣고 점검 결과 관계의 전체 내용을 돌려준다."""
    with EasySession(rules.read_text(encoding="utf-8")) as session:
        for batch in export_facts(g):
            _insert(session, batch.facts)
        _insert(session, stored_values(g))
        names = [*CHECKS, "current_status", "current_due"]
        results = {name: sorted(_fact(row) for row in session.snapshot(name)) for name in names}
    return results


@dataclass(frozen=True)
class Delta:
    meeting: str
    date: dt.date
    relation: str
    row: Fact
    diff: int  # +1 생김, -1 사라짐


def run_timeline(g: Graph, relations: list[str], rules: Path = RULES_FILE) -> Iterator[Delta]:
    """회의를 하나씩 넣으면서 증분 계산(step)한다. 각 회의가 바꾼 결과만 나온다."""
    with EasySession(rules.read_text(encoding="utf-8")) as session:
        for batch in export_facts(g):
            _insert(session, batch.facts)
            for relation, row, diff in session.step():
                if relation in relations:
                    yield Delta(batch.meeting, batch.date, relation, _fact(row), diff)
