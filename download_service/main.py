"""
Model Download Service

Downloads models from Quant Service (cloud) MinIO to local Inference Service MinIO.
Maintains model metadata and tracks download status.
"""
import os
import sys
import uuid
import tempfile
import requests
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add shared directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import verify_token, create_service_token
from shared.minio_client import (
    get_minio_client, init_bucket, upload_file, file_exists, 
    get_file_size, BUCKET_NAME
)
from shared.database import (
    get_db, init_db, ModelRecord, 
    create_model_record, update_model_status, get_model_by_uuid
)

app = FastAPI(
    title="Model Download Service",
    description="Downloads models from Quant Service to local MinIO",
    version="1.0.0"
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
QUANT_SERVICE_URL = os.getenv("QUANT_SERVICE_URL", "http://quant-api:8300")
QUANT_SERVICE_ID = os.getenv("QUANT_SERVICE_ID", "inference-service")
QUANT_SERVICE_SECRET = os.getenv("QUANT_SERVICE_SECRET", "inference-secret-key")


class DownloadRequest(BaseModel):
    """Request to download a model from Quant Service."""
    model_id: int  # Model ID in Quant Service
    file_type: str = "quantized"  # 'quantized' or 'original'


class DownloadResponse(BaseModel):
    """Response after initiating download."""
    model_uuid: str
    model_name: str
    status: str
    minio_path: Optional[str]
    message: str


class ModelStatusResponse(BaseModel):
    """Model download status."""
    uuid: str
    model_name: str
    status: str
    minio_path: Optional[str]
    file_size_bytes: Optional[int]
    quant_level: Optional[str]
    downloaded_at: Optional[str]


def get_quant_service_token() -> str:
    """Authenticate with Quant Service and get a token."""
    auth_url = f"{QUANT_SERVICE_URL}/auth/token"
    
    try:
        response = requests.post(
            auth_url,
            json={
                "service_id": QUANT_SERVICE_ID,
                "service_secret": QUANT_SERVICE_SECRET
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to authenticate with Quant Service: {str(e)}"
        )


def download_model_from_quant_service(
    model_uuid: str,
    model_id: int,
    file_type: str,
    model_name: str,
    quant_level: Optional[str] = None
):
    """
    Background task to download a model from Quant Service.
    Downloads to local MinIO and updates database status.
    """
    db = get_db()
    minio = get_minio_client()
    
    try:
        # Get token for Quant Service
        token = get_quant_service_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        # Get download URL from Quant Service
        download_info_url = f"{QUANT_SERVICE_URL}/download-url/{model_id}"
        params = {"expires_in": 7200}  # 2 hours
        
        response = requests.get(download_info_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        download_info = response.json()
        
        presigned_url = download_info["download_url"]
        
        # Rewrite URL for cross-cluster access via host port-forward
        # Quant Service generates URL with internal DNS (minio.llm.svc.cluster.local:9000)
        # We need to access it via host.k3d.internal:9003 (which we port-forwarded)
        if "minio.llm.svc.cluster.local" in presigned_url:
            presigned_url = presigned_url.replace("minio.llm.svc.cluster.local", "host.k3d.internal")
            presigned_url = presigned_url.replace(":9000", ":9003")
            
        file_size = download_info.get("file_size_bytes")
        # quant_level and minio_path are not returned by download-url endpoint
        source_minio_path = None 
        
        # Create a temp file to download to
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gguf") as tmp_file:
            tmp_path = tmp_file.name
        
        try:
            # Download the model file
            print(f"Downloading model from Quant Service: {model_name}")
            with requests.get(presigned_url, stream=True, timeout=3600) as r:
                r.raise_for_status()
                with open(tmp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=10*1024*1024):  # 10MB chunks
                        f.write(chunk)
            
            # Upload to local MinIO
            # Use same path structure: models/<model_uuid>/<filename>
            filename = os.path.basename(source_minio_path) if source_minio_path else f"{model_name}.gguf"
            local_minio_path = f"models/{model_uuid}/{filename}"
            
            print(f"Uploading to local MinIO: {local_minio_path}")
            init_bucket(minio, BUCKET_NAME)
            upload_file(tmp_path, local_minio_path, minio, BUCKET_NAME)
            
            # Get actual file size from downloaded file
            actual_size = os.path.getsize(tmp_path)
            
            # Update model record
            model = get_model_by_uuid(db, model_uuid)
            if model:
                model.minio_path = local_minio_path
                model.file_size_bytes = actual_size
                model.quant_level = quant_level
                model.status = "ready"
                model.downloaded_at = datetime.utcnow()
                db.commit()
            
            print(f"Model download complete: {model_name} -> {local_minio_path}")
            
        finally:
            # Cleanup temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                
    except Exception as e:
        print(f"Error downloading model: {str(e)}")
        # Update status to error
        model = get_model_by_uuid(db, model_uuid)
        if model:
            model.status = "error"
            db.commit()
    finally:
        db.close()


@app.on_event("startup")
async def startup():
    """Initialize database and MinIO on startup."""
    init_db()
    minio = get_minio_client()
    init_bucket(minio, BUCKET_NAME)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "download-service"}


@app.post("/download", response_model=DownloadResponse)
async def download_model(
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
    token_payload: dict = Depends(verify_token)
):
    """
    Initiate download of a model from Quant Service.
    
    The download happens in the background. Use /status/{uuid} to check progress.
    """
    db = get_db()
    
    try:
        # Get token for Quant Service
        quant_token = get_quant_service_token()
        headers = {"Authorization": f"Bearer {quant_token}"}
        
        # Get model info from Quant Service
        model_info_url = f"{QUANT_SERVICE_URL}/models/{request.model_id}"
        response = requests.get(model_info_url, headers=headers, timeout=30)
        response.raise_for_status()
        model_info = response.json()
        
        model_name = model_info["model_name"]
        quant_level = model_info.get("quant_level")
        hf_name = model_info.get("hf_name")
        
        # Generate UUID for local tracking
        model_uuid = str(uuid.uuid4())
        
        # Create model record in local database
        model_record = create_model_record(
            db=db,
            uuid=model_uuid,
            model_name=model_name,
            minio_path=None,  # Will be set after download
            external_source_id=request.model_id,
            hf_name=hf_name,
            quant_level=quant_level,
            model_metadata={
                "source": "quant-service",
                "file_type": request.file_type,
                "original_status": model_info.get("status")
            }
        )
        
        # Start background download
        background_tasks.add_task(
            download_model_from_quant_service,
            model_uuid,
            request.model_id,
            request.file_type,
            model_name,
            quant_level
        )
        
        return DownloadResponse(
            model_uuid=model_uuid,
            model_name=model_name,
            status="downloading",
            minio_path=None,
            message="Download initiated. Check status endpoint for progress."
        )
        
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Model not found in Quant Service")
        raise HTTPException(status_code=502, detail=f"Quant Service error: {str(e)}")
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Quant Service: {str(e)}")
    finally:
        db.close()


@app.get("/status/{model_uuid}", response_model=ModelStatusResponse)
async def get_download_status(
    model_uuid: str,
    token_payload: dict = Depends(verify_token)
):
    """Get the status of a model download."""
    db = get_db()
    
    try:
        model = get_model_by_uuid(db, model_uuid)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        
        return ModelStatusResponse(
            uuid=model.uuid,
            model_name=model.model_name,
            status=model.status,
            minio_path=model.minio_path,
            file_size_bytes=model.file_size_bytes,
            quant_level=model.quant_level,
            downloaded_at=model.downloaded_at.isoformat() if model.downloaded_at else None
        )
    finally:
        db.close()


@app.get("/models", response_model=list[ModelStatusResponse])
async def list_models(
    status: Optional[str] = None,
    token_payload: dict = Depends(verify_token)
):
    """List all downloaded models."""
    db = get_db()
    
    try:
        query = db.query(ModelRecord)
        if status:
            query = query.filter(ModelRecord.status == status)
        
        models = query.order_by(ModelRecord.created_at.desc()).all()
        
        return [
            ModelStatusResponse(
                uuid=m.uuid,
                model_name=m.model_name,
                status=m.status,
                minio_path=m.minio_path,
                file_size_bytes=m.file_size_bytes,
                quant_level=m.quant_level,
                downloaded_at=m.downloaded_at.isoformat() if m.downloaded_at else None
            )
            for m in models
        ]
    finally:
        db.close()


@app.get("/models/by-name/{model_name}", response_model=ModelStatusResponse)
async def get_model_by_name_endpoint(
    model_name: str,
    token_payload: dict = Depends(verify_token)
):
    """Get a model by name (returns latest ready version)."""
    db = get_db()
    
    try:
        model = db.query(ModelRecord).filter(
            ModelRecord.model_name == model_name,
            ModelRecord.status == "ready"
        ).order_by(ModelRecord.created_at.desc()).first()
        
        if not model:
            raise HTTPException(status_code=404, detail=f"No ready model found with name '{model_name}'")
        
        return ModelStatusResponse(
            uuid=model.uuid,
            model_name=model.model_name,
            status=model.status,
            minio_path=model.minio_path,
            file_size_bytes=model.file_size_bytes,
            quant_level=model.quant_level,
            downloaded_at=model.downloaded_at.isoformat() if model.downloaded_at else None
        )
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DOWNLOAD_SERVICE_PORT", "8202"))
    uvicorn.run(app, host="0.0.0.0", port=port)
