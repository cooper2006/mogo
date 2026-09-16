# DSH dependency evidence

- Upstream: <https://github.com/deepseek-ai/deepseek-harness>
- Reviewed source commit: `0a15e36e7f82b6ed45af6fa9759f29b40dcd965d`
- Reviewed source root version: `0.1.6-alpha.1`
- Approved npm release train: `0.1.6-alpha.1`
- License: MIT; vendored text is in `DEEPSEEK-HARNESS-MIT.txt`
- Upstream `THIRD_PARTY_NOTICES.md` SHA256 at the reviewed commit:
  `82211a06d79227912a4ca76d86b7bf5b18ab260515ce4912fd1787d66995a786`

The exact direct artifacts, registry integrity values and license evidence are
recorded in `../versions.lock`. The complete installed `pnpm-lock.yaml`
dependency graph is represented by the checked-in CycloneDX inventory at
`../sbom.cdx.json`.

The npm `0.1.6-alpha.1` metadata does not publish a verified source mapping.
MOVO therefore treats the npm integrity hash as the deployable artifact
identity and the Git commit as a separate reviewed-source baseline. They must
not be claimed as a verified source/binary correspondence without new upstream
evidence.
