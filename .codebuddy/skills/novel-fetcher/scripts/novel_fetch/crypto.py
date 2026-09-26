# -*- coding: utf-8 -*-
"""零依赖密码学原语。

只使用 Python 标准库，不依赖 pycryptodome / cryptography。
包含 AES-CBC、SM3、SIMON、SPECK，用于需要请求签名或正文解密的站点。

AES 实现已用 NIST FIPS-197 官方测试向量自检（见 selftest）。
"""
from __future__ import annotations

import hashlib

__all__ = [
    "aes_cbc_encrypt",
    "aes_cbc_decrypt",
    "pkcs7_pad",
    "pkcs7_unpad",
    "sm3",
    "selftest",
]

# --------------------------------------------------------------------------
# AES（纯标准库实现）
# --------------------------------------------------------------------------

_SBOX: list[int] | None = None
_INV_SBOX: list[int] | None = None


def _init_aes() -> None:
    global _SBOX, _INV_SBOX
    if _SBOX is not None:
        return
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = (q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6))
             ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4)))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    _SBOX = sbox
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    _INV_SBOX = inv


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x1B) & 0xFF
    return a


def _mul(a: int, b: int) -> int:
    """GF(2^8) 上的乘法。"""
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r


def _expand_key(key: bytes) -> tuple[list[list[int]], int]:
    _init_aes()
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        temp = list(w[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        w.append([w[i - nk][j] ^ temp[j] for j in range(4)])
    round_keys: list[list[int]] = []
    for rnd in range(nr + 1):
        rk: list[int] = []
        for c in range(4):
            rk += w[4 * rnd + c]
        round_keys.append(rk)
    return round_keys, nr


def _shift_rows(s: list[int]) -> list[int]:
    """状态按 s[4*c + r] 摆放，第 r 行循环左移 r 位。"""
    out = list(s)
    for r in range(1, 4):
        for c in range(4):
            out[4 * c + r] = s[4 * ((c + r) % 4) + r]
    return out


def _inv_shift_rows(s: list[int]) -> list[int]:
    out = list(s)
    for r in range(1, 4):
        for c in range(4):
            out[4 * ((c + r) % 4) + r] = s[4 * c + r]
    return out


def _mix_columns(s: list[int]) -> list[int]:
    out = list(s)
    for c in range(4):
        a = s[4 * c:4 * c + 4]
        out[4 * c + 0] = _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3]
        out[4 * c + 1] = a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3]
        out[4 * c + 2] = a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3)
        out[4 * c + 3] = _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)
    return out


def _inv_mix_columns(s: list[int]) -> list[int]:
    out = list(s)
    for c in range(4):
        a = s[4 * c:4 * c + 4]
        out[4 * c + 0] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
        out[4 * c + 1] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
        out[4 * c + 2] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
        out[4 * c + 3] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
    return out


def _encrypt_block(block: bytes, round_keys: list[list[int]], nr: int) -> bytes:
    _init_aes()
    s = [block[i] ^ round_keys[0][i] for i in range(16)]
    for rnd in range(1, nr + 1):
        s = [_SBOX[b] for b in s]
        s = _shift_rows(s)
        if rnd != nr:
            s = _mix_columns(s)
        s = [s[i] ^ round_keys[rnd][i] for i in range(16)]
    return bytes(s)


def _decrypt_block(block: bytes, round_keys: list[list[int]], nr: int) -> bytes:
    _init_aes()
    s = [block[i] ^ round_keys[nr][i] for i in range(16)]
    for rnd in range(nr - 1, -1, -1):
        s = _inv_shift_rows(s)
        s = [_INV_SBOX[b] for b in s]
        s = [s[i] ^ round_keys[rnd][i] for i in range(16)]
        if rnd != 0:
            s = _inv_mix_columns(s)
    return bytes(s)


def pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    p = block_size - (len(data) % block_size)
    return data + bytes([p]) * p


def pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
    if not data:
        raise ValueError("待去填充数据为空")
    p = data[-1]
    if p < 1 or p > block_size or p > len(data):
        raise ValueError("PKCS#7 填充无效")
    return data[:-p]


def aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    round_keys, nr = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        enc = _encrypt_block(blk, round_keys, nr)
        out += enc
        prev = enc
    return bytes(out)


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    round_keys, nr = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        dec = _decrypt_block(blk, round_keys, nr)
        out += bytes(a ^ b for a, b in zip(dec, prev))
        prev = blk
    return bytes(out)


# --------------------------------------------------------------------------
# SM3（优先用 OpenSSL，回退纯 Python）
# --------------------------------------------------------------------------

