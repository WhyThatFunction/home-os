# Monitoring

## Secrets first

This chart needs some secrets:
- keycloak
  ```
  ...
  metadata:
    name: keycloak-conf
    namespace: <monitoring-namspace>
  ...
  stringData:
    KEYCLOAK_CLIENT_ID: "<keycloak-client-id>"
    KEYCLOAK_CLIENT_SECRET: "<keycloak-client-secret>"
    KEYCLOAK_ISSUER: "<keycloak-issuer>"
  ```
- minio
  ```
  ...
  metadata:
    name: minio
    namespace: <monitoring-namspace>
  ...
  stringData:
    rootUser: "<root-user>"
    rootPassword: "<root-password>"
  ```
  
## Configurations
