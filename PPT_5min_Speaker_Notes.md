# 5-Minute Speaker Notes (MacroTracker API)

## Slide 1 (30s)
- Introduce project: MacroTracker API for nutrition logging.
- State goal: practical user flow, reliable backend behavior, and defendable final scope.

## Slide 2 (40s)
- Explain user journey: register/login -> choose food -> log by weight -> see feedback.
- Mention final scope is intentionally focused, not feature-heavy.

## Slide 3 (50s)
- Stack choice: DRF + JWT + SQLite + schema tooling.
- Explain core models and why server-side nutrient calculation is critical for data integrity.

## Slide 4 (55s)
- Emphasize this is more than CRUD: throttling, caching, invalidation, idempotency, request ID, unified errors.
- Say these features improve reliability and traceability.

## Slide 5 (50s)
- Discuss scope refinement decisions and rationale:
  - removed duplicate search endpoint,
  - removed PATCH,
  - removed profile targets route,
  - standardized input to grams only.
- Key point: coherence over endpoint count.

## Slide 6 (45s)
- Show evidence quality: 33 tests passing.
- Mention commit timeline proves iterative development and controlled refactoring.

## Slide 7 (30s)
- GenAI declaration: used for planning/analysis, not blind code generation.
- Close with final value: smaller API, cleaner contract, stronger maintainability.
