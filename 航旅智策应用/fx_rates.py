"""Verified ECB reference rates; retain provenance privately, never invent rates."""
from datetime import datetime,date
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from pathlib import Path
import json,threading,time,ssl,urllib.request,xml.etree.ElementTree as ET
from data_layer import RUNTIME,CST

SOURCE='https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
_lock=threading.Lock()
_cached=None
_checked=0


def validate(value):
    try:
        day=date.fromisoformat(value['rate_date'])
        rates={k:Decimal(str(v)) for k,v in value['rates'].items()}
    except (KeyError,TypeError,InvalidOperation,ValueError):raise ValueError('汇率数据无效') from None
    if not 0<=(datetime.now(CST).date()-day).days<=7:raise ValueError('汇率日期超出可用范围')
    if 'CNY' not in rates or any(not v.is_finite() or v<=0 for v in rates.values()):raise ValueError('汇率数据无效')
    return value


def snapshot():
    global _cached,_checked
    import flight_quotes
    with _lock:
        if _cached and time.monotonic()-_checked<21600:
            try:return validate(_cached)
            except ValueError:pass
        target=RUNTIME/'exchange-rates'/'ecb.json'
        try:
            saved=validate(json.loads(target.read_text(encoding='utf-8')))
            fetched=datetime.fromisoformat(saved['fetched_at'])
            if 0<=(datetime.now(CST)-fetched).total_seconds()<21600:
                _cached=saved;_checked=time.monotonic();return saved
        except (OSError,ValueError,KeyError,TypeError):pass
        proxy=flight_quotes.configured_proxy()
        context=ssl.create_default_context(cafile=flight_quotes.certificate_bundle())
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':proxy,'https':proxy}),urllib.request.HTTPSHandler(context=context))
        with opener.open(SOURCE,timeout=12) as response:
            raw=response.read(128001)
        if len(raw)>128000:raise ValueError('汇率响应过大')
        root=ET.fromstring(raw)
        rates={e.attrib['currency']:e.attrib['rate'] for e in root.iter() if 'currency' in e.attrib and 'rate' in e.attrib}
        rates['EUR']='1'
        value=validate({'rate_date':next(e.attrib['time'] for e in root.iter() if 'time' in e.attrib),
            'rates':rates,'source':SOURCE,'fetched_at':datetime.now(CST).isoformat()})
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(target)
        _cached=value;_checked=time.monotonic();return value


def convert(amount,currency):
    currency=str(currency or '').upper()
    try:amount=Decimal(str(amount))
    except (InvalidOperation,ValueError):raise ValueError('票价金额无效') from None
    if not amount.is_finite() or amount<=0:raise ValueError('票价金额无效')
    if currency=='CNY':return {'amount_cny':float(amount.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),
        'original_amount':float(amount),'original_currency':currency,'converted':False}
    data=snapshot()
    if currency not in data['rates']:raise ValueError('当前汇率未覆盖该币种')
    rate=Decimal(str(data['rates']['CNY']))/Decimal(str(data['rates'][currency]))
    return {'amount_cny':float((amount*rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),
        'original_amount':float(amount),'original_currency':currency,'converted':True,
        'rate':str(rate),'rate_date':data['rate_date'],'rate_source':data['source']}
