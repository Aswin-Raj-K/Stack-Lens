"""J-Link memory reader and ELF symbol loader."""

import struct

import pylink
from elftools.elf.elffile import ELFFile


# Must match trace.cpp
TRACE_BUFFER_SIZE = 131072
TRACE_EVENT_SIZE = 12  # bytes per TraceEvent

# TraceEvent layout (little-endian, 12 bytes total):
#   uint8_t  type       offset 0  (0=enter, 1=exit, 2=mark)
#   uint8_t  ipsr       offset 1  (0=thread mode, nonzero=ISR number)
#   uint8_t  _pad[2]    offset 2
#   uint32_t cyccnt     offset 4
#   uint32_t context    offset 8  (func_addr for 0/1, string literal ptr for 2)
EVENT_FMT = "<BBxxII"


def connect_jlink(device):
    jlink = pylink.JLink()
    jlink.open()
    jlink.set_tif(pylink.enums.JLinkInterfaces.SWD)
    jlink.connect(device)
    print(f"Connected to {device} (core: {jlink.core_name()})")
    return jlink


def load_elf_symbols(elf_path):
    """Return (name->addr, addr->name) dicts from the ELF symbol table."""
    name_to_addr = {}
    addr_to_name = {}

    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            raise RuntimeError("ELF has no .symtab — was it stripped?")

        for sym in symtab.iter_symbols():
            name = sym.name
            addr = sym["st_value"]
            sym_type = sym["st_info"]["type"]

            if name:
                name_to_addr[name] = addr

            if sym_type == "STT_FUNC":
                addr_to_name[addr] = name
                addr_to_name[addr & ~1] = name  # Thumb bit

    return name_to_addr, addr_to_name


# ── ELF string literal resolver ──────────────────────────────────────
# Used by the mark-event renderer to turn a `const char *` pointer captured
# in the ring buffer into the actual string by walking ELF sections.

_elf_section_cache = {}  # {elf_path: [(sh_addr, sh_end, data_bytes), ...]}
_elf_string_cache = {}   # {(elf_path, addr): str}


def _load_elf_sections(elf_path):
    if elf_path in _elf_section_cache:
        return _elf_section_cache[elf_path]
    ranges = []
    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            sh_addr = sec["sh_addr"]
            sh_size = sec["sh_size"]
            if sh_addr == 0 or sh_size == 0:
                continue
            try:
                data = sec.data()
            except Exception:
                continue
            ranges.append((sh_addr, sh_addr + sh_size, data))
    _elf_section_cache[elf_path] = ranges
    return ranges


def read_elf_string(elf_path, addr, max_len=256):
    """Resolve a pointer captured at runtime to the string literal in the ELF.

    Walks loadable ELF sections, finds the one containing ``addr``, and reads
    bytes until a null terminator or ``max_len``. Falls back to a hex repr
    when the address doesn't match any section.
    """
    if not elf_path:
        return f"<0x{addr:08X}>"
    key = (elf_path, addr)
    if key in _elf_string_cache:
        return _elf_string_cache[key]
    result = f"<0x{addr:08X}>"
    try:
        for lo, hi, data in _load_elf_sections(elf_path):
            if lo <= addr < hi:
                offset = addr - lo
                end_limit = min(offset + max_len, len(data))
                null_pos = data.find(b"\x00", offset, end_limit)
                end = null_pos if null_pos != -1 else end_limit
                try:
                    result = data[offset:end].decode("utf-8", errors="replace")
                except Exception:
                    result = f"<0x{addr:08X}>"
                break
    except Exception:
        pass
    _elf_string_cache[key] = result
    return result


def read_trace(jlink, name_to_addr):
    """Read trace_idx and trace_buf from the live target. Returns (raw_buf, trace_idx)."""
    trace_idx_addr = name_to_addr.get("trace_idx")
    trace_buf_addr = name_to_addr.get("trace_buf")

    if trace_buf_addr is None or trace_idx_addr is None:
        raise RuntimeError(
            "Could not find trace_buf / trace_idx symbols in ELF. "
            "Make sure trace.cpp is linked."
        )

    raw_idx = bytes(jlink.memory_read(trace_idx_addr, 4))
    trace_idx = struct.unpack("<I", raw_idx)[0]

    raw_buf = bytes(jlink.memory_read(trace_buf_addr, TRACE_BUFFER_SIZE * TRACE_EVENT_SIZE))

    return raw_buf, trace_idx
