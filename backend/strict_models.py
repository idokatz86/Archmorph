"""Strict Pydantic base classes for API boundary schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    """Base model for user-facing API schemas.

    Unknown fields are rejected instead of silently dropped to harden API
    boundaries against over-posting and mass-assignment mistakes.
    """

    model_config = ConfigDict(extra="forbid")
