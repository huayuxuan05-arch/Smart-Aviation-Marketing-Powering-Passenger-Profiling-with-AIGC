"""显式选择模板或本地模型；模板模式不探测、不启动、不调用推理服务。"""
import os


def configuration():
    mode = os.environ.get('AEROLENS_GENERATION_MODE', 'template')
    if mode not in ('template', 'local-model'):
        raise ValueError('AEROLENS_GENERATION_MODE 仅支持 template 或 local-model')
    if mode == 'local-model':
        from aigc_config import runtime_configuration
        return {'mode': mode, 'label': runtime_configuration()['label'], 'model_enabled': True,
                'description': '本地大模型生成文案与视觉配方，历史事实独立引用。',
                'visual': '模型选择主题与配色，本地SVG合成',
                'loading': '本地模型正在生成文案与视觉配方，预计数秒至半分钟…'}
    return {'mode': mode, 'label': '本地模板 · 大模型未接入', 'model_enabled': False,
            'description': '按目的地、兴趣与语气填入本地模板，可编辑文案并审核海报。',
            'visual': '规则选择主题与配色，本地SVG合成',
            'loading': '正在按旅客兴趣制作模板文案与矢量海报…'}


def generate(destination, holiday, theme, tone='轻松亲切', variant=1):
    config = configuration()
    if config['model_enabled']:
        from local_generation import generate as local_generate
        return {**local_generate(destination, holiday, theme, tone, variant),
                'generation_mode': 'local-model'}
    from local_generation import risk_flags
    if tone not in ('轻松亲切', '简洁直接', '温暖陪伴'):
        raise ValueError('请选择支持的语气')
    openings = {
        '轻松亲切': (f'{holiday}，给{destination}留一点期待',
                 f'想在{holiday}换个节奏？把{destination}放进旅行备选清单，'),
        '简洁直接': (f'{holiday}旅行备选：{destination}',
                 f'计划{holiday}出发？先比较前往{destination}的航线参考，'),
        '温暖陪伴': (f'一起规划，下一站{destination}',
                 f'{holiday}，和在意的人商量一次前往{destination}的旅行，'),
    }
    focus = {'目的地信息': '从了解目的地方向开始', '景区探索': '为想探索的地点留出时间',
             '酒店体验': '把住宿偏好列进规划清单', '机票比较': '结合出发日期与预算慢慢比较',
             '攻略准备': '把想了解的行程问题逐一列好'}.get(theme, '按自己的兴趣安排旅程')
    title, opening = openings[tone]
    endings = ('。先查看旅游航线参考，再决定适合自己的出发安排。',
               '。给行程留一点余地，了解航线参考后再确定出发安排。')
    text = opening + focus + endings[(int(variant) - 1) % len(endings)]
    palette, art = ('teal', 'coast') if destination in ('三亚', '海口', '厦门', '青岛') else (
        ('teal', 'mountain') if destination in ('昆明', '丽江', '大理', '西宁', '拉萨', '桂林')
        else ('indigo', 'city'))
    return {'title': title, 'text': text, 'palette': palette, 'art': art,
            'engine': config['label'], 'generation_mode': 'template',
            'generation_seconds': 0,
            'prompt': f'本地模板 v1；目的地={destination}；假期={holiday}；兴趣={theme}；语气={tone}；版本={variant}',
            'risk_flags': risk_flags(title + text),
            'visual_mode': config['visual'] + '；非目的地实拍',
            'model_revision': None, 'model_alias': None, 'thinking': False,
            'usage': {}, 'timings': {}}
