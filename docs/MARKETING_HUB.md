# FabOS Marketing & Sales Hub

FabOS now includes a provider-neutral marketing workspace foundation.

## What it manages
- Products as the source of truth for marketing posts.
- Campaigns with dates and budgets.
- Channel connections for the FABVEX website, Etsy, eBay, Facebook, Instagram, TikTok, Pinterest, email, and future channels.
- Draft, approval, scheduling, publishing, and failure states.
- Per-channel post status and external IDs.
- External marketplace sales ingestion and normalized sales reporting.
- Owner-configurable marketing behavior through the existing Settings API.

## Owner setup
The owner/admin can configure:
- marketing_enabled
- marketing_require_approval
- marketing_default_publish_mode (manual, webhook, or api)
- marketing_timezone

Channel records are configured under the Marketing section of the admin API. Each channel has an account label, profile URL, publish mode, optional webhook URL, and a credential_ref.

Security rule: credential_ref is intentionally a reference/name, not a secret value. API keys, OAuth refresh tokens, and other secrets should be stored in the deployment environment/secret store and referenced by name. Do not commit credentials to Git.

## Publishing model
The implementation separates the business data model from provider-specific APIs so platform integrations can be added without coupling the product database to Etsy/eBay/Meta/TikTok implementation details.

Normal flow:
1. Create or select a product.
2. Create a campaign.
3. Draft a post and select channels.
4. Review the content.
5. Approve the post.
6. FabOS schedules it and tracks each channel independently.
7. A provider adapter publishes it and records the external ID/result.
8. Provider adapters can import marketplace orders into marketing_external_orders.

External publishing remains approval-gated by default.

## Current limitation
The normalized channel and sales interfaces are in place, but provider-specific OAuth/API adapters are intentionally isolated from the core so credentials and platform API changes cannot destabilize FabOS. Manual mode is usable immediately; webhook/api modes are integration seams for provider connectors.