# LLM Inference Service

A Kubernetes-native LLM inference platform using llama.cpp, with a custom operator, API gateway, and React dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User Interface                                   │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐  │
│  │  React Frontend │    │   infer.py CLI  │    │    Direct API Access    │  │
│  │  (port 5173)    │    │                 │    │                         │  │
│  └────────┬────────┘    └────────┬────────┘    └────────────┬────────────┘  │
└───────────┼──────────────────────┼──────────────────────────┼───────────────┘
            │                      │                          │
            ▼                      ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API Layer                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    FastAPI Service (port 8000)                          │ │
│  │  /serve - Deploy model  │  /cleanup - Remove model  │  /status - DB     │ │
│  └────────────────────────────────────┬────────────────────────────────────┘ │
│                                       │                                       │
│  ┌────────────────────────────────────▼────────────────────────────────────┐ │
│  │                   Contract Service (port 8001)                          │ │
│  │  /apply - Create CR  │  /delete - Delete CR+resources  │  /list         │ │
│  └────────────────────────────────────┬────────────────────────────────────┘ │
└───────────────────────────────────────┼─────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Kubernetes Cluster (k3d)                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                      Go Operator (controller-runtime)                   │ │
│  │              Watches ModelServe CRs → Creates Deployment + Service      │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │  Model Pod      │  │  Model Pod      │  │      PostgreSQL             │  │
│  │  ┌───────────┐  │  │  ┌───────────┐  │  │  ┌─────────────────────┐    │  │
│  │  │llama.cpp  │  │  │  │llama.cpp  │  │  │  │  server_status      │    │  │
│  │  │ server    │  │  │  │ server    │  │  │  │  - uuid             │    │  │
│  │  └───────────┘  │  │  └───────────┘  │  │  │  - model_name       │    │  │
│  │  ┌───────────┐  │  │  ┌───────────┐  │  │  │  - status           │    │  │
│  │  │ monitor   │  │  │  │ monitor   │  │  │  │  - memory_usage_mb  │    │  │
│  │  │ sidecar   │──┼──┼──│ sidecar   │──┼──┼──│  - endpoint         │    │  │
│  │  └───────────┘  │  │  └───────────┘  │  │  └─────────────────────┘    │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘  │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    Traefik Ingress (port 8080)                          │ │
│  │     /model-qwen-gguf → Qwen Service    /model-smollm2-gguf → SmolLM2   │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Kubernetes Operator**: Custom Go operator using controller-runtime to manage model deployments
- **llama.cpp Integration**: Uses the official llama.cpp server image for model inference
- **Monitor Sidecar**: Tracks memory usage and status, writes to PostgreSQL
- **Traefik Gateway**: Single entry point for all models at `http://localhost:8080/{model-uuid}/`
- **React Dashboard**: Real-time view of all deployed models with status and memory usage
- **CLI Tool**: Simple `infer.py` script for deploying and managing models

## Prerequisites

- Docker
- kubectl
- k3d
- Python 3.9+
- Node.js 18+
- Go 1.20+ (included in tools/)

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd Inference_service

# Complete setup (creates cluster, deploys infra, starts services)
make all
```

### 2. Add Models

Place your `.gguf` model files in the `Model_Catalog/` directory:

```bash
# Example: Download a model
wget -O Model_Catalog/Qwen.gguf <model-url>
```

### 3. Deploy a Model

```bash
# Using make
make serve MODEL=Qwen

# Or using the CLI
python3 infer.py serve Qwen
```

### 4. Access the Model

- **Web UI**: http://localhost:8080/model-qwen-gguf/
- **API**: 
  ```bash
  curl http://localhost:8080/model-qwen-gguf/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"Qwen","messages":[{"role":"user","content":"Hello!"}]}'
  ```

### 5. View Dashboard

Open http://localhost:5173 (or 5174) to see all deployed models with status and memory usage.

## Makefile Commands

### Setup
| Command | Description |
|---------|-------------|
| `make all` | Complete setup from scratch |
| `make deps` | Check and install dependencies |
| `make cluster` | Create k3d cluster |
| `make infra` | Deploy infrastructure (postgres, configs) |
| `make services` | Start backend services |
| `make frontend` | Start frontend dev server |

### Runtime
| Command | Description |
|---------|-------------|
| `make start` | Start all services (cluster must exist) |
| `make stop` | Stop all services |
| `make restart` | Restart all services |
| `make status` | Show system status |
| `make logs` | Show service logs |

### Model Management
| Command | Description |
|---------|-------------|
| `make serve MODEL=<name>` | Deploy a model |
| `make remove MODEL=<name>` | Remove a deployed model |
| `make list` | List all deployed models |

### Cleanup
| Command | Description |
|---------|-------------|
| `make clean` | Stop services and delete cluster |
| `make clean-services` | Stop services only |
| `make cluster-delete` | Delete cluster only |

### Development
| Command | Description |
|---------|-------------|
| `make dev` | Start in development mode |
| `make rebuild-operator` | Rebuild and restart operator |
| `make db-shell` | Open PostgreSQL shell |
| `make db-status` | Show database contents |

## Project Structure

```
Inference_service/
├── Makefile                 # Main build/run orchestration
├── infer.py                 # CLI tool for model management
├── README.md
│
├── fastapi_service/         # Main API service (port 8000)
│   ├── main.py
│   └── requirements.txt
│
├── contract_service/        # K8s contract service (port 8001)
│   ├── main.py
│   └── requirements.txt
│
├── operator/                # Go Kubernetes operator
│   ├── cmd/main.go
│   ├── api/v1alpha1/        # CRD types
│   ├── internal/controller/ # Reconciler logic
│   └── config/              # K8s manifests
│
├── frontend/                # React dashboard
│   ├── src/
│   ├── package.json
│   └── vite.config.js
│
├── infra/                   # Infrastructure configs
│   ├── postgres.yaml        # PostgreSQL deployment
│   ├── monitor-config.yaml  # Monitor sidecar script
│   └── traefik-middlewares.yaml
│
├── Model_Catalog/           # Place .gguf model files here
│   └── .gitkeep
│
└── tools/                   # Pre-bundled tools
    ├── go/                  # Go toolchain
    └── bin/                 # kubebuilder, operator-sdk
```

## Configuration

### Cluster Settings

The k3d cluster is created with:
- Volume mount: `Model_Catalog` → `/home/Inference_service/Model_Catalog`
- Port mapping: `8080:80` (Traefik ingress)
- Relaxed eviction thresholds for low-disk environments

### Database Schema

```sql
CREATE TABLE server_status (
    uuid VARCHAR(255) PRIMARY KEY,
    model_name VARCHAR(255) NOT NULL,
    status VARCHAR(50),
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    memory_usage_mb INT,
    endpoint VARCHAR(255)
);
```

## Troubleshooting

### Services not starting

```bash
# Check status
make status

# View logs
make logs

# Restart everything
make restart
```

### Model not accessible

```bash
# Check pods
kubectl get pods

# Check ingress
kubectl get ingress

# Check middlewares
kubectl get middleware.traefik.io
```

### Database issues

```bash
# Access database
make db-shell

# Check table
make db-status
```

## License

MIT
