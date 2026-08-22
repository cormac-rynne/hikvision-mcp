# Security

## Reporting a vulnerability

Do not open a public issue for a vulnerability, credential, private address, serial number,
or unsanitized camera response. Use GitHub's private vulnerability reporting feature for the
repository. If private reporting is unavailable, contact a maintainer privately through their
GitHub profile before sharing technical details.

The latest release and the current `main` branch receive security fixes. Older versions are
not supported. Reports should include the affected version, impact, reproduction steps, and a
sanitized proof of concept. Maintainers will acknowledge reports when possible; response and
fix timelines depend on severity and maintainer availability.

## Security design

- The HTTP transport is local-only by default and uses the MCP SDK's transport protections.
- Camera hosts are fixed by TOML; ISAPI paths cannot target arbitrary hosts.
- Digest credentials come from environment variables and are redacted from responses.
- XML is parsed with external-entity-safe parsing.
- Live alerts are read for a bounded duration and returned without camera IP, MAC address,
  credentials, or raw multipart payloads.
- Detection, health, media, image, storage, and audio reads return typed semantic fields;
  MCP clients are not given raw endpoint access or raw camera payloads.
- Level 2/3 mutations require proposal then explicit approval/apply.
- A proposal detects camera changes made after it was created and refuses to overwrite them.
- Writes are not automatically retried, and success requires read-back verification.
- Persistent changes retain semantic and raw rollback snapshots in local SQLite.
- User/password, network, firmware, factory-reset, and raw write operations are not exposed.

The explicit two-call fallback prevents accidental one-call mutation but cannot prove that a
human supplied approval. Deployments requiring strong identity must use an MCP client with
native elicitation plus authenticated HTTP once that integration is added.
