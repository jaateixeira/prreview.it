# 0012. Valkey cache, loguru logging, rich console

Status: accepted

## Context
Every request with a session cookie reads its user from the database, so entering the system and every page after it pays for that read. Operators also need debuggable logs and a readable start-up.

## Decision
- **Cache port** (`Cache`: get, set with TTL, delete) in the application layer. Adapters: `ValkeyCache` (any Redis-protocol server, short socket timeouts, every error logged and treated as a miss) and `MemoryCache` (bounded, per process) as the default when no URL is configured.
- **What is cached:** the user record by id, 60 s, through `CachedUserRepository`, which drops the entry after every write (email verified, identity linked, password changed). Password hashes and tokens never enter the cache. Tenancy permissions are not cached: they gate writes and must be exact.
- **Not a dependency:** Valkey is optional, installed with the `valkey` extra, and the default in-process cache keeps development to `make install` and SQLite. This keeps ADR 0005: no extra mandatory service for self-hosters, and the hosted service runs the same code.
- **Multi-worker caveat:** separate in-process caches can serve a user up to 60 s stale after another worker changed it. The server warns when `WEB_CONCURRENCY` > 1 without a cache URL.
- **loguru** replaces standard-library logging calls; `configure_logging(level)` sets the level (`[logging] level`, `PREVIEWIT_LOG_LEVEL`: TRACE to ERROR) and routes uvicorn, SQLAlchemy and other libraries through loguru. TRACE logs every cache hit and miss.
- **rich** draws the start-up summary on stdout. It lists on/off facts and credential-free values only (tested).

## Consequences
One more optional service in hosted production. A cache outage costs latency, not availability. Later hot reads (space permissions with explicit invalidation, rate limits) can use the same port.
