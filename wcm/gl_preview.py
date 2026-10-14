"""Cached OpenGL geometry/textures for interactive bind-pose camera movement.

Qt owns the context. Assets upload once per mesh; orbit/zoom change the camera
and transparent draw order. The CPU rasterizer remains available without OpenGL.
"""
from math import cos, sin, radians
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QMatrix4x4, QPainter, QColor, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from .renderstate import blending

VERTEX = '''#version 120
attribute vec3 position;
attribute vec2 texcoord;
uniform mat4 camera;
varying vec2 uv;
void main() { gl_Position = camera * vec4(position, 1.0); uv = texcoord; }
'''
FRAGMENT = '''#version 120
uniform sampler2D image;
uniform bool textured;
uniform int alphaComp0;
uniform int alphaComp1;
uniform int alphaRef0;
uniform int alphaRef1;
uniform int alphaLogic;
varying vec2 uv;
bool compareAlpha(float a, int r, int c) {
    float b = float(r);
    if (c == 0) return false;
    if (c == 1) return a < b;
    if (c == 2) return a == b;
    if (c == 3) return a <= b;
    if (c == 4) return a > b;
    if (c == 5) return a != b;
    if (c == 6) return a >= b;
    return true;
}
void main() {
    vec4 color = textured ? texture2D(image, uv) : vec4(.725,.757,.804,1.0);
    float a = floor(color.a * 255.0 + 0.5);
    bool first = compareAlpha(a, alphaRef0, alphaComp0);
    bool second = compareAlpha(a, alphaRef1, alphaComp1);
    bool pass = first && second;
    if (alphaLogic == 1) pass = first || second;
    if (alphaLogic == 2) pass = first != second;
    if (alphaLogic == 3) pass = first == second;
    if (!pass) discard;
    gl_FragColor = color;
}
'''


def camera_matrix(width,height,yaw,pitch,zoom,radius):
    y,p=radians(yaw),radians(pitch)
    rotation=np.array([[cos(y),0,sin(y)],
                       [sin(p)*sin(y),cos(p),-sin(p)*cos(y)],
                       [-cos(p)*sin(y),sin(p),cos(p)*cos(y)]])
    scale=min(width,height)*.76*zoom/radius
    out=np.eye(4)
    out[:3,:3]=np.diag([2*scale/max(width,1),2*scale/max(height,1),-1/(radius*2)])@rotation
    return out


