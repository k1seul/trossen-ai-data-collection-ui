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
    # Rows above this are not the staging area. The corner marks are where the arm was pushed
    # to, so nothing can be staged beyond them, and everything above is furniture -- which is
    # the pot's hue with more saturation and would otherwise be read as yellow props.
    table_top: int = 0

    @classmethod
    def load(cls, reference_path: Path, workspace_path: Path) -> "Framing | None":
        if not Path(reference_path).exists():
            return None
        img = cv2.imread(str(reference_path))
        if img is None:
            return None
        crop = size = None
        top = 0
        wp = Path(workspace_path)
        if wp.exists():
            try:
                meta = json.loads(wp.read_text())
                c = meta.get("crop_main")
                crop = (int(c[0]), int(c[1]), int(c[2])) if c else None
                f = meta.get("frame")
                size = (int(f[0]), int(f[1])) if f else None
                # "highest" is the gripper's lift, not a place an object can go, so it must not
                # drag the boundary up into the furniture.
                ys = [float(m["y"]) for m in meta.get("marks", [])
                      if m.get("name") != "highest" and "y" in m]
                if ys:
                    top = int(min(ys))
            except (ValueError, TypeError, KeyError):
                pass
        return cls(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), crop, size, top)


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
    # Widened for masking tape, whose ring measures H 19-22 with S down to 62 -- the original
    # gate wanted S >= 110 and missed it entirely. Widening it this far reaches the wooden
    # furniture and the gold pot as well, which is why props are now confined to the staging
    # area and excluded from the containers' own footprints.
    "yellow": [((15, 55, 90), (38, 255, 255))],
}


