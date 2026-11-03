# ontology-study

회의록·전사 스크립트를 LLM(Upstage Solar)으로 분석해 **RDF/OWL 온톨로지 기반 지식 그래프**를 만드는 학습용 프로토타입입니다.

회의록에서 다음 지식을 뽑아 저장합니다.

- **서비스 지식**: 서비스와 기능, 특징, 로드맵
- **고객사 지식**: 사용 서비스, 제약 조건, 규모, 요청 사항, 이슈
- **사람·부서별 업무**: 누가 무엇을 언제까지 하는지, 상태가 회의마다 어떻게 바뀌었는지(히스토리)

모든 사실에는 **출처 회의, 근거 발언(원문 인용), 추출 신뢰도, 추출 모델**이 붙습니다.

> `samples/`의 회의록, 회사·사람·고객사 이름은 모두 학습용 **가상 데이터**입니다.
> 회의록은 서브 에이전트가 `data/reference.ttl`을 바탕으로 작성했고, 기대하는 추출 결과는 `samples/answer_key.md`에 있습니다.

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
    └─▶ SPARQL 질의 (queries/*.rq)
```

## 디렉터리 구조

| 경로 | 내용 |
|---|---|
| `ontology/schema.ttl` | 온톨로지 스키마 (클래스, 속성, 상하위·역관계·전이 관계, 서로소 클래스) |
| `ontology/shapes.ttl` | SHACL 데이터 품질 규칙 |
| `data/reference.ttl` | 기준 데이터: 조직도, 직원, 서비스·기능, 고객사·고객 담당자, 별칭 |
| `samples/` | 가상 회의록 4개 (2026-10-06 ~ 10-27)와 정답지 `answer_key.md` |
| `extracted/` | LLM 추출 결과(JSON) 캐시 |
| `output/graph.ttl` | 생성된 지식 그래프 |
| `queries/` | 예제 SPARQL 질의 |
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
uv run python -m meeting_kg extract samples/2026-10-13_gaon-weekly.txt

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

### 정답지와 비교한 결과 (현재 `extracted/` 기준)

`samples/answer_key.md`와 비교하면 다음과 같습니다.

**맞게 추출한 것**
- 완료 처리: SSO 기술 검토, SSO 견적, 증설 견적, 신규 사용자 가이드, 메타데이터 재요청(담당자가 "그분"으로만 언급됐는데도 김민수로 연결)
- 업로드 오류 이슈: 신규 → 진행 중(기한 10/23으로 연기) → 완료
- 대량 서명 한도 요청: 신규 → 진행 중, 서로 다른 회의에서 나온 같은 요청을 중복 병합으로 하나로 합침
- 상대 날짜 계산 ("이번 주 금요일" → 10/09 등), 결정사항, 고객사·서비스 지식 메모

**틀리거나 놓친 것**
- 이번 추출에서 LLM이 정한 견적 기한은 10/10입니다. 정답지(10/09)와 다르므로 날짜 계산도 검토가 필요합니다.
- SSO 개발이 **보류(blocked)** 된 상태를 잡지 못하고 "진행 중"으로 기록했습니다.
- 감사 로그 내보내기 요청이 4차 회의에서 **새 요청으로 중복 등록**됐습니다. 표현이 조금 달라서 문자열 유사도 기준(0.85)을 넘지 못했습니다.
- 패치 지연 사유("구버전용 별도 빌드")를 별도 **이슈로 잘못 등록**했습니다.
- 정하늘의 보안 검토 기한이 4차 회의에서 근거 없이 11/13으로 바뀌었습니다. (4차 회의에는 정하늘이 참석하지 않았음)
- 박지훈의 "SSO 연동 테스트 11/13 완료" 할 일이 따로 만들어지지 않았습니다.

### 알려진 한계

- 같은 회의록이라도 실행할 때마다 추출 결과가 조금씩 다릅니다. `extracted/`의 캐시는 그중 한 번의 결과입니다.
- 상태 판단, 특히 "보류"나 "연기" 같은 미묘한 변화는 자주 틀립니다.
- 중복 판단은 문자열 유사도 기반이라, 표현이 많이 다르면 같은 일이 두 번 등록될 수 있습니다.
- 긴 회의록을 나누어 처리하는 기능은 없습니다. 샘플은 짧아서 한 번에 처리합니다.

## 다음 단계 아이디어

- 정답지(`samples/answer_key.md`)를 기준으로 추출 정확도를 자동 채점하는 평가 스크립트
- 추출 결과를 사람이 확인·수정하는 검토 단계 추가 (신뢰도 낮은 항목 우선)
- 임베딩 기반 중복 판단으로 교체
- 긴 회의록 분할 처리
- 그래프 + LLM 질의응답 (자연어 질문 → SPARQL 생성 → 답변)
- 데이터가 커지면 GraphDB, Apache Jena Fuseki 같은 트리플 스토어로 이전
