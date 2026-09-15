# @lam/sftp Changelog

All notable changes to `@lam/sftp` are documented here.

## Unreleased - 2026-09-13

### Added

- Public `SftpRequest.context() -> lamcontext.Context` access for direct Lam
  cancellation, expiration, wait, reason, value, and native-interop APIs.
- Consumer tests that stage both `@lam/sftp` and local `@lam/ssh`, assert the
  SSH-backed Ed25519 host-key format, and exercise the request context wrapper.

### Changed

- Raised compiler compatibility to Lam 1.16 and declared `@lam/ssh` v1.0.0 as
  a pinned Git dependency after validating the sibling-checkout development flow.
- Delegated `SftpKey.generate()` to `SshKeyPair.generateHostEd25519`; it now
  returns `privateKeyPem`, moving secure key generation into the shared
  `@lam/ssh`/`lamcrypto` ecosystem while preserving `Result[str]`.
- Reimplemented `SftpRequest.cancelled()` and `deadlineUnix()` through
  `lamcontext.Context`; `_context` remains only as the native SFTP adapter slot.
- Kept `github.com/pkg/sftp v1.13.11` as the direct protocol-engine pin and
  moved `golang.org/x/crypto v0.55.0` ownership to transitive `@lam/ssh`.
- Retained the established SSH server transport in `server.lam` and
  `_adapter.lam` to avoid destabilizing the protocol engine, and refreshed the
  requirements, architecture, package layout, installation, examples, and
  testing documentation for Lam 1.16.

## 1.0.0 - 2026-09-12

### Added

- Initial callback-driven SFTP server built on `github.com/pkg/sftp` and
  `golang.org/x/crypto/ssh`.
- Password and public-key authentication callbacks with per-session metadata.
- Storage callbacks for reads, buffered writes, listings, metadata, and
  filesystem commands.
- Structural `SftpStorage` interface and chainable `SftpHandlers` registration.
- `SftpRequest`, `SftpFile`, `SftpConfig`, `SftpKey`, and protocol-aware
  `SftpErrors` helpers.
- Blocking and background lifecycle APIs with active-connection shutdown.
- Lammergeier-native request guards, request/result observers, read-only mode,
  and per-command callback helpers.
- Ready, listen, close, and error lifecycle hooks plus `wait()`, `shutdown()`,
  and `activeConnections()`.
- Request/path, file-kind, auth-metadata, and chainable configuration helpers.
- Complete `github.com/pkg/sftp` v3 server profile: hard links, POSIX rename,
  StatVFS, RealPath, Readlink, Lstat, UID/GID, extended attributes, and
  owner/group lookup.
- Random-access `SftpStreamingStorage` and aggregate `SftpBackend` contracts for
  large objects without whole-file buffering.
- Production mode with connection limits, handshake/idle deadlines,
  authentication throttling, multiple/encrypted host keys, and SSH auth limits.
- Atomic operational metrics, request cancellation helpers, and stdlib fallback
  logging.
- Public-import tests, including an in-process SSH/SFTP round trip.

### Changed

- Reorganized the package into focused models, interfaces, metrics, handlers,
  configuration, server, and internal adapter modules; `__init__.lam` is now a
  small public re-export surface.
- Replaced trivial placeholder functions with typed callback lambdas owned by
  `SftpHandlers` and `SftpServer`.
- Moved callback dispatch, storage method binding, command routing, request
  policy, and server lifecycle orchestration out of top-level Go helpers and
  into Lammergeier methods.
- Replaced the server lifecycle's raw Go `sync.RWMutex` with the stdlib
  `lamconcurrency.RWMutex`; adapter-internal locks remain native because Go
  invokes those protocol interfaces directly.
- Updated `golang.org/x/crypto` to v0.55.0, which fixes the SSH authentication
  permissions issue affecting earlier releases.
- Background serving now uses Lammergeier `async func`; `go!` remains only at
  the SSH, SFTP, networking, synchronization, random-access I/O, and key-codec
  boundaries.
