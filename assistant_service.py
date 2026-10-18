"""Read-only, role-filtered Jana orchestration. Private records stay local."""
import datetime as dt,difflib,json,os,re,threading,time,unicodedata
# Kept exported for existing integrations/tests; transport lives in its own module.
import subprocess,shutil,urllib.request
import ai_config
from ai_transport import _provider_message,_claims_json,_anymodel_curl,cloud_request,chat_request,AIError
GATE=threading.BoundedSemaphore(2)
REFUSAL='Я помогаю с JanaМен и рабочими вопросами по доступной базе. Надёжного ответа на этот вопрос не найдено. Уточните вопрос или обратитесь в HR.'
REFUSAL_KK='Мен JanaМен платформасы мен қолжетімді жұмыс нұсқаулықтары бойынша көмектесемін. Бұл сұраққа сенімді дерек табылмады. Сұрақты нақтылаңыз немесе HR маманына хабарласыңыз.'
REFUSALS={'ru':REFUSAL,'kk':REFUSAL_KK,'en':'I help with JanaMen and authorised workplace instructions. I could not find a reliable source. Please clarify or contact HR.','uz':'Men JanaMen va ruxsat etilgan ish yo‘riqnomalari bo‘yicha yordam beraman. Ishonchli manba topilmadi. Savolni aniqlashtiring yoki HR ga murojaat qiling.','tg':'Ман дар бораи JanaMen ва дастурҳои кории дастрас кӯмак мекунам. Манбаи боэътимод ёфт нашуд. Саволро аниқ кунед ё ба HR муроҷиат кунед.','mn':'Би JanaMen болон зөвшөөрөгдсөн ажлын зааврын талаар тусална. Найдвартай эх сурвалж олдсонгүй. Асуултаа тодруулна уу эсвэл HR-т хандана уу.','ky':'Мен JanaMen жана жеткиликтүү иш нускамалары боюнча жардам берем. Ишенимдүү булак табылган жок. Суроону тактаңыз же HR адисине кайрылыңыз.'}
HELPS={'ru':'Привет! Я Jana. Помогу с отпуском, Workspace, документами, обучением и сервисами. Можно спросить: «Как создать задачу?», «Мои заявки», «Мои задачи», «Мои курсы».','kk':'Сәлем! Мен Jana көмекшісімін. Демалыс, Workspace, құжаттар, оқу және сервистер бойынша көмектесемін. Мысалы: «Тапсырманы қалай құруға болады?» немесе «Менің өтінімдерім».','en':'Hello! I am Jana. I can help with leave, Workspace, documents, learning and services. Try “How do I create a task?”, “My requests”, “My tasks” or “My courses”.','uz':'Salom! Men Jana yordamchisiman. Ta’til, Workspace, hujjatlar, o‘qish va xizmatlar bo‘yicha yordam beraman. Masalan: “Vazifa qanday yaratiladi?”','tg':'Салом! Ман Jana ҳастам. Дар бораи рухсатӣ, Workspace, ҳуҷҷатҳо, омӯзиш ва хизматрасонӣ кӯмак мекунам.','mn':'Сайн байна уу! Би Jana. Амралт, Workspace, баримт бичиг, сургалт болон үйлчилгээний талаар тусална.','ky':'Салам! Мен Jana жардамчысымын. Өргүү, Workspace, документтер, окуу жана кызматтар боюнча жардам берем.'}
TOPICS={
 'leave':('отпуск','демалыс','ta’til','tatil','таътил','рухсат','амралт','өргүү','vacation','отдохн','отдых','leave'),
 'status':('статус','status','ҳолат','абал','төлөв','holat','уведомлен','истори','согласован','мәртеб','хабарлама'),
 'profile':('профил','должност','остаток','баланс','лауазым','balance'),
 'learning':('курс','сургалт','окуу','o‘qish','омӯзиш','training','обучен','academy','академ','тест','оқу','үйрен','course'),
 'workspace':('workspace','воркспейс','пространств','задач','таск','task','kanban','канбан','комментар','тапсырма','даалгавар','вазифа','vazifa'),
 'files':('файл','документ','загруз','скача','переда','поиск','file','upload','download','search','құжат','іздеу','ҳуҷҷат','hujjat','баримт'),
 'service':('сервис','обращен','поддержк','почт','оборудован','офис','ticket','support','service','қолдау','хизмат','жабдуу'),
 'onboarding':('адаптац','нович','onboarding','бейімдел','көнүү'),
 'calendar':('календар','пересеч','отсутств','calendar','absence','күнтізбе','хуанли'),
 'access':('вход','парол','регистрац','аккаунт','сброс','восстанов','login','password','account','кіру','құпиясөз','нэвтрэх'),
 'assistant':('ии','ai','модель','чат','цитат','anymodel','groq','помощник','assistant'),
 'mobile':('телефон','мобильн','pwa','интернет','офлайн','mobile','offline','phone','утас'),
 'theme':('фон','темн','тёмн','светл','цвет','оформлен','theme','background','dark','light','түс'),
 'platform':('платформ','janamen','janaмен','возможност','умеешь','platform','help')}
