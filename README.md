# CodePilot V14

CodePilot V14 is now organized as a layered Python application while retaining the established V14 runtime as the compatibility implementation.

## Structure

```text
.
├── main.py                         # stable entry point
├── pyproject.toml                  # package/build/test metadata
├── src/codepilot/
│   ├── application/               # composition + use cases
│   ├── domain/                    # state and business models
│   ├── infrastructure/            # configuration/concurrency primitives
│   ├── adapters/                  # boundaries to existing implementations
│   └── legacy/                    # original V14 low-level runtime
├── agent/                          # backward-compatible import wrappers
├── tests/unit/                     # deterministic unit tests
└── scripts/config files            # existing setup/deployment assets
```

## Design goals

1. Preserve the existing V14 hotkey workflow during migration.
2. Keep mutable session state in one typed object.
3. Isolate concurrency and generation invalidation.
4. Put Windows/AI implementations behind adapter boundaries.
5. Make core behavior testable without Windows or network access.
6. Allow one subsystem at a time to migrate from `legacy/` to production services.

## Running

The existing launch command remains supported:

```powershell
python main.py
```

The package entry point is also available:

```powershell
python -m codepilot
```

## Tests

```powershell
python -m pytest -q
```

The compatibility architecture intentionally keeps the proven V14 runtime authoritative while the new layers are introduced. This avoids a risky all-at-once rewrite and makes regressions localized.
