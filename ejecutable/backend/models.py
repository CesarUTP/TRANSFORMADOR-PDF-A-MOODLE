"""Pydantic models for the PDF → Moodle XML API."""
from pydantic import BaseModel


class QuestionStats(BaseModel):
    multichoice: int = 0
    truefalse: int = 0
    matching: int = 0
    cloze: int = 0

    @property
    def total(self) -> int:
        return self.multichoice + self.truefalse + self.matching + self.cloze


class ErrorResponse(BaseModel):
    detail: str
