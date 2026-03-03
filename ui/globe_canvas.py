# File: ui/globe_canvas.py
import numpy as np
import traceback
import matplotlib
# [Critical] Force Agg backend to prevent base map generation crashes
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cv2  # Ensure opencv-python is installed

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from vispy import scene
from vispy.geometry import create_sphere
from vispy.visuals.filters import TextureFilter

class Globe3DCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.available = True
        
        self.base_width = 4096
        self.base_height = 2048
        self.global_texture_data = None
        
        try:
            # 1. Initialize canvas (deep space background)
            self.canvas = scene.SceneCanvas(keys='interactive', show=False, app='pyqt6', bgcolor='#050510')
            self.layout.addWidget(self.canvas.native)

            # 2. Configure view
            self.view = self.canvas.central_widget.add_view()
            self.view.camera = 'turntable'
            self.view.camera.fov = 45
            self.view.camera.distance = 2.5
            # [Critical] Initial view adjustment: position China region (around 100°E) at screen center
            self.view.camera.azimuth = -255 
            self.view.camera.elevation = 30

            # 3. Create earth mesh
            self.sphere = scene.visuals.Mesh(
                meshdata=create_sphere(rows=100, cols=200, radius=1.0), 
                parent=self.view.scene, 
                color='white', shading=None
            )

            # 4. Generate static geographic base map
            print("[3D] Generating global base map with Cartopy (Agg)...")
            self.base_map = self._generate_base_map()
            self.global_texture_data = self.base_map.copy()

            # 5. Compute UV
            vertices = self.sphere.mesh_data.get_vertices()
            x, y, z = vertices[:, 0], vertices[:, 1], vertices[:, 2]
            v = (np.arccos(np.clip(z, -1.0, 1.0)) / np.pi).astype(np.float32)
            u = ((np.arctan2(y, x) + np.pi) / (2 * np.pi)).astype(np.float32)
            texcoords = np.stack((u, v), axis=1)

            # 6. Initialize texture
            # Must pass numpy array, not object
            self.tex_filter = TextureFilter(texture=self.global_texture_data, texcoords=texcoords)
            self.sphere.attach(self.tex_filter)
            print("[3D] Initialization complete.")
            
        except Exception as e:
            self.available = False
            traceback.print_exc()
            try:
                self.layout.addWidget(QLabel(f"3D Error: {e}"))
            except: pass

    def _generate_base_map(self):
        """Generate global base map (using Agg backend)."""
        try:
            dpi = 100
            fig = plt.figure(figsize=(self.base_width/dpi, self.base_height/dpi), dpi=dpi)
            canvas = FigureCanvasAgg(fig)
            ax = fig.add_axes([0, 0, 1, 1], projection=ccrs.PlateCarree())
            
            ax.set_global()
            # ── Space-dark cartographic palette for 3D globe ──────────
            # Axes bg: cosmic void between land/ocean polygons
            ax.set_facecolor('#050B14')
            # Ocean: near-void deep blue
            ax.add_feature(cfeature.OCEAN.with_scale('110m'),
                           facecolor='#050B14', edgecolor='none')
            # Land: dark olive-forest, distinct from ocean without
            # competing with satellite data colour renditions
            ax.add_feature(cfeature.LAND.with_scale('110m'),
                           facecolor='#0E1F16', edgecolor='none')
            # Rivers: barely-visible waterway traces
            ax.add_feature(cfeature.RIVERS.with_scale('110m'),
                           edgecolor='#0B2540', linewidth=0.35, alpha=0.7)
            # Borders: thin dark-blue nation outlines
            ax.add_feature(cfeature.BORDERS.with_scale('110m'),
                           edgecolor='#1A3A5A', linewidth=0.4, linestyle='-')
            # Coastlines: steel blue — the primary visual anchor
            ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
                           edgecolor='#2A6CA0', linewidth=0.7)
            # Graticule: near-invisible lat/lon grid lines
            ax.gridlines(linewidth=0.25, color='#0D1E30',
                         alpha=0.8, linestyle='-')
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
            
            return data.astype(np.float32) / 255.0
            
        except Exception as e:
            print(f"[3D] Base map generation failed: {e}. Using grid.")
            img = np.zeros((self.base_height, self.base_width, 3), dtype=np.float32)
            img[::100, :] = 0.3; img[:, ::100] = 0.3
            return img

    def update_texture(self, img_data, extent=None, alpha=1.0):
        """
        Update texture overlay (supports alpha parameter).
        """
        if not getattr(self, 'available', True): return
        
        try:
            if img_data.dtype != np.float32: img_data = img_data.astype(np.float32)
            if img_data.ndim == 2: img_data = np.dstack((img_data, img_data, img_data))
            
            final_tex = None
            
            # [Branch 1] No coordinates (native full disk) -> direct overlay, transparency blending not yet supported
            if extent is None:
                final_tex = np.ascontiguousarray(img_data)  # No flip, assume data is already top-down
            
            # [Branch 2] With coordinates (Plate Carree) -> perform geospatial alignment + transparency blending
            else:
                west, east, south, north = extent
                composite = self.base_map.copy()
                
                x_min = int((west + 180) / 360 * self.base_width)
                x_max = int((east + 180) / 360 * self.base_width)
                y_min = int((90 - north) / 180 * self.base_height)
                y_max = int((90 - south) / 180 * self.base_height)
                
                x_min = max(0, x_min); x_max = min(self.base_width, x_max)
                y_min = max(0, y_min); y_max = min(self.base_height, y_max)
                
                target_w = x_max - x_min
                target_h = y_max - y_min
                
                if target_w > 0 and target_h > 0:
                    import cv2
                    # At this point, img_data is already high-resolution (e.g., 3600x1800)
                    # We scale it to the target texture area
                    resized_sat = cv2.resize(img_data, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
                    
                    # [Key Fix 2] Lower mask threshold to fix edge cracks
                    # Changed from > 0.1 (too aggressive) to > 0.01
                    # Keep pixels as long as they are not pure black (invalid fill)
                    mask = np.sum(resized_sat, axis=2) > 0.01 
                    
                    # Alpha blending
                    base_region = composite[y_min:y_max, x_min:x_max]
                    blended = (base_region[mask] * (1.0 - alpha)) + (resized_sat[mask] * alpha)
                    
                    # Fill back
                    temp_region = base_region.copy()
                    temp_region[mask] = blended
                    composite[y_min:y_max, x_min:x_max] = temp_region
                
                # [Critical] Do not use np.flipud to ensure correct north-up orientation
                final_tex = np.ascontiguousarray(composite)

            # Trigger VisPy update
            self.tex_filter.texture = final_tex
            self.canvas.update()
            
        except Exception as e:
            print(f"[3D] Texture update error: {e}")
            traceback.print_exc()

    def reset_camera(self):
        if getattr(self, 'available', False):
            self.view.camera.set_range()

    def clear_overlay(self):
        """Reset globe texture to base map only."""
        if not getattr(self, 'available', True):
            return
        try:
            self.tex_filter.texture = np.ascontiguousarray(self.base_map.copy())
            self.canvas.update()
        except Exception as e:
            print(f"[3D] clear_overlay error: {e}")
