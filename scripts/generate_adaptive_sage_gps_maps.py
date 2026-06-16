from __future__ import annotations

import io
import csv
import math
import sys
import urllib.request
from dataclasses import asdict
from pathlib import Path

import matplotlib.pyplot as plt
import mercantile
import numpy as np
from matplotlib.collections import LineCollection
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io.bin_read import FRAME_RATE_HZ, _load_frames, _parse_gps
from src.ui_dataset import DEFAULT_ZJK_TX_GPS, distance_3d_m

DATA_DIR = Path('/mnt/win_data/data_mea/zjk_mea')
OUT_ROOT = Path('/home/guo/桌面/win_data/data_mea/zjk_mea/sage_outputs/adaptive_w20_step100')
WINDOW_SIZE = 20
STEP = 100
TX_GPS = DEFAULT_ZJK_TX_GPS
TILE_CACHE_DIR = ROOT / 'data' / 'tile_cache' / 'esri_imagery'
ESRI_TILE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
ESRI_UA = 'Mozilla/5.0 chan_meas research dashboard contact guomingqi99@gmail.com'
PROVIDER_NAME = 'UI base map: Esri World Imagery via local proxy/cache logic'
MAP_ZOOM = 17
TILE_SIZE = 256


def _window_centers(n_frames: int, window_size: int = WINDOW_SIZE, step: int = STEP) -> np.ndarray:
    if n_frames < window_size:
        return np.array([], dtype=np.int64)
    starts = np.arange(0, n_frames - window_size + 1, step, dtype=np.int64)
    return starts + window_size // 2


def _project_lonlat(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    transformer = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
    x, y = transformer.transform(lon, lat)
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def _expand_bounds(x: np.ndarray, y: np.ndarray, pad_ratio: float = 0.12, min_pad_m: float = 80.0) -> tuple[float, float, float, float]:
    xmin, xmax = float(np.min(x)), float(np.max(x))
    ymin, ymax = float(np.min(y)), float(np.max(y))
    dx = max(xmax - xmin, 1.0)
    dy = max(ymax - ymin, 1.0)
    pad_x = max(dx * pad_ratio, min_pad_m)
    pad_y = max(dy * pad_ratio, min_pad_m)
    return xmin - pad_x, xmax + pad_x, ymin - pad_y, ymax + pad_y


def _load_or_fetch_map_tile(z: int, x: int, y: int, cache_dir: Path = TILE_CACHE_DIR) -> bytes:
    if not (0 <= int(z) <= 19 and int(x) >= 0 and int(y) >= 0):
        raise ValueError('invalid tile coordinates')
    path = cache_dir / str(int(z)) / str(int(x)) / f'{int(y)}.jpg'
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    url = ESRI_TILE_URL.format(z=int(z), x=int(x), y=int(y))
    req = urllib.request.Request(url, headers={'User-Agent': ESRI_UA})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read()
    path.write_bytes(data)
    return data


def _mercator_bounds_to_lonlat_bounds(xmin: float, xmax: float, ymin: float, ymax: float) -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs('EPSG:3857', 'EPSG:4326', always_xy=True)
    west, south = transformer.transform(xmin, ymin)
    east, north = transformer.transform(xmax, ymax)
    return float(west), float(south), float(east), float(north)


def _stitch_ui_tiles(xmin: float, xmax: float, ymin: float, ymax: float, zoom: int = MAP_ZOOM) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    west, south, east, north = _mercator_bounds_to_lonlat_bounds(xmin, xmax, ymin, ymax)
    tiles = list(mercantile.tiles(west, south, east, north, [zoom]))
    if not tiles:
        raise RuntimeError('no map tiles resolved for requested bounds')

    min_x = min(t.x for t in tiles)
    max_x = max(t.x for t in tiles)
    min_y = min(t.y for t in tiles)
    max_y = max(t.y for t in tiles)
    mosaic = Image.new('RGB', ((max_x - min_x + 1) * TILE_SIZE, (max_y - min_y + 1) * TILE_SIZE))

    for tile in tiles:
        tile_bytes = _load_or_fetch_map_tile(tile.z, tile.x, tile.y, cache_dir=TILE_CACHE_DIR)
        tile_img = Image.open(io.BytesIO(tile_bytes)).convert('RGB')
        mosaic.paste(tile_img, ((tile.x - min_x) * TILE_SIZE, (tile.y - min_y) * TILE_SIZE))

    west_top = mercantile.ul(min_x, min_y, zoom)
    east_bottom = mercantile.bounds(max_x, max_y, zoom)
    x0, y1 = _project_lonlat(np.array([west_top.lng]), np.array([west_top.lat]))
    x1, y0 = _project_lonlat(np.array([east_bottom.east]), np.array([east_bottom.south]))
    extent = (float(x0[0]), float(x1[0]), float(y0[0]), float(y1[0]))
    return np.asarray(mosaic), extent


def _plot_colored_track(ax, x: np.ndarray, y: np.ndarray, values: np.ndarray, *, cmap: str = 'turbo', lw: float = 2.0):
    if len(x) < 2:
        return None
    points = np.column_stack([x, y]).reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    norm_values = np.asarray(values[:-1], dtype=np.float64)
    lc = LineCollection(segments, cmap=cmap, linewidths=lw, alpha=0.95)
    lc.set_array(norm_values)
    ax.add_collection(lc)
    return lc


def _write_window_csv(path: Path, gps: dict[str, np.ndarray], centers: np.ndarray) -> dict[str, float]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'window_index', 'center_frame', 'time_sec', 'lat', 'lon', 'alt_m',
            'hour', 'minute', 'second', 'distance_to_tx_m'
        ])
        for i, frame_idx in enumerate(centers):
            lat = float(gps['lat'][frame_idx])
            lon = float(gps['lon'][frame_idx])
            alt = float(gps['alt'][frame_idx])
            writer.writerow([
                i,
                int(frame_idx),
                round(float(frame_idx) / float(FRAME_RATE_HZ), 6),
                round(lat, 9),
                round(lon, 9),
                round(alt, 3),
                int(gps['hour'][frame_idx]),
                int(gps['minute'][frame_idx]),
                int(gps['second'][frame_idx]),
                round(float(distance_3d_m(TX_GPS, lat, lon, alt)), 3),
            ])

    dists = np.array([distance_3d_m(TX_GPS, float(gps['lat'][i]), float(gps['lon'][i]), float(gps['alt'][i])) for i in centers], dtype=np.float64)
    return {
        'n_window_points': int(len(centers)),
        'distance_min_m': float(np.min(dists)) if len(dists) else math.nan,
        'distance_max_m': float(np.max(dists)) if len(dists) else math.nan,
        'distance_mean_m': float(np.mean(dists)) if len(dists) else math.nan,
    }


