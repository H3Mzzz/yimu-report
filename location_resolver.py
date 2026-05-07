#!/usr/bin/env python3
# -*- coding: utf-8 -*-
<<<<<<< HEAD
"""高德地图位置解析：地址 → 经纬度 → 区域标签 (AOI > 附近POI > KMeans)"""

import os, json, time, hashlib
from pathlib import Path
from collections import defaultdict
=======
"""
高德地图位置解析模块

职责：
  1. 地址文本 → 经纬度（地理编码 / 关键字搜索）
  2. 经纬度 → 区域标签（逆地理编码）
  3. 空间聚类（DBSCAN 简化版）
  4. 区域聚合摘要 + 文本格式化

不做 POI 精准匹配——小店地图上常没有。
输出「区域」级别洞见，而非具体店铺。
"""

import os
import re
import json
import time
import hashlib
import math
from pathlib import Path
from collections import defaultdict, Counter

>>>>>>> 9bf0a30 (html渲染)
import requests
AMAP_KEY = os.environ.get("AMAP_API_KEY", "")
CACHE_DIR = Path(__file__).parent / ".amap_cache"
CACHE_TTL = 30 * 24 * 3600

# ── 可配置：城市关键词映射（地址文本 → 高德城市名）──
try:
    _CITY_KW: dict[str, str] = json.loads(os.environ.get("CITY_KW_MAP", "{}"))
except (json.JSONDecodeError, TypeError):
    _CITY_KW = {}

# ── 可配置：默认搜索城市 ──
DEFAULT_CITY = os.environ.get("DEFAULT_GEOCODE_CITY", "蚌埠")

# ── AOI 类型标签映射（高德 type 码 → 展示用图标+中文）──
_AOI_TYPE_MAP = {
    "141201": "🏫 高等院校", "141200": "🏫 学校",
    "141100": "🏫 学校", "141400": "🏫 学校",
    "060100": "🛒 购物中心", "060400": "🛒 超市",
    "050000": "🍽️ 餐饮", "070000": "🍽️ 餐饮",
    "080000": "🏥 医疗", "100000": "🏨 住宿",
    "110000": "🏢 写字楼", "120000": "🏠 住宅区",
}

# ── 标签来源中文名 ──
_SOURCE_CN = {
    "aoi": "AOI", "business_area": "商圈", "street": "街巷",
    "township": "乡镇", "keyword_match": "地址提取",
}

# ── AOI 黑名单：这些类型的 AOI 不适合做消费地点标签 ──
_AOI_TYPE_BLACKLIST = frozenset({
    "商务住宅;住宅区", "住宅区", "别墅", "住宅小区",
    "商务住宅;楼宇", "产业园区",
})


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

<<<<<<< HEAD
def geocode(address: str, city: str = "") -> tuple[float, float] | None:
    if not address or not AMAP_KEY:
        return None

    ck = f"gc:{address}"
    c = _load(ck)
    if c:
        return None if c.get("_nf") else (c["c"][0], c["c"][1])
=======
def _extract_poi_coords(data: dict) -> tuple[float, float] | None:
    """从高德 POI/geocode 响应中提取首个坐标"""
    if data.get("status") == "1":
        if data.get("pois"):
            lng, lat = data["pois"][0]["location"].split(",")
            return float(lng), float(lat)
        if data.get("geocodes"):
            loc = data["geocodes"][0]["location"]
            lng, lat = loc.split(",")
            return float(lng), float(lat)
    return None


