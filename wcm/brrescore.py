"""Independent, bounded BRRES reader: single MDL0, textures and bind matrices."""
from dataclasses import dataclass, field
from struct import unpack_from, error as StructError
from math import isfinite, sin, cos, radians
import re
import numpy as np
from .gxtexture import decode_texture, rgb565, rgb5a3
_MAX_INPUT=128*1024*1024
_MAX_VERTICES=125000
_MAX_TRIANGLES=65000

class PreviewDecodeError(ValueError): pass

@dataclass(frozen=True)
class ModelVariant:
    name: str
    offset: int
    size: int
    version: int
    is_lod: bool

@dataclass
class PreviewMaterial:
    name: str
    texture: object=None
    wrap_s: int=0
    wrap_t: int=0
    translucent: bool=False
    uv_channel: int=0
    uv_matrix: object=None
    cull: int=0
    depth_test: bool=True
    depth_write: bool=True
    depth_func: int=3
    blend_enabled: object=None
    blend_src: int=4
    blend_dst: int=5
    blend_subtract: bool=False
    alpha_test: tuple=(4,16,7,0,0)

@dataclass
class PreviewMesh:
    name: str
    vertices: list
    triangles: list
    uvs: list=field(default_factory=list)
    materials: list=field(default_factory=list)
    warnings: list=field(default_factory=list)

def _u16(d,p): return unpack_from('>H',d,p)[0]
def _i16(d,p): return unpack_from('>h',d,p)[0]
def _u32(d,p): return unpack_from('>I',d,p)[0]
def _i32(d,p): return unpack_from('>i',d,p)[0]

def _name(d,p):
    if not 0<=p<len(d): raise PreviewDecodeError('Invalid resource string pointer')
    end=d.find(b'\0',p,min(len(d),p+1024))
    if end<0: raise PreviewDecodeError('Unterminated resource name')
    return d[p:end].decode('utf-8',errors='replace')

def _dictionary(d,p,limit):
    if not 0<=p<=limit-24: raise PreviewDecodeError('Invalid resource dictionary')
    size,count=_u32(d,p),_u32(d,p+4)
    if count>2048 or size<24+count*16 or p+size>limit: raise PreviewDecodeError('Invalid resource dictionary size')
    out=[]
    for i in range(count):
        entry=p+24+i*16
        name=_name(d,p+_i32(d,entry+8));target=p+_i32(d,entry+12)
        if not 0<=target<limit: raise PreviewDecodeError('Invalid resource dictionary target')
        out.append((name,target))
    return out

def _resources(d):
    if not isinstance(d,bytes) or d[:4]!=b'bres': raise PreviewDecodeError('Expected BRRES resource (bres magic)')
    if len(d)>_MAX_INPUT: raise PreviewDecodeError('BRRES is too large for an embedded preview')
    if len(d)<24 or d[4:6]!=b'\xfe\xff' or _u32(d,8)!=len(d): raise PreviewDecodeError('Invalid BRRES header, byte order or file size')
    root=_u16(d,12)
    if root+8>len(d) or d[root:root+4]!=b'root': raise PreviewDecodeError('Missing BRRES root dictionary')
    folders=_dictionary(d,root+8,len(d))
    if len(folders)>64: raise PreviewDecodeError('Too many BRRES resource folders')
    result={};total=0
    for name,p in folders:
        entries=_dictionary(d,p,len(d));total+=len(entries)
        if total>4096: raise PreviewDecodeError('BRRES resource count limit exceeded')
        if name in result: raise PreviewDecodeError('Duplicate BRRES resource folder')
        result[name]=entries
    return result

def list_models(d):
    try:
        out=[]
        for name,p in _resources(d).get('3DModels(NW4R)',[]):
            if p+16>len(d) or d[p:p+4]!=b'MDL0': raise PreviewDecodeError('Invalid MDL0 dictionary entry')
            size,version=_u32(d,p+4),_u32(d,p+8)
            if size<0x70 or p+size>len(d): raise PreviewDecodeError('Invalid MDL0 span')
            out.append(ModelVariant(name,p,size,version,bool(re.search(r'lod|(?:^|[_ .-])low(?:$|[_ .-])',name,re.I))))
        if not out: raise PreviewDecodeError('No MDL0 models in BRRES')
        return out
    except (StructError,IndexError) as exc: raise PreviewDecodeError('Truncated BRRES dictionary') from exc

