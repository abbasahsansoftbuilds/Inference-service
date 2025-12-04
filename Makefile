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
        venv install-python-deps install-frontend-deps port-forward logs

# Configuration
CLUSTER_NAME := model-cluster
MODEL_CATALOG := $(PWD)/Model_Catalog
VENV := $(PWD)/.venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
GO_PATH := $(PWD)/tools/go/bin
OPERATOR_DIR := $(PWD)/operator
FRONTEND_DIR := $(PWD)/frontend
FASTAPI_DIR := $(PWD)/fastapi_service
CONTRACT_DIR := $(PWD)/contract_service
INFRA_DIR := $(PWD)/infra

# PID files for service management
PID_DIR := /tmp/inference_service
FASTAPI_PID := $(PID_DIR)/fastapi.pid
CONTRACT_PID := $(PID_DIR)/contract.pid
OPERATOR_PID := $(PID_DIR)/operator.pid
FRONTEND_PID := $(PID_DIR)/frontend.pid
POSTGRES_PF_PID := $(PID_DIR)/postgres_pf.pid

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# ============================================================================
# MAIN TARGETS
# ============================================================================

## all: Complete setup from scratch (deps + cluster + infra + services)
all: deps cluster infra services frontend
	@echo ""
	@echo "$(GREEN)============================================$(NC)"
	@echo "$(GREEN)  Setup Complete!$(NC)"
	@echo "$(GREEN)============================================$(NC)"
	@echo ""
	@echo "Services running:"
	@echo "  - FastAPI:    http://localhost:8000"
	@echo "  - Contract:   http://localhost:8001"
	@echo "  - Frontend:   http://localhost:5173"
	@echo "  - Gateway:    http://localhost:8080/{model-uuid}/"
	@echo ""
	@echo "Next steps:"
	@echo "  make serve MODEL=Qwen    # Deploy a model"
	@echo "  make list                # List deployed models"
	@echo "  make status              # Check system status"
	@echo ""

## help: Show this help message
help:
	@echo "LLM Inference Service - Makefile Commands"
	@echo "=========================================="
	@echo ""
	@echo "Setup Commands:"
	@echo "  make all              - Complete setup from scratch"
	@echo "  make deps             - Check and install dependencies"
	@echo "  make cluster          - Create k3d cluster"
	@echo "  make infra            - Deploy infrastructure (postgres, configs)"
	@echo "  make services         - Start backend services"
	@echo "  make frontend         - Start frontend dev server"
	@echo ""
	@echo "Runtime Commands:"
	@echo "  make start            - Start all services (cluster must exist)"
	@echo "  make stop             - Stop all services"
	@echo "  make restart          - Restart all services"
	@echo "  make status           - Show system status"
	@echo "  make logs             - Show service logs"
	@echo ""
	@echo "Model Commands:"
	@echo "  make serve MODEL=<name>  - Deploy a model (e.g., MODEL=Qwen)"
	@echo "  make remove MODEL=<name> - Remove a deployed model"
	@echo "  make list                - List all deployed models"
	@echo ""
	@echo "Cleanup Commands:"
	@echo "  make clean            - Stop services and delete cluster"
	@echo "  make clean-services   - Stop services only"
	@echo "  make cluster-delete   - Delete cluster only"
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
			--volume "$(MODEL_CATALOG):/home/Inference_service/Model_Catalog" \
			--port "8080:80@loadbalancer" \
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
# INFRASTRUCTURE
# ============================================================================

## infra: Deploy infrastructure components (CRD, postgres, configs)
infra: crd postgres-deploy traefik-middlewares
	@echo "$(GREEN)✓ Infrastructure deployed$(NC)"

## crd: Apply the ModelServe CRD
crd:
	@echo "Applying CRD..."
	@kubectl apply -f $(OPERATOR_DIR)/config/crd/bases/ 2>/dev/null || \
		kubectl apply -f - <<< "$$(cat <<EOF
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: modelserves.model.example.com
spec:
  group: model.example.com
  names:
    kind: ModelServe
    listKind: ModelServeList
    plural: modelserves
    singular: modelserve
  scope: Namespaced
  versions:
  - name: v1alpha1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              modelName:
                type: string
              modelUrl:
                type: string
              replicas:
                type: integer
              image:
                type: string
          status:
            type: object
            properties:
              availableReplicas:
                type: integer
    subresources:
      status: {}
