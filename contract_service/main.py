"""
Contract Service - Policy Enforcement and K8s Resource Management

Validates Custom Resources, enforces resource contracts, and applies them to the cluster.
"""
import os
import sys
import traceback
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from kubernetes import client, config, dynamic
from kubernetes.client import api_client

# Add shared directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import verify_token
from shared.database import get_db, init_db, ServerRecord, update_server_status

app = FastAPI(
    title="Contract Service",
    description="Policy enforcement and Kubernetes resource management",
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

# Resource limits for contract enforcement
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "5"))
MAX_MEMORY_MB = int(os.getenv("MAX_MEMORY_MB", "16384"))  # 16GB default
ALLOWED_NAMESPACES = os.getenv("ALLOWED_NAMESPACES", "default").split(",")

# Load K8s config
try:
    config.load_kube_config()
except:
    config.load_incluster_config()

# Dynamic client for CRs
dyn_client = dynamic.DynamicClient(api_client.ApiClient())


class ResourceContract(BaseModel):
    """Resource contract limits."""
    max_replicas: int = MAX_REPLICAS
    max_memory_mb: int = MAX_MEMORY_MB
    allowed_namespaces: list = ALLOWED_NAMESPACES


def validate_resource_contract(cr: dict) -> tuple[bool, str]:
    """
    Validate that a CR meets resource contract requirements.
    Returns (is_valid, error_message).
    """
    spec = cr.get("spec", {})
    metadata = cr.get("metadata", {})
    namespace = metadata.get("namespace", "default")
    
    # Check namespace
    if namespace not in ALLOWED_NAMESPACES:
        return False, f"Namespace '{namespace}' not allowed. Allowed: {ALLOWED_NAMESPACES}"
    
    # Check replicas
    replicas = spec.get("replicas", 1)
    if replicas > MAX_REPLICAS:
        return False, f"Replicas ({replicas}) exceeds maximum ({MAX_REPLICAS})"
    
    if replicas < 1:
        return False, "Replicas must be at least 1"
    
    # Check required fields
    if not spec.get("modelName"):
        return False, "modelName is required in spec"
    
    if not spec.get("minioPath"):
        return False, "minioPath is required in spec"
    
    return True, ""


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    init_db()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "contract-service"}


@app.get("/contract")
async def get_contract(authorization: str = Header(None)):
    """Get current resource contract limits."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    return ResourceContract()


@app.post("/apply")
async def apply_cr(cr: dict, authorization: str = Header(None)):
    """
    Apply a ModelServe Custom Resource with contract validation.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    # Validate kind
    if cr.get("kind") != "ModelServe":
        raise HTTPException(status_code=400, detail="Invalid kind. Expected 'ModelServe'")
    
    # Validate resource contract
    is_valid, error_msg = validate_resource_contract(cr)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Contract violation: {error_msg}")
    
    # Apply to Kubernetes
    resource_api = dyn_client.resources.get(api_version=cr["apiVersion"], kind=cr["kind"])
    
    try:
        name = cr["metadata"]["name"]
        namespace = cr["metadata"].get("namespace", "default")
        
        try:
            existing = resource_api.get(name=name, namespace=namespace)
            cr["metadata"]["resourceVersion"] = existing.metadata.resourceVersion
            response = resource_api.replace(body=cr, namespace=namespace)
            action = "updated"
        except Exception:
            response = resource_api.create(body=cr, namespace=namespace)
            action = "created"
            
            # Create Traefik Middleware for path stripping
            try:
                # Also create middleware for server UUID if present
                server_uuid = cr.get("metadata", {}).get("annotations", {}).get("serverUuid")
                prefixes = [f"/{name}"]
                if server_uuid:
                    prefixes.append(f"/{server_uuid}")
                
                middleware = {
                    "apiVersion": "traefik.io/v1alpha1",
                    "kind": "Middleware",
                    "metadata": {
                        "name": f"{name}-stripprefix",
                        "namespace": namespace
                    },
                    "spec": {
                        "stripPrefix": {
                            "prefixes": prefixes
                        }
                    }
                }
                middleware_api = dyn_client.resources.get(api_version="traefik.io/v1alpha1", kind="Middleware")
                middleware_api.create(body=middleware, namespace=namespace)
            except Exception:
                pass
            
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to apply CR: {str(e)}")
    
    return {"status": "success", "message": f"Resource {action}", "name": name}


