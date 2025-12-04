package controller

import (
	"context"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/api/errors"
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

//+kubebuilder:rbac:groups=model.example.com,resources=modelserves,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=model.example.com,resources=modelserves/status,verbs=get;update;patch
//+kubebuilder:rbac:groups=model.example.com,resources=modelserves/finalizers,verbs=update
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=networking.k8s.io,resources=ingresses,verbs=get;list;watch;create;update;patch;delete

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

	// Define Deployment
	dep := r.deploymentForModelServe(modelServe)

	// Check if Deployment exists
	found := &appsv1.Deployment{}
	err = r.Get(ctx, types.NamespacedName{Name: dep.Name, Namespace: dep.Namespace}, found)
	if err != nil && errors.IsNotFound(err) {
		l.Info("Creating a new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
		err = r.Create(ctx, dep)
		if err != nil {
			l.Error(err, "Failed to create new Deployment", "Deployment.Namespace", dep.Namespace, "Deployment.Name", dep.Name)
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

	// Update Status
	if found.Status.AvailableReplicas != modelServe.Status.AvailableReplicas {
		modelServe.Status.AvailableReplicas = found.Status.AvailableReplicas
		err = r.Status().Update(ctx, modelServe)
		if err != nil {
			l.Error(err, "Failed to update ModelServe status")
			return ctrl.Result{}, err
		}
	}

	return ctrl.Result{}, nil
}

// deploymentForModelServe returns a modelServe Deployment object
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

	shareProcessNamespace := true

	// For dev mode, we mount the local path.
	// In production, we would download from S3.
	// Here we assume the node has the volume mounted at /home/Inference_service/Model_Catalog

	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      m.Name,
			Namespace: m.Namespace,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: ls,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: ls,
				},
				Spec: corev1.PodSpec{
					ShareProcessNamespace: &shareProcessNamespace,
					Containers: []corev1.Container{
						{
							Image: image,
							Name:  "llama-server",
							Args: []string{
								"-m", "/models/" + m.Spec.ModelName, // Assuming model file is at /models/<ModelName>
								"--host", "0.0.0.0",
								"--port", "8080",
							},
							Ports: []corev1.ContainerPort{{
								ContainerPort: 8080,
								Name:          "http",
							}},
							VolumeMounts: []corev1.VolumeMount{{
								Name:      "model-volume",
								MountPath: "/models",
							}},
						},
						{
							Name:    "monitor-sidecar",
							Image:   "python:3.9-slim",
							Command: []string{"/bin/sh", "-c"},
							Args:    []string{"pip install psycopg2-binary psutil && python /scripts/monitor.py"},
							Env: []corev1.EnvVar{
								{Name: "SERVER_UUID", Value: m.Name},
								{Name: "MODEL_NAME", Value: m.Spec.ModelName},
							},
							VolumeMounts: []corev1.VolumeMount{
								{Name: "monitor-script", MountPath: "/scripts"},
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "model-volume",
							VolumeSource: corev1.VolumeSource{
								HostPath: &corev1.HostPathVolumeSource{
									Path: "/home/Inference_service/Model_Catalog", // Map to the node's path
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

// ingressForModelServe returns a modelServe Ingress object
func (r *ModelServeReconciler) ingressForModelServe(m *modelv1alpha1.ModelServe) *networkingv1.Ingress {
	ls := labelsForModelServe(m.Name)
	pathType := networkingv1.PathTypePrefix

	return &networkingv1.Ingress{
		ObjectMeta: metav1.ObjectMeta{
			Name:      m.Name,
			Namespace: m.Namespace,
			Annotations: map[string]string{
				// Traefik middleware for stripping the path prefix
				"traefik.ingress.kubernetes.io/router.middlewares": "default-" + m.Name + "-stripprefix@kubernetescrd",
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
