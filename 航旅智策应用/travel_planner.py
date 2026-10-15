"""全量旅客的可编辑旅行建议；航班引用原始样本，日期与联程状态单独说明。"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import math
import threading

from data_layer import DB
import marketing_ml as ml
import decision_logic as decision

_LOCK = threading.RLock()
_NETWORK = None
_CONTEXTS = {}
_AUDITS = {}
HUBS = ['北京', '上海', '广州', '成都', '西安', '昆明', '重庆', '武汉', '杭州', '南京']
GATEWAYS = {'苏州': ['上海', '无锡', '南京']}

# 地点为规划候选；开放、预约、班次、商户与价格均不据此推断。
PLACES = {
 '三亚': ['椰梦长廊','鹿回头','亚龙湾','天涯海角'],
 '上海': ['外滩','豫园','上海博物馆','武康路'],
 '丽江': ['丽江古城','黑龙潭','束河古镇','白沙古镇'],
 '乌鲁木齐': ['新疆维吾尔自治区博物馆','红山公园','新疆国际大巴扎','人民公园'],
 '兰州': ['甘肃省博物馆','黄河风情线','白塔山公园','兰州水车博览园'],
 '北京': ['天坛','故宫','颐和园','北京中轴线街区'],
 '南京': ['南京博物院','夫子庙秦淮风光带','玄武湖','明孝陵'],
 '南宁': ['青秀山','广西民族博物馆','三街两巷','南湖公园'],
 '南昌': ['滕王阁','江西省博物馆','八一广场','绳金塔街区'],
 '厦门': ['中山路','鼓浪屿','环岛路','厦门园林植物园'],
 '合肥': ['安徽博物院','逍遥津公园','包公园','淮河路步行街'],
 '呼和浩特': ['大召','内蒙古博物院','塞上老街','五塔寺'],
 '哈尔滨': ['中央大街','圣索菲亚教堂建筑艺术广场','太阳岛','松花江畔'],
 '大连': ['星海广场','滨海路','大连自然博物馆','东港'],
 '天津': ['五大道','古文化街','天津博物馆','海河沿岸'],
 '太原': ['山西博物院','晋祠','双塔寺','柳巷'],
 '广州': ['陈家祠','越秀公园','广东省博物馆','沙面'],
 '张家界': ['张家界国家森林公园','天门山','溪布街','武陵源'],
 '成都': ['人民公园','武侯祠','杜甫草堂','宽窄巷子'],
 '拉萨': ['八廓街','罗布林卡','西藏博物馆','布达拉宫'],
 '昆明': ['翠湖','云南省博物馆','滇池海埂','昆明老街'],
 '杭州': ['西湖','中国茶叶博物馆','龙井村','清河坊'],
 '桂林': ['两江四湖','象鼻山','靖江王城','东西巷'],
 '武汉': ['湖北省博物馆','东湖','黄鹤楼','江汉路'],
 '沈阳': ['沈阳故宫','辽宁省博物馆','北陵公园','中街'],
 '济南': ['大明湖','趵突泉','山东博物馆','曲水亭街'],
 '海口': ['骑楼老街','海南省博物馆','万绿园','假日海滩'],
 '深圳': ['莲花山公园','深圳博物馆','深圳湾公园','南头古城'],
 '石家庄': ['河北博物院','正定古城','隆兴寺','滹沱河沿岸'],
 '福州': ['三坊七巷','福建博物院','西湖公园','烟台山'],
 '苏州': ['平江路','拙政园','苏州博物馆','山塘街'],
 '西双版纳': ['曼听公园','西双版纳热带植物园','景洪江边','告庄西双景'],
 '西宁': ['青海省博物馆','东关清真大寺','人民公园','莫家街'],
 '西安': ['西安城墙','陕西历史博物馆','大雁塔','大唐不夜城'],
 '贵阳': ['甲秀楼','贵州省博物馆','黔灵山公园','青岩古镇'],
 '郑州': ['河南博物院','郑州商都国家考古遗址公园','二七广场','郑州黄河文化公园'],
 '重庆': ['解放碑','中国三峡博物馆','山城巷','南滨路'],
 '银川': ['宁夏博物馆','银川文化园','西夏陵','览山公园'],
 '长春': ['吉林省博物院','净月潭','长春世界雕塑园','南湖公园'],
 '长沙': ['湖南博物院','岳麓山','橘子洲','太平老街'],
 '青岛': ['栈桥','八大关','青岛市博物馆','五四广场'],
}
SOURCES = {
 '北京': [('北京旅游网官方资源库','https://s.visitbeijing.com.cn/attractions?star_rating=5&theme=2')],
 '上海': [('上海文旅推广网 豫园','https://www.meet-in-shanghai.net/cn/huangpu-district/yu-garden-480016/')],
 '杭州': [('杭州文旅旅游指南','https://wgly.hangzhou.gov.cn/attach/538/2307051510367229.pdf')],
 '苏州': [('苏州园林局 拙政园','https://ylj.suzhou.gov.cn/szsylj/sjyc/201905/c1df393edc8745abb20e8a9bd5525782.shtml'),('苏州市政府 平江街区','https://www.suzhou.gov.cn/gsbdbwlyjc/yshi/202008/12875852fc0845afa5534cc7b29c5b19.shtml')],
 '西安': [('西安市文旅局景区目录','https://wlj.xa.gov.cn/wlml/lyjq/1.html')],
}


def _parse_day(value):
    return datetime.strptime(str(value), '%Y-%m-%d').date()


class FlightNetwork:
    def __init__(self, source):
        self.edges = defaultdict(list)
        self.outgoing = defaultdict(set)
        self.incoming = defaultdict(set)
        self._best = {}
        last = None
        sql = 'SELECT rowid AS source_row,* FROM flights WHERE 机票票价>0 ORDER BY 出发城市,到达城市,出发日,机票票价,rowid'
        for record in source.execute(sql):
            flight = dict(record)
            key = (flight['出发城市'], flight['到达城市'], flight['出发日'])
            if key == last:
                continue
            last = key
            flight['candidate_id'] = 'FLIGHT_ROW_' + str(flight['source_row'] + 1)
            flight['_day'] = _parse_day(flight['出发日']).toordinal()
            self.edges[key[:2]].append(flight)
            self.outgoing[key[0]].add(key[1])
            self.incoming[key[1]].add(key[0])

    def quote(self, origin, destination, target):
        key = (origin, destination, target)
        if key not in self._best:
            ordinal = _parse_day(target).toordinal()
            values = self.edges.get((origin, destination), [])
            self._best[key] = min(values, key=lambda f: (abs(f['_day'] - ordinal), f['机票票价'], f['source_row'])) if values else None
        result = self._best[key]
        return {k: v for k, v in result.items() if k != '_day'} if result else None

    def route(self, origin, destination, target):
        airports = GATEWAYS.get(destination, [destination])
        possible = []
        for gateway in airports:
            if gateway == origin:
                continue
            direct = self.quote(origin, gateway, target)
            if direct:
                possible.append(self.describe([direct], destination, gateway, target))
                continue
            hubs = self.outgoing.get(origin, set()) & self.incoming.get(gateway, set())
            hubs = sorted(hubs, key=lambda city: (city not in HUBS, HUBS.index(city) if city in HUBS else 99, city))[:20]
            for hub in hubs:
                first = self.quote(origin, hub, target)
                second = self.quote(hub, gateway, target)
                if first and second:
                    possible.append(self.describe([first, second], destination, gateway, target))
        return min(possible, key=lambda option: (not option['exact_date'], len(option['flights']), option['date_gap'], option['reference_fare'])) if possible else None

    @staticmethod
    def describe(flights, destination, gateway, target):
        exact = len(flights) == 1 and flights[0]['出发日'] == target
        return {'flights': flights, 'gateway': gateway, 'destination': destination,
                'kind': '直飞历史候选' if len(flights) == 1 else '两段航线网络参考',
                'exact_date': exact, 'target_date': target,
                'date_gap': max(abs((_parse_day(f['出发日']) - _parse_day(target)).days) for f in flights),
                'reference_fare': round(sum(float(f['机票票价']) for f in flights), 2),
                'ground_transfer': f'{gateway}机场至苏州的地面接驳建议，需另查铁路或公路班次和费用' if destination != gateway else None,
                'status': '目标日期有历史直飞记录' if exact else '使用其他日期历史记录作航线参考' if len(flights) == 1 else '两段历史航线存在，日期、机场和衔接尚未核验',
                'bookable': False}


def network(source):
    global _NETWORK
    databases = source.execute('PRAGMA database_list').fetchall()
    file = next((row[2] for row in databases if row[1] == 'main'), '')
    if not file:
        return FlightNetwork(source)
    stat = Path(file).stat()
    key = (file, stat.st_size, stat.st_mtime_ns)
    with _LOCK:
        if _NETWORK is None or _NETWORK[0] != key:
            _NETWORK = (key, FlightNetwork(source))
        return _NETWORK[1]


def options(raw=None):
    raw = raw or {}
    holiday = next((h for h in ml.HOLIDAYS if h['id'] == raw.get('holiday', 'national')), None)
    if not holiday:
        raise ValueError('请选择支持的假期')
    asof = raw.get('asof') or max('2023-12-31', (_parse_day(holiday['start']) - timedelta(days=1)).isoformat())
    _parse_day(asof)
    if not '2023-12-31' <= asof <= '2024-12-24':
        raise ValueError('动态画像截点须位于2023-12-31至2024-12-24')
    days = int(raw.get('days', 3))
    if days not in (3, 4, 5, 7):
        raise ValueError('请选择3、4、5或7天行程')
    pace = raw.get('pace', '跟随画像')
    if pace not in ('跟随画像', '轻松', '均衡', '充实'):
        raise ValueError('行程节奏不支持')
    total = float(raw['trip_budget']) if raw.get('trip_budget') not in (None, '') else None
    if total is not None and (not math.isfinite(total) or not 100 <= total <= 100000):
        raise ValueError('每名成人全程预算须为100至100000元')
    date = raw.get('start_date') or None
    if date:
        _parse_day(date)
        if date <= asof:
            raise ValueError('规划出发日期须晚于画像截点')
    return {'holiday': holiday, 'asof': asof, 'days': days, 'pace': pace, 'trip_budget': total, 'start_date': date}


def context(raw=None):
    config = options(raw)
    key = (config['asof'], config['holiday']['id'])
    with _LOCK:
        if key not in _CONTEXTS:
            arrays, users, objects, destinations = ml.load_data()
            # Planning uses the same decision-time score as the marketing workspace.
            import marketing_app
            snapshot = marketing_app.trained_snapshot(config['asof'])
            _CONTEXTS.clear()
            _CONTEXTS[key] = (arrays, users, destinations, snapshot, {u['user_id']: i for i, u in enumerate(users)})
        return config, _CONTEXTS[key]


def make_plan(source, user_id, raw=None, compact=False):
    config, (arrays, users, destinations, snapshot, lookup) = context(raw)
    if user_id not in lookup:
        raise ValueError('旅客不存在')
    index = lookup[user_id]
    user = users[index]
    origin = user['usual_departure_city']
    ranked = sorted(range(len(destinations)), key=lambda j: (-float(snapshot['scores'][index, j]), j))
    observed = [j for j in ranked if snapshot['count'][60][index, j] > 0]
    requested = destinations[observed[0] if observed else ranked[0]]
    candidates = [j for j in observed if destinations[j] != origin and not (destinations[j] == '苏州' and origin in ('上海', '南京'))][:3]
    if not candidates:
        candidates = [j for j in ranked if destinations[j] != origin][:3]
    routes = network(source)
    selected = None
    alternatives = []
    for j in candidates:
        intent = decision.trip_intent(arrays, index, j, config['asof'], config['holiday'])
        date = config['start_date'] or intent['travel_date']
        if config['start_date'] and config['start_date'] != intent['travel_date']:
            intent = {**intent, 'budget': None, 'budget_status': 'reference' if intent['budget_reference'] is not None else 'unknown', 'budget_basis': '规划日期已调整，原查询预算仅供参考'}
        route = routes.route(origin, destinations[j], date)
        if route:
            value = {'j': j, 'intent': intent, 'date': date, 'route': route}
            alternatives.append(value)
            if selected is None:
                selected = value
    if selected is None:
        for destination in ['成都', '西安', '厦门', '北京', '杭州', '三亚']:
            if destination == origin or destination not in destinations:
                continue
            j = destinations.index(destination)
            intent = decision.trip_intent(arrays, index, j, config['asof'], config['holiday'])
            date = config['start_date'] or intent['travel_date']
            if config['start_date'] and config['start_date'] != intent['travel_date']:
                intent = {**intent, 'budget': None, 'budget_status': 'reference' if intent['budget_reference'] is not None else 'unknown', 'budget_basis': '规划日期已调整，原查询预算仅供参考'}
            route = routes.route(origin, destination, date)
            if route:
                selected = {'j': j, 'intent': intent, 'date': date, 'route': route}
                alternatives.append(selected)
                break
    if selected is None:
        raise ValueError('该出发城市缺少航线网络数据，需补充数据后规划')
    j, intent, start, outbound = selected['j'], selected['intent'], selected['date'], selected['route']
    destination = destinations[j]
    theme_index = int(snapshot['cluster'][index, :5].argmax())
    themes = ['城市初访', '自然与景区', '舒适休闲', '交通与预算', '文化与攻略']
    party = user.get('travel_party', '独行')
    pace = config['pace'] if config['pace'] != '跟随画像' else '轻松' if party in ('亲子', '长者同行') or theme_index == 2 else '均衡'
    end = (_parse_day(start) + timedelta(days=config['days'] - 1)).isoformat()
    return_route = routes.route(outbound['gateway'], origin, end)
    # Avoid pretending that ground access or independently sampled legs are a verified itinerary.
    reason = '保留近期关注首选目的地' if destination == requested else f'原关注方向为{requested}，展示可达备选{destination}；需旅客确认'
    if requested == origin:
        reason = f'原关注目的地与出发地均为{origin}，本方案提出异地备选{destination}；也可选择本地游'
    airfare_cap = intent['budget']
    excess = max(0, outbound['reference_fare'] - airfare_cap) if airfare_cap is not None else None
    summary = {'user_id': user_id, 'origin': origin, 'destination': destination, 'requested_destination': requested,
               'start_date': start, 'end_date': end, 'days': config['days'], 'party': party, 'theme': themes[theme_index],
               'pace': pace, 'score': round(float(snapshot['scores'][index, j]), 4),
               'flight_kind': outbound['kind'], 'flight_date_exact': outbound['exact_date'],
               'flight_reference_fare': outbound['reference_fare'], 'flight_numbers': [f['航班号'] for f in outbound['flights']],
               'route_available': True, 'date_basis': '用户调整的规划日期' if config['start_date'] else intent['date_basis'],
               'selection_reason': reason, 'budget_excess': excess, 'has_return_reference': bool(return_route),
               'asof': config['asof'], 'bookable': False, 'plan_version': 'personal-trip-v1'}
    if compact:
        return summary
    priorities = [f'依据近7天关注{round(float(snapshot["X"][index,j,0])*100,1)}%及近60天关注{round(float(snapshot["X"][index,j,2])*100,1)}%选择方向；分数不代表购票概率。',
                  f'同行方式为{party}，采用{pace}节奏和{themes[theme_index]}主题。',
                  '同次机票预算已作为差额检查依据。' if airfare_cap is not None else '本次机票预算尚未明确，历史参考不代替旅客确认。']
    alternative_plans = [{'destination': destinations[x['j']], 'target_date': x['date'],
                'reference_fare': x['route']['reference_fare'], 'kind': x['route']['kind'], 'status': x['route']['status']} for x in alternatives[1:]]
    return compose_plan(summary, intent, outbound, return_route, theme_index, config, priorities, alternative_plans)


def compose_plan(summary, intent, outbound, return_route, theme_index, config, priorities, alternative_plans):
    origin, destination, start = summary['origin'], summary['destination'], summary['start_date']
    party, pace = summary['party'], summary['pace']
    airfare_cap, excess = intent['budget'], summary['budget_excess']
    themes = ['城市初访', '自然与景区', '舒适休闲', '交通与预算', '文化与攻略']
    points = PLACES[destination]
    if theme_index == 1:
        points = points[2:] + points[:2]
    elif theme_index == 4:
        points = points[1:3] + [points[0], points[3]]
    selected=config.get('preferred_attractions',[])
    if selected:
        points=list(dict.fromkeys(selected+points))
    if destination == '拉萨':
        pace = '轻松'
        summary['pace'] = pace
    lodging = 240 if theme_index == 3 else 360 if theme_index == 2 else 300
    nights = config['days'] - 1
    if config['trip_budget'] is not None and return_route and config.get('adjust_lodging',True):
        fixed = outbound['reference_fare'] + return_route['reference_fare'] + config['days'] * 160 + (200 if pace == '轻松' else 300)
        lodging = max(120, min(600, int((config['trip_budget'] / 1.1 - fixed) / nights / 10) * 10))
    costs = [
        {'name': '去程航空', 'value': outbound['reference_fare'], 'basis': '原始历史样本合计，非当前报价'},
        {'name': '返程航空', 'value': return_route['reference_fare'] if return_route else None, 'basis': '原始历史样本合计' if return_route else '尚缺返程参考'},
        {'name': '住宿', 'value': nights * lodging, 'basis': f'情景假设每晚每名成人{lodging}元，{nights}晚'+('；按所填总预算调整，非商户报价' if config['trip_budget'] is not None and config.get('adjust_lodging',True) else '；非商户报价')},
        {'name': '餐饮', 'value': config['days'] * 100, 'basis': '情景假设每名成人每天100元'},
        {'name': '市内交通', 'value': config['days'] * 60, 'basis': '情景假设每天60元，跨城接驳另核验'},
        {'name': '景点与体验预留', 'value': 200 if pace == '轻松' else 300, 'basis': '预算预留，不是门票报价'},
    ]
    subtotal = sum(c['value'] or 0 for c in costs)
    reserve = round(subtotal * .1)
    costs.append({'name': '机动预留', 'value': reserve, 'basis': '以上可估部分的10%情景预留'})
    estimate = subtotal + reserve if return_route else None
    budget = {'components': costs, 'estimated_total': estimate, 'specified_total': config['trip_budget'],
              'difference': round(estimate - config['trip_budget'], 2) if estimate is not None and config['trip_budget'] is not None else None,
              'one_way_airfare_cap': airfare_cap, 'flight_budget_basis': intent['budget_basis'],
              'basis': '按一名成人测算，同行人数未知；历史票价、住宿餐饮情景与真实报价分开。查询上限只指机票，不代表全程总预算。'}
    daily = []
    for day in range(config['days']):
        date = (_parse_day(start) + timedelta(days=day)).isoformat()
        if day == 0:
            blocks = [
                {'time': '到达前', 'activity': '核对去程航班与行李规则', 'detail': '按目标日期重查航班；历史记录日期不同或两段航线时，先核实可售及衔接，再安排地面活动。'},
                {'time': '到达后', 'activity': '机场接驳与入住', 'detail': outbound['ground_transfer'] or f'前往{destination}住宿点；首日优先放下行李并确认返程交通。'},
                {'time': '傍晚可选', 'activity': points[0] + '轻松游览', 'detail': '仅在实际到达时间允许时安排，步行与休息交替，不把晚到航班排成完整游览日。'},
                {'time': '晚间', 'activity': '晚餐与次日准备', 'detail': '在住宿附近选择餐饮，核对次日预约、开放信息及交通，保留休息时间。'},
            ]
            title = '抵达与轻松熟悉目的地'
        elif day == config['days'] - 1:
            blocks = [
                {'time': '早餐后', 'activity': '整理行李与退房', 'detail': '先确认返程日期、机场及接驳，行李寄存条件需向住宿方确认。'},
                {'time': '返程前可选', 'activity': '住宿附近漫游或休息', 'detail': '有充足时间再安排，优先同一片区活动；早班返程直接取消游览。'},
                {'time': '起飞前', 'activity': '前往返程机场', 'detail': '按实际航司办理时限和当日路况预留时间，跨城接驳单独核验。'},
                {'time': '返程', 'activity': '返回' + origin, 'detail': '核对返程候选、跨日到达、转机和行李要求，未完成订票前保留替代方案。'},
            ]
            title = '从容收尾与返程'
        else:
            remaining = points[1:]
            first = remaining[(day-1)*2] if (day-1)*2<len(remaining) else ['城市街区与文化细节探索','当地饮食与生活体验','自由活动与休息'][(day-3)%3]
            second = remaining[(day-1)*2+1] if (day-1)*2+1<len(remaining) else '根据体力选择住宿周边活动或休息'
            blocks = [
                {'time': '09:30—12:00' if pace == '轻松' else '09:00—12:00', 'activity': first, 'detail': '建议先核对预约与开放；以本片区为主，避免把排队和交通时间挤出行程。'},
                {'time': '12:00—14:00', 'activity': '午餐与休息', 'detail': '亲子或长者同行保留较长休息段；其他客群可按体力调整。' if party in ('亲子','长者同行') else '在上一活动周边用餐，留出休息与下一段交通时间。'},
                {'time': '14:00—17:00', 'activity': second if pace != '轻松' else second + '或休息二选一', 'detail': '具体行进顺序按住宿位置和当天交通调整；轻松节奏每天至多一个主要景点。'},
                {'time': '晚间可选', 'activity': '城市街区与当地餐饮体验', 'detail': '优先住宿周边短程活动；朋友、情侣可增加夜间漫游，亲子和长者优先早点休息。'},
            ]
            title = themes[theme_index] + '主题体验'
        daily.append({'day': day + 1, 'date': date, 'title': title, 'blocks': blocks})
    checks = ['确认本次日期、同行人数与全程预算', '按目标日期核验去程和返程可售航班、税费与行李',
              '核验景点开放、预约和实际票价', '确认住宿区域、房型及取消条件', '按航班时刻与住宿位置调整逐日交通']
    if len(outbound['flights']) > 1:
        checks.insert(2, '两段航线仅表示网络可达，必须核验同日或跨日衔接、机场与联程保障')
    if excess:
        checks.insert(0, f'去程历史参考高于同次机票上限{excess:.0f}元，比较备选方向或调整预算')
    return {**summary, 'intent': intent, 'personalization': priorities, 'outbound': outbound, 'return_route': return_route,
            'daily_itinerary': daily, 'lodging': {'area': f'优先{destination}核心游览区域或公共交通便利片区，按最终景点顺序选址',
                'type': '重视电梯、隔音与便利接驳，优先少换住宿点' if party == '长者同行' else '重视家庭空间、午休和周边餐饮，少换住宿点' if party == '亲子' else '交通便利，比较总价与取消条件',
                'nights': nights, 'status': '区域与条件建议，未推荐已核验商户或房型'},
            'budget': budget, 'alternatives': alternative_plans,
            'checklist': checks, 'sources': [{'title': title, 'url': url} for title,url in SOURCES.get(destination, [])],
            'backup_options': [
                {'name':'节省预算','advice':'优先压缩付费体验与住宿情景费用，保留交通和机动预留；若机票已超过总预算，应比较备选日期或方向。'},
                {'name':'减少体力消耗','advice':f'每天只保留一个主要地点，优先{points[0]}所在片区，其余时段留作休息，少换住宿点。'},
                {'name':'预约未成功或不宜户外','advice':'将无法成行的活动改为住宿周边漫游或已核验开放的室内文化场所，先确认预约再调整顺序。'},
            ],
            'place_status': '地点候选；列出的参考资料只支持相应地点背景，未逐点核验全部开放、预约和票价。',
            'basis': '旅行建议由动态行为、原始航线网络、同行方式和规划参数组合；历史日期保持原值，旅游活动时间与非机票费用为可调整建议。'}


def list_plans(source, raw=None):
    raw = raw or {}
    config, (_, users, _, _, _) = context(raw)
    query = str(raw.get('q', '')).strip().lower()
    page = max(1, int(raw.get('page', 1)))
    size = min(50, max(1, int(raw.get('page_size', 20))))
    matched = [u for u in users if not query or any(query in str(u.get(key, '')).lower() for key in ('user_id','residence_city','residence_province','usual_departure_city','travel_party'))]
    selected = matched[(page-1)*size:page*size]
    return {'population': len(users), 'total': len(matched), 'page': page, 'page_size': size,
            'items': [make_plan(source, u['user_id'], raw, compact=True) for u in selected],
            'settings': {**config, 'holiday': config['holiday']['id']},
            'coverage': full_population_audit(source, raw),
            'coverage_scope': '全量旅客均可请求规划，不受营销名单人数与退订条件限制；航线网络参考与目标日期历史直飞分别标记。'}


def full_population_audit(source, raw=None):
    config, (_, users, _, _, _) = context(raw)
    key = (id(network(source)), config['asof'], config['holiday']['id'], config['days'], config['start_date'])
    with _LOCK:
        if key in _AUDITS:
            return _AUDITS[key]
        counts = Counter()
        failures = []
        for user in users:
            try:
                plan = make_plan(source, user['user_id'], raw, compact=True)
                counts['planned'] += 1
                counts['with_flight_reference'] += int(plan['route_available'])
                counts['exact_date_direct'] += int(plan['flight_date_exact'])
                counts['with_return_reference'] += int(plan['has_return_reference'])
                counts['preferred_destination_retained'] += int(plan['requested_destination'] == plan['destination'])
            except ValueError as error:
                failures.append({'user_id': user['user_id'], 'reason': str(error)})
        result = {'population': len(users), **counts, 'failed': len(failures), 'failures': failures,
                  'scope': '全量旅客逐人生成；有航线参考不等于目标日期可售，其他日期和未验证两段衔接均单独说明',
                  'asof': config['asof'], 'days': config['days']}
        _AUDITS.clear()
        _AUDITS[key] = result
        return result
