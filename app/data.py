"""可重复合成数据；与真实旅客及真实航班无关。"""
import random
from datetime import datetime, timedelta, timezone

AS_OF = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)
ROUTES = [
    {"id": "R01", "origin": "上海", "destination": "三亚", "theme": "海滨度假", "fare": 980, "seats": 48},
    {"id": "R02", "origin": "上海", "destination": "成都", "theme": "城市美食", "fare": 650, "seats": 72},
    {"id": "R03", "origin": "北京", "destination": "昆明", "theme": "自然探索", "fare": 850, "seats": 60},
    {"id": "R04", "origin": "广州", "destination": "西安", "theme": "文化探索", "fare": 720, "seats": 55},
]


def synthetic_passengers(count=120, seed=42):
    rng = random.Random(seed)
    passengers = []
    for index in range(count):
        route = ROUTES[index % len(ROUTES)]
        events = []
        for _ in range(rng.randint(1, 12)):
            events.append({
                "event_type": rng.choice(["destination_search", "hotel_view", "fare_view", "guide_view"]),
                "destination": route["destination"],
                "occurred_at": (AS_OF - timedelta(days=rng.randint(0, 29), hours=rng.randint(0, 20))).isoformat(),
            })
        passengers.append({
            "id": f"SYN-{index + 1:04d}", "origin": route["origin"],
            "budget": rng.choice([600, 800, 1000, 1500]), "events": events,
            "consent": index % 7 != 0, "channels": ["app", "email"] if index % 3 else ["app"],
            "preferred_hour": rng.choice([10, 12, 18, 20]), "contacts_7d": index % 4,
            "has_booking": index % 11 == 0, "data_source": "synthetic",
        })
    return passengers
