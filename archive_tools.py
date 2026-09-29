"""Sogou skin ZIP rewriting; Python 3.6+, standard library only."""
import io
import struct
import zlib
from zipfile import ZipFile, ZipInfo

PAD = 'ime/custom-padding.bin'


def build(source, replacements):
    """Recompress a local vendor ZIP and add an overlay, preserving its envelope.

    No vendor resources are embedded in this module. Local/central extra fields
    are preserved independently; they need not be identical in the source ZIP.
    """
    if len(source) < 50 or source[-22:-18] != b'PK\x05\x06':
        raise ValueError('Unsupported ZIP ending')
    tail = bytearray(source[-22:])
    if any(struct.unpack_from('<HH', tail, 4)) or struct.unpack_from('<H', tail, 20)[0]:
        raise ValueError('Split/commented ZIP unsupported')
    cd = struct.unpack_from('<I', tail, 16)[0]
    local, central = bytearray(), []

    def append_record(head, entry, data, method):
        if method == 8:
            compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
            packed = compressor.compress(data) + compressor.flush()
        else:
            packed = data
        crc = zlib.crc32(data) & 0xffffffff
        struct.pack_into('<H', head, 8, method)
        struct.pack_into('<III', head, 14, crc, len(packed), len(data))
        struct.pack_into('<H', entry, 10, method)
        struct.pack_into('<III', entry, 16, crc, len(packed), len(data))
        struct.pack_into('<I', entry, 42, len(local))
        local.extend(head + packed)
        central.append(entry)

    def append_new(name, data, method):
        # zipfile creates the header, flags and UTF-8 filename; no extraction.
        buf = io.BytesIO()
        with ZipFile(buf, 'w') as single:
            single.writestr(ZipInfo(name), b'')
        raw = buf.getvalue()
        offset = struct.unpack_from('<I', raw, len(raw) - 6)[0]
        append_record(bytearray(raw[:offset]), bytearray(raw[offset:-22]), data, method)

    with ZipFile(io.BytesIO(source)) as old:
        infos = old.infolist()
        names = old.namelist()
        if not infos or len(set(names)) != len(names) or PAD in names or PAD in replacements:
            raise ValueError('Duplicate entries, existing padding, or empty source')
        if infos[0].header_offset != 0 or infos[0].filename in replacements:
            raise ValueError('First native ZIP record must remain unchanged')
        at = cd
        for index, info in enumerate(infos):
            if info.flag_bits & 9 or info.compress_type not in (0, 8):
                raise ValueError('Encrypted/descriptor/unknown compression ZIP unsupported')
            if source[at:at + 4] != b'PK\x01\x02':
                raise ValueError('Bad central directory')
            n, e, c = struct.unpack_from('<HHH', source, at + 28)
            entry = bytearray(source[at:at + 46 + n + e + c])
            at += len(entry)
            start = info.header_offset
            n, e = struct.unpack_from('<HH', source, start + 26)
            head = bytearray(source[start:start + 30 + n + e])
            if index == 0:
                stop = infos[1].header_offset if len(infos) > 1 else cd
                local.extend(source[start:stop])
                central.append(entry)
            else:
                append_record(head, entry, replacements.get(info.filename, old.read(info)), 8)
        if at != len(source) - 22:
            raise ValueError('ZIP64/trailing data unsupported')
        for name in sorted(set(replacements) - set(names)):
            append_new(name, replacements[name], 8)
        overhead = 76 + 2 * len(PAD.encode('utf-8'))
        gap = len(source) - len(local) - sum(len(e) for e in central) - 22 - overhead
        if gap < 0:
            raise ValueError('Overlay exceeds ZIP size budget; keep large images outside the ZIP')
        append_new(PAD, b'\0' * gap, 0)
        if len(central) >= 65535:
            raise ValueError('ZIP64 unsupported')
        directory = b''.join(central)
        struct.pack_into('<HHII', tail, 8, len(central), len(central), len(directory), len(local))
        result = bytes(local) + directory + bytes(tail)
        if result[:50] != source[:50] or len(result) != len(source):
            raise ValueError('Native fingerprint changed')
        with ZipFile(io.BytesIO(result)) as final:
            if final.testzip() is not None:
                raise ValueError('Generated ZIP failed CRC validation')
            for name in names:
                if final.read(name) != replacements.get(name, old.read(name)):
                    raise ValueError('Member content changed unexpectedly: ' + name)
        return result


def rewrite(source, replacements):
    """Preserve native fingerprint, unrelated compressed members and ZIP extras."""
    end = bytearray(source[-22:])
    if end[:4] != b'PK\x05\x06' or struct.unpack_from('<H', end, 20)[0]:
        raise ValueError('Unsupported ZIP ending/comment')
    cd = struct.unpack_from('<I', end, 16)[0]
    with ZipFile(io.BytesIO(source)) as z:
        infos = z.infolist()
        if infos[-1].filename != PAD:
            raise ValueError('Expected final padding member')
        if not set(replacements).issubset(set(z.namelist())):
            raise ValueError('Replacement member missing')
        central = []
        at = cd
        for info in infos:
            if source[at:at + 4] != b'PK\x01\x02':
                raise ValueError('Bad central directory')
            n, e, c = struct.unpack_from('<HHH', source, at + 28)
            central.append(bytearray(source[at:at + 46 + n + e + c]))
            at += 46 + n + e + c
        if at != len(source) - 22:
            raise ValueError('Unsupported ZIP trailing data')

        def assemble(pad_size):
            local = bytearray()
            entries = []
            for index, info in enumerate(infos):
                if info.flag_bits & 9:
                    raise ValueError('Encrypted/descriptor ZIP unsupported')
                start = info.header_offset
                stop = infos[index + 1].header_offset if index + 1 < len(infos) else cd
                record = bytearray(source[start:stop])
                entry = bytearray(central[index])
                struct.pack_into('<I', entry, 42, len(local))
                if info.filename in replacements or info.filename == PAD:
                    data = b'\0' * pad_size if info.filename == PAD else replacements[info.filename]
                    n, e = struct.unpack_from('<HH', record, 26)
                    head = record[:30 + n + e]
                    if info.compress_type == 0:
                        compressed = data
                    elif info.compress_type == 8:
                        compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
                        compressed = compressor.compress(data) + compressor.flush()
                    else:
                        raise ValueError('Unsupported compression')
                    crc = zlib.crc32(data) & 0xffffffff
                    struct.pack_into('<III', head, 14, crc, len(compressed), len(data))
                    struct.pack_into('<III', entry, 16, crc, len(compressed), len(data))
                    record = head + compressed
                local.extend(record)
                entries.append(entry)
            central_bytes = b''.join(entries)
            tail = bytearray(end)
            struct.pack_into('<II', tail, 12, len(central_bytes), len(local))
            return bytes(local) + central_bytes + bytes(tail)

        short = assemble(0)
        gap = len(source) - len(short)
        if gap < 0:
            raise ValueError('Paths exceed skin padding budget; use a shorter home path')
        result = assemble(gap)
        if len(result) != len(source) or result[:50] != source[:50]:
            raise ValueError('Native fingerprint changed')
        with ZipFile(io.BytesIO(result)) as final:
            if final.testzip() is not None or final.namelist() != z.namelist():
                raise ValueError('ZIP integrity check failed')
            for name in z.namelist():
                if name not in replacements and name != PAD and final.read(name) != z.read(name):
                    raise ValueError('Unrelated member changed: ' + name)
        return result
