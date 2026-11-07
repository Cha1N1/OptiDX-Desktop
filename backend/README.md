# Bundled Desktop backend

`OptiDX.py` is the independently adapted backend used by OptiDX Desktop. Its
original provenance remains in `UPSTREAM_SNAPSHOT.json`; `SNAPSHOT.json` records
the current checksum and Desktop changes. The separate original-script repository
is not modified by Desktop maintenance.

Use Python 3.10 or later with Desktop's dependencies, or the bundled interpreter:

```bash
./run.sh --backend --help
```

Management jobs use a scoped backend context in a separate worker process.
Keep installation and launching separate. The app's normal installation/update
jobs never launch a game.

The user quirks file accepts either of these forms:

```text
mygame = optiscaler_dll=d3d12.dll
othergame optiscaler_dll=version.dll
```

Downloads require verified HTTPS, including redirects. Available GitHub SHA-256
asset digests are checked before deployment, including cached payloads. Missing
upstream digests do not provide an independent authenticity check. The Desktop
metadata client supports `GITHUB_TOKEN` for GitHub API calls and reports when it
uses verified stale metadata after a network failure; payload failures remain
failures. Do not put tokens in profiles or publish them in diagnostics.
