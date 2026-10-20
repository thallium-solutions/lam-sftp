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
- Zero-conversion byte-slice streaming (`onReadAtBytes`/`onWriteAtBytes`,
  `SftpByteStreamingStorage`) for high-throughput storage backends.
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
  Lam 1.18's `lamcrypto` ecosystem, plus host-key loading through `lamos`.
- Configurable read and upload memory limits, each defaulting to 64 MiB.

## Lam-first implementation

Request policy, callback dispatch, storage adaptation, command routing,
lifecycle orchestration, guards, observers, and read-only behavior are written
in Lammergeier. Generic Ed25519 generation and OpenSSH key conversion belong to
`@lam/ssh`, which in turn uses Lam 1.18's `lamcrypto`; request cancellation and
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
├── __init__.lam       # public re-exports
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

- Lammergeier compiler (`lamc`) **1.18.0 or newer** within the compatible
  `1.x` and `2.x` lines (`>=1.18, <4`).
- `@lam/ssh` 3.0.2, resolved transitively from its pinned Git release.
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

Install the package directly from its Git release (tags are plain versions,
without a `v` prefix). Its manifest resolves the pinned `@lam/ssh` 3.0.0
dependency transitively:

```bash
lamc install https://github.com/thallium-solutions/lam-sftp.git@3.1.0
```

After a registry release, use the canonical scoped name:

```bash
lamc install @lam/sftp@3.1.0
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
    requestContext: Context = request.context()?
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

func serve() -> Result {
    config: SftpConfig = SftpConfig.fromKeyFile("./sftp_host_key")?
    handlers: SftpHandlers = SftpHandlers(
        read = readFile,
        list = listFiles,
        write = lambda (req: SftpRequest, data: list[int]) -> Result[int]: SftpErrors.permissionDenied(req.path),
        command = lambda (req: SftpRequest) -> Result[bool]: SftpErrors.unsupported(req.method),
    )

    server: SftpServer = SftpServer(config, handlers)
    _ = server.onPasswordAuth(lambda (auth: SftpAuth) -> bool: auth.username == "demo" and auth.password == "change-me")
    return server.listen()
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
    func init(self, bucket: S3Client) {
        self.bucket: S3Client = bucket
    }

    func read(self, request: SftpRequest) -> Result[list[int]] {
        return self.bucket.getBuffer(request.path[1:])
    }

    func write(self, request: SftpRequest, data: list[int]) -> Result[int] {
        uploaded: Result = self.bucket.putBuffer(request.path[1:], data)
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

server.use(BucketStorage(S3Client.fromEnv()))
```

Attach a partial storage provider with `server.use(storage)` or
`handlers.use(storage)`. `use` is implemented in Lammergeier by
binding the storage object's methods as ordinary callbacks. A callback
registered later with `onRead`, `onWrite`, `onList`, or `onCommand` overrides
the corresponding interface method.

`useByteStreamingStorage` installs a `SftpByteStreamingStorage`; it is a
separately named method because a class may satisfy both streaming interfaces.

For the complete production surface, implement `SftpBackend`. It combines the
basic `SftpStorage`, random-access `SftpStreamingStorage`, and
`SftpProtocolStorage` contracts. Attach it once with:

```lammergeier
server.useBackend(MyBackend())
```

`use` is an overload set for the disjoint `SftpStorage`,
`SftpStreamingStorage`, and `SftpProtocolStorage` roles. Lam 1.18 checks each
structural contract at compile time, so invalid providers no longer reach a
runtime type assertion. Use the separately typed `useBackend` method for a
complete `SftpBackend`; keeping the aggregate distinct avoids ambiguous overload
selection because a backend also satisfies the three narrower interfaces.

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

The same metadata identifies live sessions, so access can be withdrawn
immediately (an account suspended, a key revoked) without waiting for the
client to disconnect:

```lammergeier
for session in server.activeSessions() {
    print(session["username"], session["remoteAddress"], session["tenant"])
}
closed: int = server.disconnectWhere("tenant", suspendedTenantId)
```

`activeSessions()` returns one entry per authenticated connection with its
auth metadata plus `username`, `remoteAddress` and `connectedAt` (Unix
seconds). `disconnectWhere(key, value)` closes every connection whose metadata
`key` equals `value` and returns how many it closed; their transfers in
progress fail, other connections are unaffected.

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
| `onOpenWrite(req)` | Validate an open for writing before any data arrives (missing parent, permission, quota); the error is the OPEN status. |
| `onCloseWrite(req)` | Commit/finalize an upload after all writes succeed. |
| `onTransferError(req, error)` | Abort or clean up after a connection/transfer failure; `onCloseWrite` is skipped after failure. |

