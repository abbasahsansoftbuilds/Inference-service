package controller

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	modelv1alpha1 "github.com/example/model-operator/api/v1alpha1"
)

// ModelServeReconciler reconciles a ModelServe object
type ModelServeReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// Environment variable defaults
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

//+kubebuilder:rbac:groups=model.example.com,resources=modelserves,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=model.example.com,resources=modelserves/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=model.example.com,resources=modelserves/finalizers,verbs=update
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch
//+kubebuilder:rbac:groups=core,resources=secrets,verbs=get;list;watch
//+kubebuilder:rbac:groups=networking.k8s.io,resources=ingresses,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=traefik.containo.us,resources=middlewares,verbs=get;list;watch;create;update;patch;delete

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
func (r *ModelServeReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	l := log.FromContext(ctx)

	// Fetch the ModelServe instance
	modelServe := &modelv1alpha1.ModelServe{}
	err := r.Get(ctx, req.NamespacedName, modelServe)
	if err != nil {
		if errors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	// Update status to Pending if not set
	if modelServe.Status.Phase == "" {
		modelServe.Status.Phase = "Pending"
		modelServe.Status.Message = "Initializing model server"
		if err := r.Status().Update(ctx, modelServe); err != nil {
			l.Error(err, "Failed to update initial status")
			return ctrl.Result{}, err
		}
	}

	// Create StripPrefix middleware for Traefik
	if err := r.createStripPrefixMiddleware(ctx, modelServe); err != nil {
		l.Error(err, "Failed to create StripPrefix middleware")
		return ctrl.Result{}, err
	}

	// Define Deployment
	dep := r.deploymentForModelServe(modelServe)

	// Check if Deployment exists
	found := &appsv1.Deployment{}
	err = r.Get(ctx, types.NamespacedName{Name: dep.Name, Namespace: dep.Namespace}, found)
	if err != nil && errors.IsNotFound(err) {
		l.Info("Creating a new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
		
		// Update status to Downloading
		modelServe.Status.Phase = "Downloading"
		modelServe.Status.Message = "Downloading model from MinIO"
		if err := r.Status().Update(ctx, modelServe); err != nil {
			l.Error(err, "Failed to update status to Downloading")
		}
		
		err = r.Create(ctx, dep)
		if err != nil {
			l.Error(err, "Failed to create new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
			modelServe.Status.Phase = "Failed"
			modelServe.Status.Message = fmt.Sprintf("Failed to create deployment: %v", err)
			r.Status().Update(ctx, modelServe)
			return ctrl.Result{}, err
		}
		// Deployment created successfully - return and requeue
		return ctrl.Result{Requeue: true}, nil
	} else if err != nil {
		l.Error(err, "Failed to get Deployment")
		return ctrl.Result{}, err
	}

	// Define Service
	svc := r.serviceForModelServe(modelServe)

	// Check if Service exists
	foundSvc := &corev1.Service{}
	err = r.Get(ctx, types.NamespacedName{Name: svc.Name, Namespace: svc.Namespace}, foundSvc)
	if err != nil && errors.IsNotFound(err) {
		l.Info("Creating a new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
		err = r.Create(ctx, svc)
		if err != nil {
			l.Error(err, "Failed to create new Service", "Service.Namespace", svc.Namespace, "Service.Name", svc.Name)
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
	} else if err != nil {
		l.Error(err, "Failed to get Service")
		return ctrl.Result{}, err
	}

	// Define Ingress
	ing := r.ingressForModelServe(modelServe)

	// Check if Ingress exists
	foundIng := &networkingv1.Ingress{}
	err = r.Get(ctx, types.NamespacedName{Name: ing.Name, Namespace: ing.Namespace}, foundIng)
	if err != nil && errors.IsNotFound(err) {
		l.Info("Creating a new Ingress", "Ingress.Namespace", ing.Namespace, "Ingress.Name", ing.Name)
		err = r.Create(ctx, ing)
		if err != nil {
			l.Error(err, "Failed to create new Ingress", "Ingress.Namespace", ing.Namespace, "Ingress.Name", ing.Name)
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
	} else if err != nil {
		l.Error(err, "Failed to get Ingress")
		return ctrl.Result{}, err
	}

	// Update Status based on deployment state
	needsStatusUpdate := false
	
	if found.Status.AvailableReplicas != modelServe.Status.AvailableReplicas {
		modelServe.Status.AvailableReplicas = found.Status.AvailableReplicas
		needsStatusUpdate = true
	}

	// Update service name
	if modelServe.Status.ServiceName != svc.Name {
		modelServe.Status.ServiceName = svc.Name
		needsStatusUpdate = true
	}

	// Update gateway URL
	gatewayURL := fmt.Sprintf("http://localhost/%s", modelServe.Name)
	if modelServe.Status.GatewayURL != gatewayURL {
		modelServe.Status.GatewayURL = gatewayURL
		needsStatusUpdate = true
	}

	// Update phase based on replicas
	if found.Status.AvailableReplicas > 0 {
		if modelServe.Status.Phase != "Running" {
			modelServe.Status.Phase = "Running"
			modelServe.Status.Message = "Model server is running"
			now := metav1.NewTime(time.Now())
			modelServe.Status.StartedAt = &now
			needsStatusUpdate = true
		}
		
		// Try to get pod name
		podList := &corev1.PodList{}
		listOpts := []client.ListOption{
			client.InNamespace(modelServe.Namespace),
			client.MatchingLabels(labelsForModelServe(modelServe.Name)),
		}
		if err := r.List(ctx, podList, listOpts...); err == nil && len(podList.Items) > 0 {
			for _, pod := range podList.Items {
				if pod.Status.Phase == corev1.PodRunning {
					if modelServe.Status.PodName != pod.Name {
						modelServe.Status.PodName = pod.Name
						needsStatusUpdate = true
					}
					break
				}
			}
		}
	} else if modelServe.Status.Phase != "Downloading" && modelServe.Status.Phase != "Failed" {
		modelServe.Status.Phase = "Pending"
		modelServe.Status.Message = "Waiting for pod to be ready"
		needsStatusUpdate = true
	}

	if needsStatusUpdate {
		err = r.Status().Update(ctx, modelServe)
		if err != nil {
			l.Error(err, "Failed to update ModelServe status")
			return ctrl.Result{}, err
		}
	}

	return ctrl.Result{}, nil
}

// createStripPrefixMiddleware creates a Traefik StripPrefix middleware for the model
func (r *ModelServeReconciler) createStripPrefixMiddleware(ctx context.Context, m *modelv1alpha1.ModelServe) error {
	// Create StripPrefix middleware using unstructured object since we may not have Traefik CRDs imported
	middleware := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      m.Name + "-stripprefix",
			Namespace: m.Namespace,
			Labels:    labelsForModelServe(m.Name),
		},
		Data: map[string]string{
			"middleware.yaml": fmt.Sprintf(`
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: %s-stripprefix
  namespace: %s
spec:
  stripPrefix:
    prefixes:
      - /%s
`, m.Name, m.Namespace, m.Name),
		},
	}

	found := &corev1.ConfigMap{}
	err := r.Get(ctx, types.NamespacedName{Name: middleware.Name, Namespace: middleware.Namespace}, found)
	if err != nil && errors.IsNotFound(err) {
		return r.Create(ctx, middleware)
	}
	return err
}

// deploymentForModelServe returns a modelServe Deployment object with MinIO init container
func (r *ModelServeReconciler) deploymentForModelServe(m *modelv1alpha1.ModelServe) *appsv1.Deployment {
	ls := labelsForModelServe(m.Name)
	replicas := m.Spec.Replicas
	if replicas == nil {
		r := int32(1)
		replicas = &r
	}

	image := m.Spec.Image
	if image == "" {
		image = "ghcr.io/ggerganov/llama.cpp:server"
	}

	// Get MinIO configuration from spec or environment
	minioEndpoint := m.Spec.MinIOEndpoint
	if minioEndpoint == "" {
		minioEndpoint = getEnvOrDefault("MINIO_ENDPOINT", "minio:9000")
	}
	
	minioBucket := m.Spec.MinIOBucket
	if minioBucket == "" {
		minioBucket = getEnvOrDefault("MINIO_BUCKET", "inference-models")
	}

	minioPath := m.Spec.MinIOPath
	if minioPath == "" {
		minioPath = "models/" + m.Spec.ModelName
	}

	// Memory and CPU limits
	memoryLimit := m.Spec.MemoryLimit
	if memoryLimit == 0 {
		memoryLimit = 4096 // 4GB default
	}
	cpuLimit := m.Spec.CPULimit
	if cpuLimit == 0 {
		cpuLimit = 2000 // 2 cores default
	}

	// Parse runtime params if provided
	llamaArgs := []string{
		"-m", "/models/" + m.Spec.ModelName,
		"--host", "0.0.0.0",
		"--port", "8080",
	}
	if m.Spec.RuntimeParams != "" {
		// Parse additional params
		extraArgs := strings.Fields(m.Spec.RuntimeParams)
		llamaArgs = append(llamaArgs, extraArgs...)
	}

	shareProcessNamespace := true

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      m.Name,
			Namespace: m.Namespace,
			Labels:    ls,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: ls,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: ls,
					Annotations: map[string]string{
						"model-uuid": m.Spec.ModelUUID,
					},
				},
				Spec: corev1.PodSpec{
					ShareProcessNamespace: &shareProcessNamespace,
					// Init container to download model from MinIO
					InitContainers: []corev1.Container{
						{
							Name:  "download-model",
							Image: "minio/mc:latest",
							Command: []string{"/bin/sh", "-c"},
							Args: []string{
								fmt.Sprintf(`
set -e
echo "Configuring MinIO client..."
mc alias set minio http://%s $MINIO_ACCESS_KEY $MINIO_SECRET_KEY

echo "Downloading model from MinIO..."
mc cp minio/%s/%s /models/%s

echo "Model downloaded successfully"
ls -la /models/
`, minioEndpoint, minioBucket, minioPath, m.Spec.ModelName),
							},
							Env: []corev1.EnvVar{
								{
									Name: "MINIO_ACCESS_KEY",
									ValueFrom: &corev1.EnvVarSource{
										SecretKeyRef: &corev1.SecretKeySelector{
											LocalObjectReference: corev1.LocalObjectReference{Name: "inference-secrets"},
											Key:                  "MINIO_ACCESS_KEY",
										},
									},
								},
								{
									Name: "MINIO_SECRET_KEY",
									ValueFrom: &corev1.EnvVarSource{
										SecretKeyRef: &corev1.SecretKeySelector{
											LocalObjectReference: corev1.LocalObjectReference{Name: "inference-secrets"},
											Key:                  "MINIO_SECRET_KEY",
										},
									},
								},
							},
							VolumeMounts: []corev1.VolumeMount{
								{Name: "model-volume", MountPath: "/models"},
							},
						},
					},
					Containers: []corev1.Container{
						{
							Image: image,
							Name:  "llama-server",
							Args:  llamaArgs,
							Ports: []corev1.ContainerPort{{
								ContainerPort: 8080,
								Name:          "http",
							}},
							VolumeMounts: []corev1.VolumeMount{{
								Name:      "model-volume",
								MountPath: "/models",
							}},
							Resources: corev1.ResourceRequirements{
								Requests: corev1.ResourceList{
									corev1.ResourceMemory: resource.MustParse(fmt.Sprintf("%dMi", memoryLimit/2)),
									corev1.ResourceCPU:    resource.MustParse(fmt.Sprintf("%dm", cpuLimit/2)),
								},
								Limits: corev1.ResourceList{
									corev1.ResourceMemory: resource.MustParse(fmt.Sprintf("%dMi", memoryLimit)),
									corev1.ResourceCPU:    resource.MustParse(fmt.Sprintf("%dm", cpuLimit)),
								},
							},
							ReadinessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									HTTPGet: &corev1.HTTPGetAction{
										Path: "/health",
										Port: intstr.FromInt(8080),
									},
								},
								InitialDelaySeconds: 30,
								PeriodSeconds:       10,
							},
							LivenessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									HTTPGet: &corev1.HTTPGetAction{
										Path: "/health",
										Port: intstr.FromInt(8080),
									},
								},
								InitialDelaySeconds: 60,
								PeriodSeconds:       30,
							},
						},
						{
							Name:    "monitor-sidecar",
							Image:   "python:3.9-slim",
							Command: []string{"/bin/sh", "-c"},
							Args:    []string{"pip install psycopg2-binary psutil requests && python /scripts/monitor.py"},
							Env: []corev1.EnvVar{
								{Name: "SERVER_UUID", Value: m.Name},
								{Name: "MODEL_UUID", Value: m.Spec.ModelUUID},
								{Name: "MODEL_NAME", Value: m.Spec.ModelName},
								{
									Name: "DATABASE_URL",
									ValueFrom: &corev1.EnvVarSource{
										ConfigMapKeyRef: &corev1.ConfigMapKeySelector{
											LocalObjectReference: corev1.LocalObjectReference{Name: "inference-config"},
											Key:                  "DATABASE_URL",
										},
									},
								},
							},
							VolumeMounts: []corev1.VolumeMount{
								{Name: "monitor-script", MountPath: "/scripts"},
							},
							Resources: corev1.ResourceRequirements{
								Requests: corev1.ResourceList{
									corev1.ResourceMemory: resource.MustParse("64Mi"),
									corev1.ResourceCPU:    resource.MustParse("50m"),
								},
								Limits: corev1.ResourceList{
									corev1.ResourceMemory: resource.MustParse("128Mi"),
									corev1.ResourceCPU:    resource.MustParse("100m"),
								},
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "model-volume",
							VolumeSource: corev1.VolumeSource{
								EmptyDir: &corev1.EmptyDirVolumeSource{
									SizeLimit: resource.NewQuantity(10*1024*1024*1024, resource.BinarySI), // 10GB
								},
							},
						},
						{
							Name: "monitor-script",
							VolumeSource: corev1.VolumeSource{
								ConfigMap: &corev1.ConfigMapVolumeSource{
									LocalObjectReference: corev1.LocalObjectReference{Name: "monitor-script"},
								},
							},
						},
					},
				},
			},
		},
	}
}

