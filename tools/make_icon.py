#!/usr/bin/env python3
"""bullsTerminal 앱 아이콘 생성기 (표준 라이브러리만 사용).

`assets/bullsterminal.svg` 와 동일한 도형 정의를 래스터로 그려서
  - assets/bullsterminal.ico  (Windows 실행파일/작업표시줄, 16~256px 멀티 사이즈)
  - assets/bullsterminal.png  (Linux 런타임/hicolor 256px)
를 만든다.

사용법:
    python tools/make_icon.py
"""
from __future__ import annotations

import os
import struct
import sys
import zlib

# ---------------------------------------------------------------- 색상/치수
# 좌표는 256x256 캔버스 기준(= SVG viewBox 와 동일).
BG = (0x15, 0x1B, 0x26)      # 터미널 창 배경
TITLE = (0x20, 0x29, 0x38)   # 타이틀바
LINE = (0x2E, 0x3A, 0x4E)    # 테두리/구분선
RED = (0xFF, 0x5F, 0x57)
YELLOW = (0xFE, 0xBC, 0x2E)
GREEN = (0x28, 0xC8, 0x40)
PROMPT = (0x46, 0xD1, 0x7F)  # 프롬프트 >_
LOCK = (0xF2, 0xB4, 0x41)    # 자물쇠(= secure shell)

MASTER = 1536                # 마스터 렌더 해상도(256 의 6배, 16/24/32/48 로 나누어떨어짐)
SCALE = MASTER / 256.0
ICO_SIZES = (256, 128, 64, 48, 32, 24, 16)


# ------------------------------------------------------------------- 도형들
def rrect(x0, y0, x1, y1, r):
    """둥근 사각형(라운드 반경 r)."""
    def f(x, y):
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        cx = min(max(x, x0 + r), x1 - r)
        cy = min(max(y, y0 + r), y1 - r)
        dx, dy = x - cx, y - cy
        return dx * dx + dy * dy <= r * r
    f.bbox = (x0, y0, x1, y1)
    return f


def circle(cx, cy, r):
    def f(x, y):
        dx, dy = x - cx, y - cy
        return dx * dx + dy * dy <= r * r
    f.bbox = (cx - r, cy - r, cx + r, cy + r)
    return f


def ring_upper(cx, cy, ro, ri):
    """위쪽 절반만 남긴 링(자물쇠 고리)."""
    def f(x, y):
        if y > cy:
            return False
        dx, dy = x - cx, y - cy
        d2 = dx * dx + dy * dy
        return ri * ri <= d2 <= ro * ro
    f.bbox = (cx - ro, cy - ro, cx + ro, cy)
    return f


def polyline(points, w):
    """둥근 끝/이음을 가진 선분 묶음(프롬프트 꺾쇠)."""
    half = w / 2.0
    segs = list(zip(points[:-1], points[1:]))

    def f(x, y):
        for (ax, ay), (bx, by) in segs:
            vx, vy = bx - ax, by - ay
            wx, wy = x - ax, y - ay
            L2 = vx * vx + vy * vy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
            dx, dy = wx - t * vx, wy - t * vy
            if dx * dx + dy * dy <= half * half:
                return True
        return False
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    f.bbox = (min(xs) - half, min(ys) - half, max(xs) + half, max(ys) + half)
    return f


def both(a, b):
    """두 도형의 교집합(창 모양으로 잘라내기)."""
    def f(x, y):
        return a(x, y) and b(x, y)
    ax0, ay0, ax1, ay1 = a.bbox
    bx0, by0, bx1, by1 = b.bbox
    f.bbox = (max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1))
    return f


def sub(a, b):
    """a 에서 b 를 뺀 영역(테두리)."""
    def f(x, y):
        return a(x, y) and not b(x, y)
    f.bbox = a.bbox
    return f


def build_shapes():
    """(도형, 색) 목록을 뒤쪽이 위로 오도록 순서대로 반환."""
    win = rrect(8, 8, 248, 248, 52)
    inner = rrect(11, 11, 245, 245, 49)

    def clip(shape):
        return both(win, shape)

    shapes = [
        (win, BG),                                        # 창 배경
        (clip(rrect(8, 8, 248, 58, 0)), TITLE),           # 타이틀바
        (clip(rrect(8, 58, 248, 61.5, 0)), LINE),         # 구분선
        (sub(win, inner), LINE),                          # 테두리
        (clip(circle(40, 34, 7)), RED),                   # 신호등 3개
        (clip(circle(68, 34, 7)), YELLOW),
        (clip(circle(96, 34, 7)), GREEN),
        # 자물쇠 외곽 여백(배경색으로 5px 확장해 프롬프트와 분리)
        (clip(rrect(159, 175, 233, 235, 15)), BG),
        (clip(ring_upper(196, 180, 29, 10)), BG),
        # 자물쇠
        (clip(rrect(164, 180, 228, 230, 10)), LOCK),
        (clip(ring_upper(196, 180, 24, 15)), LOCK),
        (clip(circle(196, 202, 6)), BG),                  # 열쇠구멍
        (clip(rrect(193, 202, 199, 216, 3)), BG),
        # 프롬프트 >_
        (clip(polyline([(56, 92), (96, 124), (56, 156)], 18)), PROMPT),
        (clip(rrect(108, 138, 164, 156, 9)), PROMPT),
    ]
    return shapes


