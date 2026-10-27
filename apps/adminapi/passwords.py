"""
The old admin panel's password hash, so imported admins keep their passwords.

Dadehfa's PasswordHelper.HashPassword: Argon2id over the UTF-8 password with
salt = upper-case hex MD5 of the password, associated data = the user's
PublicKey, secret = the user's SecretKey; 1 iteration, 16 MB, 1 lane,
180-byte output, Base64. argon2-cffi's high-level API has no secret or
associated data, so this calls the reference implementation directly.
"""
from __future__ import annotations

import base64
import hashlib

from argon2.low_level import ARGON2_VERSION, Type, core, ffi, lib

OUT_LEN = 180


def _buffer(data: bytes):
    return (ffi.from_buffer(data) if data else ffi.NULL), len(data)


def legacy_hash(password: str, public_key: str, secret_key: str) -> str:
    pwd = password.encode()
    salt = hashlib.md5(pwd).hexdigest().upper().encode()
    out = ffi.new("uint8_t[]", OUT_LEN)
    keep = [pwd, salt, public_key.encode(), secret_key.encode()]  # alive until core() returns
    pwd_p, pwd_n = _buffer(keep[0])
    salt_p, salt_n = _buffer(keep[1])
    ad_p, ad_n = _buffer(keep[2])
    secret_p, secret_n = _buffer(keep[3])
    ctx = ffi.new("argon2_context *", {
        "out": out, "outlen": OUT_LEN,
        "pwd": pwd_p, "pwdlen": pwd_n,
        "salt": salt_p, "saltlen": salt_n,
        "secret": secret_p, "secretlen": secret_n,
        "ad": ad_p, "adlen": ad_n,
        "t_cost": 1, "m_cost": 16384, "lanes": 1, "threads": 1,
        "version": ARGON2_VERSION,
        "allocate_cbk": ffi.NULL, "free_cbk": ffi.NULL,
        "flags": lib.ARGON2_DEFAULT_FLAGS,
    })
    rc = core(ctx, Type.ID.value)
    if rc != lib.ARGON2_OK:
        raise ValueError(f"argon2 error {rc}")
    return base64.b64encode(bytes(ffi.buffer(out, OUT_LEN))).decode()
