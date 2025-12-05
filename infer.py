#!/usr/bin/env python3
"""
Inference Service CLI - Serve and Cleanup LLM models

Usage:
    python3 infer.py serve <model_name>   - Deploy and serve a model (with port-forward)
    python3 infer.py clean <model_name>   - Cleanup/remove a deployed model
    python3 infer.py list                 - List all deployed models with ports
"""

import sys
import socket
import subprocess
import time
import requests
import argparse
import os
import signal

# Configuration
BASE_URL = os.getenv("FASTAPI_URL", "http://localhost:8200")
HEADERS = {"Authorization": "Bearer test-token"}
PID_DIR = "/tmp/inference_service_pf"

def find_available_port(start_port=8181):
    """Find the next available port starting from start_port."""
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            result = sock.connect_ex(('localhost', port))
            if result != 0:
                return port
            port += 1
    raise RuntimeError("No available ports found")

def get_pid_file(model_name: str) -> str:
    """Get the PID file path for a model's port-forward process."""
    os.makedirs(PID_DIR, exist_ok=True)
    return os.path.join(PID_DIR, f"{model_name.lower()}.pid")

def get_port_file(model_name: str) -> str:
    """Get the port file path for a model's forwarded port."""
    os.makedirs(PID_DIR, exist_ok=True)
    return os.path.join(PID_DIR, f"{model_name.lower()}.port")

def start_port_forward(model_name: str, k8s_service_name: str) -> int:
    """Start kubectl port-forward for a model and return the local port."""
    local_port = find_available_port(8181)
    
    cmd = [
        "kubectl", "port-forward",
        f"svc/{k8s_service_name}",
        "-n", "default",
        f"{local_port}:80"
    ]
    
    # Start kubectl as a background process
    pf_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True  # Detach from parent
    )
    
    # Save PID and port
    pid_file = get_pid_file(model_name)
    port_file = get_port_file(model_name)
    
    with open(pid_file, 'w') as f:
        f.write(str(pf_process.pid))
    with open(port_file, 'w') as f:
        f.write(str(local_port))
    
    return local_port

def stop_port_forward(model_name: str):
    """Stop the port-forward process for a model."""
    pid_file = get_pid_file(model_name)
    port_file = get_port_file(model_name)
    
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass
        os.remove(pid_file)
    
    if os.path.exists(port_file):
        os.remove(port_file)

def get_forwarded_port(model_name: str) -> int | None:
    """Get the forwarded port for a model, or None if not forwarded."""
    port_file = get_port_file(model_name)
    pid_file = get_pid_file(model_name)
    
    if not os.path.exists(port_file) or not os.path.exists(pid_file):
        return None
    
    # Check if process is still running
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check if process exists
        
        with open(port_file, 'r') as f:
            return int(f.read().strip())
    except (ProcessLookupError, ValueError, FileNotFoundError):
        # Process died, clean up
        stop_port_forward(model_name)
        return None

