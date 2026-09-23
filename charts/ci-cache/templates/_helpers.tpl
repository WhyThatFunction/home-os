{{/*
Shared provisioning internals for the RustFS bucket/lifecycle bootstrap.

Both the Sync-phase hook Job (provisioning/job.yaml, guarantees ordering on
a first install) and the CronJob (provisioning/cronjob.yaml, the continuous
reconciler that heals a bucket lost between syncs — e.g. a replaced RustFS
PVC, which changes no manifest and so triggers no ArgoCD sync) run the
exact same idempotent script against the exact same pod shape. Two runners
of one script is fine; two copies of the script is the DRY violation this
repo's own rule calls out ("a rule that exists twice is a rule that will
disagree with itself") — so it is defined once here and included from both.
*/}}

{{/*
The provisioning script body. Takes the root context (pass `$`), because it
is included from inside a `{{- with .Values.provisioning }}` block in one
caller and from a plain pod-template context in the other — reading
`.Values.provisioning` directly here means neither caller has to adjust its
scope to use it.
*/}}
{{- define "ci-cache.provisioning.script" -}}
endpoint={{ .Values.provisioning.endpoint | quote }}
access_key="$(cat /credentials/access-key)"
secret_key="$(cat /credentials/secret-key)"

attempt=0
until rc --quiet alias set rustfs "$endpoint" "$access_key" "$secret_key" --bucket-lookup path && rc --quiet ready rustfs; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo "RustFS did not become ready within 300 seconds" >&2
    exit 1
  fi
  sleep 5
done

# No users and no policies to provision here — this instance's root
# credential doubles as the only identity every consumer uses (see the
# rootSecret comment in values.yaml for why).
{{- range .Values.provisioning.buckets }}
rc --quiet bucket create --ignore-existing rustfs/{{ .name }}
{{- if .expiryDays }}
rc --quiet bucket lifecycle rule import rustfs/{{ .name }} /config/lifecycle-{{ .name }}.json
{{- end }}
{{- end }}
{{- end -}}

{{/*
The full Pod template (metadata + spec) both the Job and the CronJob's
jobTemplate render verbatim. Takes the root context (pass `$`) for the same
reason as the script above. Callers `include` this right after their own
`template:` key and `nindent` it to whatever depth that key sits at.
*/}}
{{- define "ci-cache.provisioning.podTemplate" -}}
metadata:
  labels:
    app.kubernetes.io/name: rustfs-provisioning
    app.kubernetes.io/instance: {{ .Release.Name | quote }}
spec:
  automountServiceAccountToken: false
  enableServiceLinks: false
  restartPolicy: OnFailure
  securityContext:
    runAsNonRoot: true
    runAsUser: 100
    runAsGroup: 101
    fsGroup: 101
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: provision
      image: {{ printf "%s:%s" .Values.provisioning.image.repository .Values.provisioning.image.tag | quote }}
      imagePullPolicy: {{ .Values.provisioning.image.pullPolicy }}
      command: ["/bin/sh", "-ceu"]
      args:
        - |
          {{- include "ci-cache.provisioning.script" . | nindent 10 }}
      env:
        - name: HOME
          value: /work
      resources:
        requests:
          cpu: 10m
          memory: 32Mi
        limits:
          cpu: 500m
          memory: 256Mi
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
        readOnlyRootFilesystem: true
      volumeMounts:
        - name: work
          mountPath: /work
        - name: config
          mountPath: /config
          readOnly: true
        - name: root-credentials
          mountPath: /credentials
          readOnly: true
  volumes:
    - name: work
      emptyDir: {}
    - name: config
      configMap:
        name: ci-cache-provisioning
    - name: root-credentials
      secret:
        secretName: {{ .Values.rootSecret.name | quote }}
        items:
          - key: root-user
            path: access-key
          - key: root-password
            path: secret-key
{{- end -}}
