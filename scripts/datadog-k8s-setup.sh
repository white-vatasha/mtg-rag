#!/usr/bin/env bash
# Apply Datadog overlay, agent secret, and rebuild/restart the API on Minikube.
# Requires DD_API_KEY in the environment or in project-root .env (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${DD_API_KEY:-}" ]]; then
  echo "Missing DD_API_KEY."
  echo "  cp .env.example .env"
  echo "  # Add: DD_API_KEY=<your-datadog-api-key>"
  echo "  # Or: export DD_API_KEY='...'"
  exit 1
fi

kubectl config use-context minikube >/dev/null 2>&1 || true

echo "Updating datadog-secret in mtg-rag…"
kubectl create secret generic datadog-secret -n mtg-rag \
  --from-literal=api-key="${DD_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Applying k8s/overlays/datadog…"
kubectl apply -k k8s/overlays/datadog

echo "Building mtg-rag-api:latest in Minikube Docker…"
eval "$(minikube docker-env)"
docker build -t mtg-rag-api:latest -f docker/Dockerfile.api .

echo "Restarting API deployment…"
kubectl -n mtg-rag rollout restart deployment/api
kubectl -n mtg-rag delete pod -l app=api --field-selector=status.phase=Pending --ignore-not-found 2>/dev/null || true

echo ""
echo "Datadog agent:"
kubectl -n mtg-rag get daemonset datadog-agent 2>/dev/null || echo "  (daemonset not ready yet)"
kubectl -n mtg-rag get pods -l app=datadog-agent 2>/dev/null || true
echo ""
echo "API logs: kubectl -n mtg-rag logs -f deployment/api"
echo "Datadog: APM service mtg-rag-api, logs source python"
