#!/bin/bash

echo "=== Testing Inference Service Deployment ==="
echo

echo "1. Testing health endpoint (no auth required)..."
HEALTH=$(curl -s -H "Host: inference.local" http://localhost:8180/health)
echo "Health: $HEALTH"
echo

echo "2. Getting authentication token..."
TOKEN=$(curl -s -X POST -H "Host: inference.local" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin-password"}' \
  http://localhost:8180/auth/token | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "ERROR: Failed to get token"
  exit 1
fi
echo "Token received: ${TOKEN:0:50}..."
echo

echo "3. Testing /status endpoint (requires auth)..."
STATUS=$(curl -s -H "Host: inference.local" \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8180/status)
echo "Status: $STATUS"
echo

echo "4. Testing /models/available endpoint..."
MODELS=$(curl -s -H "Host: inference.local" \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8180/models/available)
echo "Models: $MODELS"
echo

echo "5. Checking ModelServe CR status..."
kubectl get modelserves test-model -o json | \
  python3 -c "import sys, json; ms=json.load(sys.stdin); print(f'ModelServe: {ms[\"metadata\"][\"name\"]}'); print(f'Spec: {ms[\"spec\"]}')" 2>/dev/null
echo

echo "6. Checking deployed resources..."
kubectl get pods -l model_serve_cr=test-model
echo

echo "=== All tests complete ==="
