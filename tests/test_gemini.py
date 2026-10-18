"""Gemini configuration + actual local HTTP contract/API tests. NEVER live Google."""
import io,json,os,tempfile,threading,unittest,urllib.request,urllib.error,time
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import test_app
import ai_config as config,gemini_transport as gt,assistant_service as ai

class GeminiConfigTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.env=patch.dict(os.environ,{},clear=True);self.env.start();self.addCleanup(self.env.stop)
  self.path=patch.object(config,'ROOT',self.root);self.path.start();self.addCleanup(self.path.stop)
 def key(self,text='fake-gemini-key'):(self.root/'GEMINI_KEY.txt').write_text(text,encoding='utf-8-sig')
 def test_key_only_auto_model(self):
  self.key();s=config.settings();self.assertEqual(s['provider'],'gemini');self.assertEqual(s['model'],'auto');self.assertEqual(s['transport'],'urllib');self.assertEqual(s['daily_limit'],0)
 def test_gemini_file_wins_over_old_files(self):
  self.key();(self.root/'AI_KEY.txt').write_text('fake-old-anymodel');(self.root/'.env').write_text('JANA_AI_PROVIDER=anymodel\nJANA_AI_CHAT_MODE=grounded');s=config.settings();self.assertEqual(s['provider'],'gemini');self.assertEqual(s['chat_mode'],'chat');self.assertEqual(s['key'],'fake-gemini-key')
 def test_explicit_environment_can_disable(self):
  self.key()
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'extractive'}):self.assertEqual(config.settings()['provider'],'extractive')
 def test_placeholder_not_configured(self):self.key('PASTE_YOUR_GEMINI_API_KEY_HERE');self.assertFalse(config.settings()['configured'])
 def test_oversized_key_error(self):self.key('a'*5000);self.assertEqual(config.settings()['config_error'],'gemini_key_file')
 def test_key_hot_reload(self):self.key('fake-first');self.assertEqual(config.settings()['key'],'fake-first');self.key('fake-second');self.assertEqual(config.settings()['key'],'fake-second')
 def test_env_key_supported(self):
  with patch.dict(os.environ,{'JANA_GEMINI_API_KEY':'fake-env-key'}):self.assertEqual(config.settings()['provider'],'gemini')
 def test_no_curl_needed(self):
  self.key()
  with patch('ai_config.shutil.which',return_value=None):self.assertFalse(config.settings()['config_error'])
 def test_explicit_model_url_injection_rejected(self):
  self.key()
  for name in ['https://evil.test','gemini-x?key=secret','gemini-x/../../evil']:
   with patch.dict(os.environ,{'JANA_GEMINI_MODEL':name}):self.assertEqual(config.settings()['config_error'],'model')
 def test_status_no_key(self):self.key();s=config.public_settings();self.assertNotIn('fake-gemini-key',json.dumps(s));self.assertIn('resolved_model',s)

class GeminiParserTests(unittest.TestCase):
 def result(self,parts=None,reason='STOP'):return {'candidates':[{'finishReason':reason,'content':{'parts':parts or [{'text':'Привет!'}]}}]}
 def test_plain_text_no_claims(self):self.assertEqual(gt.parse_response(self.result()),'Привет!')
 def test_thoughts_not_displayed(self):self.assertEqual(gt.parse_response(self.result([{'text':'PRIVATE THOUGHT','thought':True},{'text':'Ответ.'}])),'Ответ.')
 def test_parts_joined(self):self.assertEqual(gt.parse_response(self.result([{'text':'Добрый '},{'text':'день'}])),'Добрый день')
 def test_safety_block(self):
  with self.assertRaises(ai.AIError) as e:gt.parse_response(self.result(reason='SAFETY'))
  self.assertEqual(e.exception.code,'gemini_blocked')
 def test_prompt_block(self):
  with self.assertRaises(ai.AIError) as e:gt.parse_response({'promptFeedback':{'blockReason':'SAFETY'}})
  self.assertEqual(e.exception.code,'gemini_blocked')
 def test_no_candidate(self):
  with self.assertRaises(ai.AIError) as e:gt.parse_response({})
  self.assertEqual(e.exception.code,'gemini_empty')
 def test_truncation_explicit(self):
  with self.assertRaises(ai.AIError) as e:gt.parse_response(self.result(reason='MAX_TOKENS'))
  self.assertEqual(e.exception.code,'gemini_truncated')
 def test_api_key_error_safe(self):
  body=json.dumps({'error':{'message':'secret-key-must-not-leak','details':[{'reason':'API_KEY_INVALID'}]}}).encode();self.assertEqual(gt._error_code(400,body),'gemini_key_invalid')

