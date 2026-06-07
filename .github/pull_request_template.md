## Package

<!-- Which package does this PR affect? -->

## Summary

<!-- What does this PR do and why? -->

## Checklist

- [ ] Tests added/updated and passing (`make ci`)
- [ ] Package README updated (if public API changed)
- [ ] `CHANGELOG.md` updated under `[Unreleased]` for user-visible changes
- [ ] No new dependencies without justification
- [ ] Self-contained tests (no running LatchGate needed)

## Security checklist

If this PR touches `common/` (serialization, discovery, schema, transport) or any code controlling what the model sees:

- [ ] Output-only serialization preserved (receipt/trace/verification never in model output)
- [ ] Description redaction preserved (enforcement topology omitted in default mode)
- [ ] Negative tests added (sensitive data excluded, invalid input rejected)
- [ ] No secrets, receipt IDs, or enforcement metadata in error messages returned to the model

<!-- Delete this section if the PR doesn't touch security-relevant code. -->
