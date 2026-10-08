from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtractedPage:
    text: str
    page_number: int | None = None


class DocumentExtractor:
    def extract(self, path: str, file_type: str) -> list[ExtractedPage]:
        suffix = file_type.lower().lstrip('.')
        if suffix == 'txt':
            return [ExtractedPage(Path(path).read_text(encoding='utf-8'))]
        if suffix == 'pdf':
            import fitz
            with fitz.open(path) as pdf:
                return [ExtractedPage(page.get_text(), index + 1) for index, page in enumerate(pdf)]
        if suffix == 'docx':
            from docx import Document as WordDocument
            doc = WordDocument(path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            paragraphs.extend(' | '.join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows)
            return [ExtractedPage('\n'.join(paragraphs))]
        raise ValueError(f'Unsupported document format: {suffix}')


class RecursiveChunker:
    def __init__(self, chunk_size: int = 1200, overlap: int = 180) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                minimum = start + self.chunk_size // 2
                boundaries = [text.rfind(separator, minimum, end) + len(separator)
                              for separator in ('\n\n', '\n', '. ', ' ')]
                boundary = max((value for value in boundaries if value > minimum), default=0)
                if boundary:
                    end = boundary
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(start + 1, end - self.overlap)
        return chunks
