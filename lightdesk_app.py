import colorsys
import ipaddress
import json
import math
import socket
import sys
import threading
from collections import deque

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal, QObject, QSettings
from PySide6.QtGui import (
    QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QImage,
    QPainterPath, QPen, QBrush, QScreen, QPixmap, QCursor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QSlider,
    QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QMessageBox, QGraphicsDropShadowEffect
)

BULB_IP = "192.168.1.33"  # Default IP; users can change it in the app.
PORT = 38899

BG = "#111114"
PANEL = "#1A1A1E"
PANEL_ALT = "#222226"
BORDER = "#2D2D33"
TEXT = "#F5F5F7"
MUTED = "#96969F"
ACCENT = "#9B87F5"
GREEN = "#65D6A0"
RED = "#FF7777"


def rgb_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(v))) for v in rgb])


def hex_rgb(value):
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("Enter a six-digit HEX colour, such as #9B87F5.")
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ValueError("HEX colour must contain only 0–9 and A–F.")


class UiBridge(QObject):
    invoke = Signal(object)


class WizClient:
    """Local WiZ UDP client. Uses the working unsigned setPilot command."""
    def __init__(self, ip=BULB_IP):
        self.ip = ip

    def request(self, method, params=None, timeout=1.8):
        payload = {"method": method, "params": params or {}}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(json.dumps(payload).encode("utf-8"), (self.ip, PORT))
            data, _ = sock.recvfrom(8192)
        response = json.loads(data.decode("utf-8"))
        if "error" in response:
            error = response["error"]
            raise RuntimeError(
                f"WiZ error {error.get('code')}: "
                f"{error.get('message', 'Command rejected')}"
            )
        return response

    def get_state(self):
        response = self.request("getPilot")
        result = response.get("result")
        if not isinstance(result, dict) or "state" not in result:
            raise RuntimeError("Unexpected status response from the bulb.")
        return result

    def set_color(self, color, brightness):
        r, g, b = hex_rgb(color)
        return self.request("setPilot", {
            "state": True, "dimming": int(brightness),
            "r": r, "g": g, "b": b
        })

    def set_power(self, on):
        return self.request("setPilot", {"state": bool(on)})

    def set_brightness(self, color, brightness):
        r, g, b = hex_rgb(color)
        return self.request("setPilot", {
            "state": True, "dimming": int(brightness),
            "r": r, "g": g, "b": b
        })


