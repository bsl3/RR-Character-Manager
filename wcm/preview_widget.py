"""Qt viewport for a read-only, textured BRRES bind-pose preview.

This is intentionally a lightweight native mesh viewer, not embedded BrawlCrate.
Cached OpenGL draws on supported desktops; a CPU fallback works without a GL context.
"""
from __future__ import annotations

from math import cos, sin, radians, sqrt
from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import QImage, QColor, QBrush, QPainter, QPen, QPolygonF, QGuiApplication
from PySide6.QtWidgets import QWidget
from .preview3d import PreviewMesh
from .raster import render_mesh
from threading import Event
from concurrent.futures import ThreadPoolExecutor
_RENDER_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rrcm-raster")


class MeshPreviewWidget(QWidget):
    """Drag to orbit, scroll to zoom; reuse GPU resources throughout camera motion."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(330, 275)
        self.setMouseTracking(True)
        self.setToolTip('Left-drag to orbit · Mouse wheel to zoom · Double-click to reset')
        self._cancel_render = Event()
        self._disposed = False
        self._frame = None
        self._render_key = None
        self._future = None
        self._requested_key = None
        self._generation = 0
        self._poll = QTimer(self)
        self._poll.setInterval(16)
        self._poll.timeout.connect(self._poll_render)
        self._poll.start()
        self.mesh: PreviewMesh | None = None
        self.yaw = 24.0
        self.pitch = -9.0
        self.zoom = 1.0
        self.wireframe = False
        self._last = None
        self._center = (0.0,0.0,0.0)
        self._radius = 1.0
        self._colors = ('#bcd8f8','#c7b4ea','#93cfcd','#e1c3a8','#b2c6e6','#e1b2c8')
        self._gl = None
        if QGuiApplication.platformName() not in ('offscreen','minimal'):
            from .gl_preview import GLPreview
            self._gl = GLPreview(self)
            self._gl.setGeometry(self.rect())
            self._gl.show()

    def update(self, *args):
        super().update(*args)
        if getattr(self,'_gl',None) is not None: self._gl.update()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self._gl is not None: self._gl.setGeometry(self.rect())

    def _software_fallback(self,reason):
        if self._gl is not None:
            self._gl.hide();self._gl.deleteLater();self._gl=None
        self.setToolTip('Software preview: '+reason)
        self._render_key=None
        self.update()

    def set_mesh(self, mesh: PreviewMesh | None):
        self._cancel_render.set()
        self._cancel_render = Event()
        self.mesh = mesh
        self._frame = None
        self._generation += 1
        self.reset_view()
        if not mesh: return
        # Fit *vertices actually used by faces*, so invisible vertex buffers do
        # not dwarf the rendered model. Keep a fallback for point-cloud mode.
        used = {i for tri in mesh.triangles for i in tri[:3]}
        points = [mesh.vertices[i] for i in used] if used else mesh.vertices
        if not points: return
        mins = [min(v[i] for v in points) for i in range(3)]
        maxs = [max(v[i] for v in points) for i in range(3)]
        self._center = tuple((lo+hi)/2 for lo,hi in zip(mins,maxs))
        self._radius = max(1.,max(hi-lo for lo,hi in zip(mins,maxs)))
        self.update()

    def reset_view(self):
        self._generation += 1
        self.yaw = 24.0
        self.pitch = -9.0
        self.zoom = 1.0
        self.update()

    def set_wireframe(self, value):
        self._generation += 1
        self.wireframe = bool(value)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else: super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._last is not None:
            pos = event.position()
            self._generation += 1
            self.yaw += (pos.x()-self._last.x())*0.6
            self.pitch = max(-89.,min(89.,self.pitch + (pos.y()-self._last.y())*0.6))
            self._last = pos
            self.update()
            event.accept()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
            event.accept()
        else:super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        self.reset_view()
        event.accept()

    def wheelEvent(self,event):
        if event.angleDelta().y():
            self._generation += 1
            self.zoom = max(0.15,min(9.,self.zoom * (1.13 ** (event.angleDelta().y()/120))))
            self.update()
        event.accept()

    def _project(self, point):
        x,y,z = (point[i]-self._center[i] for i in range(3))
        yaw=radians(self.yaw)
        pitch=radians(self.pitch)
        x,z = cos(yaw)*x + sin(yaw)*z, -sin(yaw)*x + cos(yaw)*z
        y,z = cos(pitch)*y - sin(pitch)*z, sin(pitch)*y + cos(pitch)*z
        scale = max(0.01,min(self.width(),self.height())*0.76*self.zoom / self._radius)
        return (self.width()/2 + x*scale, self.height()/2-y*scale, z)

    def _key(self):
        return (id(self.mesh), self.width(), self.height(), self.yaw,
                self.pitch, self.zoom, self.wireframe, self._last is not None)

    def hideEvent(self, event):
        self._generation += 1
        super().hideEvent(event)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._poll.stop()
        self._cancel_render.set()
        if self._future is not None:
            self._future.cancel()
            self._future = None
        if self._gl is not None:
            self._gl.release_resources()
        self.mesh = None
        self._frame = None

    def _poll_render(self):
        if self._disposed:
            return
        if self._gl is not None:
            if self.isVisible() and not self._gl.isValid():
                self._software_fallback('OpenGL context unavailable')
            else: return
        if self._future is not None and self._future.done():
            try:
                result = self._future.result()
                # Publish completed camera frames during motion. Reject frames
                # from a previous model/size, but do not starve continuous drag.
                if result is not None and self._requested_key[:3] == self._key()[:3]:
                    h, w = result.shape[:2]
                    self._frame = QImage(result.data, w, h, w*4,
                                         QImage.Format.Format_RGBA8888).copy()
                    self._render_key = self._requested_key
            except Exception as exc:
                self.setToolTip('Rendering failed: ' + str(exc))
                self._render_key = self._requested_key
            self._future = None
            self.update()
        if self.mesh and self.isVisible() and self._future is None and self._key() != self._render_key:
            self._requested_key = self._key()
            generation = self._generation
            key = self._requested_key
            mesh = self.mesh
            factor = min(1.,240/max(self.width(),self.height())) if self._last is not None else 1.
            cancelled = self._cancel_render
            self._future = _RENDER_POOL.submit(render_mesh, mesh, self.width()*factor, self.height()*factor,
                self.yaw, self.pitch, self.zoom, self.wireframe,
                cancelled.is_set)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#101b2b'))
        if self._frame is not None:
            painter.drawImage(self.rect(), self._frame)
        elif self.mesh:
            painter.setPen(QColor('#8c9fb7'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Rendering textures…')
        else:
            painter.setPen(QColor('#8c9fb7'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Select a BRRES to preview')
        painter.setPen(QColor('#96acc4'))
        painter.drawText(12, self.height()-14, 'Orbit: drag   •   Zoom: scroll   •   Reset: double-click')
        painter.end()
