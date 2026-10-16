"""Account identity, ownership and consent are independent of the browser token."""
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import accounts
import personal_app as personal
import real_travelers as real
from data_layer import connect


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        self.temp=TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp')
        self.runtime=patch.object(personal,'RUNTIME',Path(self.temp.name));self.runtime.start()
        self.addCleanup(self.temp.cleanup);self.addCleanup(self.runtime.stop)
        self.owner=accounts.create_account('traveler_a','QA-only-password')
        self.other=accounts.create_account('traveler_b','QA-only-password')
    def test_login_tokens_keep_one_identity_and_logout_revokes_only_that_token(self):
        a=accounts.login({'username':'TRAVELER_A','password':'QA-only-password'},'traveler')
        b=accounts.login({'username':'traveler_a','password':'QA-only-password'},'traveler')
        self.assertNotEqual(a,b);self.assertEqual(accounts.resolve(a,'traveler')['owner'],self.owner)
        self.assertEqual(accounts.resolve(b,'traveler')['owner'],self.owner)
        self.assertIsNone(accounts.resolve(a,'staff'));accounts.logout(a)
        self.assertIsNone(accounts.resolve(a,'traveler'));self.assertIsNotNone(accounts.resolve(b,'traveler'))
        with personal.db() as c:
            hashes=[r[0] for r in c.execute('SELECT token_hash FROM account_login_sessions')]
            self.assertNotIn(b,hashes);self.assertIn(hashlib.sha256(b.encode()).hexdigest(),hashes)
    def test_preferences_and_plans_never_cross_accounts(self):
        plan=personal.create_plan(self.source,self.owner,{'preferences':{**personal.defaults(),'required_airlines':['3U','CA'],'excluded_airlines':['9C']},'expected_revision':0})['plan']
        self.assertEqual(personal.state(self.other)['revision'],0)
        with self.assertRaises(ValueError):personal.get_plan(self.other,plan['id'])
        token=accounts.login({'username':'traveler_a','password':'QA-only-password'},'traveler')
        self.assertEqual(personal.state(accounts.resolve(token,'traveler')['owner'])['preferences']['required_airlines'],['3U','CA'])
        real.set_consent(self.owner,{'enabled':True});ident=real.dashboard()['profiles'][0]['user_id']
        self.assertNotIn('traveler_a',json.dumps(real.export_case()))
        self.assertEqual(real.profile(ident)['identity_kind'],'account')
    def test_register_does_not_adopt_anonymous_or_previous_users_data(self):
        _,guest,_=personal.session()
        personal.save_preferences(self.source,guest,{'preferences':{**personal.defaults(),'required_airlines':['MU']}})
        registered=accounts.create_account('new_user','QA-only-password')
        self.assertNotEqual(registered,guest);self.assertEqual(personal.state(registered)['revision'],0)
        self.assertEqual(real.dashboard()['population'],0)
    def test_salted_passwords_validation_and_login_throttle(self):
        with personal.db() as c:
            rows=c.execute('SELECT password_salt,password_hash FROM personal_accounts').fetchall()
            self.assertNotEqual(rows[0]['password_salt'],rows[1]['password_salt'])
            self.assertNotEqual(rows[0]['password_hash'],rows[1]['password_hash'])
        for name,pw in [('ab','long-password'),('invalid name','long-password'),('new_user','short')]:
            with self.assertRaises(ValueError):accounts.create_account(name,pw)
        with self.assertRaises(ValueError):accounts.create_account('TRAVELER_A','long-password')
        with patch.object(accounts,'_failures',{('traveler','traveler_a'):[accounts.time.monotonic()]*8}):
            with self.assertRaisesRegex(ValueError,'尝试次数'):accounts.login({'username':'traveler_a','password':'wrong'},'traveler')
    def test_expired_sessions_cannot_access_account(self):
        token=accounts.issue(self.owner)
        with personal.db() as c:c.execute("UPDATE account_login_sessions SET expires_at='2024-01-01T00:00:00+08:00'")
        self.assertIsNone(accounts.resolve(token,'traveler'))
    def test_two_hundred_isolated_account_profiles_export_without_crossing(self):
        # Seed a clearly isolated cohort; password hash is not used for these fixtures.
        with personal.db() as c:
            for i in range(200):
                owner=f'qa_account_{i:03d}';at=personal.now()
                c.execute('INSERT INTO personal_accounts VALUES(?,?,?,?,?,?,?)',(owner,f'qa_{i:03d}','0'*64,'0'*64,accounts.ITERATIONS,'traveler',at))
                c.execute('INSERT INTO personal_sessions VALUES(?,?,?,?)',(owner,at,1,json.dumps({**personal.defaults(),'required_airlines':['CA' if i%2 else 'MU']})))
                c.execute('INSERT INTO personal_users VALUES(?,?,?,?)',(owner,f'QA_TRAVEL_{i:03d}',at,at))
                c.execute('INSERT INTO real_traveler_consent VALUES(?,?,?,?)',(owner,f'QA_TRAVEL_{i:03d}',1,at))
        data=real.dashboard();self.assertEqual(data['population'],200)
        self.assertEqual({a['code']:a['preferred_users'] for a in data['airline_preferences']},{'CA':100,'MU':100})
        records=real.export_case()['records'];self.assertEqual(len({p['user_id'] for p in records}),200)
        self.assertNotIn('password',json.dumps(records));self.assertNotIn('username',json.dumps(records))


if __name__=='__main__':unittest.main()
