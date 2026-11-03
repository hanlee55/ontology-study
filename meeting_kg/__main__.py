"""명령줄 사용법:

python -m meeting_kg build [--refresh] [--offline]   회의록 → 그래프 (output/graph.ttl)
python -m meeting_kg extract samples/xxx.txt         회의록 하나만 추출해서 JSON 출력 (저장 안 함)
python -m meeting_kg validate                        SHACL 검증
python -m meeting_kg infer                           추론 전후 비교
python -m meeting_kg query [이름|--list|--file x.rq] [--no-inference]
python -m meeting_kg evaluate [--verbose] [--json result.json]   정답지 기준 채점
python -m meeting_kg check [--timeline]              wirelog 규칙으로 모순·이상 징후 점검
"""

import argparse
import json
import sys
from pathlib import Path

from rdflib import RDF, Graph, URIRef
from rdflib.query import Result, ResultRow

from .config import ANSWER_KEY_FILE, EXTRACTED_DIR, GRAPH_FILE, ONT, QUERIES_DIR, ROOT
from .pipeline import build, infer, load_graph, load_ttl, validate
from .table import clip, print_rows


def cmd_build(args: argparse.Namespace) -> None:
    graph = build(
        refresh=args.refresh,
        offline=args.offline,
        extracted_dir=Path(args.extracted_dir),
        graph_file=Path(args.output),
    )
    conforms, _ = validate(graph)
    print("SHACL 검증:", "통과" if conforms else "위반 있음 (python -m meeting_kg validate 로 상세 확인)")


def cmd_extract(args: argparse.Namespace) -> None:
    from .catalog import build_entity_catalog, build_tracked_items
    from .config import REFERENCE_FILE
    from .extract import call_llm
    from .transcript import load_transcript

    graph = load_ttl(REFERENCE_FILE)
    extraction = call_llm(load_transcript(Path(args.file)), build_entity_catalog(graph), build_tracked_items(graph))
    print(extraction.model_dump_json(indent=2))


def cmd_validate(args: argparse.Namespace) -> None:
    conforms, report = validate(load_graph())
    print(report)
    sys.exit(0 if conforms else 1)


def cmd_infer(args: argparse.Namespace) -> None:
    graph = load_graph()
    inferred = infer(graph)

    def count(g: Graph, cls: URIRef) -> int:
        return len(set(g.subjects(RDF.type, cls)))

    print(f"저장된 트리플: {len(graph)}  →  스키마+추론 후: {len(inferred)}\n")
    print(f"{'클래스':<16}{'추론 전':>8}{'추론 후':>8}")
    for name in ["Person", "Agent", "Organization", "TrackedItem", "ExtractedItem"]:
        print(f"{name:<16}{count(graph, ONT[name]):>8}{count(inferred, ONT[name]):>8}")

    print("\n추론으로 새로 생긴 관계 예시:")
    for prop in ["hasMember", "responsibleFor", "hasUpdate", "usedBy", "hasAccountManager"]:
        before = len(list(graph.triples((None, ONT[prop], None))))
        after = len(list(inferred.triples((None, ONT[prop], None))))
        print(f"  ont:{prop:<18} {before:>3} → {after:>3}")
    before = len(list(graph.triples((None, ONT.subOrganizationOf, None))))
    after = len(list(inferred.triples((None, ONT.subOrganizationOf, None))))
    print(f"  ont:{'subOrganizationOf':<18} {before:>3} → {after:>3}  (전이 관계)")