// serviceForModelServe returns a modelServe Service object
func (r *ModelServeReconciler) serviceForModelServe(m *modelv1alpha1.ModelServe) *corev1.Service {
	ls := labelsForModelServe(m.Name)
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      m.Name,
			Namespace: m.Namespace,
			Labels:    ls,
		},
		Spec: corev1.ServiceSpec{
			Selector: ls,
			Ports: []corev1.ServicePort{{
				Port:       80,
				TargetPort: intstr.FromInt(8080),
			}},
			Type: corev1.ServiceTypeClusterIP,
		},
	}
}

// ingressForModelServe returns a modelServe Ingress object with JWT auth middleware
func (r *ModelServeReconciler) ingressForModelServe(m *modelv1alpha1.ModelServe) *networkingv1.Ingress {
	ls := labelsForModelServe(m.Name)
	pathType := networkingv1.PathTypePrefix

	// Chain JWT auth middleware with strip prefix middleware
	// Format: namespace-middlewarename@kubernetescrd
	middlewares := fmt.Sprintf("%s-jwt-auth@kubernetescrd,%s-%s-stripprefix@kubernetescrd",
		m.Namespace, m.Namespace, m.Name)

	return &networkingv1.Ingress{
		ObjectMeta: metav1.ObjectMeta{
			Name:      m.Name,
			Namespace: m.Namespace,
			Annotations: map[string]string{
				// Traefik middleware chain: JWT auth first, then strip prefix
				"traefik.ingress.kubernetes.io/router.middlewares": middlewares,
			},
			Labels: ls,
		},
		Spec: networkingv1.IngressSpec{
			IngressClassName: func() *string { s := "traefik"; return &s }(),
			Rules: []networkingv1.IngressRule{
				{
					IngressRuleValue: networkingv1.IngressRuleValue{
						HTTP: &networkingv1.HTTPIngressRuleValue{
							Paths: []networkingv1.HTTPIngressPath{
								{
									Path:     "/" + m.Name,
									PathType: &pathType,
									Backend: networkingv1.IngressBackend{
										Service: &networkingv1.IngressServiceBackend{
											Name: m.Name,
											Port: networkingv1.ServiceBackendPort{
												Number: 80,
											},
										},
									},
								},
							},
						},
					},
				},
			},
		},
	}
}

// labelsForModelServe returns the labels for selecting the resources
// belonging to the given modelServe CR name.
func labelsForModelServe(name string) map[string]string {
	return map[string]string{"app": "model-serve", "model_serve_cr": name}
}

// SetupWithManager sets up the controller with the Manager.
func (r *ModelServeReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&modelv1alpha1.ModelServe{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Owns(&networkingv1.Ingress{}).
		Complete(r)
}
