"""UVC camera controls (exposure, gain, focus, ...) via USB control requests.

macOS lets AVFoundation stream from the camera while another process sends
UVC class requests to the camera's video-control interface, so these
settings can be changed and locked during the live preview.
"""

import array
import struct
import sys
from pathlib import Path

try:
    import usb.core
    import usb.backend.libusb1
except ImportError:      # pragma: no cover
    usb = None

SET_CUR, GET_CUR, GET_MIN, GET_MAX, GET_RES, GET_INFO, GET_DEF = 0x01, 0x81, 0x82, 0x83, 0x84, 0x86, 0x87

# name: (entity, selector, size, signed, kind, label)
CONTROLS = {
    "auto_exposure":        ("ct", 0x02, 1, False, "ae",    "Auto exposure"),
    "exposure_priority":    ("ct", 0x03, 1, False, "bool",  "Allow frame-rate drop for exposure"),
    "exposure_time":        ("ct", 0x04, 4, False, "range", "Exposure (x0.1 ms)"),
    "auto_focus":           ("ct", 0x08, 1, False, "bool",  "Auto focus"),
    "focus":                ("ct", 0x06, 2, False, "range", "Focus"),
    "gain":                 ("pu", 0x04, 2, False, "range", "Gain"),
    "brightness":           ("pu", 0x02, 2, True,  "range", "Brightness"),
    "contrast":             ("pu", 0x03, 2, False, "range", "Contrast"),
    "gamma":                ("pu", 0x09, 2, False, "range", "Gamma"),
    "sharpness":            ("pu", 0x08, 2, False, "range", "Sharpness"),
    "backlight":            ("pu", 0x01, 2, False, "range", "Backlight compensation"),
    "auto_white_balance":   ("pu", 0x0B, 1, False, "bool",  "Auto white balance"),
    "white_balance":        ("pu", 0x0A, 2, False, "range", "White balance (K)"),
    "power_line":           ("pu", 0x05, 1, False, "menu",  "Light flicker filter"),
}
POWER_LINE = {0: "Off", 1: "50 Hz", 2: "60 Hz (US)"}
APPLY_ORDER = ["auto_exposure", "exposure_priority", "auto_focus", "auto_white_balance",
               "power_line", "exposure_time", "focus", "white_balance", "gain",
               "brightness", "contrast", "gamma", "sharpness", "backlight"]


def _backend():
    lib = Path(sys.prefix) / "lib" / "libusb-1.0.dylib"
    if lib.exists():
        return usb.backend.libusb1.get_backend(find_library=lambda _: str(lib))
    return usb.backend.libusb1.get_backend()


