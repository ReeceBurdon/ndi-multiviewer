"""Publish N moving test-pattern NDI sources so the multiviewer can be tried without cameras.

    python tools/test_sources.py --count 6
"""

import argparse
import time
from fractions import Fraction

import numpy as np
import cyndilib as ndi

BARS = np.array(
    [[192, 192, 192], [192, 192, 0], [0, 192, 192], [0, 192, 0], [192, 0, 192], [192, 0, 0], [0, 0, 192]],
    dtype=np.uint8,
)

# 3x5 bitmap digits for burning the source number into the picture.
DIGITS = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111",
}


def make_background(w: int, h: int, n: int) -> np.ndarray:
    img = np.zeros((h, w, 4), np.uint8)
    img[..., 3] = 255
    bar_w = w // len(BARS)
    for i, color in enumerate(BARS):
        img[: h * 2 // 3, i * bar_w : (i + 1) * bar_w, :3] = color
    img[h * 2 // 3 :, :, :3] = np.linspace(0, 255, w, dtype=np.uint8)[None, :, None]
    # Big number so each tile is easy to tell apart.
    px = h // 12
    x0 = w // 2 - (len(str(n)) * 4 * px) // 2
    for k, ch in enumerate(str(n)):
        bits = DIGITS[ch]
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    y, x = h // 6 + r * px, x0 + k * 4 * px + c * px
                    img[y : y + px, x : x + px, :3] = (20, 20, 20)
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--name", default="Test Pattern")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=360)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    senders, backgrounds = [], []
    for i in range(args.count):
        s = ndi.Sender(f"{args.name} {i + 1}")
        vf = ndi.VideoSendFrame()
        vf.set_resolution(args.width, args.height)
        vf.set_frame_rate(Fraction(args.fps, 1))
        vf.set_fourcc(ndi.FourCC.RGBA)
        s.set_video_frame(vf)
        s.open()
        senders.append(s)
        backgrounds.append(make_background(args.width, args.height, i + 1))
    print(f"Publishing {args.count} NDI sources named '{args.name} N'. Ctrl+C to stop.")

    box = args.height // 8
    frame_no = 0
    try:
        while True:
            start = time.perf_counter()
            for i, (s, bg) in enumerate(zip(senders, backgrounds)):
                img = bg.copy()
                # A white box sweeping across shows the feed is live.
                x = (frame_no * (4 + i)) % (args.width - box)
                img[args.height // 2 : args.height // 2 + box, x : x + box, :3] = 255
                s.write_video(img.ravel())
            frame_no += 1
            time.sleep(max(0.0, 1 / args.fps - (time.perf_counter() - start)))
    except KeyboardInterrupt:
        pass
    finally:
        for s in senders:
            s.close()


if __name__ == "__main__":
    main()
