"""Validated NW4R voice resources; independent format implementation, no game writes."""
from dataclasses import dataclass, field
from pathlib import Path
import hashlib, io, mmap, re, struct, wave, zipfile
import numpy as np

MAX_AUDIO = 32 * 1024 * 1024
MAX_SECONDS = 30
# Suffixes addressed by the inspected RR loose-voice loader.
SUPPORTED_GROUPS=frozenset(('PC','NPC','CAN_PC','CAN_NPC','GOL_TOP','GOL_TOP2','GOL_TOP3','GOL_GOD','GOL_GOD2','GOL_GOD3','GOL_BAD','GOL_BAD2','GOL_BAD3'))

def u32(d, a):
    if a < 0 or a+4 > len(d): raise ValueError('Truncated sound reference')
    return struct.unpack_from('>I', d, a)[0]
def align(n): return (n+31)&~31
def chunk(d, a, size):
    if a < 0 or size < 0 or a+size > len(d): raise ValueError('Sound offset outside resource')
    return bytes(d[a:a+size])
def header(tag, size, first, blocks, version=0x100):
    return struct.pack('>4sHHIHH',tag,0xfeff,version,size,first,blocks)
def check_header(d, tag):
    if len(d)<32 or d[:4]!=tag or d[4:6]!=b'\xfe\xff':raise ValueError(f'Expected big-endian {tag.decode()} resource')
    if not 32 <= u32(d,8) <= len(d):raise ValueError('Invalid sound resource length')

def wav_pcm(raw, target_rate=None, channels=None):
    if len(raw)>MAX_AUDIO:raise ValueError('WAV exceeds 32 MiB limit')
    try:
        with wave.open(io.BytesIO(raw),'rb') as w:
            rate=w.getframerate();count=w.getnframes();ch=w.getnchannels();width=w.getsampwidth()
            if w.getcomptype()!='NONE' or ch not in (1,2) or width not in (1,2,3,4) or not 8000<=rate<=96000:
                raise ValueError('Use an uncompressed PCM WAV: mono/stereo, 8â€“32 bit, 8â€“96 kHz')
            if count<=0 or count/rate>MAX_SECONDS:raise ValueError('Voice clips must be nonempty and at most 30 seconds')
            data=w.readframes(count)
            if len(data)!=count*ch*width:raise ValueError('Truncated WAV samples')
    except (wave.Error, EOFError) as exc:raise ValueError('Unsupported WAV; export an uncompressed PCM WAV') from exc
    if width==1:samples=(np.frombuffer(data,np.uint8).astype(np.int32)-128)*256
    elif width==3:
        b=np.frombuffer(data,np.uint8).reshape(-1,3).astype(np.int32)
        v=b[:,0]|b[:,1]<<8|b[:,2]<<16;v=np.where(v&0x800000,v-0x1000000,v);samples=v>>8
    else:samples=np.frombuffer(data,'<i2' if width==2 else '<i4').astype(np.int32)>>(0 if width==2 else 16)
    samples=samples.reshape(-1,ch).astype(np.float64)
    channels=channels or ch
    if channels not in (1,2):raise ValueError('Unsupported channel count')
    if channels!=ch:samples=samples.mean(axis=1,keepdims=True) if channels==1 else np.repeat(samples,2,axis=1)
    target_rate=target_rate or min(rate,48000)
    if target_rate!=rate:
        # Linear interpolation is adequate for short voices; downsampling first
        # applies a box low-pass to avoid folding the highest source frequencies.
        if rate>target_rate:
            window=max(1,int(np.ceil(rate/target_rate)))
            samples=np.column_stack([np.convolve(samples[:,i],np.ones(window)/window,'same') for i in range(channels)])
        n=max(1,round(len(samples)*target_rate/rate));x=np.arange(n)*rate/target_rate
        samples=np.column_stack([np.interp(x,np.arange(len(samples)),samples[:,i]) for i in range(channels)])
    return target_rate,np.clip(np.rint(samples),-32768,32767).astype('<i2')

