"""
Handles setting the Windows desktop wallpaper.
No admin rights required.
"""
import ctypes
import os

SPI_SETDESKWALLPAPER = 20
SPI_GETDESKWALLPAPER = 0x0073
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def get_current_wallpaper() -> str:
    """Returns the path of whatever wallpaper is currently set, so it can be restored later."""
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 260, buf, 0)
    return buf.value


def generate_black_image(path: str, width: int = 1920, height: int = 1080) -> str:
    """Creates a solid black .png at the given path. Overwrites if it exists."""
    from PIL import Image

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", (width, height), color=(0, 0, 0))
    img.save(path)
    return path


def set_wallpaper(image_path: str) -> None:
    """Sets the Windows desktop wallpaper to the given image file (must be .bmp, .jpg, or .png)."""
    image_path = os.path.abspath(image_path)
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Wallpaper image not found: {image_path}")

    ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, image_path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    )
