"""Export one detailed dynamic-profile plan per admitted synthetic user."""
from __future__ import annotations
import gzip,json
from collections import Counter
from pathlib import Path
import current_population as population
import independent_cohort as cohort
import flight_quotes as flights
from data_layer import RUNTIME


def export():
    active=json.loads((RUNTIME/'current-cohorts'/'active.json').read_text(encoding='utf-8'))
    root=Path(active['root']);results={}
    for split in ('training','validation','test'):
        cache=population.load(split);counts=Counter()
        path=root/split/'traveler_plans.jsonl.gz'
        with gzip.open(path,'wt',encoding='utf-8') as stream:
            for user in cache['data'][1]:
                plan=population.make_plan(None,user['user_id'])
                if not plan.get('live_flights'):raise ValueError('Reverify current quotations before publishing plan results')
                if len(plan['daily_itinerary'])!=user['days']:raise ValueError('Incomplete itinerary')
                stream.write(json.dumps(plan,ensure_ascii=False)+'\n')
                counts['users']+=1;counts['results']+=1;counts['quoted_results']+=1;counts[plan['budget_status']]+=1
        results[split]=dict(counts,result_coverage=counts['results']/counts['users'],
            quoted_result_coverage_at_export=counts['quoted_results']/counts['users'],
            within_budget_rate=counts['within_budget']/counts['users'],plans_sha256=cohort.digest(path))
        print('DETAILED_PLANS_READY',split,dict(counts),flush=True)
    report=dict(version='current-queryable-budget-preferred-v2',generated_at=flights.now(),splits=results,
        query_conditions=36,conditioned_sampling=True,original_model_retrained=False,
        model_role='frozen original attention model plus dynamic annual features; scenario-cost enumeration and budget-preferred selection',
        attention_score_is_purchase_probability=False,retention='successful observations only',
        interpretation='Coverage is conditional on live-quote admission; neither model accuracy nor unconditional market coverage. Nonflight costs are estimates.')
    cohort.write_json(root/'plan_report.json',report)
    return report


if __name__=='__main__':export()