def default_model(variants):
    return max(range(len(variants)),key=lambda i:(not variants[i].is_lod,
        not bool(re.search(r'(?:^|[_ .-])(?:alt\w*|shadow|hair)(?:$|[_ .-])',variants[i].name,re.I)),
        bool(re.fullmatch(r'model|normal|driver|body|menu|driver_model',variants[i].name,re.I)),
        bool(re.search(r'driver|body|menu',variants[i].name,re.I)),variants[i].size))

def _sections(d,p,end,i):
    off=_i32(d,p+0x10+i*4)
    if not off: return []
    if not p+0x70<=p+off<end: raise PreviewDecodeError('MDL0 section outside model')
    entries=_dictionary(d,p+off,end)
    if any(not p+0x70<=target<end for _,target in entries): raise PreviewDecodeError('MDL0 entry outside model')
    return entries

def _vectors(d,p,end,uv=False):
    if p+32>end: raise PreviewDecodeError('Truncated vertex buffer')
    size,off=_u32(d,p),_i32(d,p+8);comp,fmt=_u32(d,p+0x14),_u32(d,p+0x18)
    div,stride=d[p+0x1c:p+0x1e];count=_u16(d,p+0x1e)
    dim=(2 if comp else 1) if uv else (3 if comp else 2)
    if fmt>4 or comp>1 or div>24 or count>_MAX_VERTICES: raise PreviewDecodeError('Unsupported vertex/UV encoding')
    unit=(1,1,2,2,4)[fmt]
    if stride<unit*dim or size<32 or off<32 or p+size>end or off+count*stride>size: raise PreviewDecodeError('Invalid vertex buffer span')
    out=[];scale=1 if fmt==4 else 1/(1<<div);template='>'+('B','b','H','h','f')[fmt]*dim
    for i in range(count):
        v=tuple(float(a*scale) for a in unpack_from(template,d,p+off+i*stride))
        if not all(isfinite(a) and abs(a)<=1e7 for a in v): raise PreviewDecodeError('Nonfinite or excessive vertex')
        out.append(v+(0.,)*((2 if uv else 3)-dim))
    return out

def _triangles_of_primitive(cmd,v):
    if cmd==0x90:
        for i in range(0,len(v)-2,3): yield v[i],v[i+1],v[i+2]
    elif cmd==0x98:
        for i in range(len(v)-2): yield (v[i+1],v[i],v[i+2]) if i&1 else (v[i],v[i+1],v[i+2])
    elif cmd==0xa0:
        for i in range(1,len(v)-1): yield v[0],v[i],v[i+1]
    elif cmd in (0x80,0x88):
        for i in range(0,len(v)-3,4):
            yield v[i],v[i+1],v[i+2]
            yield v[i],v[i+2],v[i+3]

def _matrix(d,p):
    v=unpack_from('>12f',d,p)
    if not all(isfinite(a) and abs(a)<1e7 for a in v): raise PreviewDecodeError('Invalid bone matrix')
    m=np.eye(4);m[:3,:4]=np.array(v).reshape(3,4)
    return m

def _bind_influences(nodes,inverse,mix):
    for nid,weights in mix:
        if any(b not in nodes for b,_ in weights): raise PreviewDecodeError('Unknown envelope bone')
        if len(weights)==1:
            value=nodes[weights[0][0]]
            nodes[nid]=value.copy() if value is not None else None
        elif any(nodes[b] is None or inverse.get(b) is None for b,_ in weights):
            nodes[nid]=None
        else:
            nodes[nid]=sum((nodes[b]@inverse[b])*w for b,w in weights)

