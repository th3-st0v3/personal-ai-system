from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PASIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )
