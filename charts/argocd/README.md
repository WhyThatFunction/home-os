# ArgoCD

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade -i -n argocd argocd argo/argo-cd --values values.yaml
```