{{/*
The predictor part of an InferenceService, shared by the stable model and
the canary. Takes root, tag and nodeEnvironment.
*/}}
{{- define "model.predictor" }}
  predictor:
    minReplicas: 1
    maxReplicas: 1
    # One GPU per node: the old pod must release it before the new one can
    # start, so a rolling update would hang in Pending.
    deploymentStrategy:
      type: Recreate
    nodeSelector:
      environment: {{ .nodeEnvironment }}
    containers:
      - name: kserve-container
        image: "{{ .root.Values.model.image.repository }}:{{ .tag }}"
        ports:
          - name: http
            containerPort: {{ .root.Values.model.port }}
            protocol: TCP
        env:
          - name: WEIGHTS_BUCKET
            value: {{ .root.Values.model.weightsBucket }}
          # Secrets are created outside the chart so values never touch git.
          - name: HF_TOKEN
            valueFrom:
              secretKeyRef:
                name: hf-token
                key: HF_TOKEN
          - name: API_KEY
            valueFrom:
              secretKeyRef:
                name: api-key
                key: API_KEY
        resources:
          requests:
            cpu: {{ .root.Values.model.cpuRequest }}
            memory: {{ .root.Values.model.memoryRequest }}
            nvidia.com/gpu: 1
          limits:
            cpu: {{ .root.Values.model.cpuLimit | quote }}
            memory: {{ .root.Values.model.memoryLimit }}
            nvidia.com/gpu: 1
        # A cold start downloads ~6GB of weights and compiles kernels,
        # so allow up to 20 minutes (80 x 15s) before restarting.
        startupProbe:
          httpGet:
            path: /health
            port: {{ .root.Values.model.port }}
          periodSeconds: 15
          failureThreshold: 80
        livenessProbe:
          httpGet:
            path: /health
            port: {{ .root.Values.model.port }}
          periodSeconds: 20
        readinessProbe:
          httpGet:
            path: /health
            port: {{ .root.Values.model.port }}
          periodSeconds: 10
{{- end }}
