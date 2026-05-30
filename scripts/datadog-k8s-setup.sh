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

# Trim quotes/whitespace often introduced when copying into .env
DD_API_KEY="$(printf '%s' "${DD_API_KEY}" | tr -d '[:space:]"'"'"')"
DD_SITE="$(printf '%s' "${DD_SITE:-datadoghq.com}" | tr -d '[:space:]"'"'"')"

if [[ "${DD_API_KEY}" == REPLACE_WITH_DATADOG_API_KEY* ]]; then
  echo "DD_API_KEY is still the placeholder. Set a real key in .env"
  exit 1
fi

if [[ "${#DD_API_KEY}" -lt 32 ]]; then
  echo "DD_API_KEY is too short (${#DD_API_KEY} chars). You may have an Application key;"
  echo "create an API key at Organization Settings → API Keys (usually 32 characters)."
  exit 1
fi

validate_key() {
  local site="$1"
  local code
  code="$(curl -s -o /dev/null -w "%{http_code}" -H "DD-API-KEY: ${DD_API_KEY}" \
    "https://api.${site}/api/v1/validate")"
  echo "${code}"
}

echo "Validating API key against ${DD_SITE}…"
http_code="$(validate_key "${DD_SITE}")"
if [[ "${http_code}" != "200" ]]; then
  if [[ "${DD_SITE}" == "datadoghq.com" ]]; then
    echo "  datadoghq.com → HTTP ${http_code}; trying datadoghq.eu…"
    eu_code="$(validate_key "datadoghq.eu")"
    if [[ "${eu_code}" == "200" ]]; then
      DD_SITE="datadoghq.eu"
      echo "  Key is valid on EU site. Set DD_SITE=datadoghq.eu in .env"
      http_code="200"
    fi
  fi
fi

if [[ "${http_code}" != "200" ]]; then
  echo "Datadog rejected this API key (HTTP ${http_code})."
  echo ""
  echo "Fix:"
  echo "  1. Use an API key (not Application key): Organization Settings → API Keys"
  echo "  2. Match region: US → DD_SITE=datadoghq.com  |  EU → DD_SITE=datadoghq.eu"
  echo "  3. No quotes around the key in .env:  DD_API_KEY=abc123...  (not DD_API_KEY=\"...\")"
  echo "  4. Create a new key if this one was revoked"
  exit 1
fi
echo "API key OK (site: ${DD_SITE})."

kubectl config use-context minikube >/dev/null 2>&1 || true

echo "Updating datadog-secret in mtg-rag…"
kubectl create secret generic datadog-secret -n mtg-rag \
  --from-literal=api-key="${DD_API_KEY}" \
  --from-literal=site="${DD_SITE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Applying k8s/overlays/datadog…"
kubectl apply -k k8s/overlays/datadog

echo "Restarting Datadog agent (pick up secret + kubelet settings)…"
kubectl -n mtg-rag rollout restart daemonset/datadog-agent 2>/dev/null \
  || kubectl -n mtg-rag delete pod -l app=datadog-agent --wait=false

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
echo "Datadog: Infrastructure → filter cluster:mtg-rag-minikube"
echo "         APM service mtg-rag-api, logs source python"
echo "Agent logs: kubectl -n mtg-rag logs -l app=datadog-agent --tail=30"