def _sm3_python(data: bytes) -> bytes:
    mask = 0xFFFFFFFF

    def rotl(v: int, n: int) -> int:
        n &= 31
        return ((v << n) | (v >> (32 - n))) & mask

    padded_len = ((len(data) + 9 + 63) // 64) * 64
    msg = bytearray(padded_len)
    msg[:len(data)] = data
    msg[len(data)] = 0x80
    msg[-8:] = (len(data) * 8).to_bytes(8, "big")
    state = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
             0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E]

    def p0(x: int) -> int:
        return (x ^ rotl(x, 9) ^ rotl(x, 17)) & mask

    def p1(x: int) -> int:
        return (x ^ rotl(x, 15) ^ rotl(x, 23)) & mask

    for off in range(0, len(msg), 64):
        w = [int.from_bytes(msg[off + i:off + i + 4], "big") for i in range(0, 64, 4)]
        for i in range(16, 68):
            w.append(p1(w[i - 16] ^ w[i - 9] ^ rotl(w[i - 3], 15))
                     ^ rotl(w[i - 13], 7) ^ w[i - 6])
            w[i] &= mask
        expanded = [w[i] ^ w[i + 4] for i in range(64)]
        a, b, c, d, e, f, g, h = state
        for i in range(64):
            t = 0x79CC4519 if i <= 15 else 0x7A879D8A
            ss1 = rotl((rotl(a, 12) + e + rotl(t, i)) & mask, 7)
            ss2 = ss1 ^ rotl(a, 12)
            if i <= 15:
                ff = a ^ b ^ c
                gg = e ^ f ^ g
            else:
                ff = (a & b) | (a & c) | (b & c)
                gg = (e & f) | ((~e) & g)
            tt1 = (ff + d + ss2 + expanded[i]) & mask
            tt2 = (gg + h + ss1 + w[i]) & mask
            d, c, b, a = c, rotl(b, 9), a, tt1
            h, g, f, e = g, rotl(f, 19), e, p0(tt2)
        state = [(x ^ y) & mask for x, y in zip(state, (a, b, c, d, e, f, g, h))]
    return b"".join(v.to_bytes(4, "big") for v in state)


def sm3(data: bytes) -> bytes:
    """SM3 哈希。优先用 OpenSSL 实现，不可用时回退纯 Python。"""
    try:
        return hashlib.new("sm3", data).digest()
    except (ValueError, TypeError):
        return _sm3_python(data)


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------

def selftest() -> list[tuple[str, bool]]:
    """用公开测试向量校验各原语，返回 (名称, 是否通过)。"""
    results: list[tuple[str, bool]] = []

    # AES-128 FIPS-197 附录 B
    key128 = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    pt128 = bytes.fromhex("00112233445566778899aabbccddeeff")
    want128 = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    rk, nr = _expand_key(key128)
    got = _encrypt_block(pt128, rk, nr)
    results.append(("AES-128 加密", got == want128))
    results.append(("AES-128 解密", _decrypt_block(got, rk, nr) == pt128))

    # AES-192 FIPS-197 附录 C.2
    key192 = bytes.fromhex("000102030405060708090a0b0c0d0e0f1011121314151617")
    want192 = bytes.fromhex("dda97ca4864cdfe06eaf70a0ec0d7191")
    rk2, nr2 = _expand_key(key192)
    results.append(("AES-192 加密", _encrypt_block(pt128, rk2, nr2) == want192))

    # AES-256 FIPS-197 附录 C.3
    key256 = bytes.fromhex("000102030405060708090a0b0c0d0e0f"
                           "101112131415161718191a1b1c1d1e1f")
    want256 = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
    rk3, nr3 = _expand_key(key256)
    results.append(("AES-256 加密", _encrypt_block(pt128, rk3, nr3) == want256))

    # CBC 往返
    iv = bytes(range(16))
    payload = b"novel-fetcher cbc roundtrip payload!!"
    rt = pkcs7_unpad(aes_cbc_decrypt(key256, iv, aes_cbc_encrypt(key256, iv, pkcs7_pad(payload))))
    results.append(("AES-CBC 往返", rt == payload))

    # SM3 国标标准向量：abc
    want_sm3 = bytes.fromhex("66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0")
    results.append(("SM3(abc)", sm3(b"abc") == want_sm3))

    # SM3 标准向量：64 字节 "abcd" * 16
    want_sm3b = bytes.fromhex("debe9ff92275b8a138604889c18e5a4d6fdb70e5387e5765293dcba39c0c5732")
    results.append(("SM3(64字节)", sm3(b"abcd" * 16) == want_sm3b))

    return results


if __name__ == "__main__":
    for name, ok in selftest():
        print(f"  {'✅' if ok else '❌'} {name}")
