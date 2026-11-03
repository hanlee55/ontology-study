"""그래프에 이미 있는 엔티티와 추적 항목을 LLM에게 보여줄 목록으로 정리한다.

LLM이 "민수 님", "가온 쪽" 같은 표현을 기존 ID(emp-kim-minsu, cust-gaon)로
연결할 수 있도록, 이름과 별칭을 함께 제공하는 것이 엔티티 정규화의 핵심이다.
"""

from typing import Any

from rdflib import RDF, RDFS, Graph, URIRef
from rdflib.term import Node

from .config import EX, ONT, SKOS

ENTITY_CLASSES = {
    "Employee": ONT.Employee,
    "CustomerContact": ONT.CustomerContact,
    "Department": ONT.Department,
    "Customer": ONT.Customer,
    "Service": ONT.Service,
    "Feature": ONT.Feature,
}

STATUSES = {
    "open": ONT.Open,
    "in_progress": ONT.InProgress,
    "blocked": ONT.Blocked,
    "done": ONT.Done,
    "cancelled": ONT.Cancelled,
}
STATUS_NAMES = {uri: name for name, uri in STATUSES.items()}

PRIORITIES = {"high": ONT.High, "medium": ONT.Medium, "low": ONT.Low}

TRACKED_CLASSES = {
    "ActionItem": ONT.ActionItem,
    "CustomerRequest": ONT.CustomerRequest,
    "Issue": ONT.Issue,
}

# 엔티티별로 함께 보여줄 맥락 정보 (예: 직원의 소속 부서)
CONTEXT_PROPERTIES = {
    "Employee": ONT.memberOf,
    "CustomerContact": ONT.worksFor,
    "Department": ONT.subOrganizationOf,
    "Feature": ONT.featureOf,
}


type Record = dict[str, Any]


def short_id(uri: URIRef) -> str:
    return str(uri).removeprefix(str(EX))


def uri_subjects(graph: Graph, predicate: Node, obj: Node) -> list[URIRef]:
    """(?, predicate, obj) 패턴의 주어 중 URI만 정렬해서 돌려준다."""
    return sorted(s for s in graph.subjects(predicate, obj) if isinstance(s, URIRef))


def uri_value(graph: Graph, subject: Node, predicate: Node) -> URIRef | None:
    """(subject, predicate, ?)의 값이 URI면 돌려준다."""
    value = graph.value(subject, predicate)
    return value if isinstance(value, URIRef) else None


def update_seq(update: URIRef) -> int:
    """한 회의 안에서 몇 번째 상태 변경인지. to_rdf가 upd-…-20261020, upd-…-20261020-2 순으로 만든다."""
    last = short_id(update).rsplit("-", 1)[-1]
    return 1 if len(last) == 8 else int(last)


def label_of(graph: Graph, uri: Node) -> str:
    label = graph.value(uri, RDFS.label) or graph.value(uri, ONT.description)
    return str(label) if label is not None else str(uri).removeprefix(str(EX))


def build_entity_catalog(graph: Graph) -> list[Record]:
    catalog = []
    for type_name, cls in ENTITY_CLASSES.items():
        for uri in uri_subjects(graph, RDF.type, cls):
            entry: Record = {
                "id": short_id(uri),
                "type": type_name,
                "label": label_of(graph, uri),
                "aliases": sorted(str(a) for a in graph.objects(uri, SKOS.altLabel)),
            }
            prop = CONTEXT_PROPERTIES.get(type_name)
            if prop and (parent := uri_value(graph, uri, prop)):
                entry["in"] = short_id(parent)
            if title := graph.value(uri, ONT.jobTitle):
                entry["title"] = str(title)
            catalog.append(entry)
    return catalog


def build_tracked_items(graph: Graph, include_closed: bool = False) -> list[Record]:
    """다음 회의 추출 시 '이미 존재하는 할 일·요청·이슈'로 알려줄 목록."""
    closed = {ONT.Done, ONT.Cancelled}
    items = []
    for type_name, cls in TRACKED_CLASSES.items():
        for uri in uri_subjects(graph, RDF.type, cls):
            status = uri_value(graph, uri, ONT.status)
            if status in closed and not include_closed:
                continue
            items.append(
                {
                    "id": short_id(uri),
                    "type": type_name,
                    "description": str(graph.value(uri, ONT.description)),
                    "status": STATUS_NAMES.get(status) if status else None,
                    "assignees": [label_of(graph, a) for a in graph.objects(uri, ONT.assignedTo)],
                    "due_date": str(d) if (d := graph.value(uri, ONT.dueDate)) else None,
                }
            )
    return items


def build_alias_index(graph: Graph) -> dict[str, URIRef]:
    """이름·별칭 → URI. LLM이 ID 대신 이름을 돌려줬을 때 복구용."""
    index: dict[str, URIRef] = {}
    for cls in ENTITY_CLASSES.values():
        for uri in uri_subjects(graph, RDF.type, cls):
            for name in [*graph.objects(uri, RDFS.label), *graph.objects(uri, SKOS.altLabel)]:
                index.setdefault(str(name).replace(" ", ""), uri)
    return index
