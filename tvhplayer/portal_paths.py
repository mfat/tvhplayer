"""Display-only host path lookup for document-portal grants."""

import os


def document_host_path(doc_id):
    """Ask Documents v5; older portals and denied grants have no display path."""
    try:
        from PyQt6.QtCore import QMetaType
        from PyQt6.QtDBus import QDBusArgument, QDBusConnection, QDBusMessage
    except ImportError:
        return ''
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return ''
    ids = QDBusArgument()
    ids.beginArray(QMetaType.Type.QString.value)
    ids.add(doc_id)
    ids.endArray()
    message = QDBusMessage.createMethodCall(
        'org.freedesktop.portal.Documents', '/org/freedesktop/portal/documents',
        'org.freedesktop.portal.Documents', 'GetHostPaths')
    message.setArguments([ids])
    reply = bus.call(message, timeout=500)
    if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
        return ''
    paths = reply.arguments()[0]
    if not isinstance(paths, dict):
        return ''
    raw = paths.get(doc_id)
    if raw is None:
        return ''
    try:
        path = os.fsdecode(bytes(raw)).rstrip('\0')
    except (TypeError, ValueError):
        return ''
    return path if path.startswith('/') and '\0' not in path else ''
