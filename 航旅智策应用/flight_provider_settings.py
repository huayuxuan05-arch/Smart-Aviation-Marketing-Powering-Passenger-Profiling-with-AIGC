"""Local flight-source settings; credentials never enter HTTP responses or Git."""
import base64,ctypes,json,os,re
from pathlib import Path
from data_layer import RUNTIME

CONFIG=RUNTIME/'flight-provider'/'serpapi.json'
VERSION='google-route-catalog-v2-serpapi-v1'


def read():
    try:
        raw=CONFIG.read_text(encoding='utf-8-sig')
        if len(raw)>32768:raise ValueError()
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError()
        return value
    except FileNotFoundError:return {}
    except (OSError,ValueError):raise ValueError('本机航班服务配置无效，请重新配置') from None


def settings():
    value=read()
    provider=os.environ.get('AEROLENS_FLIGHT_PROVIDER') or value.get('provider') or ('serpapi' if os.environ.get('SERPAPI_API_KEY') else 'fli')
    if provider not in ('fli','serpapi'):raise ValueError('航班服务配置不支持该数据源')
    currency=str(value.get('currency','JPY')).upper();country=str(value.get('country','jp')).lower();language=str(value.get('language','ja')).lower()
    if not re.fullmatch('[A-Z]{3}',currency) or not re.fullmatch('[a-z]{2}',country) or not re.fullmatch('[a-z]{2}(?:-[a-z]{2})?',language):raise ValueError('航班服务地区或币种配置无效')
    limits={}
    for key,default,ceiling in [('hourly_limit',50,100000),('monthly_limit',250,1000000)]:
        try:limits[key]=int(value.get(key,default))
        except (ValueError,TypeError):raise ValueError('航班服务额度配置无效') from None
        if not 1<=limits[key]<=ceiling:raise ValueError('航班服务额度配置无效')
    return {'provider':provider,'currency':currency,'country':country,'language':language,**limits,
        'key_configured':bool(os.environ.get('SERPAPI_API_KEY') or value.get('api_key_encrypted'))}


class _Blob(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data,encrypt):
    if os.name!='nt':raise ValueError('本机加密密钥仅支持 Windows；其他环境请使用环境变量')
    buffer=ctypes.create_string_buffer(data)
    incoming=_Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));outgoing=_Blob()
    crypt=ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not crypt(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing)):
        raise ValueError('无法读取当前 Windows 用户的航班密钥，请重新配置')
    try:return ctypes.string_at(outgoing.data,outgoing.length)
    finally:ctypes.windll.kernel32.LocalFree(outgoing.data)


def api_key():
    value=os.environ.get('SERPAPI_API_KEY')
    if not value:
        encrypted=read().get('api_key_encrypted')
        if not encrypted:raise ValueError('请先在本机配置 SerpApi 密钥')
        try:value=_crypt(base64.b64decode(encrypted,validate=True),False).decode('utf-8')
        except (ValueError,UnicodeError):raise ValueError('本机航班密钥无法读取，请重新配置') from None
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,256}',value):raise ValueError('SerpApi 密钥格式无效，请重新配置')
    return value


def save_key(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,256}',value.strip()):raise ValueError('密钥格式无效，请复制完整 API Key')
    encrypted=base64.b64encode(_crypt(value.strip().encode(),True)).decode('ascii')
    config=read();config.update(provider='serpapi',api_key_encrypted=encrypted)
    for key,default in [('currency','JPY'),('country','jp'),('language','ja'),('hourly_limit',50),('monthly_limit',250)]:config.setdefault(key,default)
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    temporary=CONFIG.with_suffix('.tmp');temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(CONFIG)
