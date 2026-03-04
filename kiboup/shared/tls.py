"""mTLS certificate management for kiboup.

Generates and manages a local CA, server certificates, and client
certificates using the ``cryptography`` library.  Certificates are
persisted to disk and automatically renewed when they approach
expiration.
"""

import datetime
import ipaddress
import logging
import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger("kiboup.tls")

_DEFAULT_CERTS_DIR = Path.home() / ".kiboserve" / "certs"
_CA_VALIDITY_DAYS = 3650
_CERT_VALIDITY_DAYS = 365
_RENEW_BEFORE_DAYS = 30
_KEY_SIZE = 2048


@dataclass
class MTLSConfig:
    """Configuration for mutual TLS.

    When all cert/key paths are ``None`` the library auto-generates
    and persists them under ``certs_dir``.

    Attributes:
        certs_dir: Directory for auto-generated certificates.
        ca_cert: Path to an existing CA certificate (disables auto-CA).
        ca_key: Path to an existing CA private key.
        server_cert: Path to an existing server certificate.
        server_key: Path to an existing server private key.
        client_cert: Path to an existing client certificate.
        client_key: Path to an existing client private key.
        hostname: SAN hostname for the server certificate.
        validity_days: Validity period for generated leaf certificates.
        renew_before_days: Renew a certificate when fewer than this
            many days remain before expiry.
    """

    certs_dir: Path = field(default_factory=lambda: _DEFAULT_CERTS_DIR)
    ca_cert: Optional[Path] = None
    ca_key: Optional[Path] = None
    server_cert: Optional[Path] = None
    server_key: Optional[Path] = None
    client_cert: Optional[Path] = None
    client_key: Optional[Path] = None
    hostname: str = "localhost"
    validity_days: int = _CERT_VALIDITY_DAYS
    renew_before_days: int = _RENEW_BEFORE_DAYS


