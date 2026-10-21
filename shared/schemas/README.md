# shared/schemas

This folder will hold `contracts.schema.json`, the JSON Schema of every API contract, exported from the pydantic models in `apps/api/app/models.py` by `make types`. The TypeScript types in `apps/web/lib/types.ts` are generated from it. The file is generated: never edit it by hand.
Phase 1 builds it, and CI fails if it is out of date.