def _write_summary(path: Path, bin_path: Path, gps: dict[str, np.ndarray], centers: np.ndarray, dist_stats: dict[str, float]) -> None:
    raw_count = len(gps['lat'])
    summary = {
        'bin_path': str(bin_path),
        'frame_rate_hz': float(FRAME_RATE_HZ),
        'window_size_frames': WINDOW_SIZE,
        'step_frames': STEP,
        'raw_gps_points': int(raw_count),
        'window_center_points': int(len(centers)),
        'lat_min': float(np.min(gps['lat'])),
        'lat_max': float(np.max(gps['lat'])),
        'lon_min': float(np.min(gps['lon'])),
        'lon_max': float(np.max(gps['lon'])),
        'alt_min_m': float(np.min(gps['alt'])),
        'alt_max_m': float(np.max(gps['alt'])),
        'tx_gps': asdict(TX_GPS),
        'map_provider': PROVIDER_NAME,
        **dist_stats,
    }
    lines = [f'{k}: {v}' for k, v in summary.items()]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _make_map(out_png: Path, title: str, gps: dict[str, np.ndarray], centers: np.ndarray) -> None:
    lat = np.asarray(gps['lat'], dtype=np.float64)
    lon = np.asarray(gps['lon'], dtype=np.float64)
    alt = np.asarray(gps['alt'], dtype=np.float64)

    x_raw, y_raw = _project_lonlat(lon, lat)
    center_lat = lat[centers]
    center_lon = lon[centers]
    center_alt = alt[centers]
    center_x, center_y = _project_lonlat(center_lon, center_lat)
    tx_x, tx_y = _project_lonlat(np.array([TX_GPS.lon]), np.array([TX_GPS.lat]))

    fig, ax = plt.subplots(figsize=(11, 11), dpi=180)
    xmin, xmax, ymin, ymax = _expand_bounds(np.concatenate([x_raw, tx_x]), np.concatenate([y_raw, tx_y]))
    basemap_img, basemap_extent = _stitch_ui_tiles(xmin, xmax, ymin, ymax, zoom=MAP_ZOOM)
    ax.imshow(basemap_img, extent=basemap_extent, origin='upper', zorder=0)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)

    ax.plot(x_raw, y_raw, color='white', linewidth=5.0, alpha=0.55, solid_capstyle='round', zorder=3)

    times = centers.astype(np.float64) / float(FRAME_RATE_HZ)
    lc = _plot_colored_track(ax, center_x, center_y, times, cmap='turbo', lw=2.5)
    scatter = ax.scatter(center_x, center_y, c=times, cmap='turbo', s=18, edgecolors='black', linewidths=0.25, zorder=5)

    ax.scatter(tx_x, tx_y, marker='^', s=170, color='#ffcc00', edgecolors='black', linewidths=1.0, zorder=7, label='TX')
    ax.scatter(center_x[0], center_y[0], marker='o', s=100, color='#00ff7f', edgecolors='black', linewidths=0.8, zorder=7, label='RX start')
    ax.scatter(center_x[-1], center_y[-1], marker='X', s=120, color='#ff4d4f', edgecolors='black', linewidths=0.8, zorder=7, label='RX end')

    ax.set_title(f'{title}\nGPS trajectory aligned to adaptive windows (w=20, step=100, 1 s centers)', fontsize=13)
    ax.set_axis_off()

    cbar = fig.colorbar(scatter, ax=ax, fraction=0.035, pad=0.01)
    cbar.set_label('Time (s)', fontsize=10)

    dists = np.array([distance_3d_m(TX_GPS, float(la), float(lo), float(al)) for la, lo, al in zip(center_lat, center_lon, center_alt)], dtype=np.float64)
    info = (
        f'Window points: {len(centers)}\n'
        f'Raw GPS frames: {len(lat)}\n'
        f'Distance to TX: {np.min(dists):.2f}–{np.max(dists):.2f} m\n'
        f'Altitude: {np.min(center_alt):.1f}–{np.max(center_alt):.1f} m'
    )
    ax.text(
        0.015, 0.02, info,
        transform=ax.transAxes,
        fontsize=9,
        color='white',
        bbox=dict(boxstyle='round,pad=0.35', facecolor='black', alpha=0.6, edgecolor='white')
    )
    ax.legend(loc='upper right', fontsize=9, framealpha=0.85)

    fig.tight_layout()
    fig.savefig(out_png, bbox_inches='tight')
    plt.close(fig)


