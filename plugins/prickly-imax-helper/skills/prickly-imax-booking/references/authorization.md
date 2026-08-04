# Authorization Gate

Distribution builds may enable automatic submission only when the operator has documented authorization covering automated availability queries, seat selection, payment submission, distribution to end users, and applicable rate limits.

Store only an authorization identifier and allowed capability flags in the repository. Do not store confidential correspondence or API credentials.

For the current private beta, record the approval date, scope, the maximum rate of one automated availability request per IP per second, and the SHA-256 fingerprint of the privately retained authorization source. The fingerprint proves which retained document was used; it does not independently prove the issuer's identity.

Every installation must still require the end user to use their own CGV account and payment method, accept the configured booking constraints, set quantity and payment limits, and understand that one successful or uncertain submission stops the monitor.
