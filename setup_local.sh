#!/usr/bin/env bash
# Bootstrap local dev: venv, deps, data dirs, KB PDF, optional index.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> TVS WhatsApp bot — local setup"

if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 not found. Install: sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

if [[ ! -d venv ]]; then
  echo "==> Creating venv..."
  python3 -m venv venv || {
    echo "ERROR: Could not create venv. Try: sudo apt install python3-venv"
    exit 1
  }
fi

# shellcheck disable=SC1091
source venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt

mkdir -p data

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example — edit GEMINI_API_KEY before running."
fi

# Load .env for subsequent steps
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

if [[ ! -f tvs_three_wheelers_kb.pdf ]]; then
  echo "==> Building knowledge-base PDF..."
  python build_tvs_3w_kb.py
fi

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo ""
  echo "------------------------------------------------------------------"
  echo "NEXT: Add your Gemini API key to .env"
  echo "  GEMINI_API_KEY=your_key   # https://aistudio.google.com/app/apikey"
  echo ""
  echo "Then index the KB and copy FILE_SEARCH_STORE into .env:"
  echo "  source venv/bin/activate"
  echo "  python index_document.py tvs_three_wheelers_kb.pdf"
  echo ""
  echo "Run the local mock CRM lab:"
  echo "  docker compose --profile lab up -d --build"
  echo "  open http://localhost:8003/mock/chat"
  echo "------------------------------------------------------------------"
  exit 0
fi

if [[ -z "${FILE_SEARCH_STORE:-}" ]]; then
  echo "==> Indexing KB into Gemini File Search (needs network)..."
  python index_document.py tvs_three_wheelers_kb.pdf | tee /tmp/index_out.txt
  STORE=$(grep -o 'fileSearchStores/[^ ]*' /tmp/index_out.txt | tail -1 || true)
  if [[ -n "$STORE" ]]; then
    if grep -q '^FILE_SEARCH_STORE=' .env; then
      sed -i "s|^FILE_SEARCH_STORE=.*|FILE_SEARCH_STORE=${STORE}|" .env
    else
      echo "FILE_SEARCH_STORE=${STORE}" >> .env
    fi
    echo "==> Wrote FILE_SEARCH_STORE=${STORE} to .env"
  else
    echo "WARN: Could not parse store name — copy FILE_SEARCH_STORE= from index output into .env"
  fi
fi

echo ""
echo "==> Ready."
echo "  Local lab:  docker compose --profile lab up -d --build"
echo "              http://localhost:8003/mock/chat"
echo "  Production: docker compose --profile client up -d --build"
echo "  Tests:      .venv/bin/python -m pytest tests/ -q"
