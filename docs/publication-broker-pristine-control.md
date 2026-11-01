# Additive pristine-control transport compatibility

Apply this narrow correction **after** the accepted corrected transport
`86ed78ec423df05d26d5423e5e55db7b0e8da4a42632eedb2f9135b5b52eb638`.
It does not replace that patch, change its seal or modify composition.

The separately sealed SQL/Blob composition represents a pristine SQL target as
`AttemptControl(session=None, active=None, revision="0")`. Authenticated
`read-control` now returns exactly that shape rather than refusing it. No
session is fabricated and no acquisition is performed.

Only read-control may expose a missing session, and only with that exact
pristine shape. Acquisition and present commit/recovery outcomes still require
an actual session owned by the independently verified worker. A null result is
permitted only for an absent recovery outcome, never for commit or acquire.

Tests use the signed authentication fixture and separately couple the real
SQL/Blob composition through injected offline transports. These checks do not
qualify SQL engine permissions, provider policy or deployed HTTP behavior.
No routes, flags, credentials, grants, provisioning or deployment are added.
