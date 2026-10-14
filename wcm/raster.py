"""Orthographic textured software renderer with UV interpolation and depth buffer.

No Qt objects or source writes. Called off the GUI thread. TEV is intentionally
not emulated; transparency uses alpha cutout and sorted translucent blending.
"""
import numpy as np
from math import sin, cos, radians
from .renderstate import compare, alpha_pass, blending, blend_colors


def wrap(values,mode):
    if mode==1: return values-np.floor(values)
    if mode==2:
        v=np.mod(values,2)
        return np.where(v>1,2-v,v)
    return np.clip(values,0,1)


def render_mesh(mesh,width,height,yaw=24,pitch=-9,zoom=1,wireframe=False,cancel=None):
    width=max(32,min(960,int(width)));height=max(32,min(960,int(height)))
    out=np.empty((height,width,4),dtype=np.uint8);out[:]=[16,27,43,255]
    depth=np.full((height,width),-np.inf)
    if not mesh or not mesh.triangles: return out
    verts=np.asarray(mesh.vertices,dtype=np.float64)
    faces=np.asarray(mesh.triangles,dtype=np.int32)
    used=np.unique(faces[:,:3]);bounds=verts[used]
    lo,hi=bounds.min(axis=0),bounds.max(axis=0)
    verts=verts-(lo+hi)/2
    radius=max(float((hi-lo).max()),1e-5)
    y,p=radians(yaw),radians(pitch)
    x,z=cos(y)*verts[:,0]+sin(y)*verts[:,2],-sin(y)*verts[:,0]+cos(y)*verts[:,2]
    yy,zz=cos(p)*verts[:,1]-sin(p)*z,sin(p)*verts[:,1]+cos(p)*z
    scale=min(width,height)*.76*zoom/radius
    screen=np.column_stack([width/2+x*scale,height/2-yy*scale,zz])
    uv=np.asarray(mesh.uvs if mesh.uvs else [(0,0)]*len(verts))
    textures=[np.asarray(m.texture,dtype=np.uint8) if m.texture is not None else None for m in mesh.materials]
    # Opaque first, translucent back to front. Same depth convention as camera.
    order=sorted(range(len(faces)),key=lambda i:(bool(mesh.materials[faces[i,3]].translucent) if mesh.materials else False,
                   float(screen[faces[i,:3],2].mean())))
    for step,index in enumerate(order):
        if step%64==0 and cancel and cancel(): return None
        a,b,c,mi=faces[index];v=screen[[a,b,c]]
        minx=max(0,int(np.floor(v[:,0].min())));maxx=min(width-1,int(np.ceil(v[:,0].max())))
        miny=max(0,int(np.floor(v[:,1].min())));maxy=min(height-1,int(np.ceil(v[:,1].max())))
        if maxx<minx or maxy<miny: continue
        x0,y0=v[0,:2];x1,y1=v[1,:2];x2,y2=v[2,:2]
        den=(y1-y2)*(x0-x2)+(x2-x1)*(y0-y2)
        if abs(den)<1e-8: continue
        material=mesh.materials[mi] if mesh.materials else None
        cull=material.cull if material else 0
        # GX authored front faces are clockwise in model/NDC space.
        if cull==3 or (cull==2 and den<=0) or (cull==1 and den>=0): continue
        xx,yy=np.meshgrid(np.arange(minx,maxx+1)+.5,np.arange(miny,maxy+1)+.5)
        w0=((y1-y2)*(xx-x2)+(x2-x1)*(yy-y2))/den
        w1=((y2-y0)*(xx-x2)+(x0-x2)*(yy-y2))/den
        w2=1-w0-w1
        zz=w0*v[0,2]+w1*v[1,2]+w2*v[2,2]
        view=depth[miny:maxy+1,minx:maxx+1]
        mask=(w0>=-1e-7)&(w1>=-1e-7)&(w2>=-1e-7)
        if material is None or material.depth_test:
            # Positive camera Z is nearer; GX comparisons use increasing depth
            # away from the camera, hence negate both depth values.
            mask &= compare(-zz,-view,material.depth_func if material else 3)
        if wireframe:
            # Edge distance in pixels, independent of triangle size.
            alt=[abs(den)/max(np.linalg.norm(v[j,:2]-v[k,:2]),1e-9) for j,k in ((1,2),(2,0),(0,1))]
            mask &= np.minimum.reduce([w0*alt[0],w1*alt[1],w2*alt[2]])<.85
        if not mask.any(): continue
        material=mesh.materials[mi] if mesh.materials else None
        texture=textures[mi] if textures else None
        if texture is not None and not wireframe:
            st=w0[...,None]*uv[a]+w1[...,None]*uv[b]+w2[...,None]*uv[c]
            # GX UV origin follows top-left image convention.
            sx=wrap(st[...,0],material.wrap_s);sy=wrap(st[...,1],material.wrap_t)
            tx=np.minimum((sx*texture.shape[1]).astype(int),texture.shape[1]-1)
            ty=np.minimum((sy*texture.shape[0]).astype(int),texture.shape[0]-1)
            colors=texture[ty,tx].copy()
        else:
            colors=np.empty((*xx.shape,4),dtype=np.uint8);colors[:]=[185,193,205,255]
        mask &= alpha_pass(colors[...,3],material.alpha_test if material else (4,16,7,0,0))
        if not mask.any(): continue
        target=out[miny:maxy+1,minx:maxx+1]
        if blending(material):
            blended=blend_colors(colors,target,material)
            target[mask,:3]=blended[mask]
        else:
            target[mask,:3]=colors[mask,:3]
        if material is None or (material.depth_test and material.depth_write):
            view[mask]=zz[mask]
    return out
