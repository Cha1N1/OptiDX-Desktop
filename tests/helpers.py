import struct


def pe_fixture(imports=("d3d12.dll",), bits=64):
    data = bytearray(2048)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664 if bits == 64 else 0x14C, 1)
    optional_size = 240 if bits == 64 else 224
    struct.pack_into("<H", data, 0x94, optional_size)
    struct.pack_into("<H", data, 0x98, 0x20B if bits == 64 else 0x10B)
    struct.pack_into(
        "<II", data, 0x98 + (112 if bits == 64 else 96) + 8, 0x1000, 20 * (len(imports) + 1)
    )
    section = 0x98 + optional_size
    struct.pack_into("<IIII", data, section + 8, 1024, 0x1000, 1024, 512)
    for i, name in enumerate(imports):
        offset = 768 + 64 * i
        struct.pack_into("<IIIII", data, 512 + 20 * i, 0, 0, 0, 0x1000 + offset - 512, 0)
        encoded = name.encode() + b"\0"
        data[offset : offset + len(encoded)] = encoded
    return bytes(data)


def wait_until(predicate, timeout=2000):
    """Pump Qt events until a state is reached; PySide6 does not expose qWaitFor."""
    import time
    from PySide6.QtTest import QTest

    end = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < end:
        QTest.qWait(10)
    return bool(predicate())