class GLPreview(QOpenGLWidget):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner=owner
        fmt=QSurfaceFormat();fmt.setVersion(2,0)
        fmt.setDepthBufferSize(24);fmt.setSamples(4)
        self.setFormat(fmt)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.program=None;self.groups=[];self.uploaded=None
        self.radius=1.;self.failed=False;self.upload_count=0;self.draw_count=0

    def initializeGL(self):
        try:
            self.gl=self.context().functions();self.gl.initializeOpenGLFunctions()
            self.program=QOpenGLShaderProgram(self)
            for kind,source in ((QOpenGLShader.ShaderTypeBit.Vertex,VERTEX),
                                (QOpenGLShader.ShaderTypeBit.Fragment,FRAGMENT)):
                if not self.program.addShaderFromSourceCode(kind,source): raise RuntimeError(self.program.log())
            self.program.bindAttributeLocation('position',0)
            self.program.bindAttributeLocation('texcoord',1)
            if not self.program.link(): raise RuntimeError(self.program.log())
            self.context().aboutToBeDestroyed.connect(self.release_resources)
        except Exception as exc: self.fallback(exc)

    def fallback(self,exc):
        if self.failed: return
        self.failed=True
        QTimer.singleShot(0,lambda:self.owner._software_fallback(str(exc)))

    def release_resources(self):
        self.makeCurrent()
        for buffer,edges,texture,_,_,_,_ in self.groups:
            buffer.destroy();edges.destroy()
            if texture is not None: texture.destroy()
        self.groups=[];self.uploaded=None
        if self.program is not None:
            self.program.removeAllShaders();self.program=None
        self.doneCurrent()

    def upload(self,mesh):
        for buffer,edges,texture,_,_,_,_ in self.groups:
            buffer.destroy();edges.destroy()
            if texture is not None: texture.destroy()
        self.groups=[]
        if mesh is None: self.uploaded=mesh;return
        verts=np.asarray(mesh.vertices,dtype=np.float32)
        faces=np.asarray(mesh.triangles,dtype=np.int32)
        bounds=verts[np.unique(faces[:,:3])];lo,hi=bounds.min(0),bounds.max(0)
        verts=verts-(lo+hi)/2
        self.radius=max(float((hi-lo).max()),1e-5)
        uv=np.asarray(mesh.uvs if mesh.uvs else [(0,0)]*len(verts),dtype=np.float32)
        data=np.column_stack((verts,uv))
        materials=mesh.materials
        for mi in np.unique(faces[:,3]):
            indices=faces[faces[:,3]==mi,:3]
            triangles=np.ascontiguousarray(data[indices].reshape(-1,5),dtype=np.float32)
            lines=np.ascontiguousarray(data[indices[:,[0,1,1,2,2,0]]].reshape(-1,5),dtype=np.float32)
            buffers=[]
            for array in (triangles,lines):
                buf=QOpenGLBuffer();buf.create();buf.bind()
                buf.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
                raw=array.tobytes();buf.allocate(raw,len(raw));buf.release();buffers.append(buf)
            mat=materials[int(mi)] if materials else None
            texture=None
            if mat and mat.texture is not None:
                im=mat.texture.convert('RGBA');raw=im.tobytes()
                qimage=QImage(raw,im.width,im.height,im.width*4,QImage.Format.Format_RGBA8888).copy()
                texture=QOpenGLTexture(qimage)
                texture.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
                texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
                wraps=(QOpenGLTexture.WrapMode.ClampToEdge,QOpenGLTexture.WrapMode.Repeat,QOpenGLTexture.WrapMode.MirroredRepeat)
                texture.setWrapMode(QOpenGLTexture.CoordinateDirection.DirectionS,wraps[mat.wrap_s] if 0<=mat.wrap_s<3 else wraps[0])
                texture.setWrapMode(QOpenGLTexture.CoordinateDirection.DirectionT,wraps[mat.wrap_t] if 0<=mat.wrap_t<3 else wraps[0])
            centers=verts[indices].mean(axis=1)
            self.groups.append((*buffers,texture,mat,len(triangles),centers.mean(axis=0),centers))
        self.uploaded=mesh;self.upload_count+=1

    def paintGL(self):
        if self.failed or self.program is None: return
        try:
            gl=self.gl;view=self.owner
            gl.glClearColor(16/255,27/255,43/255,1)
            gl.glClear(0x4000|0x100)
            if self.uploaded is not view.mesh: self.upload(view.mesh)
            if view.mesh:
                gl.glFrontFace(0x0900)
                matrix=camera_matrix(self.width(),self.height(),view.yaw,view.pitch,view.zoom,self.radius)
                self.program.bind()
                self.program.setUniformValue('camera',QMatrix4x4(matrix.ravel().tolist()))
                # Explicit integer uniforms: Python numeric overload resolution
                # can otherwise choose Qt's float setter for sampler/bool values.
                gl.glUniform1i(self.program.uniformLocation('image'),0)
                # Opaque materials first; translucent material groups back to front.
                groups=sorted(self.groups,key=lambda g:(bool(g[3] and g[3].translucent),-float(matrix[2,:3]@g[5])))
                for buffer,edges,texture,mat,count,center,centers in groups:
                    cull=mat.cull if mat else 0
                    if cull==3: continue
                    if cull:
                        gl.glEnable(0x0b44);gl.glCullFace(0x0405 if cull==2 else 0x0404)
                    else: gl.glDisable(0x0b44)
                    if mat is None or mat.depth_test:
                        gl.glEnable(0x0b71);gl.glDepthFunc(0x0200+(mat.depth_func if mat else 3))
                        gl.glDepthMask(mat.depth_write if mat else True)
                    else: gl.glDisable(0x0b71);gl.glDepthMask(False)
                    if blending(mat):
                        gl.glEnable(0x0be2)
                        src=(0,1,0x0306,0x0307,0x0302,0x0303,0x0304,0x0305)
                        dst=(0,1,0x0300,0x0301,0x0302,0x0303,0x0304,0x0305)
                        gl.glBlendFunc(1 if mat.blend_subtract else src[mat.blend_src],
                                       1 if mat.blend_subtract else dst[mat.blend_dst])
                        gl.glBlendEquation(0x800b if mat.blend_subtract else 0x8006)
                    else: gl.glDisable(0x0be2)
                    alpha=mat.alpha_test if mat else (4,16,7,0,0)
                    for name,value in zip(('alphaComp0','alphaRef0','alphaComp1','alphaRef1','alphaLogic'),alpha):
                        gl.glUniform1i(self.program.uniformLocation(name),int(value))
                    target=edges if view.wireframe else buffer;target.bind()
                    self.program.enableAttributeArray(0);self.program.enableAttributeArray(1)
                    self.program.setAttributeBuffer(0,0x1406,0,3,20)
                    self.program.setAttributeBuffer(1,0x1406,12,2,20)
                    textured=texture is not None and not view.wireframe
                    gl.glUniform1i(self.program.uniformLocation('textured'),int(textured))
                    if textured: texture.bind(0)
                    if blending(mat) and not mat.depth_write and not view.wireframe:
                        # Sort only no-depth-write faces; contiguous runs share
                        # a draw call. Vertex/texture buffers remain cached.
                        order=np.argsort(-(centers@matrix[2,:3]),kind='stable')
                        start=last=int(order[0])
                        for index in order[1:]:
                            index=int(index)
                            if index==last+1: last=index;continue
                            gl.glDrawArrays(0x0004,start*3,(last-start+1)*3)
                            start=last=index
                        gl.glDrawArrays(0x0004,start*3,(last-start+1)*3)
                    else:
                        gl.glDrawArrays(0x0001 if view.wireframe else 0x0004,0,count*2 if view.wireframe else count)
                    if textured: texture.release()
                    target.release()
                self.program.disableAttributeArray(0);self.program.disableAttributeArray(1)
                self.program.release()
                gl.glDepthMask(True);gl.glDisable(0x0be2);gl.glDisable(0x0b44);gl.glDisable(0x0b71)
                self.draw_count+=1;view._render_key=view._key()
            painter=QPainter(self);painter.setPen(QColor('#96acc4'))
            if view.mesh is None:
                painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'Select a BRRES to preview')
            painter.drawText(12,self.height()-14,'Orbit: drag   •   Zoom: scroll   •   Reset: double-click')
            painter.end()
        except Exception as exc: self.fallback(exc)