@app.post("/delete")
async def delete_cr(request: dict, authorization: str = Header(None)):
    """
    Delete a ModelServe CR and its associated resources.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    name = request.get("name")
    namespace = request.get("namespace", "default")
    
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name' in request")
    
    deleted_resources = []
    errors = []
    
    # 1. Delete the ModelServe CR
    try:
        resource_api = dyn_client.resources.get(
            api_version="model.example.com/v1alpha1", 
            kind="ModelServe"
        )
        resource_api.delete(name=name, namespace=namespace)
        deleted_resources.append(f"ModelServe/{name}")
    except Exception as e:
        if "NotFound" not in str(e):
            errors.append(f"ModelServe: {str(e)}")
    
    # 2. Delete the Deployment
    try:
        apps_api = client.AppsV1Api()
        apps_api.delete_namespaced_deployment(name=name, namespace=namespace)
        deleted_resources.append(f"Deployment/{name}")
    except client.exceptions.ApiException as e:
        if e.status != 404:
            errors.append(f"Deployment: {e.reason}")
    
    # 3. Delete the Service
    try:
        core_api = client.CoreV1Api()
        core_api.delete_namespaced_service(name=name, namespace=namespace)
        deleted_resources.append(f"Service/{name}")
    except client.exceptions.ApiException as e:
        if e.status != 404:
            errors.append(f"Service: {e.reason}")
    
    # 4. Delete the Ingress
    try:
        networking_api = client.NetworkingV1Api()
        networking_api.delete_namespaced_ingress(name=name, namespace=namespace)
        deleted_resources.append(f"Ingress/{name}")
    except client.exceptions.ApiException as e:
        if e.status != 404:
            errors.append(f"Ingress: {e.reason}")
    
    # 5. Delete the Traefik Middleware
    try:
        middleware_api = dyn_client.resources.get(api_version="traefik.io/v1alpha1", kind="Middleware")
        middleware_api.delete(name=f"{name}-stripprefix", namespace=namespace)
        deleted_resources.append(f"Middleware/{name}-stripprefix")
    except Exception as e:
        if "NotFound" not in str(e):
            errors.append(f"Middleware: {str(e)}")
    
    # 6. Delete from database
    db = get_db()
    try:
        # Delete server records matching this CR name pattern
        db.query(ServerRecord).filter(
            ServerRecord.uuid.like(f"{name}%")
        ).delete(synchronize_session=False)
        db.commit()
        deleted_resources.append(f"DB/{name}")
    except Exception as e:
        errors.append(f"Database: {str(e)}")
    finally:
        db.close()
    
    if not deleted_resources and errors:
        raise HTTPException(status_code=500, detail=f"Failed to delete resources: {errors}")
    
    return {
        "status": "success", 
        "message": f"Resource {name} deleted", 
        "name": name,
        "deleted": deleted_resources,
        "errors": errors if errors else None
    }


@app.get("/list")
async def list_crs(authorization: str = Header(None)):
    """List all deployed ModelServe CRs."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    try:
        resource_api = dyn_client.resources.get(
            api_version="model.example.com/v1alpha1",
            kind="ModelServe"
        )
        
        items = resource_api.get(namespace="default")
        
        models = []
        for item in items.items:
            models.append({
                "name": item.metadata.name,
                "modelName": item.spec.get("modelName", "unknown"),
                "modelUuid": item.spec.get("modelUuid"),
                "serverUuid": item.spec.get("serverUuid"),
                "replicas": item.spec.get("replicas", 1),
                "status": getattr(item, "status", {})
            })
        
        return {"status": "success", "models": models}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CRs: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("CONTRACT_PORT", "8201"))
    uvicorn.run(app, host="0.0.0.0", port=port)