TITLE_TOPICS={'Оформление:':'theme','Workspace':'workspace','Документы:':'files','Сервисы:':'service','Адаптация:':'onboarding','Календарь':'calendar','Вход,':'access','AI Jana:':'assistant','Мобильный':'mobile','Возможности':'platform'}
def provider_mode():return ai_config.settings()['provider']
def _words(q):return re.findall(r'[\wёәіңғүұқөһ]+',q.lower())
def ranked_docs(q,docs):
 stop={'как','где','изменить','измен','создать','созда','открыть','откры','нажать','сделать','работает','how','what','change','create'}
 words=[w for w in _words(q) if w not in stop];concepts=set()
 for topic,aliases in TOPICS.items():
  if any(any(w.startswith(a) or (len(w)>4 and len(a)>4 and difflib.SequenceMatcher(None,w,a).ratio()>.83) for a in aliases) for w in words):concepts.add(topic)
 scored=[]
 for doc in docs:
  keywords=str(doc.get('keywords','')).lower().split(',');title=str(doc.get('title',''))
  topic={1:'leave',2:'status',3:'profile',4:'learning',5:'status',6:'status'}.get(doc['id'])
  for prefix,t in TITLE_TOPICS.items():
   if title.startswith(prefix):topic=t
  score=(18 if topic in concepts else 0)
  score+=sum(3 for k in keywords if len(k.strip())>2 and k.strip() not in stop and any(w.startswith(k.strip()) or k.strip().startswith(w) and len(w)>3 for w in words))
  score+=sum(1 for w in words if len(w)>4 and w in title.lower())
  if score:scored.append((score,doc))
 if not scored:return []
 ranked=sorted(scored,key=lambda x:(-x[0],x[1]['id']));threshold=max(4 if concepts else 3,ranked[0][0]*.35)
 return [d for score,d in ranked if score>=threshold][:3]
def _norm(text):return ' '.join(unicodedata.normalize('NFC',text).split())
def validate_claims(result,docs):
 if not isinstance(result,dict) or result.get('insufficient') is not False:return None
 claims=result.get('claims');lookup={d['id']:d for d in docs}
 if not isinstance(claims,list) or not 1<=len(claims)<=3:return None
 clean=[]
 for c in claims:
  if not isinstance(c,dict):return None
  sid=c.get('source_id');quote=c.get('quote');text=c.get('text')
  if type(sid) is not int or sid not in lookup or not isinstance(quote,str) or len(quote.strip())<16 or len(quote)>5000:return None
  body=lookup[sid]['body']
  if quote not in body:
   # Only Unicode/whitespace differences are tolerated, never approximate/fuzzy evidence.
   if _norm(quote) not in _norm(body):return None
  if not isinstance(text,str) or not 1<=len(text.strip())<=1500:return None
  clean.append({'text':text.strip(),'source_id':sid,'quote':quote.strip()})
 return clean
