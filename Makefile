# ============================================================================
# LLM Inference Service - Complete Setup Makefile
# ============================================================================
# This Makefile provides commands to set up and manage the entire application
# including cluster creation, service deployment, and model management.
#
# Usage:
#   make help           - Show all available commands
#   make all            - Complete setup from scratch
#   make start          - Start all services (cluster must exist)
#   make stop           - Stop all services
#   make clean          - Remove everything including cluster
# ============================================================================

.PHONY: all help deps check-deps cluster cluster-delete infra operator services \
        frontend start stop clean status serve-model clean-model list-models \
        venv install-python-deps install-frontend-deps port-forward logs \
        docker-build docker-push docker-load

# Configuration
CLUSTER_NAME := inference-cluster
VENV := $(PWD)/.venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
GO_PATH := $(PWD)/tools/go/bin
OPERATOR_DIR := $(PWD)/operator
FRONTEND_DIR := $(PWD)/frontend
FASTAPI_DIR := $(PWD)/fastapi_service
CONTRACT_DIR := $(PWD)/contract_service
DOWNLOAD_DIR := $(PWD)/download_service
SHARED_DIR := $(PWD)/shared
INFRA_DIR := $(PWD)/infra

# Docker image names
FASTAPI_IMAGE := inference-fastapi:latest
CONTRACT_IMAGE := inference-contract:latest
DOWNLOAD_IMAGE := inference-download:latest

