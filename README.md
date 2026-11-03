# ontology-study

회의록·전사 스크립트를 LLM(Upstage Solar)으로 분석해 **RDF/OWL 온톨로지 기반 지식 그래프**를 만드는 학습용 프로토타입입니다.

회의록에서 다음 지식을 뽑아 저장합니다.

- **서비스 지식**: 서비스와 기능, 특징, 로드맵
- **고객사 지식**: 사용 서비스, 제약 조건, 규모, 요청 사항, 이슈
- **사람·부서별 업무**: 누가 무엇을 언제까지 하는지, 상태가 회의마다 어떻게 바뀌었는지(히스토리)

모든 사실에는 **출처 회의, 근거 발언(원문 인용), 추출 신뢰도, 추출 모델**이 붙습니다.

> `samples/`의 회의록, 회사·사람·고객사 이름은 모두 학습용 **가상 데이터**입니다.
> 회의록은 서브 에이전트가 `data/reference.ttl`을 바탕으로 작성했고, 기대하는 추출 결과(정답지)는 `samples/answer_key.toml`에 있습니다.

## 전체 흐름

```
samples/*.txt (회의록)
    │  ① 날짜순으로 하나씩
    ▼
meeting_kg/extract.py   Upstage Solar(solar-pro4) + JSON 스키마 강제 출력
    │  - 엔티티 카탈로그(조직도·고객사·서비스, 별칭 포함)를 함께 전달 → ID로 연결
    │  - 이전 회의에서 생긴 미완료 항목 목록을 함께 전달 → 기존 항목 갱신(히스토리)
    ▼
extracted/*.json        추출 결과 캐시 (API 키 없이도 재현 가능)
    │
    ▼
meeting_kg/to_rdf.py    JSON → RDF 트리플
    │  - ID 보정 (이름·별칭·비슷한 ID를 정식 ID로)
    │  - 중복 병합 (LLM이 기존 항목을 새 항목으로 또 만든 경우)
    │  - 상태 변경은 StatusUpdate 이벤트로 기록
    ▼
output/graph.ttl        지식 그래프 (Turtle)
    │
    ├─▶ SHACL 검증 (ontology/shapes.ttl)
    ├─▶ OWL 2 RL 추론 (ontology/schema.ttl + owlrl)
    ├─▶ SPARQL 질의 (queries/*.rq)
    ├─▶ wirelog 규칙 점검 (rules/checks.dl): 이벤트로 현재 상태 계산, 모순·이상 징후 탐지
    └─▶ 정답지 채점 (samples/answer_key.toml)
```

## 디렉터리 구조

| 경로 | 내용 |
|---|---|
| `ontology/schema.ttl` | 온톨로지 스키마 (클래스, 속성, 상하위·역관계·전이 관계, 서로소 클래스) |
| `ontology/shapes.ttl` | SHACL 데이터 품질 규칙 |
| `data/reference.ttl` | 기준 데이터: 조직도, 직원, 서비스·기능, 고객사·고객 담당자, 별칭 |
| `samples/` | 가상 회의록 4개 (2026-10-06 ~ 10-27)와 정답지 `answer_key.toml` |
| `extracted/` | LLM 추출 결과(JSON) 캐시 |
| `output/graph.ttl` | 생성된 지식 그래프 |
| `queries/` | 예제 SPARQL 질의 |
| `rules/checks.dl` | wirelog Datalog 점검 규칙 |
| `meeting_kg/` | Python 코드 |
| `pyproject.toml`, `uv.lock` | 의존성 (uv로 관리) |
| `ruff.toml`, `mypy.ini` | 린터·포맷터, 타입 검사 설정 |

## 설치

