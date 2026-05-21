from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    id: str
    title: str | None = None

    annotations: list["DocumentAnnotation"] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentPropertySet:
    publication_year: int | None = None
    publication_month: int | None = None
    publication_day: int | None = None

@dataclass(frozen=True)
class DocumentAnnotation:
    annotator: str


