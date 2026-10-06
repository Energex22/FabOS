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

## Customer CAD AI

FabOS also uses the configured AI provider for constrained customer CAD assistance:

- Text requests are converted into a validated parametric CAD specification.
- Reference images can be analyzed for geometry and labeled dimensions.
- Image-derived CAD is deliberately blocked until a trustworthy scale is confirmed and required measurements/critical ambiguities are resolved.
- CadQuery creates the actual geometry; the AI never executes generated Python or CAD code.
- Generated geometry is dimensionally verified before STL/STEP/3MF artifacts are returned.
- Customers can revise a generated model with a new instruction; revisions retain parent-job lineage.
- Printer preflight checks the generated bounding box against the selected printer build volume.
- Completed CAD can be attached directly to a customer quote and carried into Design Vault/production.

### Vision-model requirement

Image analysis requires a multimodal/vision-capable model.

For OpenAI-compatible providers, configure a vision-capable model at `ai_model`.

For Ollama, configure a vision-capable model and set `ai_endpoint` to the Ollama server. FabOS sends reference-image bytes using Ollama's native `images` message field. A normal text-only Ollama model will not be able to analyze reference photos.

### Dimensional safety

A photo by itself is not treated as a measurement. FabOS requires either a labeled drawing dimension, an explicitly supplied physical measurement, or another recognized physical scale reference before reference-derived geometry can be generated. This prevents perspective or pixel measurements from silently becoming manufacturing dimensions.