class GeminiBoundaryTests(unittest.TestCase):
 def config(self):return {'provider':'gemini','model':'gemini-test','key':'fake-boundary-key','timeout':2}
 def test_redirect_not_followed(self):self.assertIsNone(gt.NoRedirect().redirect_request(None,None,302,'redirect',{},'https://outside.invalid'))
 def test_timeout_classified(self):
  with patch.object(gt,'_open',side_effect=TimeoutError()):
   with self.assertRaises(ai.AIError) as e:gt._request('models',self.config(),time.monotonic()+2)
  self.assertEqual(e.exception.code,'timeout')
 def test_invalid_json_is_safe(self):
  with patch.object(gt,'_open',return_value=io.BytesIO(b'not-json-secret')):
   with self.assertRaises(ai.AIError) as e:gt._request('models',self.config(),time.monotonic()+2)
  self.assertEqual(e.exception.code,'invalid_response');self.assertNotIn('secret',str(e.exception))
 def test_oversized_response_rejected(self):
  with patch.object(gt,'_open',return_value=io.BytesIO(b'a'*(gt.LIMIT+1))):
   with self.assertRaises(ai.AIError) as e:gt._request('models',self.config(),time.monotonic()+2)
  self.assertEqual(e.exception.code,'response_too_large')
 def test_expired_deadline_no_request(self):
  with patch.object(gt,'_open') as opening:
   with self.assertRaises(ai.AIError):gt._request('models',self.config(),time.monotonic()-1)
   opening.assert_not_called()
 def test_invalid_model_no_request(self):
  with patch.object(gt,'_open') as opening:
   with self.assertRaises(ai.AIError):gt.resolve_model(dict(self.config(),model='https://outside.invalid'))
   opening.assert_not_called()

class GeminiPlatformTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  test_app.PlatformTests.setUpClass.__func__(cls)
  cls.mode='ok';cls.requests=[];cls.model_lists=0
  class Stub(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def send(self,status,obj):
    body=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def do_GET(self):
    cls.model_lists+=1
    if cls.mode=='no_model':return self.send(200,{'models':[{'name':'models/embedding-001','supportedGenerationMethods':['embedContent']}]})
    return self.send(200,{'models':[{'name':'models/gemini-3.8-flash','supportedGenerationMethods':['generateContent']},{'name':'models/gemini-3.5-flash-lite','supportedGenerationMethods':['generateContent']}]})
   def do_POST(self):
    payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));cls.requests.append({'path':self.path,'headers':dict(self.headers),'body':payload})
    if cls.mode in ('403','429','503'):return self.send(int(cls.mode),{'error':{'message':'fake-private-detail-never-display'}})
    if cls.mode=='blocked':return self.send(200,{'promptFeedback':{'blockReason':'SAFETY'}})
    text=payload['contents'][-1]['parts'][0]['text'];reply='Модель получила: '+text
    return self.send(200,{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':reply}]}}]})
  cls.stub=ThreadingHTTPServer(('127.0.0.1',0),Stub);cls.worker=threading.Thread(target=cls.stub.serve_forever,daemon=True);cls.worker.start()
 @classmethod
 def tearDownClass(cls):
  cls.stub.shutdown();cls.stub.server_close();cls.worker.join();test_app.PlatformTests.tearDownClass.__func__(cls)
 def setUp(self):
  type(self).mode='ok';type(self).requests=[];type(self).model_lists=0;self.server.ai_attempts={};gt._CACHE.clear()
  self.env=patch.dict(os.environ,{'JANA_AI_PROVIDER':'gemini','JANA_GEMINI_API_KEY':'fake-local-google-key','JANA_GEMINI_MODEL':'auto','JANA_AI_CHAT_MODE':'chat','JANA_AI_DAILY_LIMIT':'0'});self.env.start();self.addCleanup(self.env.stop)
  real_open=gt._open
  def routed(req,timeout):
   self.assertTrue(req.full_url.startswith(gt.BASE));self.assertNotIn('fake-local-google-key',req.full_url)
   local=urllib.request.Request('http://127.0.0.1:'+str(self.stub.server_port)+'/'+req.full_url[len(gt.BASE):],data=req.data,headers=dict(req.headers),method=req.method)
   return real_open(local,timeout)
  self.route=patch.object(gt,'_open',side_effect=routed);self.route.start();self.addCleanup(self.route.stop)
 def ask(self,q,**kw):return self.clients['employee'].call('assistant',dict(question=q,**kw))
 def test_complete_platform_model_reply(self):
  code,a=self.ask('Привет');self.assertEqual(code,200);self.assertEqual(a['mode'],'gemini');self.assertEqual(a['answer'],'Модель получила: Привет');self.assertEqual(a['provider_config']['resolved_model'],'gemini-3.5-flash-lite');self.assertEqual(len(self.requests),1)
 def test_native_url_and_header(self):
  self.ask('Привет');r=self.requests[0];self.assertEqual(r['path'],'/models/gemini-3.5-flash-lite:generateContent');self.assertEqual(r['headers'].get('X-Goog-Api-Key'),'fake-local-google-key');self.assertNotIn('Authorization',r['headers']);self.assertNotIn('key=',r['path']);self.assertIn('systemInstruction',r['body']);self.assertNotIn('messages',r['body'])
 def test_multiturn_user_model_user(self):
  a=self.ask('Через какую модель ты работаешь?')[1];self.ask('Если работает, скажи Ноу',thread_id=a['thread_id']);contents=self.requests[-1]['body']['contents'];self.assertEqual([x['role'] for x in contents],['user','model','user']);self.assertIn('Через какую модель',contents[0]['parts'][0]['text']);self.assertEqual(self.model_lists,1)
 def test_system_actual_model(self):
  self.ask('Какая модель?');text=self.requests[-1]['body']['systemInstruction']['parts'][0]['text'];self.assertIn('ACTUAL_SERVER_MODEL: gemini-3.5-flash-lite',text);self.assertNotIn('fake-local-google-key',text)
 def test_errors_no_fallback_no_retry(self):
  for status in ['403','429','503']:
   type(self).mode=status;before=len(self.requests);a=self.ask('Как создать задачу?')[1];self.assertEqual(a['mode'],'error');self.assertEqual(a['error_code'],'http_'+status);self.assertEqual(a['sources'],[]);self.assertEqual(len(self.requests),before+1);self.assertNotIn('fake-private-detail',json.dumps(a))
 def test_empty_model_access_explained(self):
  type(self).mode='no_model';a=self.ask('Привет')[1];self.assertEqual(a['error_code'],'gemini_no_model');self.assertEqual(self.requests,[])
 def test_provider_block_not_faked(self):
  type(self).mode='blocked';a=self.ask('Привет')[1];self.assertEqual(a['error_code'],'gemini_blocked');self.assertEqual(a['mode'],'error')
 def test_private_account_never_sent(self):
  a=self.ask('Мой профиль')[1];self.assertEqual(a['mode'],'account');self.assertEqual(self.requests,[]);self.assertEqual(self.model_lists,0)
 def test_idempotency_only_one_google_generation(self):
  args={'client_id':'gemini-same-request'};a=self.ask('Привет',**args);b=self.ask('Привет',**args);self.assertEqual(a,b);self.assertEqual(len(self.requests),1)
 def test_local_private_pair_excluded_from_history(self):
  a=self.ask('Мой профиль')[1];self.ask('Привет',thread_id=a['thread_id']);self.assertEqual(len(self.requests[-1]['body']['contents']),1)
 def test_saved_history_and_status(self):
  a=self.ask('Привет')[1];h=self.clients['employee'].call('chat/messages',{'id':a['thread_id']})[1];self.assertEqual(h['messages'][-1]['payload']['mode'],'gemini');status=self.clients['employee'].call('ai/status')[1];self.assertEqual(status['build'],'1.4-iPhone');self.assertEqual(status['last_result']['mode'],'gemini');self.assertNotIn('fake-local-google-key',json.dumps(status))
 def test_explicit_model_skips_list(self):
  with patch.dict(os.environ,{'JANA_GEMINI_MODEL':'gemini-custom-flash'}):
   self.ask('Привет');self.assertEqual(self.model_lists,0);self.assertEqual(self.requests[0]['path'],'/models/gemini-custom-flash:generateContent')
 def test_source_revocation_history_removed(self):
  a=self.ask('Как создать задачу?')[1]
  with self.app.connect() as db:db.execute('UPDATE knowledge SET version=version+1 WHERE id=?',(a['sources'][0]['id'],))
  self.ask('А дальше?',thread_id=a['thread_id']);self.assertEqual(len(self.requests[-1]['body']['contents']),1)
 def test_secret_file_not_served(self):
  with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(self.base+'/GEMINI_KEY.txt')
  self.assertEqual(err.exception.code,404)

