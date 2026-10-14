"""Conservative BMG editor for RR's CharaRR.bmg (UTF-16BE messages).

Preserves unrelated messages as raw bytes, message metadata, message IDs,
original header, and unknown sections. Only the changed text or IDs are rebuilt.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct


def be16(data, at): return struct.unpack_from('>H', data, at)[0]
def be32(data, at): return struct.unpack_from('>I', data, at)[0]
def align32(data: bytes | bytearray) -> bytes:
    return bytes(data) + b'\0' * (-len(data) % 32)


@dataclass
class Message:
    id: int
    raw: bytes       # Includes UTF-16BE null termination
    metadata: bytes  # Original INF1 entry suffix


class CharacterBMG:
    def __init__(self, original: bytes, header: bytes, sections: list[tuple[bytes, bytes]],
                 messages: list[Message], entry_width: int, order_sorted: bool,
                 original_dat_prefix: bytes):
        self.original = original
        self.header = header
        self.sections = sections
        self.messages = messages
        self.entry_width = entry_width
        self.order_sorted = order_sorted
        self.dat_prefix = original_dat_prefix
        self.dirty = False

    @classmethod
    def read(cls, raw: bytes) -> 'CharacterBMG':
        if len(raw) < 0x20 or raw[:8] != b'MESGbmg1':
            raise ValueError('Invalid BMG header')
        count = be32(raw, 12)
        at = 0x20
        sections: list[tuple[bytes, bytes]] = []
        for _ in range(count):
            if at + 8 > len(raw):
                raise ValueError('Truncated BMG section header')
            size = be32(raw, at + 4)
            if size < 8 or at + size > len(raw):
                raise ValueError('Invalid BMG section size')
            sections.append((raw[at:at + 4], raw[at:at + size]))
            at += size
        data_by_tag = {tag: chunk for tag, chunk in sections}
        if not all(t in data_by_tag for t in (b'INF1', b'DAT1', b'MID1')):
            raise ValueError('Expected INF1, DAT1, and MID1 BMG sections')
        inf, dat, mid = (data_by_tag[t] for t in (b'INF1', b'DAT1', b'MID1'))
        if raw[16] != 2 or len(inf) < 16 or len(mid) < 16:
            raise ValueError('Expected UTF-16 BMG with complete INF1/MID1 headers')
        total = be16(inf, 8)
        if be16(mid, 8) != total:
            raise ValueError('BMG INF1/MID1 message counts disagree')
        width = be16(inf, 10)
        if width < 4 or width > 64 or total > 60000:
            raise ValueError('Unsupported BMG INF entry format')
        if 16 + total * width > len(inf) or 16 + total * 4 > len(mid):
            raise ValueError('Truncated BMG entries')
        offsets = [be32(inf, 16 + i * width) for i in range(total)]
        if any(off >= len(dat) - 8 or off % 2 for off in offsets):
            raise ValueError('Invalid BMG message offsets')
        first_data = min(offsets, default=0)
        messages = []
        for i, offset in enumerate(offsets):
            id_ = be32(mid, 16 + 4 * i)
            start = 8 + offset
            cursor = start
            while cursor + 1 < len(dat) and dat[cursor:cursor + 2] != b'\0\0':
                if dat[cursor:cursor + 2] == b'\x00\x1a':
                    if cursor + 3 > len(dat):
                        raise ValueError('Truncated BMG control sequence')
                    length = dat[cursor + 2]
                    if length < 4 or length % 2 or cursor + length > len(dat):
                        raise ValueError('Invalid BMG control sequence length')
                    cursor += length
                else:
                    cursor += 2
            if cursor + 1 >= len(dat):
                raise ValueError('Unterminated UTF-16 BMG message')
            messages.append(Message(id_, dat[start:cursor + 2], inf[16 + i * width + 4:16 + (i + 1) * width]))
        ids = [m.id for m in messages]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate BMG message IDs')
        return cls(raw, raw[:32], sections, messages, width,
                   ids == sorted(ids), dat[8:8 + first_data])

    def _lookup(self, message_id: int) -> Message | None:
        return next((m for m in self.messages if m.id == message_id), None)

    def get_text(self, message_id: int) -> str:
        message = self._lookup(message_id)
        if message is None:
            return ''
        try:
            return message.raw[:-2].decode('utf-16-be').lstrip('\t')
        except UnicodeDecodeError:
            return '<non-text message>'

    def set_text(self, message_id: int, text: str) -> None:
        if not 0 <= message_id <= 0xFFFFFFFF:
            raise ValueError('Invalid message ID')
        if '\0' in text or '\x1a' in text:
            raise ValueError('NUL and BMG control markers are not valid in new text')
        if len(text) > 200:
            raise ValueError('Character name or author credit is too long')
        message = self._lookup(message_id)
        if message is not None and b'\x00\x1a' in message.raw:
            raise ValueError('This message contains control sequences and cannot be edited safely')
        prefix = '\t' if message is None or message.raw.startswith(b'\x00\x09') else ''
        new_raw = (prefix + text).encode('utf-16-be') + b'\0\0'
        if message is not None:
            if message.raw != new_raw:
                message.raw = new_raw
                self.dirty = True
        else:
            meta = self.messages[0].metadata if self.messages else bytes(self.entry_width - 4)
            self.messages.append(Message(message_id, new_raw, meta))
            self.dirty = True

    def remap(self, char_id: int, slot_changes: dict[int, int], delete_slots: set[int] | None = None) -> None:
        """Atomically remap name+author BMG IDs without intermediate collisions."""
        delete_slots = delete_slots or set()
        if any(not 1 <= s <= 100 for s in [*slot_changes, *slot_changes.values(), *delete_slots]):
            raise ValueError('Slot must be 1–100')
        updated: list[Message] = []
        change = False
        for msg in self.messages:
            prefix = msg.id >> 16
            low = msg.id & 0xffff
            family = low & 0xff00
            slot = low & 0xff
            if prefix == char_id and family in (0x6a00, 0x7a00):
                if slot in delete_slots:
                    change = True
                    continue
                if slot in slot_changes:
                    target = slot_changes[slot]
                    if target != slot:
                        change = True
                    updated.append(Message((prefix << 16) | family | target, msg.raw, msg.metadata))
                    continue
            updated.append(msg)
        ids = [m.id for m in updated]
        if len(ids) != len(set(ids)):
            raise ValueError('BMG remapping causes a message-ID collision')
        if change:
            self.messages = updated
            self.dirty = True

    def encode(self) -> bytes:
        if not self.dirty:
            return self.original
        if any(tag in (b'FLW1', b'FLI1') for tag, _ in self.sections):
            raise ValueError('Flow BMG sections refer to message indexes; refusing to rebuild them unsafely')
        # RR stops searching when it encounters an ID greater than its target.
        # Every rebuilt table must therefore be sorted, including old imports.
        entries = sorted(self.messages, key=lambda m: m.id)
        if len(entries) > 60000 or len({m.id for m in entries}) != len(entries):
            raise ValueError('Too many or duplicate BMG message IDs')
        original = {tag: chunk for tag, chunk in self.sections}
        inf_header = bytearray(original[b'INF1'][:16])
        struct.pack_into('>H', inf_header, 8, len(entries))
        inf_entries = bytearray()
        dat_content = bytearray(self.dat_prefix)
        mid_content = bytearray()
        for msg in entries:
            if len(msg.metadata) != self.entry_width - 4:
                raise ValueError('Invalid BMG metadata size')
            inf_entries += struct.pack('>I', len(dat_content)) + msg.metadata
            dat_content += msg.raw
            mid_content += struct.pack('>I', msg.id)
        inf = align32(inf_header + inf_entries)
        dat = align32(original[b'DAT1'][:8] + dat_content)
        mid_header = bytearray(original[b'MID1'][:16])
        struct.pack_into('>H',mid_header,8,len(entries))
        mid = align32(mid_header + mid_content)
        new_sections = {b'INF1': inf, b'DAT1': dat, b'MID1': mid}
        assembled = []
        for tag, chunk in self.sections:
            next_chunk = bytearray(new_sections.get(tag, chunk))
            struct.pack_into('>I', next_chunk, 4, len(next_chunk))
            assembled.append(bytes(next_chunk))
        hdr = bytearray(self.header)
        struct.pack_into('>I', hdr, 8, len(hdr) + sum(map(len, assembled)))
        return bytes(hdr) + b''.join(assembled)


def name_id(character_id: int, slot: int) -> int:
    # PAL GetCharacterBMGId (80833774): vanilla non-Mii names use 9000 + ID.
    # Custom skin IDs retain the native character in the high halfword.
    if slot == 0:
        return 9000 + character_id
    return (character_id << 16) | 0x6a00 | slot


def author_id(character_id: int, slot: int) -> int:
    return (character_id << 16) | 0x7a00 | slot
