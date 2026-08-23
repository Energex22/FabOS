# Architecture
Desktop client -> application services -> event/automation layer -> SQLite -> plugins/integrations.

Original design files are immutable and versioned by hash. Commands are transactional. Events are durable. Automation handlers must be idempotent. External integrations require retry and reconciliation. The Windows 7 edition stays on a trusted LAN and is never exposed directly to the internet.
