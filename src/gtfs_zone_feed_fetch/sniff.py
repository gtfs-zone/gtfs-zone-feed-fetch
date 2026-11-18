"""What a downloaded body is, from its first bytes."""


def sniff(head: bytes) -> str:
    """zip, empty, html, json, xml or unknown."""
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    head = head[:512].lstrip().lower()
    if not head:
        return "empty"
    if head.startswith((b"<!doctype html", b"<html")) or b"<html" in head:
        return "html"
    if head.startswith((b"{", b"[")):
        return "json"
    if head.startswith(b"<"):
        return "xml"
    return "unknown"
