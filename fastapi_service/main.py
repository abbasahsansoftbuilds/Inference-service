"""
FastAPI Service - Main API Gateway for Inference Service

Handles model serving requests, checks model availability in MinIO,
and triggers download from Quant Service when needed.
"""
import os
import sys
import uuid as uuid_lib
from typing import Optional, List
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

# Add shared directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import verify_token, create_access_token
from shared.minio_client import get_minio_client, file_exists, BUCKET_NAME
from shared.database import (
    get_db, init_db, 
    ServerRecord, ModelRecord,
    get_model_by_name, get_model_by_uuid,
    create_server_record, update_server_status
)

app = FastAPI(
    title="Inference Service API",
    description="API Gateway for LLM Inference Service",
    version="2.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
CONTRACT_SERVICE_URL = os.getenv("CONTRACT_SERVICE_URL", "http://localhost:8201/apply")
CONTRACT_DELETE_URL = os.getenv("CONTRACT_DELETE_URL", "http://localhost:8201/delete")
CONTRACT_LIST_URL = os.getenv("CONTRACT_LIST_URL", "http://localhost:8201/list")
DOWNLOAD_SERVICE_URL = os.getenv("DOWNLOAD_SERVICE_URL", "http://localhost:8202")
GATEWAY_HOST = os.getenv("GATEWAY_HOST", "localhost:8080")


class TokenRequest(BaseModel):
    """Request for authentication token."""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Authentication token response."""
    access_token: str
    token_type: str
    expires_in: int


class ServerStatusResponse(BaseModel):
    """Server status response."""
    uuid: str
    model_uuid: Optional[str] = None
    model_name: str
    status: str
    memory_usage_mb: int = 0
    memory_max_mb: int = 0
    cpu_usage_percent: float = 0.0
    endpoint: Optional[str] = None
    gateway_url: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    init_db()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "fastapi-gateway"}


@app.post("/auth/token", response_model=TokenResponse)
async def login(request: TokenRequest):
    """
    Authenticate user and return JWT token.
    """
    valid_users = {
        "admin": os.getenv("ADMIN_PASSWORD", "admin-password"),
        "operator": os.getenv("OPERATOR_PASSWORD", "operator-password")
    }
    
    if request.username not in valid_users:
        raise HTTPException(status_code=401, detail="Invalid username")
    
    if request.password != valid_users[request.username]:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    token = create_access_token(
        subject=request.username,
        additional_claims={"role": "admin" if request.username == "admin" else "operator"}
    )
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=24 * 3600
    )

@app.get("/serve")
async def serve_model(
    model: str,
    replicas: int = 1,
    token_payload: dict = Depends(verify_token)
):
    """
    Request to deploy and serve a model.
    
    1. Check if model exists in local MinIO
    2. If not, return info about triggering download from Quant Service
    3. If yes, create CR and deploy
    """
    db = get_db()
    
    try:
        # Clean model name (remove .gguf if present for lookup)
        model_name = model.replace(".gguf", "")
        
        # Check if model exists in local database (already downloaded)
        model_record = get_model_by_name(db, model_name)
        
        if not model_record:
            # Model not in local MinIO - need to download
            return {
                "status": "model_not_found",
                "message": f"Model '{model_name}' not found in local storage. Use /download endpoint to fetch from Quant Service.",
                "download_endpoint": f"{DOWNLOAD_SERVICE_URL}/download",
                "next_steps": [
                    "1. Call Quant Service to list available models",
                    "2. Use /download endpoint with model_id to download",
                    "3. Wait for download to complete",
                    "4. Call /serve again"
                ]
            }
        
        if model_record.status != "ready":
            return {
                "status": "model_not_ready",
                "message": f"Model '{model_name}' is being downloaded. Current status: {model_record.status}",
                "model_uuid": model_record.uuid,
                "check_status_endpoint": f"{DOWNLOAD_SERVICE_URL}/status/{model_record.uuid}"
            }
        
        # Model is ready - create CR for deployment
        # Generate server UUID
        server_uuid = str(uuid_lib.uuid4())
        
        # Kubernetes-compliant name
        cr_name = f"model-{model_name.lower().replace('_', '-').replace('.', '-')}-{server_uuid[:8]}"
        
        cr = {
            "apiVersion": "model.example.com/v1alpha1",
            "kind": "ModelServe",
            "metadata": {
                "name": cr_name,
                "namespace": "default",
                "annotations": {
                    "serverUuid": server_uuid
                }
            },
            "spec": {
                "modelName": f"{model_name}.gguf",
                "minioPath": model_record.minio_path,
                "minioBucket": BUCKET_NAME,
                "minioEndpoint": "minio:9000",
                "modelUuid": model_record.uuid,
                "replicas": replicas
            }
        }
        
        # Create server record in database
        create_server_record(
            db=db,
            uuid=server_uuid,
            model_uuid=model_record.uuid,
            model_name=model_name,
            runtime_params={"replicas": replicas},
            namespace="default"
        )
        
        # Forward token for contract service
        internal_token = create_access_token(subject=token_payload.get("sub", "system"), token_type="internal")
        
        # Submit to Contract Service
        try:
            response = requests.post(
                CONTRACT_SERVICE_URL,
                json=cr,
                headers={"Authorization": f"Bearer {internal_token}"},
                timeout=30
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise HTTPException(status_code=500, detail=f"Contract Service failed: {str(e)}")
        
        # Gateway URL
        gateway_url = f"https://{GATEWAY_HOST}/{server_uuid}/"
        
        # Update server record with gateway URL
        update_server_status(db, server_uuid, "starting", gateway_url=gateway_url, endpoint=f"/{cr_name}")
        
        return {
            "status": "success",
            "message": f"Model {model_name} deployment requested",
            "server_uuid": server_uuid,
            "model_uuid": model_record.uuid,
            "gateway_url": gateway_url,
            "cr": cr
        }
        
    finally:
        db.close()

@app.delete("/cleanup")
async def cleanup_model(model: str, token_payload: dict = Depends(verify_token)):
    """
    Cleanup/delete a deployed model and all its associated resources.
    """
    model_name = model.replace(".gguf", "")
    cr_name = f"model-{model_name.lower().replace('_', '-').replace('.', '-')}"
    
    delete_request = {
        "name": cr_name,
        "namespace": "default"
    }
    
    internal_token = create_access_token(subject=token_payload.get("sub", "system"), token_type="internal")
    
    try:
        response = requests.post(
            CONTRACT_DELETE_URL,
            json=delete_request,
            headers={"Authorization": f"Bearer {internal_token}"},
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Contract Service failed: {str(e)}")
    
    return {
        "status": "success",
        "message": f"Model {model_name} cleanup completed",
        "deleted_resource": cr_name,
        "details": result
    }

@app.get("/list")
async def list_models(token_payload: dict = Depends(verify_token)):
    """List all currently deployed models."""
    internal_token = create_access_token(subject=token_payload.get("sub", "system"), token_type="internal")
    
    try:
        response = requests.get(
            CONTRACT_LIST_URL,
            headers={"Authorization": f"Bearer {internal_token}"},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Contract Service failed: {str(e)}")

@app.get("/status", response_model=List[ServerStatusResponse])
async def get_server_status(token_payload: dict = Depends(verify_token)):
    """
    Get the status of all inference servers from the database.
    """
    db = get_db()
    
    try:
        servers = db.query(ServerRecord).order_by(ServerRecord.updated_at.desc()).all()
        
        return [
            ServerStatusResponse(
                uuid=s.uuid,
                model_uuid=s.model_uuid,
                model_name=s.model_name,
                status=s.status,
                memory_usage_mb=s.memory_usage_mb or 0,
                memory_max_mb=s.memory_max_mb or 0,
                cpu_usage_percent=s.cpu_usage_percent or 0.0,
                endpoint=s.endpoint,
                gateway_url=s.gateway_url,
                created_at=s.created_at.isoformat() if s.created_at else None,
                started_at=s.started_at.isoformat() if s.started_at else None,
                updated_at=s.updated_at.isoformat() if s.updated_at else None
            )
            for s in servers
        ]
    finally:
        db.close()


@app.get("/models/available")
async def list_available_models(token_payload: dict = Depends(verify_token)):
    """
    List all models available in local MinIO (downloaded from Quant Service).
    """
    db = get_db()
    
    try:
        models = db.query(ModelRecord).filter(
            ModelRecord.status == "ready"
        ).order_by(ModelRecord.created_at.desc()).all()
        
        return {
            "status": "success",
            "models": [
                {
                    "uuid": m.uuid,
                    "model_name": m.model_name,
                    "quant_level": m.quant_level,
                    "file_size_bytes": m.file_size_bytes,
                    "minio_path": m.minio_path,
                    "downloaded_at": m.downloaded_at.isoformat() if m.downloaded_at else None
                }
                for m in models
            ]
        }
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FASTAPI_PORT", "8200"))
    uvicorn.run(app, host="0.0.0.0", port=port)
