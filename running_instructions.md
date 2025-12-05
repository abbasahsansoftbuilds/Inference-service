# LLM Inference Service - Running Instructions

This document provides complete instructions for setting up and running the LLM Inference Service platform.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture-overview)
3. [Quick Start](#quick-start)
4. [Detailed Setup](#detailed-setup)
5. [Configuration](#configuration)
6. [API Usage](#api-usage)
7. [Cross-Cluster Model Download](#cross-cluster-model-download)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

| Software | Minimum Version | Installation |
|----------|----------------|--------------|
| Docker | 20.10+ | [Install Docker](https://docs.docker.com/get-docker/) |
| kubectl | 1.25+ | [Install kubectl](https://kubernetes.io/docs/tasks/tools/) |
| k3d | 5.0+ | [Install k3d](https://k3d.io/v5.6.0/#installation) |
| Python | 3.11+ | [Install Python](https://www.python.org/downloads/) |
| Node.js | 18+ | [Install Node.js](https://nodejs.org/) |
| Go | 1.21+ | [Install Go](https://go.dev/doc/install) |

### System Requirements

- **CPU**: 4+ cores recommended
- **RAM**: 8GB minimum, 16GB recommended
- **Disk**: 50GB+ free space for models and MinIO storage
- **Network**: Internet access for pulling container images

### Verify Prerequisites

```bash
# Run this command to verify all tools are installed
make check-deps
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Inference Service Cluster                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐                │
│  │   FastAPI   │   │  Contract   │   │  Download   │                │
│  │   Service   │   │   Service   │   │   Service   │                │
│  │  (Port 8200)│   │  (Port 8201)│   │  (Port 8202)│                │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘                │
│         │                 │                 │                        │
│         └────────┬────────┴────────┬────────┘                        │
│                  │                 │                                  │
│         ┌───────▼────────┐ ┌──────▼──────┐                          │
│         │   PostgreSQL   │ │    MinIO    │                          │
│         │   (Port 5432)  │ │ (Port 9000) │                          │
│         └────────────────┘ └─────────────┘                          │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Kubernetes Operator                        │    │
│  │  - Creates ModelServe CRDs                                   │    │
│  │  - Manages llama.cpp deployments                             │    │
│  │  - Creates Services and Ingresses                            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Traefik Ingress                            │    │
│  │                    (Port 8080)                                │    │
│  │       http://localhost:8080/{server-uuid}/                    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      Quant Service Cluster                           │
│                        (External/Cloud)                              │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐               │
│  │  Quant API  │   │    MinIO    │   │    Argo     │               │
│  │ (Port 8300) │   │    (9000)   │   │  Workflows  │               │
│  └─────────────┘   └─────────────┘   └─────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| FastAPI Service | 8200 | Main API gateway for model management |
| Contract Service | 8201 | Policy enforcement and resource contracts |
| Download Service | 8202 | Model download from Quant service |
| PostgreSQL | 5432 | Database for server and model records |
| MinIO | 9000/9001 | Object storage for model files |
| Traefik Gateway | 8080 | Ingress for model inference endpoints |
| Frontend | 5173 | React-based management UI |

---

## Quick Start

### One-Command Setup

```bash
cd Inference_service
make all
```

This command will:
1. Check and install dependencies
2. Create the k3d cluster
3. Build Docker images
4. Deploy infrastructure (PostgreSQL, MinIO, ConfigMaps, Secrets)
5. Deploy the Kubernetes operator
6. Deploy all services
7. Start the frontend

### Access the Services

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| FastAPI | http://localhost:8200 |
| MinIO Console | http://localhost:9001 |
| Model Gateway | http://localhost:8080/{server-uuid}/ |

### Default Credentials

| Service | Username | Password |
|---------|----------|----------|
| Frontend/API | admin | admin |
| MinIO | minioadmin | minioadmin123 |
| PostgreSQL | admin | securepassword123 |

---

## Detailed Setup

### Step 1: Install Dependencies

```bash
make deps
```

This creates a Python virtual environment and installs all required packages.

### Step 2: Create Kubernetes Cluster

```bash
make cluster
```

Creates a k3d cluster named `inference-cluster` with:
- Port 8080 mapped to load balancer
- Ports 9000/9001 for MinIO (if NodePort is used)

### Step 3: Build Docker Images

```bash
make docker-build
```

Builds three Docker images:
- `inference-fastapi:latest`
- `inference-contract:latest`
- `inference-download:latest`

### Step 4: Load Images into Cluster

```bash
make docker-load
```

Imports the Docker images into the k3d cluster.

### Step 5: Deploy Infrastructure

```bash
make infra
```

Deploys:
- PostgreSQL with proper schema
- MinIO object storage
- ConfigMaps and Secrets
- Traefik middlewares
- Monitor script ConfigMap

### Step 6: Deploy Operator

```bash
make operator-deploy
```

Builds and deploys the Kubernetes operator that manages ModelServe CRDs.

### Step 7: Deploy Services

```bash
make services-deploy
```

Deploys all FastAPI services to Kubernetes.

### Step 8: Start Frontend

```bash
make frontend
```

Starts the React development server.

---

## Configuration

### Environment Variables

All configuration is managed through Kubernetes ConfigMaps and Secrets.

#### ConfigMap: `inference-config`

```yaml
# PostgreSQL
DATABASE_URL: "postgresql://admin:password@postgres:5432/inference_db"

# MinIO
MINIO_ENDPOINT: "minio:9000"
MINIO_BUCKET: "inference-models"
MINIO_SECURE: "false"

# Quant Service (external)
QUANT_SERVICE_URL: "http://quant-api.llm.svc.cluster.local:8300"

# JWT
JWT_ALGORITHM: "HS256"
JWT_EXPIRY_HOURS: "24"

# Resource Limits
MAX_REPLICAS: "5"
ALLOWED_NAMESPACES: "default,inference"
```

#### Secrets: `inference-secrets`

```yaml
POSTGRES_USER: "admin"
POSTGRES_PASSWORD: "securepassword123"
MINIO_ACCESS_KEY: "minioadmin"
MINIO_SECRET_KEY: "minioadmin123"
JWT_SECRET: "your-super-secret-jwt-key-change-in-production-minimum-32-chars"
```

### Modifying Configuration

1. Edit the YAML files in `infra/`:
   - `infra/configmap.yaml`
   - `infra/secrets.yaml`

2. Apply changes:
   ```bash
   kubectl apply -f infra/configmap.yaml
   kubectl apply -f infra/secrets.yaml
   kubectl rollout restart deployment -l app=fastapi-service
   ```

---

## API Usage

### Authentication

All API endpoints (except `/health`) require JWT authentication.

#### Get JWT Token

```bash
curl -X POST http://localhost:8200/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

#### Use Token in Requests

```bash
export TOKEN="eyJhbGciOiJIUzI1NiIs..."

curl http://localhost:8200/status \
  -H "Authorization: Bearer $TOKEN"
```

### API Endpoints

#### List Available Models

```bash
curl http://localhost:8200/models \
  -H "Authorization: Bearer $TOKEN"
```

#### Serve a Model

```bash
curl -X POST http://localhost:8200/serve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_uuid": "abc123-def456-...",
    "model_name": "Qwen.gguf",
    "replicas": 1,
    "runtime_params": "--ctx-size 2048"
  }'
```

#### Check Server Status

```bash
curl http://localhost:8200/status \
  -H "Authorization: Bearer $TOKEN"
```

#### Stop a Server

```bash
curl -X DELETE http://localhost:8200/stop/{server_uuid} \
  -H "Authorization: Bearer $TOKEN"
```

### Using the Model

Once a model is running, access it through the Traefik gateway:

```bash
# Chat completion
curl http://localhost:8080/{server-uuid}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'

# Text completion
curl http://localhost:8080/{server-uuid}/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Hello, how are you?",
    "max_tokens": 100
  }'
```

---

## Cross-Cluster Model Download

Models are stored in the Quant service's MinIO and need to be downloaded to the Inference service's MinIO before serving.

### Download Process

1. **Request Download from Quant Service**:
   ```bash
   curl -X POST http://localhost:8202/download/{model_uuid} \
     -H "Authorization: Bearer $TOKEN"
   ```

2. **Check Download Status**:
   ```bash
   curl http://localhost:8202/status/{model_uuid} \
     -H "Authorization: Bearer $TOKEN"
   ```

3. **Model appears in `/models` endpoint once downloaded**

### Flow Diagram

```
Quant Service MinIO  ──────>  Download Service  ──────>  Inference MinIO
(llm-models bucket)      (streaming download)      (inference-models bucket)
        │                        │                           │
        │                        ▼                           │
        │              Creates ModelRecord                   │
        │              in PostgreSQL                         │
        │                        │                           │
        └────────────────────────┴───────────────────────────┘
                                 │
                                 ▼
                     Model ready to serve via
                     /serve endpoint
```

---

## Troubleshooting

### Common Issues

#### 1. Cluster not starting

```bash
# Check Docker is running
docker ps

# Delete and recreate cluster
make cluster-delete
make cluster
```

#### 2. Services not connecting to database

```bash
# Check PostgreSQL is ready
kubectl get pods -l app=postgres
kubectl logs deploy/postgres

# Restart port forward
make port-forward
```

#### 3. Images not loading into cluster

```bash
# Rebuild and reload images
make docker-build
make docker-load

# Check images are available
docker exec -it k3d-inference-cluster-server-0 crictl images
```

#### 4. Operator not creating resources

```bash
# Check operator logs
tail -f /tmp/operator.log

# Restart operator
make rebuild-operator
```

#### 5. JWT Token Invalid

```bash
# Ensure JWT_SECRET matches across all services
kubectl get secret inference-secrets -o jsonpath='{.data.JWT_SECRET}' | base64 -d
```

### Useful Commands

```bash
# Check system status
make status

# View all logs
make logs

# View Kubernetes pod logs
make logs-k8s

# Open database shell
make db-shell

# Check database contents
make db-status

# Restart all services
make restart
```

### Log Locations

| Log | Location |
|-----|----------|
| FastAPI | `/tmp/fastapi_service.log` |
| Contract | `/tmp/contract_service.log` |
| Download | `/tmp/download_service.log` |
| Operator | `/tmp/operator.log` |
| Frontend | `/tmp/frontend.log` |

---

## Cleanup

### Stop All Services

```bash
make stop
```

### Full Cleanup

```bash
make clean
```

This stops all services and deletes the k3d cluster.

---

## Production Considerations

1. **Secrets Management**: Use Kubernetes Secrets with proper RBAC or external secret managers like HashiCorp Vault.

2. **JWT Secret**: Generate a strong, random JWT secret (minimum 32 characters).

3. **Database**: Consider using managed PostgreSQL (RDS, Cloud SQL) for production.

4. **MinIO**: Consider using managed object storage (S3, GCS) for production.

5. **Resource Limits**: Adjust memory and CPU limits in `infra/services.yaml` based on your model sizes.

6. **Monitoring**: Add Prometheus metrics and Grafana dashboards for observability.

7. **TLS**: Configure TLS certificates for all external endpoints.

8. **Network Policies**: Implement Kubernetes network policies to restrict pod-to-pod communication.
