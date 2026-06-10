from hashlib import sha1

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.config import rag_settings


def split_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or rag_settings.RAG_CHUNK_SIZE,
        chunk_overlap=chunk_overlap
        if chunk_overlap is not None
        else rag_settings.RAG_CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(documents)

    for index, chunk in enumerate(chunks):
        source = chunk.metadata.get("source", "unknown")
        page = chunk.metadata.get("page", "")
        digest = sha1(f"{source}:{page}:{index}:{chunk.page_content}".encode()).hexdigest()
        chunk.metadata["chunk_id"] = digest[:16]
        chunk.metadata["chunk_index"] = index
    return chunks
