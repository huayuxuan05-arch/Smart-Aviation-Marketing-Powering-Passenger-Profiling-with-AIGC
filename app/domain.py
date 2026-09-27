"""可解释规则基线，预留模型替换边界。"""
import math
from collections import Counter
from datetime import datetime
from html import escape

from app.data import AS_OF, ROUTES


def build_profile(passenger, as_of=AS_OF):
    signals = []
    for event in passenger["events"]:
        stamp = datetime.fromisoformat(event["occurred_at"])
        age = (as_of - stamp).total_seconds() / 86400
        if 0 <= age <= 30:
            signals.append((event, math.exp(-age / 7)))
    destinations = Counter()
    for event, weight in signals:
        destinations[event["destination"]] += weight
    intent = round(min(sum(weight for _, weight in signals) / 6, 1), 3)
    segment = "高意向待转化" if intent >= .5 else "潜在出游探索"
    if passenger["has_booking"]:
        segment = "已购票服务"
    reasons = [f"近30天有效行为{len(signals)}次", "按7天指数衰减计算兴趣"]
    return {
        "id": passenger["id"], "origin": passenger["origin"], "budget": passenger["budget"],
        "segment": segment, "intent_score": intent, "interests": dict(destinations.most_common()),
        "consent": passenger["consent"], "channels": passenger["channels"],
        "preferred_hour": passenger["preferred_hour"], "contacts_7d": passenger["contacts_7d"],
        "has_booking": passenger["has_booking"], "reasons": reasons,
        "data_source": "synthetic", "model_type": "rule_baseline", "as_of": as_of.isoformat(),
    }


def recommendations(profile):
    result = []
    for route in ROUTES:
        if route["origin"] != profile["origin"] or route["seats"] <= 0:
            continue
        interest = min(profile["interests"].get(route["destination"], 0) / 4, 1)
        affordable = route["fare"] <= profile["budget"]
        score = round(.6 * interest + .25 * float(affordable) + .15 * profile["intent_score"], 3)
        result.append({**route, "score": score, "affordable": affordable,
                       "reason": f"出发地匹配；目的地兴趣{interest:.2f}；预算{'覆盖' if affordable else '不足'}"})
    return sorted(result, key=lambda r: (-r["score"], r["id"]))


def contact_decision(profile):
    if not profile["consent"]:
        return {"eligible": False, "reason": "未授权营销"}
    if profile["has_booking"]:
        return {"eligible": False, "reason": "已购票，退出拉新营销"}
    if profile["contacts_7d"] >= 2:
        return {"eligible": False, "reason": "达到7天2次频控上限"}
    channel = next((c for c in ["app", "email"] if c in profile["channels"]), None)
    if not channel:
        return {"eligible": False, "reason": "无授权渠道"}
    return {"eligible": True, "channel": channel, "hour": profile["preferred_hour"],
            "timezone": "Asia/Shanghai", "reason": "授权渠道优先级与偏好时段规则；投放前仍需复核"}


class TemplateContentProvider:
    """离线模板提供者；企业版可以实现同一 generate 接口接入授权 LLM。"""
    name = "offline_template"

    def generate(self, profile, route):
        title = f"假期去{route['destination']}，发现{route['theme']}"
        body = (f"从{route['origin']}出发，探索{route['destination']}。"
                f"演示参考票价¥{route['fare']}，非真实报价；实际价格与余位以授权票务系统为准。")
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='960' height='480' viewBox='0 0 960 480'>"
               "<rect width='960' height='480' fill='#102e50'/>"
               "<circle cx='820' cy='90' r='210' fill='#245e75'/>"
               "<path d='M60 360 Q400 40 870 280' stroke='#57d7c2' fill='none' stroke-width='4'/>"
               f"<text x='60' y='170' fill='white' font-size='42'>{escape(title)}</text>"
               f"<text x='60' y='245' fill='#b7eee7' font-size='28'>{escape(route['origin'])} → {escape(route['destination'])}</text>"
               "<text x='60' y='430' fill='white' font-size='22'>合成场景 · 模板视觉 · 非真实促销</text></svg>")
        return {"title": title, "body": body, "visual_svg": svg, "provider": self.name,
                "is_aigc": False, "review_required": True, "prompt_version": "template-v1"}
