"""Prospective itinerary features and hard-constraint-first ranking.

Fare observations have timestamps. These features are ready for future explicit
choice labels, but are not presented as a trained purchase/price prediction model.
"""
from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone
import numpy as np
from constraint_planner import optimize

FEATURES = ['city_attention_score', 'booking_lead_days', 'date_shift_days',
    'airfare_band_width', 'trip_band_width', 'outbound_cap_ratio', 'inbound_cap_ratio',
    'roundtrip_trip_cap_share', 'max_stops', 'outbound_departure_hour',
    'outbound_arrival_hour', 'return_departure_hour', 'return_arrival_hour',
    'outbound_minutes', 'return_minutes', 'quote_age_minutes', 'destination_changed']


def timestamp(value):
    parsed=datetime.fromisoformat(value)
    # The quote feed's segment clocks are China local time; observations include offset.
    return parsed


def itinerary_features(candidate, preferences, observed_asof):
    option=candidate['option']; out=option['outbound']; back=option['inbound']
    prices=[out['price_cny'],back['price_cny']]
    if not all(math.isfinite(p) and p>0 for p in prices): raise ValueError('Invalid quoted fare')
    air=preferences['one_way_airfare']; total=preferences['adult_trip_budget']
    if not (0<=air['min']<=air['max'] and 0<=total['min']<=total['max'] and air['max']>0 and total['max']>0):
        raise ValueError('Invalid budget interval')
    now=timestamp(observed_asof); observed=timestamp(candidate['observed_at'])
    if now.tzinfo is None or observed.tzinfo is None: raise ValueError('Quote clock needs an explicit timezone')
    age=(now-observed).total_seconds()/60
    if age<0: raise ValueError('Future quote cannot be used as a feature')
    travel=timestamp(candidate['start_date']); requested=timestamp(preferences['start_date'])
    lead=(travel.date()-now.astimezone(timezone(timedelta(hours=8))).date()).days
    if lead<0: raise ValueError('Travel date has passed')
    def clocks(leg):
        segments=leg.get('segments',[])
        if not segments: raise ValueError('Quoted flight segments are required')
        start=timestamp(segments[0]['departure_time']); end=timestamp(segments[-1]['arrival_time'])
        duration=(end-start).total_seconds()/60
        if duration<=0: raise ValueError('Invalid flight chronology')
        return start.hour+start.minute/60, end.hour+end.minute/60, duration
    od,oa,om=clocks(out); bd,ba,bm=clocks(back)
    outgoing=out['segments']; incoming=back['segments']
    last_day=travel.date()+timedelta(days=preferences['days']-1)
    if (timestamp(outgoing[0]['departure_time']).date()!=travel.date() or
        timestamp(incoming[0]['departure_time']).date()!=last_day or
        timestamp(outgoing[-1]['arrival_time'])>=timestamp(incoming[0]['departure_time'])):
        raise ValueError('Flight dates do not match the proposed trip')
    return dict(zip(FEATURES,[float(candidate.get('interest_score',0)),lead,
        (travel-requested).days,air['max']-air['min'],total['max']-total['min'],
        prices[0]/air['max'],prices[1]/air['max'],sum(prices)/total['max'],
        candidate.get('max_stops',0),od,oa,bd,ba,om,bm,age,
        int(candidate['destination']!=preferences['destination'])]))


def exploration_state(snapshot, row):
    """Observed uncertainty heuristic, never reads a simulated scenario label."""
    p=snapshot['X'][row,:,1]
    entropy=float(-(p*np.log(np.maximum(p,1e-10))).sum()/np.log(len(p)))
    uncertain=bool(p.max()<.2 and entropy>.65)
    return dict(needs_preference_confirmation=uncertain, observed_entropy_30d=entropy,
        label='广泛探索，推荐城市待确认' if uncertain else '按当前偏好排序',
        probability_of_purchase=None)


def rank(candidates, preferences, observed_asof, *, allow_alternatives=False,
         max_quote_age_minutes=15, max_date_shift_days=3, offline_snapshot=False):
    """No learned score can buy its way through a hard cap or stale live quote."""
    valid=[]; rejected={}; feature_rows=[]
    for candidate in candidates:
        try: shift=abs((timestamp(candidate['start_date'])-timestamp(preferences['start_date'])).days)
        except (KeyError, ValueError, TypeError): shift=0
        if shift>max_date_shift_days:
            rejected['date_outside_permission']=rejected.get('date_outside_permission',0)+1; continue
        try: features=itinerary_features(candidate,preferences,observed_asof)
        except (ValueError, KeyError, TypeError, OverflowError):
            rejected['invalid_quote']=rejected.get('invalid_quote',0)+1; continue
        if features['quote_age_minutes']>=max_quote_age_minutes and not offline_snapshot:
            rejected['stale_quote']=rejected.get('stale_quote',0)+1; continue
        if abs(features['date_shift_days'])>max_date_shift_days:
            rejected['date_outside_permission']=rejected.get('date_outside_permission',0)+1; continue
        valid.append(candidate);feature_rows.append(features)
    result=optimize(valid,preferences,allow_alternatives=allow_alternatives)
    return {**result,'feature_rows':feature_rows,'rejected':rejected,
        'offline_snapshot':offline_snapshot,'requires_quote_refresh_before_use':offline_snapshot,
        'ranking_basis':'explicit constraints, city attention and declared cost scenarios; no trained adoption labels'}