def outside_crop(
    rgb: np.ndarray, crop: "tuple[int, int, int] | None", min_area: int = 220,
    skip_top: int = 0,
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
            if cy < skip_top:
                continue                    # furniture above the table, never a stray prop
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


# A tape roll is a ring and leaves its hole empty; a block fills its bounding box. Measured on
# the props in use: blocks 0.79-0.96 filled, tape rolls 0.38-0.49. The gap is wide enough that
# the threshold does not have to be careful, and it holds at any distance, which a size
# threshold would not.
PROP_FILL_THRESHOLD = 0.65

# Below this the blob is noise or a sliver of something occluded, not a prop worth judging.
PROP_MIN_AREA = 220


def zone_of(cx: float, crop: "tuple[int, int, int] | None", frame_w: int = 640,
            cy: "float | None" = None, top: int = 0) -> str:
    """Which cell a point falls in: thirds across, and near / far up the table.

    Thirds of the crop rather than of the frame, and rather than the shoulder angles the
    staging sheet defines its zones by: what is being judged here is a picture, the operator is
    placing objects by eye against lines drawn on that same picture, and a zone that means one
    thing in the check and another on screen would be worse than no check.

    Depth is split too, because three columns leave the near-far axis entirely to chance -- the
    same axis the last round left fixed, and the one a reach has to generalise over. Returns
    "L" when no cy is given, so a sheet written before rows existed still means something.
    """
    if crop:
        x, y, side = crop
    else:
        x, y, side = 0, 0, frame_w
    u = (cx - x) / max(side, 1)
    col = "L" if u < 1 / 3 else ("C" if u < 2 / 3 else "R")
    if cy is None:
        return col
    y0, y1 = max(y, top), y + side
    return f"{col}-{'far' if cy < (y0 + y1) / 2 else 'near'}"


def identify_props(rgb: np.ndarray, crop: "tuple[int, int, int] | None",
                   skip_top: int = 0, exclude: "list[dict] | None" = None) -> list[dict]:
    """Every block and tape roll in the staging area, with its colour, kind and zone.

    skip_top drops the rows above the staging area, and exclude drops the containers' own
    footprints. Both are needed once the yellow gate is wide enough to see masking tape: the
    wooden furniture behind the arm and the gold pot both fall inside it, and the pot being a
    ring would be reported as a large yellow tape roll.
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    boxes = [(c["x"] - c["w"] / 2, c["y"] - c["h"] / 2, c["w"], c["h"])
             for c in (exclude or [])]
    found = []
    for name, ranges in PROP_HUES.items():
        m = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            m |= cv2.inRange(hsv, np.array(lo), np.array(hi))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            area = int(st[i, cv2.CC_STAT_AREA])
            if area < PROP_MIN_AREA:
                continue
            w, h = int(st[i, cv2.CC_STAT_WIDTH]), int(st[i, cv2.CC_STAT_HEIGHT])
            fill = area / max(w * h, 1)
            cx, cy = float(ce[i][0]), float(ce[i][1])
            if cy < skip_top:
                continue
            if any(bx <= cx <= bx + bw and by <= cy <= by + bh for bx, by, bw, bh in boxes):
                continue
            kind = "block" if fill >= PROP_FILL_THRESHOLD else "tape roll"
            inside = True
            if crop:
                x, y, side = crop
                inside = x <= cx <= x + side and y <= cy <= y + side
            found.append({"colour": name, "kind": kind, "object": f"{name} {kind}",
                          "x": cx, "y": cy, "w": w, "h": h, "fill": round(fill, 2),
                          "zone": zone_of(cx, crop, cy=cy, top=skip_top),
                          "inside_crop": inside})
    return found


# Containers are not props and cannot be found the same way. A gold pot is a hue the table
# does not have; a clear bowl is almost exactly the table, and what gives it away is its bright
# white base. Both are judged RELATIVE to the table rather than against fixed numbers, because
# the staging sheet changes the lighting every episode by design and any absolute threshold
# would hold under condition A and fail under C.
CONTAINER_MIN_AREA = 700          # a tape roll is ~1800 at the rim but not round-and-bright
# A bowl measures ~2500 and a pot ~5000 here. The cap is what stops a brightness threshold that
# has drifted low from returning the tablecloth as one enormous round bright object, which is
# exactly what it did when the staging-area boundary moved twenty rows.
CONTAINER_MAX_AREA = 12000
CONTAINER_ASPECT = (0.55, 1.8)    # both containers are near-circular from this angle
POT_HUE = (14, 36)                # gold; the wooden cabinet is redder and far more saturated
POT_SAT_MAX = 130
# Gold and yellow are the same hue, so a yellow tape roll passes the pot's colour test. Size is
# what separates them and shape is not: the closing that joins the pot's rim to its body also
# fills the tape's hole, so both come out solid. Measured here, the pot is 5000 px and a tape
# ring about 1000.
POT_MIN_AREA = 2500


def _table_reference(hsv: np.ndarray, crop: "tuple[int,int,int] | None",
                     skip_top: int) -> "tuple[float, float]":
    """Median value and saturation of the mat, to judge everything else against."""
    h, w = hsv.shape[:2]
    if crop:
        x, y, side = crop
        x0, x1 = max(0, x), min(w, x + side)
        y0, y1 = max(skip_top, y), min(h, y + side)
    else:
        x0, x1, y0, y1 = 0, w, skip_top, h
    patch = hsv[y0:y1, x0:x1]
    if patch.size == 0:
        return 150.0, 10.0
    return float(np.median(patch[:, :, 2])), float(np.median(patch[:, :, 1]))


def find_containers(rgb: np.ndarray, crop: "tuple[int,int,int] | None",
                    skip_top: int = 130) -> list[dict]:  # noqa: D401
    """The bowl and the pot, with their zones.

    skip_top drops the rows above the table edge. The furniture behind the arm is wood, which
    is the pot's hue with more saturation, and the gripper carries bright white pads -- both
    would be read as containers from a mask alone.
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, w = hsv.shape[:2]
    table_v, table_s = _table_reference(hsv, crop, skip_top)
    roi = np.zeros((h, w), np.uint8)
    if crop:
        x, y, side = crop
        roi[max(skip_top, y):min(h, y + side), max(0, x):min(w, x + side)] = 255
    else:
        roi[skip_top:, :] = 255

    V = hsv[:, :, 2].astype(np.int16)
    S = hsv[:, :, 1].astype(np.int16)
    # The bowl is nearly the table: clear walls, and only its white base separates it. A fixed
    # multiple of the table's brightness is too brittle for that -- a small drift in the
    # reference turns the whole mat into one blob -- so the threshold is also held at a high
    # percentile of the staging area, which caps how much of the frame can ever pass.
    inside = V[roi > 0]
    floor = float(np.percentile(inside, 97)) if inside.size else 255.0
    bowl_v = max(table_v * 1.12, floor)
    masks = {
        "pot": cv2.inRange(hsv, np.array((POT_HUE[0], int(table_s) + 20, 60)),
                           np.array((POT_HUE[1], POT_SAT_MAX, 255))),
        "bowl": (((V > bowl_v) & (S < table_s + 30)).astype(np.uint8) * 255),
    }
    out = []
    for name, m in masks.items():
        m = cv2.bitwise_and(m, roi)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            area = int(st[i, cv2.CC_STAT_AREA])
            if not CONTAINER_MIN_AREA <= area <= CONTAINER_MAX_AREA:
                continue
            if name == "pot" and area < POT_MIN_AREA:
                continue                      # a yellow tape roll, not the pot
            bw, bh = int(st[i, cv2.CC_STAT_WIDTH]), int(st[i, cv2.CC_STAT_HEIGHT])
            if not (CONTAINER_ASPECT[0] <= bw / max(bh, 1) <= CONTAINER_ASPECT[1]):
                continue
            cx, cy = float(ce[i][0]), float(ce[i][1])
            out.append({"object": name, "kind": "container", "x": cx, "y": cy,
                        "w": bw, "h": bh, "area": area,
                        "zone": zone_of(cx, crop, cy=cy, top=skip_top), "inside_crop": True})
    # One of each at most: the biggest blob wins, since a highlight on the mat can pass the
    # bowl's test but never beats the bowl itself.
    best = {}
    for c in out:
        if c["object"] not in best or c["area"] > best[c["object"]]["area"]:
            best[c["object"]] = c
    return list(best.values())


# Every status verify_scene can return, with how to show it. It lives here, beside the code
# that produces them, because the caller had its own copy and they drifted: "note" was added
# for a container nobody asked for, the copy was not, and every gate after the first episode
# died on a KeyError -- silently, since it happens inside a Qt slot.
STATUS_LABELS = {
    "ok": "OK   ",
    "wrong": "WRONG",
    "missing": "MISS ",
    "extra": "EXTRA",
    "skip": "eye  ",
    "note": "note ",
}


def verify_scene(expected: list[dict], rgb: np.ndarray,
                 crop: "tuple[int, int, int] | None",
                 skip_top: int = 130) -> tuple[bool, list[tuple[str, str]]]:
    """Compare the staged scene against what the camera can actually see.

    Returns (everything matches, [(status, line)]). Containers are not judged: a white bowl on
    a white mat is not something colour segmentation should be trusted to find, and a wrong
    answer about it would cost more than no answer.
    """
    containers = find_containers(rgb, crop, skip_top=skip_top)
    seen = identify_props(rgb, crop, skip_top=skip_top, exclude=containers) + containers
    unmatched = list(seen)
    lines, ok = [], True
    for want in expected:
        name = (want.get("object") or "").lower()
        if name in ("bowl", "pot"):
            kind, colour, match = "container", None, lambda s: s["object"] == name
        else:
            kind = "tape roll" if "tape" in name else ("block" if "block" in name else None)
            colour = next((c for c in PROP_HUES if c in name), None)
            if kind is None or colour is None:
                lines.append(("skip", f"{want.get('object')} -- by eye "
                                      f"(expected zone {want.get('zone')})"))
                continue

            def match(s, _c=colour, _k=kind):
                return s.get("colour") == _c and s["kind"] == _k

        # A sheet written before rows existed asks for "L", not "L-far". Compare on what it
        # actually specifies rather than failing every line of an older sheet.
        wz = str(want.get("zone", ""))

        def same_zone(s, _w=wz):
            return s["zone"].split("-")[0] == _w if "-" not in _w else s["zone"] == _w

        hit = next((s for s in unmatched if match(s) and same_zone(s)), None)
        if hit is not None:
            unmatched.remove(hit)
            lines.append(("ok", f"{want['object']} in {want['zone']}"))
            continue
        wrong = next((s for s in unmatched if match(s)), None)
        ok = False
        if wrong is not None:
            unmatched.remove(wrong)
            where = wrong["zone"] if wrong["inside_crop"] else "OUTSIDE THE CROP"
            lines.append(("wrong", f"{want['object']}: in {where}, "
                                   f"should be {want['zone']}"))
        else:
            lines.append(("missing", f"{want['object']}: not found -- should be in "
                                     f"{want['zone']}"))
    for extra in unmatched:
        if extra["kind"] == "container":
            # A container nobody asked for is usually the other one left on the mat, which
            # matters, but it is also the detection most likely to be a highlight on the
            # tablecloth -- so it is reported without failing the scene.
            lines.append(("note", f"{extra['object']} seen in {extra['zone']}, "
                                  f"not part of this episode"))
            continue
        ok = False
        lines.append(("extra", f"{extra['object']} in {extra['zone']} is not in this episode"))
    return ok, lines


# Boundaries and letters only, no wash of colour over the bands. A 12% tint was enough to move
# a green block's detected centroid across a boundary when the detector was pointed at the
# drawn frame -- the real path reads the raw one, but leaving a version of the scene in which
# the answer differs is a trap for whoever wires the next thing up.


def draw_zones(bgr: np.ndarray, crop: "tuple[int, int, int] | None",
               top: int = 0) -> np.ndarray:
    """The L / C / R bands, labelled, so objects can be placed without measuring anything.

    Drawn only while a scene is being staged. During an episode it would be clutter over the
    thing the operator is actually watching, and the zones are settled by then anyway.

    top is the staging area's near edge; the letters sit inside the band an object can occupy
    rather than at the bottom of the crop, which is mat nobody reaches.
    """
    if not crop:
        return bgr
    x, y, side = crop
    h, w = bgr.shape[:2]
    y0 = max(y, top)
    y1 = min(h, y + side)
    if y1 <= y0:
        return bgr

    ymid = int((y0 + y1) / 2)
    for px in (int(x + side / 3), int(x + side * 2 / 3)):
        cv2.line(bgr, (px, y0), (px, y1), (255, 255, 255), 2)
        cv2.line(bgr, (px, y0), (px, y1), (60, 60, 60), 1)
    cv2.line(bgr, (max(0, x), ymid), (min(w, x + side), ymid), (255, 255, 255), 2)
    cv2.line(bgr, (max(0, x), ymid), (min(w, x + side), ymid), (60, 60, 60), 1)

    # One label per cell, at the cell's own centre, so a name always sits where the object goes.
    for k, col in enumerate("LCR"):
        px = int(x + side * (k + 0.5) / 3)
        for row, py in (("far", (y0 + ymid) // 2), ("near", (ymid + y1) // 2)):
            text = f"{col}-{row}"
            (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            org = (px - tw // 2, py)
            cv2.putText(bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
            cv2.putText(bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return bgr


def lighting_signature(rgb: np.ndarray, crop: "tuple[int,int,int] | None",
                       skip_top: int = 0) -> dict:
    """What the mat looks like under the light currently on.

    Brightness alone does not separate these conditions -- an overhead-lit mat measured V 150
    and one with the sub lamp added V 157, which any change of exposure covers. A directional
    lamp shows up in colour and in how evenly it lights the mat, so those go in too.
    """
    h, w = rgb.shape[:2]
    if crop:
        x, y, side = crop
        x0, x1 = max(0, x), min(w, x + side)
        y0, y1 = max(skip_top, y), min(h, y + side)
    else:
        x0, x1, y0, y1 = 0, w, skip_top, h
    patch = rgb[y0:y1, x0:x1].astype(np.float32)
    R, G, B = patch[:, :, 0].mean(), patch[:, :, 1].mean(), patch[:, :, 2].mean()
    v = cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_RGB2HSV)[:, :, 2].astype(np.float32)
    med = float(np.median(v)) or 1.0
    return {"v_median": med,
            "r_over_b": float(R / max(B, 1e-6)),
            "g_over_b": float(G / max(B, 1e-6)),
            "evenness": float(np.percentile(v, 95) / med),
            "v_spread": float(v.std() / med)}


# Each feature divided by how much it is allowed to wander before it means something. Set from
# the same scene photographed twice under one condition: anything smaller than this is the
# camera's own variation, not the light.
LIGHT_SCALE = {"v_median": 6.0, "r_over_b": 0.010, "g_over_b": 0.010,
               "evenness": 0.030, "v_spread": 0.030}


def lighting_distance(a: dict, b: dict) -> float:
    """How far apart two signatures are, in units of "enough to notice"."""
    return float(np.sqrt(sum(((a[k] - b[k]) / s) ** 2 for k, s in LIGHT_SCALE.items())))


def classify_lighting(sig: dict, profiles: dict) -> "tuple[str | None, float, str]":
    """Which stored condition this looks like, and whether the answer means anything.

    Returns (name, margin, message). A margin near 1 means the two conditions are as far apart
    as the noise -- in which case the honest answer is that the camera cannot tell, and a
    lighting axis nobody can verify is one that gets recorded wrong and analysed anyway.
    """
    if len(profiles) < 2:
        return None, 0.0, "fewer than two lighting conditions have been recorded"
    d = sorted(((lighting_distance(sig, p), n) for n, p in profiles.items()))
    best, second = d[0], d[1]
    margin = second[0] / max(best[0], 1e-6)
    if second[0] < 2.0:
        return None, margin, (f"cannot tell {best[1]} from {second[1]}: they differ by "
                              f"{second[0] - best[0]:.1f}, which is inside the camera's own "
                              f"variation. This lighting axis is not measurable here.")
    if margin < 1.6:
        return best[1], margin, (f"probably {best[1]}, but {second[1]} is nearly as close "
                                 f"(margin {margin:.1f}x) -- treat it as unknown")
    return best[1], margin, f"{best[1]}"


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

    # Every status the code can emit has a label. Nothing else keeps them together, and the
    # gap between them is invisible until a scene happens to produce the missing one.
    import re as _re
    emitted = set(_re.findall(r'lines\.append\(\("([a-z]+)"', Path(__file__).read_text()))
    assert emitted <= set(STATUS_LABELS), f"no label for {sorted(emitted - set(STATUS_LABELS))}"

    scene = np.zeros((480, 640, 3), np.uint8)
    crop = (113, 0, 441)
    cv2.rectangle(scene, (300, 200), (330, 230), (220, 30, 30), -1)     # inside
    assert outside_crop(scene, crop) == [], outside_crop(scene, crop)
    cv2.rectangle(scene, (600, 300), (630, 330), (30, 30, 220), -1)     # outside, to the right
    strays = outside_crop(scene, crop)
    assert [s[0] for s in strays] == ["blue"], strays
    assert outside_crop(scene, None) == []

    # A filled square reads as a block, a ring as a tape roll, and the zone follows the crop.
    props = np.zeros((480, 640, 3), np.uint8)
    cv2.rectangle(props, (170, 300), (198, 328), (30, 220, 30), -1)          # green block, L
    cv2.circle(props, (400, 300), 24, (220, 30, 30), -1)   # RGB, as identify_props reads it
    cv2.circle(props, (400, 300), 13, (0, 0, 0), -1)                          # red ring, C
    got = {(p["object"], p["zone"]) for p in identify_props(props, crop)}
    assert ("green block", "L-near") in got, got
    assert ("red tape roll", "C-near") in got, got

    # A sheet naming only a column still matches; one naming a cell is held to the cell.
    want = [{"object": "green block", "zone": "L"}, {"object": "red tape roll", "zone": "C"}]
    good, lines = verify_scene(want, props, crop, skip_top=0)
    assert good, lines
    good, lines = verify_scene([{"object": "green block", "zone": "L-near"},
                                {"object": "red tape roll", "zone": "C-near"}], props, crop, 0)
    assert good, lines
    bad, lines = verify_scene([{"object": "green block", "zone": "L-far"},
                               {"object": "red tape roll", "zone": "C-near"}], props, crop, 0)
    assert not bad and any(s == "wrong" for s, _ in lines), lines
    bad, lines = verify_scene([{"object": "green block", "zone": "R"},
                               {"object": "red tape roll", "zone": "C"}], props, crop, 0)
    assert not bad and any(s == "wrong" for s, _ in lines), lines
    bad, lines = verify_scene([{"object": "blue block", "zone": "L"}], props, crop, 0)
    assert not bad and any(s == "missing" for s, _ in lines), lines
    assert any(s == "extra" for s, _ in lines), lines

    # Furniture above the staging area is never a stray prop.
    up = np.zeros((480, 640, 3), np.uint8)
    cv2.rectangle(up, (20, 30), (60, 70), (220, 200, 30), -1)     # yellow, well above the table
    assert outside_crop(up, crop) and not outside_crop(up, crop, skip_top=110)
    print("framing selftest ok")


if __name__ == "__main__":
    selftest()
