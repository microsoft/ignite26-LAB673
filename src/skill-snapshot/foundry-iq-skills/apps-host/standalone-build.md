# Contributor build and immutable export

Consumers do not run these commands. Contributors use the existing pinned
toolchain and approved npm feed; on Windows set `GRAPH_TEST_PYTHON` to an existing
Python 3.12 executable when needed by supervision tests.

```powershell
npm run typecheck
npm run build:embedded
npm run build:standalone
npm run test:standalone
npm run test:standalone:browser
npm run package:standalone
```

`package:standalone` builds and exports `dist\apps-host`, not a separate ZIP:

```text
apps-host/
  launch.mjs
  connector.mjs
  supervise.py
  README.md
  standalone-*.md
  CONNECTOR_THIRD_PARTY_NOTICES.txt
  payload-provenance.json
  ui/
    standalone.html
    sandbox.html
    assets/*
    THIRD_PARTY_NOTICES.txt
    build-provenance.json
    apps/
      ontology/
        ontology.html
        evidence.html
        assets/*
        THIRD_PARTY_NOTICES.txt
        asset-manifest.json
      ekg/  (graph.html, evidence.html, assets, notices, manifest)
      grz/  (explorer.html, evidence.html, assets, notices, manifest)
```

The export requires a clean source commit and exact lock/output hashes. Payload
provenance binds every file except itself using relative paths and raw lowercase
SHA-256, with source/dirty identity, Node, SDK and lockfile versions. The host
README index and every linked standalone guide page are copied from the canonical docs and included in that file map. The plugin
packager must preserve the complete variable emitted tree, not a fixed file count.
Run `build:embedded` before the localhost build to bind the matching six embedded
resource hashes. Embedded single-file files and their existing runtime contract
remain separate from this localhost payload. The plugin
packager preserves those bytes and independently binds the provenance in its
final plugin digest. No npm dependencies, fixtures, credentials, source maps,
developer checkout or additional wrapper/client are needed at customer runtime.

Dependency versions remain pinned in the root lock. TypeScript 6.0.3 retains
the public AST APIs used by existing identity regressions; this transport change
does not authorize renderer upgrades or relax historical performance gates.

[Prerequisites and setup](standalone-setup.md) | [Launch](standalone-launch.md)
