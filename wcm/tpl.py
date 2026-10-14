"""Nintendo TPL RGB5A3 images for MKWii minimap and CSS portraits."""
from __future__ import annotations
from pathlib import Path
import struct
from PIL import Image, ImageOps

MAGIC = 0x0020AF30

def _tpl_header(payload: bytes) -> tuple[int, int, int]:
    if len(payload) < 0x40 or struct.unpack_from('>I',payload,0)[0] != MAGIC:
        raise ValueError('Invalid TPL header')
    if struct.unpack_from('>I',payload,4)[0] != 1:
        raise ValueError('Only single-texture TPL is supported')
    table = struct.unpack_from('>I',payload,8)[0]
    if table > len(payload)-8:
        raise ValueError('TPL texture table is truncated')
    header = struct.unpack_from('>I',payload,table)[0]
    if header > len(payload)-12:
        raise ValueError('TPL texture header is truncated')
    height,width = struct.unpack_from('>HH',payload,header)
    fmt = struct.unpack_from('>I',payload,header+4)[0]
    pixel_offset = struct.unpack_from('>I',payload,header+8)[0]
    if fmt != 5 or not 1 <= width <= 2048 or not 1 <= height <= 2048:
        raise ValueError('Expected RGB5A3 texture')
    blocks = ((width+3)//4)*((height+3)//4)
    if pixel_offset + blocks*32 > len(payload):
        raise ValueError('TPL pixel data is truncated')
    return width, height, pixel_offset


def tpl_dimensions(payload: bytes) -> tuple[int, int]:
    """Inspect the same validated texture header without decoding its pixels."""
    width, height, _ = _tpl_header(payload)
    return width, height


def read_tpl(payload: bytes) -> Image.Image:
    width, height, pixel_offset = _tpl_header(payload)
    img = Image.new('RGBA',(width,height))
    pixels = img.load();p=pixel_offset
    for ty in range(0,height,4):
        for tx in range(0,width,4):
            for j in range(4):
                for i in range(4):
                    v=struct.unpack_from('>H',payload,p)[0];p+=2
                    if v&0x8000:
                        r=(v>>10)&31;g=(v>>5)&31;b=v&31
                        px=(r*255//31,g*255//31,b*255//31,255)
                    else:
                        a=(v>>12)&7;r=(v>>8)&15;g=(v>>4)&15;b=v&15
                        px=(r*255//15,g*255//15,b*255//15,a*255//7)
                    if tx+i<width and ty+j<height:
                        pixels[tx+i,ty+j]=px
    return img


def image_to_tpl(image: Image.Image, target_size: int) -> bytes:
    if target_size not in (32,64):
        raise ValueError('Only 32px minimap and 64px CSS portrait output supported')
    image=ImageOps.contain(image.convert('RGBA'), (target_size,target_size), Image.Resampling.LANCZOS)
    square=Image.new('RGBA',(target_size,target_size),(0,0,0,0))
    square.alpha_composite(image,((target_size-image.width)//2,(target_size-image.height)//2))
    out=bytearray(0x40)
    struct.pack_into('>IIII',out,0,MAGIC,1,0x0c,0x14)
    struct.pack_into('>HHII',out,0x14,target_size,target_size,5,0x40)
    struct.pack_into('>II',out,0x20,0,0) # wrapping
    struct.pack_into('>II',out,0x28,1,1) # filtering
    pixels=square.load()
    for ty in range(0,target_size,4):
        for tx in range(0,target_size,4):
            for y in range(4):
                for x in range(4):
                    r,g,b,a=pixels[tx+x,ty+y]
                    if a>224:
                        pixel=0x8000|((r*31+127)//255<<10)|((g*31+127)//255<<5)|((b*31+127)//255)
                    else:
                        pixel=(((a*7+127)//255)<<12)|(((r*15+127)//255)<<8)|(((g*15+127)//255)<<4)|((b*15+127)//255)
                    out+=struct.pack('>H',pixel)
    return bytes(out)


def png_to_tpl(path: Path, target_size: int) -> bytes:
    with Image.open(path) as image:
        return image_to_tpl(image,target_size)


def detected_icons(entries: list[tuple[str, bytes]]) -> dict[str, list[tuple[str, bytes]]]:
    """Rank all nested PNG/TPL images by dimensions, then secondary name hints."""
    import io
    from pathlib import PurePosixPath
    choices = {'Portrait': [], 'Map': []}
    for path, data in entries:
        if not path.lower().endswith(('.png', '.tpl')):
            continue
        try:
            if data.startswith(b'\x89PNG\r\n\x1a\n'):
                with Image.open(io.BytesIO(data)) as image:
                    size = image.size
            elif data.startswith(bytes.fromhex('0020af30')):
                size = tpl_dimensions(data)
            else:
                continue
        except (OSError, ValueError, struct.error):
            continue
        if max(size) > 4096:
            continue
        leaf = PurePosixPath(path.replace('\\', '/')).name.casefold()
        css = any(tag in leaf for tag in ('css', 'portrait', 'tt_', '64x64', 'menu_'))
        minimap = any(tag in leaf for tag in ('minimap', 'map', 'st_', '32x32'))
        kind = ('Portrait' if size == (64, 64) else 'Map' if size == (32, 32)
                else 'Portrait' if css else 'Map' if minimap else None)
        if kind is None:
            continue
        expected = 64 if kind == 'Portrait' else 32
        hint = css if kind == 'Portrait' else minimap
        opposite = minimap if kind == 'Portrait' else css
        from .library import parse_asset
        asset = parse_asset(path, source_import=True)
        canonical = bool(asset and asset.category == kind)
        mapped_folder = kind.casefold() in [part.casefold() for part in PurePosixPath(path.replace('\\', '/')).parts[:-1]]
        rank = (size != (expected, expected), 0 if hint else 2 if opposite else 1,
                not canonical, not mapped_folder, path.casefold(), path)
        choices[kind].append((rank, path, data))
    return {kind: [(path, data) for _, path, data in sorted(items, key=lambda item: item[0])]
            for kind, items in choices.items()}
