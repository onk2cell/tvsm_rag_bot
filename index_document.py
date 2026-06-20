"""One-time: index your PDF into a Gemini File Search store.

Usage:  python index_document.py path/to/manual.pdf
Re-run only when the document changes. Costs ~$0.15 per 1M tokens to index.
"""
import sys
import time

from dotenv import load_dotenv
from google import genai

load_dotenv()

DISPLAY_NAME = "tvs-manual"
MAX_WAIT_SEC = 600

client = genai.Client()


def find_store():
    """Reuse a store with our display name if it already exists."""
    try:
        for s in client.file_search_stores.list():
            if getattr(s, "display_name", None) == DISPLAY_NAME:
                return s
    except Exception:
        pass
    return None


def main(pdf_path: str) -> None:
    store = find_store()
    if store:
        print(f"Reusing existing store: {store.name}")
    else:
        store = client.file_search_stores.create(config={"display_name": DISPLAY_NAME})
        print(f"Created store: {store.name}")

    print(f"Uploading and indexing {pdf_path} ...")
    op = client.file_search_stores.upload_to_file_search_store(
        file_search_store_name=store.name,
        file=pdf_path,
        config={"display_name": pdf_path},
    )

    waited = 0
    while not getattr(op, "done", False) and waited < MAX_WAIT_SEC:
        print("  indexing...")
        time.sleep(5)
        waited += 5
        op = client.operations.get(op)          # adjust if your SDK polls differently

    print("\nDONE. Put this line in your .env:")
    print(f"FILE_SEARCH_STORE={store.name}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "manual.pdf")
