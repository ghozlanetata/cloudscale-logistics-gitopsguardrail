# CloudScale Logistics - GitOps Manifest Guardrail

CloudScale Logistics is a small shipment-tracking API surrounded by a practical Kubernetes delivery
guardrail. A pull request is checked for application regressions, malformed Kubernetes resources,
workload security gaps, leaked credentials, and high or critical image vulnerabilities. The workflow
can be configured as a required status check before merging. The Kubernetes overlays are the desired
state; a cluster change is made through a reviewed Git change rather than an imperative production
deployment from CI.

This repository contains runnable local-cluster examples. It is not deployed to a public cloud and
does not claim production availability. The bundled PostgreSQL StatefulSet is for local evaluation;
it is not a substitute for a managed, backed-up, highly available database.

## Architecture

```mermaid
flowchart LR
  Dev[Developer] --> PR[GitHub Pull Request]
  PR --> CI[GitHub Actions]
  CI --> Gates[Tests | schema | kube-score | Gitleaks | Trivy]
  Gates --> Review[Review and merge]
  Review --> Git[Git repository desired state]
  Git -. optional Argo CD reconciliation .-> Cluster[Kubernetes]
  subgraph Cluster
    Ingress[Ingress controller namespace] --> API[Logistics API | 2+ replicas]
    API --> PG[(PostgreSQL | local demo)]
    HPA[HPA] -. scales .-> API
  end
```

```mermaid
flowchart LR
  Gateway[ingress-system namespace] -->|TCP 8000| API[logistics-api pods]
  API -->|TCP 5432| DB[postgres pod]
  API -->|UDP/TCP 53| DNS[cluster DNS]
  Other[Other pods / namespaces] -. denied by policy .-> API
  Other -. denied by policy .-> DB
```

The API is exposed as an internal `ClusterIP` Service. The API NetworkPolicy accepts traffic only
from a namespace labeled `kubernetes.io/metadata.name=ingress-system`, and allows egress only to the
Postgres pods and cluster DNS. Postgres accepts connections only from API pods and permits DNS egress
for cluster name resolution. A CNI that enforces Kubernetes NetworkPolicy is required; install and
configure an ingress controller in the named namespace to expose the API through a gateway. For local
smoke testing, use `kubectl port-forward`.

## Technology

| Area           | Implemented                                                                      |
| -------------- | -------------------------------------------------------------------------------- |
| API            | Python 3.12, FastAPI, psycopg 3                                                  |
| Packaging      | Docker, Python slim image, non-root runtime                                      |
| Platform       | Kubernetes, Kustomize, NetworkPolicy, HPA                                        |
| Delivery gates | GitHub Actions, Ruff, pytest, kubeconform, kube-score, Hadolint, Gitleaks, Trivy |
| Automation     | Python manifest guardrail CLI                                                    |

## Repository layout

```text
app/                         FastAPI application
tests/                       API and guardrail tests
tools/validate_manifests.py  Project-specific workload policy checks
k8s/base/                    API, PostgreSQL, policy and scaling resources
k8s/overlays/dev/            Local development image reference
k8s/overlays/production/     Placeholder registry and versioned image tag
examples/insecure/           Deliberately failing, non-deployable fixture
.github/workflows/ci.yaml    Pull request and main branch quality gates
```

## API

| Method and path           | Behavior                                                        |
| ------------------------- | --------------------------------------------------------------- |
| `GET /health`             | Process liveness only; does not depend on PostgreSQL            |
| `GET /ready`              | Returns 503 when a configured PostgreSQL connection check fails |
| `GET /api/shipments`      | Returns deterministic sample shipment records                   |
| `GET /api/shipments/{id}` | Looks up a sample shipment; unknown IDs return 404              |

The shipment records are intentionally small and in-memory: persistence and schema migrations are
outside this guardrail project's scope. When `DATABASE_URL` is configured, readiness checks the
database, which demonstrates dependency-aware routing without pretending that shipment writes are
implemented. With no `DATABASE_URL`, readiness supports local API-only development.

## Security and reliability controls

* The API image and pod run as UID/GID 10001, drop all Linux capabilities, disallow privilege
  escalation, use the runtime default seccomp profile, and mount the root filesystem read-only.
* The pod does not receive a service-account token because it makes no Kubernetes API calls.
* CPU and memory requests and limits make scheduler placement and HPA CPU utilization meaningful.
* The API starts with two replicas, has a best-effort hostname spread constraint, and a
  PodDisruptionBudget that keeps one replica available during voluntary disruptions. These controls
  reduce correlated placement and maintenance impact; they do not protect against every node or
  dependency failure.
* Startup, liveness, and readiness probes serve different purposes. Startup allows initialization
  time before liveness begins. Liveness answers whether the process should be restarted. Readiness
  includes its configured database dependency and controls whether the Service sends it traffic.
  When a pod becomes unready, it remains running but is removed from the Service's ready endpoints
  until its readiness check succeeds again.
* NetworkPolicies constrain API ingress and egress and isolate Postgres ingress. Enforcement depends
  on the cluster CNI; a policy object alone does not enforce traffic on every network plugin.
* No real Secret is committed. `k8s/base/secret.example.yaml` documents the API Secret shape and is
  deliberately excluded from Kustomize resources. The local instructions create secrets with
  `kubectl`; production should use an external secret manager/controller and rotate credentials.
* Gitleaks scans the checked-out repository history for likely credentials. Trivy scans the built
  application image for high and critical OS/library vulnerabilities. These are risk gates, not
  proof of zero risk.

The included Postgres image retains its upstream container security behavior and persistent volume
requirements. It has non-root UID/GID 70, a read-only root with writable data and runtime mounts,
resource bounds, probes, and restricted network ingress. For a real service, use managed PostgreSQL
with backups, failover, encryption, monitoring, and a tested recovery plan.

