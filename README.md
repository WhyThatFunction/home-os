# Home OS

- Talos

## Talos

- Simple (x86):
  Link
  [here](https://factory.talos.dev/?arch=amd64&board=undefined&cmdline-set=true&extensions=-&extensions=siderolabs%2Fqemu-guest-agent&platform=metal&secureboot=undefined&target=metal&version=1.10.4)

  ```yaml
  customization:
    systemExtensions:
      officialExtensions:
        - siderolabs/qemu-guest-agent
  ```

  and produces the id `ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515`


- Simple (longhorn ready) (x86):
  Link
  [here](https://factory.talos.dev/?arch=amd64&board=undefined&cmdline-set=true&extensions=-&extensions=siderolabs%2Fiscsi-tools&extensions=siderolabs%2Fqemu-guest-agent&extensions=siderolabs%2Futil-linux-tools&platform=metal&secureboot=undefined&target=metal&version=1.10.4)

  ```yaml
  customization:
    systemExtensions:
      officialExtensions:
        - siderolabs/iscsi-tools
        - siderolabs/qemu-guest-agent
        - siderolabs/util-linux-tools
  ```

  and produces the id `88d1f7a5c4f1d3aba7df787c448c1d3d008ed29cfb34af53fa0df4336a56040b`


- Nvidia ready (x86):
  Link
  [here](https://factory.talos.dev/?arch=amd64&board=undefined&cmdline-set=true&extensions=-&extensions=siderolabs%2Fiscsi-tools&extensions=siderolabs%2Fnvidia-container-toolkit-production&extensions=siderolabs%2Fqemu-guest-agent&extensions=siderolabs%2Futil-linux-tools&extensions=siderolabs%2Fnonfree-kmod-nvidia-production&platform=metal&secureboot=undefined&target=metal&version=1.10.4)
  ```yaml
  customization:
    systemExtensions:
      officialExtensions:
        - siderolabs/iscsi-tools
        - siderolabs/nonfree-kmod-nvidia-production
        - siderolabs/nvidia-container-toolkit-production
        - siderolabs/qemu-guest-agent
        - siderolabs/util-linux-tools
  ```

  and produces the id `c35d5bd14fd96abc839f9f44f5effd00c48f654edb8a42648f4b2eb6051d1dd6`

## Longhorn

[Integrate with talos](https://longhorn.io/docs/1.9.0/advanced-resources/os-distro-specific/talos-linux-support/).

Managed by ArgoCD.

## Nvidia

Links [here](https://www.talos.dev/v1.10/talos-guides/configuration/nvidia-gpu). 
Managed by ArgoCD.

## CloudNative PG

Managed by ArgoCD.

Testing:
```shell
kubectl apply -f - <<EOF
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: postgresql-storage
spec:
  instances: 2
  affinity:
    nodeSelector:
      data-node: "true"
  # Example of rolling update strategy:
  # - unsupervised: automated update of the primary once all
  #                 replicas have been upgraded (default)
  # - supervised: requires manual supervision to perform
  #               the switchover of the primary
  #primaryUpdateStrategy: unsupervised

  # Persistent storage configuration
  storage:
    storageClass: longhorn-local
    size: 1Gi

EOF
```