ERRORS={'not_configured':'Ключ модели не настроен. Добавьте ключ Google в GEMINI_KEY.txt.','curl_missing':'Не найден curl.exe. Проверьте его установку на сервере.','timeout':'Модель не ответила за отведённое время.','network':'Нет соединения с API модели.','invalid_response':'Ответ модели получен в неподдерживаемом формате.','http_400':'API отклонил параметры или модель (HTTP 400).','http_401':'API не принял ключ (HTTP 401).','http_402':'Проверьте баланс и доступ к модели (HTTP 402).','http_403':'API запретил запрос (HTTP 403). Проверьте scripts/check_ai.py.','http_404':'API не нашёл модель или маршрут (HTTP 404).','http_429':'Достигнута квота или частота запросов провайдера (HTTP 429).','daily_limit':'Достигнут дневной лимит AI этой платформы.','busy':'Все доступные подключения модели заняты.','invalid_evidence':'Ответ модели не прошёл проверку источников.','insufficient':'Модель не нашла подтверждённого ответа в переданных источниках.'}
def _reply(text,mode='account',**kw):
 out=dict(answer=text,mode=mode,sources=[],actions=[]);out.update(kw);return out
def _private(db,q,own,user):
 low=q.lower();uid=user['id'];mine=any(x in low for x in ('мои ','мой ','моей ','моего ','моим ','моём ','моем ','моя ','мне ','у меня','моих ','менің','my ','менин'))
 if not mine:return None
 if any(x in low for x in ('задач','tasks','task','тапсырма')):
  import platform_service as ps
  tasks=[dict(t) for t in db.execute("SELECT * FROM tasks WHERE assignee_id=? AND status!='done' ORDER BY COALESCE(due_date,'9999'),id",(uid,)) if ps.visible_task(db,user,t)]
  labels={'todo':'К выполнению','doing':'В работе','done':'Готово'}
  text='Ваши незавершённые задачи: '+str(len(tasks))+'.'
  if tasks:text+='\n'+'\n'.join(f'• {t["title"]} — {labels.get(t["status"],t["status"])}; срок: {t["due_date"] or "не указан"}.' for t in tasks[:10])
  return _reply(text,actions=[{'page':'workspace','label':'Workspace'}])
 if any(x in low for x in ('курс','обучен','course','оқу')):
  rows=db.execute('SELECT c.title,a.completed,a.score FROM assignments a JOIN courses c ON c.id=a.course_id WHERE a.user_id=? ORDER BY c.id',(uid,)).fetchall()
  text='Назначено курсов: '+str(len(rows))+'.'
  if rows:text+='\n'+'\n'.join(f'• {r["title"]} — '+('завершён' if r['completed'] else 'не завершён')+(f'; лучший результат: {r["score"]}%.' if r['score'] is not None else '.') for r in rows[:10])
  return _reply(text,actions=[{'page':'academy','label':'Academy'}])
 if any(x in low for x in ('обращен','ticket')):
  rows=db.execute('SELECT id,title,status FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 10',(uid,)).fetchall()
  return _reply('\n'.join(f'№{r["id"]}: {r["title"]} — {r["status"]}.' for r in rows) or 'У вас пока нет сервисных обращений.',actions=[{'page':'service','label':'Сервисы'}])
 if any(x in low for x in ('профил','должност','руководител','profile','manager')):
  manager=db.execute('SELECT name FROM users WHERE id=?',(user.get('manager_id'),)).fetchone()
  return _reply(f'{user["name"]}\nДолжность: {user["position"]}\nПодразделение: {user["department"]}\nРуководитель: {manager[0] if manager else "не назначен"}. Кадровые изменения выполняет HR.')
 if any(x in low for x in ('остаток','баланс','balance')) or ('сколько' in low and any(x in low for x in ('отпуск','дней'))):
  return _reply(f'Тестовый остаток: {user["vacation_days"]} дней. Он не списывается автоматически и не является официальным балансом 1С:ЗУП.',actions=[{'page':'requests','label':'Мои заявки'}])
 if any(x in low for x in ('заяв','request','өтін')) or ('статус' in low and 'отпуск' in low):
  match=re.search(r'(?:№|#)\s*(\d+)',low);rows=[r for r in own if not match or r['id']==int(match.group(1))]
  if not rows:return _reply('Своя заявка с таким номером не найдена.',actions=[{'page':'requests','label':'Мои заявки'}])
  return _reply('\n'.join(f'№{r["id"]}: {r["status_label"]}. {r["start_date"]} — {r["end_date"]}.' for r in rows[:5]),actions=[{'request_id':r['id'],'label':f'Открыть №{r["id"]}'} for r in rows[:5]])
 return None