def _local_transform(values):
    """Column-vector T * Rz * Ry * Rx * S, including intentional zero scales."""
    if not all(isfinite(v) and abs(v)<1e7 for v in values): return None
    sx,sy,sz,rx,ry,rz,tx,ty,tz=values
    x,y,z=map(radians,(rx,ry,rz));cx,cy,cz=cos(x),cos(y),cos(z);ax,ay,az=sin(x),sin(y),sin(z)
    xrot=np.array([[1,0,0],[0,cx,-ax],[0,ax,cx]])
    yrot=np.array([[cy,0,ay],[0,1,0],[-ay,0,cy]])
    zrot=np.array([[cz,-az,0],[az,cz,0],[0,0,1]])
    m=np.eye(4);m[:3,:3]=zrot@yrot@xrot@np.diag((sx,sy,sz));m[:3,3]=(tx,ty,tz)
    return m

def _bone_nodes(d,bones,end,warnings):
    # Cached bind matrices can be stale after a mod changes its local SRT.
    # BrawlCrate's bind preview evaluates local SRT through the bone hierarchy;
    # envelopes still reference the ORIGINAL inverse-bind matrices.
    records={};nodes={};inverse={};by_offset={at:name for name,at in bones}
    for name,at in bones:
        if at+0xd0>end: raise PreviewDecodeError('Truncated bone')
        nid=_i32(d,at+0x10)
        if nid in nodes: raise PreviewDecodeError('Duplicate bone node ID')
        nodes[nid]=None
        local=_local_transform(unpack_from('>9f',d,at+0x20));parent=_i32(d,at+0x5c)
        parent=at+parent if parent else None
        if parent is not None and parent not in by_offset: raise PreviewDecodeError('Unknown bone parent')
        records[at]=(nid,local,parent)
        if local is None: warnings.append(f'Bone {name}: invalid local SRT; ignored only when not needed by drawable geometry')
        try: inverse[nid]=_matrix(d,at+0xa0)
        except PreviewDecodeError:
            inverse[nid]=None
            warnings.append(f'Bone {name}: invalid inverse-bind matrix; ignored only when not needed by drawable geometry')
        if _u32(d,at+0x18): warnings.append('Billboard bone: static local transform used')
    evaluated=set()
    # Iterative parent evaluation avoids Python recursion limits for deep rigs.
    for at in records:
        chain=[];seen=set();cursor=at
        while cursor is not None and cursor not in evaluated:
            if cursor in seen: raise PreviewDecodeError('Cycle in bone hierarchy')
            seen.add(cursor);chain.append(cursor);cursor=records[cursor][2]
        for cursor in reversed(chain):
            nid,local,parent=records[cursor]
            if local is not None:
                if parent is None: nodes[nid]=local
                else:
                    parent_matrix=nodes[records[parent][0]]
                    nodes[nid]=parent_matrix@local if parent_matrix is not None else None
            evaluated.add(cursor)
    return nodes,inverse

def _definitions(d,p,end):
    draws=[];mix=[]
    for name,at in _sections(d,p,end,0):
        for _ in range(20000):
            if at>=end: raise PreviewDecodeError('Truncated MDL0 definitions')
            cmd=d[at];at+=1
            if cmd==1: break
            if cmd in (2,5):
                if at+4>end: raise PreviewDecodeError('Truncated node definition')
                at+=4
            elif cmd==3:
                if at+3>end: raise PreviewDecodeError('Truncated NodeMix')
                node,count=_u16(d,at),d[at+2];at+=3
                if not count or count>64 or at+count*6>end: raise PreviewDecodeError('Invalid NodeMix weights')
                weights=[(_u16(d,at+i*6),unpack_from('>f',d,at+i*6+2)[0]) for i in range(count)]
                if any(not isfinite(w) or w<0 for _,w in weights) or abs(sum(w for _,w in weights)-1)>.02: raise PreviewDecodeError('Invalid envelope weights')
                mix.append((node,weights));at+=count*6
            elif cmd==4:
                if at+7>end: raise PreviewDecodeError('Truncated draw definition')
                draws.append((_u16(d,at),_u16(d,at+2),_u16(d,at+4),name=='DrawXlu'));at+=7
            elif cmd==6: at+=4
            else: raise PreviewDecodeError(f'Unsupported MDL0 definition opcode {cmd}')
        else: raise PreviewDecodeError('MDL0 definition limit exceeded')
    return draws,mix

