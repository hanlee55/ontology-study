"""터미널용 표 출력 (한글 폭을 고려한 정렬)."""

from collections.abc import Sequence


def display_width(s: str) -> int:
    """한글 등 전각 문자는 터미널에서 두 칸을 차지한다."""
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in s)


def clip(s: str, limit: int) -> str:
    out, w = "", 0
    for ch in s.replace("\n", " "):
        w += display_width(ch)
        if w > limit:
            return out + "…"
        out += ch
    return out


def print_rows(headers: Sequence[str], rows: Sequence[Sequence[str]], limit: int = 60) -> None:
    if not rows:
        print("(결과 없음)\n")
        return

    clipped = [[clip(cell, limit) for cell in row] for row in rows]
    widths = [max(display_width(h), *(display_width(r[i]) for r in clipped)) for i, h in enumerate(headers)]

    def pad(s: str, w: int) -> str:
        return s + " " * (w - display_width(s))

    print(" | ".join(pad(h, w) for h, w in zip(headers, widths, strict=True)))
    print("-+-".join("-" * w for w in widths))
    for r in clipped:
        print(" | ".join(pad(c, w) for c, w in zip(r, widths, strict=True)))
    print(f"({len(rows)}행)\n")
