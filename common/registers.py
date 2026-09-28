"""
GreenGauge Modbus register map, shared by the meter emulator and the gateway.

All values are holding registers (function code 3), 0-based addresses,
big-endian with the high word first: the most common layout on industrial meters.

addr  name          type     notes
----  ------------  -------  ---------------------------------------------
 0    timestamp     uint32   meter clock, unix seconds
 2    kw            float32  active power
 4    kvar          float32  reactive power
 6    kva           float32  apparent power
 8    pf            float32  power factor
10    voltage       float32  line-to-line volts
12    ia            float32  phase A current
14    ib            float32  phase B current
16    ic            float32  phase C current
18    energy_wh     uint32   cumulative active energy, Wh
20    status        uint16   0 off, 1 idle, 2 running           (machine meters)
21    loaded_s      uint16   seconds loaded in the last minute  (compressor only)
22    pieces_total  uint32   production pulse counter           (incomer only)
24    ambient_c     float32  ambient temperature                (incomer only)
26    shift         uint16   0 none, 1 A, 2 B                   (incomer only)
27    producing     uint16   1 if the line is producing         (incomer only)
"""
import struct

N_REGISTERS = 28
STATUS_CODES = {"off": 0, "idle": 1, "running": 2}
STATUS_NAMES = {v: k for k, v in STATUS_CODES.items()}
SHIFT_CODES = {"": 0, "A": 1, "B": 2}
SHIFT_NAMES = {v: k for k, v in SHIFT_CODES.items()}

# (name, address, type)
FIELDS = [
    ("timestamp", 0, "u32"),
    ("kw", 2, "f32"), ("kvar", 4, "f32"), ("kva", 6, "f32"), ("pf", 8, "f32"),
    ("voltage", 10, "f32"), ("ia", 12, "f32"), ("ib", 14, "f32"), ("ic", 16, "f32"),
    ("energy_wh", 18, "u32"),
    ("status", 20, "u16"), ("loaded_s", 21, "u16"),
    ("pieces_total", 22, "u32"),
    ("ambient_c", 24, "f32"),
    ("shift", 26, "u16"), ("producing", 27, "u16"),
]


def _words(fmt: str, value) -> list[int]:
    b = struct.pack(">" + fmt, value)
    return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2)]


def encode(values: dict) -> list[int]:
    """dict of field values -> list of 28 register words (missing fields = 0)."""
    regs = [0] * N_REGISTERS
    for name, addr, typ in FIELDS:
        v = values.get(name, 0) or 0
        if typ == "f32":
            w = _words("f", float(v))
        elif typ == "u32":
            w = _words("I", int(v) & 0xFFFFFFFF)
        else:
            w = [int(v) & 0xFFFF]
        regs[addr:addr + len(w)] = w
    return regs


def decode(regs: list[int]) -> dict:
    """list of 28 register words -> dict of field values."""
    out = {}
    for name, addr, typ in FIELDS:
        if typ == "u16":
            out[name] = regs[addr]
            continue
        b = regs[addr].to_bytes(2, "big") + regs[addr + 1].to_bytes(2, "big")
        out[name] = struct.unpack(">f" if typ == "f32" else ">I", b)[0]
    return out