def _textures(d,resources,warnings):
    textures={};palettes={};total=0;palette_entries=0
    for name,p in resources.get('Palettes(NW4R)',[]):
        try:
            size=_u32(d,p+4);version=_u32(d,p+8)
            if d[p:p+4]!=b'PLT0' or version not in (1,3) or p+size>len(d): raise ValueError('Invalid PLT0')
            off=_u32(d,p+0x10);fmt=_u32(d,p+0x18);count=_u16(d,p+0x1c)
            palette_entries+=count
            if fmt>2 or not count or count>16384 or off<0x40 or off+count*2>size or palette_entries>65536: raise ValueError('Invalid or excessive palette')
            palettes[name]=[rgb565(v) if fmt==1 else rgb5a3(v) if fmt==2 else (v&255,)*3+(v>>8,) for v in unpack_from('>'+str(count)+'H',d,p+off)]
        except (ValueError,StructError): warnings.append(f'Palette {name}: unsupported or malformed')
    for name,p in resources.get('Textures(NW4R)',[]):
        try:
            if p+0x40>len(d) or d[p:p+4]!=b'TEX0': raise ValueError('Invalid TEX0')
            size,version=_u32(d,p+4),_u32(d,p+8)
            if version not in (1,3) or p+size>len(d): raise ValueError(f'Unsupported TEX0 version {version}')
            off=_u32(d,p+0x10);w,h=_u16(d,p+0x1c),_u16(d,p+0x1e);fmt=_u32(d,p+0x20)
            total+=w*h
            if total>16777216 or not 0x40<=off<size: raise ValueError('Texture memory/span limit exceeded')
            textures[name]=(d[p+off:p+size],w,h,fmt)
        except (ValueError,StructError) as exc: warnings.append(f'Texture {name}: {exc}')
    return textures,palettes

def texture_srt(scale_s,scale_t,angle,translate_s,translate_t,mode=0):
    """NW4R static texture transform, acting on top-left (s,t,1) coordinates.

    Maya rotates around (1/2,1/2), scales around (0,1), then translates
    inside that scale. XSI rotates around (0,1); Max uses the center for both.
    """
    if mode not in (0,1,2): raise PreviewDecodeError('Unsupported texture matrix mode')
    c,s=cos(radians(angle)),sin(radians(angle))
    rotation=np.array([[c,s,0],[-s,c,0],[0,0,1.]])
    if mode==1: rotation=np.array([[c,-s,0],[s,c,0],[0,0,1.]])
    def shift(x,y): return np.array([[1.,0,x],[0,1.,y],[0,0,1.]])
    pivot=(0.,1.) if mode==1 else (.5,.5)
    turn=shift(*pivot)@rotation@shift(-pivot[0],-pivot[1])
    scale=np.diag([scale_s,scale_t,1.])
    if mode==2:
        return shift(.5,.5)@scale@rotation@shift(-.5-translate_s,-.5+translate_t)
    stretch=shift(0,1)@scale@shift(0,-1)
    translation=shift(-translate_s,translate_t)
    return stretch@(turn@translation if mode==1 else translation@turn)


