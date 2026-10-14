"""Small structurally valid resources for installer/transaction tests."""
import struct

def valid_brres(marker=b''):
    d=bytearray(240+len(marker));d[:6]=b'bres\xfe\xff';struct.pack_into('>H',d,12,16)
    d[16:20]=b'root';struct.pack_into('>I',d,20,112)
    for at in (24,64):struct.pack_into('>II',d,at,40,1)
    d[128:132]=b'MDL0';struct.pack_into('>II',d,132,112+len(marker),11);d[240:]=marker
    for dictionary,name,target in ((24,'3DModels(NW4R)',64),(64,'driver',128)):
        string=len(d);d.extend(name.encode()+b'\0');struct.pack_into('>ii',d,dictionary+32,string-dictionary,target-dictionary)
    d.extend(bytes((-len(d))%32));struct.pack_into('>I',d,8,len(d));return bytes(d)

def valid_szs(marker=b''):
    from wcm.szs import U8Archive
    return U8Archive({'marker':marker}).encode()
