#!/usr/bin/env python3
"""高德地图位置解析：地址→经纬度→AOI/POI/DBSCAN三级标签→区域聚合。"""

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
DEFAULT_CITY = os.environ.get("DEFAULT_GEOCODE_CITY", "")


def _load(key):
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


def _save(key, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["_ts"] = time.time()
    p = CACHE_DIR / f"geo_{hashlib.md5(key.encode()).hexdigest()}.json"
    p.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _api(url, params):
    for _ in range(2):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(1)
    return {"status": "0"}


def geocode(address, city=None):
    """地址 → (lng, lat)，使用高德 POI 关键字搜索。"""
    if not address or not AMAP_KEY:
        return None
    if city is None:
        city = DEFAULT_CITY

    ck = f"gc:{address}|{city}"
    cached = _load(ck)
    if cached:
        return None if cached.get("_nf") else (cached["c"][0], cached["c"][1])

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


def regeocode(lng, lat):
    """经纬度 → 结构化区域信息（AOI、POI、行政区划）。"""
    if not AMAP_KEY:
        return {}

    ck = f"rg:{lng:.6f},{lat:.6f}"
    cached = _load(ck)
    if cached:
        return cached.get("a", {})

    data = _api("https://restapi.amap.com/v3/geocode/regeo", {
        "key": AMAP_KEY, "location": f"{lng:.6f},{lat:.6f}", "extensions": "all",
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


def _haversine(lng1, lat1, lng2, lat2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _dbscan(points, eps=0.003, min_samples=2):
    """DBSCAN 空间聚类，优先使用 sklearn，回退纯 Python 实现。"""
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
        pass

    n = len(points)
    if n <= 1:
        return ([0] * n, {0: points[0]}) if n == 1 else ([], {})
    eps_m = eps * 111000
    labels = [0] * n
    cluster_id = 0
    for i in range(n):
        if labels[i] != 0:
            continue
        neighbors = [j for j in range(n) if _haversine(*points[i], *points[j]) <= eps_m]
        if len(neighbors) < min_samples:
            labels[i] = -1
            continue
        cluster_id += 1
        labels[i] = cluster_id
        queue = list(neighbors)
        while queue:
            j = queue.pop(0)
            if labels[j] == -1:
                labels[j] = cluster_id
            if labels[j] != 0:
                continue
            labels[j] = cluster_id
            j_neighbors = [k for k in range(n) if _haversine(*points[j], *points[k]) <= eps_m]
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


def _resolve_label(region):
    """AOI → POI → None（交给 DBSCAN 聚类兜底）。"""
    if region.get("aois"):
        return region["aois"][0]
    if region.get("pois"):
        return region["pois"][0]
    return None


def enrich_transactions(transactions, city=None, dbscan_eps=0.003, dbscan_min_samples=2):
    """批量解析交易地址，附加 lng/lat/aoi_label 等字段。"""
    if city is None:
        city = DEFAULT_CITY

    result = []
    dbscan_queue = []

    for t in transactions:
        addr = (t.get("address", "") or "").strip()
        out = dict(t, lng=None, lat=None, aoi_label="",
                   district="", township="", formatted_address="", aois=[], pois=[])

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
        labels, centers = _dbscan(pts, eps=dbscan_eps, min_samples=dbscan_min_samples)
        for i, lid in zip(indices, labels):
            if lid == -1:
                cx, cy = pts[indices.index(i)]
                result[i]["aoi_label"] = f"附近({round(cx, 4)},{round(cy, 4)})"
            else:
                cx, cy = centers[lid]
                result[i]["aoi_label"] = f"区域{lid}({cx},{cy})"

    return result


def area_summary(transactions, eps_meters=300, min_samples=2):
    """对已 enrich 的交易按 aoi_label 分组聚合，返回聚簇摘要。"""
    grouped = defaultdict(list)
    for t in transactions:
        label = t.get("aoi_label", "")
        if label and t.get("lng") is not None:
            grouped[label].append(t)

    clusters = []
    for label, items in grouped.items():
        total_amount = sum(abs(it.get("amount", 0)) for it in items)
        cats = defaultdict(float)
        for it in items:
            cats[it.get("category", "未知")] += abs(it.get("amount", 0))
        top_cats = dict(sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5])
        clusters.append({
            "aoi_label": label, "count": len(items),
            "total_amount": round(total_amount, 2),
            "avg_amount": round(total_amount / len(items), 2) if items else 0,
            "top_categories": top_cats,
            "addresses": list(set(it.get("address", "") for it in items if it.get("address"))),
        })

    clusters.sort(key=lambda x: x["count"], reverse=True)

    return {
        "clusters": clusters,
        "stats": {
            "total_with_location": sum(1 for t in transactions if t.get("lng") and t.get("aoi_label")),
            "total_without_location": sum(1 for t in transactions if t.get("lng") is None),
        },
    }