def read_query(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    title = next(
        (line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("# title:")), path.stem
    )
    return title, text


def print_table(result: Result) -> None:
    headers = [str(v) for v in result.vars or []]
    rows = [["" if cell is None else str(cell) for cell in row] for row in result if isinstance(row, ResultRow)]
    print_rows(headers, rows)


def cmd_query(args: argparse.Namespace) -> None:
    files = sorted(QUERIES_DIR.glob("*.rq"))
    if args.list:
        for f in files:
            print(f"{f.stem:<32} {read_query(f)[0]}")
        return

    if args.file:
        targets = [Path(args.file)]
    elif args.name:
        targets = [f for f in files if f.stem.startswith(args.name) or args.name in f.stem]
        if not targets:
            sys.exit(f"'{args.name}'에 해당하는 질의가 없습니다. --list 로 목록을 확인하세요.")
    else:
        targets = files

    graph = load_graph()
    if not args.no_inference:
        graph = infer(graph)
    for path in targets:
        title, text = read_query(path)
        print(f"■ {title}  ({path.relative_to(ROOT) if path.is_relative_to(ROOT) else path})")
        print_table(graph.query(text))


def cmd_evaluate(args: argparse.Namespace) -> None:
    from .evaluate import evaluate, evaluation_to_dict, load_answer_key

    graph = load_ttl(Path(args.graph)) if args.graph else load_graph()
    result = evaluate(graph, load_answer_key(Path(args.key)))

    correct, total = result.score
    print(f"■ 총점: {correct}/{total} ({correct / total:.1%})\n")
    rows = [[name, str(c), str(t), f"{c / t:.0%}" if t else "-"] for name, (c, t) in result.summary().items()]
    print_rows(["범주", "맞음", "전체", "비율"], rows)

    print("■ 추적 항목 (✔ 맞음, ✘ 틀림, · 선택 항목)")
    item_rows = []
    for r in result.tracked + result.facts:
        failed = [c for c in r.checks if not c.ok]
        if not args.verbose and not failed:
            continue
        mark = "·" if r.key.optional else ("✔" if not failed else "✘")
        if r.match is None:
            detail = "그래프에서 찾지 못함"
        else:
            shown = failed if failed else r.checks[1:]  # 첫 체크(항목 찾기)는 그래프 항목 칸에 이미 나타남
            detail = "; ".join(f"{c.category} 기대 {c.expected} / 실제 {c.actual}" for c in shown)
        item_rows.append([mark, r.key.id, r.key.summary, r.match.id if r.match else "-", detail])
    print_rows(["", "정답", "내용", "그래프 항목", "틀린 체크"], item_rows, limit=70)

    print(f"■ 중복 등록 {len(result.duplicates)}건 (이미 매칭된 정답과 같은 내용의 항목)")
    print_rows(["그래프 항목", "정답", "설명"], [[i.id, k.id, i.description] for i, k in result.duplicates], limit=70)
    print(f"■ 정답지에 없는 항목 {len(result.extras)}건")
    print_rows(["그래프 항목", "종류", "설명"], [[i.id, i.kind, i.description] for i in result.extras], limit=70)

    if args.json:
        Path(args.json).write_text(json.dumps(evaluation_to_dict(result), ensure_ascii=False, indent=2) + "\n")
        print(f"JSON 저장: {args.json}")


def cmd_check(args: argparse.Namespace) -> None:
    from .catalog import label_of
    from .config import EX
    from .rules import CHECKS, run_checks, run_timeline

    graph = load_ttl(Path(args.graph)) if args.graph else load_graph()

    def show(value: object) -> str:
        """항목·회의 ID에는 설명이나 제목을, 날짜 정수에는 날짜 형식을 붙인다."""
        if isinstance(value, int):
            text = str(value)
            if len(text) == 8:
                return f"{text[:4]}-{text[4:6]}-{text[6:]}"
            if len(text) == 9:
                return f"{text[:4]}-{text[4:6]}-{text[6:8]} #{text[8]}"
            return text
        uri = EX[str(value)]
        if str(value).startswith("meeting-") or (uri, ONT.description, None) in graph:
            return f"{value} {clip(label_of(graph, uri), 30)}"
        return str(value)

    if args.timeline:
        names = ["current_status", *CHECKS]
        current = None
        rows: list[list[str]] = []
        for delta in run_timeline(graph, names):
            if delta.meeting != current:
                if rows:
                    print_rows(["", "관계", "내용"], rows, limit=90)
                current, rows = delta.meeting, []
                print(f"■ {delta.date} {show(delta.meeting)}")
            sign = "+" if delta.diff > 0 else "-"
            rows.append([sign, delta.relation, " / ".join(show(v) for v in delta.row)])
        print_rows(["", "관계", "내용"], rows, limit=90)
        return

    results = run_checks(graph)
    for name, (description, headers) in CHECKS.items():
        found = results[name]
        print(f"■ {description}: {len(found)}건  ({name})")
        if found:
            print_rows(headers, [[show(v) for v in row] for row in found], limit=60)
        else:
            print()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m meeting_kg", description="회의록 → 온톨로지 지식 그래프")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="회의록을 추출해 그래프 생성")
    p.add_argument("--refresh", action="store_true", help="저장된 추출 결과를 무시하고 LLM을 다시 호출")
    p.add_argument("--offline", action="store_true", help="LLM을 호출하지 않고 저장된 추출 결과만 사용")
    p.add_argument("--extracted-dir", default=str(EXTRACTED_DIR), help="추출 결과 JSON 폴더 (기본: extracted/)")
    p.add_argument("--output", default=str(GRAPH_FILE), help="그래프 저장 파일 (기본: output/graph.ttl)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("extract", help="회의록 하나를 추출해 JSON으로 출력")
    p.add_argument("file")
    p.set_defaults(func=cmd_extract)

    sub.add_parser("validate", help="SHACL 검증").set_defaults(func=cmd_validate)
    sub.add_parser("infer", help="추론 전후 비교").set_defaults(func=cmd_infer)

    p = sub.add_parser("query", help="SPARQL 질의 실행")
    p.add_argument("name", nargs="?", help="질의 파일 이름 (예: 01, timeline). 생략하면 전부 실행")
    p.add_argument("--list", action="store_true", help="질의 목록")
    p.add_argument("--file", help="임의의 .rq 파일 실행")
    p.add_argument("--no-inference", action="store_true", help="추론 없이 저장된 트리플만으로 질의")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("evaluate", help="정답지 기준으로 추출 정확도 채점")
    p.add_argument("--key", default=str(ANSWER_KEY_FILE), help="정답지 TOML (기본: samples/answer_key.toml)")
    p.add_argument("--graph", help="채점할 그래프 .ttl (기본: output/graph.ttl)")
    p.add_argument("--verbose", action="store_true", help="맞은 항목도 모두 출력")
    p.add_argument("--json", help="결과를 JSON 파일로 저장 (실행 간 비교용)")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("check", help="wirelog 규칙으로 모순·이상 징후 점검 (rules/checks.dl)")
    p.add_argument("--graph", help="점검할 그래프 .ttl (기본: output/graph.ttl)")
    p.add_argument("--timeline", action="store_true", help="회의를 하나씩 넣으며 증분 계산한 변경 내역 출력")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
