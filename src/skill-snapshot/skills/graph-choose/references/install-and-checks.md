# Install and checks

This testing-only snapshot bundles Foundry IQ, EKG, grounding, GRZ and ontology
in one local plugin. Use the [snapshot runtime instructions](../../../README.md#install-the-local-runtimes),
not marketplace installation, to keep the pinned source revision.

Run only the checks required by the route: `ekg-provision --version`,
`ekg-build --version`, `ekg-consume --version`, `grounding-build --version`,
`grz-build --version`, or `ontology-consume --version`. For GRZ builds, check the
[native prerequisite](../../../README.md#grz-native-runtime-prerequisite).
Version checks alone do not prove service readiness.

Kusto graph analysis is external to this snapshot. `entity-skills` is planned
and cannot be run. If a required runtime or native asset is missing, report
the prerequisite; do not substitute a fixture, simulator or another revision.

Restart the host if needed after local plugin installation. Before sign-in,
state the tenant display name and avoid printing IDs, secrets or tokens.
Then hand off to the owning skill, retaining its approval boundaries.