## CI pipeline

On pull requests and pushes to `main`, GitHub Actions runs:

1. Ruff linting and pytest for API behavior and manifest guardrails.
2. Python checks against the deployable base, then verifies the insecure fixture fails.
3. Kustomize renders both overlays; kubeconform checks Kubernetes schemas and kube-score flags
   workload quality risks such as absent probes, resource bounds, or security settings.
4. Hadolint checks Dockerfile practices and Docker builds the API image.
5. Gitleaks scans for accidentally committed secrets; Trivy fails on fixed high/critical image
   vulnerabilities.

`tools/validate_manifests.py` is intentionally narrow and supplements, rather than replaces,
kubeconform (schema correctness) and kube-score (broader workload heuristics). It checks the specific
security baseline expected by this repository and gives findings with file and container context.

## Intentional failure demonstration

`examples/insecure/deployment.yaml` is excluded from every Kustomize overlay. It has a root user,
privileged mode, extra capabilities, privilege escalation, no resource bounds, no probes, and no
NetworkPolicy. Try:

```sh
python tools/validate_manifests.py examples/insecure
```

The command returns non-zero and describes the gaps. CI repeats that check and separately runs
kube-score against the fixture, requiring both checks to reject it. The engineering loop is:
insecure change -> guardrail fails with actionable findings -> repair the manifest -> the normal
deployment path can pass.

## Run locally

Prerequisites: Python 3.12+, Docker, `kubectl`, and (for cluster use) Minikube or kind with a
NetworkPolicy-capable CNI. Install Python tools and run checks:

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt pytest ruff pyyaml httpx
ruff check app tests tools
pytest -q
python tools/validate_manifests.py k8s/base
```

Run the API and exercise it:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/shipments
```

Build the container:

```sh
docker build -t cloudscale-logistics:dev .
docker run --rm -p 8000:8000 cloudscale-logistics:dev
```

For Minikube, build into its image store, create demo credentials, and apply the dev overlay:

```sh
minikube start
minikube image build -t cloudscale-logistics:dev .
kubectl -n logistics create secret generic postgres-credentials --from-literal=POSTGRES_PASSWORD='local-demo-only'
kubectl -n logistics create secret generic logistics-db --from-literal=DATABASE_URL='postgresql://logistics:local-demo-only@postgres:5432/logistics'
kubectl apply -k k8s/overlays/dev
kubectl -n logistics rollout status statefulset/postgres
kubectl -n logistics rollout status deployment/logistics-api
kubectl -n logistics port-forward service/logistics-api 8000:8000
```

In a second terminal, call `http://127.0.0.1:8000/ready` and `/api/shipments`. Secret creation is
shown before apply because the examples are never stored in Git. For kind, load the image with
`kind load docker-image cloudscale-logistics:dev` after building it. A default Minikube CNI may not
enforce NetworkPolicy; install a compatible CNI before treating policy behavior as tested. HPA
metrics require metrics-server; `kubectl top pods -n logistics` should return metrics before CPU
autoscaling can make decisions.

## GitOps operating model

CI validates changes but does not hold cluster credentials or deploy to Kubernetes. In a production
setup, an Argo CD (or Flux) controller would watch a pinned branch/path, compare live objects with
`k8s/overlays/production`, and reconcile an approved merge. Image tags should be immutable digests
updated by a reviewed automation pull request. Credentials would come from an external secret
provider, and promotion between environments would be represented by overlay changes. This repo
includes Kustomize overlays but does not include or claim a configured Argo CD installation.

The HPA uses two minimum replicas, up to six, targeting 70% average requested CPU. Two replicas
provide a baseline for disruption and rolling updates; six is a modest bounded ceiling for this
example. The target is not a measured capacity claim. CPU utilization scaling requires metrics-server
and appropriate requests on each target container.

## Engineering decisions and trade-offs

* One API keeps the focus on delivery and platform controls rather than service decomposition.
* Sample shipment data keeps API tests deterministic; PostgreSQL is present to exercise dependency
  configuration and readiness, not to imply a complete persistence layer.
* A local Postgres StatefulSet makes the example runnable, while production should use a managed DB.
* The custom validator covers a small explicit baseline; mature schema and quality tools remain the
  authorities for Kubernetes API shape and wider best-practice analysis.
* NetworkPolicy ingress assumes a gateway in `ingress-system`. Change that selector to match the
  actual cluster ingress architecture before deploying elsewhere.

## Troubleshooting

* **API pod waits for Secret:** create both `postgres-credentials` and `logistics-db` in namespace
  `logistics` as shown above; neither contains real committed credentials.
* **Readiness returns 503:** inspect `kubectl logs -n logistics statefulset/postgres` and verify the
  API `DATABASE_URL`, Secret key, DNS name, and PostgreSQL readiness.
* **ImagePullBackOff locally:** load/build the image into the selected cluster and confirm the image
  tag matches the dev overlay.
* **HPA shows `<unknown>`:** install metrics-server and wait for resource metrics; HPA cannot scale
  on CPU utilization without them.
* **Network traffic is unexpectedly blocked or allowed:** verify CNI NetworkPolicy support and the
  ingress namespace labels. Policies are additive; audit all policies selecting these pods.
* **Read-only PostgreSQL startup fails:** check that the writable PVC and `/tmp` and runtime mounts
  are available and compatible with the cluster storage driver.

## Future work

Argo CD application definition, AWS EKS and Terraform provisioning, managed PostgreSQL, Prometheus
and Grafana, external secrets, image signing/verification, and Kyverno or OPA admission policies
would extend this example. None of those are implemented here.
