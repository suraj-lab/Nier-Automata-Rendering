"""Decode the replay's existing tightly packed raw frame format."""
import struct

import numpy as np


_FORMATS_8BIT = {28, 29, 87, 91}


def decode_raw(data: bytes) -> np.ndarray:
    """Return an (height, width, 3) float32 RGB array from a raw frame."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) < 12:
        raise ValueError('invalid raw frame header')
    width, height, fmt = struct.unpack_from('<3I', data)
    if not width or not height:
        raise ValueError('raw frame dimensions must be nonzero')
    if fmt != 26 and fmt not in _FORMATS_8BIT:
        raise ValueError(f'unsupported raw frame format: {fmt}')
    expected = width * height * 4
    if len(data) != 12 + expected:
        raise ValueError('raw frame payload length mismatch')

    packed = np.frombuffer(data, dtype=np.uint8, offset=12).reshape(height, width, 4)
    if fmt in _FORMATS_8BIT:
        channels = packed[..., [2, 1, 0]] if fmt in (87, 91) else packed[..., :3]
        return channels.astype(np.float32) / np.float32(255)

    words = np.frombuffer(data, dtype='<u4', offset=12).reshape(height, width)

    def component(bits, shift, fraction_bits):
        field = (words >> shift) & ((1 << bits) - 1)
        mantissa = field & ((1 << fraction_bits) - 1)
        exponent = field >> fraction_bits
        values = np.ldexp(mantissa.astype(np.float64), -14 - fraction_bits)
        normal = np.ldexp(1.0 + mantissa.astype(np.float64) / (1 << fraction_bits),
                          exponent.astype(np.int32) - 15)
        values = np.where(exponent == 0, values, normal)
        values = np.where(exponent == 31,
                          np.where(mantissa == 0, np.inf, np.nan), values)
        return values.astype(np.float32)

    return np.stack((component(11, 0, 6), component(11, 11, 6),
                     component(10, 22, 5)), axis=-1)
