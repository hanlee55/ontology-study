"""회의록 텍스트 파일 읽기.

형식:
    제목: ...
    일시: 2026-10-13 (화) 14:00
    참석자: 김민수, 이서연, ...
    ---
    [00:00:04] 김민수: 발언 내용
"""

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

WEEKDAYS = "월화수목금토일"


@dataclass
class Transcript:
    path: Path
    title: str
    date: dt.date
    participants: list[str]
    header: dict[str, str]
    body: str

    @property
    def meeting_id(self) -> str:
        return f"meeting-{self.path.stem}"

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.date.weekday()]


def load_transcript(path: Path) -> Transcript:
    text = path.read_text(encoding="utf-8")
    head, sep, body = text.partition("\n---\n")
    if not sep:
        raise ValueError(f"{path}: 헤더와 본문을 구분하는 '---' 줄이 없습니다")

    header = {}
    for line in head.splitlines():
        key, colon, value = line.partition(":")
        if colon:
            header[key.strip()] = value.strip()

    match = re.search(r"\d{4}-\d{2}-\d{2}", header.get("일시", ""))
    if not match:
        raise ValueError(f"{path}: '일시: YYYY-MM-DD ...' 헤더가 필요합니다")

    participants = [p.strip() for p in header.get("참석자", "").split(",") if p.strip()]
    return Transcript(
        path=path,
        title=header.get("제목", path.stem),
        date=dt.date.fromisoformat(match.group()),
        participants=participants,
        header=header,
        body=body.strip(),
    )


def list_transcripts(directory: Path) -> list[Transcript]:
    transcripts = [load_transcript(p) for p in directory.glob("*.txt")]
    return sorted(transcripts, key=lambda t: (t.date, t.path.name))
