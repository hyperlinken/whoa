# CodePilot V14 — Refactored Architecture

## Principles

- Composition root owns dependency wiring.
- Domain state is represented by typed dataclasses/enums.
- Use cases contain application workflows.
- Adapters isolate the existing Gemini and Windows implementations.
- Concurrency is centralized in `TaskRunner` and `GenerationGate`.
- The original low-level implementation is retained under `codepilot.legacy` to minimize behavioral drift.

## Runtime flow

```text
Hotkey / UI
    |
    v
Application
    |
    +--> SessionService
    +--> CaptureScreenshot
    +--> AnalyzeAndSolve ----> GeminiService ----> legacy Gemini client
    +--> AnalyzeResult ------> GeminiService
    +--> InputService -------> legacy Windows implementation
```

## Compatibility strategy

The refactor does not duplicate the mature low-level implementations. Instead, adapters translate between typed application models and the existing APIs. This reduces regression risk and permits incremental replacement of individual components.

## Safety boundary

Platform-specific mechanisms designed to circumvent application or assessment protections are not expanded or improved by this refactor. The architecture exposes them only behind the existing low-level boundary.
