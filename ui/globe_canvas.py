# File: ui/globe_canvas.py
import logging
from typing import Optional, Tuple
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cv2

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from vispy import scene
from vispy.visuals.filters import TextureFilter

logger = logging.getLogger(__name__)


class Globe3DCanvas(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.available = True

        self.base_width = 4096
        self.base_height = 2048
        self.global_texture_data = None
        # Graticule lines can be mistaken for seam artifacts in 3D view.
        self.show_graticule = False

        try:
            # 1. Initialize canvas (deep space background)
            self.canvas = scene.SceneCanvas(keys='interactive', show=False, app='pyqt6', bgcolor='#050510')
            self.layout.addWidget(self.canvas.native)

            # 2. Configure view
            self.view = self.canvas.central_widget.add_view()
            self.view.camera = 'turntable'
            self.view.camera.fov = 45
            self.view.camera.distance = 2.5
            # Initial view adjustment: position China region (around 100E) at screen center
            self.view.camera.azimuth = -255
            self.view.camera.elevation = 30

            # 3. Create earth mesh with seam-safe UV sphere topology.
            vertices, faces, texcoords = self._create_uv_sphere(
                rows=180,
                cols=360,
                radius=1.0,
            )
            self.sphere = scene.visuals.Mesh(
                vertices=vertices,
                faces=faces,
                parent=self.view.scene,
                color='white',
                shading=None,
            )

            # 4. Generate static geographic base map
            logger.info("[3D] Generating global base map with Cartopy (Agg)...")
            self.base_map = self._generate_base_map()
            self.global_texture_data = self.base_map.copy()

            # 5. Initialize texture
            self.tex_filter = TextureFilter(texture=self.global_texture_data, texcoords=texcoords)
            self.sphere.attach(self.tex_filter)
            logger.info("[3D] Initialization complete.")

        except Exception as e:
            self.available = False
            logger.exception("[3D] Initialization failed")
            try:
                self.layout.addWidget(QLabel(f"3D Error: {e}"))
            except Exception:
                pass

    def _generate_base_map(self) -> np.ndarray:
        """Generate global base map (using Agg backend via FigureCanvasAgg)."""
        try:
            dpi = 100
            fig = plt.figure(figsize=(self.base_width/dpi, self.base_height/dpi), dpi=dpi)
            canvas = FigureCanvasAgg(fig)
            ax = fig.add_axes([0, 0, 1, 1], projection=ccrs.PlateCarree())

            ax.set_global()
            # ── Space-dark cartographic palette for 3D globe ──────────
            ax.set_facecolor('#050B14')
            ax.add_feature(cfeature.OCEAN.with_scale('110m'),
                           facecolor='#050B14', edgecolor='none')
            ax.add_feature(cfeature.LAND.with_scale('110m'),
                           facecolor='#0E1F16', edgecolor='none')
            ax.add_feature(cfeature.RIVERS.with_scale('110m'),
                           edgecolor='#0B2540', linewidth=0.35, alpha=0.7)
            ax.add_feature(cfeature.BORDERS.with_scale('110m'),
                           edgecolor='#1A3A5A', linewidth=0.4, linestyle='-')
            ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
                           edgecolor='#2A6CA0', linewidth=0.7)
            if self.show_graticule:
                ax.gridlines(linewidth=0.2, color='#0D1E30',
                             alpha=0.35, linestyle='-')
            # ─────────────────────────────────────────────────────────

            canvas.draw()

            # Compatibility buffer extraction
            try:
                buf = canvas.buffer_rgba()
                data = np.asarray(buf)
            except AttributeError:
                data = np.frombuffer(canvas.tostring_rgb(), dtype=np.uint8)
                data = data.reshape(canvas.get_width_height()[::-1] + (3,))

            plt.close(fig)

            if data.shape[2] == 4:
                data = data[:, :, :3]

            tex = data.astype(np.float32) / 255.0
            return self._enforce_horizontal_wrap(tex)

        except Exception as e:
            logger.error(f"[3D] Base map generation failed: {e}. Using grid.")
            img = np.zeros((self.base_height, self.base_width, 3), dtype=np.float32)
            img[::100, :] = 0.3
            img[:, ::100] = 0.3
            return img

    @staticmethod
    def _create_uv_sphere(
        rows: int = 180,
        cols: int = 360,
        radius: float = 1.0,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Build a UV sphere mesh with duplicated seam vertices.

        Longitude uses cols+1 samples so U=0 and U=1 are different vertices at
        the same position. This prevents triangles from interpolating across the
        texture seam, which removes the visible zigzag dateline artifact.
        """
        rows = max(8, int(rows))
        cols = max(16, int(cols))

        lats = np.linspace(-0.5 * np.pi, 0.5 * np.pi, rows + 1, dtype=np.float32)
        lons = np.linspace(-np.pi, np.pi, cols + 1, dtype=np.float32)
        lon_grid, lat_grid = np.meshgrid(lons, lats)

        cos_lat = np.cos(lat_grid)
        sin_lat = np.sin(lat_grid)
        cos_lon = np.cos(lon_grid)
        sin_lon = np.sin(lon_grid)

        x = radius * cos_lat * cos_lon
        y = radius * cos_lat * sin_lon
        z = radius * sin_lat
        # Force seam columns to be numerically identical to avoid sub-pixel cracks.
        x[:, -1] = x[:, 0]
        y[:, -1] = y[:, 0]
        z[:, -1] = z[:, 0]
        vertices = np.stack((x, y, z), axis=-1).reshape(-1, 3).astype(np.float32)

        u = (lon_grid + np.pi) / (2.0 * np.pi)
        # Avoid exact U=1.0 boundary sampling; keep right seam at (1-eps).
        u[:, 0] = 0.0
        u[:, -1] = np.nextafter(np.float32(1.0), np.float32(0.0))
        v = 1.0 - ((lat_grid + 0.5 * np.pi) / np.pi)
        texcoords = np.stack((u, v), axis=-1).reshape(-1, 2).astype(np.float32)

        faces = []
        stride = cols + 1
        for i in range(rows):
            base = i * stride
            next_base = (i + 1) * stride
            for j in range(cols):
                a = base + j
                b = base + j + 1
                c = next_base + j
                d = next_base + j + 1
                faces.append((a, b, c))
                faces.append((b, d, c))
        faces_arr = np.asarray(faces, dtype=np.uint32)
        return vertices, faces_arr, texcoords

    @staticmethod
    def _enforce_horizontal_wrap(tex: np.ndarray) -> np.ndarray:
        """
        Force left/right texture edges to match at longitude seam.

        This removes visible seams on the ±180° meridian when the globe mesh
        samples both U=0 and U=1 boundaries.
        """
        if tex is None or tex.ndim < 2 or tex.shape[1] < 2:
            return tex
        # Blend multiple seam columns to hide residual single-pixel line artifacts.
        seam_width = min(3, tex.shape[1] // 2)
        for k in range(seam_width):
            edge = 0.5 * (tex[:, k, ...] + tex[:, -(k + 1), ...])
            tex[:, k, ...] = edge
            tex[:, -(k + 1), ...] = edge
        return tex

    def update_texture(
        self,
        img_data: np.ndarray,
        extent: Optional[Tuple[float, float, float, float]] = None,
        alpha: float = 1.0,
    ) -> None:
        """Update texture overlay (supports alpha parameter)."""
        if not getattr(self, 'available', True):
            return

        # Skip redundant updates when input is unchanged
        sig = (id(img_data), img_data.shape, extent, alpha)
        if getattr(self, '_last_tex_sig', None) == sig:
            return
        self._last_tex_sig = sig

        try:
            if img_data.dtype != np.float32:
                img_data = img_data.astype(np.float32)
            if img_data.ndim == 2:
                img_data = np.dstack((img_data, img_data, img_data))

            final_tex = None

            # No coordinates (native full disk) -> direct overlay
            if extent is None:
                final_tex = np.ascontiguousarray(img_data)

            # With coordinates (Plate Carree) -> geospatial alignment + transparency blending
            else:
                west, east, south, north = extent
                composite = self.base_map.copy()

                x_min = int((west + 180) / 360 * self.base_width)
                x_max = int((east + 180) / 360 * self.base_width)
                y_min = int((90 - north) / 180 * self.base_height)
                y_max = int((90 - south) / 180 * self.base_height)

                x_min = max(0, x_min)
                x_max = min(self.base_width, x_max)
                y_min = max(0, y_min)
                y_max = min(self.base_height, y_max)

                target_w = x_max - x_min
                target_h = y_max - y_min

                if target_w > 0 and target_h > 0:
                    resized_sat = cv2.resize(img_data, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

                    # Keep pixels as long as they are not pure black (invalid fill)
                    mask = np.sum(resized_sat, axis=2) > 0.01

                    # Alpha blending
                    base_region = composite[y_min:y_max, x_min:x_max]
                    blended = (base_region[mask] * (1.0 - alpha)) + (resized_sat[mask] * alpha)

                    temp_region = base_region.copy()
                    temp_region[mask] = blended
                    composite[y_min:y_max, x_min:x_max] = temp_region

                final_tex = np.ascontiguousarray(composite)

            final_tex = self._enforce_horizontal_wrap(final_tex)

            # Trigger VisPy update
            self.tex_filter.texture = final_tex
            self.canvas.update()

        except Exception as e:
            logger.error(f"[3D] Texture update error: {e}", exc_info=True)

    def reset_camera(self) -> None:
        if getattr(self, 'available', False):
            self.view.camera.set_range()

    def clear_overlay(self) -> None:
        """Reset globe texture to base map only."""
        if not getattr(self, 'available', True):
            return
        try:
            self.tex_filter.texture = np.ascontiguousarray(self.base_map.copy())
            self.canvas.update()
        except Exception as e:
            logger.error(f"[3D] clear_overlay error: {e}")

    def cleanup(self) -> None:
        """Release GPU and large array resources."""
        if hasattr(self, 'canvas'):
            try:
                self.canvas.close()
            except Exception:
                pass
        self.base_map = None
        self.global_texture_data = None

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
