/*
Copyright 2025.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package v1alpha1

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
)

// log is for logging in this package.
var modelservelog = logf.Log.WithName("modelserve-resource")

// JWTClaims represents the JWT payload
type JWTClaims struct {
	Sub  string `json:"sub"`
	Type string `json:"type"`
	Exp  int64  `json:"exp"`
	Iat  int64  `json:"iat"`
}

// SetupWebhookWithManager will setup the manager to manage the webhooks
func (r *ModelServe) SetupWebhookWithManager(mgr ctrl.Manager) error {
	return ctrl.NewWebhookManagedBy(mgr).
		For(r).
		Complete()
}

//+kubebuilder:webhook:path=/mutate-model-example-com-v1alpha1-modelserve,mutating=true,failurePolicy=fail,sideEffects=None,groups=model.example.com,resources=modelserves,verbs=create;update,versions=v1alpha1,name=mmodelserve.kb.io,admissionReviewVersions=v1

var _ webhook.Defaulter = &ModelServe{}

// Default implements webhook.Defaulter so a webhook will be registered for the type
func (r *ModelServe) Default() {
	modelservelog.Info("default", "name", r.Name)

	// Set default values
	if r.Spec.Replicas == nil {
		replicas := int32(1)
		r.Spec.Replicas = &replicas
	}

	if r.Spec.MemoryLimit == 0 {
		r.Spec.MemoryLimit = 4096 // 4GB default
	}

	if r.Spec.CPULimit == 0 {
		r.Spec.CPULimit = 2000 // 2 cores default
	}

	if r.Spec.MinIOBucket == "" {
		r.Spec.MinIOBucket = "inference-models"
	}

	if r.Spec.MinIOEndpoint == "" {
		r.Spec.MinIOEndpoint = "minio:9000"
	}

	if r.Spec.Image == "" {
		r.Spec.Image = "ghcr.io/ggerganov/llama.cpp:server"
	}
}

//+kubebuilder:webhook:path=/validate-model-example-com-v1alpha1-modelserve,mutating=false,failurePolicy=fail,sideEffects=None,groups=model.example.com,resources=modelserves,verbs=create;update;delete,versions=v1alpha1,name=vmodelserve.kb.io,admissionReviewVersions=v1

var _ webhook.Validator = &ModelServe{}

// ValidateCreate implements webhook.Validator so a webhook will be registered for the type
func (r *ModelServe) ValidateCreate() (admission.Warnings, error) {
	modelservelog.Info("validate create", "name", r.Name)

	// Validate JWT from annotation if present
	if err := r.validateJWT(); err != nil {
		return nil, err
	}

	// Validate required fields
	if r.Spec.ModelName == "" {
		return nil, fmt.Errorf("modelName is required")
	}

	if r.Spec.ModelUUID == "" {
		return nil, fmt.Errorf("modelUuid is required")
	}

	if r.Spec.MinIOPath == "" {
		return nil, fmt.Errorf("minioPath is required")
	}

	// Validate replicas
	if r.Spec.Replicas != nil && *r.Spec.Replicas > 5 {
		return nil, fmt.Errorf("replicas cannot exceed 5")
	}

	// Validate memory limit
	if r.Spec.MemoryLimit > 32768 {
		return nil, fmt.Errorf("memoryLimit cannot exceed 32768 MB (32GB)")
	}

	// Validate CPU limit
	if r.Spec.CPULimit > 16000 {
		return nil, fmt.Errorf("cpuLimit cannot exceed 16000m (16 cores)")
	}

	return nil, nil
}

// ValidateUpdate implements webhook.Validator so a webhook will be registered for the type
func (r *ModelServe) ValidateUpdate(old runtime.Object) (admission.Warnings, error) {
	modelservelog.Info("validate update", "name", r.Name)

	// Validate JWT from annotation if present
	if err := r.validateJWT(); err != nil {
		return nil, err
	}

	// Validate replicas
	if r.Spec.Replicas != nil && *r.Spec.Replicas > 5 {
		return nil, fmt.Errorf("replicas cannot exceed 5")
	}

	return nil, nil
}

// ValidateDelete implements webhook.Validator so a webhook will be registered for the type
func (r *ModelServe) ValidateDelete() (admission.Warnings, error) {
	modelservelog.Info("validate delete", "name", r.Name)

	// Validate JWT from annotation if present
	if err := r.validateJWT(); err != nil {
		return nil, err
	}

	return nil, nil
}

// validateJWT validates the JWT token in the annotation
func (r *ModelServe) validateJWT() error {
	// Get JWT secret from environment
	jwtSecret := os.Getenv("JWT_SECRET")
	if jwtSecret == "" {
		jwtSecret = "your-secret-key-change-in-production"
	}

	// Check for JWT in annotation
	token, ok := r.Annotations["model.example.com/auth-token"]
	if !ok {
		// If no token annotation, skip JWT validation (rely on RBAC)
		modelservelog.Info("No auth-token annotation, skipping JWT validation")
		return nil
	}

	// Parse JWT
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return fmt.Errorf("invalid JWT format")
	}

	// Decode header (not used but validate it exists)
	_, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return fmt.Errorf("invalid JWT header: %v", err)
	}

	// Decode payload
	payloadBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return fmt.Errorf("invalid JWT payload: %v", err)
	}

	var claims JWTClaims
	if err := json.Unmarshal(payloadBytes, &claims); err != nil {
		return fmt.Errorf("invalid JWT claims: %v", err)
	}

	// Verify signature
	signatureInput := parts[0] + "." + parts[1]
	h := hmac.New(sha256.New, []byte(jwtSecret))
	h.Write([]byte(signatureInput))
	expectedSignature := base64.RawURLEncoding.EncodeToString(h.Sum(nil))

	if parts[2] != expectedSignature {
		return fmt.Errorf("invalid JWT signature")
	}

	// Check expiration
	if claims.Exp < time.Now().Unix() {
		return fmt.Errorf("JWT token has expired")
	}

	// Validate token type
	if claims.Type != "internal" && claims.Type != "user" {
		return fmt.Errorf("invalid token type: %s", claims.Type)
	}

	modelservelog.Info("JWT validated successfully", "sub", claims.Sub, "type", claims.Type)
	return nil
}
