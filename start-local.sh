#!/usr/bin/env bash
# Avvio locale del backend Equity Research (macOS/Linux).
# Legge le variabili da .env (il codice NON usa python-dotenv, quindi le
# carichiamo qui) poi lancia uvicorn su http://localhost:8000, come Render.
#
#   ./start-local.sh            avvio normale (come produzione)
#   ./start-local.sh --reload   con auto-reload sui cambi di file (dev)

set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "File .env non trovato in $(pwd). Crealo con i valori delle chiavi (vedi .env.example)." >&2
  exit 1
fi

set -a
while IFS='=' read -r key value || [[ -n "$key" ]]; do
  key="$(printf '%s' "$key" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [[ -z "$key" || "$key" == \#* ]] && continue
  value="$(printf '%s' "$value" | tr -d '\r')"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value#\"}"
    value="${value%\"}"
  fi
  if [[ -n "$value" ]]; then
    export "$key=$value"
    echo "  env: $key impostata"
  fi
done < "$ENV_FILE"
set +a

if [[ ! -x "venv/bin/python" ]]; then
  echo "venv non trovato — crealo prima con: python3 -m venv venv && venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

RELOAD_ARGS=()
if [[ "${1:-}" == "--reload" || "${1:-}" == "-Reload" ]]; then
  RELOAD_ARGS=(--reload)
fi

echo ""
echo "Avvio backend su http://localhost:8000 (docs: http://localhost:8000/docs)"
echo ""
exec venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 8000 "${RELOAD_ARGS[@]}"
