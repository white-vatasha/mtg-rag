# MTG Commander RAG

A local **Retrieval-Augmented Generation (RAG)** app for Magic: The Gathering **Commander (EDH)**. Ask questions about competitive decks, card rules, and EDHRec meta; log in to save your own decklists.

Powered by **ChromaDB**, **LlamaIndex**, and **Ollama** (`llama3.2:3b` in Minikube; `llama3.1:8b` if you have enough RAM locally) + `nomic-embed-text`.

## Features

- **Commander Oracle** — natural-language Q&A over card rules and scraped decklists
- **EDHRec intelligence** — synergies, themes, and staple cards per commander
- **Color-aware answers** — parses requests like “blue-red” as Izzet (U/R), not Azorius
- **Save decklists** — when a response includes a deck list, logged-in users can save it to **My Decks**
- **Runs locally or on Minikube** — same API with automatic indexing on cluster startup

---

## Quick start (local)

### Prerequisites

1. **Python 3.11+** and a virtualenv  
2. **Ollama** with models:
   ```bash
   ollama pull llama3.2:3b
   ollama pull nomic-embed-text
   ```
3. **Node.js 18+** (for the frontend)
4. **Card database** — download [MTGJSON AtomicCards](https://mtgjson.com/downloads/all-files/) to `context/AtomicCards.json` (~147 MB)

### 1. Backend

From the **project root** (`MTG-Rag/`):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional: set SECRET_KEY
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

On first start the API will **index Commander-legal cards** if `ingestion/mtg_db/` is empty (can take 20–40 minutes). Set `AUTO_DOWNLOAD_CARDS=true` in `.env` to fetch `AtomicCards.json` automatically.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) — Vite proxies `/api` to port 8000.

### 3. Refresh deck knowledge (optional, better answers)

```bash
# Scrape EDHRec meta + decklists, then insert into the index
python -m ingestion.scrapper

# Re-index all enriched files without re-embedding every card
python -m ingestion.scrapper reindex
```

Outputs live under `ingestion/scraped_decks/` and `ingestion/scraped_decks/knowledge/`.

---

## Minikube (Kubernetes)

Run **Ollama**, the **API**, and the **frontend** in a local cluster with persistent storage for models and the vector index.

### Prerequisites

