# Native GRZ runtime

Community generation uses the separate, self-contained **GRZBuildPoc 0.1.4-local**
binary and the `grz-cli-v1` contract. Python wheels contain the importer and
verified launcher, not a Python clustering fallback or the native executable.
Normal plugin setup does not download or execute native code.

Obtain the native artifact from the operator's trusted distribution and select its
absolute path with `--native-binary` (or `GRZ_BUILD_BINARY`). Before execution the
runtime verifies the selected bytes against the host's pinned SHA-256:

| Native RID | Executable | SHA-256 |
|---|---|---|
| `win-x64` | `GRZBuildPoc.exe` | `6aa6ac85ed84436ce9676178c252eede85891b9d1717aca66cae095830354579` |
| `linux-x64` | `GRZBuildPoc` | `7095407bc5b3499056e2f94401d6eed22b103f2db947aae114e96b17fcaab66a` |

Only these two native pins are supplied. Five Python dependency locks do **not**
mean five native generation builds are provided. Other supported Python hosts can
browse existing hierarchies; native generation without a supplied trusted host
checksum fails explicitly. Do not bypass verification, synthesize native outputs,
substitute another binary or infer execution acceptance from lock resolution.

Read-only import of retained native artifacts is not a new native run, full source
coverage, successful upload, publication or model-call authorization.
