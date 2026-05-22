# ArgoCD

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade -i -n argocd-image-updater argocd-image-updater argo/argocd-image-updater --values values.yaml
```