def _blocked(q):
 low=q.lower()
 if any(x in low for x in ('зарплат','оклад','паспорт','иин','жалақы','жсн','salary','system prompt','игнорируй','ignore all','раскрой инструкц','закон','уволь','беремен','пенси','больнич','реквизит')):return True
 return bool(re.search(r'(покажи|дай|раскрой|узнай|show|reveal).{0,45}(парол|ключ|токен|password|api key|чуж|других сотруд)',low))
def grounded_answer(db,q,docs,own,user,lang='ru'):
 lang=lang if lang in REFUSALS else 'ru';q=q.strip()[:2000]
 if _blocked(q):return _reply(REFUSALS[lang],'no_answer')
 if q.lower().strip(' !?.') in ('ты кто','кто ты','как дела','чем можешь помочь','чем ты можешь помочь','who are you'):return _reply(HELPS[lang],'help')
 if re.fullmatch(r'(привет|здравствуй(?:те)?|сәлем|салам|salom|салом|hello|hi|сайн байна уу|спасибо|рахмет|thanks|thank you)[!?.\s]*',q.lower()):return _reply(HELPS[lang],'help')
 private=_private(db,q,own,user)
 if private:return private
 if len(_words(q))<2 and not ranked_docs(q,docs):return _reply(HELPS[lang],'clarification')
 found=ranked_docs(q,docs)
 if not found:return _reply(REFUSALS[lang],'no_answer')
 # Constrain each request to a bounded document context; only allowed docs arrive here.
 found=[dict(d,body=d['body'][:5000]) for d in found];top=found[0]
 out=dict(answer=top['body'],sources=[{'id':top['id'],'title':top['title']}],mode='extractive',actions=[])
 if top['id']==1:out['actions']=[{'action':'new-request','label':'Начать оформление отпуска'}]
 elif top['id']==4:out['actions']=[{'page':'academy','label':'К обучению'}]
 config=ai_config.settings()
 if config['provider']=='extractive':
  out['error_code']='not_configured';out['notice']='Поисковый режим: '+ERRORS['not_configured'];return out
 def fallback(code):
  out.update(mode='extractive_fallback',error_code=code,notice=ERRORS.get(code,'Модель недоступна ('+code+').')+' Показана выдержка из доступной базы.');return out
 if config['config_error']:return fallback(config['config_error'])
 if not GATE.acquire(blocking=False):return fallback('busy')
 try:
  day=dt.datetime.now(dt.timezone.utc).date().isoformat();db.execute('INSERT OR IGNORE INTO ai_usage(day,calls) VALUES(?,0)',(day,))
  reserved=db.execute('UPDATE ai_usage SET calls=calls+1 WHERE day=? AND calls<?',(day,config['daily_limit'])).rowcount;db.commit()
  if not reserved:return fallback('daily_limit')
  try:
   result=cloud_request(q,found,lang)
   if isinstance(result,dict) and result.get('insufficient') is True:return _reply(REFUSALS[lang],'no_answer',error_code='insufficient',notice='Модель не нашла подтверждённого ответа. Неподходящий текст источника не подставляется.')
   claims=validate_claims(result,found)
   if not claims:return fallback('invalid_evidence')
   ids={c['source_id'] for c in claims}
   out.update(answer='\n\n'.join(c['text'] for c in claims),claims=claims,sources=[{'id':d['id'],'title':d['title']} for d in found if d['id'] in ids],mode=config['provider'],notice='Ответ модели по источникам. Сверьте важные детали с цитатами.')
   return out
  except AIError as e:return fallback(e.code)
  except TimeoutError:return fallback('timeout')
  except Exception:return fallback('internal_ai')
 finally:GATE.release()