class ColorWheel(QWidget):
    colorPicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(330, 330)
        self.setMouseTracking(True)
        self.color = QColor(97, 157, 254)
        self._wheel_rect = QRectF()
        self._dragging = False
        self._wheel_cache = {}

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(420, 420)

    def set_color(self, hex_color):
        self.color = QColor(hex_color)
        self.update()

    def wheel_geometry(self):
        side = min(self.width(), self.height())
        margin = 18
        outer = QRectF(
            (self.width() - side) / 2 + margin,
            (self.height() - side) / 2 + margin,
            side - margin * 2,
            side - margin * 2
        )
        thickness = max(34, side * 0.105)
        inner = outer.adjusted(thickness, thickness, -thickness, -thickness)
        return outer, inner

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer, inner = self.wheel_geometry()
        self._wheel_rect = outer

        # Draw the spectrum into a cached image so the visible hue and
        # click-to-colour math use exactly the same coordinate convention.
        # This prevents the wheel from selecting the complementary colour.
        image_side = max(1, int(round(outer.width())))
        wheel_image = self._wheel_cache.get(image_side)
        if wheel_image is None:
            wheel_image = QImage(
                image_side, image_side,
                QImage.Format.Format_ARGB32
            )
            wheel_image.fill(Qt.GlobalColor.transparent)
            center = (image_side - 1) / 2.0
            outer_r = center
            inner_r = outer_r * 0.76
            for iy in range(image_side):
                for ix in range(image_side):
                    dx = ix - center
                    dy = iy - center
                    distance = math.hypot(dx, dy)
                    if inner_r <= distance <= outer_r:
                        # Right = red, bottom = green, left = cyan,
                        # top = magenta; picker uses this same formula.
                        hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
                        rr, gg, bb = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                        wheel_image.setPixelColor(
                            ix, iy,
                            QColor(round(rr * 255), round(gg * 255), round(bb * 255))
                        )
            self._wheel_cache = {image_side: wheel_image}

        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawImage(outer, wheel_image)

        # Subtle outer rim
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.drawEllipse(outer)

        # Centre disk and subtle shading
        center_rect = inner.adjusted(5, 5, -5, -5)
        center_gradient = QLinearGradient(
            center_rect.topLeft(), center_rect.bottomRight()
        )
        center_gradient.setColorAt(0, QColor("#29292E"))
        center_gradient.setColorAt(1, QColor("#17171B"))
        painter.setPen(QPen(QColor("#303036"), 1))
        painter.setBrush(QBrush(center_gradient))
        painter.drawEllipse(center_rect)

        # Center HEX readout
        painter.setPen(QColor(MUTED))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRectF(center_rect.left(), center_rect.center().y() - 38,
                   center_rect.width(), 22),
            Qt.AlignmentFlag.AlignCenter, "HEX COLOUR"
        )
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI", max(15, int(self.width() * .055)),
                              QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(center_rect.left() + 5, center_rect.center().y() - 13,
                   center_rect.width() - 10, 36),
            Qt.AlignmentFlag.AlignCenter, self.color.name().upper()
        )
        painter.setPen(QColor(MUTED))
        painter.setFont(QFont("Segoe UI", 9))
        r, g, b = self.color.red(), self.color.green(), self.color.blue()
        painter.drawText(
            QRectF(center_rect.left(), center_rect.center().y() + 23,
                   center_rect.width(), 22),
            Qt.AlignmentFlag.AlignCenter, f"RGB  {r}  ·  {g}  ·  {b}"
        )

        # Selector marker on ring
        r, g, b = self.color.red(), self.color.green(), self.color.blue()
        h, s, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        angle = h * 2 * math.pi
        radius = (outer.width() + inner.width()) / 4
        marker_x = outer.center().x() + math.cos(angle) * radius
        marker_y = outer.center().y() + math.sin(angle) * radius
        painter.setPen(QPen(QColor(0, 0, 0, 150), 5))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(marker_x, marker_y), 9, 9)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(QColor(self.color))
        painter.drawEllipse(QPointF(marker_x, marker_y), 6, 6)

    def pick_at(self, point):
        outer, inner = self.wheel_geometry()
        dx = point.x() - outer.center().x()
        dy = point.y() - outer.center().y()
        distance = math.hypot(dx, dy)
        outer_r = outer.width() / 2
        inner_r = inner.width() / 2
        if distance > outer_r or distance < inner_r:
            return
        hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        self.color = QColor(int(r * 255), int(g * 255), int(b * 255))
        self.update()
        self.colorPicked.emit(self.color.name().upper())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.pick_at(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.pick_at(event.position())

    def mouseReleaseEvent(self, event):
        self._dragging = False


class RGBRow(QWidget):
    changed = Signal(str, int)

    def __init__(self, channel, color, value=100, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.name = QLabel(channel)
        self.name.setFixedWidth(18)
        self.name.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(self.name)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setValue(value)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 5px; background: #35353D; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {color}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #F5F5F7; width: 12px; margin: -5px 0;
                border-radius: 6px;
            }}
        """)
        layout.addWidget(self.slider, 1)

        self.value_label = QLabel(str(value))
        self.value_label.setFixedWidth(28)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight |
                                      Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(self.value_label)

        self.slider.valueChanged.connect(self._changed)

    def _changed(self, value):
        self.value_label.setText(str(value))
        self.changed.emit(self.channel, value)


class EyedropperOverlay(QWidget):
    picked = Signal(str)
    cancelled = Signal()

    def __init__(self, screen_pixmap, screen_geometry):
        super().__init__(None)
        self.pixmap = screen_pixmap
        self.geometry_global = screen_geometry
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setGeometry(screen_geometry)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.preview_point = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.pixmap)
        # Dim slightly and add instructions
        p.fillRect(self.rect(), QColor(0, 0, 0, 28))
        panel = QRectF(20, 20, 390, 62)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#17171D"))
        p.drawRoundedRect(panel, 12, 12)
        p.setPen(QColor(TEXT))
        p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        p.drawText(34, 44, "PICK A COLOUR")
        p.setPen(QColor("#C4C4CE"))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(34, 64, "Click a pixel  ·  Esc to cancel")

        if self.preview_point:
            x, y = self.preview_point.x(), self.preview_point.y()
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(x, y), 8, 8)

    def mouseMoveEvent(self, event):
        self.preview_point = event.position()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            image = self.pixmap.toImage()
            x = max(0, min(image.width() - 1, point.x()))
            y = max(0, min(image.height() - 1, point.y()))
            color = QColor(image.pixel(x, y)).name().upper()
            self.picked.emit(color)
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Lightdesk", "Lightdesk")
        saved_ip = self.settings.value("bulb_ip", BULB_IP, type=str)
        self.client = WizClient(saved_ip)
        self.bridge = UiBridge()
        self.bridge.invoke.connect(self.run_ui_action)
        self.current_color = "#619DFE"
        self.is_on = False
        self.brightness = 60
        self.busy = False
        self.history = deque(
            ["#2348C7", "#F000B9", "#8A62C7", "#FF4A20",
             "#00EAA0", "#FF9E00", "#F5ED00", "#9700F4", "#35E900"],
            maxlen=12
        )
        self.overlay = None
        self._brightness_timer = QTimer(self)
        self._brightness_timer.setSingleShot(True)
        self._brightness_timer.setInterval(180)
        self._brightness_timer.timeout.connect(self.apply_brightness)

        self.setWindowTitle("WiZ Sync")
        self.resize(1080, 720)
        self.setMinimumSize(900, 650)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}
            QLabel {{ background: transparent; }}
            QLineEdit {{
                background: {PANEL_ALT}; border: 1px solid {BORDER};
                border-radius: 10px; padding: 10px 12px; color: {TEXT};
                selection-background-color: {ACCENT};
            }}
            QPushButton {{
                background: {PANEL_ALT}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 10px; padding: 10px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ background: #303039; border-color: #555560; }}
            QPushButton:pressed {{ background: #393544; }}
        """)
        self.build_ui()
        QTimer.singleShot(250, self.load_state)

    def run_ui_action(self, callback):
        callback()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(18)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        title = QLabel("WiZ Sync")
        title.setStyleSheet("font-size: 27px; font-weight: 700;")
        subtitle = QLabel("PERSONAL LIGHT STUDIO")
        subtitle.setStyleSheet(f"color: {MUTED}; font-size: 10px; letter-spacing: 2px;")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()

        self.connection_label = QLabel("●  CONNECTING")
        self.connection_label.setStyleSheet(f"color: #F2C879; font-size: 11px;")
        header.addWidget(self.connection_label)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)

        left = QFrame()
        left.setObjectName("panel")
        left.setStyleSheet(f"QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 20px; }}")
        left.setMinimumWidth(340)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 24, 24, 22)
        left_layout.setSpacing(13)

        left_layout.addWidget(self.section_label("Colour controls"))
        desc = QLabel("Fine-tune your light with RGB values.")
        desc.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        left_layout.addWidget(desc)

        self.rgb_rows = {}
        for channel, color in [("R", "#FF414B"), ("G", "#35DB79"), ("B", "#478AFF")]:
            row = RGBRow(channel, color)
            row.changed.connect(self.rgb_changed)
            self.rgb_rows[channel] = row
            left_layout.addWidget(row)

        left_layout.addSpacing(8)
        left_layout.addWidget(self.section_label("Lighting scenes"))
        scenes_grid = QGridLayout()
        scenes_grid.setHorizontalSpacing(8)
        scenes_grid.setVerticalSpacing(8)
        scenes = [
            ("Sunset", "#FF6B3D", 72),
            ("Relax", "#FFB98A", 38),
            ("Focus", "#FFF1D6", 100),
            ("Ocean", "#238CFF", 68),
            ("Forest", "#36C982", 55),
            ("Night", "#5145A8", 18),
        ]
        for i, (name, color, level) in enumerate(scenes):
            scene_btn = QPushButton(name)
            scene_btn.setMinimumHeight(34)
            scene_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {PANEL_ALT}; color: {TEXT};
                    border: 1px solid {BORDER}; border-radius: 9px;
                    text-align: left; padding: 7px 10px;
                }}
                QPushButton:hover {{
                    background: #303039; border: 1px solid {color};
                }}
            """)
            scene_btn.clicked.connect(
                lambda checked=False, c=color, b=level, n=name:
                    self.apply_scene(n, c, b)
            )
            scenes_grid.addWidget(scene_btn, i // 2, i % 2)
        left_layout.addLayout(scenes_grid)

        left_layout.addWidget(self.section_label("Recent colours"))
        history_grid = QGridLayout()
        history_grid.setSpacing(10)
        self.history_buttons = []
        for i, color in enumerate(self.history):
            btn = self.make_swatch(color)
            history_grid.addWidget(btn, i // 5, i % 5)
            self.history_buttons.append(btn)
        left_layout.addLayout(history_grid)

        left_layout.addStretch()
        self.eyedropper_button = QPushButton("  ⌁   Pick colour from screen")
        self.eyedropper_button.setMinimumHeight(44)
        self.eyedropper_button.setStyleSheet(f"""
            QPushButton {{ background: #282630; border: 1px solid #454052;
            border-radius: 12px; text-align: left; padding-left: 15px; }}
            QPushButton:hover {{ background: #363243; }}
        """)
        self.eyedropper_button.clicked.connect(self.start_eyedropper)
        left_layout.addWidget(self.eyedropper_button)

        hex_row = QHBoxLayout()
        self.hex_input = QLineEdit(self.current_color)
        self.hex_input.setPlaceholderText("#RRGGBB")
        hex_row.addWidget(self.hex_input, 1)
        apply_hex_btn = QPushButton("Apply")
        apply_hex_btn.setStyleSheet(f"background: {ACCENT}; color: #17131F; font-weight: 700; border: none;")
        apply_hex_btn.clicked.connect(self.apply_hex)
        hex_row.addWidget(apply_hex_btn)
        left_layout.addLayout(hex_row)

        body.addWidget(left, 4)

        right = QFrame()
        right.setObjectName("panel")
        right.setStyleSheet(f"QFrame#panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 20px; }}")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(22, 20, 22, 20)
        right_layout.setSpacing(12)

        top = QHBoxLayout()
        info = QVBoxLayout()
        lamp_title = QLabel("Lamp")
        lamp_title.setStyleSheet("font-size: 20px; font-weight: 650;")
        lamp_subtitle = QLabel("Philips WiZ Neo  ·  Living space")
        lamp_subtitle.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        info.addWidget(lamp_title)
        info.addWidget(lamp_subtitle)
        top.addLayout(info)
        top.addStretch()

        self.power_button = QPushButton("⏻")
        self.power_button.setFixedSize(58, 58)
        self.power_button.setStyleSheet("""
            QPushButton { background: #242328; color: #FF5B36; border: 2px solid #39363B;
            border-radius: 29px; font-size: 28px; }
            QPushButton:hover { background: #332723; border-color: #FF6848; }
        """)
        self.power_button.clicked.connect(self.toggle_power)
        top.addWidget(self.power_button)
        right_layout.addLayout(top)

        bright_head = QHBoxLayout()
        bright_head.addWidget(QLabel("Brightness"))
        bright_head.addStretch()
        self.brightness_value = QLabel("60%")
        self.brightness_value.setStyleSheet("font-size: 12px; font-weight: 700;")
        bright_head.addWidget(self.brightness_value)
        right_layout.addLayout(bright_head)

        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(1, 100)
        self.brightness_slider.setValue(self.brightness)
        self.brightness_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 8px; background: #34343B; border-radius: 4px; }}
            QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 4px; }}
            QSlider::handle:horizontal {{ background: #FFFFFF; width: 17px; margin: -5px 0; border-radius: 8px; }}
        """)
        self.brightness_slider.valueChanged.connect(self.brightness_changed)
        right_layout.addWidget(self.brightness_slider)

        right_layout.addWidget(self.section_label("Colour studio"))
        self.wheel = ColorWheel()
        self.wheel.colorPicked.connect(self.wheel_changed)
        right_layout.addWidget(self.wheel, 1)

        bottom = QHBoxLayout()
        self.preview_dot = QLabel(" ")
        self.preview_dot.setFixedSize(17, 17)
        self.preview_dot.setStyleSheet(f"background: {self.current_color}; border-radius: 8px;")
        bottom.addWidget(self.preview_dot)
        self.color_name = QLabel("Selected colour")
        self.color_name.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        bottom.addWidget(self.color_name)
        bottom.addStretch()
        self.rgb_summary = QLabel("RGB 97 · 157 · 254")
        self.rgb_summary.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        bottom.addWidget(self.rgb_summary)
        right_layout.addLayout(bottom)

        ip_row = QHBoxLayout()
        ip_label = QLabel("Bulb IP")
        ip_label.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        ip_row.addWidget(ip_label)
        self.device_ip_input = QLineEdit(self.client.ip)
        self.device_ip_input.setPlaceholderText("e.g. 192.168.1.33")
        self.device_ip_input.setClearButtonEnabled(True)
        ip_row.addWidget(self.device_ip_input, 1)
        self.apply_ip_button = QPushButton("Apply IP")
        self.apply_ip_button.clicked.connect(self.apply_device_ip)
        ip_row.addWidget(self.apply_ip_button)
        right_layout.addLayout(ip_row)

        self.status_label = QLabel("Connecting to your bulb…")
        self.status_label.setStyleSheet(f"color: {MUTED}; font-size: 11px; padding-top: 2px;")
        right_layout.addWidget(self.status_label)
        body.addWidget(right, 6)

        self.update_color_widgets(self.current_color, update_wheel=True)

    def section_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 14px; font-weight: 650;")
        return label

    def make_swatch(self, color):
        btn = QPushButton()
        btn.setFixedSize(31, 31)
        btn.setToolTip(color)
        btn.setStyleSheet(f"""
            QPushButton {{ background: {color}; border: 2px solid #45454D; border-radius: 15px; padding: 0; }}
            QPushButton:hover {{ border: 2px solid white; }}
        """)
        btn.clicked.connect(lambda checked=False, c=color: self.choose_history(c))
        return btn

    def apply_scene(self, name, color, brightness):
        self.brightness = int(brightness)
        self.brightness_slider.setValue(self.brightness)
        self.brightness_value.setText(f"{self.brightness}%")
        self.update_color_widgets(color, update_wheel=True)
        self.run_command(
            lambda: self.client.set_color(color, self.brightness),
            lambda result: self.scene_success(name, color)
        )

    def scene_success(self, name, color):
        self.is_on = True
        self.power_button.setText("⏻")
        self.update_history(color)
        self.set_status(f"{name} scene applied · {color}", GREEN)

    def choose_history(self, color):
        self.update_color_widgets(color)
        self.apply_color(color)

    def update_history(self, color):
        if color in self.history:
            self.history.remove(color)
        self.history.appendleft(color)
        for i, btn in enumerate(self.history_buttons):
            if i < len(self.history):
                c = list(self.history)[i]
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {c}; border: 2px solid #45454D; border-radius: 15px; padding: 0; }}
                    QPushButton:hover {{ border: 2px solid white; }}
                """)
                btn.setToolTip(c)

    def update_color_widgets(self, color, update_wheel=False):
        color = QColor(color).name().upper()
        self.current_color = color
        r, g, b = hex_rgb(color)
        for channel, value in zip(("R", "G", "B"), (r, g, b)):
            row = self.rgb_rows.get(channel)
            if row:
                row.slider.blockSignals(True)
                row.slider.setValue(value)
                row.value_label.setText(str(value))
                row.slider.blockSignals(False)
        if hasattr(self, "hex_input"):
            self.hex_input.setText(color)
        if hasattr(self, "preview_dot"):
            self.preview_dot.setStyleSheet(f"background: {color}; border-radius: 8px;")
        if hasattr(self, "rgb_summary"):
            self.rgb_summary.setText(f"RGB {r} · {g} · {b}")
        if hasattr(self, "color_name"):
            self.color_name.setText(color)
        if update_wheel:
            self.wheel.set_color(color)

    def rgb_changed(self, channel, value):
        values = {key: row.slider.value() for key, row in self.rgb_rows.items()}
        color = rgb_hex((values["R"], values["G"], values["B"]))
        self.update_color_widgets(color, update_wheel=True)
        # Apply only after the user pauses moving a slider.
        if not hasattr(self, "_rgb_timer"):
            self._rgb_timer = QTimer(self)
            self._rgb_timer.setSingleShot(True)
            self._rgb_timer.setInterval(220)
            self._rgb_timer.timeout.connect(lambda: self.apply_color(self.current_color))
        self._rgb_timer.start()

    def wheel_changed(self, color):
        self.update_color_widgets(color)
        self.apply_color(color)

    def apply_hex(self):
        try:
            color = QColor(rgb_hex(hex_rgb(self.hex_input.text())))
            self.update_color_widgets(color.name().upper(), update_wheel=True)
            self.apply_color(color.name().upper())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid HEX colour", str(exc))

    def apply_color(self, color):
        self.update_color_widgets(color, update_wheel=True)
        self.run_command(
            lambda: self.client.set_color(color, self.brightness),
            lambda result: self.color_success(color, result)
        )

    def color_success(self, color, result):
        self.is_on = True
        self.power_button.setText("⏻")
        self.update_history(color)
        self.set_status(f"Colour applied · {color}", GREEN)

    def brightness_changed(self, value):
        self.brightness = int(value)
        self.brightness_value.setText(f"{value}%")
        self._brightness_timer.start()

    def apply_brightness(self):
        if not self.is_on:
            self.set_status("Brightness selected · turn the light on to apply", MUTED)
            return
        self.run_command(
            lambda: self.client.set_brightness(self.current_color, self.brightness),
            lambda result: self.set_status(f"Brightness set to {self.brightness}%", GREEN)
        )

    def toggle_power(self):
        desired = not self.is_on
        self.run_command(
            lambda: self.client.set_power(desired),
            lambda result: self.power_success(desired)
        )

    def power_success(self, desired):
        self.is_on = desired
        self.power_button.setText("⏻")
        self.set_status("Light turned on" if desired else "Light turned off", GREEN)
        if desired:
            self.apply_color(self.current_color)

    def run_command(self, work, on_success=None):
        if self.busy:
            self.set_status("Please wait for the current command…", MUTED)
            return
        self.busy = True
        self.set_status("Sending command…", MUTED)

        def worker():
            result = None
            error = None
            try:
                result = work()
            except Exception as exc:
                error = str(exc)

            def finish():
                self.busy = False
                if error:
                    self.set_status(f"Command failed: {error}", RED)
                elif on_success:
                    on_success(result)
            self.bridge.invoke.emit(finish)

        threading.Thread(target=worker, daemon=True).start()

    def load_state(self):
        if self.busy:
            QTimer.singleShot(500, self.load_state)
            return

        self.busy = True

        def worker():
            state = None
            error = None
            try:
                state = self.client.get_state()
            except Exception as exc:
                error = str(exc)

            def finish():
                self.busy = False
                if error:
                    self.set_status(f"Offline · {error}", RED)
                    self.connection_label.setText("● OFFLINE")
                    self.connection_label.setStyleSheet(f"color: {RED}; font-size: 11px;")
                    return

                self.is_on = bool(state.get("state", False))
                self.brightness = int(state.get("dimming", 60))
                self.brightness_slider.setValue(max(1, min(100, self.brightness)))
                self.brightness_value.setText(f"{self.brightness}%")
                if all(k in state for k in ("r", "g", "b")):
                    color = rgb_hex((state["r"], state["g"], state["b"]))
                    self.update_color_widgets(color, update_wheel=True)
                self.set_status("Connected · light is " + ("on" if self.is_on else "off"), GREEN)
                self.connection_label.setText("● CONNECTED")
                self.connection_label.setStyleSheet(f"color: {GREEN}; font-size: 11px;")
            self.bridge.invoke.emit(finish)

        threading.Thread(target=worker, daemon=True).start()

    def apply_device_ip(self):
        value = self.device_ip_input.text().strip()
        try:
            new_ip = str(ipaddress.IPv4Address(value))
        except ipaddress.AddressValueError:
            QMessageBox.warning(
                self,
                "Invalid IP address",
                "Enter a valid IPv4 address, for example 192.168.1.33."
            )
            return

        self.client.ip = new_ip
        self.settings.setValue("bulb_ip", new_ip)
        self.set_status(f"Bulb IP set to {new_ip}. Checking connection…", MUTED)
        self.load_state()

    def set_status(self, text, color=MUTED):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px; padding-top: 2px;")
        if color == GREEN:
            self.connection_label.setText("● CONNECTED")
            self.connection_label.setStyleSheet(f"color: {GREEN}; font-size: 11px;")

    def start_eyedropper(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            self.set_status("No screen available for colour picking", RED)
            return
        # Hide the app before taking the screenshot so it cannot be sampled.
        self.hide()

        def capture():
            try:
                screen = QApplication.primaryScreen()
                pixmap = screen.grabWindow(0)
                geometry = screen.geometry()
                self.overlay = EyedropperOverlay(pixmap, geometry)
                self.overlay.picked.connect(self.eyedropper_picked)
                self.overlay.cancelled.connect(self.eyedropper_cancelled)
                self.overlay.show()
                self.overlay.raise_()
                self.overlay.activateWindow()
                self.overlay.setFocus()
            except Exception as exc:
                self.show()
                self.set_status(f"Eyedropper failed: {exc}", RED)

        QTimer.singleShot(250, capture)

    def eyedropper_picked(self, color):
        self.show()
        self.raise_()
        self.activateWindow()
        self.update_color_widgets(color, update_wheel=True)
        self.apply_color(color)

    def eyedropper_cancelled(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.set_status("Colour picking cancelled", MUTED)

    def closeEvent(self, event):
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WiZ Sync")
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
