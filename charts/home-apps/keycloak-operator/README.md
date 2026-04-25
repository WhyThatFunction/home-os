# Keycloak Operator, Locally

```shell
export KEYCLOAK_VERSION="26.6.1"

curl -LO https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/$(KEYCLOAK_VERSION)/kubernetes/keycloaks.k8s.keycloak.org-v1.yml
curl -LO https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/$(KEYCLOAK_VERSION)/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml
curl -LO https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/$(KEYCLOAK_VERSION)/kubernetes/kubernetes.yml
```