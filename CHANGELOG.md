# Changelog

All notable project versions are recorded in this file.

## [v0.2] - 2026-04-15

### Added
- Automated test suite with 20 tests using Django `APITestCase`/`TestCase`.
- Coverage for auth, food endpoints, meal log CRUD, analytics endpoints, and model nutrient calculation.

### Why this release matters
- Improves reliability and provides regression safety before advanced API enhancements.

## [v0.1] - 2026-04-14

### Added
- Initial MacroTracker API using Django + DRF.
- JWT authentication endpoints.
- Food catalog endpoint.
- Meal log CRUD endpoints with per-user isolation.
- Daily summary, trends, and advanced analytics endpoints.
