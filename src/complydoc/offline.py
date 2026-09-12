"""Process-wide network guard.

complydoc's entire trust proposition is that document content never leaves the
machine. That promise is enforced here rather than merely documented: the guard
replaces the outbound entry points of the standard library socket module with
functions that raise, so any accidental or transitive network call fails loudly
instead of succeeding quietly.

The guard is armed by the CLI before any document is opened, and
``tests/test_offline_guard.py`` asserts that a full audit completes with it in
place. Local ``AF_UNIX`` sockets are permitted because they cannot leave the
machine; every ``AF_INET``/``AF_INET6`` connection and every DNS lookup is
refused.

``arm`` changes the whole process, which is right for a command that owns its
process and wrong for a library inside somebody else's. Code called as a
library uses ``guarded()``, which puts the socket module back exactly as it
found it — so complydoc can promise its own audit reached no network without
breaking the network its caller depends on.
"""

from __future__ import annotations

import contextlib
import socket
from collections.abc import Iterator
from typing import Any, Final

__all__ = ["NetworkAccessError", "arm", "guard_status", "guarded", "is_armed"]

_ORIGINAL_CONNECT: Final = socket.socket.connect
_ORIGINAL_CONNECT_EX: Final = socket.socket.connect_ex
_ORIGINAL_CREATE_CONNECTION: Final = socket.create_connection
_ORIGINAL_GETADDRINFO: Final = socket.getaddrinfo

_armed = False

_MESSAGE = (
    "complydoc blocked an outbound network call. This tool is offline by design: "
    "no document content may leave the machine. If you are seeing this, a dependency "
    "attempted a connection and the run has been stopped rather than allowed to continue."
)


class NetworkAccessError(RuntimeError):
    """Raised when any code attempts to open a network connection."""


def _is_local(family: int) -> bool:
    unix = getattr(socket, "AF_UNIX", None)
    return unix is not None and family == unix


def _blocked_connect(self: socket.socket, address: Any) -> None:
    if _is_local(self.family):
        _ORIGINAL_CONNECT(self, address)
        return
    raise NetworkAccessError(f"{_MESSAGE} (attempted connect to {address!r})")


def _blocked_connect_ex(self: socket.socket, address: Any) -> int:
    if _is_local(self.family):
        return int(_ORIGINAL_CONNECT_EX(self, address))
    raise NetworkAccessError(f"{_MESSAGE} (attempted connect_ex to {address!r})")


def _blocked_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
    raise NetworkAccessError(f"{_MESSAGE} (attempted create_connection to {address!r})")


def _blocked_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
    raise NetworkAccessError(f"{_MESSAGE} (attempted DNS lookup of {host!r})")


def arm() -> None:
    """Install the guard. Idempotent."""
    global _armed
    if _armed:
        return
    # Replacing standard library entry points is the point of this module, so the
    # signature mismatches mypy reports here are deliberate rather than accidental.
    socket.socket.connect = _blocked_connect  # type: ignore[method-assign, assignment]
    socket.socket.connect_ex = _blocked_connect_ex  # type: ignore[method-assign, assignment]
    socket.create_connection = _blocked_create_connection
    socket.getaddrinfo = _blocked_getaddrinfo
    _armed = True


def disarm() -> None:
    """Restore the original socket entry points.

    Used by test teardown and by `guarded()` on its way out. Not something a
    document-reading path should ever call.
    """
    global _armed
    socket.socket.connect = _ORIGINAL_CONNECT  # type: ignore[method-assign]
    socket.socket.connect_ex = _ORIGINAL_CONNECT_EX  # type: ignore[method-assign]
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION
    socket.getaddrinfo = _ORIGINAL_GETADDRINFO
    _armed = False


@contextlib.contextmanager
def guarded(active: bool = True) -> Iterator[None]:
    """Arm the guard for this block, then leave the process as it was found.

    The library entry points run inside this. Arming permanently would be
    sabotage in a host application: every unrelated HTTP call in the process
    would start failing, with a message about documents that makes no sense
    where it appeared.

    Restores on the way out whatever happens, and does nothing at all if the
    caller has already armed the guard for themselves — in which case it is
    theirs to disarm, not ours.
    """
    if not active or _armed:
        yield
        return

    arm()
    try:
        yield
    finally:
        disarm()


def is_armed() -> bool:
    return _armed


def guard_status() -> str:
    """The value recorded in every report's run metadata."""
    return "armed" if _armed else "not_armed"
