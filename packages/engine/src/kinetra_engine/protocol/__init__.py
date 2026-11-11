"""The document subscription and command channel (C-05a): `client-adapter.md` 3.1 and 3.2 over WebSocket.

The messages are `kinetra_core.protocol`. `Document` is the owner of one project (revision, history, verdict state);
`Hub` puts documents on a WebSocket and is the one way into a document from inside the process (`Hub.publish`).
"""

from .document import Document, Outcome, refuse_unsubscribed
from .server import Hub

__all__ = ["Document", "Hub", "Outcome", "refuse_unsubscribed"]
