from dataclasses import dataclass


@dataclass(frozen=True)
class EntityMention:
    surface_form: str
    relation: str
    context: str

@dataclass(frozen=True)
class DateMention:
    raw: str
    year: int
    month: int
    day: int

@dataclass(frozen=True)
class DocOcrEnrichment:
    publication_date: DateMention
    entities: list[EntityMention]
    keywords: list[str]

@dataclass(frozen=True)
class DocOcrEnrichRun:
    start_timestamp: int
    model: str
    prompt: str
    outputs: list[DocOcrEnrichment]