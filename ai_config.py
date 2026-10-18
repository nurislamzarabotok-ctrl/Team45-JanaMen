"""AI configuration is re-read locally. Secrets never enter public status."""
import os,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PLACEHOLDERS=('paste_','your_','вставь','твой_','ваш_','<','sk-...')
def valid_key(value):
 return bool(value and not any(c.isspace() or c=='\x00' for c in value) and not value.lower().startswith(PLACEHOLDERS))
def settings():
 file_values={};error=''
 try:
  f=ROOT/'.env'
  if f.is_file():
   if f.stat().st_size>16384:raise ValueError()
   for line in f.read_text(encoding='utf-8-sig').splitlines():
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
     k,v=line.split('=',1)
     if k.strip().startswith('JANA_'):file_values[k.strip()]=v.strip().strip('"').strip("'")
 except (OSError,UnicodeError,ValueError):error='config_file'
 values={**file_values,**{k:v for k,v in os.environ.items() if k.startswith('JANA_')}}
 keyfile=ROOT/'AI_KEY.txt'
 try:
  if keyfile.is_file():
   if keyfile.stat().st_size>4096:raise ValueError()
   lines=[x.strip() for x in keyfile.read_text(encoding='utf-8-sig').splitlines() if x.strip() and not x.strip().startswith('#')]
   if len(lines)==1 and valid_key(lines[0]):
    if 'JANA_ANYMODEL_API_KEY' not in os.environ:values['JANA_ANYMODEL_API_KEY']=lines[0]
    if 'JANA_AI_PROVIDER' not in os.environ:values['JANA_AI_PROVIDER']='anymodel'
 except (OSError,UnicodeError,ValueError):error='key_file'
 # A dedicated Gemini key file wins over obsolete file-based AnyModel settings.
 gemini_file=ROOT/'GEMINI_KEY.txt'
 try:
  if gemini_file.is_file():
   if gemini_file.stat().st_size>4096:raise ValueError()
   lines=[x.strip() for x in gemini_file.read_text(encoding='utf-8-sig').splitlines() if x.strip() and not x.strip().startswith('#')]
   if len(lines)==1 and valid_key(lines[0]):
    if 'JANA_GEMINI_API_KEY' not in os.environ:values['JANA_GEMINI_API_KEY']=lines[0]
    if 'JANA_AI_PROVIDER' not in os.environ:values['JANA_AI_PROVIDER']='gemini'
 except (OSError,UnicodeError,ValueError):error='gemini_key_file'
 provider=values.get('JANA_AI_PROVIDER','auto').strip().lower()
 if provider=='auto':provider='gemini' if valid_key(values.get('JANA_GEMINI_API_KEY','').strip()) else 'anymodel' if valid_key(values.get('JANA_ANYMODEL_API_KEY','').strip()) else 'groq' if valid_key(values.get('JANA_GROQ_API_KEY','').strip()) else 'extractive'
 if provider not in ('extractive','anymodel','groq','gemini'):error='provider';provider='extractive'
 key=values.get('JANA_'+provider.upper()+'_API_KEY','').strip() if provider!='extractive' else ''
 configured=provider!='extractive' and valid_key(key)
 transport=values.get('JANA_ANYMODEL_TRANSPORT','curl').strip().lower() if provider=='anymodel' else 'urllib'
 if transport not in ('curl','urllib'):error='transport'
 if provider=='anymodel' and transport=='curl' and not (shutil.which('curl.exe') or shutil.which('curl')):error='curl_missing'
 def integer(name,default,low,high):
  nonlocal error
  try:return max(low,min(high,int(values.get(name,str(default)))))
  except (ValueError,TypeError):error='config_number';return default
 chat_mode=values.get('JANA_AI_CHAT_MODE','chat').strip().lower()
 if provider=='gemini':chat_mode='chat'
 if chat_mode not in ('chat','grounded'):error='chat_mode'
 timeout=integer('JANA_AI_TIMEOUT',45,5,50);cap=integer('JANA_AI_DAILY_LIMIT',40 if chat_mode=='grounded' else 0,0,100000)
 model=values.get('JANA_ANYMODEL_MODEL','am/gpt-oss-20b') if provider=='anymodel' else values.get('JANA_GROQ_MODEL','openai/gpt-oss-20b')
 if provider=='gemini':model=values.get('JANA_GEMINI_MODEL','auto').strip().removeprefix('models/')
 if provider=='gemini' and model!='auto':
  import re
  if not re.fullmatch(r'gemini-[A-Za-z0-9._-]{1,120}',model):error='model'
 if not model.strip() or len(model)>160 or any(c in model for c in '\r\n'):error='model'
 return {'provider':provider if configured else 'extractive','requested_provider':provider,'key':key if configured else '', 'configured':configured,'model':model.strip(),'transport':transport,'timeout':timeout,'daily_limit':cap,'chat_mode':chat_mode,'config_error':error}
def public_settings():
 s=settings()
 out={k:s[k] for k in ('provider','requested_provider','configured','model','transport','timeout','daily_limit','chat_mode','config_error')}

 if s['provider']=='gemini':
  import gemini_transport
  out['resolved_model']=gemini_transport.selected_model(s)
 return out
