"""Write a decoded image as a binary PPM (P6). Indexed images are already expanded."""

from .errors import FormatError
from .image import DecodedImage


def to_ppm_bytes(image: DecodedImage) -> bytes:
    ch = image.channels
    if ch not in (1, 3, 4):
        raise FormatError(f"cannot write PPM for channels={ch}")
    w, h = image.width, image.height
    pix = image.pixels
    if ch == 3:
        body = pix
    elif ch == 1:
        body = bytes(b for s in pix for b in (s, s, s))
    else:
        # drop alpha
        body = bytes(b for i in range(0, len(pix), 4) for b in pix[i : i + 3])
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    return header + body


def write_ppm(image: DecodedImage, path: str) -> None:
    with open(path, "wb") as f:
        f.write(to_ppm_bytes(image))
