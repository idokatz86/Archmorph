{{/*
Expand the name of the chart.
*/}}
{{- define "archmorph.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Reviewed schema transition contract shared by preflight and migration hooks. */}}
{{- define "archmorph.migrationAcceptedRevisions" -}}
{{- $accepted := .Values.migrations.acceptedCurrentAlembicRevisions -}}
{{- $head := required "migrations.expectedAlembicHead is required" .Values.migrations.expectedAlembicHead -}}
{{- if not $accepted -}}
{{- fail "migrations.acceptedCurrentAlembicRevisions must contain reviewed revisions" -}}
{{- end -}}
{{- $seen := dict -}}
{{- range $revision := $accepted -}}
{{- if not (regexMatch "^[A-Za-z0-9_-]+$" $revision) -}}
{{- fail "migrations.acceptedCurrentAlembicRevisions contains an invalid revision" -}}
{{- end -}}
{{- if hasKey $seen $revision -}}
{{- fail "migrations.acceptedCurrentAlembicRevisions must be unique" -}}
{{- end -}}
{{- $_ := set $seen $revision true -}}
{{- end -}}
{{- if not (hasKey $seen $head) -}}
{{- fail "migrations.acceptedCurrentAlembicRevisions must include expectedAlembicHead" -}}
{{- end -}}
{{- range $revision := $accepted }}
- "--accept-current"
- {{ $revision | quote }}
{{- end -}}
{{- end }}

{{/* Unique CI/GitOps identity for separately applied preflight and migration Jobs. */}}
{{- define "archmorph.migrationExecutionId" -}}
{{- $executionId := required "migrations.executionId is required for migration phases" .Values.migrations.executionId -}}
{{- if not (regexMatch "^[a-z0-9][a-z0-9-]{0,39}$" $executionId) -}}
{{- fail "migrations.executionId must be a lowercase DNS-safe identity of at most 40 characters" -}}
{{- end -}}
{{- $executionId -}}
{{- end }}

{{/* Immutable image shared by the application and migration hook. */}}
{{- define "archmorph.image" -}}
{{- $environment := lower .Values.env.ENVIRONMENT -}}
{{- if or (eq $environment "prod") (eq $environment "production") (eq $environment "staging") -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" .Values.image.digest) -}}
{{- fail "image.digest must be an immutable sha256 digest in production/staging" -}}
{{- end -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else if .Values.image.digest -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" .Values.image.digest) -}}
{{- fail "image.digest must be an immutable sha256 digest" -}}
{{- end -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) -}}
{{- end -}}
{{- end }}

{{/* Secret containing runtime credentials. */}}
{{- define "archmorph.secretName" -}}
{{- if .Values.externalSecrets.enabled -}}
{{- printf "%s-secrets" (include "archmorph.fullname" .) -}}
{{- else if .Values.existingSecret.name -}}
{{- .Values.existingSecret.name -}}
{{- else -}}
{{- fail "configure externalSecrets.enabled=true or existingSecret.name" -}}
{{- end -}}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "archmorph.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "archmorph.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "archmorph.labels" -}}
helm.sh/chart: {{ include "archmorph.chart" . }}
{{ include "archmorph.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "archmorph.selectorLabels" -}}
app.kubernetes.io/name: {{ include "archmorph.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "archmorph.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "archmorph.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
