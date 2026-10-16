"""Local accounts with stable owners, salted passwords and revocable login tokens."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from datetime import timedelta

ITERATIONS=600_000
SESSION_SECONDS=12*60*60
_failures={}
_lock=threading.Lock()


def required():return os.environ.get('AEROLENS_LOGIN_REQUIRED','1')!='0'


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS personal_accounts(
        owner TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_salt TEXT NOT NULL,
        password_hash TEXT NOT NULL,iterations INTEGER NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS account_login_sessions(
        token_hash TEXT PRIMARY KEY,owner TEXT NOT NULL,expires_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS account_session_owner ON account_login_sessions(owner);''')


def clean_name(value):
    if not isinstance(value,str):raise ValueError('请填写账号')
    value=unicodedata.normalize('NFKC',value).strip().casefold()
    if not re.fullmatch(r'[a-z0-9_\-\u3400-\u9fff]{3,32}',value):raise ValueError('账号须为3至32位汉字、字母、数字、下划线或短横线')
    return value


def password_hash(password,salt,iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),iterations).hex()


def create_account(username,password,role='traveler'):
    import personal_app as personal
    username=clean_name(username)
    if not isinstance(password,str) or not 8<=len(password)<=128:raise ValueError('密码须为8至128位')
    if role not in ('traveler','staff'):raise ValueError('账号角色不支持')
    salt=secrets.token_hex(32);digest=password_hash(password,salt);owner=uuid.uuid4().hex+uuid.uuid4().hex
    try:
        with personal.db() as c:
            c.execute('INSERT INTO personal_accounts VALUES(?,?,?,?,?,?,?)',(owner,username,salt,digest,ITERATIONS,role,personal.now()))
            c.execute('INSERT INTO personal_sessions(owner,created_at) VALUES(?,?)',(owner,personal.now()))
            c.execute('INSERT INTO personal_users VALUES(?,?,?,?)',(owner,'TRAVEL_'+uuid.uuid4().hex[:12].upper(),personal.now(),personal.now()))
    except sqlite3.IntegrityError:raise ValueError('该账号已存在，请登录或更换账号') from None
    return owner


def issue(owner):
    import personal_app as personal
    token=secrets.token_hex(32)
    with personal.db() as c:
        c.execute('DELETE FROM account_login_sessions WHERE expires_at<=?',(personal.now(),))
        c.execute('INSERT INTO account_login_sessions VALUES(?,?,?)',
            (hashlib.sha256(token.encode()).hexdigest(),owner,(personal.datetime.now(personal.CST)+timedelta(seconds=SESSION_SECONDS)).isoformat()))
    return token


def resolve(token,role):
    import personal_app as personal
    if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{64}',token):return None
    with personal.db() as c:
        row=c.execute('''SELECT a.owner,a.username,a.role,u.user_id FROM account_login_sessions l
            JOIN personal_accounts a ON a.owner=l.owner JOIN personal_users u ON u.owner=a.owner
            WHERE l.token_hash=? AND l.expires_at>? AND a.role=?''',
            (hashlib.sha256(token.encode()).hexdigest(),personal.now(),role)).fetchone()
        if not row:return None
        c.execute('UPDATE personal_users SET last_seen_at=? WHERE owner=? AND last_seen_at<?',
            (personal.now(),row['owner'],(personal.datetime.now(personal.CST)-timedelta(minutes=5)).isoformat()))
        return dict(row)


def login(body,role):
    import personal_app as personal
    username=clean_name(body.get('username'));password=body.get('password')
    if not isinstance(password,str) or len(password)>128:raise ValueError('账号或密码不正确')
    key=(role,username);clock=time.monotonic()
    with _lock:
        attempts=[t for t in _failures.get(key,[]) if clock-t<300]
        if len(attempts)>=8:raise ValueError('尝试次数过多，请5分钟后重试')
    with personal.db() as c:row=c.execute('SELECT * FROM personal_accounts WHERE username=? AND role=?',(username,role)).fetchone()
    digest=password_hash(password,row['password_salt'] if row else '0'*64,row['iterations'] if row else ITERATIONS)
    if not row or not hmac.compare_digest(digest,row['password_hash']):
        with _lock:
            if len(_failures)>=4096:_failures.pop(next(iter(_failures)))
            _failures.setdefault(key,[]).append(clock)
        raise ValueError('账号或密码不正确')
    with _lock:_failures.pop(key,None)
    return issue(row['owner'])


def logout(token):
    import personal_app as personal
    if not isinstance(token,str):return
    with personal.db() as c:c.execute('DELETE FROM account_login_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))


def ensure_admin():
    """One local operator account; credentials stay in ignored runtime only."""
    import personal_app as personal
    with personal.db() as c:
        if c.execute("SELECT 1 FROM personal_accounts WHERE role='staff'").fetchone():return
    password=secrets.token_urlsafe(18);create_account('marketing_admin',password,'staff')
    target=personal.RUNTIME/'marketing-admin.txt'
    target.write_text('营销管理账号：marketing_admin\n密码：'+password+'\n仅供本站管理人员使用。请勿上传或分享此文件。\n',encoding='utf-8')


if __name__=='__main__':
    ensure_admin()
    print('Local management account is ready; credentials are in runtime/marketing-admin.txt')
