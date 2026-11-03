"""회의록 → (Upstage Solar LLM) → MeetingExtraction JSON."""

import datetime as dt
import json
from pathlib import Path

from openai import OpenAI

from .catalog import Record
from .config import UPSTAGE_API_KEY, UPSTAGE_BASE_URL, UPSTAGE_MODEL
from .models import MeetingExtraction
from .transcript import Transcript

SYSTEM_PROMPT = """\
당신은 회의록에서 업무 지식을 뽑아 지식 그래프에 넣는 분석가입니다.
회의록을 읽고 주어진 JSON 스키마에 맞춰 정보를 추출하세요.

[엔티티 ID 규칙]
- 사람·부서·고객사·서비스·기능은 반드시 '엔티티 카탈로그'의 id를 사용합니다.
  회의에서는 별칭("민수 님", "가온 쪽", "Docs")으로 불리므로 aliases를 참고해 연결하세요.
- 카탈로그에 정말 없는 대상(새 기능, 처음 등장한 사람 등)만 new_entities에 추가하고
  'new:'로 시작하는 임시 ID를 만들어 다른 항목에서 그 ID로 참조합니다.
- 카탈로그에 없는 ID를 지어내지 마세요. id는 카탈로그에 적힌 문자열을 한 글자도 바꾸지 말고 그대로 복사합니다.
- relates_to, concerns, affects에는 엔티티 id나 할 일·요청·이슈의 id만 넣습니다 (지식 메모나 결정은 참조 불가).

[항목 분류 규칙]
- action_items: 우리 회사 직원·부서가 하기로 한 일. assignees에는 직원(Employee) 또는 부서(Department)만 넣습니다.
  고객사 담당자가 하는 일은 넣지 않습니다.
- customer_requests: 고객사가 원하거나 요청한 기능·변경 사항.
- issues: 장애, 버그, 불만처럼 해결이 필요한 문제. 고객이 장애 해결을 요청해도 customer_requests가 아니라 issues에만 넣습니다.
- decisions: 방식·방침·일정처럼 회의에서 확정된 선택. "~하겠습니다" 같은 약속은 결정이 아니라 할 일입니다.
  일정(데모, 방문, 미팅 등)이 확정되면 decisions와 함께, 그 일정을 준비·진행할 담당자의 action_items도 만듭니다.
- knowledge: 할 일이 아닌, 오래 유지되는 사실 (고객사의 제약 조건, 규모, 정책, 서비스 특징, 로드맵 등).
- 한 발언이 여러 종류에 해당할 수 있습니다. 예: 고객이 기능을 요청하고 우리 직원이 검토를 약속했다면
  customer_requests 1개 + action_items 1개.
- requested_by에는 고객 담당자가 아니라 고객사(Customer) id를 넣습니다.

[기존 항목과 히스토리] ← 가장 중요
- 먼저 '기존 추적 항목' 목록을 확인하세요. 그 목록에 있는 일이 다시 언급되면(진행, 완료, 지연, 기한 변경)
  새 항목을 만들지 말고 updates에 existing_id와 현재 상태를 넣습니다.
  예) 지난 회의의 할 일 "견적서를 금요일까지 보낸다" + 이번 회의 "견적서는 지난 금요일에 보냈습니다"
      → updates: {existing_id: 그 할 일, status: done}
  예) 지난 회의의 고객 요청 "SSO 연동" + 이번 회의 "개발은 제가 맡아서 11월 13일까지 하겠습니다"
      → updates: {existing_id: 그 요청, status: in_progress} 그리고 새 action_items: SSO 개발
  예) 지난 회의의 할 일 "기술 검토 후 결과 공유" + 이번 회의 "검토 끝났습니다"
      → updates: {existing_id: 그 할 일, status: done}. 이후의 개발 작업은 별도의 새 action_items.
- updates에 넣은 항목과 같은 일을 action_items, customer_requests, issues에 다시 만들지 마세요.
- 같은 existing_id는 updates에 한 번만 넣습니다.
- 상태: 완료 done, 진행 중 in_progress, 막혀 있거나 미뤄짐 blocked, 새로 생김 open.
- 새 할 일·요청·이슈에는 ref에 'new:' 임시 ID를 붙입니다. 같은 응답의 다른 항목(relates_to 등)에서
  그 임시 ID로 서로 연결할 수 있습니다. 기존 항목은 그 id를 그대로 씁니다.

[날짜]
- due_date는 YYYY-MM-DD 형식입니다. "이번 주 금요일", "다음 주 화요일", "오늘" 같은 표현은
  회의 일자와 요일을 기준으로 계산하세요. 기한이 언급되지 않았으면 null.

[출처]
- evidence에는 근거가 된 발언을 회의록에서 그대로 복사해 넣습니다 (화자 이름 포함, 타임스탬프 제외).
- confidence는 해석이 명확하면 0.9 이상, 추측이 섞이면 낮게 줍니다.
- 모든 설명(description, statement, summary)은 한국어로 간결하게 씁니다.
"""


def build_user_prompt(transcript: Transcript, catalog: list[Record], tracked: list[Record]) -> str:
    return f"""\
# 회의 정보
- 제목: {transcript.title}
- 회의 일자: {transcript.date.isoformat()} ({transcript.weekday}요일)
- 참석자(헤더): {", ".join(transcript.participants)}

# 엔티티 카탈로그
{json.dumps(catalog, ensure_ascii=False, indent=1)}

# 기존 추적 항목 (이전 회의에서 생긴, 아직 끝나지 않은 할 일·요청·이슈)
{json.dumps(tracked, ensure_ascii=False, indent=1) if tracked else "(없음)"}

# 회의록
{transcript.body}
"""


def call_llm(transcript: Transcript, catalog: list[Record], tracked: list[Record]) -> MeetingExtraction:
    if not UPSTAGE_API_KEY:
        raise RuntimeError("UPSTAGE_API_KEY가 없습니다. .env 파일을 만들거나 --offline 옵션을 사용하세요.")

    client = OpenAI(api_key=UPSTAGE_API_KEY, base_url=UPSTAGE_BASE_URL)
    completion = client.chat.completions.parse(
        model=UPSTAGE_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(transcript, catalog, tracked)},
        ],
        response_format=MeetingExtraction,
        temperature=0,
    )
    message = completion.choices[0].message
    if message.parsed is None:
        raise RuntimeError(f"LLM 응답을 해석하지 못했습니다: {message.refusal or message.content}")
    return message.parsed


def cache_path(transcript: Transcript, directory: Path) -> Path:
    return directory / f"{transcript.path.stem}.json"


def save_extraction(transcript: Transcript, extraction: MeetingExtraction, directory: Path) -> Path:
    path = cache_path(transcript, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "source": f"samples/{transcript.path.name}",
        "model": UPSTAGE_MODEL,
        "extracted_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "result": extraction.model_dump(),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_extraction(transcript: Transcript, directory: Path) -> tuple[MeetingExtraction, str] | None:
    path = cache_path(transcript, directory)
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    return MeetingExtraction.model_validate(record["result"]), record.get("model", "unknown")
