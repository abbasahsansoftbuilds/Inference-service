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
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// ModelServeSpec defines the desired state of ModelServe
type ModelServeSpec struct {
	// ModelName is the name of the model file (e.g., "Qwen.gguf")
	ModelName string `json:"modelName"`

	// ModelUUID is the unique identifier for the model in the database
	ModelUUID string `json:"modelUuid"`

	// MinIOPath is the path to the model in MinIO (e.g., "models/Qwen.gguf")
	MinIOPath string `json:"minioPath"`

	// MinIOEndpoint is the MinIO service endpoint (e.g., "minio:9000")
	// +optional
	MinIOEndpoint string `json:"minioEndpoint,omitempty"`

	// MinIOBucket is the bucket name containing the model
	// +optional
	MinIOBucket string `json:"minioBucket,omitempty"`

	// Image is the container image to use for serving (optional)
	// +optional
	Image string `json:"image,omitempty"`

	// Replicas is the number of replicas to run (optional, default 1)
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// RuntimeParams are additional runtime parameters for llama.cpp
	// +optional
	RuntimeParams string `json:"runtimeParams,omitempty"`

	// MemoryLimit is the maximum memory in MB for the container
	// +optional
	MemoryLimit int32 `json:"memoryLimit,omitempty"`

	// CPULimit is the maximum CPU in millicores for the container
	// +optional
	CPULimit int32 `json:"cpuLimit,omitempty"`
}

// ModelServeStatus defines the observed state of ModelServe
type ModelServeStatus struct {
	// AvailableReplicas is the number of available replicas
	AvailableReplicas int32 `json:"availableReplicas"`

	// Phase is the current phase of the ModelServe (Pending, Downloading, Running, Failed)
	Phase string `json:"phase,omitempty"`

	// GatewayURL is the URL to access the model through the ingress
	GatewayURL string `json:"gatewayUrl,omitempty"`

	// ServiceName is the name of the Kubernetes service
	ServiceName string `json:"serviceName,omitempty"`

	// PodName is the name of the pod running the model
	PodName string `json:"podName,omitempty"`

	// StartedAt is when the model server started
	StartedAt *metav1.Time `json:"startedAt,omitempty"`

	// Message provides additional information about the current status
	Message string `json:"message,omitempty"`
}

//+kubebuilder:object:root=true
//+kubebuilder:subresource:status
//+kubebuilder:printcolumn:name="Model",type=string,JSONPath=`.spec.modelName`
//+kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`
//+kubebuilder:printcolumn:name="Replicas",type=integer,JSONPath=`.status.availableReplicas`
//+kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// ModelServe is the Schema for the modelserves API
type ModelServe struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ModelServeSpec   `json:"spec,omitempty"`
	Status ModelServeStatus `json:"status,omitempty"`
}

//+kubebuilder:object:root=true

// ModelServeList contains a list of ModelServe
type ModelServeList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ModelServe `json:"items"`
}

func init() {
	SchemeBuilder.Register(&ModelServe{}, &ModelServeList{})
}