| Tool | Install |
|------|---------|
| [Minikube](https://minikube.sigs.k8s.io/docs/start/) | `brew install minikube` |
| [kubectl](https://kubernetes.io/docs/tasks/tools/) | `brew install kubectl` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Required as Minikube driver |

**Memory:** The deploy script requests **6 GB** for Minikube (fits Docker Desktop’s default 8 GB VM). For a larger cluster:

```bash
# Docker Desktop → Settings → Resources → Memory ≥ 12 GB, then:
MINIKUBE_MEMORY=10240 ./scripts/minikube-deploy.sh
```

### Deploy (one command)

Run from the **project root** — not `ingestion/` or `scraped_decks/`:

```bash
chmod +x scripts/*.sh
./scripts/minikube-deploy.sh
```

The script will:

1. Start Minikube (if needed) and set `kubectl` context to `minikube`
2. Enable the ingress addon
3. Build `mtg-rag-api` and `mtg-rag-frontend` images inside Minikube’s Docker
4. Apply all manifests in `k8s/base` (creates namespace `mtg-rag`)
5. Wait for Ollama and pull `llama3.2:3b` + `nomic-embed-text`
6. Wait for the API deployment (first boot **indexes inside the cluster**)

### Automatic indexing on API startup

When `AUTO_INDEX_ON_STARTUP=true` (default in `k8s/base/configmap.yaml`), each API pod will:

1. Wait for Ollama and required models  
2. Download `AtomicCards.json` if missing (`AUTO_DOWNLOAD_CARDS=true`)  
3. Embed Commander-legal cards into Chroma (first time: **~20–40 min**, persisted on PVC)  
4. Index any deck/EDHRec files under `ingestion/scraped_decks/` on the volume  

Watch progress:

```bash
kubectl -n mtg-rag get pods -w
kubectl -n mtg-rag logs -f deployment/api
```

Check health (includes indexing phase):

```bash
curl -s http://$(minikube ip):30080/api/health | python3 -m json.tool
```

Traffic is only routed when RAG is ready (`/api/ready` returns 200).

### Access the app

On **Minikube with the Docker driver (macOS)**, `http://$(minikube ip):30080` does **not** work until a tunnel is running. Pods can be `Running` while the browser times out.

```bash
# Terminal 1 — leave open (routes NodePort to your Mac)
minikube tunnel

# Terminal 2
open "http://$(minikube ip):30080"
```

Or use Minikube’s port-forward (also keep that terminal open):

```bash
minikube service frontend -n mtg-rag
```

Ingress (after tunnel):

```bash
echo "$(minikube ip) mtg-rag.local" | sudo tee -a /etc/hosts
open http://mtg-rag.local
```

### Optional: seed an existing local index

Skip the long first-time card embedding by copying your local data into the cluster:

```bash
./scripts/minikube-seed-data.sh
```

Requires `context/AtomicCards.json`, and ideally `ingestion/mtg_db/` already built locally.

### Teardown

```bash
./scripts/minikube-teardown.sh
# PVCs remain unless deleted:
# kubectl delete pvc -n mtg-rag ollama-models rag-data
```

### Minikube troubleshooting

| Symptom | Fix |
|---------|-----|
| `connection refused` on `localhost:8080` | Minikube not started or wrong context: `minikube start` then `kubectl config use-context minikube` |
| `namespace "mtg-rag" not found` | Deploy not applied yet: `./scripts/minikube-deploy.sh` from project root |
| `no such file or directory: ./scripts/minikube-deploy.sh` | `cd` to project root (`MTG-Rag/`), not a subdirectory |
| `minikube is not installed` | `brew install minikube` |
| `Docker Desktop has only X MB memory` | Lower RAM: default script uses 6 GB, or increase Docker Desktop memory |
| API pod `Pending` | Insufficient cluster memory: `kubectl describe pod -n mtg-rag -l app=api` |
| Frontend `ErrImagePull` | Rebuild inside Minikube: `eval $(minikube docker-env)` then `docker build -t mtg-rag-frontend:latest -f docker/Dockerfile.frontend .` |
| `/api/query` **500** — `requires more system memory` | Default `llama3.1:8b` needs ~20 GiB; cluster uses `llama3.2:3b` + `OLLAMA_LLM_NUM_CTX=4096`. Rebuild API image after config changes. |

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness + `rag_ready`, indexing phase/message |
| GET | `/api/ready` | **503** until RAG index is ready (used by K8s readiness probe) |
| POST | `/api/query` | Ask Commander questions (`{"question": "..."}`) |
| POST | `/api/auth/register` | Create account (JSON: `email`, `password`) |
| POST | `/api/auth/login` | OAuth2 form login (`username`=email, `password`) |
| GET | `/api/auth/me` | Current user (Bearer token) |
| GET/POST/PUT/DELETE | `/api/decks` | Saved decklists (auth required) |

Query responses may include `has_decklist`, `decklist` (parsed card list), and `color_identity` when colors are detected in the question.

---

## Configuration

Copy `.env.example` to `.env` for local development. In Minikube, edit `k8s/base/configmap.yaml` and `k8s/base/secret.yaml`.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (change me) | JWT signing key |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API (`http://ollama:11434` in cluster) |
| `OLLAMA_LLM_MODEL` | `llama3.2:3b` (K8s) | Chat model; use `llama3.1:8b` locally only if you have ~24GB RAM for Ollama |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `AUTO_INDEX_ON_STARTUP` | `true` | Index cards + decks on API boot |
| `AUTO_DOWNLOAD_CARDS` | `false` / `true` in K8s | Download AtomicCards.json if missing |
| `ATOMIC_CARDS_URL` | MTGJSON API URL | Source for card download |
| `INDEX_DECKS_ON_STARTUP` | `true` | Index `scraped_decks/` files on boot |
| `CORS_ORIGINS` | localhost dev URLs | Comma-separated allowed origins |
| `DD_TRACE_ENABLED` | `false` | FastAPI/SQLAlchemy/requests APM via `ddtrace` |
| `DD_METRICS_ENABLED` | `false` | DogStatsD bootstrap/query metrics |
| `DD_LOGS_JSON` | `true` | JSON logs on stdout for Datadog log pipelines |
| `DD_SERVICE` / `DD_ENV` / `DD_VERSION` | see `.env.example` | Unified service tags |
| `DD_AGENT_HOST` | `127.0.0.1` | Datadog Agent host (node IP in Kubernetes) |

---

## Datadog observability

The API emits **JSON logs** (with optional trace correlation), **APM traces** for HTTP, RAG bootstrap, and `/api/query`, and **DogStatsD** gauges for bootstrap phases when enabled.

### Local development

1. Run a [Datadog Agent](https://docs.datadoghq.com/agent/) on your machine (Docker example):

   ```bash
   docker run -d --name dd-agent \
     -e DD_API_KEY=<your-api-key> \
     -e DD_APM_ENABLED=true \
     -e DD_DOGSTATSD_NON_LOCAL_TRAFFIC=true \
     -p 8126:8126/tcp -p 8125:8125/udp \
     gcr.io/datadoghq/agent:7
   ```

2. Copy `.env.example` to `.env` and set `DD_TRACE_ENABLED=true`, `DD_METRICS_ENABLED=true`, `DD_AGENT_HOST=127.0.0.1`.

3. Start the API (tracing is wired via `ddtrace-run` in `docker/Dockerfile.api`; locally use the same):

   ```bash
   ddtrace-run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
   ```

In Datadog: **APM → Services** (`mtg-rag-api`), **Logs** (source `python`), **Metrics** (`mtg_rag.bootstrap.*`).

### Minikube + Datadog Agent

1. Add your API key to `.env` (copy from `.env.example`):

   ```bash
   cp .env.example .env
   # Edit .env: DD_API_KEY=<your-datadog-api-key>
   ```

2. Run the setup script (applies overlay, agent, rebuilds API):

   ```bash
   chmod +x scripts/datadog-k8s-setup.sh
   ./scripts/datadog-k8s-setup.sh
   ```

   Or one-shot without `.env`: `DD_API_KEY='...' ./scripts/datadog-k8s-setup.sh`

The overlay enables tracing/metrics, deploys a node **DaemonSet** agent, and sets `DD_AGENT_HOST` to the node IP so the API pod sends traces and StatsD to the agent on the same node.

---

## Project layout

```
MTG-Rag/
├── api/                 # FastAPI: query, auth, decks, color parsing
├── ingestion/           # RAG pipeline, scraper, startup indexing
│   ├── mtg_db/          # Chroma persistent store (gitignored)
│   └── scraped_decks/   # Decklists + knowledge/ (gitignored)
├── frontend/            # React + Vite UI
├── context/             # AtomicCards.json (gitignored)
├── data/                # SQLite app.db (gitignored)
├── k8s/
│   ├── base/              # Core manifests (kubectl apply -k k8s/base)
│   └── overlays/datadog/  # Optional Datadog agent + APM/logging
├── docker/              # Dockerfiles + nginx config
└── scripts/
    ├── minikube-deploy.sh
    ├── minikube-seed-data.sh
    └── minikube-teardown.sh
```

---

## Architecture (Minikube)

```mermaid
flowchart LR
  User --> Frontend[frontend nginx :30080]
  Frontend -->|/api| API[api FastAPI :8000]
  API --> Ollama[ollama :11434]
  API --> Chroma[(PVC rag-data\nChroma + SQLite)]
  API --> Ollama
```

---

## License

Use at your own risk. Card data from [MTGJSON](https://mtgjson.com/). Deck scraping targets public deck sites; respect their terms of service and rate limits.
