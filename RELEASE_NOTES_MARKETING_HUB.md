# Marketing Hub Foundation

## Added
- Provider-neutral marketing channels for FABVEX website, Etsy, eBay, Facebook, Instagram, TikTok, Pinterest, email, and future channels.
- Campaigns, product-linked posts, media metadata, scheduling, approval, per-channel publication state, and external IDs.
- Product-aware platform copy variants.
- External marketplace sales ingestion and normalized channel sales summaries.
- Owner-configurable marketing settings and credential references.
- Seeded channel records with external channels disabled until configured.
- Administrator API endpoints for marketing, campaigns, posts, channels, approval, sales, and copy variants.
- Regression tests for channel/campaign/post lifecycle and sales aggregation.

## Safety defaults
- Marketing is enabled but external publishing requires approval by default.
- External channels are disabled until the owner configures them.
- Secrets are not stored in Git or the normal settings values; settings use credential references.
