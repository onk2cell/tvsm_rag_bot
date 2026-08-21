# Client seeds

One JSON file per client, holding the configuration a brand-new stack starts
from. A deployment picks one with an environment variable:

```bash
ADMIN_CONFIG_SEED=seeds/tvs.json
```

`AdminConfigStore.ensure_seeded()` uses it **only when the stack has no config
file yet**. Once `data/admin_config.json` exists, the seed is never consulted
again — an existing deployment cannot be reconfigured by changing this, and the
admin panel remains the way to edit a running bot.

## Why these are files rather than code

`admin_config.default_config()` used to return the TVS configuration, so a
stack deployed for any other client *was* a TVS bot until somebody edited it:
TVS name, TVS welcome text, TVS products, TVS campaign — and TVS brochure PDFs
sent to that client's customers. The default is neutral now, and each client's
real values live here, so standing one up is a deployment setting rather than a
code change.

## Adding a client

1. Copy an existing seed and edit it — name, welcome, intro per language,
   capture fields, flow steps, campaign, documents.
2. Deploy a stack with `ADMIN_CONFIG_SEED` pointing at it, its own `data/`
   directory, and its own host ports.
3. `validate_config()` runs on the seed at first boot. A seed that is named but
   unreadable or invalid raises rather than quietly falling back — a deployment
   that says which client it is should fail loudly if it cannot be that client.

## Files

| File | Client |
| --- | --- |
| `tvs.json` | TVS passenger three-wheelers — the values `default_config()` used to return |
