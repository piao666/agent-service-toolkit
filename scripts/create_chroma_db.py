import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.embeddings import get_embedding_model

# Load environment variables from the .env file
load_dotenv()


def create_chroma_db(
    folder_path: str,
    db_name: str = "./chroma_db",
    delete_chroma_db: bool = True,
    chunk_size: int = 2000,
    overlap: int = 500,
):
    embeddings = get_embedding_model()

    # Initialize Chroma vector store
    if delete_chroma_db and os.path.exists(db_name):
        shutil.rmtree(db_name)
        print(f"Deleted existing database at {db_name}")

    chroma = Chroma(
        embedding_function=embeddings,
        persist_directory=f"./{db_name}",
    )

    # Initialize text splitter
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)

    total_chunks = 0
    loaded_documents = 0

    # Iterate over files in the folder
    for filename in sorted(os.listdir(folder_path)):
        file_path = os.path.join(folder_path, filename)

        # Load document based on file extension
        # Add more loaders if required, i.e. JSONLoader, TxtLoader, etc.
        if filename.endswith(".pdf"):
            loader = PyPDFLoader(file_path)
        elif filename.endswith(".docx"):
            loader = Docx2txtLoader(file_path)
        else:
            continue  # Skip unsupported file types

        # Load and split document into chunks
        document = loader.load()
        chunks = text_splitter.split_documents(document)
        loaded_documents += 1

        # Add chunks to Chroma vector store
        for chunk in chunks:
            chunk.metadata["source"] = str(Path(file_path).as_posix())
            chunk_id = chroma.add_documents([chunk])
            if chunk_id:
                print(f"Chunk added with ID: {chunk_id}")
                total_chunks += 1
            else:
                print("Failed to add chunk")

        print(f"Document {filename} added to database.")

    print(f"Vector database created and saved in {db_name}.")
    print(f"Documents loaded: {loaded_documents}")
    print(f"Chunks added: {total_chunks}")
    return chroma


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a local Chroma database from documents.")
    parser.add_argument("--folder", default="./data", help="Folder containing .pdf/.docx documents.")
    parser.add_argument("--db-name", default="./chroma_db", help="Chroma persist directory.")
    parser.add_argument("--chunk-size", type=int, default=2000, help="Text splitter chunk size.")
    parser.add_argument("--overlap", type=int, default=500, help="Text splitter chunk overlap.")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Append to an existing Chroma directory instead of deleting it first.",
    )
    parser.add_argument(
        "--test-query",
        default="RAG Agent system data flow",
        help="Query used for the post-build retrieval smoke test.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Create the Chroma database
    chroma = create_chroma_db(
        folder_path=args.folder,
        db_name=args.db_name,
        delete_chroma_db=not args.keep_existing,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
    )

    # Create retriever from the Chroma database
    retriever = chroma.as_retriever(search_kwargs={"k": 3})

    # Perform a similarity search
    similar_docs = retriever.invoke(args.test_query)

    # Display results
    for i, doc in enumerate(similar_docs, start=1):
        print(
            f"\nResult {i}:"
            f"\nSource: {doc.metadata.get('source', 'unknown')}"
            f"\nPage: {doc.metadata.get('page', 'n/a')}"
            f"\nContent:\n{doc.page_content[:800]}"
        )
