#!/bin/sh

set -eu

KUBE_CONTEXT="${KUBE_CONTEXT:-admin@homeos}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-s3}"
LEGACY_DEPLOYMENT="${LEGACY_DEPLOYMENT:-s3-minio}"
RUSTFS_DEPLOYMENT="${RUSTFS_DEPLOYMENT:-rustfs}"
DATA_CLAIM="${DATA_CLAIM:-s3-minio}"
EXPECTED_STORAGE_CLASS="${EXPECTED_STORAGE_CLASS:-sstorage}"
EXPECTED_NAS_PATH="${EXPECTED_NAS_PATH:-/volume1/k8s/pvcs/s3/s3-minio}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

kube() {
  kubectl --context "$KUBE_CONTEXT" --namespace "$KUBE_NAMESPACE" "$@"
}

claim_checks() {
  claim_json="$(kube get persistentvolumeclaim "$DATA_CLAIM" -o json)" ||
    fail "PVC $KUBE_NAMESPACE/$DATA_CLAIM is missing"

  claim_phase="$(printf '%s' "$claim_json" | jq -r '.status.phase')"
  storage_class="$(printf '%s' "$claim_json" | jq -r '.spec.storageClassName')"
  access_modes="$(printf '%s' "$claim_json" | jq -r '.spec.accessModes | join(",")')"
  requested_size="$(printf '%s' "$claim_json" | jq -r '.spec.resources.requests.storage')"
  volume_name="$(printf '%s' "$claim_json" | jq -r '.spec.volumeName')"

  [ "$claim_phase" = Bound ] || fail "PVC is $claim_phase, expected Bound"
  [ "$storage_class" = "$EXPECTED_STORAGE_CLASS" ] ||
    fail "PVC storageClass is $storage_class, expected $EXPECTED_STORAGE_CLASS"
  [ "$access_modes" = ReadWriteOnce ] ||
    fail "PVC accessModes are $access_modes, expected ReadWriteOnce"

  volume_json="$(kubectl --context "$KUBE_CONTEXT" get persistentvolume "$volume_name" -o json)"
  reclaim_policy="$(printf '%s' "$volume_json" | jq -r '.spec.persistentVolumeReclaimPolicy')"
  nas_server="$(printf '%s' "$volume_json" | jq -r '.spec.nfs.server // ""')"
  nas_path="$(printf '%s' "$volume_json" | jq -r '.spec.nfs.path // ""')"
  [ "$reclaim_policy" = Retain ] || fail "PV reclaim policy is $reclaim_policy, expected Retain"
  [ "$nas_path" = "$EXPECTED_NAS_PATH" ] ||
    fail "PV NFS path is $nas_path, expected $EXPECTED_NAS_PATH"
  [ -n "$nas_server" ] || fail "PV $volume_name is not backed by an NFS server"

  note "PVC: $KUBE_NAMESPACE/$DATA_CLAIM ($requested_size, $access_modes, $storage_class, PV $volume_name)"
  note "NAS: $nas_server:$nas_path (reclaim policy $reclaim_policy)"
}

preflight() {
  require_command kubectl
  require_command jq

  current_context="$(kubectl config current-context)"
  [ "$current_context" = "$KUBE_CONTEXT" ] ||
    fail "current kubectl context is $current_context, expected $KUBE_CONTEXT"

  deployment_json="$(kube get deployment "$LEGACY_DEPLOYMENT" -o json)" ||
    fail "legacy Deployment $KUBE_NAMESPACE/$LEGACY_DEPLOYMENT is missing"
  desired_replicas="$(printf '%s' "$deployment_json" | jq -r '.spec.replicas // 0')"
  ready_replicas="$(printf '%s' "$deployment_json" | jq -r '.status.readyReplicas // 0')"
  image="$(printf '%s' "$deployment_json" | jq -r '.spec.template.spec.containers[] | select(.name == "minio") | .image')"
  [ "$desired_replicas" = 1 ] || fail "legacy MinIO wants $desired_replicas replicas, expected 1"
  [ "$ready_replicas" = 1 ] || fail "legacy MinIO has $ready_replicas ready replicas, expected 1"
  [ -n "$image" ] || fail "could not identify the legacy MinIO image"

  claim_checks

  mount_json="$(printf '%s' "$deployment_json" | jq -c --arg claim "$DATA_CLAIM" '
    .spec.template.spec as $pod
    | ($pod.volumes[] | select(.persistentVolumeClaim.claimName == $claim) | .name) as $volume
    | $pod.containers[]
    | select(.name == "minio")
    | .volumeMounts[]
    | select(.name == $volume)
  ')"
  mount_path="$(printf '%s' "$mount_json" | jq -r '.mountPath')"
  sub_path="$(printf '%s' "$mount_json" | jq -r '.subPath // ""')"
  [ "$mount_path" = /bitnami/minio/data ] ||
    fail "legacy data mount is $mount_path, expected /bitnami/minio/data"
  [ -z "$sub_path" ] || fail "legacy data mount unexpectedly uses subPath=$sub_path"

  process_uid="$(kube exec deployment/"$LEGACY_DEPLOYMENT" -- id -u)"
  [ "$process_uid" = 1001 ] || fail "legacy MinIO runs as UID $process_uid, expected 1001"
  kube exec deployment/"$LEGACY_DEPLOYMENT" -- sh -ceu '
    test -d /bitnami/minio/data/.minio.sys
    test ! -e /bitnami/minio/data/.rustfs.sys
  ' || fail "volume markers do not describe an untouched MinIO volume"

  note "Legacy deployment: $KUBE_NAMESPACE/$LEGACY_DEPLOYMENT (ready, image $image, UID $process_uid)"
  note "Data layout: PVC root is mounted directly at /bitnami/minio/data"
  note "Buckets visible at the PVC root:"
  kube exec deployment/"$LEGACY_DEPLOYMENT" -- sh -ceu '
    find /bitnami/minio/data -mindepth 1 -maxdepth 1 -type d ! -name ".*" -print |
      sed "s#^/bitnami/minio/data/##" |
      sort
  '
  note ""
  note "PREFLIGHT PASSED. This does not prove that objects are free of SSE/KMS encryption or transition tiers."
  note "Before syncing the chart: freeze all S3 writers, stop MinIO, and snapshot the NAS path for this PVC."
}

