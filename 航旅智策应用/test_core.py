"""数据契约、动态画像、历史航班及营销漏斗回归检查。"""
import unittest
from datetime import datetime,timedelta
from data_layer import connect,build,convert
from algorithm_layer import profile,history,flight_search
from evaluation_layer import marketing


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = connect()
        cls.uid = cls.c.execute('SELECT user_id FROM users ORDER BY user_id LIMIT 1').fetchone()[0]

    @classmethod
    def tearDownClass(cls):
        cls.c.close()

    def test_01_manifest_and_source_hashes(self):
        manifest = build()
        hashes = {'01_航班信息.xlsx':'4f82b8901f75e86aaf55d99d367a8cfb41ef69495ee1dba19a35b90578d9b73f',
            '02_用户行为.xlsx':'d894e544ddc47170d00c9fed62675bc2b81992aadb0588a5b447f71c44f66291',
            '03_营销反馈.xlsx':'cde6d737fc174c1f06f8d9adc2459f8b49c1657e487ee053e7471bcc85b71860'}
        self.assertEqual({f['name']:f['sha256'] for f in manifest['files']},hashes)
        self.assertEqual(manifest['counts']['behaviors'],3970000)
        self.assertEqual(self.uid,'SIMU_00006')
        self.assertEqual(len(history(self.c,self.uid)),397)

    def test_02_future_records_do_not_change_snapshot(self):
        rows=history(self.c,self.uid)
        expected=profile(self.c,self.uid,'2024-05-31',30,14)
        actual=profile(self.c,self.uid,'2024-05-31',30,14,rows)
        self.assertEqual(actual,expected)
        self.assertTrue(all(r['search_at_cst']<=expected['as_of_time'] for r in expected['records']))
        self.assertTrue(all(r['search_at_cst'].startswith('2024-05') for r in expected['records']))

    def test_excel_second_rounding(self):
        self.assertEqual(convert('search_at_cst',45261.9341782407),'2023-12-01 22:25:13')
        first=self.c.execute('SELECT search_at_cst FROM behaviors WHERE record_id="SIMB_00009_000"').fetchone()[0]
        self.assertEqual(first,'2023-12-01 22:25:13')

    def test_03_partial_process_and_unknown_budget(self):
        r=history(self.c,self.uid)[0]
        t=datetime.fromisoformat(r['search_at_cst'])+timedelta(seconds=1)
        p=profile(self.c,self.uid,str(t),30,14)
        self.assertEqual(p['records'][0]['phase'],'搜索完成')
        self.assertIsNone(p['records'][0]['visit_at_cst'])
        self.assertIsNone(p['records'][0]['dwell_seconds'])
        self.assertEqual(p['favorites'],{})
        self.assertIsNone(p['budget']['median'])

    def test_04_favorite_state_and_cancellation(self):
        # 可控边界用例：取消动作尚未发生/已经发生，不能读取未来is_favorited。
        base=history(self.c,self.uid)[0]
        add={**base,'record_id':'TEST_ADD','search_at_cst':'2024-01-01 10:00:00','visit_at_cst':'2024-01-01 10:01:00','favorite_at_cst':'2024-01-01 10:02:00','dwell_seconds':30,'favorite_action':'add','is_favorited':1}
        remove={**add,'record_id':'TEST_REMOVE','search_at_cst':'2024-01-02 10:00:00','visit_at_cst':'2024-01-02 10:01:00','favorite_at_cst':'2024-01-02 10:02:00','favorite_action':'remove','is_favorited':0}
        before=profile(self.c,self.uid,'2024-01-02 10:01:30',30,14,[add,remove])
        after=profile(self.c,self.uid,'2024-01-02 10:02:01',30,14,[add,remove])
        self.assertIn(base['object_id'],before['favorites'])
        self.assertEqual(after['favorites'],{})
        self.assertEqual(before['records'][0]['favorite_action'],'none')

    def test_05_history_matching_and_hard_budget(self):
        result=flight_search(self.c,'大理','北京','2024-01-01',700)
        self.assertGreater(result['total'],0)
        self.assertTrue(all(f['出发日']=='2024-01-01' and f['出发城市']=='大理' and f['到达城市']=='北京' and f['机票票价']<=700 for f in result['items']))
        self.assertTrue(all(f['candidate_id'].startswith('FLIGHT_ROW_') for f in result['items']))
        self.assertEqual(flight_search(self.c,'大理','北京','2024-01-01',1)['total'],0)
        self.assertEqual(flight_search(self.c,'大理','不存在的景区','2024-01-01')['mapping'],'未确定')

    def test_06_imputed_delay_excluded_from_sort(self):
        a=flight_search(self.c,'大理','北京','2024-01-01',None,'price')
        prices=[f['机票票价'] for f in a['items']]
        self.assertEqual(prices,sorted(prices))
        for f in a['items']:
            self.assertEqual(f['delay_imputed'],f['平均误点时间'] in (1,2,3,4,5))

    def test_07_full_year_funnel_matches_guide(self):
        result=marketing(self.c,None,'2024-12-31')
        expected={'send':120000,'exposure':96104,'effective_exposure':85473,'click':5701,'mock_order':248,'mock_paid':215,'mock_refund':8}
        self.assertEqual({k:result['counts'][k] for k in expected},expected)
        self.assertEqual(result['rates']['effective_ctr']['value'],6.67)
        self.assertEqual(result['rates']['click_to_paid']['value'],3.77)
        self.assertEqual(sum(o['status']=='mock_cancelled' for o in result['orders']),33)

    def test_08_prewarm_has_no_marketing(self):
        result=marketing(self.c,None,'2023-12-31')
        self.assertEqual(result['counts']['effective_exposure'],0)
        self.assertEqual(result['pushes'],[])
        self.assertIsNone(result['rates']['effective_ctr']['value'])


if __name__=='__main__':
    unittest.main(verbosity=2)