The SFTP engine may issue concurrent `ReadAt` calls. Streaming backends must be
safe for concurrent callbacks and must enforce their own total object/quota
limits; `maxReadBytes` and `maxWriteBytes` bound the convenience whole-file
mode, while SFTP packet size bounds individual streaming calls. Read-write
`Open` requires both `onReadAt` and `onWriteAt`; configuring only one returns
`SSH_FX_OP_UNSUPPORTED`. A short successful `writeAt` is rejected because
`github.com/pkg/sftp` otherwise reports the entire packet as written.

#### Byte-slice streaming

`onReadAt`/`onWriteAt` exchange `list[int]`, which costs a per-byte conversion
of every packet. High-throughput backends (object storage gateways, proxies)
should use the `bytes` variants instead; the packet payload is handed over
as-is:

| Registration | Purpose |
|---|---|
| `onReadAtBytes(req, offset, length) -> Result[bytes]` | Same contract as `onReadAt`, returning a byte slice. |
| `onWriteAtBytes(req, data: bytes, offset) -> Result[int]` | Same contract as `onWriteAt`, receiving the payload slice. |
| `useByteStreamingStorage(storage)` | Installs a `SftpByteStreamingStorage` (`readAtBytes`, `writeAtBytes`, `closeRead`, `closeWrite`). |

Byte callbacks take precedence over the `list[int]` ones when both are
registered, and guards, read-only mode, metrics and transfer-error hooks apply
unchanged. The `data` slice passed to `writeAtBytes` is only valid during the
call: copy it (for example by appending it to your own buffer) if it must
outlive the callback. On a 256 MiB loopback upload the byte path measured
~800 MiB/s versus ~640 MiB/s for `list[int]`, with no per-packet `[]int`
allocation.

```lammergeier
from @lam/sftp import SftpRequest, SftpServer
from lamerrors import Result

func forward(request: SftpRequest, data: bytes, offset: int) -> Result[int] {
    # hand `data` to a writer that copies it, e.g. an S3 multipart buffer
    return Result.Ok(len(data))
}

func install(server: SftpServer) {
    _ = server.onWriteAtBytes(forward)
}
```

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
| `context()` | `Result[Context]` wrapping the protocol request's native Go context. |
| `isReadOperation()`, `isWriteOperation()`, `isListOperation()`, `isCommandOperation()` | Operation classification helpers. |
| `cancelled()` | `Result[bool]` reporting cancellation by disconnect/completion. |
| `deadlineUnix()` | `Result[int]` containing the context deadline in Unix seconds, or `0` when none is set. |

Use `context()` directly for Lam 1.18 cancellation trees, expiration inspection,
bounded waits, reasons, and values. `context()`, `cancelled()`, and
`deadlineUnix()` preserve native-context and duration failures as `Result`
values. A manually constructed request receives a live simple context;
adapter-built requests wrap `github.com/pkg/sftp`'s native request context.

