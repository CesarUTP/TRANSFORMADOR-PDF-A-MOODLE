"""Pydantic models for the PDF → Moodle XML API."""
from pydantic import BaseModel


class QuestionStats(BaseModel):
    multichoice: int = 0
    truefalse: int = 0
    matching: int = 0
    cloze: int = 0
    essay: int = 0
    shortanswer: int = 0
    numerical: int = 0
    # Factor por el que se multiplicaron todos los puntos para que los huecos
    # de «Completar» (pesos enteros en Moodle) quedaran exactos; 1 = sin cambio.
    escala: int = 1

    @property
    def total(self) -> int:
        return (
            self.multichoice + self.truefalse + self.matching + self.cloze
            + self.essay + self.shortanswer + self.numerical
        )


class ErrorResponse(BaseModel):
    detail: str
