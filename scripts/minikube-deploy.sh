#!/usr/bin/env bash
# Build images into Minikube's Docker daemon and deploy the stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v minikube >/dev/null 2>&1; then
  echo "ERROR: minikube is not installed."
  echo ""
  echo "You have kubectl and Docker, but Minikube is required for this script."
  echo "Install on macOS:"
  echo "  brew install minikube"
  echo ""
  echo "Then run from the project root (not ingestion/ or scraped_decks/):"
  echo "  cd \"$ROOT\""
  echo "  ./scripts/minikube-deploy.sh"
  echo ""
  echo "Docs: https://minikube.sigs.k8s.io/docs/start/"
  exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is not installed. Install: brew install kubectl"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed. Minikube needs a container runtime."
  exit 1
fi

echo "==> Starting minikube (if needed)..."
# Default 6GB fits Docker Desktop's typical 8GB VM limit; override: MINIKUBE_MEMORY=12288
MINIKUBE_MEMORY="${MINIKUBE_MEMORY:-6144}"
if ! minikube status >/dev/null 2>&1; then
  minikube start --driver=docker --cpus=4 --memory="${MINIKUBE_MEMORY}" --disk-size=40g
else
  echo "    Minikube already running."
fi
# Ensure kubectl points at minikube (fixes localhost:8080 connection refused)
kubectl config use-context minikube 2>/dev/null || true

echo "==> Enabling ingress addon..."
minikube addons enable ingress

echo "==> Building images inside minikube Docker..."
eval "$(minikube docker-env)"
docker build -t mtg-rag-api:latest -f docker/Dockerfile.api .
docker build -t mtg-rag-frontend:latest -f docker/Dockerfile.frontend .

echo "==> Applying Kubernetes manifests..."
kubectl apply -k k8s/base

echo "==> Waiting for Ollama..."
kubectl -n mtg-rag rollout status deployment/ollama --timeout=300s

echo "==> Pulling Ollama models (required before API can index)..."
kubectl -n mtg-rag delete job ollama-pull-models --ignore-not-found
kubectl -n mtg-rag apply -f k8s/base/ollama-models-job.yaml
kubectl -n mtg-rag wait --for=condition=complete job/ollama-pull-models --timeout=3600s

echo "==> Waiting for API (indexes on first startup; may take up to an hour)..."
kubectl -n mtg-rag rollout status deployment/api --timeout=3600s
kubectl -n mtg-rag rollout status deployment/frontend --timeout=120s

echo ""
echo "Deploy complete."
echo ""
echo "Next steps:"
echo "  1. Watch API index on first boot (20–40 min if no seed data):"
echo "       kubectl -n mtg-rag logs -f deployment/api"
echo "  2. Optional: copy local index to skip card embedding:"
echo "       ./scripts/minikube-seed-data.sh"
echo "  3. Open the app (Docker driver on Mac — NodePort needs a tunnel):"
echo "       # Option A — keep this terminal open:"
echo "       minikube tunnel"
echo "       open \"http://$(minikube ip):30080\""
echo "       # Option B — temporary local URL (keep terminal open):"
echo "       minikube service frontend -n mtg-rag"
echo ""
