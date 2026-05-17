"""The Broadcaster: routes master keystrokes to enabled, alive slaves.

Author: Aditya Kapadia.

Pure logic, owns no fds. Kept in its own module so the broadcast
routing has a clear test surface separate from the TUI loop and the
orchestrator that wires everything together.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from csshx_latest.slave import Slave, write_to_slave

log = logging.getLogger(__name__)


@dataclass
class Broadcaster:
    """Routes bytes to enabled slaves."""

    slaves: list[Slave] = field(default_factory=list)

    def add(self, s: Slave) -> None:
        """Register a slave with the broadcaster."""
        self.slaves.append(s)

    def enabled_indices(self) -> list[int]:
        """Indices of slaves that currently receive broadcast bytes."""
        return [s.index for s in self.slaves if s.enabled and not s.dead]

    def alive_indices(self) -> list[int]:
        """Indices of slaves that are still connected (ssh hasn't exited)."""
        return [s.index for s in self.slaves if not s.dead]

    def toggle(self, index: int) -> bool:
        """Flip the ``enabled`` flag of the slave with the given index.

        Returns the new ``enabled`` value. Raises ``KeyError`` if no
        slave has that index.
        """
        for s in self.slaves:
            if s.index == index:
                s.enabled = not s.enabled
                return s.enabled
        raise KeyError(index)

    def set_all_enabled(self, enabled: bool) -> None:
        """Enable / disable broadcast to every (alive) slave at once."""
        for s in self.slaves:
            if not s.dead:
                s.enabled = enabled

    async def broadcast(self, data: bytes) -> None:
        """Write ``data`` to every enabled, alive slave concurrently.

        Per-slave failures are logged at WARNING -- they're treated as
        non-fatal because the dead-slave detection path will set
        ``dead=True`` and stop subsequent writes, but a silent failure
        here would otherwise leave the user wondering why a host stopped
        responding.
        """
        targets = [s for s in self.slaves if s.enabled and not s.dead]
        if not targets:
            return
        results = await asyncio.gather(
            *(write_to_slave(s, data) for s in targets),
            return_exceptions=True,
        )
        for slave, result in zip(targets, results):
            if isinstance(result, BaseException):
                log.warning("broadcast to slave %d (%s) failed: %r", slave.index, slave.host, result)
