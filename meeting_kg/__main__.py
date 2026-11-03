"""명령줄 사용법:

python -m meeting_kg build [--refresh] [--offline]   회의록 → 그래프 (output/graph.ttl)
python -m meeting_kg extract samples/xxx.txt         회의록 하나만 추출해서 JSON 출력 (저장 안 함)
python -m meeting_kg validate                        SHACL 검증
python -m meeting_kg infer                           추론 전후 비교
python -m meeting_kg query [이름|--list|--file x.rq] [--no-inference]
"""

import argparse
import sys
from pathlib import Path

from rdflib import RDF, Graph, URIRef
from rdflib.query import Result, ResultRow

from .config import ONT, QUERIES_DIR, ROOT
from .pipeline import build, infer, load_graph, load_ttl, validate


def cmd_build(args: argparse.Namespace) -> None:
    graph = build(refresh=args.refresh, offline=args.offline)
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
    if not rows:
        print("(결과 없음)\n")
        return

    def width(s: str) -> int:  # 한글은 터미널에서 두 칸을 차지
        return sum(2 if ord(ch) > 0x1100 else 1 for ch in s)

    def clip(s: str, limit: int = 60) -> str:
        out, w = "", 0
        for ch in s.replace("\n", " "):
            w += width(ch)
            if w > limit:
                return out + "…"
            out += ch
        return out

    rows = [[clip(c) for c in r] for r in rows]
    widths = [max(width(h), *(width(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def pad(s: str, w: int) -> str:
        return s + " " * (w - width(s))

    print(" | ".join(pad(h, w) for h, w in zip(headers, widths, strict=True)))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(" | ".join(pad(c, w) for c, w in zip(r, widths, strict=True)))
    print(f"({len(rows)}행)\n")


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m meeting_kg", description="회의록 → 온톨로지 지식 그래프")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="회의록을 추출해 그래프 생성")
    p.add_argument("--refresh", action="store_true", help="저장된 추출 결과를 무시하고 LLM을 다시 호출")
    p.add_argument("--offline", action="store_true", help="LLM을 호출하지 않고 저장된 추출 결과만 사용")
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