def _geocode_attempt(address: str, city: str) -> tuple[float, float] | None:
    """单次 geocode 尝试，返回 (lng, lat) 或 None"""

    # 策略0：文本搜索（高德 text API 容错高，citylimit 防跨城匹配）
    data = _safe_get(AMAP_TEXT_URL, {
        "key": AMAP_KEY, "keywords": address,
        "city": city, "citylimit": "true", "offset": 3,
    })
    coords = _extract_poi_coords(data)

    # 策略1：拆解「品牌(分店)名称」格式
    if not coords:
        m = re.match(r"^(.+?)\((.+?)\)(.*)$", address)
        if m:
            brand, area, rest = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            # brand + area
            data = _safe_get(AMAP_TEXT_URL, {
                "key": AMAP_KEY, "keywords": f"{brand} {area}",
                "city": city, "citylimit": "true", "offset": 3,
            })
            coords = _extract_poi_coords(data)
            # brand + rest（括号后可能是"安财东校区"等）
            if not coords and rest:
                data = _safe_get(AMAP_TEXT_URL, {
                    "key": AMAP_KEY, "keywords": f"{brand} {rest}",
                    "city": city, "citylimit": "true", "offset": 3,
                })
                coords = _extract_poi_coords(data)

    # 策略2：地理编码（适合结构化地址）
    if not coords:
        data = _safe_get(AMAP_GEO_URL, {
            "key": AMAP_KEY, "address": address, "city": city,
        })
        coords = _extract_poi_coords(data)

    return coords


def _extract_city_from_address(address: str) -> str | None:
    """从地址文本中提取城市名"""
    for kw, city in sorted(_CITY_KW.items(), key=lambda x: -len(x[0])):
        if kw in address:
            return city
    return None


def geocode(address: str, city: str = None) -> tuple[float, float] | None:
    """
    地址文本 → (lng, lat) 经纬度。

    策略：
    1. 从地址提取城市关键词
    2. 缓存命中直接返回
    3. 指定城市关键字搜索 → 地址提取城市搜索 → 全国兜底
    """
    if not address or not AMAP_KEY:
        return None

    if city is None:
        city = DEFAULT_CITY

    # 优先从地址中提取城市，防止跨城错位（如淮南地址搜到蚌埠同名店铺）
    detected_city = _extract_city_from_address(address)
    primary_city = detected_city or city
>>>>>>> 9bf0a30 (html渲染)

    data = _api("https://restapi.amap.com/v3/place/text", {
        "key": AMAP_KEY, "keywords": address, "city": city,
        "offset": 1, "page": 1, "extensions": "base",
    })

<<<<<<< HEAD
    coords = None
    if data.get("status") == "1" and data.get("pois"):
        lng_str, lat_str = data["pois"][0]["location"].split(",")
        coords = (float(lng_str), float(lat_str))
=======
    coords = _geocode_attempt(address, primary_city)

    # 提取到的城市失败 → 试默认城市
    if not coords and detected_city and detected_city != city:
        coords = _geocode_attempt(address, city)

    # 全国范围兜底
    if not coords:
        coords = _geocode_attempt(address, "")

    # 失败结果也缓存，避免重复消耗配额
    if coords:
        _cache_set(cache_key, {"lng": coords[0], "lat": coords[1]})
    else:
        _cache_set(cache_key, {"lng": None, "lat": None, "_not_found": True})
>>>>>>> 9bf0a30 (html渲染)

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

