# Missing Implementations

## 1. MinIO Availability Check
**Requirement:** FastAPI checks whether the requested model is present in MinIO.
**Current Status:** The `fastapi_service` checks local filesystem (`MODEL_CATALOG_PATH`) instead of MinIO bucket.
**File:** `fastapi_service/main.py`

## 2. Workflow A Trigger
**Requirement:** If model is not present in MinIO, trigger Workflow A (DAG for model retrieval).
**Current Status:** Code raises 404 HTTPException if model is missing locally. No logic to trigger external workflow or DAG.
**File:** `fastapi_service/main.py`

## 3. Fetch Signed URL (DAG)
**Requirement:** A DAG retrieves a signed URL (temporary, time-limited) pointing to the model object in MinIO/S3.
**Current Status:** Component is completely missing. Code notes "No-op in dev, use local path".
**Files:** No DAG service exists.

## 4. On-Prem Download Service
**Requirement:** A dedicated service uses the signed URL to download the model into on-prem MinIO and returns the internal MinIO URL/path and metadata.
**Current Status:** This service is completely missing.
**Files:** No download service exists.

## 5. CR Template - Internal MinIO URL
**Requirement:** CR template should include internal MinIO URL, model name, runtime parameters, configuration options.
**Current Status:** CR template uses local filesystem path (`modelUrl`). Does not reference MinIO URL.
**File:** `fastapi_service/main.py`

## 6. Contract Service - Resource Contract Enforcement
**Requirement:** Contract service must enforce a resource contract for cluster safety, perform authorization checks, and apply CR only if valid.
**Current Status:** Contract service performs basic schema check (kind == "ModelServe") but does not enforce resource contracts or cluster safety policies.
**File:** `contract_service/main.py`

## 7. Operator - Volume Mounting from MinIO
**Requirement:** Operator should download model from internal MinIO URL or use appropriate volume mounting.
**Current Status:** Operator uses `HostPath` volume pointing to local filesystem instead of downloading from MinIO or using internal URL.
**File:** `operator/internal/controller/modelserve_controller.go`

## 8. Authentication - JWT Signature Verification
**Requirement:** Valid JWT token at every step with signature verification.
**Current Status:** Basic token extraction is implemented (`verify_token`), but does not verify JWT signatures or validate against an auth provider. Accepts any token starting with "Bearer ".
**Files:** `fastapi_service/main.py`, `contract_service/main.py`

## 9. Operator Webhook Authentication
**Requirement:** Operator webhooks (if any) must require valid JWT.
**Current Status:** Webhooks are not enabled. Webhook configuration is commented out in kustomization files.
**Files:** `operator/config/crd/kustomization.yaml`, `operator/config/default/kustomization.yaml`

## 10. Gateway Ingress Authentication
**Requirement:** Gateway ingress must require valid JWT.
**Current Status:** Traefik Ingress is created but has no authentication middleware configured.
**File:** `operator/internal/controller/modelserve_controller.go`

## 11. Postgres - Server Records Schema
**Requirement:** Server records must include: server UUID, model UUID being served, model name, runtime parameters, status, memory usage (current + max), CPU usage, timestamps (created_at, started_at, updated_at), Kubernetes pod/service identifiers, gateway URL.
**Current Status:** Schema missing: model UUID, runtime parameters, max memory, CPU usage, created_at, started_at (only start_time exists), pod/service identifiers.
**File:** `infra/postgres.yaml`

## 12. Postgres - Model Records Table
**Requirement:** Model records table must include: model UUID, model name, gguf file path (internal MinIO production path), quantisation/formatting metadata, timestamps.
**Current Status:** Model records table does not exist. No model metadata storage.
**File:** `infra/postgres.yaml`

## 13. Gateway URL Format
**Requirement:** Each server must be accessible via `https://<gateway-host>/<server-UUID>`.
**Current Status:** Uses `http://localhost:8080/<cr-name>/` (HTTP not HTTPS, uses CR name not server UUID).
**Files:** `frontend/src/App.jsx`, `operator/internal/controller/modelserve_controller.go`

## 14. Frontend - Fetch UUID from DB
**Requirement:** When server is clicked, frontend fetches UUID from DB and opens correct gateway URI.
**Current Status:** Frontend uses CR name directly from status endpoint, not a separate UUID lookup.
**File:** `frontend/src/App.jsx`

## 15. Frontend - Display All Required Fields
**Requirement:** Frontend must show server status, timestamps, memory usage, model name, UUID.
**Current Status:** Missing: created_at, started_at, max memory, CPU usage, model UUID (only shows model name).
**File:** `frontend/src/App.jsx`
