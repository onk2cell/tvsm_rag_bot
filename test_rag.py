"""Quick terminal test of the RAG layer BEFORE wiring up WhatsApp.

Usage:  python test_rag.py   (then type questions; blank line to quit)
"""
from rag import ask

if __name__ == "__main__":
    print("Ask questions about your document (blank line to quit).")
    while True:
        q = input("\nQ: ").strip()
        if not q:
            break
        answer, cites = ask(q)
        print("A:", answer)
        if cites:
            print("Sources:", ", ".join(cites))
