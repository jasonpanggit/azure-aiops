# Deferred Items

- **Pre-existing frontend compliance test failure:** `web/src/app/compliance/page.test.tsx` mocks `@/lib/services` without the `complianceApi` export now consumed by `web/src/app/compliance/page.tsx`. The isolated test and full frontend suite both fail before assertions with Vitest's missing-export error. This is unrelated to 03-06 remediation files and was not modified.
