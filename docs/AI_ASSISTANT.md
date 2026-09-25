# FabOS AI Assistant

FabOS includes an optional provider-neutral AI assistant.

## Providers

- `disabled` — default; no network access.
- `openai_compatible` — works with an OpenAI-compatible chat-completions endpoint.
- `ollama` — works with a local Ollama server.

No AI SDK is required; the integration uses Python's standard HTTP library.

## Owner setup

Configure in FabOS Settings:

- `ai_provider`
- `ai_model`
- `ai_endpoint`
- `ai_api_key_env`
- `ai_allow_customer_data`
- `ai_require_action_approval`

For hosted providers, put the API key in an environment variable named by `ai_api_key_env`. Do not place the actual key in SQLite, Git, or a settings export.

For Ollama, point `ai_endpoint` at the local server, normally `http://127.0.0.1:11434`.

## Current capabilities

- General FabOS business/operations chat.
- Product-aware marketing assistance.
- Platform-specific marketing package drafts.
- Product context can be passed to the AI without exposing the full database.

## Safety boundary

The assistant is advisory by default. It does not publish marketing posts, change prices, issue refunds, place orders, delete records, or perform other consequential business actions merely because the AI suggested them.

The existing marketing approval workflow remains the gate for external publishing.

## Next AI layer

The next major step is tool calling with explicit permissions. That would let the AI request actions such as:
- find low-stock filament;
- summarize today's production queue;
- draft a product listing;
- prepare a quote;
- identify failed prints;
- prepare a marketing campaign.

Each action should be represented as a typed FabOS operation with validation, audit logging, and owner approval for consequential actions.

## Safe tool mode

The assistant now exposes a bounded read-only tool layer for product search/details, operational snapshots, recent order summaries, and marketing summaries. Tool calls are limited to three rounds per request and are recorded in the AI audit tables when the database has migration 49 applied.

AI still cannot publish posts, change prices, issue refunds, send customer messages, create production jobs, delete records, or spend money. Those actions require dedicated FabOS workflows and explicit owner approval; the AI approval setting remains enabled by default.

Conversations receive a local ID so the desktop/API clients can maintain continuity. Customer information is excluded from AI context by default via ai_allow_customer_data=false.
