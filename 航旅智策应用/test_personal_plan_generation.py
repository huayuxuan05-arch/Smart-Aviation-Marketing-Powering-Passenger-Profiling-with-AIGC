"""模型内容、训练证据及确认版本核验，全部推理响应为测试夹具。"""
import copy
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import local_generation as model
import personal_app as personal
import personal_assistant as assistant
import personal_plan_generation as generation
import flight_quotes
from data_layer import connect
from planning_evidence import guidance


def content(days):
    return {'daily_itinerary':[{'title':'城市慢游','blocks':[{'time':t,'activity':'公园散步','detail':'视精力调整，首末日预留接驳时间'} for t in ['上午','下午','晚上']]} for _ in range(days)],
        'lodging':{'area':'地铁站附近','conditions':'优先安静、可取消，预订前核验'},
        'nonflight_costs':{'住宿':660,'餐饮':400,'市内交通':200,'景点与体验':160},
        'backup_options':[{'name':'减少付费活动','advice':'优先公园散步'},{'name':'住宿比较','advice':'比较公共交通便利区域'}],
        'travel_advice':{'summary':'按轻松节奏准备成都旅行','reasons':['遵循本人城市选择','按主动预算安排'],'practical_tips':['核对证件','提前核验酒店','核对航班行李']},
        'checklist':['核对证件','核对航班行李','核对酒店取消条件','核验景点预约']}


class PlanGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        self.temp=TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp')
        self.runtime=patch.object(personal,'RUNTIME',Path(self.temp.name));self.runtime.start();self.addCleanup(self.runtime.stop);self.addCleanup(self.temp.cleanup)
        _,self.owner,_=personal.session()
        self.prefs={**personal.defaults(),'origin':'上海','destination':'成都','start_date':'2026-11-15','days':4,'trip_budget':4000,'required_airlines':['3U'],'excluded_airlines':['9C']}
        self.plan=personal.make_plan(self.source,self.prefs)
    def response(self,value):
        return {'model':model.ALIAS,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value,ensure_ascii=False)}}],'usage':{'completion_tokens':400}}
    def compose(self,value):
        with patch.object(model,'ensure'),patch.object(model,'rpc',return_value=self.response(value)) as rpc:
            result=generation.compose(self.plan,self.prefs)
        return result,rpc
    def test_all_cards_generated_but_flight_dates_and_estimates_remain_controlled(self):
        result,rpc=self.compose(content(4))
        self.assertTrue(result['ai_planning']['content_generated']);self.assertNotIn('live_flights',result)
        self.assertEqual(result['daily_itinerary'][0]['date'],'2026-11-15')
        self.assertEqual(result['daily_itinerary'][-1]['date'],'2026-11-18')
        projected=flight_quotes.public_payload(result)
        self.assertEqual(next(c['value'] for c in projected['budget']['components'] if c['name']=='住宿'),660)
        self.assertIsNone(projected['budget']['estimated_total'])
        self.assertEqual(result['preference_constraints']['required_airlines'],['3U'])
        self.assertTrue(model.explanation_matches_plan(projected))
        self.assertEqual(self.plan['lodging']['area'],personal.make_plan(self.source,self.prefs)['lodging']['area'])
        self.assertIn('training_guidance',rpc.call_args.args[1]['messages'][1]['content'])
    def test_bad_outputs_cannot_become_trip_content(self):
        for change in [lambda v:v['nonflight_costs'].update(住宿=-1),lambda v:v.update(flight_number='3U1234'),
                       lambda v:v['daily_itinerary'].pop(),lambda v:v['checklist'].append('已预订酒店'),
                       lambda v:v['checklist'].append('乘坐3U1234航班')]:
            value=content(4);change(value)
            with self.assertRaises(ValueError):self.compose(value)
    def test_cached_model_preview_is_identical_to_confirmed_plan(self):
        with patch.dict(os.environ,{'AEROLENS_GENERATION_MODE':'template'}):
            personal.create_plan(self.source,self.owner,{'preferences':self.prefs,'expected_revision':0})
        with patch.dict(os.environ,{'AEROLENS_GENERATION_MODE':'local-model'}),patch.object(model,'extract_preferences',return_value={'items':[],'engine':'QA mocked model'}),patch.object(model,'ensure'),patch.object(model,'rpc',return_value=self.response(content(4))) as rpc:
            draft=assistant.create(self.source,self.owner,{'text':'轻松一点，减少付费活动','kind':'feedback','plan_id':personal.state(self.owner)['latest_plan']['id'],'expected_revision':1})
            self.assertTrue(draft['can_confirm'])
            result=assistant.confirm(self.source,self.owner,draft['id'],{'confirmed':True,'version':draft['version']})
        self.assertEqual(rpc.call_count,1)
        self.assertEqual(draft['preview']['daily_itinerary'],result['plan']['daily_itinerary'])
        self.assertEqual(draft['preview']['budget'],result['plan']['budget'])
    def test_training_guidance_is_traceable_and_test_is_evidence_only(self):
        result=guidance(self.prefs)
        self.assertEqual(result['simulated_users'],10000)
        self.assertTrue(max(result['training_dates'])<min(result['test_dates']))
        self.assertIn('ndcg_at_3',result['test_ranking_metrics'])
        self.assertNotIn('user_id',result)


if __name__=='__main__':unittest.main()
