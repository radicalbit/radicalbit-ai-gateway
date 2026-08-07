# Radicalbit AI Gateway

A self-hosted, OpenAI-compatible gateway for routing, securing, and observing all your LLM traffic.

## What is it?

Radicalbit AI Gateway is a centralized proxy that sits between your applications and LLM providers (OpenAI, Anthropic, Google Gemini, Azure OpenAI, and more). It gives you a single, consistent entry point with built-in routing, caching, rate limiting, guardrails, and observability — without changing your existing OpenAI SDK calls.

## Features

### Governance & Security
- **Guardrails** — block or warn on harmful content using rule-based filters (regex, PII detection via Presidio) or LLM-as-a-Judge semantic evaluation
- **Rate limiting** — cap requests per time window at the route level
- **Token limiting** — cap input and output token consumption independently per time window
- **Budget limiting** — enforce cost-based spending limits per time window
- **Fallback** — automatic failover across models when a provider fails

### Cost Control
- **Exact caching** — cache identical requests to cut latency and cost
- **Semantic caching** — cache semantically similar requests using embedding similarity
- **Intelligent routing** — route requests dynamically based on keywords, token/context length, time of day, budget consumption, ML classifiers, or semantic intent

### Observability
- **Prometheus metrics** — 20+ metrics (request rates, latency, token usage, cache hits, guardrail triggers, fallback activations) on a dedicated endpoint
- **OpenTelemetry tracing** — end-to-end distributed tracing with ClickHouse storage and support for custom OTLP exporters (Jaeger, Grafana Tempo, etc.)
- **Alert Rules** — real-time email notifications triggered by guardrails, caching, and route events
- **UI dashboard** — manage routes, groups, API keys, alert rules, and monitor cost and events in real time

### Multi-provider support
Native: OpenAI, Anthropic, Google Gemini, Azure OpenAI, DeepSeek, Mistral
OpenAI-compatible: Ollama, vLLM, OpenRouter, any on-premises endpoint

## Quickstart

**Prerequisites:** Docker and Docker Compose.

1. Clone the repository:
   ```bash
   git clone https://github.com/radicalbit/radicalbit-ai-gateway.git
   cd radicalbit-ai-gateway
   ```

2. Add your LLM provider API key to `secrets.yaml`:
   ```yaml
   OPENAI_API_KEY: sk-your-key-here
   ```

3. Start the stack:
   ```bash
   docker compose up -d
   ```

4. The gateway is running at `http://localhost:9000`.

For the full quickstart guide, configuration reference, and provider setup, see the **[documentation](https://docs.ai-gateway.radicalbit.ai/)**.

## Enterprise

The open-source gateway is production-ready for most teams. For organizations that need more control:

- **RBAC** — role-based access control (Admin, Builder, Auditor roles) with project-level isolation
- **SSO / IDP integration** — Keycloak and OIDC-compatible identity providers; automatic user and group sync
- **JWT authentication** — authenticate gateway API calls with IDP-issued JWT tokens instead of managing gateway API keys
- **Enterprise secrets backends** — store LLM provider credentials in AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager, or Azure Key Vault

[Contact us](https://radicalbit.ai) to learn more about the enterprise edition.