def wav_bytes(rate, samples):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:w.setnchannels(samples.shape[1]);w.setsampwidth(2);w.setframerate(rate);w.writeframes(samples.astype('<i2').tobytes())
    return out.getvalue()

def rwav_info(d):
    check_header(d,b'RWAV');info=u32(d,16)
    if chunk(d,info,4)!=b'INFO':raise ValueError('RWAV INFO missing')
    a=info+8;encoding,looped,channels,rate_hi=chunk(d,a,4)
    rate=(rate_hi<<16)|struct.unpack_from('>H',d,a+4)[0]
    units=u32(d,a+12);count=(units//16*14+max(0,units%16-2)) if encoding==2 else units+1
    if encoding not in (0,1,2) or channels not in (1,2) or not 8000<=rate<=96000 or count<=0 or count/rate>MAX_SECONDS:
        raise ValueError('Unsupported RWAV encoding, channels, rate or duration')
    return a,encoding,looped,channels,rate,count

def decode_rwav(d):
    a,encoding,looped,channels,rate,count=rwav_info(d);location=u32(d,24)+8;offsets=a+u32(d,a+16);decoded=[]
    for ch in range(channels):
        c=a+u32(d,offsets+ch*4);start=location+u32(d,c)
        if encoding==0:pcm=np.frombuffer(chunk(d,start,count),np.int8).astype(np.int16)*256
        elif encoding==1:pcm=np.frombuffer(chunk(d,start,count*2),'>i2').astype('<i2')
        else:
            ad=a+u32(d,c+4);coeff=struct.unpack('>16h',chunk(d,ad,32))
            hist1,hist2=struct.unpack('>hh',chunk(d,ad+36,4));pcm=[]
            data=chunk(d,start,((count+13)//14)*8)
            for f in range(0,len(data),8):
                pred=data[f]>>4;scale=1<<(data[f]&15)
                if pred>=8:raise ValueError('Invalid DSP predictor')
                c1,c2=coeff[pred*2:pred*2+2]
                for b in data[f+1:f+8]:
                    for v in (b>>4,b&15):
                        if len(pcm)==count:break
                        v=v-16 if v>=8 else v
                        sample=max(-32768,min(32767,((v*scale<<11)+c1*hist1+c2*hist2+1024)>>11))
                        pcm.append(sample);hist2,hist1=hist1,sample
            pcm=np.asarray(pcm,dtype='<i2')
        decoded.append(pcm)
    return wav_bytes(rate,np.column_stack(decoded))

def encode_rwav(raw, baseline):
    _,_,looped,channels,rate,_=rwav_info(baseline)
    if looped:raise ValueError('Looped voice waves require explicit loop editing; replacement is disabled')
    rate,samples=wav_pcm(raw,min(rate,48000),channels);count=len(samples)
    info_size=align(8+28+4*channels+28*channels);data_at=32+info_size
    info=bytearray(info_size);struct.pack_into('>4sI',info,0,b'INFO',info_size)
    struct.pack_into('>4B HBB 5I',info,8,1,0,channels,rate>>16,rate&65535,0,0,0,count-1,28,data_at+(u32(baseline,u32(baseline,16)+28)-u32(baseline,24)),0)
    data=bytearray();wave_base=8
    for ch in range(channels):
        chan=28+4*channels+28*ch;struct.pack_into('>I',info,wave_base+28+ch*4,chan)
        struct.pack_into('>II',info,wave_base+chan,len(data),0)
        original_info=rwav_info(baseline)[0]
        original_channel=original_info+u32(baseline,original_info+u32(baseline,original_info+16)+ch*4)
        info[wave_base+chan+8:wave_base+chan+28]=chunk(baseline,original_channel+8,20)
        data.extend(samples[:,ch].astype('>i2').tobytes());data.extend(bytes(-len(data)%32))
    data_block=struct.pack('>4sI',b'DATA',len(data)+8)+data
    output=header(b'RWAV',data_at+len(data_block),32,2,0x102)+struct.pack('>4I',32,len(info),data_at,len(data_block))+info+data_block
    decode_rwav(output)
    return output

class WaveResource:
    def __init__(self,data):
        if data[:4] not in (b'RWSD',b'RBNK'):raise ValueError('Only RWSD/RBNK wave resources are supported')
        check_header(data,data[:4]);size=u32(data,8);self.prefix=data[:size]
        found=[at for at in range(align(size),len(data)-31,32) if data[at:at+4]==b'RWAR']
        if not found:raise ValueError('RWSD/RBNK has no appended RWAR wave archive')
        at=found[0];r=chunk(data,at,u32(data,at+8));check_header(r,b'RWAR');table=u32(r,16);d=u32(r,24)
        if chunk(r,table,4)!=b'TABL' or chunk(r,d,4)!=b'DATA':raise ValueError('Invalid RWAR blocks')
        count=u32(r,table+8)
        if not 0<=count<=4096 or table+12+count*12>d:raise ValueError('Invalid RWAR wave table')
        self.waves=[]
        for i in range(count):
            entry=table+12+i*12;w=chunk(r,d+u32(r,entry+4),u32(r,entry+8));check_header(w,b'RWAV');self.waves.append(w)
        self.original=data;self.tail=data[at+len(r):]
    def rebuild(self,replacements):
        if not replacements:return self.original
        waves=list(self.waves)
        for index,raw in replacements.items():
            if not 0<=index<len(waves):raise ValueError('Wave index outside resource')
            waves[index]=raw;decode_rwav(raw)
        table_size=align(12+len(waves)*12);data=bytearray(32);table=bytearray(table_size)
        for i,w in enumerate(waves):
            struct.pack_into('>III',table,12+i*12,0x01000000,len(data),len(w));data.extend(w);data.extend(bytes(-len(data)%32))
        struct.pack_into('>4sII',table,0,b'TABL',table_size,len(waves));struct.pack_into('>4sI',data,0,b'DATA',len(data))
        offset=32+table_size;archive=header(b'RWAR',offset+len(data),32,2)+struct.pack('>4I',32,table_size,offset,len(data))+table+data
        result=self.prefix+bytes(-len(self.prefix)%32)+archive+self.tail
        checked=WaveResource(result)
        if checked.prefix!=self.prefix or len(checked.waves)!=len(self.waves):raise ValueError('Wave rebuild failed validation')
        return result
    def data_wave_map(self):
        if self.prefix[:4]!=b'RWSD':return {}
        d=u32(self.prefix,16)+8;p=self.prefix
        def refs(a):
            count=u32(p,a)
            if count>4096:raise ValueError('Invalid RWSD reference count')
            return [d+u32(p,a+8+i*8) for i in range(count)]
        result={}
        for i,entry in enumerate(refs(d)):
            note=d+u32(p,entry+20);result[i]=[u32(p,n) for n in refs(note)]
        return result

@dataclass
class VoiceBank:
    file_id:int
    stem:str
    resource:bytes
    labels:dict=field(default_factory=dict)
    writable:bool=True
    @property
    def key(self):return self.stem

class VoiceArchive:
    """Read only the selected character's INFO-referenced files from BRSAR."""
    def __init__(self,path,code):
        self.path=Path(path);self.code=code;self.banks={};self.shared=[]
        with self.path.open('rb') as file,mmap.mmap(file.fileno(),0,access=mmap.ACCESS_READ) as d:
            check_header(d,b'RSAR');base=u32(d,24)+8;sbase=u32(d,16)+8
            def ref(a):return base+u32(d,a+4)
            def refs(a):
                count=u32(d,a)
                if count>20000:raise ValueError('Invalid BRSAR list count')
                return [ref(a+4+i*8) for i in range(count)]
            st=sbase+u32(d,sbase);strings=[]
            for i in range(u32(d,st)):
                at=sbase+u32(d,st+4+i*4);end=d.find(b'\0',at,min(len(d),at+1024))
                if end<0:raise ValueError('Invalid BRSAR symbol')
                strings.append(chunk(d,at,end-at).decode('ascii'))
            sounds=refs(ref(base));groups=refs(ref(base+32));records={}
            prefix=f'GRP_VO_{code.upper()}_'
            owned_groups=[g for g in groups if u32(d,g)<len(strings) and strings[u32(d,g)].startswith(prefix)]
            uses={}
            for g in owned_groups:
                for item in refs(ref(g+32)):uses[u32(d,item)]=uses.get(u32(d,item),0)+1
            ambiguous_stems=set()
            for g in owned_groups:
                sid=u32(d,g);name=strings[sid] if sid<len(strings) else ''
                if not name.startswith(prefix):continue
                for item in refs(ref(g+32)):
                    fid=u32(d,item);head=chunk(d,u32(d,g+16)+u32(d,item+4),u32(d,item+8))
                    audio=chunk(d,u32(d,g+24)+u32(d,item+12),u32(d,item+16))
                    if head[:4] not in (b'RWSD',b'RBNK'):continue
                    size=u32(head,8);combined=head[:size]+bytes(-size%32)+audio
                    resource=WaveResource(combined)
                    shared=uses[fid]>1 and head[:4]==b'RBNK'
                    stem=name[len(prefix):]+(f'.shared-{fid}' if shared else '')+('.brwsd' if head[:4]==b'RWSD' else '.brbnk')
                    if stem in self.banks and self.banks[stem].resource!=combined:
                        previous=self.banks.pop(stem);ambiguous_stems.add(stem)
                        previous.stem=stem.rsplit('.',1)[0]+f'.ambiguous-{previous.file_id}.'+stem.rsplit('.',1)[1]
                        previous.writable=False;self.banks[previous.stem]=previous
                    if stem in ambiguous_stems:
                        stem=stem.rsplit('.',1)[0]+f'.ambiguous-{fid}.'+stem.rsplit('.',1)[1];shared=True
                    bank=VoiceBank(fid,stem,combined,writable=not shared and stem.split('.')[0] in SUPPORTED_GROUPS);self.banks[stem]=bank;records[fid]=(bank,resource.data_wave_map())
            for sid,s in enumerate(sounds):
                fid=u32(d,s+4)
                if fid not in records or d[s+22]!=3:continue
                bank,mapping=records[fid];symbol=strings[u32(d,s)];index=u32(d,ref(s+24))
                for wi in mapping.get(index,[]):bank.labels.setdefault(wi,[]).append((sid,symbol))
            # The runtime addresses group + extension, not an individual bank
            # file ID. A typed override must not be applied to two native banks.
            typed_groups={}
            for bank in self.banks.values():
                typed_groups.setdefault((bank.stem.split('.')[0],bank.resource[:4]),[]).append(bank)
            for banks in typed_groups.values():
                if len({bank.file_id for bank in banks})>1:
                    for bank in banks:bank.writable=False
            # Files outside dedicated voice groups may contain other characters.
            # They are never exported as a per-character replacement.
        if not self.banks:raise ValueError(f'No dedicated voice groups found for {code.upper()} in this BRSAR')

EVENT_WORDS={'JP':'Jump','ACT':'Action','FAL':'Fall','LND':'Land','ITM':'Item','OVTAK':'Overtake','PUT':'Place item','PWUP':'Power-up','RET':'Recovery','SCES':'Success','SPN':'Spin','TRW':'Throw','WLE':'Wheelie','FAIL':'Failure','ATK':'Attack','DMG':'Damage','DAMAGE':'Damage','JUMP':'Jump','DASH':'Boost','DSH':'Boost','START':'Start','WIN':'Win','LOSE':'Lose','CAN':'Cannon','GOL':'Finish','TOP':'Top finish','GOD':'Good finish','BAD':'Poor finish','PC':'Player','NPC':'Opponent','END':'End','FALL':'Fall','DRIFT':'Drift','TRICK':'Trick','ITEM':'Item','HIT':'Hit','LAND':'Land'}
def event_label(bank,index):
    labels=bank.labels.get(index,[])
    if labels:
        def word(token):
            match=re.fullmatch(r'([A-Z]+)(\d*)',token)
            return EVENT_WORDS.get(match[1],match[1].title())+(' '+match[2] if match[2] else '') if match else token
        names=[' '.join(word(x) for x in re.sub(r'^VO_[A-Z0-9]+_','',label).split('_')) for _,label in labels]
        return ' / '.join(dict.fromkeys(names))
    group=bank.stem.split('.')[0];name=' '.join(EVENT_WORDS.get(x,x.title()) for x in group.split('_'))
    return f'{name} Â· '+('Sequence bank' if bank.stem.endswith('brbnk') else 'Voice')+f' clip {index+1}'

def map_wavs(entries,archive):
    """Require verified file/wave identity or a unique exact BRSAR event label."""
    mapped={};unmatched=[];duplicates=set();by_id={b.file_id:b for b in archive.banks.values() if b.writable}
    for path,raw in entries:
        if not path.lower().endswith('.wav'):continue
        parts=Path(path.replace('\\','/')).parts;target=None
        m=re.fullmatch(r'Audio\[(\d+)\]\.wav',parts[-1],re.I)
        folder=next((re.match(r'^\[(\d+)\](?:\s+(.*))?$',p) for p in reversed(parts[:-1]) if re.match(r'^\[\d+\]',p)),None)
        if m and folder:
            bank=by_id.get(int(folder[1]));index=int(m[1])
            supplied=folder[2]
            if bank and (not supplied or supplied.casefold()==(f'GRP_VO_{archive.code.upper()}_'+bank.stem.split('.')[0]).casefold()) and index<len(WaveResource(bank.resource).waves):target=(bank.key,index)
        if target is None:
            name=Path(parts[-1]).stem.casefold();matches=[]
            for bank in archive.banks.values():
                if not bank.writable:continue
                for index,labels in bank.labels.items():
                    if any(label.casefold()==name for _,label in labels):matches.append((bank.key,index))
            if len(set(matches))==1:target=matches[0]
        if target is None:unmatched.append(path);continue
        if target in mapped:
            duplicates.add(target);unmatched.extend([mapped[target][0],path]);continue
        mapped[target]=(path,raw)
    for target in duplicates:mapped.pop(target,None)
    return mapped,list(dict.fromkeys(unmatched))

def baseline_path(pack=None):
    from PySide6.QtCore import QSettings
    configured=QSettings('Retro Rewind','Character Manager').value('voice/vanillaArchive','')
    if configured and Path(configured).is_file():return Path(configured)
    # A distribution's BRSAR can already contain modified voices. Restoring
    # vanilla requires the explicitly selected original, not a guessed archive.
    return None

def generated_voices(entries,code,baseline):
    archive=VoiceArchive(baseline,code);mapped,unmatched=map_wavs(entries,archive);bybank={};metadata=[]
    for (key,index),(path,raw) in mapped.items():
        resource=WaveResource(archive.banks[key].resource)
        bybank.setdefault(key,{})[index]=encode_rwav(raw,resource.waves[index])
        metadata.append({'group':key,'wave':index,'source':path,'file_id':archive.banks[key].file_id,'sha256':hashlib.sha256(raw).hexdigest()})
    result={key:WaveResource(archive.banks[key].resource).rebuild(changes) for key,changes in bybank.items()}
    return result,metadata,unmatched

class VoiceSession:
    """Stage wave edits without touching archives or the user's vanilla baseline."""
    def __init__(self,pack,code,slot,baseline):
        self.pack=pack;self.code=code;self.slot=slot;self.archive=VoiceArchive(baseline,code)
        if (code,slot) not in pack.inventory.skins:raise ValueError('Character no longer exists')
        # A filename alias selects the event layout, not the owning character slot.
        from .library import CHARACTER_CODES, CHARACTER_NAMES
        aliases = {code: code for code in CHARACTER_CODES}
        aliases.update({name.upper().replace(' ', '_').replace('.', '').casefold(): code
                        for name, code in zip(CHARACTER_NAMES, CHARACTER_CODES)})
        borrowed = {}
        for asset in pack.inventory.skins[code,slot].files:
            if asset.category != 'Sound':
                continue
            match = re.fullmatch(r'GRP_VO_[A-Z]{2,3}-\d+_(.+\.(?:brwsd|brbnk))\.([\w-]+)',
                                 Path(asset.relpath).name, re.I)
            if match:
                key = next((k for k in self.archive.banks if k.casefold() == match[1].casefold()), match[1])
                source_code = aliases.get(match[2].casefold())
                if source_code is None:
                    continue  # Preserve legacy labels that do not name a vanilla behavior.
                source_archive = borrowed.setdefault(source_code, None)
                if source_archive is None:
                    source_archive = borrowed[source_code] = VoiceArchive(baseline, source_code)
                bank = next((bank for stem, bank in source_archive.banks.items()
                             if stem.casefold() == match[1].casefold()), None)
                if bank is None:
                    raise ValueError('Borrowed voice behavior has no matching bank: ' + match[0])
                self.archive.banks[key] = VoiceBank(bank.file_id, key, bank.resource, bank.labels, bank.writable)
        self.defaults={key:WaveResource(bank.resource) for key,bank in self.archive.banks.items()}
        self.current=dict(self.defaults);self.paths={};self.logicals={};self.errors={};self.pending={};self.missing=set()
        self.expected={};self.pending_sources={};self.pending_raw={}
        self.errors.update({key:'This bank is read-only: the per-skin group loader cannot address it independently' for key,bank in self.archive.banks.items() if not bank.writable})
        self.editable=pack.can_edit_skin(code,slot)
        skin=pack.inventory.skins[code,slot]
        for asset in skin.files:
            if asset.category!='Sound':continue
            m=re.match(r'^GRP_VO_[A-Z]{2,3}-\d+_(.*)$',Path(asset.relpath).name,re.I)
            if not m:continue
            suffix=re.fullmatch(r'(.+\.(?:brwsd|brbnk))(?:\.[\w-]+)?',m[1],re.I)
            key=suffix[1] if suffix else m[1]
            key=next((k for k in self.defaults if k.casefold()==key.casefold()),key)
            if key not in self.defaults:continue
            if key in self.paths:
                self.errors[key]='Multiple installed banks address this group; ambiguous voice aliases must be resolved first'
                continue
            path=pack.asset_path(asset.relpath);self.paths[key]=path;self.logicals[key]=asset.relpath.casefold()
            if not path.is_file():
                self.missing.add(key);self.expected[path]=None;continue
            raw=path.read_bytes();self.expected[path]=hashlib.sha256(raw).hexdigest()
            try:
                r=WaveResource(raw)
                same_events=(r.data_wave_map()==self.defaults[key].data_wave_map()) if r.prefix[:4]==b'RWSD' else r.prefix==self.defaults[key].prefix
                if not same_events or len(r.waves)!=len(self.defaults[key].waves):
                    raise ValueError('Event table differs from vanilla; editing would risk other voices')
                self.current[key]=r
            except ValueError as exc:self.errors[key]=str(exc)
        self.rows=[(key,i) for key in self.defaults for i in range(len(self.defaults[key].waves))]
    def state(self,key,index):
        if not self.archive.banks[key].writable:return 'Bank · read-only'
        if key in self.errors:return 'Incompatible'
        if (key,index) in self.pending:return 'Staged · '+('Original' if self.pending[key,index]==self.defaults[key].waves[index] else 'Replaced')
        if key in self.missing:return 'Missing · vanilla fallback'
        return 'Original' if self.current[key].waves[index]==self.defaults[key].waves[index] else 'Replaced'
    def audio(self,key,index,original=False):
        if key in self.errors and not original:raise ValueError(self.errors[key]+'; use Play Original')
        raw=self.defaults[key].waves[index] if original else self.pending.get((key,index),self.current[key].waves[index])
        return decode_rwav(raw)
    def replace(self,key,index,raw,source):
        if not self.editable:raise PermissionError('Enable Developer Mode to edit distribution voices')
        if key in self.errors:raise ValueError(self.errors[key])
        encoded=encode_rwav(raw,self.defaults[key].waves[index])
        self.pending[key,index]=encoded
        digest=hashlib.sha256(raw).hexdigest()
        saved_source=f'VoiceEditor/{key}/Wave{index}-{digest}.wav'
        self.pending_raw[key,index]=(saved_source,raw)
        self.pending_sources[key,index]={'group':key,'wave':index,'source':Path(source).name,
            'file_id':self.archive.banks[key].file_id,'sha256':digest,'source_payload':saved_source}
    def restore(self,key,index):
        if not self.editable:raise PermissionError('This character is read-only')
        if key in self.errors:raise ValueError(self.errors[key])
        self.pending[key,index]=self.defaults[key].waves[index];self.pending_sources[key,index]=None;self.pending_raw.pop((key,index),None)
    def revert(self):self.pending.clear();self.pending_sources.clear();self.pending_raw.clear()
    def import_wavs(self,entries):
        mapped,unmatched=map_wavs(entries,self.archive);failed=[]
        for (key,index),(path,raw) in mapped.items():
            try:self.replace(key,index,raw,path)
            except ValueError as exc:failed.append(f'{path}: {exc}')
        return len(mapped)-len(failed),unmatched,failed
    def plan(self):
        from .operations import EditPlan
        import json
        if not self.editable:raise PermissionError('This character is read-only')
        if self.pack.inventory.skins.get((self.code,self.slot)) is None:raise ValueError('Character no longer exists')
        plan=EditPlan(f'Edit voices for {self.code.upper()} slot {self.slot}')
        patch=self.pack.is_patch_skin(self.code,self.slot)
        skin=self.pack.inventory.skins[self.code,self.slot]
        folder=(self.pack.patch_directories.get((self.code,self.slot)) or self.pack._character_patch_directory(skin.name,self.code,self.slot)) if patch else self.pack.character/'Sound'
        root=self.pack.patches_path if patch else self.pack.character
        if not folder.resolve().is_relative_to(root.resolve()):raise ValueError('Linked sound folder cannot be edited')
        for key in dict.fromkeys(key for key,index in self.pending):
            if key in self.errors:raise ValueError(self.errors[key])
            changes={i:raw for (k,i),raw in self.pending.items() if k==key}
            payload=self.current[key].rebuild(changes)
            logical=f'Sound/GRP_VO_{self.code.upper()}-{self.slot}_{key}'
            destination=self.paths.get(key)
            if destination is None or (patch and not destination.resolve().is_relative_to(self.pack.patches_path.resolve())):
                destination=folder/Path(logical).name
            for logical_name, physical in {**self.pack.distribution_assets, **self.pack.patch_assets}.items():
                if physical.resolve()==destination.resolve() and logical_name not in {logical.casefold(),self.logicals.get(key)}:
                    raise ValueError(f'Sound file is shared with another logical resource: {destination.name}')
            if destination.exists():
                if destination not in self.paths.values():raise ValueError(f'An unrelated sound resource occupies {destination.name}')
                plan.replace_existing.add(destination)
                plan.expected[destination]=self.expected[destination]
            else:plan.expected[destination]=None
            plan.writes[destination]=payload
            plan.metadata.append(f'{key}: {len(changes)} wave edits; all other waves and event tables preserved')
        if plan.writes:
            for asset in skin.files:
                if asset.category=='Sound' and asset.relpath.lower().endswith('.silent'):
                    mute=self.pack.asset_path(asset.relpath)
                    if patch and not mute.resolve().is_relative_to(self.pack.patches_path.resolve()):
                        raise ValueError('An inherited distribution silence override blocks these voices. Remove that override explicitly in Developer Mode first.')
                    if mute.is_file():
                        for logical_name, physical in {**self.pack.distribution_assets, **self.pack.patch_assets}.items():
                            if physical.resolve()==mute.resolve() and logical_name!=asset.relpath.casefold():raise ValueError('Silence flag is shared with another resource')
                        removal=self.pack.delete_resource(self.code,self.slot,asset.relpath)
                        plan.deletes.update(removal.deletes);plan.writes.update(removal.writes)
                        plan.replace_existing.update(removal.replace_existing)
                        plan.expected[mute]=hashlib.sha256(mute.read_bytes()).hexdigest()
                        plan.expected.update({p:self.pack._snapshot[p] for p in removal.writes if p in self.pack._snapshot})
                        plan.metadata.append('Remove this character-owned silence flag so edited voices can play')
            metadata_path=(folder/self.pack.PATCH_META_FILENAME if patch else self.pack.character/'SourceResources'/f'{self.code}-{self.slot}-metadata.json')
            if metadata_path.is_symlink() or not metadata_path.resolve().is_relative_to(root.resolve()):raise ValueError('Linked voice metadata cannot be edited')
            metadata=json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else {}
            if patch:metadata.update(json.loads(self.pack._skin_metadata(self.code,self.slot,skin.name,skin.author)))
            prior=metadata.get('voice',{})
            if not isinstance(prior,dict) or prior.get('version',1)!=1:raise ValueError('Unsupported voice metadata version; preview remains available, but editing would discard metadata')
            entries={(v['group'],v['wave']):v for v in prior.get('replacements',[]) if isinstance(v,dict) and 'group' in v and 'wave' in v}
            for key,value in self.pending_sources.items():
                if value is None:entries.pop(key,None)
                else:entries[key]=value
            metadata['voice']={**prior,'version':1,'base_character':self.code,'encoding':'PCM16BE','replacements':list(entries.values())}
            plan.writes[metadata_path]=(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
            plan.expected[metadata_path]=hashlib.sha256(metadata_path.read_bytes()).hexdigest() if metadata_path.exists() else None
            if metadata_path.exists():plan.replace_existing.add(metadata_path)
            if self.pending_raw:
                from .mkchara import zip_members
                bundle=(folder if patch else self.pack.character/'SourceResources')/f'{self.code}-{self.slot}-source.rrcm-source'
                if bundle.is_symlink() or not bundle.resolve().is_relative_to(root.resolve()):raise ValueError('Linked voice source bundle cannot be edited')
                preserved={};previous=bundle.read_bytes() if bundle.exists() else None
                if previous is not None:
                    with zipfile.ZipFile(io.BytesIO(previous)) as archive:
                        preserved={name:archive.read(info) for name,info in zip_members(archive).items()}
                for name,raw in self.pending_raw.values():
                    matches=[n for n in preserved if n.casefold()==name.casefold()]
                    if matches and preserved[matches[0]]!=raw:raise ValueError('An unrelated source occupies '+name)
                    if not matches:preserved[name]=raw
                output=io.BytesIO()
                with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
                    for name,raw in preserved.items():archive.writestr(name,raw)
                with zipfile.ZipFile(io.BytesIO(output.getvalue())) as checked:zip_members(checked)
                plan.writes[bundle]=output.getvalue()
                plan.expected[bundle]=hashlib.sha256(previous).hexdigest() if previous is not None else None
                if previous is not None:plan.replace_existing.add(bundle)
                plan.metadata.append('Original replacement WAVs retained in the existing portable source bundle')
            plan.warnings.append('Per-skin voices require the compatible loose RWSD/RBNK voice loader. PCM voices use more memory than ADPCM; validate on Dolphin/Wii. Shared menu banks are not replaced.')
        return plan
