from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

import survey_evidence as survey
import personal_app as personal
from data_layer import connect, CST


class EvidenceTests(unittest.TestCase):
    def raw(self,**changes):
        raw={q['id']:([1] if q['type']=='multi' else 1) for q in survey.schema()['questions']}
        return {**raw,'Q03':2,'response_id':'R1','research_id':'S1','_time':'2026-10-01 12:00',**changes}
    def audit(self,records):return survey.audit(records,datetime(2026,10,15,11,tzinfo=CST))
    def test_conflict_does_not_guess_or_discard_other_fields(self):
        rows,s=self.audit([self.raw(Q28='[4,2,9,3]',Q21='[3,9]')])
        self.assertIsNone(rows[0]['answers']['Q28']);self.assertIsNone(rows[0]['answers']['Q21'])
        self.assertEqual(rows[0]['answers']['Q18'],[1]);self.assertEqual(s['counts']['eligible_rows'],1)
        self.assertEqual(s['distributions']['Q28']['denominator'],0);self.assertEqual(s['counts']['exclusive_conflict_rows'],1)
    def test_numeric_multi_and_json_array_are_same_codes(self):
        q=survey.schema()['questions'][12]
        self.assertEqual(survey.parse_answer(18,q),([18],None));self.assertEqual(survey.parse_answer('[18]',q),([18],None))
        self.assertEqual(survey.parse_answer('[2,1]',q),([1,2],None));self.assertIsNotNone(survey.parse_answer('[18,1]',q)[1])
    def test_future_consent_duplicates_excluded(self):
        rows,s=self.audit([self.raw(),self.raw(response_id='R1'),self.raw(response_id='R2',Q01=2),self.raw(response_id='R3',_time='2026-10-15 23:59')])
        self.assertEqual(s['counts']['eligible_rows'],1);self.assertEqual(s['distributions']['Q18']['denominator'],1)
        self.assertEqual(s['counts']['future_timestamp'],1);self.assertFalse(any(r['usable'] for r in rows[1:]))
    def test_skip_and_wrong_city_attraction_not_counted(self):
        rows,s=self.audit([self.raw(Q03=1,Q04='[2]',Q13='[2]',Q14='[1]')])
        self.assertIsNone(rows[0]['answers']['Q04']);self.assertIsNone(rows[0]['answers']['Q14'])
        self.assertEqual(rows[0]['answers']['Q13'],[2]);self.assertEqual(s['distributions']['Q04']['denominator'],0)
    def test_target_and_recalled_cities_do_not_leak_into_features(self):
        rows,_=self.audit([self.raw()]);before=survey.features(rows[0])
        for key in ['Q13','Q14','Q23','Q24','Q25']:rows[0]['answers'][key]=[2]
        self.assertEqual(before,survey.features(rows[0]))
    def test_public_output_has_no_response_identifiers(self):
        rows,summary=self.audit([self.raw()])
        with TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp') as folder,patch.object(survey,'STORE',Path(folder)):
            (Path(folder)/'summary.json').write_text(json.dumps(summary),encoding='utf-8')
            (Path(folder)/'responses.private.json').write_text(json.dumps(rows),encoding='utf-8')
            public=json.dumps(survey.public_summary());self.assertNotIn('R1',public);self.assertNotIn(rows[0]['key'],public)


class SurveyPersonalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def plan(self,**changes):
        prefs=personal.validate(self.source,{**personal.defaults(),'origin':'北京','destination':'杭州','start_date':'2026-11-15',**changes})
        return personal.make_plan(self.source,prefs)
    def test_explicit_city_attractions_lodging_and_budget_choice(self):
        with patch.object(survey,'destination_prior',return_value={'长沙':1,'杭州':0}):
            plan=self.plan(days=5,preferred_attractions=['中国茶叶博物馆','西湖'],lodging_priority='安静休息',trip_budget=100,overbudget_policy='暂缓出游')
        self.assertEqual(plan['destination'],'杭州');self.assertFalse(plan['recommendation_model']['survey_prior_used'])
        activities=' '.join(b['activity'] for d in plan['daily_itinerary'] for b in d['blocks'])
        self.assertIn('中国茶叶博物馆',activities);self.assertIn('西湖',activities)
        self.assertIn('安静休息',plan['lodging']['type']);self.assertIn('暂缓出游',plan['backup_options'][0]['advice'])
        self.assertEqual(plan['start_date'],'2026-11-15');self.assertEqual(plan['budget']['specified_total'],100)
    def test_date_comparison_within_permission_never_auto_applied(self):
        plan=self.plan(date_flexibility='前后1天可比较');self.assertEqual(plan['start_date'],'2026-11-15')
        self.assertEqual([d['start_date'] for d in plan['date_comparisons']],['2026-11-14','2026-11-16'])
        self.assertEqual(self.plan(date_flexibility='日期固定')['date_comparisons'],[])
    def test_short_plan_discloses_selected_but_unscheduled_places(self):
        plan=self.plan(days=2,preferred_attractions=['西湖','龙井村','中国茶叶博物馆'])
        self.assertEqual(len(plan['daily_itinerary']),2);self.assertTrue(any('尚未排入' in x for x in plan['checklist']))
    def test_invalid_city_attraction_pair_rejected(self):
        with self.assertRaisesRegex(ValueError,'当前目的地'):self.plan(preferred_attractions=['故宫'])
    def test_unknown_date_duration_and_budget_saved_as_intent_without_plan(self):
        with TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp') as folder,patch.object(personal,'RUNTIME',Path(folder)):
            _,owner,_=personal.session()
            prefs={**personal.defaults(),'planning_stage':'先收集灵感','start_date':'','days':'','trip_budget':''}
            result=personal.save_preferences(self.source,owner,{'preferences':prefs,'expected_revision':0})
            self.assertIsNone(result['preferences']['start_date']);self.assertIsNone(result['preferences']['days']);self.assertIsNone(result['preferences']['trip_budget'])
            self.assertEqual(personal.state(owner)['plans'],[])
            with self.assertRaisesRegex(ValueError,'仅保存出游意向'):personal.create_plan(self.source,owner,{'preferences':prefs,'expected_revision':1})


if __name__=='__main__':unittest.main()
