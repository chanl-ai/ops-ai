# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Typed models shared by parsers, strategies and the pipeline.

Settings models mirror `apps/console/src/lib/types/knowledge-ingest.ts`: field names are the
snake_case form of the console's camelCase names, and validation accepts either spelling so the
console's JSON can be passed in unchanged.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# ---------------------------------------------------------------------------------------------------------
# Parsed documents
# ---------------------------------------------------------------------------------------------------------


class Paragraph(_Model):
    kind: Literal["paragraph"] = "paragraph"
    text: str
    page: int | None = None


class Table(_Model):
    kind: Literal["table"] = "table"
    headers: list[str]
    rows: list[list[str]]
    caption: str | None = None
    page: int | None = None
    sheet: str | None = None

    def as_text(self) -> str:
        """The table as pipe-separated text, used when a table is chunked as prose."""
        lines = [" | ".join(self.headers)]
        lines.extend(" | ".join(row) for row in self.rows)
        if self.caption:
            lines.insert(0, self.caption)
        return "\n".join(lines)


Block = Annotated[Paragraph | Table, Field(discriminator="kind")]


class Section(_Model):
    """A run of content under one heading. `heading_path` is empty for content before any heading."""

    heading_path: list[str] = Field(default_factory=list[str])
    level: int = 0
    blocks: list[Block] = Field(default_factory=list[Block])
    page: int | None = None

    @property
    def paragraphs(self) -> list[Paragraph]:
        return [b for b in self.blocks if isinstance(b, Paragraph)]

    @property
    def tables(self) -> list[Table]:
        return [b for b in self.blocks if isinstance(b, Table)]


class SourceMetadata(_Model):
    filename: str
    mime_type: str
    size_bytes: int
    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    page_count: int | None = None
    #: Fields the source system supplies (SharePoint columns, document properties); read by `field:` mappings.
    fields: dict[str, str] = Field(default_factory=dict[str, str])


class ParsedDocument(_Model):
    title: str
    source: SourceMetadata
    sections: list[Section]
    #: 1-based page numbers whose text came from OCR.
    ocr_pages: list[int] = Field(default_factory=list[int])
    #: 1-based page numbers with no text layer that were not OCR'd.
    pages_without_text: list[int] = Field(default_factory=list[int])
    #: Characters dropped by boilerplate removal during parsing.
    removed_chars: int = 0
    warnings: list[str] = Field(default_factory=list[str])

    @property
    def tables(self) -> list[Table]:
        return [t for s in self.sections for t in s.tables]

    def plain_text(self) -> str:
        """All content in reading order, the input to the content digest."""
        parts: list[str] = []
        for section in self.sections:
            if section.heading_path:
                parts.append(section.heading_path[-1])
            for block in section.blocks:
                parts.append(block.text if isinstance(block, Paragraph) else block.as_text())
        return "\n\n".join(parts)


class ParsingSettings(_Model):
    ocr: bool = False
    tables: bool = True
    vision: bool = False


# ---------------------------------------------------------------------------------------------------------
# Ingest settings (console: IngestSettings)
# ---------------------------------------------------------------------------------------------------------

IngestStrategy = Literal["structure", "fixed", "topic", "faq", "context_headers", "parent_child", "table_rows", "clean"]
IngestPresetId = Literal["policy_manual", "help_centre", "rate_table", "email_templates", "custom"]
ColumnRole = Literal["searchable", "metadata", "ignored"]

SPLITTERS: tuple[IngestStrategy, ...] = ("structure", "fixed", "topic")
AI_STEPS: tuple[IngestStrategy, ...] = ("topic", "faq")


class TableColumn(_Model):
    name: str
    role: ColumnRole
    key: bool = False


class IngestApproval(_Model):
    status: Literal["not_needed", "pending", "approved"] = "not_needed"
    approved_steps: list[str] = Field(default_factory=list[str])
    requested_by: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None


class IngestSettings(_Model):
    preset: IngestPresetId = "custom"
    strategies: list[IngestStrategy] = Field(default_factory=lambda: ["structure"])
    size: int = 400
    overlap: int = 40
    child_size: int = 120
    questions_per_section: int = 3
    columns: list[TableColumn] = Field(default_factory=list[TableColumn])
    model: str = ""
    approval: IngestApproval = Field(default_factory=IngestApproval)


# ---------------------------------------------------------------------------------------------------------
# Split output (console: PreviewChunk, SplitCounts, SplitPreview)
# ---------------------------------------------------------------------------------------------------------

ChunkKind = Literal["chunk", "row", "parent"]
IndexUnitKind = Literal["self", "child", "question"]


class Chunk(_Model):
    index: int
    kind: ChunkKind = "chunk"
    #: What a query returns.
    text: str
    #: What search matches for the chunk's own unit: the text plus any context header.
    indexed_text: str
    section_path: list[str] = Field(default_factory=list[str])
    questions: list[str] | None = None
    children: list[str] | None = None
    metadata: dict[str, str] = Field(default_factory=dict[str, str])
    tokens: int = 0
    page: int | None = None
    #: Numeric band parsed from a band, amount or range column (spec 14.6); `None` upper means open.
    row_band: tuple[float, float | None] | None = None
    #: Prefix `context_headers` adds to every unit of this chunk.
    context_header: str | None = None


class IndexUnit(_Model):
    """One entry in the index. A match on any unit returns `chunk_index`'s chunk."""

    chunk_index: int
    kind: IndexUnitKind
    indexed_text: str


class SplitCounts(_Model):
    chunks: int = 0
    indexed_units: int = 0
    questions: int = 0
    tokens: int = 0
    model_calls: int = 0
    removed_chars: int = 0


class SplitResult(_Model):
    title: str
    strategies: list[IngestStrategy]
    chunks: list[Chunk]
    counts: SplitCounts
    notes: list[str] = Field(default_factory=list[str])

    def index_units(self) -> list[IndexUnit]:
        units: list[IndexUnit] = []
        for chunk in self.chunks:
            prefix = f"{chunk.context_header}\n\n" if chunk.context_header else ""
            if chunk.children:
                units.extend(
                    IndexUnit(chunk_index=chunk.index, kind="child", indexed_text=prefix + child)
                    for child in chunk.children
                )
            else:
                units.append(IndexUnit(chunk_index=chunk.index, kind="self", indexed_text=chunk.indexed_text))
            units.extend(
                IndexUnit(chunk_index=chunk.index, kind="question", indexed_text=q) for q in chunk.questions or []
            )
        return units
