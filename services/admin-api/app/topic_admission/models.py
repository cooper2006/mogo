from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TopicTerm(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    synonyms: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("keyword")
    @classmethod
    def clean_keyword(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("keyword_required")
        return value

    @field_validator("synonyms")
    @classmethod
    def clean_synonyms(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 80 for value in cleaned):
            raise ValueError("invalid_synonym")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("duplicate_synonym")
        return cleaned


class TopicRule(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(default="", max_length=80)
    enabled: bool = True
    terms: list[TopicTerm] = Field(min_length=1, max_length=30)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()


class TopicPolicyPayload(BaseModel):
    mode: Literal["off", "denylist", "allowlist"] = "off"
    rules: list[TopicRule] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_rules(self) -> "TopicPolicyPayload":
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_rule_id")
        return self


class TopicTestPayload(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    policy: TopicPolicyPayload


class TopicChangesPayload(BaseModel):
    mode: Literal["off", "denylist", "allowlist"]
    updatedAt: str | None = None
    upserts: list[TopicRule] = Field(default_factory=list, max_length=200)
    deletes: list[str] = Field(default_factory=list, max_length=200)


class TopicDraftTestPayload(TopicChangesPayload):
    text: str = Field(min_length=1, max_length=20_000)
