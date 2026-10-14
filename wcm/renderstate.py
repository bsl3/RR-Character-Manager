"""GX material comparisons/blending shared by the preview backends."""
import numpy as np

def compare(value,reference,function):
    if function==0: return np.zeros_like(value,dtype=bool)
    if function==1: return value<reference
    if function==2: return value==reference
    if function==3: return value<=reference
    if function==4: return value>reference
    if function==5: return value!=reference
    if function==6: return value>=reference
    return np.ones_like(value,dtype=bool)

def alpha_pass(alpha,test):
    c0,r0,c1,r1,logic=test
    a,b=compare(alpha,r0,c0),compare(alpha,r1,c1)
    return (a&b,a|b,a^b,~(a^b))[logic]

def blending(material):
    return bool(material and (material.translucent if material.blend_enabled is None else material.blend_enabled))

def blend_colors(source,target,material):
    src=source.astype(np.float64)/255.;dst=target.astype(np.float64)/255.
    def factor(mode,is_source):
        if mode==0: return 0.
        if mode==1: return 1.
        if mode in (2,3):
            color=dst[...,:3] if is_source else src[...,:3]
            return color if mode==2 else 1-color
        alpha=src[...,3:4] if mode in (4,5) else dst[...,3:4]
        return alpha if mode in (4,6) else 1-alpha
    if material.blend_subtract: color=dst[...,:3]-src[...,:3]
    else: color=src[...,:3]*factor(material.blend_src,True)+dst[...,:3]*factor(material.blend_dst,False)
    return np.rint(np.clip(color,0,1)*255).astype(np.uint8)
