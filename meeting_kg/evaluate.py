"""정답지(samples/answer_key.toml)를 기준으로 지식 그래프의 추출 정확도를 채점한다.

매칭 규칙
- 추적 항목(할 일·요청·이슈): 같은 종류 + 같은 회의에서 생성 + 설명에 키워드가 모두 포함(띄어쓰기 무시).
  후보가 여럿이면 담당자가 겹치는 항목을 먼저 고르고, 한 그래프 항목은 정답 하나에만 매칭한다.
- 결정·지식: 종류가 같고 키워드가 모두 포함되면 매칭한다 (회의 날짜는 보지 않음).

채점 단위(체크)
- 필수 추적 항목마다: 찾음, 담당자, 요청 고객사, 최종 기한, 회의 시점별 상태
- 결정·지식마다: 찾음
- 정답 항목을 찾지 못하면 그 항목의 나머지 체크도 모두 틀린 것으로 센다 (분모가 실행마다 같도록).
"""

import datetime as dt
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import RDF, Graph, Literal, URIRef

from .catalog import STATUS_NAMES, TRACKED_CLASSES, short_id, update_seq, uri_subjects, uri_value
from .config import ONT

FACT_CLASSES = {"Decision": ONT.Decision, "KnowledgeNote": ONT.KnowledgeNote}
CATEGORIES = ["항목 찾기", "담당자", "요청 고객사", "기한", "상태", "결정", "지식"]


# ---- 정답지 -------------------------------------------------------------------


@dataclass(frozen=True)
class KeyItem:
    id: str
    kind: str
    meeting: dt.date
    summary: str
    keywords: list[str]
    exclude: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    customer: str | None = None
    due: dt.date | None = None
    status: dict[dt.date, tuple[str, ...]] = field(default_factory=dict)
    optional: bool = False


@dataclass(frozen=True)
class AnswerKey:
    tracked: list[KeyItem]
    facts: list[KeyItem]  # kind = "Decision" | "KnowledgeNote"


def _date(value: Any) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def _key_item(raw: dict[str, Any], kind: str | None = None) -> KeyItem:
    status = {
        _date(day): tuple(expected) if isinstance(expected, list) else (expected,)
        for day, expected in raw.get("status", {}).items()
    }
    return KeyItem(
        id=raw["id"],
        kind=kind or raw["kind"],
        meeting=_date(raw["meeting"]),
        summary=raw.get("summary", ""),
        keywords=raw["keywords"],
        exclude=raw.get("exclude", []),
        assignees=raw.get("assignees", []),
        customer=raw.get("customer"),
        due=_date(raw["due"]) if "due" in raw else None,
        status=status,
        optional=raw.get("optional", False),
    )


def load_answer_key(path: Path) -> AnswerKey:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tracked = [_key_item(raw) for raw in data.get("tracked", [])]
    for item in tracked:
        if item.kind not in TRACKED_CLASSES:
            raise ValueError(f"{path}: {item.id}의 kind '{item.kind}'를 알 수 없습니다")
    facts = [_key_item(raw, "Decision") for raw in data.get("decisions", [])]
    facts += [_key_item(raw, "KnowledgeNote") for raw in data.get("knowledge", [])]
    return AnswerKey(tracked=tracked, facts=facts)


# ---- 그래프 -------------------------------------------------------------------


@dataclass
class GraphItem:
    uri: URIRef
    kind: str
    description: str
    created: dt.date | None
    assignees: set[str]
    customer: str | None
    due: dt.date | None
    history: list[tuple[dt.date, str]]  # (회의 날짜, 그 회의에서 바뀐 상태), 시간순

    @property
    def id(self) -> str:
        return short_id(self.uri)

    def status_on(self, day: dt.date) -> str | None:
        """그 회의가 끝난 시점의 상태 (그 회의에서 언급이 없으면 직전 상태가 유지됨)."""
        current = None
        for when, status in self.history:
            if when > day:
                break
            current = status
        return current