def serve_model(model_name: str):
    """
    Request the server to deploy and serve a model, then set up port forwarding.
    """
    model_filename = f"{model_name}.gguf"
    serve_url = f"{BASE_URL}/serve"
    params = {"model": model_filename}
    k8s_service_name = f"model-{model_name.lower()}-gguf"
    
    print(f"--- Serving model: {model_name} ---")
    print(f"[1/2] Requesting server to load: {model_filename}...")
    
    try:
        response = requests.get(serve_url, params=params, headers=HEADERS)
        response.raise_for_status()
        result = response.json()
        print(f"      ✓ Success: Model deployment requested")
        print(f"      CR Name: {result['cr']['metadata']['name']}")
    except requests.exceptions.RequestException as e:
        print(f"      ✗ Error: {e}")
        return False
    
    # Wait for deployment to be ready
    print(f"[2/2] Setting up port forwarding...")
    print(f"      Waiting for pod to be ready...")
    time.sleep(5)  # Give K8s time to create the pod
    
    # Check if service exists and pod is ready
    max_retries = 30
    for i in range(max_retries):
        try:
            result = subprocess.run(
                ["kubectl", "get", "svc", k8s_service_name, "-n", "default"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                break
        except Exception:
            pass
        if i < max_retries - 1:
            time.sleep(2)
    else:
        print(f"      ✗ Service not ready after {max_retries * 2}s")
        return False
    
    # Start port forwarding
    try:
        local_port = start_port_forward(model_name, k8s_service_name)
        time.sleep(2)  # Wait for port-forward to establish
        print(f"      ✓ Port forwarding established")
        print(f"")
        print(f"      Model accessible at: http://localhost:{local_port}")
        print(f"      Example: curl http://localhost:{local_port}/v1/chat/completions \\")
        print(f"               -H 'Content-Type: application/json' \\")
        print(f"               -d '{{\"model\":\"{model_name}\",\"messages\":[{{\"role\":\"user\",\"content\":\"Hello\"}}]}}'")
        return True
    except Exception as e:
        print(f"      ✗ Failed to set up port forwarding: {e}")
        return False

def cleanup_model(model_name: str):
    """
    Request the server to cleanup/delete a deployed model and stop port forwarding.
    """
    model_filename = f"{model_name}.gguf"
    cleanup_url = f"{BASE_URL}/cleanup"
    params = {"model": model_filename}
    
    print(f"--- Cleaning up model: {model_name} ---")
    
    # Stop port forwarding first
    print(f"[1/2] Stopping port forwarding...")
    stop_port_forward(model_name)
    print(f"      ✓ Port forwarding stopped")
    
    print(f"[2/2] Requesting server to remove: {model_filename}...")
    
    try:
        response = requests.delete(cleanup_url, params=params, headers=HEADERS)
        response.raise_for_status()
        result = response.json()
        print(f"      ✓ Success: {result['message']}")
        print(f"      Deleted: {result['deleted_resource']}")
        return True
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"      ✗ Model not found or already cleaned up")
        else:
            print(f"      ✗ Error: {e}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"      ✗ Error: {e}")
        return False

def list_models():
    """
    List all currently deployed models with their forwarded ports.
    """
    list_url = f"{BASE_URL}/list"
    
    print("--- Deployed Models ---")
    
    try:
        response = requests.get(list_url, headers=HEADERS)
        response.raise_for_status()
        result = response.json()
        
        if not result.get('models'):
            print("  No models currently deployed.")
            return True
        
        for model in result['models']:
            # Extract model name from modelName (e.g., "Qwen.gguf" -> "Qwen")
            model_name = model['modelName'].replace('.gguf', '')
            port = get_forwarded_port(model_name)
            
            print(f"  • {model['name']}")
            print(f"      Model: {model['modelName']}")
            print(f"      Replicas: {model['replicas']}")
            if port:
                print(f"      Port: http://localhost:{port}")
            else:
                print(f"      Port: (not forwarded - run 'serve {model_name}' to forward)")
        
        return True
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Inference Service CLI - Serve and Cleanup LLM models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 infer.py serve Qwen      Deploy the Qwen model
  python3 infer.py clean Qwen      Remove the Qwen model deployment
  python3 infer.py list            List all deployed models
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Deploy and serve a model")
    serve_parser.add_argument("model_name", help="Name of the model (e.g., Qwen, danube)")
    
    # Clean command
    clean_parser = subparsers.add_parser("clean", help="Cleanup/remove a deployed model")
    clean_parser.add_argument("model_name", help="Name of the model to remove")
    
    # List command
    subparsers.add_parser("list", help="List all deployed models")
    
    args = parser.parse_args()
    
    if args.command == "serve":
        success = serve_model(args.model_name)
        sys.exit(0 if success else 1)
    elif args.command == "clean":
        success = cleanup_model(args.model_name)
        sys.exit(0 if success else 1)
    elif args.command == "list":
        success = list_models()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