def conversation_history(db,tid,role):
 """Only this owned thread is supplied by server; skip private tools and stale context."""
 rows=db.execute('SELECT role,body,payload FROM chat_messages WHERE thread_id=? ORDER BY id DESC LIMIT 24',(tid,)).fetchall()
 result=[];pending=None
 for row in reversed(rows):
  if row['role']=='user':pending=row['body'];continue
  try:payload=json.loads(row['payload'] or '{}')
  except (TypeError,ValueError):pending=None;continue
  valid=payload.get('mode') in ('anymodel','groq','gemini')
  for source in payload.get('sources',[]):
   fresh=db.execute("SELECT version FROM knowledge WHERE id=? AND (audience='all' OR audience=?)",(source['id'],role)).fetchone()
   if not fresh or payload.get('source_versions',{}).get(str(source['id']))!=fresh[0]:valid=False
  if valid and pending is not None:
   result.extend([{'role':'user','content':pending[:1000]},{'role':'assistant','content':row['body'][:4000]}])
  pending=None
 return result[-12:]

def answer(db,q,docs,own,user,lang='ru',history=None):
 config=ai_config.settings()
 if config.get('chat_mode','chat')=='grounded':return grounded_answer(db,q,docs,own,user,lang)
 # Exact account queries remain local: no HR database records are sent to a provider.
 private=_private(db,q,own,user)
 if private:return private
 def failure(code):
  return _reply('Не удалось получить ответ ИИ. '+ERRORS.get(code,'Ошибка подключения к модели ('+code+').'),
                'error',error_code=code,notice='Шаблонный ответ или выдержка из базы вместо ответа модели не подставляются.')
 if not config['configured']:return failure('not_configured')
 if config['config_error']:return failure(config['config_error'])
 # Ranking supplies context, never decides whether a question may reach the model.
 ordered=ranked_docs(q,docs)+[d for d in docs if d not in ranked_docs(q,docs)]
 found=[];budget=22000
 for d in ordered:
  if budget<=0:break
  body=d['body'][:min(5000,budget)];found.append(dict(d,body=body));budget-=len(body)
 if not GATE.acquire(blocking=False):return failure('busy')
 try:
  day=dt.datetime.now(dt.timezone.utc).date().isoformat()
  db.execute('INSERT OR IGNORE INTO ai_usage(day,calls) VALUES(?,0)',(day,))
  if config['daily_limit']:
   reserved=db.execute('UPDATE ai_usage SET calls=calls+1 WHERE day=? AND calls<?',(day,config['daily_limit'])).rowcount
  else:reserved=db.execute('UPDATE ai_usage SET calls=calls+1 WHERE day=?',(day,)).rowcount
  db.commit()
  if not reserved:return failure('daily_limit')
  try:
   text=chat_request(q,found,lang,history=history)
   return _reply(text,config['provider'],sources=[{'id':d['id'],'title':d['title']} for d in found],
                 notice='Ответ ИИ. Инструкции ниже переданы как контекст, а не как подтверждение каждого утверждения.')
  except AIError as e:return failure(e.code)
  except TimeoutError:return failure('timeout')
  except Exception:return failure('internal_ai')
 finally:GATE.release()

ERRORS.update({
 'gemini_key_invalid':'Google не принял API-ключ. Проверьте GEMINI_KEY.txt и действительность ключа в AI Studio.',
 'gemini_key_restricted':'Ограничения ключа запрещают этот серверный запрос. Проверьте ограничения API-ключа в Google Cloud.',
 'gemini_key_file':'Не удалось прочитать GEMINI_KEY.txt. Нужна одна строка с ключом, без кавычек.',
 'gemini_no_model':'Google не вернул доступную текстовую модель с generateContent. Проверьте доступ проекта.',
 'gemini_blocked':'Google остановил ответ по своим правилам. Ответ не подменён шаблоном; уточните вопрос.',
 'gemini_empty':'Google вернул ответ без текста. Повторите вопрос позже.',
 'gemini_truncated':'Ответ Google остановлен по лимиту длины. Попросите более короткий ответ.',
 'response_too_large':'Ответ API превысил технический размер.',
 'http_403':'API запретил запрос (403). Проверьте разрешения ключа, доступ API и регион проекта.',
 'http_429':'Квота или частота запросов API исчерпана (429). Проверьте лимиты и биллинг у провайдера.',
 'http_503':'Сервис модели временно недоступен (503). Автоматический повтор не выполнялся.'
})