def _texture_coordinates(d,at,size,ref_offset,mat,warnings):
    # MDL0 v11 material SRT table and XF texgen commands (texture 0).
    table=at+0x1a0+(ref_offset&15)
    if table+28>at+size: raise PreviewDecodeError('Truncated material texture transform')
    flags=_u32(d,table)&15; mode=_u32(d,table+4)
    ss,st,r,ts,tt=unpack_from('>5f',d,table+8)
    if not all(isfinite(v) and abs(v)<1e7 for v in (ss,st,r,ts,tt)):
        raise PreviewDecodeError('Invalid texture transform')
    if flags&2: ss=st=1.
    if flags&4: r=0.
    if flags&8: ts=tt=0.
    mat.uv_matrix=texture_srt(ss,st,r,ts,tt,mode)
    dl=at+_i32(d,at+0x3c)+0xe0
    if not at<=dl<at+size: raise PreviewDecodeError('Invalid material display list')
    cursor=dl
    while cursor<at+size:
        cmd=d[cursor];cursor+=1
        if cmd==0: continue
        if cmd!=0x10: break
        if cursor+4>at+size: raise PreviewDecodeError('Truncated material XF command')
        count=_u16(d,cursor)+1;address=_u16(d,cursor+2);cursor+=4
        if count>256 or cursor+count*4>at+size: raise PreviewDecodeError('Invalid material XF span')
        if address<=0x1040<address+count:
            value=_u32(d,cursor+(0x1040-address)*4);source=(value>>7)&31
            if 5<=source<=12 and ((value>>4)&7)==0:
                mat.uv_channel=source-5
            else: warnings.append(f'Material {mat.name}: generated environment coordinates approximated with UV0')
            break
        cursor+=count*4


def _material_state(d,at,size,mat,warnings):
    """Read BP depth/blend/alpha registers independently of DrawOpa/DrawXlu.

    DrawXlu controls scheduling, not depth writes. BP masks apply to only the
    next register write; the material mode block occupies 32 bytes.
    """
    start=at+_i32(d,at+0x3c)
    if start<at+0x40 or start+32>at+size:
        raise PreviewDecodeError('Invalid material mode block')
    registers={0x40:0x17,0x41:0x34a0,0xf3:0x3f0000};mask=0xffffff
    cursor=start
    while cursor<start+32:
        cmd=d[cursor];cursor+=1
        if cmd==0: continue
        if cmd!=0x61 or cursor+4>start+32:
            raise PreviewDecodeError('Invalid material BP command')
        word=_u32(d,cursor);cursor+=4;reg=word>>24;value=word&0xffffff
        if reg==0xfe: mask=value;continue
        if reg in registers: registers[reg]=(registers[reg]&~mask)|(value&mask)
        mask=0xffffff
    z,blend,alpha=(registers[i] for i in (0x40,0x41,0xf3))
    mat.depth_test=bool(z&1);mat.depth_write=bool(z&16);mat.depth_func=(z>>1)&7
    mat.blend_enabled=bool(blend&1);mat.blend_src=(blend>>8)&7;mat.blend_dst=(blend>>5)&7
    mat.blend_subtract=bool(blend&0x800)
    mat.alpha_test=((alpha>>16)&7,alpha&255,(alpha>>19)&7,(alpha>>8)&255,(alpha>>22)&3)
    if blend&2: warnings.append(f'Material {mat.name}: GX logic operations are not reproduced')


def _materials(d,p,end,textures,palettes,warnings):
    result=[];cache={};decoded_pixels=0
    for name,at in _sections(d,p,end,8):
        if at+0x34>end: raise PreviewDecodeError('Truncated material')
        size=_u32(d,at)
        if size<0x34 or at+size>end: raise PreviewDecodeError('Invalid material size')
        count=_u32(d,at+0x2c);off=_i32(d,at+0x30)
        mat=PreviewMaterial(name,translucent=bool(_u32(d,at+0x10)&0x80000000))
        mat.cull=_u32(d,at+0x18)
        _material_state(d,at,size,mat,warnings)
        if count:
            ref=at+off
            if count>8 or off<=0 or ref+count*0x34>at+size: raise PreviewDecodeError('Invalid texture reference span')
            tex=_name(d,ref+_i32(d,ref));paloff=_i32(d,ref+4);pal=_name(d,ref+paloff) if paloff else ''
            mat.wrap_s,mat.wrap_t=_u32(d,ref+0x18),_u32(d,ref+0x1c)
            _texture_coordinates(d,at,size,off,mat,warnings)
            try:
                if (tex,pal) not in cache:
                    raw,w,h,fmt=textures[tex]
                    decoded_pixels+=w*h
                    if decoded_pixels>16777216: raise ValueError('Decoded texture cache limit exceeded')
                    cache[tex,pal]=decode_texture(raw,w,h,fmt,palette=palettes.get(pal))
                mat.texture=cache[tex,pal]
            except (KeyError,ValueError,IndexError) as exc: warnings.append(f'Material {name}: texture {tex} unavailable ({exc})')
            if count>1 or d[at+0x16]>1: warnings.append(f'Material {name}: first texture only; multi-stage TEV/effects approximated')
        else: warnings.append(f'Material {name}: untextured material, neutral fallback')
        result.append(mat)
    return result

