from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
from kubernetes import client, config, dynamic
from kubernetes.client import api_client
import os
import psycopg2

app = FastAPI()

# Database configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "inference_db")

def get_db_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB
    )

# Load K8s config
try:
    config.load_kube_config()
except:
    config.load_incluster_config()

# Dynamic client for CRs
dyn_client = dynamic.DynamicClient(api_client.ApiClient())

class CRTemplate(BaseModel):
    apiVersion: str
    kind: str
    metadata: dict
    spec: dict

def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format")
    token = authorization.split(" ")[1]
    # In a real app, verify the token signature here.
    return token

@app.post("/apply")
async def apply_cr(cr: dict, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
         raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = authorization.split(" ")[1]
    
    # 1. Validation Logic
    # Schema validation is implicit via K8s, but we can add policy checks here.
    # e.g. Check resource limits (not in our simple CRD yet, but placeholder)
    
    if cr.get("kind") != "ModelServe":
        raise HTTPException(status_code=400, detail="Invalid kind")

    # 2. Apply to Kubernetes
    resource_api = dyn_client.resources.get(api_version=cr["apiVersion"], kind=cr["kind"])
    
    try:
        # Try to create, if exists, patch (or just apply logic)
        # For simplicity, we'll try to create and ignore if exists (or update)
        # Server-side apply is better but let's stick to simple create/patch
        
        # Check if exists
        name = cr["metadata"]["name"]
        namespace = cr["metadata"].get("namespace", "default")
        
        try:
            existing = resource_api.get(name=name, namespace=namespace)
            # Update
            cr["metadata"]["resourceVersion"] = existing.metadata.resourceVersion
            response = resource_api.replace(body=cr, namespace=namespace)
            action = "updated"
        except Exception:
            # Create
            response = resource_api.create(body=cr, namespace=namespace)
            action = "created"
            
            # Create Traefik Middleware for path stripping
            try:
                middleware = {
                    "apiVersion": "traefik.io/v1alpha1",
                    "kind": "Middleware",
                    "metadata": {
                        "name": f"{name}-stripprefix",
                        "namespace": namespace
                    },
                    "spec": {
                        "stripPrefix": {
                            "prefixes": [f"/{name}"]
                        }
                    }
                }
                middleware_api = dyn_client.resources.get(api_version="traefik.io/v1alpha1", kind="Middleware")
                middleware_api.create(body=middleware, namespace=namespace)
            except Exception as mw_err:
                # Middleware might already exist, that's ok
                pass
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply CR: {str(e)}")
        
    return {"status": "success", "message": f"Resource {action}", "name": name}

@app.post("/delete")
async def delete_cr(request: dict, authorization: str = Header(None)):
    """
    Delete a ModelServe CR and its associated resources (Deployment, Service).
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
    
    # 2. Delete the Deployment (same name as CR)
    try:
        apps_api = client.AppsV1Api()
        apps_api.delete_namespaced_deployment(name=name, namespace=namespace)
        deleted_resources.append(f"Deployment/{name}")
    except client.exceptions.ApiException as e:
        if e.status != 404:
            errors.append(f"Deployment: {e.reason}")
    
    # 3. Delete the Service (same name as CR)
    try:
        core_api = client.CoreV1Api()
        core_api.delete_namespaced_service(name=name, namespace=namespace)
        deleted_resources.append(f"Service/{name}")
    except client.exceptions.ApiException as e:
        if e.status != 404:
            errors.append(f"Service: {e.reason}")
    
    # 4. Delete the Ingress (same name as CR)
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
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM server_status WHERE uuid = %s", (name,))
        conn.commit()
        cur.close()
        conn.close()
        deleted_resources.append(f"DB/{name}")
    except Exception as e:
        errors.append(f"Database: {str(e)}")
    
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
    """
    List all deployed ModelServe CRs.
    """
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
                "replicas": item.spec.get("replicas", 1),
                "status": getattr(item, "status", {})
            })
        
        return {"status": "success", "models": models}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CRs: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
