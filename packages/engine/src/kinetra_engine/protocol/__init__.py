"""The document subscription and command channel (C-05a): `client-adapter.md` 3.1 and 3.2 over WebSocket.

The messages are `kinetra_core.protocol`. `Document` is the owner of one project (revision, history, verdict state);
`Hub` puts documents on a WebSocket and is the one way into a document from inside the process (`Hub.publish`).
`ReferenceClient` (C-05c) is the headless client that speaks only the protocol; `conformance` is the suite every client
must pass.
"""

from .client import CoreError, ProtocolViolation, ReferenceClient, RunRecord
from .document import Document, Outcome, refuse_unsubscribed
from .server import Hub

__all__ = ["CoreError", "Document", "Hub", "Outcome", "ProtocolViolation", "ReferenceClient", "RunRecord", "refuse_unsubscribed"]