def _date_value(g: Graph, subject: URIRef, predicate: URIRef) -> dt.date | None:
    value = g.value(subject, predicate)
    return _date(value.toPython()) if isinstance(value, Literal) else None


def _meeting_date(g: Graph, meeting: URIRef | None) -> dt.date | None:
    return _date_value(g, meeting, ONT.meetingDate) if meeting is not None else None


def load_graph_items(g: Graph) -> list[GraphItem]:
    items = []
    for kind, cls in TRACKED_CLASSES.items():
        for uri in uri_subjects(g, RDF.type, cls):
            history = []
            for update in uri_subjects(g, ONT.updateOf, uri):
                when = _meeting_date(g, uri_value(g, update, ONT.recordedIn))
                status = uri_value(g, update, ONT.newStatus)
                if when is not None and status in STATUS_NAMES:
                    history.append((when, update_seq(update), STATUS_NAMES[status]))
            customer = uri_value(g, uri, ONT.requestedBy)
            items.append(
                GraphItem(
                    uri=uri,
                    kind=kind,
                    description=str(g.value(uri, ONT.description) or ""),
                    created=_meeting_date(g, uri_value(g, uri, ONT.createdIn)),
                    assignees={short_id(a) for a in g.objects(uri, ONT.assignedTo) if isinstance(a, URIRef)},
                    customer=short_id(customer) if customer else None,
                    due=_date_value(g, uri, ONT.dueDate),
                    history=[(when, status) for when, _, status in sorted(history)],
                )
            )
    return items


def load_graph_facts(g: Graph) -> list[GraphItem]:
    facts = []
    for kind, cls in FACT_CLASSES.items():
        for uri in uri_subjects(g, RDF.type, cls):
            facts.append(
                GraphItem(
                    uri=uri,
                    kind=kind,
                    description=str(g.value(uri, ONT.description) or ""),
                    created=_meeting_date(g, uri_value(g, uri, ONT.mentionedIn)),
                    assignees=set(),
                    customer=None,
                    due=None,
                    history=[],
                )
            )
    return facts


# ---- 매칭과 채점 ----------------------------------------------------------------


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def keywords_match(description: str, key: KeyItem) -> bool:
    text = normalize(description)
    if any(normalize(word) in text for word in key.exclude):
        return False
    return all(any(normalize(alt) in text for alt in group.split("|")) for group in key.keywords)


@dataclass
class Check:
    category: str
    ok: bool
    expected: str
    actual: str


@dataclass
class ItemResult:
    key: KeyItem
    match: GraphItem | None
    checks: list[Check]


@dataclass
class Evaluation:
    tracked: list[ItemResult]
    facts: list[ItemResult]
    duplicates: list[tuple[GraphItem, KeyItem]]  # (중복 그래프 항목, 이미 매칭된 정답)
    extras: list[GraphItem]  # 정답지에 없는 그래프 항목

    def scored_checks(self) -> list[Check]:
        return [c for r in self.tracked + self.facts if not r.key.optional for c in r.checks]

    def summary(self) -> dict[str, tuple[int, int]]:
        counts: dict[str, tuple[int, int]] = {}
        for category in CATEGORIES:
            checks = [c for c in self.scored_checks() if c.category == category]
            counts[category] = (sum(c.ok for c in checks), len(checks))
        return counts

    @property
    def score(self) -> tuple[int, int]:
        checks = self.scored_checks()
        return sum(c.ok for c in checks), len(checks)


def _show(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, (set, list, tuple)):
        return ",".join(sorted(str(v) for v in value)) or "-"
    return str(value)


