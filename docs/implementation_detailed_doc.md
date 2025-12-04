# Model Inference Service - Detailed Implementation Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Component Details](#component-details)
   - [FastAPI Service](#1-fastapi-service)
   - [Contract Service](#2-contract-service)
   - [Kubernetes Operator](#3-kubernetes-operator)
   - [Model Catalog](#4-model-catalog)
4. [Custom Resource Definition (CRD)](#custom-resource-definition-crd)
5. [Request Flow](#request-flow)
6. [Authentication](#authentication)
7. [Development vs Production Mode](#development-vs-production-mode)
8. [Deployment Artifacts](#deployment-artifacts)
9. [Running the System](#running-the-system)

---

## System Overview

This system provides an end-to-end solution for deploying and serving Large Language Models (LLMs) in GGUF format using Kubernetes. It follows a microservices architecture with three main components that work together to validate, deploy, and serve models on-demand.

The system uses **llama.cpp's llama-server** as the inference runtime, which efficiently serves quantized GGUF models with support for both CPU and GPU inference.

---

## Architecture

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   User/Client   │────▶│   FastAPI Service   │────▶│  Contract Service   │
│                 │     │     (Port 8000)     │     │     (Port 8001)     │
└─────────────────┘     └─────────────────────┘     └──────────┬──────────┘
                                                               │
                                                               ▼
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Model Catalog  │◀───▶│  Kubernetes Cluster │◀────│   ModelServe CRD    │
│ (Local Storage) │     │                     │     └─────────────────────┘
└─────────────────┘     │  ┌───────────────┐  │
                        │  │   Operator    │  │
                        │  │  (Reconciler) │  │
                        │  └───────┬───────┘  │
                        │          ▼          │
                        │  ┌───────────────┐  │
                        │  │  Deployment   │  │
                        │  │ (llama-server)│  │
                        │  └───────────────┘  │
                        └─────────────────────┘
```

---

## Component Details

### 1. FastAPI Service

**Location:** `/home/Inference_service/fastapi_service/`

**Purpose:** Acts as the API gateway and entry point for all model serving requests. It handles user authentication, model availability validation, and initiates the deployment workflow.

**Port:** 8000

**Key Responsibilities:**

- **Request Handling:** Exposes a `GET /serve` endpoint that accepts a model name as a query parameter
- **JWT Authentication:** Validates that all incoming requests contain a valid Bearer token in the Authorization header
- **Model Availability Check:** Verifies that the requested model exists in the Model Catalog before proceeding
- **CR Template Generation:** Creates a Kubernetes Custom Resource (CR) template with all necessary deployment parameters
- **Contract Service Communication:** Forwards the CR template to the Contract Service for validation and application

**Endpoint Details:**

| Endpoint | Method | Parameters | Headers Required |
|----------|--------|------------|------------------|
| `/serve` | GET | `model` (query param) | `Authorization: Bearer <token>` |

**CR Template Structure Generated:**
```
- apiVersion: model.example.com/v1alpha1
- kind: ModelServe
- metadata: name (derived from model name), namespace (default)
- spec: modelName, modelUrl (local path), replicas
```

**Dependencies:**
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `requests` - HTTP client for Contract Service communication
- `pydantic` - Data validation
- `python-jose` - JWT handling (prepared for future use)

---

### 2. Contract Service

**Location:** `/home/Inference_service/contract_service/`

**Purpose:** Acts as a policy enforcement and validation layer between the FastAPI service and Kubernetes. It ensures that only valid, authorized Custom Resources are applied to the cluster.

**Port:** 8001

**Key Responsibilities:**

- **Authorization Verification:** Re-validates the JWT token passed from FastAPI to ensure the request chain is authenticated
- **Schema Validation:** Verifies that the incoming CR conforms to the expected structure (kind must be "ModelServe")
- **Policy Enforcement:** Placeholder for resource limits, quotas, and organizational policies
- **Kubernetes Apply:** Uses the Kubernetes Python client to create or update Custom Resources in the cluster
- **Idempotent Operations:** Handles both creation of new resources and updates to existing ones

**Endpoint Details:**

| Endpoint | Method | Body | Headers Required |
|----------|--------|------|------------------|
| `/apply` | POST | CR JSON object | `Authorization: Bearer <token>` |

**Kubernetes Integration:**
- Uses `kubernetes.client.dynamic.DynamicClient` for flexible CR manipulation
- Supports both in-cluster and out-of-cluster (kubeconfig) authentication
- Implements create-or-update logic: attempts creation first, falls back to update if resource exists

**Response Behavior:**
- Returns success with action taken ("created" or "updated")
- Returns 400 for invalid CR kind
- Returns 401 for missing/invalid authorization
- Returns 500 for Kubernetes API failures

**Dependencies:**
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `kubernetes` - Official Kubernetes Python client
- `pydantic` - Data validation

---

### 3. Kubernetes Operator

**Location:** `/home/Inference_service/operator/`

**Purpose:** A Go-based Kubernetes operator that watches for ModelServe Custom Resources and reconciles the cluster state to match the desired state by creating Deployments and Services.

**Built With:** Kubebuilder framework

**Key Responsibilities:**

- **CR Watching:** Continuously monitors the cluster for new, updated, or deleted ModelServe resources
- **Reconciliation:** Ensures the actual cluster state matches the desired state defined in the CR
- **Deployment Creation:** Creates Kubernetes Deployments running llama-server containers
- **Service Creation:** Creates ClusterIP Services to expose the model endpoints
- **Status Management:** Updates the CR status with the current number of available replicas
- **Owner References:** Establishes ownership so that deleting a CR cascades to its Deployment and Service

**Reconciliation Logic:**

1. Fetch the ModelServe CR by name/namespace
2. If CR not found (deleted), return without error
3. Build a Deployment specification based on CR spec
4. Check if Deployment exists:
   - If not, create it and requeue
   - If yes, continue
5. Build a Service specification
6. Check if Service exists:
   - If not, create it and requeue
   - If yes, continue
7. Update CR status with deployment's available replicas

**Deployment Specification:**

| Field | Value |
|-------|-------|
| Container Image | `ghcr.io/ggerganov/llama.cpp:server` (default) or custom from CR |
| Container Port | 8080 |
| Volume Mount | `/models` (maps to host's Model Catalog) |
| Command Args | `-m /models/<modelName> --host 0.0.0.0 --port 8080` |
| Replicas | From CR spec (default: 1) |

**Service Specification:**

| Field | Value |
|-------|-------|
| Type | ClusterIP |
| Port | 80 → 8080 (target) |
| Selector | Labels matching the Deployment |

**RBAC Permissions:**
- Full access to `modelserves` (CRD resources)
- Full access to `deployments` (apps/v1)
- Full access to `services` (core/v1)

---

### 4. Model Catalog

**Location:** `/home/Inference_service/Model_Catalog/`

**Purpose:** Local storage directory containing all available GGUF model files that can be served.

**Current Contents:**
- `Qwen.gguf` - Qwen model in GGUF format
- `qwen.gguf` - Alternative Qwen model file
- `SmolLM2.gguf` - SmolLM2 135M Instruct model
- `test-model.gguf` - Test model file
- `test-model/` - Test model directory

**Volume Mounting:**
In development mode, this directory is mounted into pods via Kubernetes HostPath volumes at `/models`. The llama-server container accesses model files from this mounted path.

---

## Custom Resource Definition (CRD)

**Location:** `/home/Inference_service/operator/config/crd/bases/`

**API Group:** `model.example.com`  
**Version:** `v1alpha1`  
**Kind:** `ModelServe`

**Spec Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `modelName` | string | Yes | Name of the model file (e.g., "Qwen.gguf") |
| `modelUrl` | string | Yes | URL or local path to the model file |
| `image` | string | No | Container image override (default: llama.cpp server) |
| `replicas` | int32 | No | Number of replicas (default: 1) |

**Status Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `availableReplicas` | int32 | Current number of available pod replicas |

**Example CR:**
```yaml
apiVersion: model.example.com/v1alpha1
kind: ModelServe
metadata:
  name: model-qwen.gguf
  namespace: default
spec:
  modelName: Qwen.gguf
  modelUrl: /home/Inference_service/Model_Catalog/Qwen.gguf
  replicas: 1
```

---

## Request Flow

### Step-by-Step Walkthrough

**Step 1: User Initiates Request**
```
GET http://localhost:8000/serve?model=Qwen.gguf
Authorization: Bearer <jwt-token>
```

**Step 2: FastAPI Validates Token**
- Extracts token from Authorization header
- Verifies "Bearer " prefix exists
- (Future: validates JWT signature and claims)

**Step 3: Model Availability Check**
- Constructs path: `/home/Inference_service/Model_Catalog/Qwen.gguf`
- Checks if file or directory exists at that path
- Returns 404 if model not found

**Step 4: CR Template Creation**
- Generates CR name: `model-qwen.gguf` (lowercase, hyphens)
- Populates spec with model name, local path, default replicas
- Sets namespace to "default"

**Step 5: Contract Service Submission**
- POSTs CR JSON to `http://localhost:8001/apply`
- Includes original Bearer token in request

**Step 6: Contract Service Validation**
- Re-validates authorization header
- Checks CR kind equals "ModelServe"
- (Future: enforces resource quotas and policies)

**Step 7: Kubernetes Apply**
- Uses dynamic client to interact with ModelServe API
- Attempts to GET existing resource by name
- If not found: CREATE new resource
- If found: UPDATE with new spec (preserves resourceVersion)

**Step 8: Operator Detects CR**
- Controller-runtime watch triggers on CR create/update
- Reconcile function invoked with CR namespace/name

**Step 9: Deployment Reconciliation**
- Operator builds Deployment spec from CR
- Creates Deployment if not exists
- Deployment creates Pod with llama-server container

**Step 10: Service Reconciliation**
- Operator builds Service spec from CR
- Creates Service if not exists
- Service provides stable endpoint for model

**Step 11: Model Loading**
- Pod starts, mounts Model Catalog via HostPath
- llama-server loads GGUF model into memory
- Server begins listening on port 8080

**Step 12: Ready for Inference**
- Model is accessible via Service ClusterIP:80
- Or via port-forward to Deployment:8080
- Supports OpenAI-compatible `/v1/chat/completions` API

---

## Authentication

### Current Implementation

All three services implement JWT token validation:

**FastAPI Service:**
- Requires `Authorization: Bearer <token>` header
- Extracts and validates token format
- Passes token to Contract Service

**Contract Service:**
- Requires `Authorization: Bearer <token>` header
- Re-validates token before applying CR
- Ensures authenticated request chain

**Operator:**
- Uses Kubernetes RBAC for authorization
- ServiceAccount with appropriate ClusterRole bindings
- No external authentication (cluster-internal only)

### Token Validation Logic
```
1. Check Authorization header exists
2. Verify header starts with "Bearer "
3. Extract token after "Bearer "
4. (Stub) Accept token as valid
```

**Note:** Current implementation accepts any well-formed token. Production deployment should implement full JWT signature verification using a shared secret or public key.

---

## Development vs Production Mode

### Development Mode (Current)

| Aspect | Development Behavior |
|--------|---------------------|
| Model Storage | Local filesystem (`/home/Inference_service/Model_Catalog`) |
| Signed URLs | No-op, uses local file paths directly |
| Volume Mounting | HostPath volumes pointing to local directory |
| Kubernetes | Local cluster (k3s, minikube, kind, etc.) |
| Authentication | Stub validation (any token accepted) |
| Services | Run directly via `python main.py` or `go run` |

### Production Mode (Future)

| Aspect | Production Behavior |
|--------|---------------------|
| Model Storage | MinIO/S3 object storage |
| Signed URLs | Pre-signed URLs with expiration for secure access |
| Volume Mounting | Init containers download from signed URL, or CSI drivers |
| Kubernetes | Production cluster with proper node pools |
| Authentication | Full JWT validation with identity provider |
| Services | Containerized, deployed via Helm/Kustomize |

---

## Deployment Artifacts

### Service PID Files

Each service writes its process ID to a file for management:

| Service | PID File |
|---------|----------|
| FastAPI | `/home/Inference_service/fastapi_service/fastapi.pid` |
| Contract | `/home/Inference_service/contract_service/contract.pid` |
| Operator | `/home/Inference_service/operator/operator.pid` |

### Kubernetes Resources Created

For each model served, the following resources are created:

| Resource | Naming Convention | Example |
|----------|-------------------|---------|
| ModelServe CR | `model-<name>` | `model-qwen.gguf` |
| Deployment | `model-<name>` | `model-qwen.gguf` |
| Service | `model-<name>` | `model-qwen.gguf` |
| Pod | `model-<name>-<hash>-<id>` | `model-qwen.gguf-88bd4d75-4dkdw` |

### Labels Applied

All resources are labeled for selection and identification:
```
app: model-serve
model_serve_cr: <cr-name>
```

---

## Running the System

### Prerequisites
- Python 3.8+ with pip
- Go 1.19+
- Kubernetes cluster (local or remote)
- kubectl configured
- CRD installed in cluster

### Starting Services

**1. Install CRD:**
```bash
cd /home/Inference_service/operator
kubectl apply -f config/crd/bases/
```

**2. Start FastAPI Service:**
```bash
cd /home/Inference_service/fastapi_service
pip install -r requirements.txt
python main.py
# Runs on port 8000
```

**3. Start Contract Service:**
```bash
cd /home/Inference_service/contract_service
pip install -r requirements.txt
python main.py
# Runs on port 8001
```

**4. Start Operator:**
```bash
cd /home/Inference_service/operator
go run ./cmd/main.go
# Watches cluster for ModelServe CRs
```

### Serving a Model

**1. Ensure model exists:**
```bash
ls /home/Inference_service/Model_Catalog/
```

**2. Request deployment:**
```bash
curl -X GET "http://localhost:8000/serve?model=<model-name>.gguf" \
     -H "Authorization: Bearer any-token"
```

**3. Check deployment status:**
```bash
kubectl get modelserves,deployments,pods -n default
```

**4. Access model for inference:**
```bash
# Port forward
kubectl port-forward deployment/model-<name>.gguf 8888:8080

# Make inference request
curl -X POST "http://localhost:8888/v1/chat/completions" \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"Hello"}],"max_tokens":50}'
```

### Stopping Services

```bash
# Kill by PID
kill $(cat /home/Inference_service/fastapi_service/fastapi.pid)
kill $(cat /home/Inference_service/contract_service/contract.pid)
kill $(cat /home/Inference_service/operator/operator.pid)

# Remove deployments
kubectl delete modelserve --all -n default
```

---

## Directory Structure Reference

```
/home/Inference_service/
├── Model_Catalog/              # GGUF model files
│   ├── Qwen.gguf
│   ├── SmolLM2.gguf
│   └── ...
├── fastapi_service/            # API Gateway
│   ├── main.py                 # FastAPI application
│   ├── requirements.txt        # Python dependencies
│   └── fastapi.pid             # Process ID file
├── contract_service/           # Policy & Apply Service
│   ├── main.py                 # Contract service application
│   ├── requirements.txt        # Python dependencies
│   └── contract.pid            # Process ID file
├── operator/                   # Kubernetes Operator
│   ├── api/v1alpha1/           # CRD Go types
│   │   ├── modelserve_types.go # ModelServe struct definitions
│   │   └── groupversion_info.go
│   ├── cmd/main.go             # Operator entrypoint
│   ├── internal/controller/    # Reconciliation logic
│   │   └── modelserve_controller.go
│   ├── config/                 # Kubernetes manifests
│   │   ├── crd/bases/          # CRD YAML
│   │   ├── rbac/               # RBAC rules
│   │   └── manager/            # Operator deployment
│   ├── go.mod                  # Go dependencies
│   └── Makefile                # Build commands
└── tools/                      # Development tools
    ├── bin/                    # Binaries (kubebuilder, operator-sdk)
    └── go/                     # Go installation
```

---

## Summary

This implementation provides a complete model serving pipeline that:

1. **Accepts** authenticated requests for model deployment
2. **Validates** model availability and request parameters
3. **Enforces** policies through a dedicated contract service
4. **Deploys** models as Kubernetes-native Custom Resources
5. **Reconciles** the cluster state via a dedicated operator
6. **Serves** models using the efficient llama.cpp runtime
7. **Exposes** OpenAI-compatible inference endpoints

The architecture separates concerns cleanly: FastAPI handles user interaction, Contract Service handles policy, and the Operator handles Kubernetes orchestration. This separation allows each component to evolve independently and enables fine-grained access control at each layer.
