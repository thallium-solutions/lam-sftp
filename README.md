# @lam/sftp

`@lam/sftp` is a callback-driven SFTP server for the
[Lammergeier programming language](https://github.com/thallium-solutions/lammergeier-lang).
It keeps [`github.com/pkg/sftp`](https://github.com/pkg/sftp) as its SFTP
protocol engine and composes with local
[`@lam/ssh`](https://github.com/thallium-solutions/lam-ssh) for generic SSH key
functionality and SSH dependency ownership, while leaving storage
entirely to the application. Files can come from an S3 bucket, local disk, a
database, a virtual filesystem, an API, or any other source your callbacks can
reach.

## Features

- Lammergeier functions and lambdas for password auth, public-key auth, reads,
  writes, directory listings, metadata lookups, and filesystem commands.
- A structural `SftpStorage` interface for class-based backends.
- Standard `lamerrors.Result` and `Error` values for expected failures.
- Protocol-aware `SftpErrors` helpers for not-found, permission, conflict,
  invalid-request, and unsupported-operation responses.
- Normalized `SftpRequest` values with the authenticated user, peer address,
  open flags, attributes, target path, per-session metadata, and a public
  `lamcontext.Context` wrapper.
- Blocking and background server lifecycle methods built with Lammergeier
  `async func`, plus ready/listen/close/error hooks.
- Per-command sugar (`onMkdir`, `onRemove`, `onRename`, and others), request
  guards, request/result observers, and a server-wide read-only switch.
- In-memory OpenSSH Ed25519 host-key generation delegated to `@lam/ssh` and
  Lam 1.16's `lamcrypto` ecosystem, plus host-key loading through `lamos`.
- Configurable read and upload memory limits, each defaulting to 64 MiB.

## Lam-first implementation

Request policy, callback dispatch, storage adaptation, command routing,
lifecycle orchestration, guards, observers, and read-only behavior are written
in Lammergeier. Generic Ed25519 generation and OpenSSH key conversion belong to
`@lam/ssh`, which in turn uses Lam 1.16's `lamcrypto`; request cancellation and
expiration are exposed as `lamcontext.Context`. The raw request context is kept
only in `SftpRequest._context` as the adapter slot required by
`github.com/pkg/sftp`.

The established SSH server transport stays in `server.lam` and `_adapter.lam`
because extracting it would destabilize the existing protocol engine. Their
`go!` boundaries remain limited to SSH/SFTP transport, network listeners,
`io.ReaderAt`/`io.WriterAt`, `os.FileInfo`, and adapter-internal synchronization.
Production controls reuse `lamerrors`, `lamos`, `lamlog`, `lamtime`,
`lamconcurrency`, and `lamratelimit.TokenBucket` instead of reimplementing those
facilities. `github.com/pkg/sftp v1.13.11` remains a direct Go pin;
`golang.org/x/crypto v0.55.0` is supplied transitively by `@lam/ssh`.

## Package structure

```text
lam-sftp/
├── __init__.lam       # public re-exports and tag()
├── models.lam         # requests/lamcontext, files, auth, errors, StatVFS
├── interfaces.lam     # storage and backend contracts
├── metrics.lam        # Atomic-backed operational counters
├── handlers.lam       # callbacks, guards, routing, read-only policy
├── config.lam         # configuration and @lam/ssh-backed host keys
├── server.lam         # Lam lifecycle plus established SSH server transport
└── _adapter.lam       # unavoidable Go SSH/SFTP protocol/interface adapter
```

Consumers import only the scoped package root. Internal modules use relative
imports and are bundled transitively:

```lammergeier
from @lam/sftp import SftpServer, SftpConfig, SftpHandlers
```

## Requirements

- Lammergeier compiler (`lamc`) **1.16.0 or newer** within the compatible
  `1.x` line (`^1.16`).
- `@lam/ssh` v1.0.0, resolved transitively from its pinned Git release.
- Go **1.25.0 or newer**, required by `github.com/pkg/sftp v1.13.11`.

## Compliance profile

`@lam/sftp` implements the complete server-side profile exposed by
`github.com/pkg/sftp v1.13.11`: SFTP protocol version 3 plus
`hardlink@openssh.com`, `posix-rename@openssh.com`, and
`statvfs@openssh.com`. The adapter implements random read/write handles,
read-write `Open`, `Setstat`, distinct `Stat`/`Lstat`, canonical `RealPath`,
`Readlink`, UID/GID, extended attributes, owner/group name lookup, hard links,
POSIX rename, and filesystem statistics.

The dependency does not implement SFTP v4–v6, ACLs, remote file locking,
`fsync@openssh.com`, or arbitrary vendor extensions. Those cannot honestly be
claimed by this package without replacing or extending the underlying protocol
engine. Open and Mkdir creation-attribute limitations inherited from
`github.com/pkg/sftp` are also documented below.

## Installation

Install the package directly from its Git release. Its manifest resolves the
pinned `@lam/ssh` v1.0.0 dependency transitively:

```bash
lamc install https://github.com/thallium-solutions/lam-sftp.git@v1.0.0
```

After a registry release, use the canonical scoped name:

```bash
lamc install @lam/sftp@1.0.0
```

For sibling-checkout development, declare the package in an application project
and redirect only SSH with the project-level replacement mechanism:

```toml
[dependencies]
"@lam/sftp" = { path = "../lam-sftp" }

[replace]
"@lam/ssh" = { path = "../lam-ssh" }
```

Then run `lamc install`. Tests do not install globally; their runner stages both
checkouts as `extlibs/@lam/sftp` and `extlibs/@lam/ssh`, matching the resolved
consumer layout while remaining independent of network availability.

The manifest name remains `@lam/sftp`, so every installation form uses the same import:

```lammergeier
from @lam/sftp import SftpServer
```

## Host key

Use a persistent host key in production so clients can verify the server's
identity:

```bash
ssh-keygen -t ed25519 -f ./sftp_host_key -N ''
```

Do not commit the private key. `SftpKey.generate()` preserves its
`Result[str]` API, delegates generation to
`SshKeyPair.generateHostEd25519("lam-sftp host key")`, and returns the pair's
OpenSSH `privateKeyPem`. `@lam/ssh` sources Ed25519 key material from
`lamcrypto`.

```lammergeier
from @lam/sftp import SftpConfig, SftpKey

hostKey: str = SftpKey.generate()?
config: SftpConfig = SftpConfig(hostKey)
```

Ephemeral keys are intended for tests or short-lived development servers. For
fingerprints, authorized public keys, passphrases, and parsing, use the full
`SshKeyPair` API from `@lam/ssh` directly.

## Quick start with callbacks

Every handler can be a named function or a lambda. The example below exposes
one read-only virtual file:

```lammergeier
from @lam/sftp import SftpAuth, SftpConfig, SftpErrors, SftpFile, SftpHandlers, SftpRequest, SftpServer
from lambytes import Bytes
from lamcontext import Context
from lamerrors import Result

func readFile(request: SftpRequest) -> Result[list[int]] {
    requestContext: Context = request.context()
    if requestContext.expired() {
        return SftpErrors.connectionLost("client disconnected")
    }
    if request.path == "/hello.txt" {
        return Result.Ok(Bytes.toBytes("hello from Lammergeier\n"))
    }
    return SftpErrors.notFound(request.path)
}

func listFiles(request: SftpRequest) -> Result[list[SftpFile]] {
    if request.method == "List" and request.path == "/" {
        return Result.Ok([SftpFile.file("hello.txt", 23)])
    }
    if request.method == "Stat" and request.path == "/hello.txt" {
        return Result.Ok([SftpFile.file("hello.txt", 23)])
    }
    if request.method == "Stat" and request.path == "/" {
        return Result.Ok([SftpFile.directory("/")])
    }
    return SftpErrors.notFound(request.path)
}

func main() {
    do {
        config: SftpConfig = SftpConfig.fromKeyFile("./sftp_host_key")?
        handlers: SftpHandlers = SftpHandlers(
            read = readFile,
            list = listFiles,
            write = lambda (req: SftpRequest, data: list[int]) -> Result[int]: SftpErrors.permissionDenied(req.path),
            command = lambda (req: SftpRequest) -> Result[bool]: SftpErrors.unsupported(req.method),
        )

        server: SftpServer = SftpServer(config, handlers)
        _ = server.onPasswordAuth(lambda (auth: SftpAuth) -> bool: auth.username == "demo" and auth.password == "change-me")
        _ = server.tryListen()?
    } catch err {
        print(f"SFTP failed: {err}")
    }
}
```

Connect with any SFTP client:

```bash
sftp -P 2022 demo@127.0.0.1
```

## Class-based storage

Use `SftpStorage` when a backend has state or several handlers share a client.
The interface is structural: a class only needs methods with the matching
signatures.

```lammergeier
from @lam/sftp import SftpErrors, SftpFile, SftpRequest, SftpStorage
from @lam/s3 import S3Client
from lamerrors import Result

class BucketStorage {
    func __init__(self, bucket: S3Client) {
        self.bucket: S3Client = bucket
    }

    func read(self, request: SftpRequest) -> Result[list[int]] {
        return self.bucket.tryGetBuffer(request.path[1:])
    }

    func write(self, request: SftpRequest, data: list[int]) -> Result[int] {
        uploaded: Result = self.bucket.tryPutBuffer(request.path[1:], data)
        if not uploaded.ok() {
            return uploaded
        }
        return Result.Ok(len(data))
    }

    func list(self, request: SftpRequest) -> Result[list[SftpFile]] {
        return SftpErrors.unsupported(request.method)
    }

    func command(self, request: SftpRequest) -> Result[bool] {
        return SftpErrors.unsupported(request.method)
    }
}

# server.useStorage(BucketStorage(S3Client.fromEnv()))
```

Attach a backend with `server.useStorage(backend)` or
`handlers.useStorage(backend)`. `useStorage` is implemented in Lammergeier by
binding the storage object's methods as ordinary callbacks. A callback
registered later with `onRead`, `onWrite`, `onList`, or `onCommand` overrides
the corresponding interface method.

For the complete production surface, implement `SftpBackend`. It combines the
basic `SftpStorage`, random-access `SftpStreamingStorage`, and
`SftpProtocolStorage` contracts. Attach it once with:

```lammergeier
server.useBackend(MyBackend())
```

`useBackend` validates the structural interface at runtime because current
`lamc` versions incorrectly lower imported interface annotations to pointers to
Go interfaces when one class is explicitly assigned to several imported
interfaces. Individual typed `useStorage`, `useStreamingStorage`, and
`useProtocolStorage` methods remain available.

## Authentication and session metadata

No authentication mode is enabled by default. At least one callback is required
before `listen` or `listenBackground` can start.

```lammergeier
server.onPasswordAuth(lambda (auth: SftpAuth) -> bool: auth.username == "deploy" and verify(auth.password))
server.onPublicKeyAuth(lambda (auth: SftpAuth) -> bool: allowedFingerprints.contains(auth.fingerprint))
```

Password auth receives `username`, `password`, `remoteAddress`, and
`method = "password"`. Public-key auth receives `username`, `publicKey` in
OpenSSH authorized-key format, `fingerprint`, `remoteAddress`, and
`method = "publicKey"`.

An auth callback can attach non-secret routing information to the session:

```lammergeier
func authenticate(auth: SftpAuth) -> bool {
    if validTenantUser(auth.username, auth.password) {
        auth.set("tenant", tenantFor(auth.username))
        return true
    }
    return false
}

func readTenantFile(request: SftpRequest) -> Result[list[int]] {
    tenant: str = request.sessionValue("tenant")
    return loadTenantBytes(tenant, request.key())
}
```

The password is cleared before session metadata is retained. Never place
credentials or other secrets in `auth.meta`.

## Request routing

### Data callbacks

| Registration | Signature | Called for |
|---|---|---|
| `onRead` | `func(SftpRequest) -> Result[list[int]]` | Opening a file for reading |
| `onWrite` | `func(SftpRequest, list[int]) -> Result[int]` | Closing a successfully uploaded file |
| `onList` | `func(SftpRequest) -> Result[list[SftpFile]]` | `List`, `Stat`, `Lstat`, and `Readlink` |
| `onCommand` | `func(SftpRequest) -> Result[bool]` | Fallback for `Setstat`, `Rename`, `Remove`, `Mkdir`, `Rmdir`, `Link`, `Symlink`, and related commands |
| `onCommandMethod` | `str, func(SftpRequest) -> Result[bool]` | One exact command method |
| `onMkdir`, `onRemove`, `onRename`, … | `func(SftpRequest) -> Result[bool]` | One named command without a manual method switch |

`onRead` returns a complete file and `onWrite` receives a complete file after
the client closes its handle. The server buffers those values to implement
SFTP's random-access I/O. `maxReadBytes` and `maxWriteBytes` limit each buffer;
both default to 67,108,864 bytes. Set either to `0` only when an unlimited
buffer is acceptable for your deployment. A read/write `Open` first obtains
existing bytes through `onRead` and commits changed bytes through `onWrite`;
handles closed without a mutation are not written back.

For `Stat` and `Lstat`, return exactly one `SftpFile`. For `List`, return the
directory's children. For `Readlink`, return one symlink with `target` set.
All callback values may be produced by named functions or lambdas.

### Random-access streaming

Whole-file callbacks are convenient for small objects. Production backends can
avoid buffering entire files by implementing `SftpStreamingStorage` or
registering these callbacks:

| Registration | Purpose |
|---|---|
| `onReadAt(req, offset, length)` | Return at most `length` bytes beginning at `offset`; a short result signals EOF. |
| `onWriteAt(req, data, offset)` | Persist one random-access chunk and return the number of bytes written. |
| `onCloseRead(req)` | Release a read transaction or range-reader. |
| `onCloseWrite(req)` | Commit/finalize an upload after all writes succeed. |
| `onTransferError(req, error)` | Abort or clean up after a connection/transfer failure; `onCloseWrite` is skipped after failure. |

The SFTP engine may issue concurrent `ReadAt` calls. Streaming backends must be
safe for concurrent callbacks and must enforce their own total object/quota
limits; `maxReadBytes` and `maxWriteBytes` bound the convenience whole-file
mode, while SFTP packet size bounds individual streaming calls. Read-write
`Open` requires both `onReadAt` and `onWriteAt`; configuring only one returns
`SSH_FX_OP_UNSUPPORTED`. A short successful `writeAt` is rejected because
`github.com/pkg/sftp` otherwise reports the entire packet as written.

### Protocol metadata and extensions

- `onStatVFS` returns `SftpStatVFS` for `statvfs@openssh.com`.
- `onRealPath` returns an absolute canonical POSIX path.
- `onReadlink` returns a relative or absolute link target.
- `onUsername` and `onGroupName` map decimal UID/GID strings for long listings.
- `onPosixRename` preserves POSIX-rename semantics instead of falling back to
  ordinary v3 rename.
- `onLink` handles `hardlink@openssh.com`.

`SftpFile` exposes `uid`, `gid`, and `extended: list[SftpExtended]`; these are
encoded through `FileInfoUidGid` and `FileInfoExtendedData` on directory and
stat responses. `SftpRequest` exposes size, UID/GID, permissions, access time,
modification time, and extended attributes for `Setstat`.

### Guards, observers, and read-only mode

These policies run in Lammergeier before the Go SFTP adapter receives the
result:

```lammergeier
# Result.Ok(false) becomes permission denied; Result.Err is propagated.
server.guard(lambda (req: SftpRequest) -> Result[bool]: Result.Ok(req.sessionValue("tenant") != ""))

# Observers run for successful and failed requests.
server.onRequest(lambda (req: SftpRequest): print(f"SFTP {req.user} {req.method} {req.path}"))
server.onResult(lambda (req: SftpRequest, result: Result): print(f"completed={result.ok()}"))

# Reads and listings continue; writes and commands are denied.
server.setReadOnly()
```

Guards run in registration order. Command-specific callbacks take precedence
over the generic `onCommand` fallback:

```lammergeier
server.onMkdir(lambda (req: SftpRequest) -> Result[bool]: createVirtualDirectory(req.key()))
server.onCommandMethod("Setstat", lambda (req: SftpRequest) -> Result[bool]: applyAttributes(req))
```

### `SftpRequest` fields and helpers

| Field | Description |
|---|---|
| `method` | SFTP operation such as `Get`, `Put`, read/write `Open`, `List`, `Stat`, `Rename`, or `Mkdir`. |
| `path` | Normalized absolute POSIX path. |
| `target` | Destination used by rename and link operations. |
| `user` | Authenticated SSH username. |
| `remoteAddress` | Client network address. |
| `session` | Metadata set by the successful auth callback. |
| `read`, `write`, `append`, `create`, `truncate`, `exclusive` | File-open flags. |
| `hasSize`, `size` | Requested size attribute for `Setstat`. |
| `hasUidGid`, `uid`, `gid` | Requested ownership attributes. |
| `hasPermissions`, `permissions` | Requested numeric mode. |
| `hasAccessTime`, `accessedUnix` | Requested access time. |
| `hasModifiedTime`, `modifiedUnix` | Requested modification time. |
| `hasExtended`, `extended` | Requested v3 extended attributes. |
| `key()` | Path without the leading `/`, convenient for object stores. |
| `basename()` | Last path segment. |
| `sessionValue(key, fallback="")` | Safe session metadata lookup. |
| `context()` | Public `lamcontext.Context` wrapping the protocol request's native Go context. |
| `isReadOperation()`, `isWriteOperation()`, `isListOperation()`, `isCommandOperation()` | Operation classification helpers. |
| `cancelled()` | Whether `context().expired()` reports cancellation by disconnect/completion. |
| `deadlineUnix()` | `context()` deadline in Unix seconds, or `0` when none is set. |

Use `context()` directly for Lam 1.16 cancellation trees, expiration inspection,
bounded waits, reasons, and values. `cancelled()` and `deadlineUnix()` remain as
compatibility conveniences and are implemented through the same wrapper. A
manually constructed request receives a live simple context; adapter-built
requests wrap `github.com/pkg/sftp`'s native request context.

```lammergeier
requestContext: Context = request.context()
closed: bool = requestContext.expired()
absoluteExpiryMs: int = requestContext.expiresIn(None)
remainingMs: int = requestContext.expiresIn("milliseconds")
```

`expiresIn(None)` returns the absolute Unix-millisecond expiry. Supplying a unit
returns the remaining duration; both forms return `-1` when no expiry exists.

`github.com/pkg/sftp` does not preserve the attribute-flags word from
`SSH_FXP_OPEN` and ignores attributes on `SSH_FXP_MKDIR`. Therefore creation
attributes are not exposed reliably; clients should issue `Setstat` after
creation when ownership, mode, or timestamps matter.

### `SftpFile`

```lammergeier
SftpFile.file("report.pdf", 12040)
SftpFile.directory("reports")
SftpFile.symlink("latest", "/reports/2026.pdf")
```

Permissions are numeric POSIX modes: files default to `420` (`0644`),
directories to `493` (`0755`), and symlinks to `511` (`0777`).
`modifiedUnix` is a Unix timestamp in seconds. Use `at(path)` to attach a full
path and `isFile()`, `isDirectory()`, or `isSymlink()` to inspect the kind.

## Configuration builders

Configuration can be constructed positionally or with chainable Lammergeier
helpers:

```lammergeier
config: SftpConfig = (SftpConfig(hostKey)
    .addHostKey(rsaHostKey)
    .withAddress("127.0.0.1:2022")
    .withStartDirectory("/uploads")
    .withReadLimit(32 * 1024 * 1024)
    .withWriteLimit(32 * 1024 * 1024)
    .withPacketSize(65536)
    .withConnectionLimit(256)
    .withTimeouts(10000, 300000)
    .withAuthRateLimit(20, 40)
    .productionMode())
```

`addHostKeyFile(path)` loads additional keys through `lamos` and returns
`Result[SftpConfig]`. `withHostKeyPassphrase` enables encrypted private keys;
one passphrase is applied to every configured key. Production mode refuses to
start without bounded reads/writes, idle and authentication limits, and
`StatVFS`, `RealPath`, and `Readlink` callbacks.

## Production controls and metrics

- `maxConnections` bounds accepted TCP/SSH connections.
- `handshakeTimeoutMs` limits clients that connect without completing SSH.
- `idleTimeoutMs` is refreshed on every network read/write.
- `maxAuthTries` is passed to `ssh.ServerConfig`.
- `authAttemptsPerSecond` and `authBurst` use the stdlib `TokenBucket` to bound
  aggregate authentication work. Set the rate to `0` only outside production.
- Multiple host keys permit algorithm migration without abruptly changing the
  server identity for every client.
- Unhandled lifecycle errors are written through stdlib `lamlog.Log`; an
  `onError` callback replaces the default logger.

`server.metrics` is an `SftpMetrics` instance backed by stdlib `Atomic`
counters. `snapshot()` returns accepted/rejected connections, authentication
success/failure, request/failure counts, and bytes read/written. `uptimeSeconds()`
uses stdlib `lamtime.Time`.

```lammergeier
metrics: dict[str, int] = server.metricsSnapshot()
print(metrics["connectionsAccepted"])
print(metrics["bytesWritten"])
print(server.uptimeSeconds())
```

## Errors

Callbacks return stdlib `Result` values. `SftpErrors` creates structured errors
that map to useful SFTP status codes:

```lammergeier
return SftpErrors.notFound(request.path)
return SftpErrors.permissionDenied(request.path)
return SftpErrors.alreadyExists(request.path)
return SftpErrors.invalid("path cannot be empty")
return SftpErrors.unsupported(request.method)
return SftpErrors.eof()
return SftpErrors.connectionLost("upstream object stream closed")
```

Other `Result.Err(...)` values are returned as general SFTP failures. A panic in
a storage callback is recovered and converted into a callback failure rather
than terminating the listener.

## Lifecycle

```lammergeier
server.onReady(lambda (_srv: SftpServer): print("preparing SFTP"))
server.onListen(lambda (srv: SftpServer): print(f"listening on {srv.boundAddress}"))
server.onClose(lambda (_srv: SftpServer): print("SFTP closed"))
server.onError(lambda (error: any): print(f"SFTP error: {error}"))

do {
    server.tryListenBackground()?
    print(server.activeConnections())
    # application work
} catch err {
    print(f"SFTP startup failed: {err}")
}

server.shutdown()
print(server.isListening())
```

- `listen()` blocks until the server closes and panics on startup failure.
- `tryListen()` is the blocking `Result`-returning variant.
- `listenBackground()` uses a Lammergeier `async func` and returns immediately
  with a success boolean.
- `tryListenBackground()` returns `Result[bool]` with startup details.
- `close()` is idempotent and asks the listener and active connections to
  close without waiting, so it is safe from lifecycle callbacks.
- `wait()` blocks until a background listener and its `onClose` callbacks
  complete.
- `shutdown()` performs `close()` followed by `wait()`.
- `activeConnections()` reports current client TCP/SSH connections, including
  connections still completing authentication.

Register handlers and auth callbacks before starting the listener. Handler
mutation while requests are active is not supported. Do not call blocking
`wait()` or `shutdown()` from a lifecycle callback; use non-blocking `close()`
there instead.

## Testing

The tests require `lamc >=1.16.0`, stage the sibling checkouts as
`extlibs/@lam/sftp` and `extlibs/@lam/ssh`, compile through public scoped
imports, assert the `lamcontext.Context` and SSH-backed host-key integration,
and preserve the SSH/SFTP round trip against a callback-backed in-memory store:

```bash
python3 tests/run_lamsftp_tests.py --verbose
python3 tests/run_lamsftp_tests.py --race --verbose
```

Formatting can be checked with:

```bash
lamc fmt . --check
```

## License

Copyright 2026 Thallium Solutions di Busconi Alessandro. Distributed under the
Apache License, Version 2.0. Third-party dependencies retain their respective
licenses.
