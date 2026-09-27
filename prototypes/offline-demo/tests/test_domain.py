import copy
import unittest
from datetime import timedelta

from app.data import AS_OF, synthetic_passengers
from app.domain import TemplateContentProvider, build_profile, contact_decision, recommendations


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.passenger = synthetic_passengers()[1]

    def test_future_and_expired_events_cannot_affect_profile(self):
        baseline = build_profile(self.passenger)
        changed = copy.deepcopy(self.passenger)
        for days in [-1, 31]:
            changed['events'].append({'event_type':'destination_search', 'destination':'不存在的目的地',
                                      'occurred_at':(AS_OF - timedelta(days=days)).isoformat()})
        self.assertEqual(baseline, build_profile(changed))

    def test_recent_signal_weighs_more_than_old_signal(self):
        self.passenger['events'] = [{'event_type':'destination_search', 'destination':'成都', 'occurred_at':AS_OF.isoformat()}]
        recent = build_profile(self.passenger)['intent_score']
        self.passenger['events'][0]['occurred_at'] = (AS_OF - timedelta(days=20)).isoformat()
        self.assertGreater(recent, build_profile(self.passenger)['intent_score'])

    def test_consent_frequency_booking_and_channel_are_hard_gates(self):
        baseline = build_profile(self.passenger)
        self.assertTrue(contact_decision(baseline)['eligible'])
        for update in [{'consent':False}, {'contacts_7d':2}, {'has_booking':True}, {'channels':[]}]:
            with self.subTest(update=update):
                self.assertFalse(contact_decision({**baseline, **update})['eligible'])

    def test_route_matches_origin_and_explains_budget(self):
        profile = build_profile(self.passenger)
        for route in recommendations(profile):
            self.assertEqual(route['origin'], profile['origin'])
            self.assertEqual(route['affordable'], route['fare'] <= profile['budget'])
            self.assertTrue(route['reason'])

    def test_svg_escapes_text_and_content_discloses_template(self):
        profile = build_profile(self.passenger)
        route = recommendations(profile)[0]
        route['destination'] = '<script>bad</script>'
        content = TemplateContentProvider().generate(profile, route)
        self.assertNotIn('<script>', content['visual_svg'])
        self.assertFalse(content['is_aigc'])
        self.assertTrue(content['review_required'])


if __name__ == '__main__':
    unittest.main()
