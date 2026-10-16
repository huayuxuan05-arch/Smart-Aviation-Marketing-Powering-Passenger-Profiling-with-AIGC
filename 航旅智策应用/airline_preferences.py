"""航司别名和确定性约束；所有航段均须符合本人明确选择。"""
import re

AIRLINES = {
    '3U': ('四川航空', '川航', 'Sichuan Airlines'),
    '9C': ('春秋航空', '春秋', 'Spring Airlines'),
    'CA': ('中国国际航空', '中国国航', '国航', 'Air China'),
    'MU': ('中国东方航空', '东方航空', '东航', 'China Eastern'),
    'CZ': ('中国南方航空', '南方航空', '南航', 'China Southern'),
    'HO': ('吉祥航空', '吉祥', 'Juneyao Airlines'),
    'HU': ('海南航空', '海航', 'Hainan Airlines'),
    'MF': ('厦门航空', '厦航', 'XiamenAir'),
    'ZH': ('深圳航空', '深航', 'Shenzhen Airlines'),
    'EU': ('成都航空', '成航', 'Chengdu Airlines'),
    'TV': ('西藏航空', '藏航', 'Tibet Airlines'),
    'PN': ('西部航空', 'West Air'),
    'SC': ('山东航空','山航','Shandong Airlines'),
    'FM': ('上海航空','上航','Shanghai Airlines'),
}
FIELDS = ('required_airlines', 'excluded_airlines')


def normalize(values):
    if values is None or values == '':
        return []
    if not isinstance(values, list) or any(not isinstance(v,str) for v in values):
        raise ValueError('请选择支持的航空公司')
    aliases={alias.casefold():code for code,names in AIRLINES.items() for alias in (code,*names)}
    if any(v.strip().casefold() not in aliases for v in values):raise ValueError('请选择支持的航空公司')
    return sorted({aliases[v.strip().casefold()] for v in values})


def extract(text):
    patch, spans = {}, {}
    for clause in re.split(r'[，,。；;\n]', text):
        hits = []
        for code, aliases in AIRLINES.items():
            pattern = '|'.join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))+r'|(?<![A-Za-z0-9])'+re.escape(code)+r'(?![A-Za-z0-9])'
            hits.extend((m.start(),m.end(),code) for m in re.finditer(pattern,clause,re.I))
        previous_end=0;previous_key=None
        for start,end,code in sorted(hits):
            before=clause[:start]
            if re.search(r'(?:不一定|未必|不是)要\s*$', before):
                previous_key=None;previous_end=end
                continue
            negative = re.search(r'(?:不要|不想(?:坐|选|乘)?|不坐|不乘|不选|不考虑|不接受|排除|拒绝|别(?:选|坐)?)\s*$', before)
            positive = re.search(r'(?:只(?:要|坐|选|乘)|想(?:要|坐|选|乘)|要|换成|换为|改为|改成|指定|选择|坐|乘|选)\s*$', before)
            key='excluded_airlines' if negative else 'required_airlines' if positive else None
            # A coordinated list inherits only the immediately preceding carrier's intent.
            if key is None and previous_key and re.fullmatch(r'\s*(?:和|或|或者|以及|还有|、|/|／|及|与|跟)\s*',clause[previous_end:start]):
                key=previous_key
            previous_key=key;previous_end=end
            if key is None:
                continue
            patch.setdefault(key, []).append(code)
            spans[key] = clause
        if re.search(r'(?:不限航司|航空公司不限|取消航司限制|取消航空公司限制)', clause):
            for key in FIELDS:
                patch[key] = []; spans[key] = clause
    return {k: normalize(v) for k, v in patch.items()}, spans


def segment_code(segment):
    number = str(segment.get('flight_number') or '').replace(' ', '').upper()
    if re.fullmatch(r'[A-Z0-9]{2}\d{2,5}[A-Z]?',number):
        return number[:2]
    supplied=str(segment.get('airline_code') or '').upper()
    if re.fullmatch(r'[A-Z0-9]{2}',supplied):return supplied
    for value in (segment.get('airline_code'), segment.get('airline_zh'), segment.get('airline')):
        value = str(value or '').casefold()
        for code, aliases in AIRLINES.items():
            if value == code.casefold() or any(value == a.casefold() for a in aliases):
                return code
    return None


def matches_leg(leg, constraints):
    required = set(constraints.get('required_airlines') or [])
    excluded = set(constraints.get('excluded_airlines') or [])
    if not required and not excluded:
        return True
    segments = leg.get('segments') or []
    # Identity missing while a carrier restriction is active cannot establish eligibility.
    return bool(segments) and all((code := segment_code(s)) is not None and
        code not in excluded and (not required or code in required) for s in segments)


def matches_option(option, constraints):
    return all(matches_leg(option[leg], constraints) for leg in ('outbound', 'inbound'))