def main() -> None:
    subdirs = sorted([p for p in OUT_ROOT.iterdir() if p.is_dir()])
    if not subdirs:
        raise SystemExit(f'No subdirectories found under {OUT_ROOT}')

    for subdir in subdirs:
        stem = subdir.name
        bin_path = DATA_DIR / f'{stem}.bin'
        if not bin_path.exists():
            print(f'[WARN] Missing bin for {stem}: {bin_path}')
            continue

        print(f'[INFO] Processing {stem}')
        frames = _load_frames(bin_path, max_frames=None)
        gps = _parse_gps(frames)
        del frames

        centers = _window_centers(len(gps['lat']))
        if len(centers) == 0:
            print(f'[WARN] No valid window centers for {stem}')
            continue

        csv_path = subdir / 'adaptive_window_center_gps.csv'
        png_path = subdir / 'adaptive_gps_map_with_basemap.png'
        txt_path = subdir / 'adaptive_gps_map_summary.txt'

        dist_stats = _write_window_csv(csv_path, gps, centers)
        _make_map(png_path, stem, gps, centers)
        _write_summary(txt_path, bin_path, gps, centers, dist_stats)

        print(f'  -> {csv_path}')
        print(f'  -> {png_path}')
        print(f'  -> {txt_path}')


if __name__ == '__main__':
    main()