class UVCCamera:
    def __init__(self, vendor_id, product_id):
        if usb is None:
            raise RuntimeError("pyusb is not installed")
        self.dev = usb.core.find(idVendor=vendor_id, idProduct=product_id, backend=_backend())
        if self.dev is None:
            raise RuntimeError("USB camera not found for UVC controls")
        self._parse_descriptors()
        self.info = {}
        for name in CONTROLS:
            try:
                self.info[name] = self._query(name)
            except Exception:
                pass

    def _parse_descriptors(self):
        raw = self._ctrl(0x80, 0x06, 0x0200, 0, 4096)
        self.vc_interface = None
        self.entity = {}
        i, cur_intf, cur_class = 0, None, None
        while i + 2 <= len(raw):
            length, dtype = raw[i], raw[i + 1]
            if length == 0:
                break
            d = raw[i:i + length]
            if dtype == 0x04:                      # interface
                cur_intf, cur_class = d[2], (d[5], d[6])
                if cur_class == (0x0E, 0x01) and self.vc_interface is None:
                    self.vc_interface = cur_intf
            elif dtype == 0x24 and cur_class == (0x0E, 0x01) and len(d) > 5:
                subtype = d[2]
                if subtype == 0x02 and struct.unpack("<H", d[4:6])[0] == 0x0201:
                    self.entity["ct"] = d[3]       # camera terminal
                elif subtype == 0x05:
                    self.entity.setdefault("pu", d[3])  # processing unit
            i += length
        if self.vc_interface is None:
            raise RuntimeError("Camera has no UVC video-control interface")

    def _ctrl(self, bm_request_type, req, w_value, w_index, data_or_length):
        # Call the backend directly: Device.ctrl_transfer() would claim the
        # interface, which macOS refuses while the camera is in use.
        ctx = self.dev._ctx
        ctx.managed_open()
        if bm_request_type & 0x80:
            buf = array.array("B", bytes(data_or_length))
            n = ctx.backend.ctrl_transfer(ctx.handle, bm_request_type, req, w_value, w_index, buf, 500)
            return bytes(buf[:n])
        buf = array.array("B", data_or_length)
        return ctx.backend.ctrl_transfer(ctx.handle, bm_request_type, req, w_value, w_index, buf, 500)

    def _req(self, req, name, size=None, data=None):
        entity, sel, csize, signed, _, _ = CONTROLS[name]
        w_index = (self.entity[entity] << 8) | self.vc_interface
        if data is not None:
            return self._ctrl(0x21, req, sel << 8, w_index, data)
        return self._ctrl(0xA1, req, sel << 8, w_index, size or csize)

    def _decode(self, name, b):
        _, _, size, signed, _, _ = CONTROLS[name]
        return int.from_bytes(b[:size], "little", signed=signed)

    def _query(self, name):
        entity = CONTROLS[name][0]
        if entity not in self.entity:
            raise KeyError(name)
        info = self._req(GET_INFO, name, size=1)[0]
        if not info & 0x01:
            raise KeyError(name)
        q = {"cur": self._decode(name, self._req(GET_CUR, name))}
        kind = CONTROLS[name][4]
        if kind == "range":
            for key, req in (("min", GET_MIN), ("max", GET_MAX), ("def", GET_DEF)):
                q[key] = self._decode(name, self._req(req, name))
        elif kind == "ae":
            q["res"] = self._req(GET_RES, name)[0]     # bitmap of supported modes
            q["def"] = self._decode(name, self._req(GET_DEF, name))
        else:
            try:
                q["def"] = self._decode(name, self._req(GET_DEF, name))
            except Exception:
                q["def"] = q["cur"]
        return q

    def get(self, name):
        return self._decode(name, self._req(GET_CUR, name))

    def set(self, name, value):
        _, _, size, signed, kind, _ = CONTROLS[name]
        if kind == "ae":
            # value is True/False for auto; translate to UVC mode bits
            res = self.info[name].get("res", 0x0A)
            value = (8 if res & 8 else 2) if value else 1
        self._req(SET_CUR, name, data=int(value).to_bytes(size, "little", signed=signed))

    def read_all(self):
        """Current values in the same form set() accepts."""
        vals = {}
        for name in self.info:
            try:
                v = self.get(name)
                vals[name] = (v != 1) if CONTROLS[name][4] == "ae" else v
            except Exception:
                pass
        return vals

    def apply_all(self, values):
        errors = []
        for name in APPLY_ORDER:
            if name in values and name in self.info:
                try:
                    self.set(name, values[name])
                except Exception as e:
                    errors.append(f"{name}: {e}")
        return errors

    def reset_defaults(self):
        # Manual values only stick while the auto modes are off, so set them
        # first and restore the auto modes last.
        defaults = {n: q["def"] for n, q in self.info.items() if "def" in q}
        autos = [n for n in defaults if CONTROLS[n][4] in ("ae", "bool")]
        self.apply_all({n: (False if CONTROLS[n][4] == "ae" else 0) for n in autos
                        if n != "exposure_priority"})
        self.apply_all({n: v for n, v in defaults.items() if n not in autos})
        self.apply_all({n: ((defaults[n] != 1) if CONTROLS[n][4] == "ae" else defaults[n])
                        for n in autos})
