# -*- coding: utf-8 -*-
"""合成数据集生成器：电商订单 × 物流履约（5 表，约 10 万行）。

与《赛题二方向一-冲冠方案》对齐的设计目标：
  1. 可复现：固定随机种子（默认 42）；
  2. 歧义密度可控：金额多口径 / 超时两口径 / 实体歧义（"苹果"）/ 相对时间 / 多跳关系；
  3. 固定数据截止日 DATASET_END（默认 2026-09-20）：
     所有相对时间表达（"上月""近 7 天"…）均以该日期为基准，保证评测可复现。

用法：
    python data/generate_data.py
    python data/generate_data.py --end-date 2026-09-20 --seed 42 --out data/warehouse.duckdb
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# 中文 Windows 控制台默认 GBK，输出 ✅ 会 UnicodeEncodeError 并让脚本以非零码退出。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 基础常量

PROVINCE_REGION = {}
for _region, _provinces in {
    "华东": ["上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"],
    "华南": ["广东", "广西", "海南"],
    "华北": ["北京", "天津", "河北", "山西", "内蒙古"],
    "华中": ["河南", "湖北", "湖南"],
    "西南": ["四川", "重庆", "贵州", "云南"],
    "西北": ["陕西", "甘肃", "青海", "宁夏", "新疆"],
    "东北": ["辽宁", "吉林", "黑龙江"],
}.items():
    for _p in _provinces:
        PROVINCE_REGION[_p] = _region

PROVINCE_CITIES = {
    "上海": ["上海"], "江苏": ["南京", "苏州", "无锡"], "浙江": ["杭州", "宁波", "温州"],
    "安徽": ["合肥", "芜湖"], "福建": ["福州", "厦门"], "江西": ["南昌"], "山东": ["济南", "青岛"],
    "广东": ["广州", "深圳", "东莞"], "广西": ["南宁"], "海南": ["海口"],
    "北京": ["北京"], "天津": ["天津"], "河北": ["石家庄"], "山西": ["太原"], "内蒙古": ["呼和浩特"],
    "河南": ["郑州"], "湖北": ["武汉"], "湖南": ["长沙"],
    "四川": ["成都"], "重庆": ["重庆"], "贵州": ["贵阳"], "云南": ["昆明"],
    "陕西": ["西安"], "甘肃": ["兰州"], "青海": ["西宁"], "宁夏": ["银川"], "新疆": ["乌鲁木齐"],
    "辽宁": ["沈阳", "大连"], "吉林": ["长春"], "黑龙江": ["哈尔滨"],
}

REGION_WEIGHTS = {"华东": 0.30, "华南": 0.18, "华北": 0.16, "华中": 0.12, "西南": 0.10, "西北": 0.06, "东北": 0.08}

# 履约承诺时效（小时）——超时公理以此为基准
SLA_HOURS = {"华东": 24, "华南": 36, "华北": 48, "华中": 48, "西南": 60, "西北": 72, "东北": 72}

CATEGORY_BRANDS = {
    "数码": ["苹果", "华为", "小米", "OPPO", "vivo"],
    "家电": ["美的", "海尔", "格力", "九阳"],
    "服饰": ["优衣库", "李宁", "安踏", "海澜之家"],
    "食品": ["三只松鼠", "良品铺子", "蒙牛", "伊利"],
    "美妆": ["珀莱雅", "花西子", "自然堂", "薇诺娜"],
}
CATEGORY_COUNT = {"数码": 120, "家电": 100, "服饰": 110, "食品": 90, "美妆": 80}
PRICE_RANGE = {"数码": (999, 9999), "家电": (299, 5999), "服饰": (59, 899), "食品": (9, 199), "美妆": (29, 599)}
SERIES = ["旗舰款", "畅享款", "青春版", "专业版", "经典款"]
# 苹果数码的真实感命名（实体歧义的另一端：客户名中也含"苹果"）
APPLE_PRODUCT_NAMES = ["苹果 iPhone 15", "苹果 iPhone 15 Pro", "苹果 MacBook Air M2", "苹果 iPad 10", "苹果 Watch S9"]

CHANNELS = ["App", "小程序", "网页"]
CHANNEL_P = [0.5, 0.3, 0.2]

CARRIERS = ["顺捷速运", "风驰物流", "安达快递", "飞鱼速运", "陆港物流", "星速达", "恒通供应链", "蓝天快运"]

SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕张孔曹严华金魏陶姜"
GIVEN = ["伟", "敏", "静", "磊", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英", "霞", "平", "刚", "桂英", "芳", "鹏", "宇"]
# 含"苹果"的客户名——与"苹果"品牌构成实体歧义
APPLE_CUSTOMERS = ["苹果果业有限公司", "红苹果商贸有限公司", "苹果乐园文化传播有限公司"]


# ---------------------------------------------------------------- 生成逻辑

def _pystr(df: pd.DataFrame) -> pd.DataFrame:
    """把 object 列中的 numpy 字符串标量（np.str_）统一转为原生 Python str。

    DuckDB 1.5.x 的 pandas 扫描器不接受 np.str_（报 "Unsupported string type"）。
    """
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(str)
    return df


def generate(end_date: str, seed: int, out_path: Path) -> dict:
    rng = np.random.default_rng(seed)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    start_ts = pd.Timestamp("2026-01-01")

    # ---- 承运商（8）
    carriers = pd.DataFrame({
        "carrier_id": [f"K{i+1:02d}" for i in range(len(CARRIERS))],
        "carrier_name": CARRIERS,
        "rating": np.round(rng.uniform(3.5, 5.0, len(CARRIERS)), 1),
    })

    # ---- 商品（500）
    rows = []
    pid = 1
    for category, brands in CATEGORY_BRANDS.items():
        n = CATEGORY_COUNT[category]
        lo, hi = PRICE_RANGE[category]
        names_in_cat = []
        if category == "数码":
            names_in_cat.extend(APPLE_PRODUCT_NAMES)
        while len(names_in_cat) < n:
            brand = brands[rng.integers(0, len(brands))]
            series = SERIES[rng.integers(0, len(SERIES))]
            model = f"{rng.integers(1, 9)}{rng.choice(['号', '代', 'Pro', 'Max', 'Plus'])}"
            names_in_cat.append(f"{brand} {series} {model}")
        for name in names_in_cat[:n]:
            brand = next((b for b in brands if name.startswith(b)), brands[0])
            price = float(np.round(rng.uniform(lo, hi) if rng.random() < 0.7 else rng.uniform(hi * 0.8, hi * 1.6), 2))
            rows.append({"product_id": f"P{pid:04d}", "product_name": name, "brand": brand,
                         "category": category, "price": price})
            pid += 1
    products = pd.DataFrame(rows)

    # ---- 客户（5000）
    cust_rows = []
    for i in range(5000):
        cid = f"C{i+1:05d}"
        region = rng.choice(list(REGION_WEIGHTS), p=list(REGION_WEIGHTS.values()))
        province = rng.choice([p for p, r in PROVINCE_REGION.items() if r == region])
        city = rng.choice(PROVINCE_CITIES[province])
        if i < len(APPLE_CUSTOMERS):  # 含"苹果"的客户名（实体歧义设计）
            name = APPLE_CUSTOMERS[i]
        elif rng.random() < 0.4:  # 企业客户
            name = f"{city}{SURNAMES[rng.integers(0, len(SURNAMES))]}氏{SERIES[rng.integers(0, len(SERIES))][:2]}贸易"
        else:  # 个人客户
            name = SURNAMES[rng.integers(0, len(SURNAMES))] + GIVEN[rng.integers(0, len(GIVEN))]
        cust_rows.append({"customer_id": cid, "customer_name": name, "city": city,
                          "province": province, "region": PROVINCE_REGION[province]})
    customers = pd.DataFrame(cust_rows)

    # ---- 订单（50000）
    n_orders = 50000
    days = (end_ts.normalize() - start_ts.normalize()).days  # 262
    weights = np.linspace(1.0, 1.3, days + 1)
    day_idx = rng.choice(np.arange(days + 1), size=n_orders, p=weights / weights.sum())
    sec_off = rng.integers(8 * 3600, 23 * 3600, size=n_orders)
    order_time = start_ts + pd.to_timedelta(day_idx, unit="D") + pd.to_timedelta(sec_off, unit="s")

    cust_idx = rng.integers(0, len(customers), size=n_orders)
    prod_idx = rng.integers(0, len(products), size=n_orders)
    quantity = rng.choice([1, 2, 3, 4, 5], size=n_orders, p=[0.50, 0.25, 0.15, 0.07, 0.03])
    price = products["price"].to_numpy()[prod_idx]
    order_amount = np.round(price * quantity, 2)
    discount = np.round(rng.uniform(0.70, 1.00, size=n_orders), 2)
    pay_amount = np.round(order_amount * discount, 2)
    channel = np.array(CHANNELS)[rng.choice(len(CHANNELS), size=n_orders, p=CHANNEL_P)]

    cancelled = rng.random(n_orders) < 0.06
    recent = (end_ts - order_time).total_seconds() < 3 * 86400
    in_progress = (~cancelled) & recent & (rng.random(n_orders) < 0.4)
    status = np.where(cancelled, "已取消", np.where(in_progress, "进行中", "已完成"))

    orders = pd.DataFrame({
        "order_id": [f"O{i+1:07d}" for i in range(n_orders)],
        "customer_id": customers["customer_id"].to_numpy()[cust_idx],
        "product_id": products["product_id"].to_numpy()[prod_idx],
        "order_time": order_time,
        "quantity": quantity,
        "order_amount": order_amount,
        "pay_amount": pay_amount,
        "discount": discount,
        "status": status,
        "channel": channel,
    })

    # ---- 运单（约 4.3 万）
    ship_mask = (~cancelled) & (rng.random(n_orders) < 0.92)
    o = orders.loc[ship_mask].reset_index(drop=True)
    ns = len(o)
    ship_time = o["order_time"] + pd.to_timedelta(rng.uniform(2, 60, ns), unit="h")
    region_arr = customers.set_index("customer_id").loc[o["customer_id"], "region"].to_numpy()
    sla = np.array([SLA_HOURS[r] for r in region_arr])
    promised_time = ship_time + pd.to_timedelta(sla, unit="h")

    late = rng.random(ns) < 0.18
    delta_h = np.where(late, rng.uniform(1, 48, ns), -rng.uniform(1, 20, ns))
    delivery_time = promised_time + pd.to_timedelta(delta_h, unit="h")

    in_transit = (delivery_time > end_ts) | ((rng.random(ns) < 0.02) & (delivery_time <= end_ts))
    abnormal = (rng.random(ns) < 0.01) & (~in_transit) & late
    s_status = np.where(in_transit, "运输中", np.where(abnormal, "异常", "已签收"))
    delivery_time = delivery_time.where(~in_transit, pd.NaT)

    shipments = pd.DataFrame({
        "shipment_id": [f"S{i+1:07d}" for i in range(ns)],
        "order_id": o["order_id"].to_numpy(),
        "carrier_id": carriers["carrier_id"].to_numpy()[rng.integers(0, len(carriers), size=ns)],
        "ship_time": ship_time,
        "promised_time": promised_time,
        "delivery_time": delivery_time,
        "status": s_status,
    })

    # ---- 写库
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(out_path))
    con.register("df_orders", _pystr(orders))
    con.register("df_shipments", _pystr(shipments))
    con.register("df_products", _pystr(products))
    con.register("df_customers", _pystr(customers))
    con.register("df_carriers", _pystr(carriers))
    con.execute("CREATE OR REPLACE TABLE orders AS SELECT * FROM df_orders")
    con.execute("CREATE OR REPLACE TABLE shipments AS SELECT * FROM df_shipments")
    con.execute("CREATE OR REPLACE TABLE products AS SELECT * FROM df_products")
    con.execute("CREATE OR REPLACE TABLE customers AS SELECT * FROM df_customers")
    con.execute("CREATE OR REPLACE TABLE carriers AS SELECT * FROM df_carriers")
    con.execute("CREATE OR REPLACE TABLE meta AS SELECT * FROM (VALUES "
                f"('dataset_start', '{start_ts.date()}'), ('dataset_end', '{end_ts.date()}'), "
                f"('seed', '{seed}'), ('schema_version', 'v1')) t(key, value)")

    # ---- 统计（供回填方案文档 / 快速自检）
    stats = {
        "generated_for_end_date": str(end_ts.date()),
        "seed": seed,
        "tables": {},
        "key_aggregates": {},
    }
    for t in ["orders", "shipments", "products", "customers", "carriers"]:
        stats["tables"][t] = int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])

    # ---- 任务恢复工作台的场景表（同一仓库的 demo schema，供工作台只读取材）
    sys.path.insert(0, str(ROOT))
    from src.scenario_fixture import install as install_scenario  # noqa: E402
    install_scenario(con)
    stats["scenario"] = {name: int(con.execute(f"SELECT COUNT(*) FROM demo.{name}").fetchone()[0])
                         for name in ("customers", "carriers", "orders", "shipments")}

    gmv = con.execute(
        "SELECT SUM(order_amount), SUM(pay_amount), "
        "SUM(pay_amount) FILTER (WHERE status <> '已取消') FROM orders").fetchone()
    rates = con.execute(
        "SELECT "
        "COUNT(*) FILTER (WHERE delivery_time IS NOT NULL) * 1.0 / COUNT(*), "
        "COUNT(*) FILTER (WHERE delivery_time > promised_time) * 1.0 / NULLIF(COUNT(*) FILTER (WHERE delivery_time IS NOT NULL), 0), "
        "AVG(epoch(delivery_time - ship_time) / 3600.0) "
        "FROM shipments").fetchone()
    stats["key_aggregates"] = {
        "gmv_gross": float(gmv[0]), "gmv_paid": float(gmv[1]), "gmv_net": float(gmv[2]),
        "signed_rate_all": float(rates[0]), "delay_rate_delivered_only": float(rates[1]),
        "avg_fulfill_hours": float(rates[2]),
        "note": "全域参考值（不做筛选），用于自检与文档回填；评测题以 gold SQL 为准",
    }
    con.close()
    (out_path.parent / "warehouse_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="生成电商×物流合成数据集")
    ap.add_argument("--end-date", default="2026-09-20", help="数据截止日（相对时间基准），默认 2026-09-20")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(ROOT / "data" / "warehouse.duckdb"))
    args = ap.parse_args()

    stats = generate(args.end_date, args.seed, Path(args.out))
    print("✅ 数据生成完成:", args.out)
    for t, c in stats["tables"].items():
        print(f"   {t:<10} {c:>7,} 行")
    print("   关键参考值:")
    for k, v in stats["key_aggregates"].items():
        if isinstance(v, float):
            print(f"   {k:<24} {v:,.6f}")
    print("   任务恢复场景表（demo schema）:",
          "、".join(f"{k} {v:,}" for k, v in stats.get("scenario", {}).items()))
    print("   （相对时间基准 =", stats["generated_for_end_date"], "）")


if __name__ == "__main__":
    main()
