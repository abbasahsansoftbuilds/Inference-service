from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
import os
import requests
import json
from typing import Optional, List
import psycopg2

app = FastAPI()

# Configuration
MODEL_CATALOG_PATH = "/media/abbas/Optane/Inference_service/Model_Catalog"
CONTRACT_SERVICE_URL = "http://localhost:8001/apply"
CONTRACT_DELETE_URL = "http://localhost:8001/delete"
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "inference_db")

class ServeRequest(BaseModel):
    model_name: str

class CRTemplate(BaseModel):
    apiVersion: str = "model.example.com/v1alpha1"
    kind: str = "ModelServe"
    metadata: dict
    spec: dict

def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format")
    token = authorization.split(" ")[1]
    # In a real app, verify the token signature here.
    # For this implementation, we assume any token is valid if present.
    return token

@app.get("/serve")
def serve_model(model: str, token: str = Depends(verify_token)):
    # 2. Model Availability Check
    model_path = os.path.join(MODEL_CATALOG_PATH, model)
    # In dev, we check for directory or file. 
    # The user said "model artifact (e.g., model.Q4.gguf) exists"
    # Let's assume the model name maps to a file or directory.
    
    if not os.path.exists(model_path) and not os.path.exists(model_path + ".gguf"):
         raise HTTPException(status_code=404, detail=f"Model {model} not found in catalog")

    # 3. Fetch Signed URL (No-op in dev, use local path)
    # We will use the local path for the CR
    
    # 4. Create Custom Resource (CR) Template
    # Kubernetes names must be DNS-1035 compliant (lowercase alphanumeric, dash only)
    cr_name = f"model-{model.lower().replace('_', '-').replace('.', '-')}"
    
    cr = {
        "apiVersion": "model.example.com/v1alpha1",
        "kind": "ModelServe",
        "metadata": {
            "name": cr_name,
            "namespace": "default"
        },
        "spec": {
            "modelName": model,
            "modelUrl": model_path, # Local path in dev
            "replicas": 1
        }
    }
    
    # 5. Contract Service / Controlled Apply
    try:
        response = requests.post(CONTRACT_SERVICE_URL, json=cr, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Contract Service failed: {str(e)}")
        
    return {"status": "success", "message": f"Model {model} deployment requested", "cr": cr}

@app.delete("/cleanup")
def cleanup_model(model: str, token: str = Depends(verify_token)):
    """
    Cleanup/delete a deployed model and all its associated resources.
    This removes the ModelServe CR, which triggers the operator to delete
    the Deployment and Service.
    """
    # Construct the CR name from model name (same logic as serve)
    cr_name = f"model-{model.lower().replace('_', '-').replace('.', '-')}"
    
    delete_request = {
        "name": cr_name,
        "namespace": "default"
    }
    
    try:
        response = requests.post(
            CONTRACT_DELETE_URL, 
            json=delete_request, 
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Contract Service failed: {str(e)}")
    
    return {
        "status": "success", 
        "message": f"Model {model} cleanup completed",
        "deleted_resource": cr_name
    }

@app.get("/list")
def list_models(token: str = Depends(verify_token)):
    """
    List all currently deployed models.
    """
    try:
        response = requests.get(
            "http://localhost:8001/list",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Contract Service failed: {str(e)}")

def get_db_connection():
    """Get a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DB
        )
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

@app.get("/status")
def get_server_status(token: str = Depends(verify_token)):
    """
    Get the status of all inference servers from the database.
    Returns memory usage and status for each deployed model.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT uuid, model_name, status, memory_usage_mb, endpoint, updated_at 
            FROM server_status 
            ORDER BY updated_at DESC
        """)
        rows = cur.fetchall()
        
        servers = []
        for row in rows:
            servers.append({
                "uuid": row[0],
                "model_name": row[1],
                "status": row[2],
                "memory_usage_mb": row[3],
                "endpoint": row[4],
                "updated_at": row[5].isoformat() if row[5] else None
            })
        
        return servers
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch server status: {str(e)}")
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