EOF
)"
	@echo "$(GREEN)✓ CRD applied$(NC)"

## postgres-deploy: Deploy PostgreSQL
postgres-deploy:
	@echo "Deploying PostgreSQL..."
	@kubectl apply -f $(INFRA_DIR)/postgres.yaml
	@kubectl apply -f $(INFRA_DIR)/monitor-config.yaml
	@echo "Waiting for PostgreSQL to be ready..."
	@kubectl wait --for=condition=ready pod -l app=postgres --timeout=120s 2>/dev/null || sleep 10
	@echo "$(GREEN)✓ PostgreSQL deployed$(NC)"

## traefik-middlewares: Apply Traefik middlewares
traefik-middlewares:
	@echo "Applying Traefik middlewares..."
	@kubectl apply -f $(INFRA_DIR)/traefik-middlewares.yaml
	@echo "$(GREEN)✓ Traefik middlewares applied$(NC)"

# ============================================================================
# SERVICES
# ============================================================================

## services: Start all backend services
services: operator-start contract-start fastapi-start postgres-port-forward
	@echo "$(GREEN)✓ All services started$(NC)"

## operator-start: Start the Kubernetes operator
operator-start:
	@mkdir -p $(PID_DIR)
	@if [ -f $(OPERATOR_PID) ] && kill -0 $$(cat $(OPERATOR_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ Operator already running$(NC)"; \
	else \
		echo "Starting operator..."; \
		fuser -k 8082/tcp 2>/dev/null || true; \
		cd $(OPERATOR_DIR) && \
		PATH=$(GO_PATH):$$PATH \
		nohup go run ./cmd > /tmp/operator.log 2>&1 & \
		echo $$! > $(OPERATOR_PID); \
		sleep 3; \
		echo "$(GREEN)✓ Operator started$(NC)"; \
	fi

## contract-start: Start the contract service
contract-start:
	@mkdir -p $(PID_DIR)
	@if [ -f $(CONTRACT_PID) ] && kill -0 $$(cat $(CONTRACT_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ Contract service already running$(NC)"; \
	else \
		echo "Starting contract service..."; \
		fuser -k 8001/tcp 2>/dev/null || true; \
		cd $(CONTRACT_DIR) && \
		$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8001 > /tmp/contract_service.log 2>&1 & \
		echo $$! > $(CONTRACT_PID); \
		sleep 2; \
		echo "$(GREEN)✓ Contract service started (port 8001)$(NC)"; \
	fi

## fastapi-start: Start the FastAPI service
fastapi-start:
	@mkdir -p $(PID_DIR)
	@if [ -f $(FASTAPI_PID) ] && kill -0 $$(cat $(FASTAPI_PID)) 2>/dev/null; then \
		echo "$(YELLOW)→ FastAPI service already running$(NC)"; \
	else \
		echo "Starting FastAPI service..."; \
		fuser -k 8000/tcp 2>/dev/null || true; \
		cd $(FASTAPI_DIR) && \
		$(VENV)/bin/uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/fastapi_service.log 2>&1 & \
		echo $$! > $(FASTAPI_PID); \
		sleep 2; \
		echo "$(GREEN)✓ FastAPI service started (port 8000)$(NC)"; \
	fi

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
		echo "$(GREEN)✓ Frontend started$(NC)"; \
	fi

# ============================================================================
# START/STOP/RESTART
# ============================================================================

## start: Start all services (assumes cluster exists)
start: services frontend
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
	@if [ -f $(FRONTEND_PID) ]; then kill $$(cat $(FRONTEND_PID)) 2>/dev/null || true; rm -f $(FRONTEND_PID); fi
	@if [ -f $(FASTAPI_PID) ]; then kill $$(cat $(FASTAPI_PID)) 2>/dev/null || true; rm -f $(FASTAPI_PID); fi
	@if [ -f $(CONTRACT_PID) ]; then kill $$(cat $(CONTRACT_PID)) 2>/dev/null || true; rm -f $(CONTRACT_PID); fi
	@if [ -f $(OPERATOR_PID) ]; then kill $$(cat $(OPERATOR_PID)) 2>/dev/null || true; rm -f $(OPERATOR_PID); fi
	@if [ -f $(POSTGRES_PF_PID) ]; then kill $$(cat $(POSTGRES_PF_PID)) 2>/dev/null || true; rm -f $(POSTGRES_PF_PID); fi
	@pkill -f "uvicorn.*fastapi_service" 2>/dev/null || true
	@pkill -f "uvicorn.*contract_service" 2>/dev/null || true
	@pkill -f "go run ./cmd" 2>/dev/null || true
	@pkill -f "port-forward.*postgres" 2>/dev/null || true
	@pkill -f "vite" 2>/dev/null || true
	@echo "$(GREEN)✓ Services stopped$(NC)"

# ============================================================================
# MODEL MANAGEMENT
# ============================================================================

## serve: Deploy a model (usage: make serve MODEL=Qwen)
serve:
ifndef MODEL
	@echo "$(RED)Error: MODEL is required$(NC)"
	@echo "Usage: make serve MODEL=<model_name>"
	@echo "Example: make serve MODEL=Qwen"
	@exit 1
endif
	@$(PYTHON) infer.py serve $(MODEL)

## remove: Remove a deployed model (usage: make remove MODEL=Qwen)
remove:
ifndef MODEL
	@echo "$(RED)Error: MODEL is required$(NC)"
	@echo "Usage: make remove MODEL=<model_name>"
	@exit 1
endif
	@$(PYTHON) infer.py clean $(MODEL)

## list: List all deployed models
list:
	@$(PYTHON) infer.py list

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
	@echo "Cluster:"
	@if k3d cluster list 2>/dev/null | grep -q $(CLUSTER_NAME); then \
		echo "  $(GREEN)✓$(NC) k3d cluster '$(CLUSTER_NAME)' is running"; \
	else \
		echo "  $(RED)✗$(NC) k3d cluster '$(CLUSTER_NAME)' is not running"; \
	fi
	@echo ""
	@echo "Services:"
	@if lsof -i :8000 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) FastAPI     - http://localhost:8000"; \
	else \
		echo "  $(RED)✗$(NC) FastAPI     - not running"; \
	fi
	@if lsof -i :8001 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) Contract    - http://localhost:8001"; \
	else \
		echo "  $(RED)✗$(NC) Contract    - not running"; \
	fi
	@if lsof -i :5173 2>/dev/null | grep -q LISTEN || lsof -i :5174 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) Frontend    - http://localhost:5173"; \
	else \
		echo "  $(RED)✗$(NC) Frontend    - not running"; \
	fi
	@if lsof -i :5432 2>/dev/null | grep -q LISTEN; then \
		echo "  $(GREEN)✓$(NC) PostgreSQL  - localhost:5432 (port-forward)"; \
	else \
		echo "  $(RED)✗$(NC) PostgreSQL  - port-forward not running"; \
	fi
	@echo "  $(GREEN)✓$(NC) Gateway     - http://localhost:8080/{model}/"
	@echo ""
	@echo "Kubernetes Pods:"
	@kubectl get pods 2>/dev/null || echo "  Cannot connect to cluster"
	@echo ""

## logs: Show service logs
logs:
	@echo "=== FastAPI Logs ===" && tail -20 /tmp/fastapi_service.log 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Contract Logs ===" && tail -20 /tmp/contract_service.log 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Operator Logs ===" && tail -20 /tmp/operator.log 2>/dev/null || echo "No logs"
	@echo ""
	@echo "=== Frontend Logs ===" && tail -20 /tmp/frontend.log 2>/dev/null || echo "No logs"

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
dev: services
	@echo "Starting frontend in development mode..."
	@cd $(FRONTEND_DIR) && npm run dev

## rebuild-operator: Rebuild and restart the operator
rebuild-operator:
	@if [ -f $(OPERATOR_PID) ]; then kill $$(cat $(OPERATOR_PID)) 2>/dev/null || true; rm -f $(OPERATOR_PID); fi
	@pkill -f "go run ./cmd" 2>/dev/null || true
	@fuser -k 8082/tcp 2>/dev/null || true
	@$(MAKE) operator-start

## db-shell: Open PostgreSQL shell
db-shell:
	@kubectl exec -it deploy/postgres -- psql -U admin -d inference_db

## db-status: Show database contents
db-status:
	@kubectl exec deploy/postgres -- psql -U admin -d inference_db -c "SELECT uuid, model_name, status, memory_usage_mb FROM server_status;"