class CertManager:
    """Generates, persists, and renews X.509 certificates for mTLS."""

    def __init__(self, config: MTLSConfig):
        self._cfg = config
        self._cfg.certs_dir.mkdir(parents=True, exist_ok=True)

    # -- public API -----------------------------------------------------------

    def ensure_ca(self) -> Tuple[Path, Path]:
        """Return (ca_cert_path, ca_key_path), generating if needed."""
        cert_path = self._cfg.ca_cert or self._cfg.certs_dir / "ca.crt"
        key_path = self._cfg.ca_key or self._cfg.certs_dir / "ca.key"

        if cert_path.exists() and key_path.exists():
            if not self._needs_renewal(cert_path):
                return cert_path, key_path
            logger.info("CA certificate approaching expiry, regenerating")

        key = self._generate_key()
        name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "KiboServe Internal CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KiboServe"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self._utc_now())
            .not_valid_after(self._utc_now() + datetime.timedelta(days=_CA_VALIDITY_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, key_cert_sign=True, crl_sign=True,
                    content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False,
                    encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        self._write_cert(cert_path, cert)
        self._write_key(key_path, key)
        logger.info("Generated CA certificate: %s", cert_path)
        return cert_path, key_path

    def ensure_server_cert(self) -> Tuple[Path, Path]:
        """Return (server_cert_path, server_key_path)."""
        cert_path = self._cfg.server_cert or self._cfg.certs_dir / "server.crt"
        key_path = self._cfg.server_key or self._cfg.certs_dir / "server.key"

        if cert_path.exists() and key_path.exists():
            if not self._needs_renewal(cert_path):
                return cert_path, key_path
            logger.info("Server certificate approaching expiry, regenerating")

        ca_cert_path, ca_key_path = self.ensure_ca()
        ca_key = self._load_key(ca_key_path)
        ca_cert = self._load_cert(ca_cert_path)

        key = self._generate_key()
        san = self._build_san(self._cfg.hostname)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, self._cfg.hostname),
            ]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self._utc_now())
            .not_valid_after(
                self._utc_now() + datetime.timedelta(days=self._cfg.validity_days),
            )
            .add_extension(san, critical=False)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, key_encipherment=True,
                    content_commitment=False, key_cert_sign=False,
                    crl_sign=False, data_encipherment=False,
                    key_agreement=False, encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        self._write_cert(cert_path, cert)
        self._write_key(key_path, key)
        logger.info("Generated server certificate: %s", cert_path)
        return cert_path, key_path

    def ensure_client_cert(self, client_name: str = "agent-client") -> Tuple[Path, Path]:
        """Return (client_cert_path, client_key_path)."""
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in client_name)
        cert_path = self._cfg.client_cert or self._cfg.certs_dir / f"{safe_name}.crt"
        key_path = self._cfg.client_key or self._cfg.certs_dir / f"{safe_name}.key"

        if cert_path.exists() and key_path.exists():
            if not self._needs_renewal(cert_path):
                return cert_path, key_path
            logger.info("Client certificate approaching expiry, regenerating")

        ca_cert_path, ca_key_path = self.ensure_ca()
        ca_key = self._load_key(ca_key_path)
        ca_cert = self._load_cert(ca_cert_path)

        key = self._generate_key()
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, client_name),
            ]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self._utc_now())
            .not_valid_after(
                self._utc_now() + datetime.timedelta(days=self._cfg.validity_days),
            )
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, key_encipherment=True,
                    content_commitment=False, key_cert_sign=False,
                    crl_sign=False, data_encipherment=False,
                    key_agreement=False, encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        self._write_cert(cert_path, cert)
        self._write_key(key_path, key)
        logger.info("Generated client certificate: %s", cert_path)
        return cert_path, key_path

    # -- helpers for server / client integration ------------------------------

    def server_ssl_kwargs(self) -> Dict[str, Any]:
        """Return kwargs suitable for ``uvicorn.run()``."""
        server_cert, server_key = self.ensure_server_cert()
        ca_cert, _ = self.ensure_ca()
        return {
            "ssl_certfile": str(server_cert),
            "ssl_keyfile": str(server_key),
            "ssl_ca_certs": str(ca_cert),
            "ssl_cert_reqs": ssl.CERT_REQUIRED,
        }

    def client_ssl_kwargs(self) -> Dict[str, Any]:
        """Return kwargs suitable for ``httpx.AsyncClient()``."""
        client_cert, client_key = self.ensure_client_cert()
        ca_cert, _ = self.ensure_ca()
        ctx = ssl.create_default_context(cafile=str(ca_cert))
        ctx.load_cert_chain(certfile=str(client_cert), keyfile=str(client_key))
        return {
            "verify": ctx,
        }

    # -- internal -------------------------------------------------------------

    @staticmethod
    def _utc_now() -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    @staticmethod
    def _generate_key() -> rsa.RSAPrivateKey:
        return rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)

    def _needs_renewal(self, cert_path: Path) -> bool:
        """Return True when the certificate expires within the renewal window."""
        cert = self._load_cert(cert_path)
        remaining = cert.not_valid_after_utc - self._utc_now()
        if remaining.days < self._cfg.renew_before_days:
            return True
        return False

    @staticmethod
    def _load_cert(path: Path) -> x509.Certificate:
        return x509.load_pem_x509_certificate(path.read_bytes())

    @staticmethod
    def _load_key(path: Path) -> rsa.RSAPrivateKey:
        return serialization.load_pem_private_key(path.read_bytes(), password=None)

    @staticmethod
    def _write_cert(path: Path, cert: x509.Certificate) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    @staticmethod
    def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        path.chmod(0o600)

    @staticmethod
    def _build_san(hostname: str) -> x509.SubjectAlternativeName:
        names: list = [x509.DNSName(hostname)]
        try:
            names.append(x509.IPAddress(ipaddress.IPv4Address(hostname)))
        except ValueError:
            pass
        if hostname == "localhost":
            names.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))
            names.append(x509.IPAddress(ipaddress.IPv6Address("::1")))
        return x509.SubjectAlternativeName(names)


def _resolve_mtls(mtls) -> Optional[CertManager]:
    """Normalize a ``mtls`` parameter into a ``CertManager`` or None.

    When ``mtls=True`` the environment variable ``KIBO_CERTS_DIR`` is
    checked to override the default certificate directory.
    """
    if mtls is None or mtls is False:
        return None
    if mtls is True:
        certs_dir = os.environ.get("KIBO_CERTS_DIR")
        config = MTLSConfig(certs_dir=Path(certs_dir)) if certs_dir else MTLSConfig()
        return CertManager(config)
    if isinstance(mtls, MTLSConfig):
        return CertManager(mtls)
    if isinstance(mtls, CertManager):
        return mtls
    raise TypeError(f"mtls must be bool, MTLSConfig, or CertManager, got {type(mtls)}")
