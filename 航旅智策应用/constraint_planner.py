"""Enumerate feasible quoted flights and scenario costs before preference ranking."""
from __future__ import annotations
import math


def optimize(candidates,preferences,*,allow_alternatives=False):
    """Hard upper bounds stay hard; changed dates/cities/stops require confirmation."""
    air=preferences['one_way_airfare'];total=preferences['adult_trip_budget']
    days=preferences['days'];original_city=preferences['destination'];original_date=preferences['start_date']
    feasible=[];closest=[]
    for candidate in candidates:
        changed=(candidate['destination']!=original_city or candidate['start_date']!=original_date or
                 candidate.get('max_stops',0)>0)
        if changed and not allow_alternatives:continue
        option=candidate['option'];out=option['outbound']['price_cny'];back=option['inbound']['price_cny']
        if not all(math.isfinite(p) and p>0 for p in [out,back]):continue
        # These are declared scenarios, not scraped hotel/restaurant prices.
        for lodging,food,experience,comfort in [(260,160,200,1.0),(180,120,100,.7),(120,90,0,.4)]:
            nonflight=(days-1)*lodging+days*(food+50)+experience
            reserve=round((out+back+nonflight)*.1)
            cost=out+back+nonflight+reserve
            gap=max(0,cost-total['max']);air_gap=max(0,out-air['max'],back-air['max'])
            row={**candidate,'estimated_total':cost,'nonflight_scenario':nonflight,'reserve':reserve,
                'lodging_nightly_scenario':lodging,'food_daily_scenario':food,'activity_scenario':experience,
                'requires_confirmation':changed or comfort<1,'changes':dict(destination=candidate['destination']!=original_city,
                    date=candidate['start_date']!=original_date,connecting=candidate.get('max_stops',0)>0,
                    cost_tier=comfort<1),'total_budget_gap':gap,'one_way_budget_gap':air_gap,
                'within_target_band':out>=air['min'] and back>=air['min'] and cost>=total['min']}
            if gap==0 and air_gap==0:
                # Feasibility is a gate. Preference cannot compensate for a budget violation.
                row['utility']=float(candidate.get('interest_score',0))+.15*comfort+.08*row['within_target_band']-.08*changed-.05*candidate.get('max_stops',0)
                feasible.append(row)
            else:closest.append(row)
    feasible.sort(key=lambda r:(-r['utility'],r['estimated_total']))
    if feasible:
        original=[r for r in feasible if not (r['changes']['destination'] or r['changes']['date'] or r['changes']['connecting'])]
        return dict(status='original_conditions_feasible' if original else 'alternative_requires_confirmation',
            selected=(original or feasible)[0],alternatives=feasible[:3],accepted=False)
    closest.sort(key=lambda r:(r['one_way_budget_gap']+r['total_budget_gap'],r['estimated_total']))
    return dict(status='no_feasible_quote',selected=None,nearest=closest[:3],accepted=False)


def propose_reallocation(candidates,preferences):
    """Nonbinding proposal: preserve total ceiling, explicitly change airfare band."""
    relaxed={**preferences,'one_way_airfare':{**preferences['one_way_airfare'],
        'max':preferences['adult_trip_budget']['max']}}
    result=optimize(candidates,relaxed,allow_alternatives=True)
    proposal=result.get('selected')
    if not proposal:return None
    cap=preferences['one_way_airfare']['max'];option=proposal['option']
    excess=max(0,option['outbound']['price_cny']-cap,option['inbound']['price_cny']-cap)
    if excess<=0:return None
    return {**proposal,'requires_confirmation':True,'accepted':False,
        'status':'airfare_band_reallocation_requires_confirmation',
        'original_one_way_upper':cap,'requested_one_way_upper':max(option['outbound']['price_cny'],option['inbound']['price_cny']),
        'one_way_budget_gap':excess,'total_upper_unchanged':True,
        'changes':{**proposal['changes'],'airfare_target_band':True}}