def _object(d,p,end,positions,uvs,nodes,mesh,mat):
    if p+0x68>end: raise PreviewDecodeError('Truncated MDL0 object')
    size=_u32(d,p);limit=p+size
    if size<0x68 or limit>end: raise PreviewDecodeError('Invalid MDL0 object span')
    lo,hi=_u32(d,p+12),_u32(d,p+16);bits=lo&0x1ff
    desc=[(lo>>s)&3 for s in (9,11,13,15)]+[(hi>>(2*i))&3 for i in range(8)]
    if 1 in desc:
        mesh.warnings.append('GX direct vertex attributes unsupported; object skipped');return
    widths=[(0,0,1,2)[a] for a in desc]
    if widths[2] or widths[3]: mesh.warnings.append('GX vertex colors/lighting are not reproduced')
    if not widths[0]: return
    material=mesh.materials[mat] if mesh.materials else None
    channel=material.uv_channel if material else 0
    vg,ug=_i16(d,p+0x48),_i16(d,p+0x50+channel*2)
    if not 0<=vg<len(positions): raise PreviewDecodeError('Invalid position group')
    verts=positions[vg];uv=uvs[ug] if 0<=ug<len(uvs) else []
    if not uv: mesh.warnings.append(f'Object has no supported UV{channel}; neutral fallback')
    rigid=_i32(d,p+8);palette={};start=p+0x24+_i32(d,p+0x2c);length=_u32(d,p+0x24)
    if start<p+0x34 or start+length>limit or length>5*1024*1024: raise PreviewDecodeError('Invalid primitive stream')
    cursor=start;stop=start+length;stride=bits.bit_count()+sum(widths);dedup={}
    for _ in range(700000):
        if cursor>=stop: break
        cmd=d[cursor];cursor+=1
        if cmd==0: continue
        if cmd in (0x20,0x28,0x30,0x38,0x61):
            if cursor+4>stop: raise PreviewDecodeError('Truncated matrix/GPU load')
            if cmd==0x20: palette[(_u16(d,cursor+2)&0xfff)//12]=_u16(d,cursor)
            cursor+=4;continue
        if cmd==8: cursor+=5;continue
        if cmd==0x10:
            if cursor+4>stop: raise PreviewDecodeError('Truncated XF load')
            cursor+=4+(_u16(d,cursor)+1)*4;continue
        if cmd in (0x40,0x48): raise PreviewDecodeError('Indirect GPU display lists unsupported')
        prim=cmd&0xf8
        if prim not in (0x80,0x88,0x90,0x98,0xa0,0xa8,0xb0,0xb8): raise PreviewDecodeError(f'Unknown GPU opcode 0x{cmd:02x}')
        if cursor+2>stop: raise PreviewDecodeError('Truncated primitive')
        count=_u16(d,cursor);cursor+=2
        if cursor+count*stride>stop: raise PreviewDecodeError('Truncated primitive vertices')
        indices=[]
        for i in range(count):
            at=cursor+i*stride;node=rigid
            for bit in range(9):
                if bits&(1<<bit):
                    if bit==0:
                        node=palette.get(d[at]//3)
                        if node is None: raise PreviewDecodeError('Unresolved position matrix palette')
                    at+=1
            attrs=[]
            for width in widths:
                attrs.append(d[at] if width==1 else _u16(d,at) if width==2 else -1);at+=width
            vi,ui=attrs[0],attrs[4+channel]
            if vi>=len(verts) or (ui>=0 and uv and ui>=len(uv)): raise PreviewDecodeError('Vertex or UV index out of range')
            key=(vi,ui,node)
            if key not in dedup:
                xyz=verts[vi]
                if node>=0:
                    if node not in nodes: raise PreviewDecodeError(f'Unknown bone/envelope node {node}')
                    if nodes[node] is None: raise PreviewDecodeError(f'Invalid bind matrix required by drawable bone/envelope node {node}')
                    xyz=tuple((nodes[node]@np.array((*xyz,1.)))[:3])
                if len(mesh.vertices)>=_MAX_VERTICES: raise PreviewDecodeError('Model exceeds safe vertex preview limit')
                st=uv[ui] if uv and ui>=0 else (0.,0.)
                if material and material.uv_matrix is not None:
                    st=tuple((material.uv_matrix@np.array((*st,1.)))[:2])
                dedup[key]=len(mesh.vertices);mesh.vertices.append(xyz);mesh.uvs.append(st)
            indices.append(dedup[key])
        cursor+=count*stride
        for a,b,c in _triangles_of_primitive(prim,indices):
            if a!=b and b!=c and a!=c:
                if len(mesh.triangles)>=_MAX_TRIANGLES: raise PreviewDecodeError('Model exceeds safe triangle preview limit')
                mesh.triangles.append((a,b,c,mat))
    else: raise PreviewDecodeError('Display list command limit exceeded')

def decode_brres(d,model_index=None):
    try:
        variants=list_models(d);i=default_model(variants) if model_index is None else model_index
        if not isinstance(i,int) or not 0<=i<len(variants): raise PreviewDecodeError('Invalid model selection')
        selected=variants[i];p=selected.offset;end=p+selected.size
        if selected.version!=11: raise PreviewDecodeError(f'MDL0 version {selected.version} unsupported; requires v11')
        mesh=PreviewMesh(selected.name,[],[])
        mesh.warnings.append('Bind pose only; CHR0, billboards, TEV and animated/effect texture matrices are not reproduced. No automatic T-pose.')
        if len(variants)>1: mesh.warnings.append('Multiple models: selection uses a heuristic; inspect variants explicitly.')
        positions=[];uvs=[]
        for section,groups,budget in ((2,positions,_MAX_VERTICES),(5,uvs,_MAX_VERTICES*2)):
            total=0
            for _,at in _sections(d,p,end,section):
                if at+32>end: raise PreviewDecodeError('Truncated vertex buffer')
                total+=_u16(d,at+0x1e)
                if total>budget: raise PreviewDecodeError('Combined vertex/UV allocation limit exceeded')
                groups.append(_vectors(d,at,end,section==5))
        nodes,inverse=_bone_nodes(d,_sections(d,p,end,1),end,mesh.warnings)
        draws,mix=_definitions(d,p,end)
        # Weighted vertices use model space. Bind-pose skin matrix equals the
        # weighted sum of bind * inverse-bind, rather than the sum of bind.
        # Single influence uses the bone matrix; multiple influences use
        # model-space vertices and bind/inverse-bind skinning.
        _bind_influences(nodes,inverse,mix)
        tex,pal=_textures(d,_resources(d),mesh.warnings)
        mesh.materials=_materials(d,p,end,tex,pal,mesh.warnings);objects=_sections(d,p,end,10)
        if not draws: raise PreviewDecodeError('No MDL0 draw definitions; cannot safely guess visibility')
        seen=set()
        for mat,obj,bone,xlu in draws:
            if (obj,mat) in seen: continue
            seen.add((obj,mat))
            if obj>=len(objects) or mat>=len(mesh.materials): raise PreviewDecodeError('Invalid draw object/material index')
            mesh.materials[mat].translucent |= xlu
            _object(d,objects[obj][1],end,positions,uvs,nodes,mesh,mat)
        if not mesh.triangles: raise PreviewDecodeError('No supported drawable triangles in selected MDL0')
        mesh.warnings=list(dict.fromkeys(mesh.warnings))
        return mesh
    except (StructError,IndexError,OverflowError) as exc: raise PreviewDecodeError('Truncated or invalid BRRES resource') from exc
