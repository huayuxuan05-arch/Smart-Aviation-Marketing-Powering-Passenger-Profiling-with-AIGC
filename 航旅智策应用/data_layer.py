"""流式读取原始工作簿，建立可重建的 SQLite 研究索引。"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import zipfile
from lxml import etree as ET

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parent / '数据集'
RUNTIME = BASE / 'runtime'
DB = RUNTIME / 'aviation.sqlite3'
VERSION = 'DAILY_SYN_2024_V2_SUBSET_10K'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
EPOCH = datetime(1899, 12, 30)
CST = timezone(timedelta(hours=8))
SOURCE_HASHES = {
    '01_航班信息.xlsx':'4f82b8901f75e86aaf55d99d367a8cfb41ef69495ee1dba19a35b90578d9b73f',
    '02_用户行为.xlsx':'d894e544ddc47170d00c9fed62675bc2b81992aadb0588a5b447f71c44f66291',
    '03_营销反馈.xlsx':'cde6d737fc174c1f06f8d9adc2459f8b49c1657e487ee053e7471bcc85b71860'
}


def xlsx_tables(path):
    """每次只驻留一个 XML row；不将四百万行载入内存。"""
    with zipfile.ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for _, el in ET.iterparse(z.open('xl/sharedStrings.xml'), events=('end',), tag=NS+'si'):
                strings.append(''.join(el.itertext()))
                el.clear()
                while el.getprevious() is not None:
                    del el.getparent()[0]
        links = {x.get('Id'): x.get('Target') for x in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        book = ET.fromstring(z.read('xl/workbook.xml'))
        for sheet in book.find(NS+'sheets'):
            target = links[sheet.get(REL)]
            target = target.lstrip('/') if target.startswith('/') else 'xl/'+target
            def rows(target=target):
                for _, row in ET.iterparse(z.open(target), events=('end',), tag=NS+'row'):
                    values = []
                    for cell in row:
                        letters = ''.join(c for c in cell.get('r', '') if c.isalpha())
                        col = 0
                        for c in letters:
                            col = col*26+ord(c)-64
                        if not letters:
                            col = len(values)+1
                        while len(values) < col:
                            values.append(None)
                        raw = cell.findtext(NS+'v')
                        kind = cell.get('t')
                        if kind == 'inlineStr':
                            value = ''.join(cell.find(NS+'is').itertext())
                        elif kind == 's':
                            value = strings[int(raw)] if raw else None
                        elif kind in ('str', 'e'):
                            value = raw
                        elif raw is None:
                            value = None
                        else:
                            number = float(raw)
                            value = int(number) if number.is_integer() else number
                        if col:
                            values[col-1] = value
                    yield values
                    row.clear()
                    while row.getprevious() is not None:
                        del row.getparent()[0]
            yield sheet.get('name'), rows()


def convert(name, value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and (name.endswith('_cst') or name in ('behavior_date', 'travel_date', 'offer_departure_date', '出发日')):
        # 原文件精度为整秒；先舍入，避免Excel浮点误差导致时间提前一秒。
        d = EPOCH+timedelta(seconds=round(value*86400))
        return d.strftime('%Y-%m-%d %H:%M:%S') if name.endswith('_cst') else d.strftime('%Y-%m-%d')
    if isinstance(value, (int, float)) and name in ('出发时间', '到达时间'):
        seconds = round(value*86400) % 86400
        return f'{seconds//3600:02}:{seconds//60%60:02}'
    return value


class ClosingConnection(sqlite3.Connection):
    """sqlite的默认with仅提交事务；这里同时释放Windows文件句柄。"""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    c = sqlite3.connect(DB, timeout=60, factory=ClosingConnection)
    c.row_factory = sqlite3.Row
    return c


def build(force=False):
    RUNTIME.mkdir(exist_ok=True)
    if DB.exists() and not force:
        with connect() as c:
            try:
                cached = json.loads(c.execute('SELECT value FROM metadata WHERE key="manifest"').fetchone()[0])
                if cached.get('import_schema') != 3:
                    raise RuntimeError('索引格式已更新，请运行 build_data.py --rebuild')
                for source in cached['files']:
                    stat = (SOURCE/source['name']).stat()
                    if stat.st_size!=source['size'] or stat.st_mtime_ns!=source.get('mtime_ns'):
                        raise RuntimeError('原始数据已变更，请重新检查并执行 build_data.py --rebuild')
                return cached
            except (sqlite3.Error, TypeError):
                raise RuntimeError('本地索引未完成，请执行 build_data.py --rebuild')
    temp = RUNTIME / 'aviation.building.sqlite3'
    if temp.exists():
        temp.unlink()
    c = sqlite3.connect(temp)
    c.execute('PRAGMA journal_mode=OFF')
    c.execute('PRAGMA synchronous=OFF')
    c.execute('PRAGMA temp_store=MEMORY')
    manifest = {'version': VERSION, 'import_schema':3, 'created_at': datetime.now(CST).isoformat(timespec='seconds'), 'files': [], 'counts': {}, 'tables': {}, 'delay_provenance': '仅用于已核对SHA256的当前指南版本：1—5分钟为随机填补；后续版本须重新核验来源清单'}
    sources = [('01_航班信息.xlsx', lambda n: 'flights' if n=='航班明细' else None),
               ('02_用户行为.xlsx', lambda n: 'users' if n=='模拟用户' else 'behaviors' if n.startswith('每日行为_') else 'objects' if n=='浏览对象' else None),
               ('03_营销反馈.xlsx', lambda n: 'pushes' if n.startswith('模拟触达_') else 'events' if n.startswith('模拟反馈事件_') else 'orders' if n=='模拟订单' else 'templates' if n=='模拟素材' else None)]
    for filename, select in sources:
        path = SOURCE / filename
        digest = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
        if digest != SOURCE_HASHES[filename]:
            raise ValueError(filename+'指纹与实施指南版本不一致，请先重新核验数据契约和误点填补来源')
        manifest['files'].append({'name': filename, 'sha256': digest, 'size': path.stat().st_size, 'mtime_ns':path.stat().st_mtime_ns})
        for sheet, rows in xlsx_tables(path):
            table = select(sheet)
            if not table:
                continue
            headers = next(rows)
            if table not in manifest['counts']:
                columns = ','.join('"'+h+'"' for h in headers)
                c.execute(f'CREATE TABLE {table} ({columns})')
                manifest['counts'][table] = 0
                manifest['tables'][table] = headers
            elif headers != manifest['tables'][table]:
                raise ValueError('跨表字段不一致：'+sheet)
            sql = f'INSERT INTO {table} VALUES ({",".join("?" for _ in headers)})'
            batch = []
            count = 0
            for row in rows:
                row += [None]*(len(headers)-len(row))
                batch.append(tuple(convert(h, v) for h, v in zip(headers, row)))
                count += 1
                if len(batch) == 5000:
                    c.executemany(sql, batch)
                    batch.clear()
            if batch:
                c.executemany(sql, batch)
            c.commit()
            manifest['counts'][table] += count
            print(f'{sheet}: {count:,} 行', flush=True)
    expected = {'flights':365677, 'users':10000, 'behaviors':3970000, 'objects':451, 'pushes':120000, 'events':222591, 'orders':248, 'templates':82}
    if manifest['counts'] != expected:
        raise ValueError(f'数据规模与指南不一致：{manifest["counts"]}')
    for table,key in [('users','user_id'),('behaviors','record_id'),('pushes','push_id'),('events','feedback_id'),('orders','order_id')]:
        if c.execute(f'SELECT COUNT(*) FROM {table} WHERE {key} IS NULL').fetchone()[0]:
            raise ValueError(table+'存在空标识，索引构建停止')
    if c.execute('SELECT COUNT(DISTINCT behavior_date) FROM behaviors').fetchone()[0] !=397:
        raise ValueError('行为日期覆盖不完整')
    for sql in [
        'CREATE UNIQUE INDEX user_key ON users(user_id)',
        'CREATE UNIQUE INDEX behavior_key ON behaviors(record_id)',
        'CREATE INDEX behavior_user_time ON behaviors(user_id, search_at_cst)',
        'CREATE INDEX flight_match ON flights(出发日, 出发城市, 到达城市)',
        'CREATE INDEX push_user ON pushes(user_id,sent_at_cst)',
        'CREATE UNIQUE INDEX push_key ON pushes(push_id)',
        'CREATE INDEX event_user ON events(user_id,event_time_cst)',
        'CREATE INDEX event_push ON events(push_id,event_time_cst)',
        'CREATE INDEX order_user ON orders(user_id)',
        'CREATE UNIQUE INDEX object_key ON objects(object_id)']:
        c.execute(sql)
    c.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('INSERT INTO metadata VALUES (?,?)', ('manifest',json.dumps(manifest,ensure_ascii=False)))
    c.commit()
    c.close()
    temp.replace(DB)
    (RUNTIME/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('本地全量索引构建完成',flush=True)
    return manifest
