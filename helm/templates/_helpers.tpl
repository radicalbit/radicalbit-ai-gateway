{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "gateway.name" -}}
  {{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "common.fullname" -}}
  {{- if .Values.fullnameOverride -}}
    {{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
  {{- else -}}
    {{- $name := default .Chart.Name .Values.nameOverride -}}
    {{- if contains $name .Release.Name -}}
      {{- .Release.Name | trunc 63 | trimSuffix "-" -}}
    {{- else -}}
      {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
    {{- end -}}
  {{- end -}}
{{- end -}}

{{/*
Create a default fully qualified app name for gateway.
*/}}
{{- define "gateway.fullname" -}}
{{- $fullname := include "common.fullname" . -}}
{{- printf "%s-%s" $fullname "gw" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name for gateway.
*/}}
{{- define "worker.fullname" -}}
{{- $fullname := include "common.fullname" . -}}
{{- printf "%s-%s" $fullname "wk" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "common.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}


{{/*
Common labels
*/}}
{{- define "common.labels" -}}
helm.sh/chart: {{ include "common.chart" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.commonLabels }}
{{ toYaml .Values.commonLabels }}
{{- end }}
{{- end }}

{{/*
Gateway labels
*/}}
{{- define "gateway.labels" -}}
{{ include "common.labels" . }}
{{ include "gateway.selectorLabels" . }}
{{- end }}

{{/*
Worker labels
*/}}
{{- define "worker.labels" -}}
{{ include "common.labels" . }}
{{ include "worker.selectorLabels" . }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "common.selectorLabels" -}}
app.kubernetes.io/name: {{ include "gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Gateway selector labels
*/}}
{{- define "gateway.selectorLabels" -}}
{{ include "common.selectorLabels" . }}
app.kubernetes.io/part-of: gateway
app.kubernetes.io/component: gateway
{{- end }}

{{/*
Worker selector labels
*/}}
{{- define "worker.selectorLabels" -}}
{{ include "common.selectorLabels" . }}
app.kubernetes.io/part-of: gateway
app.kubernetes.io/component: worker
{{- end }}