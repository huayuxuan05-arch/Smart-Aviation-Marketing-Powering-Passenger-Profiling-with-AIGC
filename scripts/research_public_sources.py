"""按显式HTTPS代理读取公开页面，保存本地核验缓存，不采集个人资料。"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise urllib.error.HTTPError(request.full_url, code, 'Blocked non-HTTPS redirect', headers, fp)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class PublicHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.hidden = 0
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        if tag in ['script', 'style']:
            self.hidden += 1
        if tag == 'a':
            self.anchor = {'href': dict(attrs).get('href', ''), 'text': ''}
        if tag in ['p', 'div', 'li', 'br', 'h1', 'h2', 'tr']:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ['script', 'style']:
            self.hidden = max(0, self.hidden - 1)
        if tag == 'a' and self.anchor:
            self.links.append(self.anchor)
            self.anchor = None

    def handle_data(self, text):
        if self.hidden:
            return
        self.parts.append(text)
        if self.anchor:
            self.anchor['text'] += text


def fetch_public(url, cache_dir, proxy):
    stamp = datetime.now(timezone.utc).isoformat()
    identifier = hashlib.sha256(url.encode()).hexdigest()[:16]
    base = cache_dir / identifier
    record = {'url': url, 'retrieved_at': stamp, 'proxy_configured': True, 'cache_id': identifier}
    if urllib.parse.urlsplit(url).scheme != 'https':
        return {**record, 'status': 'rejected', 'error': 'Only HTTPS URLs accepted'}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy, 'http': proxy}), HTTPSRedirect())
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (public research)'})
        with opener.open(request, timeout=20) as response:
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise ValueError('Page exceeds 5MB limit')
            record.update(status=response.status, final_url=response.url, content_type=response.headers.get('Content-Type'))
            charset = response.headers.get_content_charset()
        match = re.search(br'charset\s*=\s*["\']?([\w-]+)', raw[:5000], re.I)
        charset = charset or (match.group(1).decode() if match else 'utf-8')
        body = raw.decode(charset, errors='replace')
        parser = PublicHTML()
        parser.feed(body)
        clean = '\n'.join(re.sub(r'\s+', ' ', p).strip() for p in ''.join(parser.parts).splitlines())
        clean = re.sub(r'\n{2,}', '\n', clean).strip()
        record.update(sha256=hashlib.sha256(raw).hexdigest(), charset=charset, text_length=len(clean))
        title = re.search(r'<title[^>]*>(.*?)</title>', body, re.I | re.S)
        record['title'] = title.group(1).strip() if title else ''
        links = [{'url': urllib.parse.urljoin(record['final_url'], link['href']),
                  'text': re.sub(r'\s+', ' ', link['text']).strip()} for link in parser.links]
        base.with_suffix('.html').write_bytes(raw)
        base.with_suffix('.txt').write_text(clean, encoding='utf-8')
        base.with_suffix('.links.json').write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as error:
        # 只记录类型与HTTP状态，不回显可能包含凭据的代理地址。
        record.update(status='failed', error_type=type(error).__name__)
        if isinstance(error, urllib.error.HTTPError):
            record['http_status'] = error.code
    base.with_suffix('.meta.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('urls', nargs='+')
    parser.add_argument('--output', default='output/public-research')
    parser.add_argument('--keywords', nargs='*', default=[])
    args = parser.parse_args()
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if not proxy:
        raise SystemExit('HTTPS_PROXY/https_proxy missing; no direct network fallback')
    cache = Path(args.output)
    cache.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(lambda u: fetch_public(u, cache, proxy), args.urls))
    for record in records:
        if isinstance(record['status'], int):
            links = json.loads((cache / (record['cache_id'] + '.links.json')).read_text(encoding='utf-8'))
            record['matched_links'] = [link for link in links if not args.keywords or any(k in link['text'] for k in args.keywords)][:30]
        print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