# PID files for service management
PID_DIR := /tmp/inference_service
FASTAPI_PID := $(PID_DIR)/fastapi.pid
CONTRACT_PID := $(PID_DIR)/contract.pid
DOWNLOAD_PID := $(PID_DIR)/download.pid
OPERATOR_PID := $(PID_DIR)/operator.pid
FRONTEND_PID := $(PID_DIR)/frontend.pid
POSTGRES_PF_PID := $(PID_DIR)/postgres_pf.pid
MINIO_PF_PID := $(PID_DIR)/minio_pf.pid

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
BLUE := \033[0;34m
NC := \033[0m # No Color

# ============================================================================
# MAIN TARGETS
# ============================================================================

## all: Complete setup from scratch (deps + cluster + infra + services)
all: deps cluster docker-build docker-load infra operator-deploy services-deploy frontend
	@echo ""
	@echo "$(GREEN)============================================$(NC)"
	@echo "$(GREEN)  Setup Complete!$(NC)"
	@echo "$(GREEN)============================================$(NC)"
	@echo ""
	@echo "Services running:"
	@echo "  - FastAPI:     http://localhost:8200"
	@echo "  - Contract:    http://localhost:8201"
	@echo "  - Download:    http://localhost:8202"
	@echo "  - Frontend:    http://localhost:5173"
	@echo "  - Gateway:     http://localhost:8080/{server-uuid}/"
	@echo "  - MinIO:       http://localhost:9000 (API)"
	@echo "  - MinIO UI:    http://localhost:9001 (Console)"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Login to the frontend at http://localhost:5173"
	@echo "  2. Download models from Quant service"
	@echo "  3. Serve models through the UI or API"
	@echo ""
	@echo "API Examples:"
	@echo "  # Get JWT token"
	@echo "  curl -X POST http://localhost:8200/auth/token \\"
	@echo "    -H 'Content-Type: application/json' \\"
	@echo "    -d '{\"username\": \"admin\", \"password\": \"admin\"}'"
	@echo ""
	@echo "  # Serve a model"
	@echo "  curl -X POST http://localhost:8200/serve \\"
	@echo "    -H 'Authorization: Bearer <token>' \\"
	@echo "    -H 'Content-Type: application/json' \\"
	@echo "    -d '{\"model_uuid\": \"<uuid>\", \"model_name\": \"Qwen.gguf\"}'"
	@echo ""

## help: Show this help message
help:
	@echo "LLM Inference Service - Makefile Commands"
	@echo "=========================================="
	@echo ""
	@echo "$(BLUE)Setup Commands:$(NC)"
	@echo "  make all                - Complete setup from scratch"
	@echo "  make deps               - Check and install dependencies"
	@echo "  make cluster            - Create k3d cluster"
	@echo "  make docker-build       - Build all Docker images"
	@echo "  make docker-load        - Load images into k3d cluster"
	@echo "  make infra              - Deploy infrastructure (postgres, minio, configs)"
	@echo "  make operator-deploy    - Deploy the Kubernetes operator"
	@echo "  make services-deploy    - Deploy all backend services to K8s"
	@echo "  make frontend           - Start frontend dev server"
	@echo ""
	@echo "$(BLUE)Local Development Commands:$(NC)"
	@echo "  make services-local     - Start services locally (not in K8s)"
	@echo "  make start              - Start all services locally"
	@echo "  make stop               - Stop all local services"
	@echo "  make restart            - Restart all local services"
	@echo ""
	@echo "$(BLUE)Runtime Commands:$(NC)"
	@echo "  make status             - Show system status"
	@echo "  make logs               - Show service logs"
	@echo "  make port-forward       - Setup port forwarding for K8s services"
	@echo ""
	@echo "$(BLUE)Cleanup Commands:$(NC)"
	@echo "  make clean              - Stop services and delete cluster"
	@echo "  make clean-services     - Stop local services only"
	@echo "  make cluster-delete     - Delete cluster only"
	@echo ""

# ============================================================================
# DEPENDENCY CHECKS
# ============================================================================

## deps: Check and install all dependencies
deps: check-deps venv install-python-deps install-frontend-deps
	@echo "$(GREEN)✓ All dependencies installed$(NC)"

## check-deps: Verify required tools are installed
check-deps:
	@echo "Checking dependencies..."
	@command -v docker >/dev/null 2>&1 || { echo "$(RED)✗ Docker is required but not installed$(NC)"; exit 1; }
	@command -v kubectl >/dev/null 2>&1 || { echo "$(RED)✗ kubectl is required but not installed$(NC)"; exit 1; }
	@command -v k3d >/dev/null 2>&1 || { echo "$(RED)✗ k3d is required but not installed$(NC)"; exit 1; }
	@command -v python3 >/dev/null 2>&1 || { echo "$(RED)✗ python3 is required but not installed$(NC)"; exit 1; }
	@command -v node >/dev/null 2>&1 || { echo "$(RED)✗ node is required but not installed$(NC)"; exit 1; }
	@command -v npm >/dev/null 2>&1 || { echo "$(RED)✗ npm is required but not installed$(NC)"; exit 1; }
	@echo "$(GREEN)✓ All required tools are installed$(NC)"

## venv: Create Python virtual environment
venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating Python virtual environment..."; \
		python3 -m venv $(VENV); \
		echo "$(GREEN)✓ Virtual environment created$(NC)"; \
	else \
		echo "$(YELLOW)→ Virtual environment already exists$(NC)"; \
	fi

## install-python-deps: Install Python dependencies
install-python-deps: venv
	@echo "Installing Python dependencies..."
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r $(FASTAPI_DIR)/requirements.txt
	@$(PIP) install --quiet -r $(CONTRACT_DIR)/requirements.txt
	@$(PIP) install --quiet -r $(DOWNLOAD_DIR)/requirements.txt
	@echo "$(GREEN)✓ Python dependencies installed$(NC)"

## install-frontend-deps: Install frontend dependencies
install-frontend-deps:
	@echo "Installing frontend dependencies..."
	@cd $(FRONTEND_DIR) && npm install --silent
	@echo "$(GREEN)✓ Frontend dependencies installed$(NC)"

# ============================================================================
# CLUSTER MANAGEMENT
# ============================================================================

## cluster: Create k3d cluster with proper configuration
cluster:
	@echo "Creating k3d cluster..."
	@if k3d cluster list 2>/dev/null | grep -q $(CLUSTER_NAME); then \
		echo "$(YELLOW)→ Cluster '$(CLUSTER_NAME)' already exists$(NC)"; \
	else \
		k3d cluster create $(CLUSTER_NAME) \
			--port "8080:80@loadbalancer" \
			--port "9000:30900@server:0" \
			--port "9001:30901@server:0" \
			--k3s-arg "--kubelet-arg=eviction-hard=nodefs.available<3%,imagefs.available<3%,memory.available<100Mi@server:0" \
			--wait; \
		echo "$(GREEN)✓ Cluster created$(NC)"; \
	fi
	@echo "Waiting for cluster to be ready..."
	@kubectl wait --for=condition=ready node --all --timeout=120s
	@echo "$(GREEN)✓ Cluster is ready$(NC)"

## cluster-delete: Delete the k3d cluster
cluster-delete:
	@echo "Deleting k3d cluster..."
	@k3d cluster delete $(CLUSTER_NAME) 2>/dev/null || true
	@echo "$(GREEN)✓ Cluster deleted$(NC)"

# ============================================================================
# DOCKER BUILD
# ============================================================================

## docker-build: Build all Docker images
docker-build:
	@echo "Building Docker images..."
	@echo "Building FastAPI service..."
	@docker build -t $(FASTAPI_IMAGE) -f $(FASTAPI_DIR)/Dockerfile $(PWD)
	@echo "Building Contract service..."
	@docker build -t $(CONTRACT_IMAGE) -f $(CONTRACT_DIR)/Dockerfile $(PWD)
	@echo "Building Download service..."
	@docker build -t $(DOWNLOAD_IMAGE) -f $(DOWNLOAD_DIR)/Dockerfile $(PWD)
	@echo "$(GREEN)✓ All Docker images built$(NC)"

## docker-load: Load Docker images into k3d cluster
docker-load:
	@echo "Loading Docker images into k3d cluster..."
	@k3d image import $(FASTAPI_IMAGE) -c $(CLUSTER_NAME)
	@k3d image import $(CONTRACT_IMAGE) -c $(CLUSTER_NAME)
	@k3d image import $(DOWNLOAD_IMAGE) -c $(CLUSTER_NAME)
	@echo "$(GREEN)✓ Images loaded into cluster$(NC)"

# ============================================================================
# INFRASTRUCTURE
# ============================================================================

## infra: Deploy infrastructure components (CRD, postgres, minio, configs)
infra: crd secrets configmap postgres-deploy minio-deploy traefik-middlewares jwt-auth-middleware monitor-script
	@echo "$(GREEN)✓ Infrastructure deployed$(NC)"

## crd: Apply the ModelServe CRD
crd:
	@echo "Applying CRD..."
	@kubectl apply -f $(OPERATOR_DIR)/config/crd/bases/ 2>/dev/null || kubectl apply -f $(PWD)/infra/modelserve-crd.yaml
	@echo "$(GREEN)✓ CRD applied$(NC)"

## secrets: Apply secrets
secrets:
	@echo "Applying secrets..."
	@kubectl apply -f $(INFRA_DIR)/secrets.yaml
	@echo "$(GREEN)✓ Secrets applied$(NC)"

## configmap: Apply configmaps
configmap:
	@echo "Applying configmaps..."
	@kubectl apply -f $(INFRA_DIR)/configmap.yaml
	@echo "$(GREEN)✓ ConfigMap applied$(NC)"

## postgres-deploy: Deploy PostgreSQL
postgres-deploy:
	@echo "Deploying PostgreSQL..."
	@kubectl apply -f $(INFRA_DIR)/postgres.yaml
	@echo "Waiting for PostgreSQL to be ready..."
	@kubectl wait --for=condition=ready pod -l app=postgres --timeout=180s 2>/dev/null || sleep 15
	@echo "$(GREEN)✓ PostgreSQL deployed$(NC)"

## minio-deploy: Deploy MinIO
minio-deploy:
	@echo "Deploying MinIO..."
	@kubectl apply -f $(INFRA_DIR)/minio.yaml
	@echo "Waiting for MinIO to be ready..."
	@kubectl wait --for=condition=ready pod -l app=minio --timeout=180s 2>/dev/null || sleep 15
	@echo "$(GREEN)✓ MinIO deployed$(NC)"

## monitor-script: Deploy monitor script ConfigMap
monitor-script:
	@echo "Deploying monitor script..."
	@kubectl apply -f $(INFRA_DIR)/monitor-script.yaml
	@echo "$(GREEN)✓ Monitor script deployed$(NC)"

## traefik-middlewares: Apply Traefik middlewares
traefik-middlewares:
	@echo "Applying Traefik middlewares..."
	@kubectl apply -f $(INFRA_DIR)/traefik-middlewares.yaml 2>/dev/null || true
	@echo "$(GREEN)✓ Traefik middlewares applied$(NC)"

## jwt-auth-middleware: Deploy JWT auth middleware for gateway
jwt-auth-middleware:
	@echo "Deploying JWT auth middleware..."
	@kubectl apply -f $(INFRA_DIR)/jwt-auth-middleware.yaml
	@echo "Waiting for JWT auth service to be ready..."
	@kubectl wait --for=condition=available deployment/jwt-auth-service --timeout=180s 2>/dev/null || sleep 15
	@echo "$(GREEN)✓ JWT auth middleware deployed$(NC)"

# ============================================================================
# OPERATOR DEPLOYMENT
# ============================================================================

## operator-deploy: Deploy the Kubernetes operator
operator-deploy: rbac
	@echo "Building and deploying operator..."
	@cd $(OPERATOR_DIR) && PATH=$(GO_PATH):$$PATH make manifests generate
	@cd $(OPERATOR_DIR) && PATH=$(GO_PATH):$$PATH make install
	@echo "Starting operator locally (for development)..."
	@mkdir -p $(PID_DIR)
	@if [ -f $(OPERATOR_PID) ] && kill -0 $$(cat $(OPERATOR_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ Operator already running$(NC)"; \
	else \
		cd $(OPERATOR_DIR) && PATH=$(GO_PATH):$$PATH nohup go run ./cmd > /tmp/operator.log 2>&1 & \
		echo $$! > $(OPERATOR_PID); \
		sleep 3; \
		echo "$(GREEN)✓ Operator started$(NC)"; \
	fi

## rbac: Apply RBAC for services
rbac:
	@echo "Applying RBAC..."
	@kubectl apply -f $(INFRA_DIR)/rbac.yaml
	@echo "$(GREEN)✓ RBAC applied$(NC)"

# ============================================================================
# SERVICES DEPLOYMENT (KUBERNETES)
# ============================================================================

## services-deploy: Deploy all backend services to Kubernetes
services-deploy:
	@echo "Deploying services to Kubernetes..."
	@kubectl apply -f $(INFRA_DIR)/services.yaml
	@echo "Waiting for services to be ready..."
	@kubectl wait --for=condition=available deployment/fastapi-service --timeout=180s 2>/dev/null || sleep 10
	@kubectl wait --for=condition=available deployment/contract-service --timeout=180s 2>/dev/null || sleep 10
	@kubectl wait --for=condition=available deployment/download-service --timeout=180s 2>/dev/null || sleep 10
	@echo "$(GREEN)✓ Services deployed$(NC)"

# ============================================================================
# LOCAL DEVELOPMENT SERVICES
# ============================================================================

## services-local: Start all backend services locally
services-local: contract-start-local fastapi-start-local download-start-local port-forward
	@echo "$(GREEN)✓ All local services started$(NC)"

## fastapi-start-local: Start the FastAPI service locally
fastapi-start-local: venv
	@mkdir -p $(PID_DIR)
	@if [ -f $(FASTAPI_PID) ] && kill -0 $$(cat $(FASTAPI_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ FastAPI service already running$(NC)"; \
	else \
		echo "Starting FastAPI service..."; \
		fuser -k 8200/tcp 2>/dev/null || true; \
		cd $(FASTAPI_DIR) && \
		DATABASE_URL="postgresql://admin:securepassword123@localhost:5432/inference_db" \
		MINIO_ENDPOINT="localhost:9000" \
		MINIO_BUCKET="inference-models" \
		MINIO_ACCESS_KEY="minioadmin" \
		MINIO_SECRET_KEY="minioadmin123" \
		JWT_SECRET="your-super-secret-jwt-key-change-in-production-minimum-32-chars" \
		CONTRACT_SERVICE_URL="http://localhost:8201" \
		DOWNLOAD_SERVICE_URL="http://localhost:8202" \
		PYTHONPATH=$(PWD) \
		$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8200 > /tmp/fastapi_service.log 2>&1 & \
		echo $$! > $(FASTAPI_PID); \
		sleep 2; \
		echo "$(GREEN)✓ FastAPI service started (port 8200)$(NC)"; \
	fi

## contract-start-local: Start the contract service locally
contract-start-local: venv
	@mkdir -p $(PID_DIR)
	@if [ -f $(CONTRACT_PID) ] && kill -0 $$(cat $(CONTRACT_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ Contract service already running$(NC)"; \
	else \
		echo "Starting contract service..."; \
		fuser -k 8201/tcp 2>/dev/null || true; \
		cd $(CONTRACT_DIR) && \
		DATABASE_URL="postgresql://admin:securepassword123@localhost:5432/inference_db" \
		JWT_SECRET="your-super-secret-jwt-key-change-in-production-minimum-32-chars" \
		PYTHONPATH=$(PWD) \
		$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8201 > /tmp/contract_service.log 2>&1 & \
		echo $$! > $(CONTRACT_PID); \
		sleep 2; \
		echo "$(GREEN)✓ Contract service started (port 8201)$(NC)"; \
	fi

## download-start-local: Start the download service locally
download-start-local: venv
	@mkdir -p $(PID_DIR)
	@if [ -f $(DOWNLOAD_PID) ] && kill -0 $$(cat $(DOWNLOAD_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ Download service already running$(NC)"; \
	else \
		echo "Starting download service..."; \
		fuser -k 8202/tcp 2>/dev/null || true; \
		cd $(DOWNLOAD_DIR) && \
		DATABASE_URL="postgresql://admin:securepassword123@localhost:5432/inference_db" \
		MINIO_ENDPOINT="localhost:9000" \
		MINIO_BUCKET="inference-models" \
		MINIO_ACCESS_KEY="minioadmin" \
		MINIO_SECRET_KEY="minioadmin123" \
		JWT_SECRET="your-super-secret-jwt-key-change-in-production-minimum-32-chars" \
		QUANT_SERVICE_URL="http://quant-api.llm.svc.cluster.local:8300" \
		PYTHONPATH=$(PWD) \
		$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8202 > /tmp/download_service.log 2>&1 & \
		echo $$! > $(DOWNLOAD_PID); \
		sleep 2; \
		echo "$(GREEN)✓ Download service started (port 8202)$(NC)"; \
	fi

## frontend: Start the frontend development server
frontend:
	@mkdir -p $(PID_DIR)
	@if [ -f $(FRONTEND_PID) ] && kill -0 $$(cat $(FRONTEND_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ Frontend already running$(NC)"; \
	else \
		echo "Starting frontend..."; \
		cd $(FRONTEND_DIR) && npm run dev > /tmp/frontend.log 2>&1 & \
		echo $$! > $(FRONTEND_PID); \
		sleep 3; \
		echo "$(GREEN)✓ Frontend started (http://localhost:5173)$(NC)"; \
	fi

## port-forward: Setup port forwarding for K8s services
port-forward: postgres-port-forward minio-port-forward

## postgres-port-forward: Set up port forwarding for PostgreSQL
postgres-port-forward:
	@mkdir -p $(PID_DIR)
	@if [ -f $(POSTGRES_PF_PID) ] && kill -0 $$(cat $(POSTGRES_PF_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ PostgreSQL port-forward already running$(NC)"; \
	else \
		echo "Setting up PostgreSQL port-forward..."; \
		fuser -k 5432/tcp 2>/dev/null || true; \
		kubectl port-forward svc/postgres 5432:5432 > /tmp/postgres_pf.log 2>&1 & \
		echo $$! > $(POSTGRES_PF_PID); \
		sleep 2; \
		echo "$(GREEN)✓ PostgreSQL port-forward established (port 5432)$(NC)"; \
	fi

## minio-port-forward: Set up port forwarding for MinIO
minio-port-forward:
	@mkdir -p $(PID_DIR)
	@if [ -f $(MINIO_PF_PID) ] && kill -0 $$(cat $(MINIO_PF_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ MinIO port-forward already running$(NC)"; \
	else \
		echo "Setting up MinIO port-forward..."; \
		fuser -k 9000/tcp 2>/dev/null || true; \
		fuser -k 9001/tcp 2>/dev/null || true; \
		kubectl port-forward svc/minio 9000:9000 9001:9001 > /tmp/minio_pf.log 2>&1 & \
		echo $$! > $(MINIO_PF_PID); \
		sleep 2; \
		echo "$(GREEN)✓ MinIO port-forward established (ports 9000, 9001)$(NC)"; \
	fi

# ============================================================================
# START/STOP/RESTART
# ============================================================================

## start: Start all services locally (assumes cluster exists)
start: services-local frontend
	@echo ""
	@echo "$(GREEN)All services started!$(NC)"
	@$(MAKE) status

## stop: Stop all services
stop: clean-services
	@echo "$(GREEN)All services stopped$(NC)"

## restart: Restart all services
restart: stop start

## clean-services: Stop all running services
clean-services:
	@echo "Stopping services..."
	-@if [ -f $(FRONTEND_PID) ]; then kill $$(cat $(FRONTEND_PID)) 2>/dev/null; rm -f $(FRONTEND_PID); fi
	-@if [ -f $(FASTAPI_PID) ]; then kill $$(cat $(FASTAPI_PID)) 2>/dev/null; rm -f $(FASTAPI_PID); fi
	-@if [ -f $(CONTRACT_PID) ]; then kill $$(cat $(CONTRACT_PID)) 2>/dev/null; rm -f $(CONTRACT_PID); fi
	-@if [ -f $(DOWNLOAD_PID) ]; then kill $$(cat $(DOWNLOAD_PID)) 2>/dev/null; rm -f $(DOWNLOAD_PID); fi
	-@if [ -f $(OPERATOR_PID) ]; then kill $$(cat $(OPERATOR_PID)) 2>/dev/null; rm -f $(OPERATOR_PID); fi
	-@if [ -f $(POSTGRES_PF_PID) ]; then kill $$(cat $(POSTGRES_PF_PID)) 2>/dev/null; rm -f $(POSTGRES_PF_PID); fi
	-@if [ -f $(MINIO_PF_PID) ]; then kill $$(cat $(MINIO_PF_PID)) 2>/dev/null; rm -f $(MINIO_PF_PID); fi
	-@pkill -f "uvicorn main:app" 2>/dev/null; true
	-@pkill -f "go run ./cmd" 2>/dev/null; true
	-@pkill -f "kubectl port-forward" 2>/dev/null; true
	-@pkill -f "node.*vite" 2>/dev/null; true
	-@fuser -k 8200/tcp 2>/dev/null; true
	-@fuser -k 8201/tcp 2>/dev/null; true
	-@fuser -k 8202/tcp 2>/dev/null; true
	@echo "$(GREEN)✓ Services stopped$(NC)"

# ============================================================================
# STATUS AND LOGS
# ============================================================================

## status: Show system status
status:
	@echo ""
	@echo "=========================================="
	@echo "  System Status"
	@echo "=========================================="
	@echo ""
	@echo "$(BLUE)Cluster:$(NC)"
	@if k3d cluster list 2>/dev/null | grep -q $(CLUSTER_NAME); then \
		echo "  $(GREEN)✓$(NC) k3d cluster '$(CLUSTER_NAME)' is running"; \
	else \
		echo "  $(RED)✗$(NC) k3d cluster '$(CLUSTER_NAME)' is not running"; \
	fi
	@echo ""
	@echo "$(BLUE)Local Services:$(NC)"
	@if lsof -i :8200 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) FastAPI      - http://localhost:8200"; \
	else \
		echo "  $(RED)✗$(NC) FastAPI      - not running"; \
	fi
	@if lsof -i :8201 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) Contract     - http://localhost:8201"; \
	else \
		echo "  $(RED)✗$(NC) Contract     - not running"; \
	fi
	@if lsof -i :8202 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) Download     - http://localhost:8202"; \
	else \
		echo "  $(RED)✗$(NC) Download     - not running"; \
	fi
	@if lsof -i :5173 2>/dev/null | grep -q LISTEN || lsof -i :5174 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) Frontend     - http://localhost:5173"; \
	else \
		echo "  $(RED)✗$(NC) Frontend     - not running"; \
	fi
	@echo ""
	@echo "$(BLUE)Port Forwards:$(NC)"
	@if lsof -i :5432 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) PostgreSQL   - localhost:5432"; \
	else \
		echo "  $(RED)✗$(NC) PostgreSQL   - port-forward not running"; \
	fi
	@if lsof -i :9000 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) MinIO API    - localhost:9000"; \
	else \
		echo "  $(RED)✗$(NC) MinIO API    - port-forward not running"; \
	fi
	@if lsof -i :9001 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) MinIO Console- localhost:9001"; \
	else \
		echo "  $(RED)✗$(NC) MinIO Console- port-forward not running"; \
	fi
	@echo "  $(GREEN)✓$(NC) Gateway      - http://localhost:8080/{server-uuid}/"
	@echo ""
	@echo "$(BLUE)Kubernetes Pods:$(NC)"
	@kubectl get pods 2>/dev/null || echo "  Cannot connect to cluster"
	@echo ""

## logs: Show service logs
logs:
	@echo "=== FastAPI Logs ===" && tail -30 /tmp/fastapi_service.log 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Contract Logs ===" && tail -30 /tmp/contract_service.log 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Download Logs ===" && tail -30 /tmp/download_service.log 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Operator Logs ===" && tail -30 /tmp/operator.log 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Frontend Logs ===" && tail -20 /tmp/frontend.log 2>/dev/null || echo "No logs"

## logs-k8s: Show Kubernetes pod logs
logs-k8s:
	@echo "=== FastAPI Pod Logs ==="
	@kubectl logs -l app=fastapi-service --tail=50 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Contract Pod Logs ==="
	@kubectl logs -l app=contract-service --tail=50 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Download Pod Logs ==="
	@kubectl logs -l app=download-service --tail=50 2>/dev/null || echo "No logs"

# ============================================================================
# CLEANUP
# ============================================================================

## clean: Complete cleanup (stop services + delete cluster)
clean: clean-services cluster-delete
	@rm -rf $(PID_DIR)
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

# ============================================================================
# DEVELOPMENT HELPERS
# ============================================================================

## dev: Start in development mode with auto-reload
dev: port-forward services-local
	@echo "Starting frontend in development mode..."
	@cd $(FRONTEND_DIR) && npm run dev

## rebuild-operator: Rebuild and restart the operator
rebuild-operator:
	@if [ -f $(OPERATOR_PID) ]; then kill $$(cat $(OPERATOR_PID)) 2>/dev/null || true; rm -f $(OPERATOR_PID); fi
	@pkill -f "go run ./cmd" 2>/dev/null || true
	@$(MAKE) operator-deploy

## db-shell: Open PostgreSQL shell
db-shell:
	@kubectl exec -it deploy/postgres -- psql -U admin -d inference_db

## db-status: Show database contents
db-status:
	@echo "=== Server Records ==="
	@kubectl exec deploy/postgres -- psql -U admin -d inference_db -c "SELECT uuid, model_name, status, memory_max_mb, cpu_usage_percent, created_at FROM server_records;" 2>/dev/null || echo "Table not found"
	@echo ""
	@echo "=== Model Records ==="
	@kubectl exec deploy/postgres -- psql -U admin -d inference_db -c "SELECT uuid, model_name, minio_path, quant_level, file_size_bytes FROM model_records;" 2>/dev/null || echo "Table not found"

## minio-shell: Open MinIO client shell
minio-shell:
	@kubectl exec -it deploy/minio -- mc alias set local http://localhost:9000 minioadmin minioadmin123
	@kubectl exec -it deploy/minio -- /bin/sh
