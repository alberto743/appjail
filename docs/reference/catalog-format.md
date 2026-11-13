# Catalog format

The format of a catalog that `appjail search` reads, whoever produces it: appjail-db, a file, or a URL added with
`index add`. Why it is strict is explained in [Catalog](../understand/catalog/index.md).

One UTF-8 JSON document, at most 16 MiB and 50,000 apps:

```json
{
  "format": "appjail-catalog",
  "version": 1,
  "origin": "https://example.org/my-apps",
  "revision": "2026-10-22",
  "apps": [
    {"name": "lagrange", "description": "A Gemini browser", "source": "github:skyjake/lagrange"},
    {"name": "tool-a", "source": "codeberg:user/tool-a"},
    {"name": "tool-b", "source": "gitlab:gitlab.example.org/group/sub/tool-b"},
    {"name": "tool-c", "source": "forgejo:git.example.net/user/tool-c"},
    {"name": "tool-d", "source": "url:https://example.com/dl/tool-d.AppImage"},
    {"name": "tool", "description": "Hosted elsewhere", "note": "resolve manually: https://example.org/tool"}
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `format` | yes | always `"appjail-catalog"` |
| `version` | yes | the integer `1`; any other version is refused |
| `origin` | no | where the catalog comes from, shown to you; up to 300 characters |
| `revision` | no | anything that tells two states apart (a commit, a date); up to 300 characters |
| `apps` | yes | a list of objects with unique names |
| `apps[].name` | yes | letters, digits, `.`, `_`, `+`, `-`, starting with a letter or digit; up to 81 characters |
| `apps[].description` | no | one line, up to 300 characters |
| `apps[].source` | no | `github:owner/repo`, `gitlab:HOST/group/.../project`, `forgejo:HOST/owner/repo`, `codeberg:owner/repo` (shorthand for `forgejo:codeberg.org/...`), `url:https://...`. Hosts are explicit, without port or credentials. Anything else, including `file:` and a bare `owner/repo`, is refused: put other locations in `note` |
| `apps[].note` | no | why there is no usable source, or a flag such as a repackager; up to 200 characters |

Rules:

- Unknown keys are errors, so a catalog means the same thing to every version that accepts it.
- A catalog that breaks a rule is refused as a whole; texts longer than their limit are cut, not refused.
- appjail stores its own serialisation of the catalog it validated, never the downloaded bytes.
- `search` offers an `appjail add` command for `github:` and `url:` sources only.
- An update that moves an app to another kind, host or owner is shown as an owner change.
