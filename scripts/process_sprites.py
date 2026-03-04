#!/usr/bin/env python3
"""Process Gemini-generated pixel art into game-ready sprite sheets.

Converts JPG images with checkerboard backgrounds into PNG sprite sheets
with proper transparency, sized for the Pixel Office v2 game engine.

Character sprites: 192x384 (4 cols x 8 rows of 48x48 frames)
Cat sprites: 128x128 (4 cols x 4 rows of 32x32 frames)
Office background: 960x544 (no transparency)
"""

from PIL import Image
import numpy as np
from collections import deque
import os
import sys

SRC_DIR = '/Users/meyanik/Dosyalar/Projects/Agentic-Lane/images_generated'
DST_DIR = '/Users/meyanik/Dosyalar/Projects/Agentic-Lane/dashboard-ui/public/office'

# === File mappings ===
# Identified by viewing each image

OFFICE_BG = 'Gemini_Generated_Image_gneapdgneapdgnea.jpg'

CHARACTER_SPRITES = {
    'worker':    'Gemini_Generated_Image_35vf5h35vf5h35vf.jpg',  # Blue shirt
    'judge':     'Gemini_Generated_Image_u1mqlwu1mqlwu1mq.jpg',  # Gold vest
    'master':    'Gemini_Generated_Image_97mi6v97mi6v97mi.jpg',  # Purple outfit
    'rag':       'Gemini_Generated_Image_5tbsc05tbsc05tbs.jpg',  # Teal shirt
    'execution': 'Gemini_Generated_Image_5gi06l5gi06l5gi0.jpg',  # Gray shirt
}

CAT_SPRITES = {
    'cat_orange': 'Gemini_Generated_Image_unph6eunph6eunph.jpg',
    'cat_gray':   'Gemini_Generated_Image_v7akkev7akkev7ak.jpg',
    'cat_black':  'Gemini_Generated_Image_87yah087yah087ya.jpg',
    'cat_calico': 'Gemini_Generated_Image_63r06263r06263r0.jpg',
}

# Target dimensions
CHAR_FRAME = (48, 48)
CHAR_COLS, CHAR_ROWS = 4, 8
CAT_FRAME = (32, 32)
CAT_COLS, CAT_ROWS = 4, 4
BG_SIZE = (960, 544)


def remove_background(img, bg_threshold=165, sat_threshold=30):
    """Remove checkerboard/solid background using flood fill from edges.

    1. Creates a mask of 'potentially background' pixels (high-value, low-saturation)
    2. Flood fills from all edge pixels + cell boundary pixels
    3. Returns RGBA image with background set to transparent
    """
    arr = np.array(img.convert('RGB'))
    h, w = arr.shape[:2]

    r = arr[:, :, 0].astype(np.int16)
    g = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)

    max_rgb = np.maximum(r, np.maximum(g, b))
    min_rgb = np.minimum(r, np.minimum(g, b))
    saturation = max_rgb - min_rgb

    # Background pixels: high brightness, low saturation (gray/white)
    bg_mask = (min_rgb >= bg_threshold) & (saturation < sat_threshold)

    # Flood fill from edges using BFS (8-connected for better coverage)
    visited = np.zeros((h, w), dtype=bool)
    queue = deque()

    # Seed from all edge pixels that match background
    for x in range(w):
        if bg_mask[0, x] and not visited[0, x]:
            visited[0, x] = True
            queue.append((0, x))
        if bg_mask[h - 1, x] and not visited[h - 1, x]:
            visited[h - 1, x] = True
            queue.append((h - 1, x))
    for y in range(1, h - 1):
        if bg_mask[y, 0] and not visited[y, 0]:
            visited[y, 0] = True
            queue.append((y, 0))
        if bg_mask[y, w - 1] and not visited[y, w - 1]:
            visited[y, w - 1] = True
            queue.append((y, w - 1))

    # 8-connected BFS flood fill (includes diagonals for better connectivity)
    neighbors = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    while queue:
        cy, cx = queue.popleft()
        for dy, dx in neighbors:
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and bg_mask[ny, nx]:
                visited[ny, nx] = True
                queue.append((ny, nx))

    # Create RGBA with background pixels transparent
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = arr
    rgba[:, :, 3] = np.where(visited, 0, 255).astype(np.uint8)

    return Image.fromarray(rgba, 'RGBA')


