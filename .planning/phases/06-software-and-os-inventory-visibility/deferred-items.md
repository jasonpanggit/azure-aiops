# Deferred Items

## Existing full-suite frontend failure

- `cd web && npm test` has one unrelated pre-existing failure in
  `src/app/compliance/page.test.tsx`: the compliance page does not render the
  expected firewall-bypass Copilot link under its current working-tree
  changes.
- This plan did not modify the compliance page or its test. The focused
  Software Inventory suite, backend suite, lint, and production build pass.
