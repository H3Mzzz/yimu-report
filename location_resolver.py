#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高德地图位置解析模块

三层标签逻辑（对齐 test 脚本）：
  1. AOI（面状区域：学校、商场）
  2. POI（点状地标：餐厅、超市）
  3. DBSCAN 聚类兜底（r≈300m, ≥2 点成簇）

数据流：
  geocode(address)        → (lng, lat)
  regeocode(lng, lat)     → {aois, pois, district, ...}
  enrich_transactions(...) → 附加 lng/lat/aoi_label
  area_summary(...)        → 分组聚合摘要
"""

import os
import json
import time
import hashlib
import math
from pathlib import Path
from collections import defaultdict

import requests

AMAP_KEY = os.environ.get("AMAP_API_KEY", "")
CACHE_DIR = Path(__file__).parent / ".amap_cache"
CACHE_TTL = 30 * 24 * 3600
DEFAULT_CITY = os.environ.get("DEFAULT_GEOCODE_CITY", "蚌埠")


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
    return None


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


# ── 第一步：地址 → 经纬度（POI 关键字搜索）──

def geocode(address: str, city: str | None = None) -> tuple[float, float] | None:
    if not address or not AMAP_KEY:
        return None
    if city is None:
        city = DEFAULT_CITY

    ck = f"gc:{address}|{city}"
    c = _load(ck)
    if c:
        return None if c.get("_nf") else (c["c"][0], c["c"][1])

    data = _api("https://restapi.amap.com/v3/place/text", {
        "key": AMAP_KEY, "keywords": address, "city": city,
        "offset": 1, "page": 1, "extensions": "base",
    })

    coords = None
    if data.get("status") == "1" and data.get("pois"):
        loc = data["pois"][0]["location"]
        lng, lat = loc.split(",")
        coords = (float(lng), float(lat))

    _save(ck, {"c": list(coords)} if coords else {"_nf": True})
    return coords


# ── 第二步：经纬度 → 结构化区域 ──

def regeocode(lng: float, lat: float) -> dict:
    if not AMAP_KEY:
        return {}

    ck = f"rg:{lng:.6f},{lat:.6f}"
    c = _load(ck)
    if c:
        return c.get("a", {})

    data = _api("https://restapi.amap.com/v3/geocode/regeo", {
        "key": AMAP_KEY,
        "location": f"{lng:.6f},{lat:.6f}",
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


# ── 第三层兜底：DBSCAN 空间聚类 ──

def _haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _cluster_labels(points: list[tuple[float, float]],
                    eps: float = 0.003, min_samples: int = 2
                    ) -> tuple[list[int], dict[int, tuple[float, float]]]:
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN

        if len(points) <= 1:
            return [0] * len(points), {0: points[0]} if points else {}

        arr = np.array(points)
        db = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean")
        labels = db.fit_predict(arr).tolist()

        centers = {}
        for lid in set(labels):
            if lid == -1:
                continue
            mask = np.array(labels) == lid
            c = arr[mask].mean(axis=0)
            centers[lid] = (round(c[0], 6), round(c[1], 6))
        return labels, centers

    except ImportError:
        return _cluster_labels_pure_python(points, eps, min_samples)


def _cluster_labels_pure_python(points, eps, min_samples):
    n = len(points)
    if n == 0:
        return [], {}
    if n == 1:
        return [0], {0: points[0]}

    eps_m = eps * 111000
    UNVISITED, NOISE = 0, -1
    labels = [UNVISITED] * n
    cluster_id = 0

    for i in range(n):
        if labels[i] != UNVISITED:
            continue
        neighbors = [j for j in range(n)
                     if _haversine(*points[i], *points[j]) <= eps_m]
        if len(neighbors) < min_samples:
            labels[i] = NOISE
            continue
        cluster_id += 1
        labels[i] = cluster_id
        queue = list(neighbors)
        while queue:
            j = queue.pop(0)
            if labels[j] == NOISE:
                labels[j] = cluster_id
            if labels[j] != UNVISITED:
                continue
            labels[j] = cluster_id
            j_neighbors = [k for k in range(n)
                           if _haversine(*points[j], *points[k]) <= eps_m]
            if len(j_neighbors) >= min_samples:
                queue.extend(j_neighbors)

    centers = {}
    for cid in range(1, cluster_id + 1):
        members = [points[i] for i in range(n) if labels[i] == cid]
        if members:
            avg_lng = sum(p[0] for p in members) / len(members)
            avg_lat = sum(p[1] for p in members) / len(members)
            centers[cid] = (round(avg_lng, 6), round(avg_lat, 6))
    return labels, centers


# ── 标签解析 ──

def _resolve_label(region: dict) -> str | None:
    """AOI → POI → None（交给 DBSCAN 聚类兜底）"""
    aois = region.get("aois", [])
    if aois:
        return aois[0]
    pois = region.get("pois", [])
    if pois:
        return pois[0]
    return None


# ── 批量处理 ──

def enrich_transactions(transactions: list[dict], city: str | None = None,
                        dbscan_eps: float = 0.003,
                        dbscan_min_samples: int = 2) -> list[dict]:
    if city is None:
        city = DEFAULT_CITY

    result = []
    dbscan_queue: list[tuple[int, float, float]] = []

    for t in transactions:
        addr = (t.get("address", "") or "").strip()
        out = dict(t,
                   lng=None, lat=None, aoi_label="",
                   district="", township="", formatted_address="",
                   aois=[], pois=[])

        if not addr:
            result.append(out)
            continue

        time.sleep(0.05)
        coords = geocode(addr, city)
        if not coords:
            result.append(out)
            continue

        out["lng"], out["lat"] = coords
        region = regeocode(*coords)
        out["district"] = region.get("district", "")
        out["township"] = region.get("township", "")
        out["formatted_address"] = region.get("formatted_address", "")
        out["aois"] = region.get("aois", [])
        out["pois"] = region.get("pois", [])

        label = _resolve_label(region)
        if label:
            out["aoi_label"] = label
        else:
            dbscan_queue.append((len(result), coords[0], coords[1]))

        result.append(out)

    if dbscan_queue:
        indices = [i for i, _, _ in dbscan_queue]
        pts = [(lng, lat) for _, lng, lat in dbscan_queue]
        labels, centers = _cluster_labels(pts, eps=dbscan_eps, min_samples=dbscan_min_samples)

        for i, lid in zip(indices, labels):
            if lid == -1:
                cx, cy = pts[indices.index(i)]
                result[i]["aoi_label"] = f"附近({round(cx, 4)},{round(cy, 4)})"
            else:
                cx, cy = centers[lid]
                result[i]["aoi_label"] = f"区域{lid}({cx},{cy})"

    return result


# ── 区域聚合摘要 ──

def area_summary(transactions: list[dict],
                 eps_meters: float = 300,
                 min_samples: int = 2) -> dict:
    """
    对已 enrich 的交易按 aoi_label 分组聚合。
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for t in transactions:
        label = t.get("aoi_label", "")
        if label and t.get("lng") is not None:
            grouped[label].append(t)

    clusters = []
    for label, items in grouped.items():
        total_amount = sum(abs(it.get("amount", 0)) for it in items)
        cats: dict[str, float] = defaultdict(float)
        for it in items:
            cats[it.get("category", "未知")] += abs(it.get("amount", 0))
        top_cats = dict(sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5])

        clusters.append({
            "aoi_label": label,
            "count": len(items),
            "total_amount": round(total_amount, 2),
            "avg_amount": round(total_amount / len(items), 2) if items else 0,
            "top_categories": top_cats,
            "addresses": list(set(it.get("address", "") for it in items if it.get("address"))),
        })

    clusters.sort(key=lambda x: x["count"], reverse=True)

    with_loc = sum(1 for t in transactions if t.get("lng") is not None and t.get("aoi_label"))
    without_loc = sum(1 for t in transactions if t.get("lng") is None)

    return {
        "clusters": clusters,
        "stats": {
            "total_with_location": with_loc,
            "total_without_location": without_loc,
        },
    }
