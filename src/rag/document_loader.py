from pathlib import Path

from langchain_community.document_loaders import (
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain_core.documents import Document

SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".md", ".txt"}


def _load_file(path: Path) -> list[Document]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        docs = Docx2txtLoader(str(path)).load()
    elif suffix == ".pdf":
        docs = PyPDFLoader(str(path)).load()
    elif suffix in {".md", ".txt"}:
        docs = TextLoader(str(path), encoding="utf-8", autodetect_encoding=True).load()
    else:
        return []

    for doc in docs:
        doc.metadata.update(
            {
                "source": path.as_posix(),
                "title": path.stem,
                "doc_type": suffix.lstrip("."),
            }
        )
    return docs


def load_documents(data_dir: str | Path) -> list[Document]:
    root = Path(data_dir)
    if not root.exists():
        raise FileNotFoundError(f"Data directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Data path is not a directory: {root}")

    documents: list[Document] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            documents.extend(_load_file(path))
    return documents
