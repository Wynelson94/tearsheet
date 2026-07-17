import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

_REAL_CONNECT = socket.socket.connect
_REAL_GETADDRINFO = socket.getaddrinfo


def _is_loopback(host: object) -> bool:
    return isinstance(host, str) and (
        host in ("localhost", "::1") or host.startswith("127.")
    )


@pytest.fixture(autouse=True)
def _no_remote_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Offline determinism is a guarantee, not a convention: any test that reaches for
    a non-loopback socket fails loudly. Loopback stays open (local test servers,
    playwright's browser transport). Opt out with @pytest.mark.live."""
    if request.node.get_closest_marker("live"):
        yield
        return

    def guarded_connect(self: socket.socket, address: object) -> None:
        if isinstance(address, (str, bytes)) or (
            isinstance(address, tuple) and _is_loopback(address[0])
        ):
            _REAL_CONNECT(self, address)  # type: ignore[arg-type]
            return
        raise RuntimeError(
            f"offline test attempted a network connection to {address!r} — "
            "mark it @pytest.mark.live if that is intentional"
        )

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if host is None or _is_loopback(host):
            return _REAL_GETADDRINFO(host, *args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError(
            f"offline test attempted a DNS lookup for {host!r} — "
            "mark it @pytest.mark.live if that is intentional"
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield


@pytest.fixture
def fixture_bytes():  # type: ignore[no-untyped-def]
    def load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()

    return load


@pytest.fixture
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Shared TEARSHEET_HOME isolation for new test files (file-local copies shadow this)."""
    home = tmp_path / "tearsheet-home"
    monkeypatch.setenv("TEARSHEET_HOME", str(home))
    return home


def build_pdf(text: str) -> bytes:
    """Assemble a minimal valid one-page PDF containing `text` (Helvetica, no deps)."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    ).encode()
    return bytes(out)


@pytest.fixture
def pdf_bytes() -> bytes:
    return build_pdf("Tearsheet PDF extraction works")
