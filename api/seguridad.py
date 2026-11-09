"""Contraseñas y tokens de sesión, solo con la biblioteca estándar."""

import hashlib
import hmac
import secrets

ALGORITMO = "pbkdf2_sha256"
# Recomendación OWASP para PBKDF2-SHA256. Las pruebas la bajan con VOLANTE_ITERACIONES para ir
# rápido; como el número se guarda con cada contraseña, cambiarlo no invalida las antiguas.
ITERACIONES = 600_000


def cifrar_contrasena(contrasena, iteraciones=None):
    iteraciones = iteraciones or ITERACIONES
    sal = secrets.token_bytes(16)
    resumen = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), sal, iteraciones)
    return f"{ALGORITMO}${iteraciones}${sal.hex()}${resumen.hex()}"


def comprobar_contrasena(contrasena, guardado):
    try:
        algoritmo, iteraciones, sal, resumen = guardado.split("$")
        calculado = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), bytes.fromhex(sal), int(iteraciones))
    except (ValueError, AttributeError):
        return False
    return algoritmo == ALGORITMO and hmac.compare_digest(calculado.hex(), resumen)


def nuevo_token():
    return secrets.token_urlsafe(32)


def huella_token(token):
    """Lo que se guarda en la base: la huella del token, nunca el token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_senuelo = None


def hash_senuelo():
    """Resumen falso para usuarios que no existen: así tardan lo mismo que una contraseña mal puesta."""
    global _senuelo
    if _senuelo is None:
        _senuelo = cifrar_contrasena(secrets.token_hex(16))
    return _senuelo