def process_sprite_sheet(src_path, cols, rows, frame_w, frame_h, name=''):
    """Process a sprite sheet: remove bg, extract/resize frames, reassemble."""
    print(f'  Loading {os.path.basename(src_path)}...')
    img = Image.open(src_path)
    w, h = img.size
    src_fw = w // cols
    src_fh = h // rows
    print(f'  Source: {w}x{h}, cell: {src_fw}x{src_fh}')

    print(f'  Removing background...')
    rgba = remove_background(img)

    # Create target sprite sheet
    target_w = cols * frame_w
    target_h = rows * frame_h
    sheet = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))

    for row in range(rows):
        for col in range(cols):
            # Extract source frame
            x1 = col * src_fw
            y1 = row * src_fh
            x2 = x1 + src_fw
            y2 = y1 + src_fh
            frame = rgba.crop((x1, y1, x2, y2))

            # Resize to target frame size
            frame = frame.resize((frame_w, frame_h), Image.LANCZOS)

            # Paste into target sheet
            tx = col * frame_w
            ty = row * frame_h
            sheet.paste(frame, (tx, ty))

    print(f'  Output: {target_w}x{target_h} ({cols}x{rows} frames of {frame_w}x{frame_h})')
    return sheet


def process_background(src_path, target_w, target_h):
    """Process office background: resize to target dimensions, no transparency."""
    print(f'  Loading {os.path.basename(src_path)}...')
    img = Image.open(src_path).convert('RGB')
    w, h = img.size
    print(f'  Source: {w}x{h} -> Target: {target_w}x{target_h}')
    return img.resize((target_w, target_h), Image.LANCZOS)


def main():
    os.makedirs(DST_DIR, exist_ok=True)

    # 1. Office background
    print('\n=== Office Background ===')
    bg = process_background(
        os.path.join(SRC_DIR, OFFICE_BG),
        BG_SIZE[0], BG_SIZE[1]
    )
    bg.save(os.path.join(DST_DIR, 'office_background.png'))
    print(f'  Saved: office_background.png')

    # 2. Character sprite sheets
    print('\n=== Character Sprites ===')
    for name, fname in CHARACTER_SPRITES.items():
        print(f'\nProcessing {name}:')
        sheet = process_sprite_sheet(
            os.path.join(SRC_DIR, fname),
            CHAR_COLS, CHAR_ROWS,
            CHAR_FRAME[0], CHAR_FRAME[1],
            name
        )
        out_path = os.path.join(DST_DIR, f'{name}.png')
        sheet.save(out_path)
        print(f'  Saved: {name}.png')

    # 3. Cat sprite sheets
    print('\n=== Cat Sprites ===')
    for name, fname in CAT_SPRITES.items():
        print(f'\nProcessing {name}:')
        sheet = process_sprite_sheet(
            os.path.join(SRC_DIR, fname),
            CAT_COLS, CAT_ROWS,
            CAT_FRAME[0], CAT_FRAME[1],
            name
        )
        out_path = os.path.join(DST_DIR, f'{name}.png')
        sheet.save(out_path)
        print(f'  Saved: {name}.png')

    print('\n=== Done! ===')
    print(f'All files saved to {DST_DIR}')

    # List output
    print('\nOutput files:')
    for f in sorted(os.listdir(DST_DIR)):
        size = os.path.getsize(os.path.join(DST_DIR, f))
        print(f'  {f}: {size:,} bytes')


if __name__ == '__main__':
    main()