Python 3.14와 [uv](https://docs.astral.sh/uv/)를 사용합니다.

```bash
uv sync          # .python-version(3.14)에 맞는 Python과 의존성을 설치
```

LLM을 호출하려면 `.env` 파일에 Upstage API 키를 넣습니다. (`.env`는 `.gitignore`에 포함되어 커밋되지 않습니다)

```bash
cp .env.example .env
# .env 파일을 열어 UPSTAGE_API_KEY 입력
```

의존성 추가·삭제는 `pyproject.toml`을 직접 고치지 말고 uv 명령을 사용합니다.

```bash
uv add <패키지>          # 실행 의존성
uv add --dev <패키지>    # 개발 도구
uv remove <패키지>
```

## 사용법

```bash
# 회의록 → 그래프 생성 (캐시가 있으면 LLM을 호출하지 않음)
uv run python -m meeting_kg build

# API 키 없이 저장된 추출 결과만으로 생성
uv run python -m meeting_kg build --offline

# 캐시를 무시하고 LLM으로 전부 다시 추출
uv run python -m meeting_kg build --refresh

# 회의록 하나만 추출해서 JSON 확인 (저장 안 함)
uv run python -m meeting_kg extract samples/2026-10-06_gaon-weekly-sso.txt

# SHACL 검증 결과 상세 출력
uv run python -m meeting_kg validate

# 추론 전후 비교
uv run python -m meeting_kg infer

# SPARQL 질의
uv run python -m meeting_kg query --list          # 목록
uv run python -m meeting_kg query                 # 전부 실행
uv run python -m meeting_kg query 04              # 이름 일부로 하나만 실행
uv run python -m meeting_kg query --file my.rq    # 직접 작성한 질의 실행
uv run python -m meeting_kg query 02 --no-inference   # 추론 없이 실행 (결과 비교용)

# 정답지 기준 채점
uv run python -m meeting_kg evaluate              # 총점, 범주별 점수, 틀린 항목
uv run python -m meeting_kg evaluate --verbose    # 맞은 항목까지 모두

# wirelog 규칙 점검
uv run python -m meeting_kg check                 # 모순·이상 징후 목록
uv run python -m meeting_kg check --timeline      # 회의를 하나씩 넣으며 회의별 변경 내역
```

새 회의록은 `samples/`에 같은 형식으로 추가하고 `build`를 실행하면 됩니다.

```
제목: 회의 제목
일시: 2026-11-03 (화) 10:00
참석자: 김민수, 이서연, 한도윤(가온물산)
---
[00:00:04] 김민수: 발언 내용
[00:00:15] 한도윤: 발언 내용
```

## 코드 품질 도구

```bash
uv run ruff format .      # 포맷
uv run ruff check .       # 린트 (--fix 로 자동 수정)
uv run mypy               # 타입 검사 (strict)
```

## 온톨로지 설계

### 주요 클래스

```
Agent ─┬─ Person ─┬─ Employee          (우리 직원)
       │          └─ CustomerContact   (고객 담당자)
       └─ Organization ─┬─ Department
                        └─ Customer
Service, Feature
Meeting
ExtractedItem ─┬─ TrackedItem ─┬─ ActionItem       (할 일)
               │               ├─ CustomerRequest  (고객 요청)
               │               └─ Issue            (이슈)
               ├─ Decision      (결정사항)
               └─ KnowledgeNote (지식 메모)
StatusUpdate   (상태 변경 이력)
Status: Open / InProgress / Blocked / Done / Cancelled
```

### 히스토리 표현

`TrackedItem`의 `ont:status`는 **현재 상태 하나만** 가집니다. 상태나 기한이 바뀔 때마다 `StatusUpdate` 이벤트를 새로 만들기 때문에, 현재 상태가 덮어써져도 과거 이력이 남습니다.

```turtle
ex:ai-20261006-03 a ont:ActionItem ;
    ont:description "SSO 엔터프라이즈 옵션 별도 견적서를 이번 주 금요일까지 정리하여 메일로 발송한다" ;
    ont:assignedTo ex:emp-kim-minsu ;
    ont:status ont:Done .                     # 현재 상태

ex:upd-ai-20261006-03-20261006 a ont:StatusUpdate ;
    ont:updateOf ex:ai-20261006-03 ; ont:newStatus ont:Open ;
    ont:newDueDate "2026-10-10"^^xsd:date ;
    ont:recordedIn ex:meeting-2026-10-06_gaon-weekly-sso .

ex:upd-ai-20261006-03-20261020 a ont:StatusUpdate ;
    ont:updateOf ex:ai-20261006-03 ; ont:newStatus ont:Done ;
    ont:recordedIn ex:meeting-2026-10-20_internal-dev-sync ;
    ont:evidence "이서연: 민수 님 오늘 외근이라 대신 전달하면, 견적서도 지난 금요일에..." .
```

### 추론으로 얻는 것 (`uv run python -m meeting_kg infer`)

데이터에는 최소한의 사실만 저장하고, 나머지는 스키마 규칙으로 추론합니다.

| 규칙 | 저장된 사실 | 추론된 사실 |
|---|---|---|
| `rdfs:subClassOf` | 김민수 a Employee | 김민수 a Person, Agent |
| `owl:inverseOf` | 할 일 assignedTo 박지훈 | 박지훈 responsibleFor 할 일 |
| `owl:inverseOf` | 박지훈 memberOf 플랫폼팀 | 플랫폼팀 hasMember 박지훈 |
| `owl:TransitiveProperty` | 플랫폼팀 → 개발본부 → 누리클라우드 | 플랫폼팀 subOrganizationOf 누리클라우드 |
| `rdfs:domain` / `range` | 요청 requestedBy 가온물산 | 가온물산 a Customer |

`queries/02_dev_hq_rollup.rq`는 저장되지 않은 `hasMember`, `responsibleFor`를 사용하므로 `--no-inference`로 실행하면 결과가 비어 있습니다.

### SHACL 검증과 "열린 세계 가정"

OWL은 열린 세계 가정을 따르기 때문에 "할 일에 담당자가 없다"는 것을 오류로 보지 않습니다. 이런 데이터 품질 규칙은 SHACL로 검사합니다.

**주의할 점**: 검증은 OWL 추론 **전의** 데이터에 대해 해야 합니다. 추론을 먼저 하면 `rdfs:range` 규칙 때문에 잘못 들어간 값도 그 클래스로 추론되어(예: `requestedBy`에 고객 담당자를 넣으면 "그 사람은 Customer다") `sh:class` 검사가 항상 통과합니다. 개발 중에 실제로 겪은 문제입니다.

## LLM 추출을 믿을 수 있게 만드는 장치

LLM 출력은 매번 조금씩 다르고 실수도 있습니다. 이 프로젝트에서는 다음 장치를 사용합니다.

1. **스키마는 사람이 설계**하고, LLM은 JSON 스키마(`meeting_kg/models.py`)에 맞춰 채우기만 합니다.
2. **엔티티 카탈로그** 제공: "민수 님", "가온 쪽", "Docs" 같은 별칭을 정식 ID로 연결하게 합니다.
3. **기존 미완료 항목 목록** 제공: 같은 일을 새로 만들지 않고 상태를 갱신하게 합니다.
4. **ID 보정** (`IdResolver`): ID 대신 이름을 쓰거나(`"박지훈"`), 비슷한 ID를 지어낸 경우(`emp-cs-yuna` → `emp-choi-yuna`) 바로잡고 경고를 남깁니다.
5. **중복 병합**: 기존 항목과 설명이 거의 같은 새 항목은 기존 항목에 병합합니다.
6. **SHACL 검증**: 담당자가 고객 담당자인 경우, 출처가 없는 경우 등을 잡아냅니다.
7. **근거 인용과 신뢰도**: 모든 항목을 원문 발언까지 추적할 수 있습니다.

## 추출 정확도 평가

`samples/answer_key.toml`은 사람이 정리한 정답지입니다. `evaluate` 명령은 이를 기준으로 그래프를 채점합니다.

**매칭**: 정답 항목과 그래프 항목은 다음 조건이 모두 맞으면 같은 것으로 봅니다. 띄어쓰기는 무시합니다.
- 같은 종류(할 일·고객 요청·이슈)
- 같은 회의에서 생성
- 설명에 정답지의 키워드가 모두 포함

**채점 단위(체크)**

| 범주 | 체크 내용 |
|---|---|
| 항목 찾기 | 정답 항목이 그래프에 있는가 |
| 담당자 | 정답의 담당자가 모두 들어 있는가 |
| 요청 고객사 | 고객 요청의 요청 고객사가 맞는가 |
| 기한 | 최종 기한이 맞는가 |
| 상태 | 각 회의가 끝난 시점의 상태가 맞는가 (언급이 없던 회의는 직전 상태 유지) |
| 결정, 지식 | 결정사항과 지식 메모를 찾았는가 |

- 항목을 못 찾으면 그 항목의 나머지 체크도 틀린 것으로 셉니다. 그래서 분모(93)는 실행마다 같습니다.
- `optional = true`인 정답(따로 추출해도 되고 안 해도 되는 항목)은 점수에 넣지 않습니다.
- **중복 등록**: 이미 매칭된 정답과 같은 내용인데 다른 회의에서 새로 만들어진 항목입니다. 점수와 별도로 보여 줍니다.
- **정답지에 없는 항목**: 점수와 별도로 보여 줍니다. 잘못 만든 것인지, 정답지에 빠진 것인지는 사람이 확인해야 합니다.

### 프롬프트·모델 비교 방법

커밋된 `extracted/`를 덮어쓰지 않고 실험별 폴더에 저장한 뒤 채점합니다. (`runs/`는 git에서 제외됨)

```bash
uv run python -m meeting_kg build --refresh --extracted-dir runs/exp1/extracted --output runs/exp1/graph.ttl
uv run python -m meeting_kg evaluate --graph runs/exp1/graph.ttl --json runs/exp1/score.json
```

### 현재 결과 (solar-pro4, 같은 프롬프트)

| 실행 | 총점 | 항목 찾기 | 담당자 | 기한 | 상태 | 중복 등록 |
|---|---|---|---|---|---|---|
| 커밋된 `extracted/` | 77/93 (82.8%) | 16/18 | 11/14 | 8/12 | 26/33 | 2 |
| 재추출 1회차 | 85/93 (91.4%) | 17/18 | 13/14 | 10/12 | 30/33 | 1 |
| 재추출 2회차 | 84/93 (90.3%) | 16/18 | 12/14 | 11/12 | 29/33 | 4 |

- **같은 프롬프트라도 실행마다 점수가 8%p 넘게 차이 납니다.** 프롬프트를 비교할 때는 한 번이 아니라 여러 번 실행해 평균을 봐야 합니다.
- **세 번 모두 틀린 것**: 가온물산 SSO 요청(R1)의 진행 → 보류(blocked) → 재개 흐름을 한 번도 끝까지 맞히지 못했습니다.
- **자주 틀린 것**
  - 내부 회의에서 강예린이 "오늘 오후에 회신드리겠다"고 한 할 일(A11)을 재추출 두 번 모두 놓쳤습니다.
  - 상대 날짜 계산: "이번 주 금요일"(10/06 기준 10/09)을 세 번 중 두 번 10/10으로 계산했습니다.

## wirelog 규칙 점검

[wirelog](https://github.com/semantic-reasoning/wirelog)는 C11로 만든 증분(incremental) Datalog 엔진입니다. Python 바인딩 [PyreWire](https://github.com/semantic-reasoning/PyreWire)로 사용합니다.

RDF/OWL은 스키마·저장·질의를 그대로 맡습니다. wirelog는 그 옆에서 **상태 변경 이벤트로 현재 상태를 계산**하고, **사람이 확인해야 할 모순과 이상 징후**를 찾습니다. `meeting_kg/rules.py`가 그래프를 Datalog 사실(관계)로 내보내 `rules/checks.dl`을 실행합니다.

### 규칙

| 규칙 | 찾는 것 |
|---|---|
| `current_status`, `current_due` | 상태·기한 변경 이벤트 중 마지막 것이 이기는 방식(Last-Write-Wins)으로 계산한 현재 값 |
| `status_mismatch`, `due_mismatch` | 그래프에 저장된 현재 값과 이벤트로 계산한 값의 차이 (변환 코드 오류) |
| `status_conflict`, `due_conflict` | 같은 회의 안에서 상태나 기한이 엇갈림 |
| `unattended_change` | 담당자(또는 담당 부서원)가 아무도 참석하지 않은 회의에서 상태·기한이 바뀜 |
| `reopened` | 완료됐던 일이 나중에 다시 열림 |
| `overdue` | 마지막 회의 날짜 기준으로 기한이 지났는데 끝나지 않음 |
| `weekend_due` | 기한이 토·일요일 ("이번 주 금요일" 같은 상대 날짜 계산 오류 가능성) |
| `duplicate_candidate` | 같은 고객사·같은 기능에 대해 다른 회의에서 또 만들어진 요청·이슈 |

규칙 예시 (현재 상태와 불참 회의 변경):

```prolog
last_status_seq(I, max(S)) :- status_event(I, S, _, _).
current_status(I, St) :- last_status_seq(I, S), status_event(I, S, St, _).

unattended_change(I, M) :-
    updated_in(I, M), has_assignee(I), !created_in(I, M), !assignee_present(I, M).
```

`check --timeline`은 회의를 하나씩 넣고 `step()`으로 증분 계산합니다. 그래서 각 회의가 **바꾼 결과만** 나옵니다. 예를 들어 2차 회의 시점에 기한이 지났던 견적서 할 일은 3차 회의에서 완료가 보고되면 `overdue`에서 빠집니다.

### 효과: 채점기가 찾은 실제 오류를 정답지 없이 미리 표시하는가

커밋된 결과와 재추출 2회, 세 그래프에서 채점 결과(`evaluate`)와 대조했습니다.

| 실제 오류 (채점기 기준) | 잡은 규칙 | 결과 |
|---|---|---|
| "이번 주 금요일"을 10/10(토)로 계산 | `weekend_due` | 이 오류가 있던 그래프 2개 모두에서 잡음 |
| SSO 기술 검토가 관계없는 다솜병원 회의에서 갱신됨 (기한 10/15 오류) | `unattended_change` | 잡음 |
| 보안 검토 기한이 한 회의 안에서 11/13 → 10/30으로 엇갈림 | `due_conflict` | 잡음 |
| SSO 요청이 한 회의 안에서 "진행 중"과 "보류"로 함께 기록됨 | `status_conflict` | 잡음 (run1) |
| 고객 요청 중복 등록 4건 | `duplicate_candidate` | 3건 잡음 |
| 할 일·이슈 중복 등록 3건 | (대상 아님) | 못 잡음 |
| 할 일 자체를 놓침 (A11, A13 등) | (없는 것은 규칙으로 못 찾음) | 못 잡음 |

**오탐(정상인데 표시된 것)도 있습니다.** 그래서 이 결과는 자동 수정이 아니라 **사람의 검토 목록**으로 써야 합니다.
- `unattended_change`: 다른 사람이 대신 전한 완료 보고("민수 님 견적서는 지난 금요일에 나갔대요")도 표시합니다.
- `weekend_due`: 가온물산은 토요일에만 작업할 수 있어서 12/12(토) 기한은 정상입니다.
- `duplicate_candidate`: run1에서 같은 기능을 다룬 다른 요청 3쌍을 중복으로 표시했습니다.

### 라이선스

wirelog 코어 엔진은 LGPL-3.0과 상용 라이선스 중 선택하는 이중 라이선스이고, PyreWire는 Apache-2.0과 GPL-3.0 이상 중 선택하는 이중 라이선스입니다. 상용으로 쓰려면 조건을 확인해야 합니다.

### 알려진 한계

- 같은 회의록이라도 실행할 때마다 추출 결과가 조금씩 다릅니다. `extracted/`의 캐시는 그중 한 번의 결과입니다.
- 상태 판단, 특히 "보류"나 "연기" 같은 미묘한 변화는 자주 틀립니다.
- 중복 판단은 문자열 유사도 기반이라, 표현이 많이 다르면 같은 일이 두 번 등록될 수 있습니다.
- 긴 회의록을 나누어 처리하는 기능은 없습니다. 샘플은 짧아서 한 번에 처리합니다.

## 다음 단계 아이디어

- 여러 번 실행해 평균·분산을 내는 반복 평가, 평가 결과를 기준으로 프롬프트 개선
- 추출 결과를 사람이 확인·수정하는 검토 단계 추가 (신뢰도 낮은 항목 우선)
- 임베딩 기반 중복 판단으로 교체
- 긴 회의록 분할 처리
- 그래프 + LLM 질의응답 (자연어 질문 → SPARQL 생성 → 답변)
- 데이터가 커지면 GraphDB, Apache Jena Fuseki 같은 트리플 스토어로 이전
