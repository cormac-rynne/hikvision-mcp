# Adding capabilities

1. Define strongly typed semantic request and response models.
2. Add abstract adapter methods independent of Hikvision endpoint names.
3. Implement generic ISAPI mapping or a model/firmware-specific adapter subclass.
   Register model/firmware-specific adapters in `AdapterRegistry`; do not select them in the
   service or MCP layers.
4. Probe support and return `unsupported_capability` instead of guessing.
5. Add a read-only service method and MCP tool.
6. For writes, implement proposal, re-read/conflict check, raw snapshot, single write,
   read-back verification, audit, and rollback metadata.
7. Add sanitized XML, JSON, or multipart fixtures and mock-adapter integration tests.

Never add model-number branching to the MCP server or tool handlers.
