"""전체 흐름: 기준 데이터 로드 → 회의록마다 추출·변환 → 저장 → 검증 → 추론."""

from collections.abc import Callable
from pathlib import Path

import owlrl
from pyshacl import validate as shacl_validate
from rdflib import Graph

from .catalog import build_entity_catalog, build_tracked_items
from .config import (
    EXTRACTED_DIR,
    GRAPH_FILE,
    REFERENCE_FILE,
    ROOT,
    SAMPLES_DIR,
    SCHEMA_FILE,
    SHAPES_FILE,
    UPSTAGE_MODEL,
    bind_prefixes,
)
from .extract import call_llm, load_extraction, save_extraction
from .to_rdf import apply_extraction
from .transcript import list_transcripts


def load_ttl(*paths: Path) -> Graph:
    g = bind_prefixes(Graph())
    for path in paths:
        g.parse(path, format="turtle")
    return g


def build(
    refresh: bool = False,
    offline: bool = False,
    extracted_dir: Path = EXTRACTED_DIR,
    graph_file: Path = GRAPH_FILE,
    log: Callable[[str], None] = print,
) -> Graph:
    """회의록을 날짜순으로 처리해 그래프를 만든다.

    앞 회의에서 생긴 할 일이 다음 회의의 '기존 추적 항목'으로 LLM에 전달되므로
    반드시 날짜순으로 처리해야 히스토리가 이어진다.
    """
    graph = load_ttl(REFERENCE_FILE)

    for transcript in list_transcripts(SAMPLES_DIR):
        cached = None if refresh else load_extraction(transcript, extracted_dir)
        if cached:
            extraction, model = cached
            log(f"[cache] {transcript.path.name}")
        elif offline:
            log(f"[skip ] {transcript.path.name} (추출 결과 없음, --offline)")
            continue
        else:
            log(f"[LLM  ] {transcript.path.name} 추출 중...")
            extraction = call_llm(transcript, build_entity_catalog(graph), build_tracked_items(graph))
            model = UPSTAGE_MODEL
            save_extraction(transcript, extraction, extracted_dir)

        warnings = apply_extraction(graph, transcript, extraction, model)
        log(
            f"        할 일 {len(extraction.action_items)}, 요청 {len(extraction.customer_requests)}, "
            f"이슈 {len(extraction.issues)}, 결정 {len(extraction.decisions)}, 지식 {len(extraction.knowledge)}"
        )
        for warning in warnings:
            log(f"        ⚠ {warning}")

    graph_file.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(graph_file, format="turtle")
    shown = graph_file.relative_to(ROOT) if graph_file.resolve().is_relative_to(ROOT) else graph_file
    log(f"저장: {shown} ({len(graph)} 트리플)")
    return graph


def load_graph() -> Graph:
    if not GRAPH_FILE.exists():
        raise FileNotFoundError("output/graph.ttl이 없습니다. 먼저 `python -m meeting_kg build`를 실행하세요.")
    return load_ttl(GRAPH_FILE)


def validate(graph: Graph) -> tuple[bool, str]:
    # 스키마를 함께 넣어야 SHACL이 rdfs:subClassOf와 상태 값(ont:Done 등)의 타입을 안다
    data = load_ttl(SCHEMA_FILE)
    data += graph
    conforms, _, report = shacl_validate(
        data_graph=data,
        shacl_graph=load_ttl(SHAPES_FILE),
        ont_graph=load_ttl(SCHEMA_FILE),
        inference="none",  # 추론 없이 저장된 그대로 검사 (이유는 shapes.ttl 주석 참고)
        abort_on_first=False,
    )
    return bool(conforms), str(report)


def infer(graph: Graph) -> Graph:
    """스키마 + 데이터에 OWL 2 RL 규칙을 적용해 추론된 트리플을 추가한 새 그래프."""
    inferred = load_ttl(SCHEMA_FILE)
    inferred += graph
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(inferred)
    return inferred
