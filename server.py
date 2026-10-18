"""JanaМен: local hackathon MVP. Python 3.10+, standard library only."""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import urllib.request
import urllib.parse
import time
import mimetypes
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
# Plain KEY=value only; never execute configuration as Python/shell.
def load_local_env():
    f=ROOT/'.env'
    if f.exists():
        for line in f.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            key,value=line.split('=',1)
            if key.strip().startswith('JANA_') and not key.strip().startswith(('JANA_AI_','JANA_ANYMODEL_','JANA_GROQ_')): os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
load_local_env()

DB = Path(os.environ.get('JANA_DB', str(ROOT / 'data' / 'jana.sqlite3')))
SESSIONS = {}
LOCK = threading.Lock()
STATUSES = {'submitted': 'На согласовании', 'approved': 'Согласована руководителем', 'completed': 'Обработана HR', 'rejected': 'Отклонена', 'withdrawn': 'Отозвана'}
TTL = 8 * 60 * 60

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def password_hash(value, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

def password_check(value, saved):
    return hmac.compare_digest(password_hash(value, saved.split(':')[0]), saved)

def notify(db, user_id, title, text, kind='request', target_id=None):
    db.execute('INSERT INTO notifications(user_id,title,body,kind,created_at,target_id) VALUES(?,?,?,?,?,?)', (user_id,title,text,kind,now(),target_id))

def audit(db, uid, action, entity):
    db.execute('INSERT INTO audit(actor_id,action,entity,created_at) VALUES(?,?,?,?)', (uid,action,str(entity),now()))

def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
          name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('employee','manager','hr')), company TEXT NOT NULL,
          position TEXT NOT NULL, department TEXT NOT NULL, manager_id INTEGER REFERENCES users(id), hire_date TEXT, vacation_days INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL DEFAULT 'vacation',
          start_date TEXT NOT NULL, end_date TEXT NOT NULL, comment TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES requests(id), actor_id INTEGER NOT NULL REFERENCES users(id),
          status TEXT NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,duration INTEGER NOT NULL,content TEXT NOT NULL,questions TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assignments(user_id INTEGER REFERENCES users(id), course_id INTEGER REFERENCES courses(id), lesson_done INTEGER NOT NULL DEFAULT 0,
          score INTEGER, completed INTEGER NOT NULL DEFAULT 0, assigned_at TEXT NOT NULL, PRIMARY KEY(user_id,course_id));
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,body TEXT NOT NULL,
          kind TEXT NOT NULL,is_read INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS knowledge(id INTEGER PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,keywords TEXT NOT NULL,audience TEXT NOT NULL DEFAULT 'all');
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor_id INTEGER REFERENCES users(id),action TEXT,entity TEXT,created_at TEXT);
        ''')
        columns={r['name'] for r in db.execute('PRAGMA table_info(notifications)')}
        if 'target_id' not in columns: db.execute('ALTER TABLE notifications ADD COLUMN target_id INTEGER')
        db.executescript("""
        CREATE TABLE IF NOT EXISTS assistant_feedback(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),source_ids TEXT NOT NULL,helpful INTEGER NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ai_usage(day TEXT PRIMARY KEY,calls INTEGER NOT NULL DEFAULT 0);
        """)
        if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            return
        pw = secrets.token_urlsafe(12)
        pwh = password_hash(pw)
        users = [
            (1,'employee@demo.local','Алия Демо','employee','Специалист по логистике','Операционный отдел',2,24),
            (2,'manager@demo.local','Тимур Демо','manager','Руководитель отдела','Операционный отдел',None,21),
            (3,'hr@demo.local','Дана Демо','hr','HR-специалист','HR',None,18),
            (4,'other@demo.local','Арман Тест','employee','Специалист','Другой отдел',None,20)]
        for uid,email,name,role,position,department,manager,days in users:
            # Deferred ordering: manager foreign key is added after every user exists.
            db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,email,pwh,name,role,'Jana Post · демо',position,department,None,'2025-03-10',days))
        db.execute('UPDATE users SET manager_id=2 WHERE id=1')
        lesson1 = [
            {'title':'Одно пространство для HR','text':'Это учебный курс демонстрационной платформы, а не официальный регламент Jana Post. В профиле находятся кадровые данные, заявки, обучение и уведомления.'},
            {'title':'Как подать заявку','text':'Откройте «Мои заявки», выберите даты и отправьте заявку на отпуск. В демонстрационном процессе руководитель согласовывает её, затем HR завершает обработку. Следите за историей и уведомлениями.'},
            {'title':'Безопасность данных','text':'Не передавайте пароль другим людям. Кадровые данные доступны только для чтения. Не вводите реальные персональные данные в учебную среду. Если помощник не находит источник, обратитесь в HR.'}]
        q1 = [
            {'text':'Где отслеживать решение по отпуску?','options':['В истории заявки и уведомлениях','Только в общем чате','В каталоге курсов'],'correct':0},
            {'text':'Можно ли изменить должность в профиле самостоятельно?','options':['Да, всегда','Нет, кадровые поля доступны только для чтения','Только ночью'],'correct':1},
            {'text':'Что делать, если у помощника нет источника?','options':['Считать любой ответ правилом компании','Запросить чужие данные','Обратиться в HR'],'correct':2}]
        lesson2 = [
            {'title':'Доступ по роли','text':'В этой демонстрации сотрудник работает только со своими данными. Руководитель рассматривает заявки своей команды. Проверка прав выполняется на сервере.'},
            {'title':'Секреты и подозрительные ссылки','text':'Не храните токены в репозитории, не сообщайте пароли в переписке. Подозрительное сообщение нужно передать ответственному специалисту, а не открывать вложение.'}]
        q2 = [{'text':'Где должны проверяться права доступа?','options':['Только в меню','На сервере','Нигде'],'correct':1},
              {'text':'Можно ли публиковать API-ключ в репозитории?','options':['Нет','Да'],'correct':0}]
        db.execute('INSERT INTO courses VALUES(1,?,?,?,?,?)',('Добро пожаловать в JanaМен','Первый день: профиль, заявки и безопасная работа',8,json.dumps(lesson1,ensure_ascii=False),json.dumps(q1,ensure_ascii=False)))
        db.execute('INSERT INTO courses VALUES(2,?,?,?,?,?)',('Цифровая безопасность','Данные, доступ и ответственное использование AI',5,json.dumps(lesson2,ensure_ascii=False),json.dumps(q2,ensure_ascii=False)))
        for uid in (1,2,3,4):
            db.execute('INSERT INTO assignments(user_id,course_id,assigned_at) VALUES(?,1,?)',(uid,now()))
            notify(db,uid,'Вам назначен курс','«Добро пожаловать в JanaМен» уже доступен в Academy.','learning',1)
        knowledge = [
            ('Как оформить отпуск','Учебный порядок: откройте «Мои заявки», нажмите «Новая заявка», укажите даты и отправьте. Руководитель рассматривает заявку, затем HR завершает обработку. Это демонстрационный процесс, не утверждённый регламент компании.','отпуск,заявк,оформ,подать,каникул,демалыс','all'),
            ('Статусы и уведомления','В демоверсии есть статусы: «На согласовании», «Согласована руководителем», «Обработана HR», «Отклонена». Изменения видны в истории заявки и центре уведомлений. Согласование руководителем ещё не означает завершение обработки HR.','статус,уведомлен,истори,согласован','all'),
            ('Кадровые данные в профиле','В демоверсии должность, подразделение, руководитель и остаток отпуска доступны только для чтения. Если данные неверны, обратитесь в HR. Автоматическое списание остатка отпуска не реализовано; источником официальных данных в будущем будет 1С:ЗУП.','профил,должност,остаток,данные,изменить,руководител','all'),
            ('Обучение в Jana Academy','Откройте назначенный курс, изучите материал, отметьте его прочитанным и пройдите тест. Для завершения требуется не менее 67% правильных ответов. Результат и прогресс сохраняются. Это условия учебного прототипа.','курс,обучен,academy,академ,тест,прогресс,оқу','all'),
            ('Рассмотрение заявок командой','В демоверсии руководитель видит заявки только прямых подчинённых. Он может согласовать или отклонить заявку на согласовании. Для отклонения необходим комментарий.','согласова,команд,подчинён,отклон','manager'),
            ('Обработка HR','В демоверсии HR завершает обработку после согласования руководителем либо отклоняет заявку с комментарием. Юридически значимые документы не создаются, связь с Documentolog смоделирована.','обработ,documentolog,кадров,документ','hr')]
        db.executemany('INSERT INTO knowledge(title,body,keywords,audience) VALUES(?,?,?,?)',knowledge)
        today = dt.date.today()
        for uid,offset,status in [(1,20,'submitted'),(1,45,'completed'),(4,30,'submitted')]:
            start=today+dt.timedelta(days=offset)
            cur=db.execute('INSERT INTO requests(user_id,start_date,end_date,comment,status,created_at) VALUES(?,?,?,?,?,?)',(uid,str(start),str(start+dt.timedelta(days=4)),'Демонстрационная заявка',status,now()))
            rid=cur.lastrowid
            db.execute('INSERT INTO history(request_id,actor_id,status,comment,created_at) VALUES(?,?,?,?,?)',(rid,uid,'submitted','Заявка создана',now()))
            if status=='completed':
                for actor,st in [(2,'approved'),(3,'completed')]:
                    db.execute('INSERT INTO history(request_id,actor_id,status,comment,created_at) VALUES(?,?,?,?,?)',(rid,actor,st,'Демонстрационная история',now()))
        cred=DB.parent/'DEMO-ACCOUNTS.txt'
        cred.write_text('Только синтетические локальные аккаунты. Не используйте этот пароль где-либо ещё.\n\n'+ '\n'.join(f'{u[1]}  /  {pw}' for u in users[:3])+'\n',encoding='utf-8')
        try: cred.chmod(0o600)
        except OSError: pass
        print(f'Тестовые учётные записи: {cred}',flush=True)

class AppError(Exception):
    def __init__(self, status, message): self.status,self.message=status,message

def require(condition, status=400, message='Некорректный запрос'):
    if not condition: raise AppError(status,message)

def public_user(db,u):
    data={k:u[k] for k in ('id','email','name','role','company','position','department','manager_id','hire_date','vacation_days','must_change','delegate_id')}
    m=db.execute('SELECT name FROM users WHERE id=?',(u['manager_id'],)).fetchone()
    data['manager_name']=m['name'] if m else 'Не назначен'
    return data

def can_read_request(db,u,r):
    if r['user_id']==u['id'] or u['role']=='hr': return True
    owner=db.execute('SELECT manager_id FROM users WHERE id=?',(r['user_id'],)).fetchone()
    return u['role']=='manager' and (owner['manager_id']==u['id'] or bool(db.execute('SELECT 1 FROM users WHERE id=? AND delegate_id=? AND active=1',(owner['manager_id'],u['id'])).fetchone()))

def request_view(db,r):
    out=dict(r)
    out['name']=db.execute('SELECT name FROM users WHERE id=?',(r['user_id'],)).fetchone()['name']
    out['status_label']=STATUSES[r['status']]
    out['history']=[dict(x) for x in db.execute('SELECT h.status,h.comment,h.created_at,u.name AS actor FROM history h JOIN users u ON u.id=h.actor_id WHERE request_id=? ORDER BY h.id',(r['id'],))]
    return out

class Handler(BaseHTTPRequestHandler):
    server_version='JanaMen/1.4-iPhone'
    def log_message(self, fmt, *args):
        print('%s %s' % (now(), fmt%args),flush=True)
    def send_json(self,data,status=200, extra=None):
        b=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(b)))
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(b)
    def headers_common(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    def public_origin(self):
        value=os.environ.get('JANA_PUBLIC_URL','').rstrip('/')
        if not value: return ''
        u=urllib.parse.urlsplit(value)
        require(u.scheme=='https' and bool(u.hostname) and not u.username and not u.password and u.path in ('','/') and not u.query and not u.fragment,500,'Некорректный JANA_PUBLIC_URL')
        return value
    def session(self):
        jar=cookies.SimpleCookie()
        try: jar.load(self.headers.get('Cookie',''))
        except cookies.CookieError: return None,None
        token=jar.get('jana_session')
        token=token.value if token else ''
        with LOCK:
            s=SESSIONS.get(token)
            if s and s['expires']<dt.datetime.now().timestamp():
                SESSIONS.pop(token,None);s=None
        return token,s
    def body(self):
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: raise AppError(400,'Некорректная длина запроса')
        require(0<length<=(2900000 if urllib.parse.urlsplit(self.path).path=='/api/file/upload' else 64000),413,'Некорректный размер запроса')
        require(self.headers.get('Content-Type','').split(';')[0]=='application/json',415,'Ожидается JSON')
        try: data=json.loads(self.rfile.read(length))
        except (ValueError,UnicodeError): raise AppError(400,'Некорректный JSON')
        require(isinstance(data,dict))
        return data
    def do_GET(self): self.handle_request(False)
    def do_POST(self): self.handle_request(True)
    def handle_request(self,post):
        try:
            host=self.headers.get('Host','').split(':')[0].lower()
            public=self.public_origin()
            allowed={'127.0.0.1','localhost'}
            if public: allowed.add(urllib.parse.urlsplit(public).hostname)
            require(host in allowed,403,'Адрес не разрешён. Настройте JANA_PUBLIC_URL на сервере.')
            path=urllib.parse.urlsplit(self.path).path
            if not path.startswith('/api/'):
                require(not post,405)
                relative='index.html' if path=='/' else path.lstrip('/')
                f=(ROOT/'static'/relative).resolve()
                require(f.is_relative_to((ROOT/'static').resolve()) and f.is_file() and f.suffix in ('.html','.js','.css','.svg','.png','.webmanifest','.mp4','.vtt','.json'),404,'Страница не найдена')
                size=f.stat().st_size;start=0;end=size-1;partial=False
                rg=self.headers.get('Range','')
                if rg and f.suffix=='.mp4':
                    import re
                    match=re.fullmatch(r'bytes=(\d*)-(\d*)',rg)
                    require(match is not None,416,'Неверный диапазон')
                    a,b=match.groups()
                    if a: start=int(a);end=min(int(b) if b else end,end)
                    else: start=max(0,size-int(b))
                    require(0<=start<=end<size,416,'Диапазон недоступен');partial=True
                self.send_response(206 if partial else 200);self.headers_common()
                mime={'.js':'application/javascript','.webmanifest':'application/manifest+json','.vtt':'text/vtt','.svg':'image/svg+xml'}.get(f.suffix,mimetypes.guess_type(str(f))[0] or 'application/octet-stream')
                self.send_header('Content-Type',mime+('; charset=utf-8' if f.suffix in ('.html','.js','.css','.vtt','.webmanifest','.json') else ''))
                if f.suffix=='.mp4': self.send_header('Accept-Ranges','bytes')
                if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.send_header('Content-Length',str(end-start+1));self.end_headers()
                with f.open('rb') as source:
                    source.seek(start);remaining=end-start+1
                    while remaining:
                        chunk=source.read(min(65536,remaining))
                        if not chunk: break
                        self.wfile.write(chunk);remaining-=len(chunk)
                return
            data=self.body() if post else {}
            if post:
                origin=self.headers.get('Origin')
                require(not origin or origin in ({public} if public else {f'http://{self.headers.get("Host")}'}),403,'Запрос с другого сайта запрещён')
            with connect() as db:
                if path=='/api/login' and post:
                    require(isinstance(data.get('email'),str) and isinstance(data.get('password'),str))
                    key=self.client_address[0]
                    stamp=dt.datetime.now().timestamp()
                    with LOCK:
                        recent=[v for v in self.server.login_attempts.get(key,[]) if stamp-v<60]
                        require(len(recent)<15,429,'Слишком много попыток. Подождите минуту.')
                        recent.append(stamp);self.server.login_attempts[key]=recent
                    user=db.execute('SELECT * FROM users WHERE email=?',(data['email'].strip().lower(),)).fetchone()
                    valid=password_check(data['password'],user['password'] if user else self.server.dummy_hash)
                    require(user is not None and valid and user['active'],401,'Неверная почта или пароль')
                    old,_=self.session()
                    with LOCK: SESSIONS.pop(old,None)
                    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
                    with LOCK:
                        SESSIONS[token]={'uid':user['id'],'csrf':csrf,'expires':stamp+TTL}
                    audit(db,user['id'],'login','session')
                    self.send_json({'user':public_user(db,user),'csrf':csrf},extra={'Set-Cookie':f'jana_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={TTL}'+('; Secure' if public else '')})
                    return
                token,s=self.session()
                require(s is not None,401,'Войдите в платформу')
                user=db.execute('SELECT * FROM users WHERE id=?',(s['uid'],)).fetchone()
                require(user is not None and user['active'],401)
                if post: require(hmac.compare_digest(self.headers.get('X-CSRF-Token',''),s['csrf']),403,'Обновите страницу и повторите действие')
                if post and user['must_change']: require(path in ('/api/password/change','/api/logout'),403,'Сначала смените временный пароль')
                if path=='/api/file/download' and not post:
                    fid=int(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('id',['0'])[0])
                    f=db.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
                    require(f is not None and platform_service.visible_file(db,user,f),404,'Файл не найден')
                    self.send_response(200);self.headers_common();self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+urllib.parse.quote(f['name']));self.send_header('Content-Length',str(len(f['data'])));self.end_headers();self.wfile.write(f['data']);return
                out=self.api(db,user,s,path,data,post)
            self.send_json(out)
        except AppError as e: self.send_json({'error':e.message},e.status)
        except sqlite3.OperationalError: self.send_json({'error':'Данные обновляются. Повторите действие через несколько секунд.'},409)
        except sqlite3.IntegrityError: self.send_json({'error':'Конфликт данных: проверьте почту и связанные записи'},409)
        except (TypeError,ValueError,KeyError): self.send_json({'error':'Некорректные поля запроса'},400)
        except Exception:
            import traceback;traceback.print_exc()
            self.send_json({'error':'Внутренняя ошибка. Подробности в терминале сервера.'},500)
    def api(self,db,u,s,path,d,post):
        uid=u['id']
        def revoke(target,all_sessions):
            token,_=self.session()
            with LOCK:
                for key in list(SESSIONS):
                    if SESSIONS[key]['uid']==target and (all_sessions or key!=token): SESSIONS.pop(key,None)
        extra=platform_service.endpoint(db,u,path,d,post,dict(require=require,notify=notify,audit=audit,now=now,password_check=password_check,password_hash=password_hash,revoke=revoke,can_read_request=can_read_request,STATUSES=STATUSES))
        if extra is not None:return extra
        if path=='/api/me' and not post: return {'user':public_user(db,u),'csrf':s['csrf'],'assistant_mode':assistant_service.provider_mode(),'ai_status':ai_config.public_settings()}
        if path=='/api/snapshot' and not post:
            platform_service.reminders(db,u,dict(notify=notify))
            rows=[request_view(db,r) for r in db.execute('SELECT * FROM requests ORDER BY id DESC') if can_read_request(db,u,r)]
            courses=self.api(db,u,s,'/api/courses',{},False)['courses']
            notifications=self.api(db,u,s,'/api/notifications',{},False)['notifications']
            result={'requests':rows,'courses':courses,'notifications':notifications,'user':public_user(db,u)}
            result['extra']=platform_service.snapshot(db,u)
            result['revision']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
            return result
        if path=='/api/assistant/feedback' and post:
            ids=d.get('source_ids',[]);helpful=d.get('helpful')
            require(type(helpful) is bool and isinstance(ids,list) and len(ids)<=3)
            available={r['id'] for r in db.execute("SELECT id FROM knowledge WHERE audience='all' OR audience=?",(u['role'],))}
            require(all(type(x) is int and x in available for x in ids),403,'Источник недоступен')
            db.execute('INSERT INTO assistant_feedback(user_id,source_ids,helpful,created_at) VALUES(?,?,?,?)',(uid,json.dumps(ids),int(helpful),now()))
            return {'ok':True}
        if path=='/api/logout'  and post:
            token,_=self.session()
            with LOCK: SESSIONS.pop(token,None)
            return {'ok':True}
        if path=='/api/requests' and not post:
            rows=db.execute('SELECT * FROM requests ORDER BY id DESC').fetchall()
            return {'requests':[request_view(db,r) for r in rows if can_read_request(db,u,r)]}
        if path=='/api/request' and post:
            start=dt.date.fromisoformat(str(d.get('start','')));end=dt.date.fromisoformat(str(d.get('end','')))
            require(start>=dt.date.today(),400,'Дата начала не может быть в прошлом')
            require(end>=start,400,'Дата окончания раньше даты начала')
            days=(end-start).days+1
            require(days<=u['vacation_days'],400,'В демоверсии длительность не может превышать показанный остаток отпуска')
            comment=str(d.get('comment','')).strip()
            require(len(comment)<=1000,400,'Комментарий: максимум 1000 символов')
            overlap=db.execute("SELECT id FROM requests WHERE user_id=? AND status IN ('submitted','approved','completed') AND start_date<=? AND end_date>=?",(uid,str(end),str(start))).fetchone()
            require(not overlap,409,'Эти даты пересекаются с существующей заявкой')
            cur=db.execute('INSERT INTO requests(user_id,start_date,end_date,comment,status,created_at) VALUES(?,?,?,?,?,?)',(uid,str(start),str(end),comment,'submitted',now()))
            rid=cur.lastrowid
            db.execute('INSERT INTO history(request_id,actor_id,status,comment,created_at) VALUES(?,?,?,?,?)',(rid,uid,'submitted','Заявка создана',now()))
            notify(db,uid,'Заявка отправлена',f'Заявка №{rid} ожидает согласования.',target_id=rid)
            if u['manager_id']: notify(db,u['manager_id'],'Новая заявка команды',f'{u["name"]}: заявка №{rid}.',target_id=rid)
            audit(db,uid,'request.create',rid)
            return {'request':request_view(db,db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone())}
        if path=='/api/request/action' and post:
            rid=int(d.get('id',0));action=d.get('action');comment=str(d.get('comment','')).strip()
            require(len(comment)<=1000,400,'Слишком длинный комментарий')
            r=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
            require(r is not None and can_read_request(db,u,r),404,'Заявка не найдена')
            require(r['user_id']!=uid,403,'Нельзя обрабатывать собственную заявку')
            owner=db.execute('SELECT * FROM users WHERE id=?',(r['user_id'],)).fetchone()
            if u['role']=='manager':
                require(can_read_request(db,u,r),403,'Только заявки своей команды')
                require(r['status']=='submitted' and action in ('approved','rejected'),409,'Этот переход статуса недоступен')
            elif u['role']=='hr':
                require((r['status']=='approved' and action in ('completed','rejected')) or (r['status']=='submitted' and action=='rejected'),409,'Сначала требуется согласование руководителя')
            else: raise AppError(403,'Недостаточно прав')
            require(action!='rejected' or bool(comment),400,'Укажите причину отклонения')
            cur=db.execute('UPDATE requests SET status=? WHERE id=? AND status=?',(action,rid,r['status']))
            require(cur.rowcount==1,409,'Статус уже изменён. Обновите список.')
            db.execute('INSERT INTO history(request_id,actor_id,status,comment,created_at) VALUES(?,?,?,?,?)',(rid,uid,action,comment or STATUSES[action],now()))
            notify(db,r['user_id'],'Статус заявки изменён',f'№{rid}: {STATUSES[action]}',target_id=rid)
            if action=='approved':
                for hr in db.execute("SELECT id FROM users WHERE role='hr'"):
                    notify(db,hr['id'],'Заявка готова к обработке',f'№{rid}: согласована руководителем.',target_id=rid)
            audit(db,uid,'request.'+action,rid)
            return {'ok':True}
        if path=='/api/notifications' and not post:
            return {'notifications':[dict(r) for r in db.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC',(uid,))]}
        if path=='/api/notifications/read' and post:
            db.execute('UPDATE notifications SET is_read=1 WHERE user_id=?',(uid,));return {'ok':True}
        if path=='/api/courses' and not post:
            rows=db.execute('SELECT c.id,c.title,c.description,c.duration,a.lesson_done,a.score,a.completed FROM courses c LEFT JOIN assignments a ON a.course_id=c.id AND a.user_id=? ORDER BY c.id',(uid,))
            return {'courses':[dict(r) for r in rows]}
        if path=='/api/course' and post:
            cid=int(d.get('id',0))
            c=db.execute('SELECT * FROM courses WHERE id=?',(cid,)).fetchone()
            a=db.execute('SELECT * FROM assignments WHERE user_id=? AND course_id=?',(uid,cid)).fetchone()
            require(c is not None and a is not None,404,'Курс не назначен')
            result=dict(c);result['content']=json.loads(c['content'])
            result['questions']=[{'text':q['text'],'options':q['options']} for q in json.loads(c['questions'])]
            result['assignment']=dict(a);return result
        if path=='/api/course/progress' and post:
            cid=int(d.get('id',0))
            require(db.execute('SELECT 1 FROM assignments WHERE user_id=? AND course_id=?',(uid,cid)).fetchone() is not None,404,'Курс не назначен')
            db.execute('UPDATE assignments SET lesson_done=1 WHERE user_id=? AND course_id=?',(uid,cid))
            return {'ok':True}
        if path=='/api/course/submit' and post:
            cid=int(d.get('id',0));answers=d.get('answers')
            a=db.execute('SELECT * FROM assignments WHERE user_id=? AND course_id=?',(uid,cid)).fetchone()
            require(a is not None,404,'Курс не назначен');require(a['lesson_done'],409,'Сначала изучите материал')
            c=db.execute('SELECT * FROM courses WHERE id=?',(cid,)).fetchone();qs=json.loads(c['questions'])
            require(isinstance(answers,list) and len(answers)==len(qs) and all(type(x) is int and 0<=x<len(q['options']) for x,q in zip(answers,qs)),400,'Ответьте на все вопросы')
            score=round(sum(x==q['correct'] for x,q in zip(answers,qs))*100/len(qs));passed=int(score>=67)
            db.execute('INSERT INTO quiz_attempts(user_id,course_id,score,created_at) VALUES(?,?,?,?)',(uid,cid,score,now()))
            best=max(a['score'] or 0,score);completed=max(a['completed'],passed)
            db.execute('UPDATE assignments SET score=?,completed=? WHERE user_id=? AND course_id=?',(best,completed,uid,cid))
            if passed and not a['completed']:
                notify(db,uid,'Курс завершён',f'«{c["title"]}»: результат {score}%.','learning',cid)
                audit(db,uid,'course.complete',cid)
            return {'score':score,'passed':bool(passed),'best_score':best}
        if path=='/api/team' and not post:
            require(u['role'] in ('manager','hr'),403,'Недостаточно прав')
            rows=db.execute('SELECT u.* FROM users u LEFT JOIN users m ON u.manager_id=m.id WHERE u.manager_id=? OR (m.delegate_id=? AND m.active=1)',(uid,uid)) if u['role']=='manager' else db.execute('SELECT * FROM users ORDER BY id')
            return {'users':[public_user(db,x) for x in rows]}
        if path=='/api/course/assign' and post:
            require(u['role']=='hr',403,'Только HR назначает обучение')
            target=int(d.get('user_id',0));cid=int(d.get('course_id',0))
            require(db.execute('SELECT 1 FROM users WHERE id=?',(target,)).fetchone() is not None,404,'Сотрудник не найден')
            course=db.execute('SELECT title FROM courses WHERE id=?',(cid,)).fetchone()
            require(course is not None,404,'Курс не найден')
            cur=db.execute('INSERT OR IGNORE INTO assignments(user_id,course_id,assigned_at) VALUES(?,?,?)',(target,cid,now()))
            require(cur.rowcount==1,409,'Этот курс уже назначен')
            notify(db,target,'Вам назначен курс',course['title'],'learning',cid);audit(db,uid,'course.assign',f'{target}:{cid}')
            return {'ok':True}
        if path=='/api/knowledge' and not post:
            return {'documents':[dict(r) for r in db.execute("SELECT id,title,body,keywords,audience,version,updated_at FROM knowledge WHERE audience='all' OR audience=? OR ?='hr' ORDER BY id",(u['role'],u['role']))]}
        if path=='/api/ai/status' and not post:
            config=ai_config.public_settings();day=dt.datetime.now(dt.timezone.utc).date().isoformat()
            usage=db.execute('SELECT calls FROM ai_usage WHERE day=?',(day,)).fetchone()
            last=db.execute('SELECT mode,error_code,elapsed_ms,created_at FROM ai_events WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
            return dict(config,build='1.4-iPhone',attempts_today=usage[0] if usage else 0,last_result=dict(last) if last else None)
        if path=='/api/assistant' and post:
            q=d.get('question','')
            require(isinstance(q,str),400,'Вопрос должен быть текстом');q=q.strip()
            require(2<=len(q)<=1000,400,'Введите вопрос от 2 до 1000 символов')
            request_key=d.get('client_id') or secrets.token_hex(16)
            import re
            require(isinstance(request_key,str) and re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',request_key),400,'Неверный идентификатор запроса')
            fingerprint=hashlib.sha256(json.dumps([q,d.get('thread_id'),d.get('lang','ru')],ensure_ascii=False).encode()).hexdigest()
            previous=db.execute('SELECT * FROM ai_turns WHERE user_id=? AND request_key=?',(uid,request_key)).fetchone()
            if previous:
                require(previous['question_hash']==fingerprint,409,'Этот идентификатор уже использован для другого вопроса')
                if previous['status']=='done':
                    cached=json.loads(previous['response'])
                    for source in cached.get('sources',[]):
                        fresh=db.execute("SELECT version FROM knowledge WHERE id=? AND (audience='all' OR audience=?)",(source['id'],u['role'])).fetchone()
                        if not fresh or cached.get('source_versions',{}).get(str(source['id']))!=fresh[0]:
                            return {'answer':'Источник изменён или больше недоступен. Задайте вопрос заново.','sources':[],'actions':[],'mode':'no_answer','error_code':'source_changed','thread_id':previous['thread_id']}
                    return cached
                raise AppError(409,'Этот вопрос уже обрабатывается. Подождите и откройте историю диалога; повторный API-вызов не выполнен.')
            with LOCK:
                stamp=time.time();recent=[x for x in self.server.ai_attempts.get(uid,[]) if stamp-x<60]
                require(len(recent)<8,429,'Не более 8 вопросов в минуту. Подождите немного.')
                self.server.ai_attempts[uid]=recent+[stamp]
            docs=[dict(r) for r in db.execute("SELECT * FROM knowledge WHERE audience='all' OR audience=?",(u['role'],))]
            own=[request_view(db,r) for r in db.execute('SELECT * FROM requests WHERE user_id=? ORDER BY id DESC',(uid,))]
            tid=int(d.get('thread_id') or 0)
            if tid:require(db.execute('SELECT 1 FROM chat_threads WHERE id=? AND user_id=?',(tid,uid)).fetchone(),404,'Диалог недоступен')
            else:tid=db.execute('INSERT INTO chat_threads(user_id,title,created_at) VALUES(?,?,?)',(uid,q[:80],now())).lastrowid
            context=q
            chat_history=assistant_service.conversation_history(db,tid,u['role']) if ai_config.settings().get('chat_mode')=='chat' else None
            if ai_config.settings().get('chat_mode')=='grounded' and q.lower().strip(' ?.!') in ('а дальше','подробнее','что потом','затем','more details','what next','а как это сделать','как это сделать','а где это','а где','объясни подробнее','расскажи подробнее','а можно подробнее'):
                prev=db.execute("SELECT body FROM chat_messages WHERE thread_id=? AND role='user' ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
                if prev:context=prev[0]+' — '+q
            db.execute('INSERT INTO ai_turns(user_id,request_key,question_hash,thread_id,status,created_at) VALUES(?,?,?,?,?,?)',(uid,request_key,fingerprint,tid,'pending',time.time()))
            db.commit() # Release SQLite writer lock BEFORE the external API call.
            started=time.monotonic()
            out=assistant_service.answer(db,context,docs,own,dict(u),str(d.get('lang','ru')),history=chat_history)
            # Permissions may change during the provider wait. Never return revoked/stale sources.
            current=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            require(current and current['active'] and self.session()[1] is not None,401,'Сеанс завершён. Войдите снова.')
            require(db.execute('SELECT 1 FROM chat_threads WHERE id=? AND user_id=?',(tid,uid)).fetchone(),409,'Диалог был удалён во время обработки')
            versions={}
            for source in out.get('sources',[]):
                original=next((x for x in docs if x['id']==source['id']),None)
                fresh=db.execute("SELECT version FROM knowledge WHERE id=? AND (audience='all' OR audience=?)",(source['id'],current['role'])).fetchone()
                if not original or not fresh or fresh[0]!=original['version']:
                    out={'answer':'Источник изменён или доступ отозван во время ответа. Задайте вопрос заново.','sources':[],'actions':[],'mode':'no_answer','error_code':'source_changed'};versions={};break
                versions[str(source['id'])]=fresh[0]
            out['source_versions']=versions;out['thread_id']=tid;out['request_id']=request_key;out['provider_config']=ai_config.public_settings()
            db.execute('INSERT INTO chat_messages(thread_id,role,body,created_at) VALUES(?,?,?,?)',(tid,'user',q,now()))
            db.execute('INSERT INTO chat_messages(thread_id,role,body,payload,created_at) VALUES(?,?,?,?,?)',(tid,'assistant',out['answer'],json.dumps(out,ensure_ascii=False),now()))
            db.execute('INSERT INTO ai_events(user_id,mode,error_code,elapsed_ms,created_at) VALUES(?,?,?,?,?)',(uid,out['mode'],out.get('error_code',''),round((time.monotonic()-started)*1000),now()))
            db.execute("UPDATE ai_turns SET status='done',response=? WHERE user_id=? AND request_key=?",(json.dumps(out,ensure_ascii=False),uid,request_key))
            return out
        raise AppError(404,'Маршрут не найден')

import sys
sys.path.insert(0,str(ROOT))
import assistant_service
import platform_service
import ai_knowledge
import ai_config

def make_server(port):
    init_db()
    with connect() as db: platform_service.initialize(db);ai_knowledge.initialize(db)
    server=ThreadingHTTPServer((os.environ.get('JANA_BIND','127.0.0.1'),port),Handler)
    server.login_attempts={};server.ai_attempts={};server.dummy_hash=password_hash(secrets.token_urlsafe(16))
    return server

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=int(os.environ.get('PORT','8000')));p.add_argument('--no-browser',action='store_true');args=p.parse_args()
    try:server=make_server(args.port)
    except OSError:
        print('Не удалось открыть порт. Остановите старый сервер или выберите другой: py -3 server.py --port 8010',flush=True);raise SystemExit(1)
    print(f'\nJanaМен 1.4 iPhone + Gemini: http://127.0.0.1:{server.server_port}\nЛокальный учебный MVP. Для остановки нажмите Ctrl+C.\n',flush=True)
    _ai=ai_config.public_settings()
    print('Папка проекта:',ROOT,'\nИИ:',_ai['provider'],'| ключ настроен:',_ai['configured'],'| модель:',_ai['model'],flush=True)
    if _ai['config_error']:print('Ошибка настройки ИИ:',_ai['config_error'],flush=True)
    if os.environ.get('JANA_PUBLIC_URL'):print('Общий адрес для iPhone и компьютера:',os.environ['JANA_PUBLIC_URL'],flush=True)
    if not args.no_browser:
        import webbrowser;threading.Timer(1,lambda:webbrowser.open(f'http://127.0.0.1:{server.server_port}')).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nСервер остановлен.')
    finally: server.server_close()
