"""Direct Google Gemini REST, verified TLS, no redirects/retries or credentials in URLs."""
import hashlib,json,re,threading,time,urllib.request,urllib.error,socket
from ai_transport import AIError
BASE='https://generativelanguage.googleapis.com/v1beta/'
_CACHE={};_LOCK=threading.Lock();LIMIT=1048576
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def _open(req,timeout):return urllib.request.build_opener(NoRedirect()).open(req,timeout=timeout)
def _cache_key(config):return hashlib.sha256(config['key'].encode()).hexdigest()
def selected_model(config):
 if config.get('provider')!='gemini':return ''
 if config['model']!='auto':return config['model']
 with _LOCK:
  cached=_CACHE.get(_cache_key(config));return cached[1] if cached and cached[0]>time.monotonic() else ''
def _error_code(status,body):
 try:
  obj=json.loads(body);err=obj.get('error',{});reasons=[d.get('reason') for d in err.get('details',[]) if isinstance(d,dict)]
  if 'API_KEY_INVALID' in reasons:return 'gemini_key_invalid'
  if 'API_KEY_SERVICE_BLOCKED' in reasons or 'API_KEY_HTTP_REFERRER_BLOCKED' in reasons:return 'gemini_key_restricted'
 except (ValueError,AttributeError,TypeError):pass
 return 'http_'+str(status)
def _request(path,config,deadline,payload=None):
 remaining=deadline-time.monotonic()
 if remaining<=0:raise AIError('timeout')
 req=urllib.request.Request(BASE+path,data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,
  headers={'Content-Type':'application/json','x-goog-api-key':config['key']},method='POST' if payload is not None else 'GET')
 try:
  with _open(req,remaining) as res:
   raw=res.read(LIMIT+1)
   if len(raw)>LIMIT:raise AIError('response_too_large')
   if time.monotonic()>deadline:raise AIError('timeout')
   obj=json.loads(raw)
   if not isinstance(obj,dict):raise AIError('invalid_response')
   return obj
 except AIError:raise
 except urllib.error.HTTPError as e:
  try:body=e.read(16384)
  except Exception:body=b''
  finally:e.close()
  raise AIError(_error_code(e.code,body)) from None
 except (TimeoutError,socket.timeout):raise AIError('timeout') from None
 except urllib.error.URLError:raise AIError('network') from None
 except (ValueError,KeyError,TypeError,UnicodeError):raise AIError('invalid_response') from None
 except OSError:raise AIError('network') from None

def resolve_model(config,deadline=None):
 if config['model']!='auto':
  if not re.fullmatch(r'gemini-[A-Za-z0-9._-]{1,120}',config['model']):raise AIError('model')
  return config['model']
 cached=selected_model(config)
 if cached:return cached
 deadline=deadline or time.monotonic()+config['timeout'];models=[];token=''
 for _ in range(3):
  from urllib.parse import urlencode
  path='models?pageSize=100'+('&'+urlencode({'pageToken':token}) if token else '')
  result=_request(path,config,deadline)
  for item in result.get('models',[]):
   name=item.get('name','').removeprefix('models/')
   if 'generateContent' in item.get('supportedGenerationMethods',[]) and re.fullmatch(r'gemini-[A-Za-z0-9._-]{1,120}',name) and not any(t in name for t in ('image','audio','tts','embedding','robotics','computer-use','live')):models.append(name)
  token=result.get('nextPageToken','')
  if not token:break
 if not models:raise AIError('gemini_no_model')
 preferences=('gemini-3.5-flash-lite','gemini-3.8-flash','gemini-3.1-flash-lite','gemini-3-flash-preview','gemini-2.5-flash-lite','gemini-2.5-flash')
 model=next((m for m in preferences if m in models),None)
 if not model:model=sorted(models,key=lambda n:('flash' not in n,any(x in n for x in ('preview','exp')),n))[0]
 with _LOCK:
  if len(_CACHE)>=16:_CACHE.clear()
  _CACHE[_cache_key(config)]=(time.monotonic()+600,model)
 return model

def parse_response(obj):
 if obj.get('promptFeedback',{}).get('blockReason'):raise AIError('gemini_blocked')
 candidates=obj.get('candidates',[])
 if not isinstance(candidates,list) or not candidates:raise AIError('gemini_empty')
 candidate=candidates[0]
 reason=candidate.get('finishReason')
 if reason in ('SAFETY','RECITATION','BLOCKLIST','PROHIBITED_CONTENT','SPII'):raise AIError('gemini_blocked')
 if reason=='MAX_TOKENS':raise AIError('gemini_truncated')
 if reason!='STOP':raise AIError('invalid_response')
 parts=candidate.get('content',{}).get('parts',[])
 text=''.join(p['text'] for p in parts if isinstance(p,dict) and not p.get('thought') and isinstance(p.get('text'),str)).strip()
 if not text:raise AIError('gemini_empty')
 if len(text)>24000:raise AIError('response_too_large')
 return text

def generate(messages,config):
 deadline=time.monotonic()+config['timeout'];model=resolve_model(config,deadline)
 system='\n\n'.join(m['content'] for m in messages if m['role']=='system')
 system+='\nACTUAL_SERVER_MODEL: '+model+'; PROVIDER: Google Gemini API. Используй это точное имя модели, если спросят.'
 contents=[]
 for m in messages:
  if m['role'] not in ('user','assistant'):continue
  role='model' if m['role']=='assistant' else 'user'
  if contents and contents[-1]['role']==role:contents[-1]['parts'].append({'text':m['content']})
  else:contents.append({'role':role,'parts':[{'text':m['content']}]})
 payload={'systemInstruction':{'parts':[{'text':system}]},'contents':contents,'generationConfig':{'maxOutputTokens':4096}}
 return parse_response(_request('models/'+model+':generateContent',config,deadline,payload))
