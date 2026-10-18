"""Trusted catalog snapshots and bounded inputs for the two implemented adapters."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.chat import ChatMessage


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int = Field(ge=1, strict=True)
    code: str = Field(min_length=1, max_length=64, strict=True)
    name: str = Field(default="", max_length=64)
    status: Literal["online", "offline", "draft"]
    param_schema: dict[str, Any]
    price_per_call: int = Field(ge=0, le=1_000_000, strict=True)
    catalog_source: Literal["internal", "market"] = "internal"


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def ends_with_user(self):
        if self.messages[-1].role != "user":
            raise ValueError("The final message must be from the user")
        return self


class SummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000, strict=True)
    max_length: int = Field(default=200, ge=30, le=1000, strict=True)

    @model_validator(mode="after")
    def nonblank_text(self):
        if not self.text.strip():
            raise ValueError("Text cannot be blank")
        return self
