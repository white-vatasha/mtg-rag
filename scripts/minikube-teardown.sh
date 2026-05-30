#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kubectl delete -k "$ROOT/k8s/base" --ignore-not-found
echo "Removed mtg-rag resources. PVCs remain unless you delete them:"
echo "  kubectl delete pvc -n mtg-rag ollama-models rag-data"
