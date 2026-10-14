"""Independent Wii tiled texture decoder. First mip only, bounded allocations."""
import struct
from PIL import Image


def rgb565(v):
    return ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255)


def rgb5a3(v):
    if v & 0x8000:
        return (((v >> 10) & 31)*255//31, ((v >> 5)&31)*255//31, (v&31)*255//31, 255)
    return (((v >> 8)&15)*17, ((v >> 4)&15)*17, (v&15)*17, ((v >> 12)&7)*255//7)


def decode_texture(raw, width, height, fmt, palette=None):
    layout = {0:(8,8,32), 1:(8,4,32), 2:(8,4,32), 3:(4,4,32),
              4:(4,4,32), 5:(4,4,32), 6:(4,4,64), 8:(8,8,32),
              9:(8,4,32), 10:(4,4,32), 14:(8,8,32)}
    if fmt not in layout:
        raise ValueError(f'Unsupported GX texture format {fmt}')
    if not 1 <= width <= 2048 or not 1 <= height <= 2048 or width*height > 4_194_304:
        raise ValueError('Texture dimensions exceed preview limit')
    bw,bh,size = layout[fmt]
    needed = ((width+bw-1)//bw)*((height+bh-1)//bh)*size
    if len(raw) < needed:
        raise ValueError('Truncated tiled texture')
    if fmt in (8,9,10) and not palette:
        raise ValueError('Indexed texture requires a supported PLT0 palette')
    image = Image.new('RGBA', (width,height))
    px = image.load()
    at = 0
    for ty in range(0,height,bh):
        for tx in range(0,width,bw):
            block = raw[at:at+size]; at += size
            for y in range(bh):
                for x in range(bw):
                    n = y*bw+x
                    if fmt == 14:
                        off = ((y//4)*2+x//4)*8
                        c0,c1 = struct.unpack_from('>HH',block,off)
                        a,b = rgb565(c0),rgb565(c1)
                        if c0>c1:
                            colors=[a,b,tuple((2*a[i]+b[i])//3 for i in range(3))+(255,),
                                    tuple((a[i]+2*b[i])//3 for i in range(3))+(255,)]
                        else:
                            colors=[a,b,tuple((a[i]+b[i])//2 for i in range(3))+(255,), (0,0,0,0)]
                        color = colors[(block[off+4+y%4] >> (6-2*(x%4)))&3]
                    elif fmt == 6:
                        color=(block[n*2+1],block[32+n*2],block[33+n*2],block[n*2])
                    elif fmt in (0,8):
                        v=(block[n//2] >> (4 if n%2==0 else 0))&15
                        if fmt==8 and v>=len(palette): raise ValueError('Palette index out of range')
                        color=palette[v] if fmt==8 else (v*17,v*17,v*17,255)
                    elif fmt in (1,2,9):
                        v=block[n]
                        if fmt==9 and v>=len(palette): raise ValueError('Palette index out of range')
                        color=palette[v] if fmt==9 else ((v&15)*17,)*3+((v>>4)*17,) if fmt==2 else (v,v,v,255)
                    else:
                        v=struct.unpack_from('>H',block,n*2)[0]
                        if fmt==3: color=(v&255,)*3+(v>>8,)
                        elif fmt==4: color=rgb565(v)
                        elif fmt==5: color=rgb5a3(v)
                        else:
                            index=v&0x3fff
                            if index >= len(palette): raise ValueError('Palette index out of range')
                            color=palette[index]
                    if tx+x < width and ty+y < height:
                        px[tx+x,ty+y]=color
    return image