<<<<<<< HEAD
    data = _api("https://restapi.amap.com/v3/geocode/regeo", {
        "key": AMAP_KEY, "location": f"{lng:.6f},{lat:.6f}",
        "extensions": "all",
=======
    data = _safe_get(AMAP_REGEO_URL, {
        "key": AMAP_KEY,
        "location": f"{lng:.6f},{lat:.6f}",
        "extensions": "all",
        "radius": 300,
>>>>>>> 9bf0a30 (html渲染)
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
<<<<<<< HEAD
            "aois": [a.get("name", "") for a in rg.get("aois", [])],
            "pois": [p.get("name", "") for p in rg.get("pois", [])],
=======
            "formatted_address": regeo.get("formatted_address", ""),
            "aois": [{"name": aoi.get("name", ""), "type": aoi.get("type", "")}
                     for aoi in regeo.get("aois", [])],
            "business_areas": [ba.get("name", "") for ba in regeo.get("businessAreas", [])],
            "street_number": regeo.get("streetNumber", {}).get("street", "") +
                              (regeo.get("streetNumber", {}).get("number", "") or ""),
>>>>>>> 9bf0a30 (html渲染)
        }
    _save(ck, {"a": r})
    return r


# ── 聚类标签（AOI > 附近POI > KMeans等待） ──

<<<<<<< HEAD
def _try_aoi_poi(region: dict) -> str | None:
    """尝试 AOI 或附近 POI，成功返回标签，失败返回 None"""
    aois = region.get("aois", [])
    if aois:
        return aois[0]
    pois = region.get("pois", [])
    if pois:
        return pois[0]
=======
def _haversine(lng1, lat1, lng2, lat2):
    """两坐标间距离（米）"""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _extract_address_keyword(addresses: list[str]) -> str | None:
    """从地址集合中提取公共地点关键词（兜底标签）"""
    if len(addresses) < 2:
        return None

    parts = []
    for addr in addresses:
        m = re.match(r'^(.+?)\((.+?)\)(.*)$', addr)
        if m:
            rest = (m.group(2) + m.group(3)).strip()
            parts.append(rest if rest else addr)
        else:
            parts.append(addr)

    counter = Counter(parts)
    qualified = [(w, c) for w, c in counter.items() if c >= max(2, len(addresses) * 0.5)]
    if not qualified:
        return None
    return max(qualified, key=lambda x: (x[1], len(x[0])))[0]


def _match_known_location(addresses: list[str]) -> str | None:
    """检查地址集合是否匹配 HARDCODED_COORDS 中的已知地点"""
    if not _HARDCODED_COORDS:
        return None
    for key in sorted(_HARDCODED_COORDS.keys(), key=lambda k: -len(k)):
        match_count = sum(1 for a in addresses if key in a)
        if match_count >= max(2, len(addresses) * 0.5):
            return key
>>>>>>> 9bf0a30 (html渲染)
    return None


def _dbscan_cluster(points: list[tuple[float, float]],
                    eps: float = 0.003, min_samples: int = 2
                    ) -> tuple[list[int], dict[int, tuple[float, float]]]:
    """DBSCAN 聚类 (r≈300m, ≥2点成簇) → (标签列表, {簇编号: 簇中心})。噪声点=-1"""
    import numpy as np
    from sklearn.cluster import DBSCAN

<<<<<<< HEAD
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
=======
    优先级：AOI（非住宅） → 商圈 → 道路+门牌 → 乡镇
    住宅区/写字楼类型 AOI 自动降级——避免「火锅店→同乐园小区」错标。
    """
    aois = region.get("aois", [])
    if aois:
        for aoi in aois:
            name = aoi.get("name", aoi) if isinstance(aoi, dict) else aoi
            aoi_type = aoi.get("type", "") if isinstance(aoi, dict) else ""
            if aoi_type not in _AOI_TYPE_BLACKLIST:
                return name

    bas = region.get("business_areas", [])
    if bas:
        return bas[0]

    street = region.get("street_number", "").strip()
    if street:
        return street

    township = region.get("township", "").strip()
    if township:
        return township

    return region.get("district", "") or region.get("city", "") or "未知区域"


def _simple_dbscan(points: list[dict], eps_meters: float = 200, min_samples: int = 3) -> tuple[list[dict], list[dict]]:
    """简版 DBSCAN 空间聚类，返回 (clusters, noise)"""
    n = len(points)
    if n == 0:
        return [], []

    def _neighbors(i):
        return {j for j in range(n) if _haversine(
            points[i]["lng"], points[i]["lat"], points[j]["lng"], points[j]["lat"]) <= eps_meters}

    UNVISITED, NOISE = -1, -2
    labels = [UNVISITED] * n
    cluster_id = 0
    for i in range(n):
        if labels[i] != UNVISITED:
>>>>>>> 9bf0a30 (html渲染)
            continue
        mask = np.array(labels) == lid
        c = arr[mask].mean(axis=0)
        centers[lid] = (round(c[0], 3), round(c[1], 3))

<<<<<<< HEAD
    return labels, centers


# ── 手动坐标 ──

=======
    groups = defaultdict(list)
    noise_pts = []
    for i, lbl in enumerate(labels):
        (noise_pts if lbl == NOISE else groups[lbl]).append(points[i])

    clusters = [_build_cluster_result(groups[cid], cid, "clustered") for cid in sorted(groups)]
    noise_results = [_build_cluster_result([pt], -1, "noise_single") for pt in noise_pts]

    clusters.sort(key=lambda x: x["count"], reverse=True)
    return clusters, noise_results


def _build_cluster_result(pts: list[dict], cid: int, label_source: str) -> dict:
    """构建单个簇/孤立点的结构化结果"""

    # 中位数滤波：分别按 lng/lat 排序取中位数（保持点配对不破坏）
    sorted_by_lng = sorted(pts, key=lambda p: p["lng"])
    sorted_by_lat = sorted(pts, key=lambda p: p["lat"])
    med_lng = sorted_by_lng[len(pts) // 2]["lng"]
    med_lat = sorted_by_lat[len(pts) // 2]["lat"]
    dists = [_haversine(p["lng"], p["lat"], med_lng, med_lat) for p in pts]
    mean_d = sum(dists) / len(dists)
    std_d = (sum((d - mean_d) ** 2 for d in dists) / len(dists)) ** 0.5 if len(dists) > 1 else 0
    threshold = mean_d + 2 * std_d if std_d > 0 else 999999

    filtered = [(p["lng"], p["lat"]) for i, p in enumerate(pts) if dists[i] <= threshold]
    if not filtered:
        filtered = [(p["lng"], p["lat"]) for p in pts]
    avg_lng = sum(p[0] for p in filtered) / len(filtered)
    avg_lat = sum(p[1] for p in filtered) / len(filtered)

    # 获取区域信息
    if cid >= 0:
        region = regeocode(avg_lng, avg_lat)
    elif pts[0].get("formatted_address"):
        region = {
            "formatted_address": pts[0].get("formatted_address", ""),
            "aois": pts[0].get("aois", []),
            "township": pts[0].get("township", ""),
        }
    else:
        region = regeocode(pts[0]["lng"], pts[0]["lat"])

    aoi_label, actual_source = _resolve_aoi_label_and_source(region, pts, label_source)
    first_aoi = region.get("aois", [None])[0] if region.get("aois") else None
    aoi_type = first_aoi.get("type", "") if isinstance(first_aoi, dict) else ""

    total_amount = sum(abs(p.get("amount", 0)) for p in pts)
    categories = defaultdict(float)
    for p in pts:
        categories[p.get("category", "未知")] += abs(p.get("amount", 0))

    return {
        "cluster_id": cid,
        "center_lng": round(avg_lng, 6), "center_lat": round(avg_lat, 6),
        "count": len(pts), "points": pts,
        "aoi_label": aoi_label, "label_source": actual_source, "aoi_type": aoi_type,
        "township": region.get("township", ""), "district": region.get("district", ""),
        "city": region.get("city", ""),
        "total_amount": round(total_amount, 2),
        "avg_amount": round(total_amount / len(pts), 2),
        "top_categories": dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]),
    }


def _resolve_aoi_label_and_source(region: dict, pts: list[dict], fallback_source: str) -> tuple[str, str]:
    """四级降级提取 AOI 标签 + 来源标识"""
    aoi_label = _extract_aoi_label(region)

    if region.get("aois"):
        source = "aoi"
    elif region.get("business_areas"):
        source = "business_area"
    elif region.get("street_number", "").strip():
        source = "street"
    else:
        source = "township"

    # 降级到 township 时尝试关键词提取兜底
    if source == "township":
        addrs = [p.get("address", "") for p in pts]
        alt = _match_known_location(addrs) or _extract_address_keyword(addrs)
        if alt:
            aoi_label, source = alt, "keyword_match"
    return aoi_label, source


# ═══════════════════════════════════════════════════════════
# 批量处理：交易列表 → 附加经纬度 + 区域标签
# ═══════════════════════════════════════════════════════════

# 手动坐标映射：高德不收录的地点通过环境变量注入
# 格式：JSON 字符串，{"点名": [lng, lat], ...}
>>>>>>> 9bf0a30 (html渲染)
try:
    _MANUAL: dict[str, tuple[float, float]] = {
        k: (v[0], v[1]) for k, v in
        json.loads(os.environ.get("HARDCODED_LOCATIONS", "{}")).items()
    }
except Exception:
    _MANUAL = {}


<<<<<<< HEAD
# ── 批量处理 ──

def enrich_transactions(transactions: list[dict], city: str = "",
                        dbscan_eps: float = 0.003, dbscan_min_samples: int = 2) -> list[dict]:
    """为每笔交易附加: lng, lat, aoi_label 及区域信息
    
    第一阶段：geocode + regeocode，AOI/POI 标签
    第二阶段：剩余未标记点 → DBSCAN 聚类
    """
    result = []
    dbscan_queue: list[tuple[int, float, float]] = []
=======
def enrich_transactions(transactions: list[dict], city: str = None) -> list[dict]:
    """
    为每笔交易附加 location 信息（纯函数，不修改输入）。

    输入 list[dict]，每项需含 address。
    返回新 list[dict]，附加字段: lng, lat, district, township, formatted_address, aois。
    """
    if city is None:
        city = DEFAULT_CITY

    result = []
    for t in transactions:
        enriched = dict(t)
        addr = enriched.get("address", "") or ""
        enriched["lng"], enriched["lat"], enriched["district"], enriched["township"] = None, None, "", ""
        enriched["formatted_address"], enriched["aois"] = "", []
>>>>>>> 9bf0a30 (html渲染)

    for idx, t in enumerate(transactions):
        addr = (t.get("address", "") or "").strip()
        out = dict(t, lng=None, lat=None, aoi_label="", district="",
                   township="", formatted_address="", aois=[], pois=[])
        if not addr:
<<<<<<< HEAD
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
=======
            result.append(enriched)
            continue

        # 速率限制：高德免费 API 并发限制严格
        time.sleep(0.05)

        addr_clean = addr.strip()
        coords = _HARDCODED_COORDS.get(addr_clean)

        # 带子品牌的已知地点：「北苑食堂蜜雪冰城」→ 拆出子品牌搜索
        if not coords and _HARDCODED_COORDS:
            for campus_key, campus_tup in _HARDCODED_COORDS.items():
                if addr_clean.startswith(campus_key) and len(addr_clean) > len(campus_key):
                    rest = addr_clean[len(campus_key):].strip()
                    coords = geocode(rest, city)
                    if coords:
                        break
                    coords = campus_tup
                    break

        if not coords:
            coords = geocode(addr, city)
        if not coords:
            result.append(enriched)
            continue

        enriched["lng"], enriched["lat"] = coords
>>>>>>> 9bf0a30 (html渲染)

        out["lng"] = coords[0]
        out["lat"] = coords[1]
        region = regeocode(*coords)
<<<<<<< HEAD

        label = _try_aoi_poi(region)
        if label:
            out["aoi_label"] = label
        else:
            dbscan_queue.append((len(result), *coords))
=======
        enriched["district"] = region.get("district", "")
        enriched["township"] = region.get("township", "")
        enriched["formatted_address"] = region.get("formatted_address", "")
        enriched["aois"] = region.get("aois", [])

        result.append(enriched)

    return result
>>>>>>> 9bf0a30 (html渲染)

        out.update(district=region.get("district", ""),
                   township=region.get("township", ""),
                   formatted_address=region.get("formatted_address", ""),
                   aois=region.get("aois", []),
                   pois=region.get("pois", []))
        result.append(out)

<<<<<<< HEAD
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
=======
# ═══════════════════════════════════════════════════════════
# 区域级聚合摘要
# ═══════════════════════════════════════════════════════════

def area_summary(transactions: list[dict], eps_meters: float = 300, min_samples: int = 3) -> dict:
    """
    从已 enrich 的交易中生成区域聚合摘要。

    返回:
    {
        "clusters": [...],
        "noise": [...],
        "by_district": {...},
        "stats": {...}
    }
    """
    with_loc = [t for t in transactions if t.get("lng") is not None]
    without_loc = len(transactions) - len(with_loc)

    result = {
        "clusters": [],
        "noise": [],
        "by_district": defaultdict(lambda: {"金额": 0, "笔数": 0}),
        "stats": {
            "total_with_location": len(with_loc),
            "total_without_location": without_loc,
            "cluster_count": 0,
            "noise_count": 0,
        },
    }

    if not with_loc:
        return result

    for t in with_loc:
        district = t.get("district", "其他")
        result["by_district"][district]["金额"] += abs(t.get("amount", 0))
        result["by_district"][district]["笔数"] += 1

    points = [{"lng": t["lng"], "lat": t["lat"], "amount": abs(t.get("amount", 0)),
                "category": t.get("category", ""), "address": t.get("address", ""),
                "resolved_place": t.get("resolved_place", ""),
                "formatted_address": t.get("formatted_address", ""),
                "aois": t.get("aois", []),
                "township": t.get("township", "")}
              for t in with_loc]

    clusters, noise = _simple_dbscan(points, eps_meters=eps_meters, min_samples=min_samples)

    result["clusters"] = clusters
    result["noise"] = noise
    result["stats"]["cluster_count"] = len(clusters)
    result["stats"]["noise_count"] = len(noise)
    result["by_district"] = dict(result["by_district"])
>>>>>>> 9bf0a30 (html渲染)

    return result


<<<<<<< HEAD
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
=======
# ═══════════════════════════════════════════════════════════
# 文本格式化（供 AI prompt 使用）
# ═══════════════════════════════════════════════════════════

def format_clusters(area: dict) -> list[str]:
    """将空间聚类结果格式化为文本行列表"""
    lines = []
    if not area.get("clusters"):
        return lines
    cluster_total = sum(c["total_amount"] for c in area["clusters"])
    lines.append("🗺️ 高频活动区域（空间聚类，半径300m，AOI标签）")
    for c in area["clusters"][:8]:
        label = c.get("aoi_label", "未知区域")
        source = _SOURCE_CN.get(c.get("label_source", "?"), c.get("label_source", "?"))
        pct = c["total_amount"] / cluster_total * 100 if cluster_total > 0 else 0
        top_cats = ", ".join(f"{k} ¥{v:.0f}" for k, v in list(c.get("top_categories", {}).items())[:3])
        lines.append(
            f"- {label}（{source}）：{c['count']}笔 / ¥{c['total_amount']:,.2f}"
            f"（占聚类总额 {pct:.0f}%）| 均值 ¥{c['avg_amount']:.2f}"
            f" | 主要: {top_cats}"
        )
    return lines


def format_noise(area: dict) -> list[str]:
    """将孤立散点格式化为文本行列表"""
    lines = []
    noise = area.get("noise", [])
    if not noise:
        return lines
    noise_sum = sum(n["total_amount"] for n in noise)
    lines.append(f"📍 孤立散点（{len(noise)} 笔，合计 ¥{noise_sum:,.2f}，半径300m内未形成聚簇）")
    for n in sorted(noise, key=lambda x: x["total_amount"], reverse=True):
        p = n["points"][0]
        addr = p.get("address", "")[:50] or n.get("aoi_label", "?")
        cat = list(n.get("top_categories", {}).keys())[0] if n.get("top_categories") else "?"
        lines.append(f"  - {n['aoi_label']} | {cat} | ¥{n['total_amount']:,.2f}（{addr}）")
    return lines
>>>>>>> 9bf0a30 (html渲染)
