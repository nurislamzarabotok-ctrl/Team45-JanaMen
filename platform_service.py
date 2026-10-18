"""Team 45: employee operations. Every operation checks server-owned ACLs."""
import base64,datetime as dt,hashlib,io,json,mimetypes,re,secrets,sqlite3,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

def initialize(db):
    for table,column,definition in [('users','active','INTEGER NOT NULL DEFAULT 1'),('users','must_change','INTEGER NOT NULL DEFAULT 0'),('users','delegate_id','INTEGER'),('users','locale',"TEXT NOT NULL DEFAULT 'ru'"),('knowledge','updated_at',"TEXT NOT NULL DEFAULT ''"),('knowledge','version','INTEGER NOT NULL DEFAULT 1'),('assignments','due_date','TEXT')]:
        if column not in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+definition)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS spaces(id INTEGER PRIMARY KEY,title TEXT NOT NULL,owner_id INTEGER REFERENCES users(id),created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS members(space_id INTEGER REFERENCES spaces(id),user_id INTEGER REFERENCES users(id),PRIMARY KEY(space_id,user_id));
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,space_id INTEGER REFERENCES spaces(id),creator_id INTEGER REFERENCES users(id),assignee_id INTEGER REFERENCES users(id),title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'todo',priority TEXT NOT NULL DEFAULT 'normal',due_date TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS task_comments(id INTEGER PRIMARY KEY,task_id INTEGER REFERENCES tasks(id),user_id INTEGER REFERENCES users(id),body TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),title TEXT NOT NULL,body TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,owner_id INTEGER REFERENCES users(id),space_id INTEGER REFERENCES spaces(id),request_id INTEGER REFERENCES requests(id),name TEXT NOT NULL,mime TEXT NOT NULL,data BLOB NOT NULL,extracted TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS file_shares(file_id INTEGER REFERENCES files(id),user_id INTEGER REFERENCES users(id),PRIMARY KEY(file_id,user_id));
    CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),assignee_id INTEGER REFERENCES users(id),category TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',priority TEXT NOT NULL DEFAULT 'normal',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS ticket_comments(id INTEGER PRIMARY KEY,ticket_id INTEGER REFERENCES tickets(id),user_id INTEGER REFERENCES users(id),body TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS onboarding(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),title TEXT NOT NULL,due_date TEXT,course_id INTEGER REFERENCES courses(id),done INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS profile_changes(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS quiz_attempts(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),course_id INTEGER REFERENCES courses(id),score INTEGER NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_threads(id INTEGER PRIMARY KEY,user_id INTEGER REFERENCES users(id),title TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY,thread_id INTEGER REFERENCES chat_threads(id) ON DELETE CASCADE,role TEXT NOT NULL,body TEXT NOT NULL,payload TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id),reminders INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS reminder_log(user_id INTEGER,day TEXT,entity TEXT,PRIMARY KEY(user_id,day,entity));
    CREATE TABLE IF NOT EXISTS schema_changes(name TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS ai_turns(user_id INTEGER NOT NULL,request_key TEXT NOT NULL,question_hash TEXT NOT NULL,thread_id INTEGER,status TEXT NOT NULL,response TEXT,created_at REAL NOT NULL,PRIMARY KEY(user_id,request_key));
    CREATE TABLE IF NOT EXISTS ai_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,mode TEXT NOT NULL,error_code TEXT NOT NULL DEFAULT '',elapsed_ms INTEGER NOT NULL,created_at TEXT NOT NULL);
    
    ''')
    if not db.execute("SELECT 1 FROM schema_changes WHERE name='quiz-v1'").fetchone():
        extra=[{'text':'Что делать перед отправкой заявки?','options':['Проверить даты и длительность','Передать пароль коллеге','Ничего не проверять'],'correct':0},{'text':'Что означает согласование руководителем?','options':['Заявка ещё ожидает обработки HR','Документ подписан ЭЦП','Официальный баланс уже изменён'],'correct':0},{'text':'Можно ли выполнять действия без соединения с сервером?','options':['Да, они всегда доставятся','Нет, нужно восстановить связь','Только вечером'],'correct':1}]
        for r in db.execute('SELECT id,questions FROM courses').fetchall():
            qs=json.loads(r['questions']);qs.extend(extra);db.execute('UPDATE courses SET questions=? WHERE id=?',(json.dumps(qs,ensure_ascii=False),r['id']))
        db.execute("INSERT INTO schema_changes VALUES('quiz-v1')")
    db.commit()

def rows(db,sql,args=()):return [dict(r) for r in db.execute(sql,args)]
def allowed_space(db,uid,sid):return bool(db.execute('SELECT 1 FROM members WHERE space_id=? AND user_id=?',(sid,uid)).fetchone())
def visible_task(db,u,t):return bool(t and (allowed_space(db,u['id'],t['space_id']) if t['space_id'] else u['id'] in (t['creator_id'],t['assignee_id'])))
def visible_file(db,u,f):
    if not f:return False
    if f['owner_id']==u['id']:return True
    if f['space_id'] and allowed_space(db,u['id'],f['space_id']):return True
    if f['request_id']:
        r=db.execute('SELECT user_id FROM requests WHERE id=?',(f['request_id'],)).fetchone();owner=db.execute('SELECT manager_id FROM users WHERE id=?',(r['user_id'],)).fetchone() if r else None
        if r and (r['user_id']==u['id'] or u['role']=='hr' or (u['role']=='manager' and (owner['manager_id']==u['id'] or bool(db.execute('SELECT 1 FROM users WHERE id=? AND delegate_id=? AND active=1',(owner['manager_id'],u['id'])).fetchone())))):return True
    return bool(db.execute('SELECT 1 FROM file_shares WHERE file_id=? AND user_id=?',(f['id'],u['id'])).fetchone())
def file_list(db,u):return [dict(r) for r in db.execute('SELECT id,owner_id,space_id,request_id,name,mime,length(data) size,created_at FROM files ORDER BY id DESC') if visible_file(db,u,r)]
def can_ticket(u,t):return bool(t and (u['role']=='hr' or u['id'] in (t['user_id'],t['assignee_id'])))
def require_text(d,key,check,maxlen=1000):
    v=str(d.get(key,'')).strip();check(0<len(v)<=maxlen,400,'Заполните поле: '+key);return v

def reminders(db,u,ctx):
    setting=db.execute('SELECT reminders FROM preferences WHERE user_id=?',(u['id'],)).fetchone()
    if setting and not setting[0]:return
    today=str(dt.date.today())
    items=[(f'task:{t["id"]}',t['title'],'workspace') for t in db.execute("SELECT * FROM tasks WHERE assignee_id=? AND due_date<=? AND status!='done'",(u['id'],today)) if visible_task(db,u,t)]
    items.extend((f'onboarding:{o["id"]}',o['title'],'onboarding') for o in db.execute('SELECT * FROM onboarding WHERE user_id=? AND due_date<=? AND done=0 AND course_id IS NULL',(u['id'],today)))
    for entity,title,kind in items:
        if db.execute('INSERT OR IGNORE INTO reminder_log VALUES(?,?,?)',(u['id'],today,entity)).rowcount:ctx['notify'](db,u['id'],'Напоминание о сроке',title,kind)

def snapshot(db,u):
    uid=u['id'];spaces=rows(db,'SELECT s.* FROM spaces s JOIN members m ON m.space_id=s.id WHERE m.user_id=? ORDER BY s.id',(uid,))
    for s in spaces:s['members']=[x[0] for x in db.execute('SELECT user_id FROM members WHERE space_id=?',(s['id'],))]
    tasks=[dict(t) for t in db.execute('SELECT * FROM tasks ORDER BY id DESC') if visible_task(db,u,t)]
    for t in tasks:t['comments']=rows(db,'SELECT c.*,u.name FROM task_comments c JOIN users u ON u.id=c.user_id WHERE task_id=? ORDER BY c.id',(t['id'],))
    tickets=[dict(t) for t in db.execute('SELECT * FROM tickets ORDER BY id DESC') if can_ticket(u,t)]
    for t in tickets:t['comments']=rows(db,'SELECT c.*,u.name FROM ticket_comments c JOIN users u ON u.id=c.user_id WHERE ticket_id=? ORDER BY c.id',(t['id'],))
    on=rows(db,'SELECT o.*,u.name FROM onboarding o JOIN users u ON u.id=o.user_id'+('' if u['role']=='hr' else ' WHERE o.user_id=?')+' ORDER BY o.id',() if u['role']=='hr' else (uid,))
    for x in on:
        if x['course_id']:x['done']=int(bool(db.execute('SELECT 1 FROM assignments WHERE user_id=? AND course_id=? AND completed=1',(x['user_id'],x['course_id'])).fetchone()))
    return {'knowledge_revision':[(r['id'],r['version']) for r in db.execute("SELECT id,version FROM knowledge WHERE audience='all' OR audience=?",(u['role'],))],'spaces':spaces,'tasks':tasks,'notes':rows(db,'SELECT * FROM notes WHERE user_id=? ORDER BY id DESC',(uid,)),'files':file_list(db,u),'tickets':tickets,'onboarding':on,'directory':rows(db,'SELECT id,name,role,department,position FROM users WHERE active=1 ORDER BY name'),'profile_changes':rows(db,'SELECT p.*,u.name FROM profile_changes p JOIN users u ON u.id=p.user_id'+('' if u['role']=='hr' else ' WHERE p.user_id=?')+' ORDER BY id DESC',() if u['role']=='hr' else (uid,)),'quiz_attempts':rows(db,'SELECT a.*,c.title FROM quiz_attempts a JOIN courses c ON c.id=a.course_id WHERE user_id=? ORDER BY a.id DESC LIMIT 30',(uid,)),'chat_threads':rows(db,'SELECT * FROM chat_threads WHERE user_id=? ORDER BY id DESC LIMIT 50',(uid,)),'preferences':dict(db.execute('SELECT * FROM preferences WHERE user_id=?',(uid,)).fetchone() or {'reminders':1})}

def extract_file(name,data):
    ext=Path(name).suffix.lower()
    if ext in ('.txt','.md','.csv'):return data.decode('utf-8-sig',errors='replace')[:120000]
    if ext=='.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                info=z.getinfo('word/document.xml')
                if info.file_size>2_000_000:return ''
                root=ET.fromstring(z.read(info));return '\n'.join(''.join(p.itertext()) for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))[:120000]
        except Exception:return ''
    if ext=='.pdf':
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data));return '\n'.join((p.extract_text() or '') for p in list(reader.pages)[:40])[:120000]
        except Exception:return ''
    return ''

def endpoint(db,u,path,d,post,ctx):
    R=ctx['require'];notify=ctx['notify'];audit=ctx['audit'];now=ctx['now'];uid=u['id']
    if path=='/api/password/change' and post:
        R(ctx['password_check'](str(d.get('current','')),u['password']),403,'Неверный текущий пароль');pw=str(d.get('password',''));R(len(pw)>=10 and any(x.isdigit() for x in pw) and any(x.isalpha() for x in pw),400,'Минимум 10 символов, буквы и цифры')
        db.execute('UPDATE users SET password=?,must_change=0 WHERE id=?',(ctx['password_hash'](pw),uid));ctx['revoke'](uid,False);audit(db,uid,'password.change','self');return {'ok':True}
    if path=='/api/admin/users' and not post:
        R(u['role']=='hr',403,'Только HR');return {'users':rows(db,'SELECT id,email,name,role,company,position,department,manager_id,delegate_id,hire_date,vacation_days,active,must_change FROM users ORDER BY id')}
    if path=='/api/admin/user' and post:
        R(u['role']=='hr',403,'Только HR');target=int(d.get('id',0));op=d.get('op','save')
        if op=='reset':
            R(target!=uid,400,'Для себя используйте смену пароля');R(db.execute('SELECT 1 FROM users WHERE id=?',(target,)).fetchone(),404,'Сотрудник не найден');pw=secrets.token_urlsafe(12)+'7a';db.execute('UPDATE users SET password=?,must_change=1 WHERE id=?',(ctx['password_hash'](pw),target));ctx['revoke'](target,True);audit(db,uid,'user.reset',target);return {'temporary_password':pw}
        if op=='active':
            R(target!=uid,400,'Нельзя заблокировать себя');R(type(d.get('active')) is bool);db.execute('UPDATE users SET active=? WHERE id=?',(int(d['active']),target));ctx['revoke'](target,True);audit(db,uid,'user.active',target);return {'ok':True}
        name=require_text(d,'name',R,100);email=require_text(d,'email',R,150).lower();role=d.get('role','employee');R(role in ('employee','manager','hr'));R(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email),400,'Некорректная почта');R(target!=uid or role=='hr',400,'Нельзя снять с себя роль HR')
        manager=int(d.get('manager_id') or 0) or None;delegate=int(d.get('delegate_id') or 0) or None
        for x in (manager,delegate):
            if x:R(x!=target and db.execute("SELECT 1 FROM users WHERE id=? AND role='manager' AND active=1",(x,)).fetchone(),400,'Выберите действующего руководителя')
        cursor=manager;visited={target} if target else set()
        while cursor:
            R(cursor not in visited,400,'Цикл в структуре подчинения');visited.add(cursor);parent=db.execute('SELECT manager_id FROM users WHERE id=?',(cursor,)).fetchone();cursor=parent[0] if parent else None
        if delegate:R(role=='manager',400,'Замещение доступно руководителю')
        days=int(d.get('vacation_days',24));R(0<=days<=100);hire=str(d.get('hire_date') or dt.date.today());dt.date.fromisoformat(hire)
        vals=(email,name,role,str(d.get('company','Jana Post'))[:100],str(d.get('position','Сотрудник'))[:100],str(d.get('department','Команда'))[:100],manager,hire,days,delegate)
        if target:
            R(db.execute('SELECT 1 FROM users WHERE id=?',(target,)).fetchone(),404,'Сотрудник не найден');db.execute('UPDATE users SET email=?,name=?,role=?,company=?,position=?,department=?,manager_id=?,hire_date=?,vacation_days=?,delegate_id=? WHERE id=?',vals+(target,));ctx['revoke'](target,target!=uid);pw=None
        else:
            pw=secrets.token_urlsafe(12)+'3a';cur=db.execute('INSERT INTO users(email,name,role,company,position,department,manager_id,hire_date,vacation_days,delegate_id,password,must_change) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)',vals+(ctx['password_hash'](pw),));target=cur.lastrowid
            if db.execute('SELECT 1 FROM courses WHERE id=1').fetchone():db.execute('INSERT INTO assignments(user_id,course_id,assigned_at) VALUES(?,1,?)',(target,now()));notify(db,target,'Вам назначен курс','Вводный курс доступен в Academy.','learning',1)
        audit(db,uid,'user.save',target);return {'id':target,'temporary_password':pw}
    if path=='/api/profile/change' and post:
        body=require_text(d,'body',R,1500);db.execute('INSERT INTO profile_changes(user_id,body,created_at) VALUES(?,?,?)',(uid,body,now()));
        for h in db.execute("SELECT id FROM users WHERE role='hr' AND active=1"):notify(db,h['id'],'Уточнение профиля',u['name']+' отправил запрос.','profile')
        return {'ok':True}
    if path=='/api/profile/resolve' and post:
        R(u['role']=='hr',403);p=db.execute('SELECT * FROM profile_changes WHERE id=?',(int(d.get('id',0)),)).fetchone();R(p,404);db.execute("UPDATE profile_changes SET status='resolved' WHERE id=?",(p['id'],));notify(db,p['user_id'],'Запрос профиля обработан','Проверьте профиль или обратитесь в HR.','profile');return {'ok':True}
    if path=='/api/space' and post:
        title=require_text(d,'title',R,100);ids=d.get('members',[]);R(isinstance(ids,list) and len(ids)<=50);ids=set(int(x) for x in ids)|{uid}
        for x in ids:R(db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(x,)).fetchone(),400,'Участник недоступен')
        sid=int(d.get('id',0))
        if sid:
            R(db.execute('SELECT 1 FROM spaces WHERE id=? AND owner_id=?',(sid,uid)).fetchone(),403,'Только владелец пространства');db.execute('UPDATE spaces SET title=? WHERE id=?',(title,sid));db.execute('DELETE FROM members WHERE space_id=?',(sid,))
        else:sid=db.execute('INSERT INTO spaces(title,owner_id,created_at) VALUES(?,?,?)',(title,uid,now())).lastrowid
        db.executemany('INSERT INTO members VALUES(?,?)',[(sid,x) for x in ids]);audit(db,uid,'space.save',sid);return {'id':sid}
    if path=='/api/task' and post:
        tid=int(d.get('id',0));old=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone() if tid else None
        if old:R(visible_task(db,u,old),404,'Задача недоступна');R(int(d.get('version',0))==old['version'],409,'Задача изменилась. Откройте заново.')
        sid=int(d.get('space_id') or 0) or None;assignee=int(d.get('assignee_id') or uid);R(not sid or allowed_space(db,uid,sid),403,'Пространство недоступно');R(allowed_space(db,assignee,sid) if sid else assignee==uid,403,'Исполнитель должен входить в пространство')
        title=require_text(d,'title',R,200);status=d.get('status','todo');priority=d.get('priority','normal');R(status in ('todo','doing','done'));R(priority in ('low','normal','high'));due=d.get('due_date') or None
        if due:dt.date.fromisoformat(due)
        vals=(sid,assignee,title,str(d.get('body',''))[:5000],status,priority,due,now())
        if old:
            R(old['creator_id']==uid or old['assignee_id']==uid or bool(old['space_id'] and db.execute('SELECT 1 FROM spaces WHERE id=? AND owner_id=?',(old['space_id'],uid)).fetchone()),403)
            cur=db.execute('UPDATE tasks SET space_id=?,assignee_id=?,title=?,body=?,status=?,priority=?,due_date=?,updated_at=?,version=version+1 WHERE id=? AND version=?',vals+(tid,old['version']));R(cur.rowcount==1,409,'Конфликт изменений')
        else:tid=db.execute('INSERT INTO tasks(space_id,assignee_id,title,body,status,priority,due_date,updated_at,creator_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',vals+(uid,now())).lastrowid
        if assignee!=uid:notify(db,assignee,'Задача обновлена',title,'workspace')
        audit(db,uid,'task.save',tid);return {'id':tid}
    if path=='/api/task/comment' and post:
        tid=int(d.get('id',0));R(visible_task(db,u,db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()),404);body=require_text(d,'body',R,2000);db.execute('INSERT INTO task_comments(task_id,user_id,body,created_at) VALUES(?,?,?,?)',(tid,uid,body,now()));return {'ok':True}
    if path=='/api/note' and post:
        nid=int(d.get('id',0));title=require_text(d,'title',R,200);body=str(d.get('body',''))[:12000]
        if nid:
            old=db.execute('SELECT * FROM notes WHERE id=? AND user_id=?',(nid,uid)).fetchone();R(old,404);R(int(d.get('version',0))==old['version'],409,'Заметка изменилась. Откройте заново.');cur=db.execute('UPDATE notes SET title=?,body=?,updated_at=?,version=version+1 WHERE id=? AND version=?',(title,body,now(),nid,old['version']));R(cur.rowcount==1,409)
        else:nid=db.execute('INSERT INTO notes(user_id,title,body,updated_at) VALUES(?,?,?,?)',(uid,title,body,now())).lastrowid
        return {'id':nid}
    if path=='/api/file/upload' and post:
        name=Path(str(d.get('name','file')).replace('\\','/')).name[:180];ext=Path(name).suffix.lower();R(ext in ('.txt','.md','.csv','.docx','.pdf','.jpg','.jpeg','.png'),400,'Допустимы TXT, MD, CSV, DOCX, PDF, JPG, PNG');R(bool(name),400)
        try:data=base64.b64decode(d.get('data',''),validate=True)
        except Exception:R(False,400,'Некорректный файл')
        R(0<len(data)<=2_000_000,413,'Размер файла: до 2 МБ');sid=int(d.get('space_id') or 0) or None;rid=int(d.get('request_id') or 0) or None;R(not(sid and rid),400)
        if sid:R(allowed_space(db,uid,sid),403)
        if rid:R(db.execute('SELECT 1 FROM requests WHERE id=? AND user_id=?',(rid,uid)).fetchone(),403)
        shares=d.get('shares',[]);R(isinstance(shares,list) and len(shares)<=50);shares=set(int(x) for x in shares)
        R(not rid or not shares,400,'Вложения заявки доступны только её участникам')
        for x in shares:R(db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(x,)).fetchone(),400)
        total=db.execute('SELECT COALESCE(sum(length(data)),0) FROM files WHERE owner_id=?',(uid,)).fetchone()[0];R(total+len(data)<=30_000_000,413,'Лимит хранилища пользователя: 30 МБ')
        text=extract_file(name,data);mime=mimetypes.guess_type(name)[0] or 'application/octet-stream';fid=db.execute('INSERT INTO files(owner_id,space_id,request_id,name,mime,data,extracted,created_at) VALUES(?,?,?,?,?,?,?,?)',(uid,sid,rid,name,mime,data,text,now())).lastrowid
        db.executemany('INSERT INTO file_shares VALUES(?,?)',[(fid,x) for x in shares]);recipients=shares|({r[0] for r in db.execute('SELECT user_id FROM members WHERE space_id=?',(sid,))} if sid else set())
        for x in recipients-{uid}:notify(db,x,'Вам доступен документ',name,'workspace')
        audit(db,uid,'file.upload',fid);return {'id':fid,'indexed':bool(text)}
    if path=='/api/files/search' and post:
        q=str(d.get('query','')).strip().lower();R(1<=len(q)<=200);out=[]
        for f in db.execute('SELECT * FROM files ORDER BY id DESC'):
            if visible_file(db,u,f) and (q in f['name'].lower() or q in f['extracted'].lower()):
                text=f['extracted'];i=max(0,text.lower().find(q)-50);out.append({'id':f['id'],'name':f['name'],'excerpt':text[i:i+240],'indexed':bool(text)})
                if len(out)>=50:break
        return {'files':out}
    if path=='/api/file/delete' and post:
        fid=int(d.get('id',0));R(db.execute('SELECT 1 FROM files WHERE id=? AND owner_id=?',(fid,uid)).fetchone(),404);db.execute('DELETE FROM file_shares WHERE file_id=?',(fid,));db.execute('DELETE FROM files WHERE id=?',(fid,));return {'ok':True}
    if path=='/api/ticket' and post:
        tid=int(d.get('id',0));old=db.execute('SELECT * FROM tickets WHERE id=?',(tid,)).fetchone() if tid else None
        if old:
            R(can_ticket(u,old),404);R(int(d.get('version',0))==old['version'],409,'Обращение обновлено. Откройте заново.')
            status=d.get('status',old['status']);R(status in ('open','progress','resolved','closed'));R(u['role']=='hr' or old['assignee_id']==uid or (old['user_id']==uid and status=='closed'),403,'Решение принимает ответственный')
            assignee=int(d.get('assignee_id') or old['assignee_id'] or uid);R(u['role']=='hr' or assignee==old['assignee_id'],403)
            R(db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(assignee,)).fetchone(),400)
            cur=db.execute('UPDATE tickets SET status=?,assignee_id=?,updated_at=?,version=version+1 WHERE id=? AND version=?',(status,assignee,now(),tid,old['version']));R(cur.rowcount==1,409);notify(db,old['user_id'],'Обращение обновлено',old['title'],'service')
        else:
            title=require_text(d,'title',R,200);body=require_text(d,'body',R,5000);category=d.get('category','hr');R(category in ('hr','it','office'));hr=db.execute("SELECT id FROM users WHERE role='hr' AND active=1 ORDER BY id LIMIT 1").fetchone();R(hr,409,'Нет ответственного HR');priority=d.get('priority','normal');R(priority in ('low','normal','high'))
            tid=db.execute('INSERT INTO tickets(user_id,assignee_id,category,title,body,priority,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(uid,hr['id'],category,title,body,priority,now(),now())).lastrowid;notify(db,hr['id'],'Новое обращение',title,'service')
        audit(db,uid,'ticket.save',tid);return {'id':tid}
    if path=='/api/ticket/comment' and post:
        tid=int(d.get('id',0));t=db.execute('SELECT * FROM tickets WHERE id=?',(tid,)).fetchone();R(can_ticket(u,t),404);body=require_text(d,'body',R,2000);db.execute('INSERT INTO ticket_comments(ticket_id,user_id,body,created_at) VALUES(?,?,?,?)',(tid,uid,body,now()));
        for x in {t['user_id'],t['assignee_id']}-{uid}:notify(db,x,'Комментарий к обращению',t['title'],'service')
        return {'ok':True}
    if path=='/api/onboarding/assign' and post:
        R(u['role']=='hr',403);target=int(d.get('user_id',0));R(db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(target,)).fetchone(),404);due=d.get('due_date') or str(dt.date.today()+dt.timedelta(days=7));dt.date.fromisoformat(due)
        R(not db.execute('SELECT 1 FROM onboarding WHERE user_id=?',(target,)).fetchone(),409,'Маршрут уже назначен')
        steps=[('Проверить профиль и контакты',None),('Пройти вводный курс',1),('Создать обращение на оборудование',None),('Встретиться с руководителем',None)]
        for title,cid in steps:db.execute('INSERT INTO onboarding(user_id,title,due_date,course_id,created_at) VALUES(?,?,?,?,?)',(target,title,due,cid,now()))
        db.execute('INSERT OR IGNORE INTO assignments(user_id,course_id,assigned_at) VALUES(?,1,?)',(target,now()));notify(db,target,'Назначена адаптация','Ваш маршрут доступен в разделе «Адаптация».','onboarding');return {'ok':True}
    if path=='/api/onboarding/check' and post:
        oid=int(d.get('id',0));o=db.execute('SELECT * FROM onboarding WHERE id=?',(oid,)).fetchone();R(o and o['user_id']==uid,404);R(not o['course_id'],409,'Курс завершается в Academy');R(type(d.get('done')) is bool);db.execute('UPDATE onboarding SET done=? WHERE id=?',(int(d['done']),oid));return {'ok':True}
    if path=='/api/notifications/item' and post:
        R(type(d.get('read')) is bool);db.execute('UPDATE notifications SET is_read=? WHERE id=? AND user_id=?',(int(d['read']),int(d.get('id',0)),uid));return {'ok':True}
    if path=='/api/preferences' and post:
        R(type(d.get('reminders')) is bool);db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)',(uid,int(d['reminders'])));return {'ok':True}
    if path=='/api/knowledge/save' and post:
        R(u['role']=='hr',403);kid=int(d.get('id',0));title=require_text(d,'title',R,200);body=require_text(d,'body',R,12000);aud=d.get('audience','all');R(aud in ('all','manager','hr'));keywords=str(d.get('keywords',''))[:500]
        if kid:
            cur=db.execute('UPDATE knowledge SET title=?,body=?,audience=?,keywords=?,updated_at=?,version=version+1 WHERE id=? AND version=?',(title,body,aud,keywords,now(),kid,int(d.get('version',0))));R(cur.rowcount==1,409,'Документ изменился. Обновите.')
        else:kid=db.execute('INSERT INTO knowledge(title,body,audience,keywords,updated_at) VALUES(?,?,?,?,?)',(title,body,aud,keywords,now())).lastrowid
        audit(db,uid,'knowledge.save',kid);return {'id':kid}
    if path=='/api/knowledge/delete' and post:
        R(u['role']=='hr',403);db.execute('DELETE FROM knowledge WHERE id=?',(int(d.get('id',0)),));return {'ok':True}
    if path=='/api/chat/list' and not post:return {'threads':rows(db,'SELECT * FROM chat_threads WHERE user_id=? ORDER BY id DESC',(uid,))}
    if path=='/api/chat/messages' and post:
        tid=int(d.get('id',0));R(db.execute('SELECT 1 FROM chat_threads WHERE id=? AND user_id=?',(tid,uid)).fetchone(),404);out=rows(db,'SELECT * FROM chat_messages WHERE thread_id=? ORDER BY id',(tid,))
        for x in out:
            x['payload']=json.loads(x['payload']) if x['payload'] else None
            if x['payload'] and x['payload'].get('sources'):
                allowed={r[0] for r in db.execute("SELECT id FROM knowledge WHERE audience='all' OR audience=?",(u['role'],))}
                stale=any(s['id'] not in allowed for s in x['payload']['sources'])
                versions=x['payload'].get('source_versions',{})
                for source in x['payload']['sources']:
                    current=db.execute('SELECT version FROM knowledge WHERE id=?',(source['id'],)).fetchone()
                    if str(source['id']) in versions and (not current or current[0]!=versions[str(source['id'])]):stale=True
                if stale:x['body']='Источник изменён или больше недоступен. Задайте вопрос заново.';x['payload']={'sources':[],'mode':'no_answer','actions':[]}
        return {'messages':out}
    if path=='/api/chat/delete' and post:
        tid=int(d.get('id',0));R(db.execute('SELECT 1 FROM chat_threads WHERE id=? AND user_id=?',(tid,uid)).fetchone(),404);db.execute('DELETE FROM ai_turns WHERE user_id=? AND thread_id=?',(uid,tid));db.execute('DELETE FROM chat_threads WHERE id=?',(tid,));return {'ok':True}
    if path=='/api/request/manage' and post:
        rid=int(d.get('id',0));r=db.execute('SELECT * FROM requests WHERE id=? AND user_id=?',(rid,uid)).fetchone();R(r,404);R(r['status']=='submitted',409,'Можно изменить или отозвать только до решения');op=d.get('op')
        if op=='withdraw':
            cur=db.execute("UPDATE requests SET status='withdrawn' WHERE id=? AND status='submitted'",(rid,));R(cur.rowcount==1,409);comment='Заявка отозвана сотрудником'
        else:
            R(op=='edit');start=dt.date.fromisoformat(str(d.get('start')));end=dt.date.fromisoformat(str(d.get('end')));R(start>=dt.date.today() and end>=start and (end-start).days+1<=u['vacation_days'],400,'Проверьте даты и остаток');R(not db.execute("SELECT 1 FROM requests WHERE user_id=? AND id!=? AND status IN ('submitted','approved','completed') AND start_date<=? AND end_date>=?",(uid,rid,str(end),str(start))).fetchone(),409,'Даты пересекаются')
            R(d.get('expected_start')==r['start_date'] and d.get('expected_end')==r['end_date'],409,'Даты уже изменены');cur=db.execute("UPDATE requests SET start_date=?,end_date=?,comment=? WHERE id=? AND status='submitted' AND start_date=? AND end_date=?",(str(start),str(end),str(d.get('comment',''))[:1000],rid,r['start_date'],r['end_date']));R(cur.rowcount==1,409);comment='Даты изменены сотрудником'
        db.execute('INSERT INTO history(request_id,actor_id,status,comment,created_at) VALUES(?,?,?,?,?)',(rid,uid,'withdrawn' if op=='withdraw' else 'submitted',comment,now()));notify(db,uid,'Заявка обновлена',comment,'request',rid)
        if u['manager_id']:notify(db,u['manager_id'],'Заявка команды обновлена',comment,'request',rid)
        audit(db,uid,'request.'+op,rid);return {'ok':True}
    if path=='/api/request/document' and post:
        rid=int(d.get('id',0));r=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone();R(r and ctx['can_read_request'](db,u,r),404);owner=db.execute('SELECT name FROM users WHERE id=?',(r['user_id'],)).fetchone();history=rows(db,'SELECT h.*,u.name FROM history h JOIN users u ON u.id=h.actor_id WHERE request_id=? ORDER BY h.id',(rid,))
        return {'text':f'JanaМен · Заявление №{rid}\nСотрудник: {owner[0]}\nПрошу предоставить отпуск: {r["start_date"]} — {r["end_date"]}\nКомментарий: {r["comment"]}\nСтатус: {ctx["STATUSES"].get(r["status"],r["status"])}\n\nИстория:\n'+'\n'.join(f'{h["created_at"]} · {h["name"]} · {h["comment"]}' for h in history)+'\n\nСформировано платформой. Не является подписанным кадровым документом. ЭЦП и Documentolog не подключены.'}
    if path=='/api/analytics' and not post:
        R(u['role'] in ('manager','hr'),403);visible=[dict(r) for r in db.execute('SELECT * FROM requests') if ctx['can_read_request'](db,u,r)];times=[]
        for r in visible:
            if r['status']=='completed':
                end=db.execute("SELECT created_at FROM history WHERE request_id=? AND status='completed' ORDER BY id DESC LIMIT 1",(r['id'],)).fetchone()
                if end:times.append(max(0,(dt.datetime.fromisoformat(end[0])-dt.datetime.fromisoformat(r['created_at'])).total_seconds()/3600))
        team=[r['id'] for r in db.execute('SELECT id,manager_id FROM users') if u['role']=='hr' or r['manager_id']==uid];course=[]
        for t in team:course.extend(rows(db,'SELECT a.*,c.title,u.name FROM assignments a JOIN courses c ON c.id=a.course_id JOIN users u ON u.id=a.user_id WHERE a.user_id=?',(t,)))
        return {'counts':{st:sum(r['status']==st for r in visible) for st in ('submitted','approved','completed','rejected','withdrawn')},'average_hours':round(sum(times)/len(times),2) if times else None,'sample_size':len(times),'learning':course,'requests':visible,'open_tickets':sum(t['status'] not in ('resolved','closed') for t in db.execute('SELECT * FROM tickets') if can_ticket(u,t))}
    if path=='/api/course/admin' and post:
        R(u['role']=='hr',403);cid=int(d.get('id',0));title=require_text(d,'title',R,200);content=d.get('content');qs=d.get('questions');R(isinstance(content,list) and 1<=len(content)<=20 and all(isinstance(x,dict) and isinstance(x.get('title'),str) and isinstance(x.get('text'),str) for x in content),400,'Материалы: массив title/text')
        R(isinstance(qs,list) and 3<=len(qs)<=30 and all(isinstance(q,dict) and isinstance(q.get('text'),str) and isinstance(q.get('options'),list) and 2<=len(q['options'])<=6 and all(isinstance(a,str) for a in q['options']) and type(q.get('correct')) is int and 0<=q['correct']<len(q['options']) for q in qs),400,'Проверьте вопросы и ответы')
        R(not cid or not db.execute('SELECT 1 FROM assignments WHERE course_id=?',(cid,)).fetchone(),409,'Назначенный курс не меняется: создайте новую версию')
        vals=(title,str(d.get('description',''))[:500],max(1,min(120,int(d.get('duration',5)))),json.dumps(content,ensure_ascii=False),json.dumps(qs,ensure_ascii=False))
        if cid:db.execute('UPDATE courses SET title=?,description=?,duration=?,content=?,questions=? WHERE id=?',vals+(cid,))
        else:cid=db.execute('INSERT INTO courses(title,description,duration,content,questions) VALUES(?,?,?,?,?)',vals).lastrowid
        return {'id':cid}
    return None
