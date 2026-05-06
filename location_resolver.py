#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高德地图位置解析：地址 → 经纬度 → 区域标签 (AOI > 附近POI > KMeans)"""

import os, json, time, hashlib
from pathlib import Path
from collections import defaultdict
import requests
AMAP_KEY = os.environ.get("AMAP_API_KEY", "")
CACHE_DIR = Path(__file__).parent / ".amap_cache"
CACHE_TTL = 30 * 24 * 3600


# ── 缓存 ──

def _load(key: str) -> dict | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"geo_{hashlib.md5(key.encode()).hexdigest()}.json"
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
            if time.time() - d.get("_ts", 0) < CACHE_TTL:
                return d
        except (json.JSONDecodeError, KeyError):
            pass


def _save(key: str, data: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["_ts"] = time.time()
    p = CACHE_DIR / f"geo_{hashlib.md5(key.encode()).hexdigest()}.json"
    p.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _api(url: str, params: dict) -> dict:
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 0:
                time.sleep(1)
    return {"status": "0"}


# ── 地址 → 经纬度（POI 关键字搜索） ──

def geocode(address: str, city: str = "") -> tuple[float, float] | None:
    if not address or not AMAP_KEY:
        return None

    ck = f"gc:{address}"
    c = _load(ck)
    if c:
        return None if c.get("_nf") else (c["c"][0], c["c"][1])

    data = _api("https://restapi.amap.com/v3/place/text", {
        "key": AMAP_KEY, "keywords": address, "city": city,
        "offset": 1, "page": 1, "extensions": "base",
    })

    coords = None
    if data.get("status") == "1" and data.get("pois"):
        lng_str, lat_str = data["pois"][0]["location"].split(",")
        coords = (float(lng_str), float(lat_str))

    _save(ck, {"c": list(coords)} if coords else {"_nf": True})
    return coords


# ── 经纬度 → 结构化区域 ──

def regeocode(lng: float, lat: float) -> dict:
    if not AMAP_KEY:
        return {}

    ck = f"rg:{lng:.6f},{lat:.6f}"
    c = _load(ck)
    if c:
        return c.get("a", {})

    data = _api("https://restapi.amap.com/v3/geocode/regeo", {
        "key": AMAP_KEY, "location": f"{lng:.6f},{lat:.6f}",
        "extensions": "all",
    })

    r = {}
    if data.get("status") == "1":
        rg = data["regeocode"]
        comp = rg.get("addressComponent", {})
        r = {
            "formatted_address": rg.get("formatted_address", ""),
            "province": comp.get("province", ""),
            "city": comp.get("city", "") or comp.get("province", ""),
            "district": comp.get("district", ""),
            "township": comp.get("township", ""),
            "aois": [a.get("name", "") for a in rg.get("aois", [])],
            "pois": [p.get("name", "") for p in rg.get("pois", [])],
        }
    _save(ck, {"a": r})
    return r


# ── 聚类标签（AOI > 附近POI > KMeans等待） ──

def _try_aoi_poi(region: dict) -> str | None:
    """尝试 AOI 或附近 POI，成功返回标签，失败返回 None"""
    aois = region.get("aois", [])
    if aois:
        return aois[0]
    pois = region.get("pois", [])
    if pois:
        return pois[0]
    return None


def _dbscan_cluster(points: list[tuple[float, float]],
                    eps: float = 0.003, min_samples: int = 2
                    ) -> tuple[list[int], dict[int, tuple[float, float]]]:
    """DBSCAN 聚类 (r≈300m, ≥2点成簇) → (标签列表, {簇编号: 簇中心})。噪声点=-1"""
    import numpy as np
    from sklearn.cluster import DBSCAN

    arr = np.array(points)
    if len(points) <= 1:
        l: list[int] = [0] * len(points)
        c: dict[int, tuple[float, float]] = {0: points[0]} if points else {}
        return l, c

    db = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean")
    labels = db.fit_predict(arr).tolist()

    centers = {}
    for lid in set(labels):
        if lid == -1:
            continue
        mask = np.array(labels) == lid
        c = arr[mask].mean(axis=0)
        centers[lid] = (round(c[0], 3), round(c[1], 3))

    return labels, centers


# ── 手动坐标 ──

try:
    _MANUAL: dict[str, tuple[float, float]] = {
        k: (v[0], v[1]) for k, v in
        json.loads(os.environ.get("HARDCODED_LOCATIONS", "{}")).items()
    }
except Exception:
    _MANUAL = {}


# ── 批量处理 ──

def enrich_transactions(transactions: list[dict], city: str = "",
                        dbscan_eps: float = 0.003, dbscan_min_samples: int = 2) -> list[dict]:
    """为每笔交易附加: lng, lat, aoi_label 及区域信息
    
    第一阶段：geocode + regeocode，AOI/POI 标签
    第二阶段：剩余未标记点 → DBSCAN 聚类
    """
    result = []
    dbscan_queue: list[tuple[int, float, float]] = []

    for idx, t in enumerate(transactions):
        addr = (t.get("address", "") or "").strip()
        out = dict(t, lng=None, lat=None, aoi_label="", district="",
                   township="", formatted_address="", aois=[], pois=[])
        if not addr:
            result.append(out); continue

        time.sleep(0.05)
        coords = _MANUAL.get(addr)
        if not coords and _MANUAL:
            for key, val in _MANUAL.items():
                if addr.startswith(key) and len(addr) > len(key):
                    coords = geocode(addr[len(key):].strip(), city) or val; break
        coords = coords or geocode(addr, city)
        if not coords:
            result.append(out); continue

        out["lng"] = coords[0]
        out["lat"] = coords[1]
        region = regeocode(*coords)

        label = _try_aoi_poi(region)
        if label:
            out["aoi_label"] = label
        else:
            dbscan_queue.append((len(result), *coords))

        out.update(district=region.get("district", ""),
                   township=region.get("township", ""),
                   formatted_address=region.get("formatted_address", ""),
                   aois=region.get("aois", []),
                   pois=region.get("pois", []))
        result.append(out)

    # ── 第二阶段：DBSCAN 聚类 ──
    if dbscan_queue:
        indices = [i for i, _, _ in dbscan_queue]
        pts = [(lng, lat) for _, lng, lat in dbscan_queue]
        labels, centers = _dbscan_cluster(pts, eps=dbscan_eps, min_samples=dbscan_min_samples)
        for i, lid in zip(indices, labels):
            if lid == -1:
                cx, cy = pts[indices.index(i)]
                result[i]["aoi_label"] = f"附近({round(cx,3)},{round(cy,3)})"
            else:
                cx, cy = centers[lid]
                result[i]["aoi_label"] = f"区域{lid + 1}({cx},{cy})"

    return result


# ── 区域聚合摘要 ──

def area_summary(transactions: list[dict]) -> dict:
    with_loc = [t for t in transactions if t.get("lng") is not None]
    wo = len(transactions) - len(with_loc)
    if not with_loc:
        return {"clusters": [], "stats": {"total_with_location": 0,
                "total_without_location": wo, "cluster_count": 0}}

    groups = defaultdict(list)
    for t in with_loc:
        label = t.get("aoi_label", "未标记")
        groups[label].append(t)

    clusters = []
    for label, pts in groups.items():
        total = sum(abs(p.get("amount", 0)) for p in pts)
        cats = defaultdict(float)
        for p in pts:
            cats[p.get("category", "未知")] += abs(p.get("amount", 0))
        clusters.append({
            "aoi_label": label, "count": len(pts),
            "total_amount": round(total, 2),
            "avg_amount": round(total / len(pts), 2),
            "top_categories": dict(sorted(cats.items(), key=lambda x: -x[1])[:5]),
        })
    clusters.sort(key=lambda x: -x["total_amount"])
    return {"clusters": clusters, "stats": {"total_with_location": len(with_loc),
            "total_without_location": wo, "cluster_count": len(clusters)}}


def cluster_label(region: dict, lng: float, lat: float) -> str:
    return _try_aoi_poi(region) or f"({round(lng,3)},{round(lat,3)})"