```lammergeier
requestContext: Context = request.context()?
closed: bool = requestContext.expired()
absoluteExpiryMs: int = requestContext.expiresIn(None)?
remainingMs: int = requestContext.expiresIn("milliseconds")?
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
    .withAddressAuthRateLimit(120, 60)
    .withAddressLockout(50, 600)
    .withProxyProtocol("optional", ["10.0.0.0/8"])
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
- `idleTimeoutMs` closes a connection after that long without network
  activity (the socket deadline is re-armed lazily, so an idle connection
  closes between `idleTimeoutMs - min(idleTimeoutMs/10, 1s)` and
  `idleTimeoutMs` after its last read or write).
- `maxAuthTries` is passed to `ssh.ServerConfig`.
- `authAttemptsPerSecond` and `authBurst` use the stdlib `TokenBucket` to bound
  aggregate authentication work. Set the rate to `0` only outside production.
- `withAddressAuthRateLimit(attemptsPerMinute, burst)` gives every client IP
  its own budget, checked before the server-wide one, so a single address
  hammering the server cannot use up `authAttemptsPerSecond` and lock
  everybody out. `withAddressLockout(maxFailures, seconds)` refuses an IP for
  `seconds` after `maxFailures` failed attempts within `seconds` (a successful
  sign-in resets the count). Both are off by default; size them for clients
  behind a shared NAT and for SSH clients that offer several keys (each
  rejected key counts as a failed attempt). The state is per server process,
  bounded in size, and available as `server.addressLimiter`
  (`SftpAddressLimiter`: `allow`, `recordFailure`, `isLocked`, `unlock`).
- `withProxyProtocol(mode, trustedCidrs)` accepts a PROXY protocol header
  (HAProxy v1 text or v2 binary, TCP over IPv4/IPv6; v2 TLVs are skipped)
  from load balancers in `trustedCidrs`, so sessions (`remoteAddress`),
  authentication callbacks, the per-address limits and logs see the real
  client. `"optional"` honours a header when a trusted peer sends one and
  keeps the TCP peer otherwise; `"required"` closes connections from
  untrusted peers and trusted peers without a header before the SSH
  handshake. A header sent by an untrusted peer is never honoured (the SSH
  handshake skips it as a pre-version line). v2 `LOCAL` (health checks) and
  v1 `UNKNOWN` keep the load balancer's address. Malformed headers close the
  connection; both count as `connectionsRejected`. Configure the balancer to
  send the header (HAProxy `send-proxy`/`send-proxy-v2`, AWS NLB proxy
  protocol v2, nginx `proxy_protocol on` in the stream module).
- Multiple host keys permit algorithm migration without abruptly changing the
  server identity for every client.
- Unhandled lifecycle errors are written through stdlib `lamlog.Log`; an
  `onError` callback replaces the default logger.

`server.metrics` is an `SftpMetrics` instance backed by stdlib `Atomic`
counters. `snapshot()` returns accepted/rejected connections, authentication
success/failure, attempts refused by the per-address limits (`authThrottled`), request/failure counts, and bytes read/written. `uptimeSeconds()`
uses stdlib `lamtime.Time`.

```lammergeier
metrics: dict[str, int] = server.metricsSnapshot()
print(metrics["connectionsAccepted"])
print(metrics["bytesWritten"])
print(server.uptimeSeconds())
```

## Performance and SSH algorithms

The per-packet path is allocation-light: byte callbacks receive the payload
slice directly, packet buffers are reused across requests
(`withBufferReuse(false)` turns this off if a callback must keep `data`
after returning), and idle deadlines are re-armed lazily.

The cipher dominates the remaining cost. OpenSSH clients prefer
ChaCha20-Poly1305, which is about half as fast as AES-GCM on CPUs with AES-NI.
The server cannot reorder a client's preferences, but it decides what it
offers:

```lammergeier
config = config.withCiphers(SftpConfig.fastCiphers())   # AES-GCM only
config = config.withKeyExchanges(["curve25519-sha256", "curve25519-sha256@libssh.org"])
config = config.withMacs(["hmac-sha2-256-etm@openssh.com"])  # unused by AEAD ciphers
```

Names are validated against the SSH library (`SftpConfigError` for unknown
ones); empty lists keep the library's secure defaults.

AES-GCM is missing from libssh2 before 1.11 (curl on Debian 12, PHP ssh2,
many integrations), which cannot connect to a GCM-only server. Adaptive
ciphers keep both: the server reads the client's SSH version line before the
handshake and offers the fast list only to clients known to support it
(`SftpConfig.gcmCapable`: OpenSSH 6.2+, libssh 0.9+, libssh2 1.11+, Go,
paramiko 3.5+, PuTTY 0.76+); every other client, and one that stays silent
for a second, gets `fallback` (default: the library's list):

```lammergeier
config = config.withAdaptiveCiphers(SftpConfig.fastCiphers())
```

Measured on an Intel i9-13900HX over loopback (server on 16 threads, clients
on the other 16; `benchmarks/throughput.lam` and OpenSSH 8.9 `sftp` with its
default settings, 1 GiB per session):

| Clients | Default ciphers | `fastCiphers()` |
|---|---|---|
| 1 OpenSSH session | 443 / 445 MB/s | 881 / 1117 MB/s (upload / download) |
| 4 sessions | 1358 / 1387 MB/s | 2550 / 3388 MB/s |
| 8 sessions | 2037 / 2177 MB/s | 3754 / 4777 MB/s |
| 16 sessions | | 4200 / 4548 MB/s |

Concurrent sessions share bandwidth evenly (at 32 sessions every flow stayed
within 80–97 MB/s). A single session already exceeds a 5 GbE link (about
590 MB/s of payload), so the network is the limit in practice. Run the
benchmark yourself:

```bash
lamc benchmarks/throughput.lam --extlibs <dir with @lam/sftp and @lam/ssh> -o /tmp/sftpbench
BENCH_MB=256 BENCH_FLOWS=1,4,8,16 /tmp/sftpbench
BENCH_SERVE=127.0.0.1:2222 BENCH_FAST_CIPHERS=1 /tmp/sftpbench   # for external clients
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

_ = server.listenBackground()?
print(server.activeConnections())
# application work

server.shutdown()
print(server.isListening())
```

- `listen()` blocks until the server closes and returns `Result[bool]`.
- `listenBackground()` starts the Lammergeier `async func` and returns
  `Result[bool]` immediately with startup details.
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

The tests require `lamc >=1.18.0`, stage the sibling checkouts as
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