def _tracked_checks(key: KeyItem, match: GraphItem | None) -> list[Check]:
    checks = [Check("항목 찾기", match is not None, key.summary, match.id if match else "-")]
    if key.assignees:
        actual = match.assignees if match else set()
        checks.append(Check("담당자", set(key.assignees) <= actual, _show(key.assignees), _show(actual)))
    if key.customer:
        actual_customer = match.customer if match else None
        checks.append(Check("요청 고객사", actual_customer == key.customer, key.customer, _show(actual_customer)))
    if key.due:
        actual_due = match.due if match else None
        checks.append(Check("기한", actual_due == key.due, str(key.due), _show(actual_due)))
    for day, expected in sorted(key.status.items()):
        actual_status = match.status_on(day) if match else None
        checks.append(
            Check("상태", actual_status in expected, f"{day:%m-%d} {'|'.join(expected)}", _show(actual_status))
        )
    return checks


def _pick(key: KeyItem, candidates: list[GraphItem]) -> GraphItem | None:
    """담당자가 가장 많이 겹치는 후보. 같으면 ID 순서로 정해 실행마다 결과가 같게 한다."""
    ranked = sorted(candidates, key=lambda c: (-len(c.assignees & set(key.assignees)), c.id))
    return ranked[0] if ranked else None


def _order(item: GraphItem) -> int:
    return item.created.toordinal() if item.created else 0


def evaluate(g: Graph, answer_key: AnswerKey) -> Evaluation:
    items = load_graph_items(g)
    used: set[URIRef] = set()

    # 필수 항목을 먼저 매칭해야 선택 항목이 필수 항목의 짝을 가로채지 않는다
    tracked_results: dict[str, ItemResult] = {}
    for key in sorted(answer_key.tracked, key=lambda k: k.optional):
        candidates = [
            item
            for item in items
            if item.uri not in used
            and item.kind == key.kind
            and item.created == key.meeting
            and keywords_match(item.description, key)
        ]
        match = _pick(key, candidates)
        if match:
            used.add(match.uri)
        tracked_results[key.id] = ItemResult(key, match, _tracked_checks(key, match))

    matched_keys = [r.key for r in tracked_results.values() if r.match]
    duplicates, extras = [], []
    for item in items:
        if item.uri in used:
            continue
        # 생성 회의와 관계없이 이미 매칭된 정답과 같은 내용이면 중복 등록
        twin = next((k for k in matched_keys if k.kind == item.kind and keywords_match(item.description, k)), None)
        if twin:
            duplicates.append((item, twin))
        else:
            extras.append(item)

    facts = load_graph_facts(g)
    used_facts: set[URIRef] = set()
    fact_results = []
    for key in answer_key.facts:
        candidates = [
            f for f in facts if f.uri not in used_facts and f.kind == key.kind and keywords_match(f.description, key)
        ]
        match = min(candidates, key=lambda f: (_order(f), f.id)) if candidates else None
        if match:
            used_facts.add(match.uri)
        category = "결정" if key.kind == "Decision" else "지식"
        fact_results.append(
            ItemResult(key, match, [Check(category, match is not None, key.summary, _show(match and match.id))])
        )

    ordered = [tracked_results[k.id] for k in answer_key.tracked]
    return Evaluation(tracked=ordered, facts=fact_results, duplicates=duplicates, extras=extras)


def evaluation_to_dict(result: Evaluation) -> dict[str, Any]:
    """비교·기록용 JSON 형태."""
    correct, total = result.score
    return {
        "score": {"correct": correct, "total": total, "ratio": round(correct / total, 4) if total else None},
        "categories": {name: {"correct": c, "total": t} for name, (c, t) in result.summary().items()},
        "duplicates": [{"graph": item.id, "answer": key.id} for item, key in result.duplicates],
        "extras": [{"graph": item.id, "kind": item.kind, "description": item.description} for item in result.extras],
        "failed": [
            {"answer": r.key.id, "category": c.category, "expected": c.expected, "actual": c.actual}
            for r in result.tracked + result.facts
            if not r.key.optional
            for c in r.checks
            if not c.ok
        ],
    }
