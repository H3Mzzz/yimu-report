#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高德地图位置解析模块

两件事：
  1. 地址文本 → 经纬度（地理编码）
  2. 经纬度 → 区域标签（逆地理编码，AOI > 商圈 > 网格三级兜底）

不做复杂空间聚类——地址本身已有足够信息，按逆地理标签分组即可。
"""

import os
import re
import json
import time
import hashlib
from pathlib import Path
from collections import defaultdict

import requests

AMAP_KEY = os.environ.get("AMAP_API_KEY", "")
AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
AMAP_TEXT_URL = "https://restapi.amap.com/v3/place/text"

CACHE_DIR = Path(__file__).parent / ".amap_cache"
CACHE_TTL = 30 * 24 * 3600  # 30 天


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

def _extract_poi_coords(data: dict) -> tuple[float, float] | None:
    """从高德 POI 搜索结果提取首个坐标"""
    if data.get("status") == "1" and data.get("pois"):
        loc = data["pois"][0]["location"]
        lng_str, lat_str = str(loc).split(",")
        return (float(lng_str), float(lat_str))
    return None


def _geocode_attempt(address: str, city: str) -> tuple[float, float] | None:
    """单次 geocode 尝试，返回 (lng, lat) 或 None（不处理缓存）"""
    params = {"key": AMAP_KEY, "city": city, "offset": 3}

    # 策略0：直接用原始地址做文本搜索
    coords = _extract_poi_coords(_safe_get(AMAP_TEXT_URL, {
        **params, "keywords": address,
    }))

    # 策略1：拆解「品牌(分店)名称」格式，分别搜品牌+区域
    if not coords:
        m = re.match(r"^(.+?)\((.+?)\)(.*)$", address)
        if m:
            brand, area, rest = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            coords = _extract_poi_coords(_safe_get(AMAP_TEXT_URL, {
                **params, "keywords": f"{brand} {area}",
            }))
            if not coords and rest:
                coords = _extract_poi_coords(_safe_get(AMAP_TEXT_URL, {
                    **params, "keywords": f"{brand} {rest}",
                }))

    # 策略2：地理编码（对看起来像地址的文本有效）
    if not coords:
        data = _safe_get(AMAP_GEO_URL, {
            "key": AMAP_KEY, "address": address, "city": city,
        })
        if data.get("status") == "1" and data.get("geocodes"):
            loc = data["geocodes"][0]["location"]
            lng, lat = loc.split(",")
            coords = (float(lng), float(lat))

    return coords


def geocode(address: str, city: str = "") -> tuple[float, float] | None:
    """
    地址文本 → (lng, lat) 经纬度。
    全国范围搜索，缓存 30 天。
    """
    if not address or not AMAP_KEY:
        return None

    cache_key = f"geocode:{address}"
    cached = _cache_get(cache_key)
    if cached:
        if cached.get("_not_found"):
            return None
        lng, lat = cached.get("lng"), cached.get("lat")
        if lng is not None and lat is not None:
            return lng, lat
        return None

    coords = _geocode_attempt(address, city)

    if coords:
        _cache_set(cache_key, {"lng": coords[0], "lat": coords[1]})
    else:
        # 失败结果也缓存，避免重复消耗配额
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
        "extensions": "all",
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
            "aois": [{"name": aoi.get("name", ""), "type": aoi.get("type", "")}
                     for aoi in regeo.get("aois", [])],
            "business_areas": [ba.get("name", "") for ba in regeo.get("businessAreas", [])],
            "street_number": regeo.get("streetNumber", {}).get("street", "") +
                              (regeo.get("streetNumber", {}).get("number", "") or ""),
        }

    _cache_set(cache_key, {"address": result})
    return result


# ═══════════════════════════════════════════════════════════
# 区域标签提取（三级兜底）
# ═══════════════════════════════════════════════════════════

def _extract_cluster_label(region: dict, lng: float, lat: float) -> str:
    """
    从逆地理结果提取聚类标签，三级兜底：
      1. AOI 兴趣面（学校/园区/商场等面状区域）
      2. 商圈
      3. 经纬度网格（保留3位小数 ≈ 100m 范围）
    """
    aois = region.get("aois", [])
    if aois:
        first = aois[0]
        return first.get("name", first) if isinstance(first, dict) else first

    bas = region.get("business_areas", [])
    if bas:
        return bas[0]

    return f"附近({round(lng, 3)},{round(lat, 3)})"


# ═══════════════════════════════════════════════════════════
# 批量处理
# ═══════════════════════════════════════════════════════════

# 手动坐标映射：高德不收录的地点可通过环境变量注入
# 格式：JSON 字符串，{"点名": [lng, lat], ...}
try:
    _HARDCODED_COORDS: dict[str, tuple[float, float]] = {
        k: (v[0], v[1])
        for k, v in json.loads(os.environ.get("HARDCODED_LOCATIONS", "{}")).items()
    }
except (json.JSONDecodeError, TypeError, KeyError):
    print("[位置解析] HARDCODED_LOCATIONS 格式无效，已忽略")
    _HARDCODED_COORDS = {}


def enrich_transactions(transactions: list[dict], city: str = "") -> list[dict]:
    """
    为每笔交易附加位置信息（返回新列表，不修改输入）。

    附加字段: lng, lat, aoi_label, district, township, formatted_address, aois
    """
    result = []
    for t in transactions:
        addr = t.get("address", "") or ""
        enriched = dict(t)
        enriched["lng"] = None
        enriched["lat"] = None
        enriched["aoi_label"] = ""
        enriched["district"] = ""
        enriched["township"] = ""
        enriched["formatted_address"] = ""
        enriched["aois"] = []

        if not addr:
            result.append(enriched)
            continue

        # 速率限制
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

        region = regeocode(*coords)
        enriched["aoi_label"] = _extract_cluster_label(region, *coords)
        enriched["district"] = region.get("district", "")
        enriched["township"] = region.get("township", "")
        enriched["formatted_address"] = region.get("formatted_address", "")
        enriched["aois"] = region.get("aois", [])

        result.append(enriched)

    return result


# ═══════════════════════════════════════════════════════════
# 区域聚合摘要
# ═══════════════════════════════════════════════════════════

def area_summary(transactions: list[dict]) -> dict:
    """
    从已 enrich 的交易中按 aoi_label 分组聚合。

    返回:
    {
        "clusters": [{
            "aoi_label": str, "count": int, "total_amount": float,
            "avg_amount": float, "top_categories": {cat: amount, ...}
        }, ...],
        "stats": {"total_with_location": N, "total_without_location": N, "cluster_count": N}
    }
    """
    with_loc = [t for t in transactions if t.get("lng") is not None]
    without_loc = len(transactions) - len(with_loc)

    if not with_loc:
        return {
            "clusters": [],
            "stats": {"total_with_location": 0, "total_without_location": without_loc, "cluster_count": 0},
        }

    groups = defaultdict(list)
    for t in with_loc:
        label = t.get("aoi_label", "未知区域")
        groups[label].append(t)

    clusters = []
    for label, pts in groups.items():
        total = sum(abs(p.get("amount", 0)) for p in pts)
        cats = defaultdict(float)
        for p in pts:
            cats[p.get("category", "未知")] += abs(p.get("amount", 0))
        clusters.append({
            "aoi_label": label,
            "count": len(pts),
            "total_amount": round(total, 2),
            "avg_amount": round(total / len(pts), 2),
            "top_categories": dict(sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]),
        })

    clusters.sort(key=lambda x: x["total_amount"], reverse=True)

    return {
        "clusters": clusters,
        "stats": {
            "total_with_location": len(with_loc),
            "total_without_location": without_loc,
            "cluster_count": len(clusters),
        },
    }


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
    print("地址 → 经纬度 → 区域标签")
    print("=" * 60)
    for addr in test_addrs:
        coords = geocode(addr)
        if coords:
            region = regeocode(*coords)
            label = _extract_cluster_label(region, *coords)
            print(f"  {addr[:50]:<50s} → {label}")
        else:
            print(f"  {addr[:50]:<50s} → 无法解析")

    print()
    print("=" * 60)
    print("区域聚合测试")
    print("=" * 60)

    txns = [
        {"address": "古茗(安徽财经大学店)安徽财经大学东校区", "amount": 12, "category": "餐饮"},
        {"address": "库迪咖啡(安徽财经大学东校区店)安徽财经大学东校区", "amount": 9, "category": "餐饮"},
        {"address": "安徽财经大学东校区北苑食堂", "amount": 15, "category": "三餐"},
        {"address": "肯德基(淮南新世界店)安徽省淮南市田家庵区朝阳中路", "amount": 35, "category": "餐饮"},
        {"address": "蜜雪冰城(龙湖春天店)安徽省蚌埠市龙子湖区", "amount": 6, "category": "餐饮"},
    ]

    enriched = enrich_transactions(txns)
    summary = area_summary(enriched)

    print(f"\n定位成功 {summary['stats']['total_with_location']}/{len(txns)} 条")
    print(f"识别 {summary['stats']['cluster_count']} 个区域\n")
    for c in summary["clusters"]:
        cats = ", ".join(f"{k} ¥{v:.0f}" for k, v in c["top_categories"].items())
        print(f"  📍 {c['aoi_label']}: {c['count']}笔 ¥{c['total_amount']:.2f} | {cats}")
