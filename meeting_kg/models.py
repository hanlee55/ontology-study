"""LLM이 회의록에서 뽑아낼 결과의 형식.

이 Pydantic 모델이 JSON 스키마로 변환되어 LLM에 전달되고,
LLM은 반드시 이 형식대로만 응답한다 (structured output).
"""

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["open", "in_progress", "blocked", "done", "cancelled"]
Priority = Literal["high", "medium", "low"]


class Provenance(BaseModel):
    evidence: str = Field(description="근거가 되는 회의록 원문 발언을 그대로 인용")
    confidence: float = Field(description="추출 확신도 0.0~1.0")


class NewEntity(BaseModel):
    temp_id: str = Field(description="이 응답 안에서 참조할 임시 ID. 반드시 'new:'로 시작 (예: new:feat-audit-export)")
    type: Literal["Feature", "CustomerContact", "Employee", "Customer", "Service"]
    label: str = Field(description="정식 이름")
    aliases: list[str] = Field(description="회의에서 불린 다른 이름들")
    parent: str | None = Field(
        description="Feature면 소속 서비스 ID, CustomerContact면 근무 고객사 ID, Employee면 소속 부서 ID. 모르면 null"
    )


class KnowledgeNote(Provenance):
    about: str = Field(description="대상 엔티티 ID (카탈로그 ID 또는 new: ID)")
    statement: str = Field(description="알게 된 사실을 한 문장으로")


class ItemUpdate(Provenance):
    existing_id: str = Field(description="'기존 추적 항목' 목록의 id")
    status: Status = Field(description="이 회의 시점의 상태")
    due_date: str | None = Field(description="기한이 새로 정해지거나 바뀌었으면 YYYY-MM-DD, 아니면 null")
    note: str = Field(description="무엇이 어떻게 진행·변경되었는지 한 문장")


class ActionItem(Provenance):
    ref: str = Field(description="이 응답 안에서 참조할 임시 ID. 'new:'로 시작 (예: new:ai-sso-dev)")
    description: str
    assignees: list[str] = Field(description="담당 직원 또는 부서 ID")
    due_date: str | None = Field(
        description="YYYY-MM-DD. '다음 주 화요일' 같은 표현은 회의 일자 기준으로 계산. 없으면 null"
    )
    status: Status
    priority: Priority | None
    relates_to: list[str] = Field(description="관련 고객사·서비스·기능·다른 항목 ID (기존 id 또는 new: ID)")


class CustomerRequest(Provenance):
    ref: str = Field(description="이 응답 안에서 참조할 임시 ID. 'new:'로 시작 (예: new:req-bulk-sign)")
    description: str
    requested_by: str = Field(description="요청한 고객사 ID")
    concerns: list[str] = Field(description="대상 서비스·기능 ID")
    priority: Priority | None
    status: Status


class Issue(Provenance):
    ref: str = Field(description="이 응답 안에서 참조할 임시 ID. 'new:'로 시작 (예: new:iss-sms-delay)")
    description: str
    reported_by: str | None = Field(description="이슈를 제기한 고객사·사람 ID")
    affects: list[str] = Field(description="영향을 받는 서비스·기능·고객사 ID")
    assignees: list[str] = Field(description="처리 담당 직원 또는 부서 ID")
    priority: Priority | None
    status: Status


class Decision(Provenance):
    description: str
    decided_by: list[str] = Field(description="결정에 참여한 사람·조직 ID")
    relates_to: list[str]


class MeetingExtraction(BaseModel):
    summary: str = Field(description="회의 내용 3문장 이내 요약")
    participants: list[str] = Field(description="참석자 ID")
    customers: list[str] = Field(description="회의에서 다룬 고객사 ID")
    new_entities: list[NewEntity] = Field(description="카탈로그에 없는 새 기능·사람 등. 꼭 필요할 때만")
    updates: list[ItemUpdate] = Field(description="기존 추적 항목의 진행·완료·지연·기한 변경. 먼저 이것부터 확인")
    knowledge: list[KnowledgeNote] = Field(description="서비스·고객사·사람에 대한 지속적인 사실 (할 일이 아닌 것)")
    action_items: list[ActionItem] = Field(description="이번 회의에서 새로 생긴 할 일만")
    customer_requests: list[CustomerRequest] = Field(description="이번 회의에서 새로 나온 고객 요청만")
    issues: list[Issue] = Field(description="이번 회의에서 새로 제기된 이슈만")
    decisions: list[Decision]
