"""Save only a public HTTPS origin; preserves AI settings. No server publication here."""
import re,sys,os
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
def normalize_url(value):
 try:u=urlsplit(value.strip())
 except ValueError:raise ValueError('Неверный адрес.') from None
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:raise ValueError('Нужен только HTTPS-адрес сервера, без пути, параметров или пароля.')
 try:port=u.port;host=u.hostname.encode('idna').decode().lower()
 except (ValueError,UnicodeError):raise ValueError('Неверный домен или порт.') from None
 if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or host in ('localhost','127.0.0.1') or len(host)>253:raise ValueError('Укажите общий домен HTTPS-сервера, не localhost.')
 return 'https://'+host+(':'+str(port) if port and port!=443 else '')
def save_url(root,value):
 url=normalize_url(value);p=Path(root)/'.env'
 if p.exists() and p.stat().st_size>16384:raise ValueError('Слишком большой .env; настройте адрес вручную.')
 text=p.read_text(encoding='utf-8-sig') if p.exists() else ''
 lines=[l for l in text.splitlines() if not re.match(r'^\s*JANA_PUBLIC_URL\s*=',l)]
 lines.append('JANA_PUBLIC_URL='+url)
 tmp=p.with_name('.env.mobile-tmp');tmp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
 try:os.chmod(tmp,0o600)
 except OSError:pass
 tmp.replace(p);return url
if __name__=='__main__':
 try:
  raw=sys.argv[1] if len(sys.argv)>1 else input('Общий HTTPS-адрес (например https://hr.example.com): ')
  url=save_url(ROOT,raw)
  print('Адрес сохранён:',url,'\nПерезапустите сервер. Ключи и данные не изменены. Это настройка адреса, а не создание хостинга.')
 except (ValueError,OSError,UnicodeError) as e:
  print('Не удалось сохранить адрес. Проверьте HTTPS-домен и доступ к .env.');sys.exit(1)
 except (EOFError,KeyboardInterrupt):print('\nОтменено.');sys.exit(1)
