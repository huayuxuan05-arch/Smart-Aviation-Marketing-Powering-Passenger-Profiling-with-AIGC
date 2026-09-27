"""活动草稿、审核、模拟实验与审计持久化。"""
import json
import random
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from app.data import AS_OF, synthetic_passengers
from app.domain import TemplateContentProvider, build_profile, contact_decision, recommendations


class Service:
    def __init__(self, database=":memory:", passengers=None):
        self.passengers = synthetic_passengers() if passengers is None else passengers
        self.lock = threading.RLock()
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, stamp TEXT, action TEXT, campaign_id TEXT)")
        self.db.commit()

    def profiles(self):
        with self.lock:
            counts = {}
            for campaign in self.campaigns():
                if campaign["status"] == "simulated":
                    pid = campaign["passenger_id"]
                    counts[pid] = counts.get(pid, 0) + 1
            return [build_profile({**p, "contacts_7d": p["contacts_7d"] + counts.get(p["id"], 0)})
                    for p in self.passengers]

    def overview(self):
        profiles = self.profiles()
        return {"data_source": "synthetic", "as_of": AS_OF.isoformat(), "passengers": len(profiles),
                "eligible": sum(contact_decision(p)["eligible"] for p in profiles),
                "high_intent": sum(p["segment"] == "高意向待转化" for p in profiles),
                "segments": {s: sum(p["segment"] == s for p in profiles) for s in sorted({p["segment"] for p in profiles})},
                "destinations": {d: sum(d in p["interests"] for p in profiles) for d in sorted({d for p in profiles for d in p["interests"]})}}

    def campaigns(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM campaigns ORDER BY rowid DESC")]

    def _save(self, campaign, action):
        self.db.execute("INSERT OR REPLACE INTO campaigns VALUES (?, ?)",
                        (campaign["id"], json.dumps(campaign, ensure_ascii=False)))
        self.db.execute("INSERT INTO audit(stamp,action,campaign_id) VALUES (?,?,?)",
                        (datetime.now(timezone.utc).isoformat(), action, campaign["id"]))
        self.db.commit()
        return campaign

    def create_campaign(self, passenger_id):
        with self.lock:
            profile = next((p for p in self.profiles() if p["id"] == passenger_id), None)
            if profile is None:
                raise ValueError("旅客不存在")
            decision = contact_decision(profile)
            if not decision["eligible"]:
                raise ValueError(decision["reason"])
            routes = recommendations(profile)
            if not routes:
                raise ValueError("没有匹配航线")
            return self._save({"id": uuid.uuid4().hex, "passenger_id": passenger_id, "status": "draft",
                               "route": routes[0], "decision": decision,
                               "content": TemplateContentProvider().generate(profile, routes[0]),
                               "data_source": "synthetic", "result": None}, "draft_created")

    def transition(self, campaign_id, action):
        with self.lock:
            row = self.db.execute("SELECT payload FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if row is None:
                raise ValueError("活动不存在")
            campaign = json.loads(row[0])
            if action == "approve" and campaign["status"] == "draft":
                campaign["status"] = "approved"
            elif action == "simulate" and campaign["status"] == "approved":
                profile = next(p for p in self.profiles() if p["id"] == campaign["passenger_id"])
                decision = contact_decision(profile)
                if not decision["eligible"]:
                    raise ValueError("投放前复核失败：" + decision["reason"])
                campaign["status"] = "simulated"
                campaign["result"] = {"delivery": "simulated_only", "real_messages_sent": 0,
                                      "experiment": self.simulated_experiment()}
                # 本次模拟占用固定演示窗口的频控预算，从活动记录恢复，重启也保留。
            else:
                raise ValueError("无效状态转换：必须先创建草稿、审核，再模拟；模拟不可重复")
            return self._save(campaign, action)

    def simulated_experiment(self, seed=7):
        rng = random.Random(seed)
        groups = {"control": {"assigned": 0, "converted": 0}, "treatment": {"assigned": 0, "converted": 0}}
        for profile in self.profiles():
            if not contact_decision(profile)["eligible"]:
                continue
            name = rng.choice(["control", "treatment"])
            groups[name]["assigned"] += 1
            # 人工设定的响应概率，只用于演示统计管线。
            groups[name]["converted"] += int(rng.random() < (.12 if name == "control" else .18))
        for group in groups.values():
            group["conversion_rate"] = round(group["converted"] / group["assigned"], 4) if group["assigned"] else None
        rates = [groups[g]["conversion_rate"] for g in ["control", "treatment"]]
        return {"data_source": "synthetic", "seed": seed, "groups": groups,
                "absolute_lift": None if None in rates else round(rates[1] - rates[0], 4),
                "note": "模拟随机分组，概率人为设定；不构成真实营销效果或统计显著性证据。"}

    def audit(self):
        with self.lock:
            return [dict(zip(["timestamp", "action", "campaign_id"], row)) for row in
                    self.db.execute("SELECT stamp,action,campaign_id FROM audit ORDER BY id DESC LIMIT 100")]
