"""Nintendo U8 archives wrapped in Yaz0 (SZS).

This is deliberately narrow: files are parsed, validated, and rebuilt without
interpreting their payloads. Never modifies game assets implicitly.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import struct

MAGIC = b'\x55\xaa\x38\x2d'


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from('>I', data, offset)[0]


def pad(value: int, alignment: int = 32) -> int:
    return (value + alignment - 1) // alignment * alignment


def yaz0_decode(src: bytes) -> bytes:
    if src[:4] != b'Yaz0':
        raise ValueError('Expected Yaz0 header')
    expected = u32(src, 4)
    if expected > 256 * 1024 * 1024:
        raise ValueError('Uncompressed archive too large')
    out = bytearray()
    at = 16
    control = 0
    bits = 0
    while len(out) < expected:
        if not bits:
            if at >= len(src):
                raise ValueError('Truncated Yaz0 control stream')
            control = src[at]
            at += 1
            bits = 8
        if control & 0x80:
            if at >= len(src):
                raise ValueError('Truncated Yaz0 literal')
            out.append(src[at]); at += 1
        else:
            if at + 2 > len(src):
                raise ValueError('Truncated Yaz0 backreference')
            b0, b1 = src[at], src[at + 1]
            at += 2
            distance = ((b0 & 15) << 8) | b1
            count = b0 >> 4
            if count == 0:
                if at >= len(src):
                    raise ValueError('Truncated Yaz0 count')
                count = src[at] + 18
                at += 1
            else:
                count += 2
            source = len(out) - distance - 1
            if source < 0 or len(out) + count > expected:
                raise ValueError('Invalid Yaz0 reference')
            for _ in range(count):
                out.append(out[source]); source += 1
        control <<= 1
        bits -= 1
    return bytes(out)


def yaz0_encode(data: bytes) -> bytes:
    """Fast bounded-window LZ encoder. Round trips with Nintendo Yaz0 decoders."""
    out = bytearray(b'Yaz0' + struct.pack('>I', len(data)) + bytes(8))
    n = len(data)
    # Hash points to previous occurrences, retaining a small shortlist per key.
    seen: dict[bytes, list[int]] = {}
    at = 0

    def insert(pos: int) -> None:
        if pos + 3 > n:
            return
        key = data[pos:pos + 3]
        choices = seen.setdefault(key, [])
        choices.append(pos)
        if len(choices) > 24:
            del choices[:len(choices) - 24]

    while at < n:
        flag_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(7, -1, -1):
            if at == n:
                break
            best_size = 0
            best_dist = 0
            if at + 3 <= n:
                choices = seen.get(data[at:at + 3], [])
                for pos in reversed(choices):
                    dist = at - pos - 1
                    if dist > 4095:
                        continue
                    max_len = min(273, n - at)
                    length = 3
                    while length < max_len and data[pos + length] == data[at + length]:
                        length += 1
                    if length > best_size:
                        best_size, best_dist = length, dist
                        if best_size == max_len:
                            break
            if best_size >= 3:
                if best_size >= 18:
                    out.extend([(best_dist >> 8) & 0x0F, best_dist & 0xFF, best_size - 18])
                else:
                    out.extend([((best_size - 2) << 4) | (best_dist >> 8), best_dist & 0xFF])
                for j in range(best_size):
                    insert(at + j)
                at += best_size
            else:
                flags |= 1 << bit
                out.append(data[at])
                insert(at)
                at += 1
        out[flag_at] = flags
    return bytes(out)


@dataclass
class U8Archive:
    files: OrderedDict[str, bytes]
    compressed: bool = True
    original: bytes | None = None
    dirty: bool = False

    @classmethod
    def read(cls, src: bytes) -> 'U8Archive':
        compressed = src.startswith(b'Yaz0')
        data = yaz0_decode(src) if compressed else src
        if len(data) < 32 or data[:4] != MAGIC:
            raise ValueError('Not a Nintendo U8 archive')
        root = u32(data, 4)
        if root < 0x20 or root + 12 > len(data):
            raise ValueError('Invalid U8 node table')
        count = u32(data, root + 8)
        if not 1 <= count <= 50000 or root + count * 12 > len(data):
            raise ValueError('Invalid U8 node count')
        names_base = root + count * 12
        end_names = root + u32(data, 8)
        if not names_base <= end_names <= len(data):
            raise ValueError('Invalid U8 string table')
        stack: list[tuple[str, int]] = [('', count)]
        files: OrderedDict[str, bytes] = OrderedDict()
        if u32(data, root) >> 24 != 1:
            raise ValueError('U8 root must be a directory')
        for idx in range(1, count):
            raw_name, offset, size = struct.unpack_from('>III', data, root + idx * 12)
            is_dir = (raw_name >> 24) == 1
            if raw_name >> 24 not in (0, 1):
                raise ValueError('Invalid U8 node type')
            while stack and idx >= stack[-1][1]:
                stack.pop()
            if not stack:
                raise ValueError('Invalid U8 directory nesting')
            start = names_base + (raw_name & 0xFFFFFF)
            if start >= end_names:
                raise ValueError('Invalid U8 filename offset')
            term = data.find(b'\0', start, end_names)
            if term < 0:
                raise ValueError('Unterminated U8 filename')
            name = data[start:term].decode('utf-8')
            # MKWii archives commonly include a conventional '.' root directory.
            # Treat it as transparent rather than rejecting the entire SZS.
            if is_dir and name == '.':
                stack.append((stack[-1][0], size))
                continue
            if not name or name in ('.', '..') or '/' in name or '\\' in name:
                raise ValueError('Unsafe U8 filename')
            path = '/'.join(filter(None, (stack[-1][0], name)))
            if is_dir:
                if size <= idx or size > count:
                    raise ValueError('Invalid U8 directory end')
                stack.append((path, size))
            else:
                if offset < 0 or size < 0 or offset + size > len(data):
                    raise ValueError('Invalid U8 payload span')
                if path in files:
                    raise ValueError('Duplicate U8 filename')
                files[path] = bytes(data[offset:offset + size])
        return cls(files, compressed, src, False)

    @classmethod
    def from_file(cls, path: Path) -> 'U8Archive':
        return cls.read(path.read_bytes())

    def replace(self, name: str, payload: bytes) -> None:
        if name not in self.files:
            raise KeyError(f'Archive member not found: {name}')
        if self.files[name] != payload:
            self.files[name] = payload
            self.dirty = True

    def encode(self) -> bytes:
        if not self.dirty and self.original is not None:
            return self.original
        class Dir:
            def __init__(self, label: str, parent=None):
                self.label = label
                self.parent = parent
                self.children: OrderedDict[str, object] = OrderedDict()

        top = Dir('')
        for path in self.files:
            components = path.split('/')
            if any(p in ('', '.', '..') for p in components):
                raise ValueError('Unsafe U8 member name')
            cur = top
            for comp in components[:-1]:
                child = cur.children.get(comp)
                if child is None:
                    child = Dir(comp, cur)
                    cur.children[comp] = child
                if not isinstance(child, Dir):
                    raise ValueError('U8 path collision')
                cur = child
            if components[-1] in cur.children:
                raise ValueError('Duplicate U8 member')
            cur.children[components[-1]] = path

        nodes: list[tuple[int, str, int, int, str]] = []
        def walk(directory: Dir, parent_index: int, prefix: str = "") -> None:
            my_index = len(nodes)
            nodes.append((1, directory.label, parent_index, -1, prefix))
            for key, value in directory.children.items():
                if isinstance(value, Dir):
                    walk(value, my_index, f"{prefix}/{key}".strip("/"))
                else:
                    nodes.append((0, key, 0, 0, value))
            nodes[my_index] = (1, directory.label, parent_index, len(nodes), prefix)
        walk(top, 0)

        string_table = bytearray(b'\0')
        names: list[int] = [0]
        for _, label, _, _, _ in nodes[1:]:
            names.append(len(string_table))
            string_table.extend(label.encode('utf-8') + b'\0')
        root_offset = 0x20
        header_size = len(nodes) * 12 + len(string_table)
        data_offset = pad(root_offset + header_size)
        buffer = bytearray(data_offset)
        buffer[:4] = MAGIC
        struct.pack_into('>III', buffer, 4, root_offset, header_size, data_offset)
        buffer[root_offset + len(nodes) * 12:root_offset + header_size] = string_table
        for i, (kind, _, parent, end, _) in enumerate(nodes):
            if kind == 1:
                struct.pack_into('>III', buffer, root_offset + i * 12, (1 << 24) | names[i], parent, end)
                continue
        for i, (kind, _, _, _, path) in enumerate(nodes):
            if kind == 1:
                continue
            payload = self.files[path]
            while len(buffer) % 32:
                buffer.append(0)
            offset = len(buffer)
            buffer.extend(payload)
            struct.pack_into('>III', buffer, root_offset + i * 12, names[i], offset, len(payload))
        while len(buffer) % 32:
            buffer.append(0)
        return yaz0_encode(bytes(buffer)) if self.compressed else bytes(buffer)
