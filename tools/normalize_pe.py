"""Make a .NET Framework executable built by the in-box compiler reproducible.

The in-box csc.exe (C# 5, .NET Framework 4.8) has no /deterministic switch. Two builds
of the same source differ in exactly two places, measured by diffing them byte for byte:

  * the COFF header's TimeDateStamp - the wall-clock second the compiler ran;
  * the module's MVID - a fresh random GUID in the #GUID metadata heap.

Everything else - IL, metadata, resources, the icon, the manifest - is already a pure
function of the source. So this does what Roslyn's /deterministic does, after the fact:
the timestamp becomes a fixed value and the MVID becomes a GUID derived from a hash of
the module with both fields zeroed. The result depends only on what was compiled.

The fields are located by parsing the PE and CLI metadata structures, never by searching
for byte patterns, and every step is checked: a file this does not understand exactly is
refused rather than edited.

Copied unchanged but for this paragraph from Codex Auto Resume's build/normalize_pe.py
(https://github.com/songyb111-gachon/codex-auto-resume-windows), which builds the product's own window
the same way: the same owner, under the same MIT licence. tools/make_exe.py runs it on Report.exe.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

# Not zero: some tools treat a zero timestamp as "unset". Any constant works; this one is
# the first second of 2000-01-01 UTC, which cannot be mistaken for a real build time.
FIXED_TIMESTAMP = 946684800


class NotNormalisable(ValueError):
    """The file is not a PE/CLI image this code fully understands."""


def _u16(b, o): return struct.unpack_from("<H", b, o)[0]
def _u32(b, o): return struct.unpack_from("<I", b, o)[0]


def _sections(data, pe):
    count = _u16(data, pe + 6)
    optional = _u16(data, pe + 20)
    table = pe + 24 + optional
    out = []
    for i in range(count):
        base = table + 40 * i
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, base + 8)
        out.append((vaddr, max(vsize, rsize), raddr))
    return out


def _rva_to_offset(sections, rva):
    for vaddr, size, raddr in sections:
        if vaddr <= rva < vaddr + size:
            return raddr + (rva - vaddr)
    raise NotNormalisable("RVA 0x%x is outside every section" % rva)


def locate(data: bytes) -> dict:
    """Find the two nondeterministic fields. Returns their file offsets."""
    if data[:2] != b"MZ":
        raise NotNormalisable("not an MZ image")
    pe = _u32(data, 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        raise NotNormalisable("no PE signature")
    magic = _u16(data, pe + 24)
    if magic == 0x20B:           # PE32+
        directories = pe + 24 + 112
    elif magic == 0x10B:         # PE32
        directories = pe + 24 + 96
    else:
        raise NotNormalisable("unknown optional header magic 0x%x" % magic)
    sections = _sections(data, pe)

    # Directory 6 is the debug directory. A debug entry carries its own timestamp and,
    # for a PDB, a GUID - more nondeterminism. This build emits none; refuse if one
    # appears rather than silently leaving a varying field behind.
    debug_rva, debug_size = struct.unpack_from("<II", data, directories + 6 * 8)
    if debug_size:
        raise NotNormalisable("image has a debug directory; build without /debug")

    cli_rva, cli_size = struct.unpack_from("<II", data, directories + 14 * 8)
    if not cli_rva:
        raise NotNormalisable("not a CLI image")
    cli = _rva_to_offset(sections, cli_rva)
    meta_rva, _meta_size = struct.unpack_from("<II", data, cli + 8)
    meta = _rva_to_offset(sections, meta_rva)
    if _u32(data, meta) != 0x424A5342:     # "BSJB"
        raise NotNormalisable("no CLI metadata signature")
    version_length = _u32(data, meta + 12)
    cursor = meta + 16 + version_length
    stream_count = _u16(data, cursor + 2)
    cursor += 4
    streams = {}
    for _ in range(stream_count):
        offset, size = struct.unpack_from("<II", data, cursor)
        end = data.index(b"\0", cursor + 8)
        name = data[cursor + 8:end].decode("ascii")
        streams[name] = (meta + offset, size)
        cursor = (end + 4) & ~3          # names are padded to a 4-byte boundary
    if "#GUID" not in streams:
        raise NotNormalisable("no #GUID heap")
    tables = streams.get("#~") or streams.get("#-")
    if not tables:
        raise NotNormalisable("no metadata table stream")
    # A third varying field, which this cannot fix: for a string switch with enough cases, or
    # a constant array initializer, the compiler emits a class named
    # "<PrivateImplementationDetails>{GUID}" with a fresh random GUID. Deriving that name from
    # the content would mean renaming a type, so the image is refused instead - the build
    # fails where it is made, rather than in the release run that compares two builds.
    strings = streams.get("#Strings")
    if strings and b"<PrivateImplementationDetails>{" in data[strings[0]:strings[0] + strings[1]]:
        raise NotNormalisable(
            "image contains <PrivateImplementationDetails>{GUID}, a class the compiler names at "
            "random; rewrite the string switch or constant array initializer that produced it")

    # The Module table (0x00) always has exactly one row, and it is always the first
    # table present. Its row is: Generation (u16), Name (string index), Mvid (GUID index),
    # EncId, EncBaseId. Index widths depend on HeapSizes.
    start, _ = tables
    heap_sizes = data[start + 6]
    valid = struct.unpack_from("<Q", data, start + 8)[0]
    if not valid & 1:
        raise NotNormalisable("no Module table")
    present = bin(valid).count("1")
    rows = start + 24 + 4 * present
    string_width = 4 if heap_sizes & 0x01 else 2
    guid_width = 4 if heap_sizes & 0x02 else 2
    if _u32(data, start + 24) != 1:
        raise NotNormalisable("Module table does not have exactly one row")
    mvid_field = rows + 2 + string_width
    mvid_index = (_u32 if guid_width == 4 else _u16)(data, mvid_field)
    if mvid_index < 1:
        raise NotNormalisable("Module has no MVID")
    guid_heap, guid_size = streams["#GUID"]
    mvid = guid_heap + 16 * (mvid_index - 1)
    if mvid + 16 > guid_heap + guid_size:
        raise NotNormalisable("MVID index outside the #GUID heap")

    return {"timestamp": pe + 8, "mvid": mvid, "checksum": pe + 24 + 64}


def normalise(data: bytes) -> bytes:
    offsets = locate(data)
    image = bytearray(data)
    if _u32(image, offsets["checksum"]) != 0:
        # A non-zero checksum would have to be recomputed after editing. csc writes
        # zero; anything else means this is not the file this was written for.
        raise NotNormalisable("image carries a PE checksum")
    struct.pack_into("<I", image, offsets["timestamp"], 0)
    image[offsets["mvid"]:offsets["mvid"] + 16] = bytes(16)
    digest = hashlib.sha256(bytes(image)).digest()
    # A version-4-shaped GUID from the content hash, like Roslyn's deterministic MVID.
    guid = bytearray(digest[:16])
    guid[7] = (guid[7] & 0x0F) | 0x40
    guid[8] = (guid[8] & 0x3F) | 0x80
    image[offsets["mvid"]:offsets["mvid"] + 16] = guid
    struct.pack_into("<I", image, offsets["timestamp"], FIXED_TIMESTAMP)
    return bytes(image)


def normalise_file(path: Path) -> str:
    path = Path(path)
    before = path.read_bytes()
    after = normalise(before)
    # Idempotent by construction: normalising a normalised file changes nothing.
    if normalise(after) != after:
        raise NotNormalisable("normalisation is not idempotent for %s" % path.name)
    path.write_bytes(after)
    return hashlib.sha256(after).hexdigest()


if __name__ == "__main__":
    import sys
    for name in sys.argv[1:]:
        print(normalise_file(Path(name)), name)
