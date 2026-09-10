"""Check that the main camera still frames what the policy's crop was measured against.

The policy does not see the 640x480 frame this UI displays. A square window of it is cut out
before the image is resized to the model's 224 -- the camera cannot be brought closer to the
table, so cropping is the only way to make a 25 mm block cover more than a fraction of one
14 px patch -- and that window is fixed in camera pixels and baked into the checkpoint at
training time.

Two things follow, and neither announces itself during a recording session:

  a bumped camera    the episodes look perfect and training converges, and the policy ends up
                     looking at a different part of the table than it was taught
  an object staged
  outside the crop   the operator sees it in the feed, demonstrates a clean pick, and the
                     policy never sees the object at all

Both are cheap to prevent and impossible to repair afterwards, so the crop is drawn on the live
feed and the camera is compared against the frame the crop was measured on.

The reference and the crop come from real_robot/mark_workspace.py in the dreamer-vla repo, which
traces the workspace by pushing the arm around by hand. Copy its _framing/reference.png and
_framing/workspace.json to the paths in constants.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import json
import numpy as np

# A 25 mm block spans about 27 px of a 640x480 frame, so eight pixels is under a third of an
# object -- close enough that the crop still frames what it framed, far enough to catch a knock.
DEFAULT_TOL_PX = 8.0
DEFAULT_TOL_DEG = 0.8


@dataclass
class Framing:
    """The reference frame and the crop measured against it."""

    reference: np.ndarray  # grayscale
    crop: tuple[int, int, int] | None  # x, y, side
    frame: tuple[int, int] | None  # w, h the crop was measured on

    @classmethod
    def load(cls, reference_path: Path, workspace_path: Path) -> "Framing | None":
        if not Path(reference_path).exists():
            return None
        img = cv2.imread(str(reference_path))
        if img is None:
            return None
        crop = size = None
        wp = Path(workspace_path)
        if wp.exists():
            try:
                meta = json.loads(wp.read_text())
                c = meta.get("crop_main")
                crop = (int(c[0]), int(c[1]), int(c[2])) if c else None
                f = meta.get("frame")
                size = (int(f[0]), int(f[1])) if f else None
            except (ValueError, TypeError, KeyError):
                pass
        return cls(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), crop, size)


def rigid_shift(ref_gray: np.ndarray, cur_gray: np.ndarray) -> tuple[float, float, float]:
    """(dx, dy, rotation degrees) taking the reference onto the current frame.

    ECC because a camera gets twisted as often as it gets slid, seeded and backed by a phase
    correlation, which sees translation only but does not fail to converge.
    """
    a = cv2.GaussianBlur(ref_gray.astype(np.float32), (5, 5), 0)
    b = cv2.GaussianBlur(cur_gray.astype(np.float32), (5, 5), 0)
    (px, py), _ = cv2.phaseCorrelate(a, b)
    warp = np.array([[1, 0, px], [0, 1, py]], dtype=np.float32)
    try:
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
        cv2.findTransformECC(a, b, warp, cv2.MOTION_EUCLIDEAN, crit, None, 5)
        return (
            float(warp[0, 2]),
            float(warp[1, 2]),
            float(np.degrees(np.arctan2(warp[1, 0], warp[0, 0]))),
        )
    except cv2.error:
        return float(px), float(py), 0.0


def verdict(
    dx: float,
    dy: float,
    rot: float,
    tol_px: float = DEFAULT_TOL_PX,
    tol_deg: float = DEFAULT_TOL_DEG,
) -> tuple[bool, str]:
    """Pass/fail plus, when it fails, which way to push the camera."""
    d = float(np.hypot(dx, dy))
    if d <= tol_px and abs(rot) <= tol_deg:
        return True, f"camera OK  (shift {d:.1f}px, rot {rot:+.2f}deg)"
    what = []
    if d > tol_px:
        # Panning a camera right slides the scene left, so the correction runs the same way as
        # the measurement: a scene sitting 12 px right means the camera is aimed 12 px too far
        # left. Inverting this would send the operator the wrong way with a camera they are
        # trying not to disturb, so selftest() asserts the wording.
        if abs(dx) >= 1:
            what.append(f"pan {'right' if dx > 0 else 'left'} {abs(dx):.0f}px")
        if abs(dy) >= 1:
            what.append(f"tilt {'down' if dy > 0 else 'up'} {abs(dy):.0f}px")
    if abs(rot) > tol_deg:
        what.append(f"roll {'clockwise' if rot > 0 else 'anticlockwise'} {abs(rot):.1f}deg")
    tail = ("  --  " + ", ".join(what)) if what else ""
    return False, f"CAMERA MOVED  (shift {d:.1f}px, rot {rot:+.2f}deg){tail}"


def check(framing: Framing, rgb: np.ndarray, **kw) -> tuple[bool, str]:
    """Compare one live frame against the reference."""
    cur = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb
    if cur.shape != framing.reference.shape:
        return False, (
            f"frame is {cur.shape[1]}x{cur.shape[0]} but the crop was measured on "
            f"{framing.reference.shape[1]}x{framing.reference.shape[0]}"
        )
    return verdict(*rigid_shift(framing.reference, cur), **kw)


def draw_crop(bgr: np.ndarray, crop: tuple[int, int, int] | None) -> np.ndarray:
    """Outline the window the policy will actually see, and dim what falls outside it.

    An object staged outside this rectangle is invisible to the policy however clean the
    demonstration is, and that is not something the operator can see in an unmarked feed.
    """
    if not crop:
        return bgr
    x, y, side = crop
    h, w = bgr.shape[:2]
    out = bgr.copy()
    mask = np.zeros((h, w), np.uint8)
    mask[max(0, y) : min(h, y + side), max(0, x) : min(w, x + side)] = 1
    out[mask == 0] = (out[mask == 0] * 0.45).astype(out.dtype)
    cv2.rectangle(out, (x, y), (x + side, y + side), (0, 165, 255), 2)
    cv2.putText(
        out,
        "policy sees this",
        (x + 6, min(h - 6, y + side - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 165, 255),
        1,
    )
    return out


# The props, in OpenCV's 0-179 hue. Blocks and tape rolls share colours; what matters here is
# only whether something coloured is outside the window, not which prop it is.
PROP_HUES = {
    "red": [((0, 110, 60), (10, 255, 255)), ((170, 110, 60), (179, 255, 255))],
    "blue": [((95, 110, 50), (130, 255, 255))],
    "green": [((45, 70, 40), (85, 255, 255))],
    "yellow": [((20, 110, 90), (35, 255, 255))],
}


def outside_crop(
    rgb: np.ndarray, crop: "tuple[int, int, int] | None", min_area: int = 220
) -> list[tuple[str, int, int]]:
    """Coloured props whose centre falls outside the window the policy sees.

    An object that drifts out of the crop mid-episode -- knocked by the gripper, or staged just
    past the edge -- makes that episode teach the policy about something it cannot see. From an
    unmarked feed it looks like an ordinary take, so the take gets kept.

    Centres rather than any overlap: a prop straddling the boundary is still mostly visible, and
    flagging it every time the gripper nudges something would train the operator to ignore this.
    """
    if not crop:
        return []
    x, y, side = crop
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    out = []
    for name, ranges in PROP_HUES.items():
        m = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            m |= cv2.inRange(hsv, np.array(lo), np.array(hi))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] < min_area:
                continue
            cx, cy = int(ce[i][0]), int(ce[i][1])
            if not (x <= cx <= x + side and y <= cy <= y + side):
                out.append((name, cx, cy))
    return out


def draw_outside(bgr: np.ndarray, strays: list[tuple[str, int, int]]) -> np.ndarray:
    """Ring what fell outside, and say so where it cannot be missed mid-episode."""
    if not strays:
        return bgr
    for _, cx, cy in strays:
        cv2.circle(bgr, (cx, cy), 18, (0, 0, 255), 3)
        cv2.drawMarker(bgr, (cx, cy), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 26, 2)
    names = ", ".join(sorted({n for n, _, _ in strays}))
    h, w = bgr.shape[:2]
    cv2.rectangle(bgr, (0, 0), (w, 30), (0, 0, 200), -1)
    cv2.putText(bgr, f"OUTSIDE THE CROP: {names}  -- the policy cannot see it", (8, 21),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return bgr


def selftest() -> None:
    """Shift a frame by a known amount and check the wording, not only the magnitude."""
    g = np.zeros((480, 640), np.uint8)
    rng = np.random.default_rng(0)
    for _ in range(200):
        cv2.circle(
            g,
            (int(rng.integers(40, 600)), int(rng.integers(40, 440))),
            int(rng.integers(4, 14)),
            int(rng.integers(60, 255)),
            -1,
        )
    for dx, dy, want in ((14, 0, "pan right"), (-14, 0, "pan left"),
                         (0, 11, "tilt down"), (0, -11, "tilt up")):
        moved = cv2.warpAffine(g, np.float32([[1, 0, dx], [0, 1, dy]]), (640, 480))
        ok, msg = verdict(*rigid_shift(g, moved))
        assert not ok and want in msg, f"({dx},{dy}) wanted '{want}', got '{msg}'"
    ok, msg = verdict(*rigid_shift(g, g))
    assert ok, msg

    scene = np.zeros((480, 640, 3), np.uint8)
    crop = (113, 0, 441)
    cv2.rectangle(scene, (300, 200), (330, 230), (220, 30, 30), -1)     # inside
    assert outside_crop(scene, crop) == [], outside_crop(scene, crop)
    cv2.rectangle(scene, (600, 300), (630, 330), (30, 30, 220), -1)     # outside, to the right
    strays = outside_crop(scene, crop)
    assert [s[0] for s in strays] == ["blue"], strays
    assert outside_crop(scene, None) == []
    print("framing selftest ok")


if __name__ == "__main__":
    selftest()