verify() {
  require_command kubectl
  require_command jq

  current_context="$(kubectl config current-context)"
  [ "$current_context" = "$KUBE_CONTEXT" ] ||
    fail "current kubectl context is $current_context, expected $KUBE_CONTEXT"

  claim_checks

  if kube get deployment "$LEGACY_DEPLOYMENT" >/dev/null 2>&1; then
    legacy_replicas="$(kube get deployment "$LEGACY_DEPLOYMENT" -o jsonpath='{.status.replicas}')"
    [ "${legacy_replicas:-0}" = 0 ] || fail "legacy MinIO still has ${legacy_replicas:-0} replicas"
  fi

  deployment_json="$(kube get deployment "$RUSTFS_DEPLOYMENT" -o json)" ||
    fail "RustFS Deployment $KUBE_NAMESPACE/$RUSTFS_DEPLOYMENT is missing"
  desired_replicas="$(printf '%s' "$deployment_json" | jq -r '.spec.replicas // 0')"
  ready_replicas="$(printf '%s' "$deployment_json" | jq -r '.status.readyReplicas // 0')"
  image="$(printf '%s' "$deployment_json" | jq -r '.spec.template.spec.containers[] | select(.name == "rustfs") | .image')"
  [ "$desired_replicas" = 1 ] || fail "RustFS wants $desired_replicas replicas, expected 1"
  [ "$ready_replicas" = 1 ] || fail "RustFS has $ready_replicas ready replicas, expected 1"
  [ -n "$image" ] || fail "could not identify the RustFS image"

  mount_json="$(printf '%s' "$deployment_json" | jq -c --arg claim "$DATA_CLAIM" '
    .spec.template.spec as $pod
    | ($pod.volumes[] | select(.persistentVolumeClaim.claimName == $claim) | .name) as $volume
    | $pod.containers[]
    | select(.name == "rustfs")
    | .volumeMounts[]
    | select(.name == $volume)
  ')"
  mount_path="$(printf '%s' "$mount_json" | jq -r '.mountPath')"
  sub_path="$(printf '%s' "$mount_json" | jq -r '.subPath // ""')"
  [ "$mount_path" = /data ] || fail "RustFS data mount is $mount_path, expected /data"
  [ -z "$sub_path" ] || fail "RustFS data mount unexpectedly uses subPath=$sub_path"

  kube exec deployment/"$RUSTFS_DEPLOYMENT" -- sh -ceu '
    test -d /data/.rustfs.sys
    test -d /data/.minio.sys
  ' || fail "expected RustFS and imported MinIO metadata markers are not both present"

  kube get --raw "/api/v1/namespaces/$KUBE_NAMESPACE/services/http:rustfs-svc:9000/proxy/health/ready" >/dev/null ||
    fail "RustFS readiness endpoint is unavailable through the Kubernetes service proxy"

  provisioned="$(kube get job s3-rustfs-provisioning -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
  [ "${provisioned:-0}" -ge 1 ] || fail "RustFS provisioning Job has not succeeded"

  note "RustFS deployment: $KUBE_NAMESPACE/$RUSTFS_DEPLOYMENT (ready, image $image)"
  note "Data layout: the original PVC root is mounted directly at /data"
  note "Provisioning: s3-rustfs-provisioning succeeded"
  note "VERIFY PASSED. Exercise every application and compare critical bucket/object/version counts before ending maintenance."
}

usage() {
  cat <<'EOF'
Usage: minio-rustfs-migration.sh preflight|verify

Read-only checks for the home-cluster MinIO-to-RustFS cutover.
Override KUBE_CONTEXT or KUBE_NAMESPACE only when deliberately targeting a
different cluster or namespace.
EOF
}

case "${1:-}" in
  preflight) preflight ;;
  verify) verify ;;
  *) usage >&2; exit 2 ;;
esac
