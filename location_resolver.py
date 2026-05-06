#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高德地图位置解析模块（粗粒度版本）

不做 POI 精准匹配——小店地图上常没有，强行匹配毫无意义。
只做两件事：
  1. 地址文本 → 经纬度（地理编码 / 关键字搜索）
  2. 经纬度 → 空间聚类（按距离分组，自动发现高频活动区域）

输出的是「区域」级别洞见，而非具体店铺。
"""

import os
import re
import json
import time
import hashlib
import math
from pathlib import Path
from collections import defaultdict

import requests

AMAP_KEY = os.environ.get("AMAP_API_KEY", "")
AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
AMAP_TEXT_URL = "https://restapi.amap.com/v3/place/text"

CACHE_DIR = Path(__file__).parent / ".amap_cache"
CACHE_TTL = 30 * 24 * 3600  # 缓存 30 天


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / f"geo_{h}.json"


def _cache_get(key: str) -> dict | None:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text("utf-8"))
        if time.time() - data.get("_ts", 0) > CACHE_TTL:
            return None
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def _cache_set(key: str, data: dict):
    data["_ts"] = time.time()
    _cache_path(key).write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _safe_get(url: str, params: dict, timeout: int = 10) -> dict:
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == 1:
                print(f"[高德API] 请求失败: {e}")
                return {"status": "0", "info": str(e)}
            time.sleep(1)
    return {"status": "0"}


# ═══════════════════════════════════════════════════════════
# 地址 → 经纬度
# ═══════════════════════════════════════════════════════════

def _geocode_attempt(address: str, city: str) -> tuple[float, float] | None:
    """单次 geocode 尝试，返回 (lng, lat) 或 None（不处理缓存）"""
    coords = None

    # 策略0：直接用原始地址做文本搜索（兜底能力最强，高德 text API 容错高）
    # citylimit=true 防止跨城匹配（如淮南地址搜到蚌埠同名店铺）
    data = _safe_get(AMAP_TEXT_URL, {
        "key": AMAP_KEY, "keywords": address,
        "city": city, "citylimit": "true", "offset": 3,
    })
    if data.get("status") == "1" and data.get("pois"):
        loc = data["pois"][0]["location"]
        lng, lat = loc.split(",")
        coords = (float(lng), float(lat))

    # 策略1：拆解「品牌(分店)名称」格式，分别搜品牌+区域
    if not coords:
        m = re.match(r"^(.+?)\((.+?)\)(.*)$", address)
        if m:
            brand = m.group(1).strip()
            area = m.group(2).strip()
            rest = m.group(3).strip()
            # 尝试 brand + area 组合
            data = _safe_get(AMAP_TEXT_URL, {
                "key": AMAP_KEY, "keywords": f"{brand} {area}",
                "city": city, "citylimit": "true", "offset": 3,
            })
            if data.get("status") == "1" and data.get("pois"):
                loc = data["pois"][0]["location"]
                lng, lat = loc.split(",")
                coords = (float(lng), float(lat))
            # brand + area 没命中，试 brand + rest（括号后可能是"安财东校区"这类）
            if not coords and rest:
                data = _safe_get(AMAP_TEXT_URL, {
                    "key": AMAP_KEY, "keywords": f"{brand} {rest}",
                    "city": city, "citylimit": "true", "offset": 3,
                })
                if data.get("status") == "1" and data.get("pois"):
                    loc = data["pois"][0]["location"]
                    lng, lat = loc.split(",")
                    coords = (float(lng), float(lat))

    # 策略2：地理编码（仅对看起来像地址的文本有效，纯店名跳过）
    if not coords:
        data = _safe_get(AMAP_GEO_URL, {
            "key": AMAP_KEY, "address": address, "city": city,
        })
        if data.get("status") == "1" and data.get("geocodes"):
            loc = data["geocodes"][0]["location"]
            lng, lat = loc.split(",")
            coords = (float(lng), float(lat))

    return coords


# 地址关键词 → 高德城市名映射（含县区→地级市回退）
_CITY_KW: dict[str, str] = {
    "淮南": "淮南", "合肥": "合肥", "阜阳": "阜阳", "宿州": "宿州",
    "滁州": "滁州", "芜湖": "芜湖", "马鞍山": "马鞍山", "安庆": "安庆",
    "凤阳": "滁州", "寿县": "淮南", "怀远": "蚌埠", "固镇": "蚌埠",
    "五河": "蚌埠", "凤台": "淮南", "定远": "滁州", "明光": "滁州",
}


def _extract_city_from_address(address: str) -> str | None:
    """从地址文本中提取城市名（优先匹配，用于 geocode 首轮尝试）"""
    for kw, city in sorted(_CITY_KW.items(), key=lambda x: -len(x[0])):
        if kw in address:
            return city
    return None


def geocode(address: str, city: str = "蚌埠") -> tuple[float, float] | None:
    """
    地址文本 → (lng, lat) 经纬度。

    策略：
    1. 从地址提取城市关键词，优先用提取到的城市
    2. 缓存命中直接返回
    3. 关键字搜索（citylimit=true，防跨城错位）
    4. 地理编码兜底
    5. 全国范围兜底
    """
    if not address or not AMAP_KEY:
        return None

    # P0修复：先从地址提取城市，避免默认蚌埠搜淮南地址
    detected_city = _extract_city_from_address(address)
    primary_city = detected_city or city

    cache_key = f"geocode:{address}:{primary_city}"
    cached = _cache_get(cache_key)
    if cached:
        if cached.get("_not_found"):
            return None
        return cached.get("lng"), cached.get("lat")

    coords = _geocode_attempt(address, primary_city)

    # 如果提取到的城市失败，试试默认城市
    if not coords and detected_city and detected_city != city:
        coords = _geocode_attempt(address, city)

    # 还不行就全国范围兜底
    if not coords:
        coords = _geocode_attempt(address, "")

    # P0修复：失败结果也缓存（标记为未找到），避免重复消耗配额
    if coords:
        _cache_set(cache_key, {"lng": coords[0], "lat": coords[1]})
    else:
        _cache_set(cache_key, {"lng": None, "lat": None, "_not_found": True})

    return coords


# ═══════════════════════════════════════════════════════════
# 逆地理编码：经纬度 → 区域名
# ═══════════════════════════════════════════════════════════

def regeocode(lng: float, lat: float) -> dict:
    """
    经纬度 → 完整逆地理信息。
    返回: {province, city, district, township, formatted_address,
           aois, business_areas, street_number}
    """
    if not AMAP_KEY:
        return {}

    cache_key = f"regeo:{lng:.6f},{lat:.6f}"
    cached = _cache_get(cache_key)
    if cached:
        return cached.get("address", {})

    data = _safe_get(AMAP_REGEO_URL, {
        "key": AMAP_KEY,
        "location": f"{lng:.6f},{lat:.6f}",
        "extensions": "all",  # 需要 aois / businessAreas / streetNumber
        "radius": 300,
    })
    result = {}
    if data.get("status") == "1":
        regeo = data.get("regeocode", {})
        comp = regeo.get("addressComponent", {})
        result = {
            "province": comp.get("province", ""),
            "city": comp.get("city", "") or comp.get("province", ""),
            "district": comp.get("district", ""),
            "township": comp.get("township", ""),
            "formatted_address": regeo.get("formatted_address", ""),
            # AOI 兴趣面（校园/园区/小区/商场）— 同时存 name 和 type 供下游分析
            "aois": [{"name": aoi.get("name", ""), "type": aoi.get("type", "")}
                     for aoi in regeo.get("aois", [])],
            # 商圈
            "business_areas": [ba.get("name", "") for ba in regeo.get("businessAreas", [])],
            # 道路+门牌号
            "street_number": regeo.get("streetNumber", {}).get("street", "") +
                              (regeo.get("streetNumber", {}).get("number", "") or ""),
        }

    _cache_set(cache_key, {"address": result})
    return result


# ═══════════════════════════════════════════════════════════
# 空间聚类 — DBSCAN 简化版
# ═══════════════════════════════════════════════════════════

def _haversine(lng1, lat1, lng2, lat2):
    """两坐标间距离（米）"""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# AOI 类型黑名单：这些类型的 AOI 不适用于消费地点标签
_AOI_TYPE_BLACKLIST = {
    "商务住宅;住宅区", "住宅区", "别墅", "住宅小区",
    "商务住宅;楼宇", "产业园区",
}


def _extract_address_keyword(addresses: list[str]) -> str | None:
    """
    从地址集合中提取公共地点关键词（兜底 township 标签）。

    策略：
    1. 品牌(分店)格式 → 提取「分店+剩余」作为候选地点
    2. 统计出现频率 ≥ 50% 的候选
    3. 取最长者（信息量最大）
    """
    if len(addresses) < 2:
        return None

    from collections import Counter
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
    # 优先选出现次数多 + 字符串长的（信息量最大）
    return max(qualified, key=lambda x: (x[1], len(x[0])))[0]


def _match_known_location(addresses: list[str]) -> str | None:
    """检查地址集合是否匹配 HARDCODED_COORDS 中的已知地点"""
    if not _HARDCODED_COORDS:
        return None
    for key in sorted(_HARDCODED_COORDS.keys(), key=lambda k: -len(k)):
        match_count = sum(1 for a in addresses if key in a)
        if match_count >= max(2, len(addresses) * 0.5):
            return key
    return None


def _extract_aoi_label(region: dict) -> str:
    """
    四级降级提取 AOI 标签，含类型过滤。

    优先级：
    1. AOI 兴趣面（非住宅类型） → "安徽财经大学(东校区)"
    2. BusinessArea 商圈        → "大学城商圈"
    3. 道路+门牌号               → "朝阳中路40号"
    4. 乡镇街道                  → "东升街道"

    关键：住宅区/写字楼类型的 AOI 不适用于消费聚类标签，
    自动降级到商圈或街巷——避免「火锅店→同乐园小区」的错标。
    """
    # P1: AOI（兼容新旧缓存格式；过滤非消费场景类型）
    aois = region.get("aois", [])
    if aois:
        for aoi in aois:
            name = aoi.get("name", aoi) if isinstance(aoi, dict) else aoi
            aoi_type = aoi.get("type", "") if isinstance(aoi, dict) else ""
            if aoi_type not in _AOI_TYPE_BLACKLIST:
                return name  # 第一个非黑名单 AOI 直接采用

    # P2: 商圈
    bas = region.get("business_areas", [])
    if bas:
        return bas[0]

    # P3: 道路+门牌号
    street = region.get("street_number", "").strip()
    if street:
        return street

    # P4: 乡镇街道
    township = region.get("township", "").strip()
    if township:
        return township

    # 兜底：区级
    return region.get("district", "") or region.get("city", "") or "未知区域"


def _simple_dbscan(points: list[dict], eps_meters: float = 200, min_samples: int = 3) -> list[dict]:
    """
    简版 DBSCAN 空间聚类。

    points: [{lng, lat, amount, category, address, ...}]
    eps_meters: 聚类半径
    min_samples: 最小样本数

    每个簇调用 1 次逆地理 API（extensions=all），
    按 AOI → 商圈 → 街巷 → 乡镇 四级降级提取标签。

    返回值字段:
    - aoi_label: 四级降级提取的标签（需求文档核心字段）
    - label_source: 标签来源 (aoi/business_area/street/township)
    - township: 用于行政区划兜底展示
    - noise_points: 孤立点列表（cluster_id=-1 的散点）
    """
    n = len(points)
    if n == 0:
        return []

    # 距离矩阵
    dist = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = _haversine(
                points[i]["lng"], points[i]["lat"],
                points[j]["lng"], points[j]["lat"],
            )
            dist[i][j] = d
            dist[j][i] = d

    # DBSCAN
    UNVISITED = -1
    NOISE = -2
    labels = [UNVISITED] * n
    cluster_id = 0

    for i in range(n):
        if labels[i] != UNVISITED:
            continue

        neighbors = [j for j in range(n) if dist[i][j] <= eps_meters]
        if len(neighbors) < min_samples:
            labels[i] = NOISE
            continue

        labels[i] = cluster_id
        seed_set = set(neighbors) - {i}

        while seed_set:
            q = seed_set.pop()
            if labels[q] == NOISE:
                labels[q] = cluster_id
            if labels[q] != UNVISITED:
                continue
            labels[q] = cluster_id
            q_neighbors = [j for j in range(n) if dist[q][j] <= eps_meters]
            if len(q_neighbors) >= min_samples:
                seed_set.update(q_neighbors)

        cluster_id += 1

    # 整理结果
    clusters = defaultdict(list)
    noise_points = []
    for i, label in enumerate(labels):
        if label == NOISE:
            noise_points.append(points[i])
        else:
            clusters[label].append(points[i])

    results = []
    noise_results = []

    for cid, pts in clusters.items():
        # 中心点：中位数过滤偏离点后求均值（抵御 GPS 漂移拉偏）
        lngs = sorted(p["lng"] for p in pts)
        lats = sorted(p["lat"] for p in pts)
        med_lng, med_lat = lngs[len(lngs) // 2], lats[len(lats) // 2]
        def _med_dist(lng, lat):
            return _haversine(lng, lat, med_lng, med_lat)
        # 剔除距离中位数超过 2σ 的异常点
        dists = [_med_dist(lngs[i], lats[i]) for i in range(len(pts))]
        mean_d = sum(dists) / len(dists)
        std_d = (sum((d - mean_d) ** 2 for d in dists) / len(dists)) ** 0.5
        threshold = mean_d + 2 * std_d if std_d > 0 else 999999
        filtered = [(lngs[i], lats[i]) for i in range(len(pts)) if dists[i] <= threshold]
        if not filtered:  # 极端情况：全被剔了，回退到原始点
            filtered = [(lngs[i], lats[i]) for i in range(len(pts))]
        avg_lng = sum(p[0] for p in filtered) / len(filtered)
        avg_lat = sum(p[1] for p in filtered) / len(filtered)

        # 1 次 API 调用拿逆地理详情
        region = regeocode(avg_lng, avg_lat)

        # 四级降级提取 AOI 标签
        aoi_label = _extract_aoi_label(region)
        label_source = "aoi"
        aoi_type = ""  # 高德 AOI 类型码，如 "141201"=高等教育院校
        if region.get("aois"):
            label_source = "aoi"
            first_aoi = region["aois"][0]
            if isinstance(first_aoi, dict):
                aoi_type = first_aoi.get("type", "")
        elif region.get("business_areas"):
            label_source = "business_area"
        elif region.get("street_number", "").strip():
            label_source = "street"
        else:
            label_source = "township"

        # 兜底：逆地理降级到 township 时，从地址文本提取关键词覆盖
        #  ① HARDCODED_LOCATIONS 已知地点匹配
        #  ② 地址公共子串提取（品牌(分店) → 分店名）
        if label_source == "township":
            addrs = [p.get("address", "") for p in pts]
            alt_label = _match_known_location(addrs) or _extract_address_keyword(addrs)
            if alt_label:
                aoi_label = alt_label
                label_source = "keyword_match"

        # 统计
        total_amount = sum(abs(p.get("amount", 0)) for p in pts)
        categories = defaultdict(float)
        for p in pts:
            categories[p.get("category", "未知")] += abs(p.get("amount", 0))

        results.append({
            "cluster_id": cid,
            "center_lng": round(avg_lng, 6),
            "center_lat": round(avg_lat, 6),
            "count": len(pts),
            "points": pts,
            "aoi_label": aoi_label,
            "label_source": label_source,
            "aoi_type": aoi_type,
            "township": region.get("township", ""),
            "district": region.get("district", ""),
            "city": region.get("city", ""),
            "total_amount": round(total_amount, 2),
            "avg_amount": round(total_amount / len(pts), 2),
            "top_categories": dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]),
        })

    # 孤立点：有 formatted_address / aois 则直接复用，不调 API
    for pt in noise_points:
        if pt.get("formatted_address"):
            # 复用 enrich 阶段已有的逆地理信息，跳过 API
            region = {
                "formatted_address": pt.get("formatted_address", ""),
                "aois": pt.get("aois", []),
                "township": pt.get("township", ""),
            }
        else:
            region = regeocode(pt["lng"], pt["lat"])
        noise_results.append({
            "cluster_id": -1,
            "center_lng": pt["lng"],
            "center_lat": pt["lat"],
            "count": 1,
            "points": [pt],
            "aoi_label": _extract_aoi_label(region),
            "label_source": "noise_single",
            "township": region.get("township", ""),
            "total_amount": abs(pt.get("amount", 0)),
            "avg_amount": abs(pt.get("amount", 0)),
            "top_categories": {pt.get("category", "未知"): abs(pt.get("amount", 0))},
        })

    results.sort(key=lambda x: x["count"], reverse=True)
    return results, noise_results


# ═══════════════════════════════════════════════════════════
# 批量处理：交易列表 → 附加经纬度 + 区域标签
# ═══════════════════════════════════════════════════════════

# 手动坐标映射表：高德不收录的地点（如校内建筑）可通过环境变量注入
# 格式：JSON 字符串，{"点名": [lng, lat], ...}
# 示例：export HARDCODED_LOCATIONS='{"北苑食堂":[117.4256,32.9081],"南苑食堂":[117.4272,32.9052]}'
try:
    _HARDCODED_COORDS: dict[str, tuple[float, float]] = {
        k: (v[0], v[1])
        for k, v in json.loads(os.environ.get("HARDCODED_LOCATIONS", "{}")).items()
    }
except (json.JSONDecodeError, TypeError, KeyError):
    print("[位置解析] HARDCODED_LOCATIONS 格式无效，已忽略")
    _HARDCODED_COORDS = {}


def enrich_transactions(transactions: list[dict], city: str = "蚌埠") -> list[dict]:
    """
    为每笔交易附加 location 信息。
    输入 list[dict]，每项需含 address
    附加字段: lng, lat, district, township
    """
    for t in transactions:
        addr = t.get("address", "") or ""
        t["lng"], t["lat"], t["district"], t["township"] = None, None, "", ""

        if not addr:
            continue

        # 速率限制：高德免费 API 并发限制严格，单线程 QPS 上限约 20
        time.sleep(0.05)

        # 手动映射：环境变量注入的高德不收录地点
        addr_clean = addr.strip()
        coords = _HARDCODED_COORDS.get(addr_clean)

        # 带子品牌的已知地点：「北苑食堂蜜雪冰城」→ 拆出子品牌搜索
        if not coords and _HARDCODED_COORDS:
            for campus_key, campus_tup in _HARDCODED_COORDS.items():
                if addr_clean.startswith(campus_key) and len(addr_clean) > len(campus_key):
                    # 剩余部分可能是品牌名，尝试搜
                    rest = addr_clean[len(campus_key):].strip()
                    coords = geocode(rest, city)
                    if coords:
                        break
                    # 搜不到就用校园坐标
                    coords = campus_tup
                    break

        if not coords:
            coords = geocode(addr, city)
        if not coords:
            continue

        t["lng"], t["lat"] = coords

        region = regeocode(*coords)
        t["district"] = region.get("district", "")
        t["township"] = region.get("township", "")
        t["formatted_address"] = region.get("formatted_address", "")
        t["aois"] = region.get("aois", [])

    return transactions


# ═══════════════════════════════════════════════════════════
# 区域级聚合摘要
# ═══════════════════════════════════════════════════════════

def area_summary(transactions: list[dict], eps_meters: float = 300, min_samples: int = 3) -> dict:
    """
    从已 enrich 的交易中生成区域聚合摘要。

    返回:
    {
        "clusters": [...],           # 空间聚类结果（含 aoi_label 四级降级标签）
        "noise": [...],              # 孤立点（每点单独逆地理）
        "by_district": {...},        # 按行政区划
        "stats": {                   # 总体统计
            "total_with_location": N,
            "total_without_location": N,
            "cluster_count": N,
            "noise_count": N,
        }
    }
    """
    # 筛选有坐标的交易
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

    # 按行政区划聚合
    for t in with_loc:
        district = t.get("district", "其他")
        result["by_district"][district]["金额"] += abs(t.get("amount", 0))
        result["by_district"][district]["笔数"] += 1

    # 空间聚类
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

    return result


# ═══════════════════════════════════════════════════════════
# CLI 测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_addrs = [
        "古茗(安徽财经大学店)安徽财经大学东校区",
        "库迪咖啡(安徽财经大学东校区店)安徽财经大学东校区",
        "蜜雪冰城(龙湖春天店)安徽省蚌埠市龙子湖区安徽财经大学龙湖春天",
        "安徽财经大学东校区北苑食堂",
        "肯德基(淮南新世界店)安徽省淮南市田家庵区朝阳中路",
    ]

    print("=" * 60)
    print("地址 → 经纬度 → 行政区划")
    print("=" * 60)
    for addr in test_addrs:
        coords = geocode(addr)
        if coords:
            region = regeocode(*coords)
            district = region.get("district", "?")
            township = region.get("township", "?")  # township 可能为空
            print(f"  {addr[:50]:<50s} → ({coords[0]:.6f}, {coords[1]:.6f}) [{district} / {township}]")
        else:
            print(f"  {addr[:50]:<50s} → 无法解析")

    print()
    print("=" * 60)
    print("空间聚类测试")
    print("=" * 60)

    # 模拟交易数据
    import random
    random.seed(42)

    # 安财北苑集群
    base_lng, base_lat = 117.4263, 32.9085
    txns = []
    for _ in range(20):
        txns.append({
            "lng": base_lng + random.uniform(-0.0005, 0.0005),
            "lat": base_lat + random.uniform(-0.0005, 0.0005),
            "amount": random.uniform(5, 25),
            "category": random.choice(["三餐", "餐饮", "购物"]),
            "address": "安财北苑附近",
            "resolved_place": "",
        })

    # 龙湖春天集群
    base2_lng, base2_lat = 117.4310, 32.9020
    for _ in range(12):
        txns.append({
            "lng": base2_lng + random.uniform(-0.0005, 0.0005),
            "lat": base2_lat + random.uniform(-0.0005, 0.0005),
            "amount": random.uniform(5, 30),
            "category": random.choice(["餐饮", "娱乐", "购物"]),
            "address": "龙湖春天附近",
            "resolved_place": "",
        })

    # 噪点
    for _ in range(5):
        txns.append({
            "lng": 117.38 + random.uniform(-0.01, 0.01),
            "lat": 32.92 + random.uniform(-0.01, 0.01),
            "amount": random.uniform(10, 50),
            "category": "其他",
            "address": "散点",
            "resolved_place": "",
        })

    clusters, noise = _simple_dbscan(txns, eps_meters=300, min_samples=3)
    print(f"\n发现 {len(clusters)} 个聚类, {len(noise)} 个孤立点\n")
    for c in clusters:
        total = sum(abs(p.get("amount", 0)) for p in c["points"])
        cats = {}
        for p in c["points"]:
            cat = p.get("category", "未知")
            cats[cat] = cats.get(cat, 0) + abs(p.get("amount", 0))
        label = c.get("aoi_label", "未知")
        source = c.get("label_source", "?")
        print(f"\n  集群 {c['cluster_id']}: {label} ({source})")
        print(f"  中心: ({c['center_lng']}, {c['center_lat']})")
        print(f"  笔数: {c['count']} | 总金额: ¥{total:.2f} | 均值: ¥{total/c['count']:.2f}")
        print(f"  主要类别: {dict(sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5])}")

    if noise:
        noise_total = sum(abs(p.get("amount", 0)) for p in noise)
        print(f"\n  孤立点: {len(noise)} 个, 合计 ¥{noise_total:.2f}")