# ----------------------------------------------------------------- 래스터화
def render_master() -> bytearray:
    """마스터 해상도로 RGBA 버퍼를 렌더링(다운샘플로 안티에일리어싱)."""
    buf = bytearray(MASTER * MASTER * 4)  # 초기값 0 = 완전 투명
    for shape, (r, g, b) in build_shapes():
        x0, y0, x1, y1 = shape.bbox
        px0 = max(0, int(x0 * SCALE) - 1)
        px1 = min(MASTER - 1, int(x1 * SCALE) + 1)
        py0 = max(0, int(y0 * SCALE) - 1)
        py1 = min(MASTER - 1, int(y1 * SCALE) + 1)
        for py in range(py0, py1 + 1):
            y = (py + 0.5) / SCALE
            row = py * MASTER * 4
            for px in range(px0, px1 + 1):
                if shape((px + 0.5) / SCALE, y):
                    o = row + px * 4
                    buf[o] = r
                    buf[o + 1] = g
                    buf[o + 2] = b
                    buf[o + 3] = 255
    return buf


def downsample(src: bytearray, sw: int, factor: int) -> bytearray:
    """박스 필터 축소. 알파를 곱한 값으로 평균내어 가장자리 검은 테를 막는다."""
    dw = sw // factor
    n = factor * factor
    dst = bytearray(dw * dw * 4)
    for dy in range(dw):
        for dx in range(dw):
            sr = sg = sb = sa = 0
            for yy in range(dy * factor, (dy + 1) * factor):
                base = (yy * sw + dx * factor) * 4
                for k in range(factor):
                    o = base + k * 4
                    a = src[o + 3]
                    if a:
                        sr += src[o] * a
                        sg += src[o + 1] * a
                        sb += src[o + 2] * a
                        sa += a
            o = (dy * dw + dx) * 4
            if sa:
                dst[o] = min(255, (sr + sa // 2) // sa)
                dst[o + 1] = min(255, (sg + sa // 2) // sa)
                dst[o + 2] = min(255, (sb + sa // 2) // sa)
                dst[o + 3] = (sa + n // 2) // n
    return dst


# -------------------------------------------------------------- 파일 포맷들
def png_bytes(rgba: bytearray, w: int) -> bytes:
    raw = bytearray()
    for y in range(w):
        raw.append(0)  # 필터 타입 0(None)
        raw += rgba[y * w * 4:(y + 1) * w * 4]

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, w, 8, 6, 0, 0, 0)  # 8bit RGBA
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def dib_bytes(rgba: bytearray, w: int) -> bytes:
    """ICO 내부용 32bit BGRA DIB(아래→위) + AND 마스크."""
    hdr = struct.pack("<IiiHHIIiiII", 40, w, w * 2, 1, 32, 0, w * w * 4, 0, 0, 0, 0)
    px = bytearray()
    for y in range(w - 1, -1, -1):
        row = y * w * 4
        for x in range(w):
            o = row + x * 4
            px += bytes((rgba[o + 2], rgba[o + 1], rgba[o], rgba[o + 3]))
    stride = ((w + 31) // 32) * 4
    mask = bytearray()
    for y in range(w - 1, -1, -1):
        bits = bytearray(stride)
        for x in range(w):
            if rgba[(y * w + x) * 4 + 3] == 0:
                bits[x >> 3] |= 0x80 >> (x & 7)
        mask += bits
    return hdr + bytes(px) + bytes(mask)


def ico_bytes(images: "list[tuple[int, bytes]]") -> bytes:
    n = len(images)
    entries = b""
    blobs = b""
    offset = 6 + 16 * n
    for size, data in images:
        d = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", d, d, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    return struct.pack("<HHH", 0, 1, n) + entries + blobs


# ------------------------------------------------------------------- 엔트리
def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "assets")
    os.makedirs(out_dir, exist_ok=True)

    print(f"마스터 렌더링 {MASTER}x{MASTER} ...", flush=True)
    master = render_master()

    # 256 과 48 은 마스터에서 직접, 나머지는 절반씩 줄여 비용을 낮춘다.
    sized = {}
    sized[256] = downsample(master, MASTER, MASTER // 256)
    sized[48] = downsample(master, MASTER, MASTER // 48)
    for src, dst in ((256, 128), (128, 64), (64, 32), (32, 16), (48, 24)):
        sized[dst] = downsample(sized[src], src, 2)

    png_path = os.path.join(out_dir, "bullsterminal.png")
    with open(png_path, "wb") as f:
        f.write(png_bytes(sized[256], 256))
    print(f"작성: {png_path}")

    # 256/128 은 PNG 압축 엔트리, 작은 크기는 호환성을 위해 DIB 엔트리.
    images = []
    for s in ICO_SIZES:
        data = png_bytes(sized[s], s) if s >= 128 else dib_bytes(sized[s], s)
        images.append((s, data))
    ico_path = os.path.join(out_dir, "bullsterminal.ico")
    with open(ico_path, "wb") as f:
        f.write(ico_bytes(images))
    print(f"작성: {ico_path} ({', '.join(str(s) for s in ICO_SIZES)}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
