# @lam/sftp Changelog

All notable changes to `@lam/sftp` are documented here.

## 3.2.0 - 2026-10-19

### Added

- `onOpenWrite(req)`: called when a client opens a file for writing, before
  any data. An error becomes the OPEN status (missing parent directory,
  permission, quota), so clients that create parent directories on demand
  (curl/libssh `--ftp-create-dirs`) and POSIX-style tools see the failure at
  open instead of on the first write.

### Changed

- Read-only servers (`setReadOnly`) refuse opening a file for writing at
  OPEN, not only on the first write.

## 3.1.0 - 2026-10-17

### Added

- `SftpServer.activeSessions()`: the authenticated connections with their
  auth metadata, `username`, `remoteAddress` and `connectedAt`.
- `SftpServer.disconnectWhere(key, value)`: closes every authenticated
  connection whose auth metadata `key` equals `value` (e.g. a suspended
  account or a revoked key) and returns how many were closed.

## 3.0.1 - 2026-10-16

### Fixed

- The `@lam/ssh` dependency pointed at the tag `v2.0.0`, which is not
  published (release tags are plain versions), so installing the package from
  Git failed. It now pins `@lam/ssh` `3.0.0`, the release this package is
  tested with.

## 3.0.0 - 2026-10-15

### Added

- Byte-slice streaming: `onReadAtBytes`/`onWriteAtBytes` on `SftpHandlers` and
  `SftpServer`, the `SftpByteStreamingStorage` interface and
  `useByteStreamingStorage`. Packet payloads reach the callback as `bytes`
  without the per-byte `list[int]` conversion (about 25% more loopback
  throughput, no per-packet `[]int` allocation). Byte callbacks take
  precedence over the `list[int]` ones; guards, read-only mode and metrics
  apply unchanged.
- SSH algorithm configuration: `withCiphers`, `withKeyExchanges`, `withMacs`
  (validated against the SSH library) and `SftpConfig.fastCiphers()` (AES-GCM
  only). OpenSSH clients then negotiate AES-GCM instead of ChaCha20-Poly1305:
  about 2x single-session throughput (443 → 881 MB/s upload, 445 → 1117 MB/s
  download) and 1.6–2.2x with 8 parallel sessions.
- `withBufferReuse(enabled)`: packet buffers are reused across requests by
  default.
- `benchmarks/throughput.lam`: single- and multi-session throughput benchmark
  (in-process clients, external clients, CPU profiles).

### Changed

- Fewer per-packet costs: reused packet buffers and lazily re-armed idle
  deadlines raised in-process upload throughput with 8 sessions from about
  3.0 to 4.3 GB/s. The idle timeout now closes a connection between
  `idleTimeoutMs - min(idleTimeoutMs/10, 1s)` and `idleTimeoutMs` after its
  last activity.

### Fixed

- `offline_server_roundtrip` waits for the single connection slot of the
  rejected login to be released before dialling again; under load the server
  could still be holding it and refuse the public-key connection.

### Removed

- **Breaking:** removed the root `tag()` helper. The package name and version
  are declared in `lamlib.toml`, and the generic top-level function made this
  package impossible to link together with any other package (or application)
  that also declared `tag()`, because all Lam modules share one Go package.

## 2.0.0 - 2026-09-30

### Added

- Public `SftpRequest.context() -> Result[lamcontext.Context]` access for direct
  Lam cancellation, expiration, wait, reason, value, and native-interop APIs.
- Consumer tests that stage both `@lam/sftp` and local `@lam/ssh`, assert the
  SSH-backed Ed25519 host-key format, and exercise the request context wrapper.

### Changed

- Replaced `tryListen`/throwing `listen` and `tryListenBackground`/boolean
  `listenBackground` twins with unsuffixed `Result[bool]` lifecycle APIs.
- Consolidated partial storage registration into compile-time checked `use`
  overloads and explicit typed `useStorage`, `useStreamingStorage`, and
  `useProtocolStorage` installers; retained a typed `useBackend` aggregate while
  removing runtime assertions and `go!` bridges.
- Migrated class constructors from `__init__` to `init`, file reads to
  `Os.readFile`, and request-context helpers to propagated `Result` values.
- Raised compiler compatibility to Lam 1.18 and declared `@lam/ssh` v2.0.0 as
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
  testing documentation for Lam 1.18.

### Testing

- Added an installed-package SSH/SFTP loopback covering explicit typed storage
  installers, auth paths, request context, lifecycle hooks, failures, and metrics.

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
