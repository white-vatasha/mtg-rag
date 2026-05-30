#!/usr/bin/env bash
# Copy local RAG assets into the cluster PVC (AtomicCards, Chroma index, scraped decks).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NS=mtg-rag
PVC_POD=""

echo "==> Finding a pod that mounts rag-data..."
for deploy in api ollama; do
  PVC_POD=$(kubectl -n "$NS" get pods -l "app=$deploy" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "$PVC_POD" ]]; then
    break
  fi
done

if [[ -z "$PVC_POD" ]]; then
  echo "No running pod in $NS. Run ./scripts/minikube-deploy.sh first."
  exit 1
fi

kubectl -n "$NS" wait --for=condition=Ready "pod/$PVC_POD" --timeout=120s

copy_if_exists() {
  local src="$1"
  local dest="$2"
  if [[ -e "$src" ]]; then
    echo "Copying $src -> pod:$dest"
    kubectl -n "$NS" exec "$PVC_POD" -c api -- mkdir -p "$(dirname "$dest")" 2>/dev/null || \
      kubectl -n "$NS" exec "$PVC_POD" -- mkdir -p "$(dirname "$dest")" 2>/dev/null || true
    kubectl -n "$NS" cp "$src" "$NS/$PVC_POD:$dest" -c api 2>/dev/null || \
      kubectl -n "$NS" cp "$src" "$NS/$PVC_POD:$dest"
  else
    echo "Skip (missing): $src"
  fi
}

# API pod layout: /data, /app/context, /app/ingestion/mtg_db, /app/ingestion/scraped_decks
if kubectl -n "$NS" get pod "$PVC_POD" -o jsonpath='{.spec.containers[*].name}' | grep -q api; then
  CONTAINER=( -c api )
else
  CONTAINER=()
fi

if [[ -f context/AtomicCards.json ]]; then
  echo "Copying AtomicCards.json (may take a minute)..."
  kubectl -n "$NS" exec "${CONTAINER[@]}" "$PVC_POD" -- mkdir -p /app/context
  kubectl -n "$NS" cp context/AtomicCards.json "$NS/$PVC_POD:/app/context/AtomicCards.json" "${CONTAINER[@]}"
fi

if [[ -d ingestion/mtg_db ]]; then
  echo "Copying Chroma index..."
  kubectl -n "$NS" exec "${CONTAINER[@]}" "$PVC_POD" -- mkdir -p /app/ingestion/mtg_db
  kubectl -n "$NS" cp ingestion/mtg_db/. "$NS/$PVC_POD:/app/ingestion/mtg_db/" "${CONTAINER[@]}"
fi

if [[ -d ingestion/scraped_decks ]]; then
  echo "Copying scraped decks..."
  kubectl -n "$NS" exec "${CONTAINER[@]}" "$PVC_POD" -- mkdir -p /app/ingestion/scraped_decks
  kubectl -n "$NS" cp ingestion/scraped_decks/. "$NS/$PVC_POD:/app/ingestion/scraped_decks/" "${CONTAINER[@]}"
fi

if [[ -f data/app.db ]]; then
  kubectl -n "$NS" exec "${CONTAINER[@]}" "$PVC_POD" -- mkdir -p /data
  kubectl -n "$NS" cp data/app.db "$NS/$PVC_POD:/data/app.db" "${CONTAINER[@]}"
fi

echo "==> Restart API to reload index..."
kubectl -n "$NS" rollout restart deployment/api
kubectl -n "$NS" rollout status deployment/api --timeout=600s

echo "Seed complete."
