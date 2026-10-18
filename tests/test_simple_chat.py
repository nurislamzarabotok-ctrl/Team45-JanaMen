"""Default conversational mode: API, privacy, history, errors and transport. No live API."""
import io,json,os,subprocess,threading,unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from test_app import PlatformTests
import assistant_service as ai
import ai_config,ai_transport
class SimpleChatTests(unittest.TestCase):
 setUpClass=classmethod(PlatformTests.setUpClass.__func__)
 tearDownClass=classmethod(PlatformTests.tearDownClass.__func__)
 def setUp(self):
  self.env=patch.dict(os.environ,{'JANA_AI_CHAT_MODE':'chat','JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-chat-only','JANA_AI_DAILY_LIMIT':'0'});self.env.start();self.addCleanup(self.env.stop);self.server.ai_attempts={}
 def ask(self,q,**kw):return self.clients['employee'].call('assistant',dict(question=q,**kw))
 def test_greeting_calls_model(self):
  with patch.object(ai,'chat_request',return_value='Привет от модели!') as call:
   code,out=self.ask('Привет');self.assertEqual(code,200);self.assertEqual(out['answer'],'Привет от модели!');self.assertEqual(out['mode'],'anymodel');call.assert_called_once()
 def test_no_document_is_not_a_refusal(self):
  with patch.object(ai,'chat_request',return_value='Четыре.') as call:
   out=self.ask('Сколько будет два плюс два?')[1];self.assertEqual(out['answer'],'Четыре.');call.assert_called_once();self.assertNotIn('claims',out)
 def test_old_word_blacklist_removed(self):
  with patch.object(ai,'chat_request',return_value='Уточните правила у HR.') as call:
   self.ask('Как сотруднику уточнить зарплату и больничный?');call.assert_called_once()
 def test_followup_gets_both_roles(self):
  with patch.object(ai,'chat_request',side_effect=['Я работаю через AnyModel.','Да, текущий запрос обработан.']) as call:
   out=self.ask('Через какую модель ты работаешь?')[1];self.ask('Сейчас они включены? Если да, скажи Ноу',thread_id=out['thread_id'])
   history=call.call_args.kwargs['history'];self.assertEqual(history[-2]['content'],'Через какую модель ты работаешь?');self.assertEqual(history[-1]['content'],'Я работаю через AnyModel.')
 def test_error_never_masquerades_as_model_or_excerpt(self):
  for error in ['http_403','timeout','http_429','invalid_response']:
   with patch.object(ai,'chat_request',side_effect=ai.AIError(error)):
    out=self.ask('Привет')[1];self.assertEqual(out['mode'],'error');self.assertEqual(out['error_code'],error);self.assertEqual(out['sources'],[]);self.assertNotIn('fake-chat-only',json.dumps(out))
 def test_private_account_tool_not_sent(self):
  with patch.object(ai,'chat_request') as call:
   out=self.ask('Мои задачи')[1];self.assertEqual(out['mode'],'account');call.assert_not_called()
 def test_account_pair_not_in_cloud_history(self):
  tid=self.ask('Мой профиль')[1]['thread_id']
  with patch.object(ai,'chat_request',return_value='Привет!') as call:
   self.ask('Привет',thread_id=tid);self.assertEqual(call.call_args.kwargs['history'],[])
 def test_revoked_context_not_reused(self):
  with patch.object(ai,'chat_request',return_value='Откройте Workspace.') as call:
   out=self.ask('Как создать задачу?')[1]
   with self.app.connect() as db:db.execute('UPDATE knowledge SET version=version+1 WHERE id=?',(out['sources'][0]['id'],))
   self.ask('А дальше?',thread_id=out['thread_id']);self.assertEqual(call.call_args.kwargs['history'],[])
 def test_context_is_role_filtered(self):
  with patch.object(ai,'chat_request',return_value='Привет!') as call:
   self.ask('Привет');docs=call.call_args.args[1];self.assertTrue(docs);self.assertFalse(any(d.get('audience')=='hr' for d in docs));self.assertLessEqual(sum(len(d['body']) for d in docs),22000)
 def test_repeated_client_id_only_one_call(self):
  with patch.object(ai,'chat_request',return_value='Ответ модели') as call:
   a=self.ask('Привет',client_id='new-mode-duplicate');b=self.ask('Привет',client_id='new-mode-duplicate');self.assertEqual(a,b);self.assertEqual(call.call_count,1)
 def test_no_key_returns_error_not_canned_reply(self):
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'extractive'}),patch.object(ai,'chat_request') as call:
   out=self.ask('Привет')[1];self.assertEqual(out['mode'],'error');self.assertEqual(out['error_code'],'not_configured');call.assert_not_called()
 def test_default_mode_is_chat_and_no_daily_cap(self):
  with patch.dict(os.environ,clear=True),patch.object(ai_config,'ROOT',self.app.ROOT/'nonexistent-test-config'):
   s=ai_config.settings();self.assertEqual(s['chat_mode'],'chat');self.assertEqual(s['daily_limit'],0)
class SimpleTransportTests(unittest.TestCase):
 def test_plain_sse_and_history_no_json_required(self):
  body=('data: '+json.dumps({'choices':[{'delta':{'content':'Да, Ноу!'}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode()
  class Response(io.BytesIO):
   def __exit__(self,*args):self.close()
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-chat-key','JANA_ANYMODEL_TRANSPORT':'urllib'}),patch('urllib.request.urlopen',return_value=Response(body)) as call:
   out=ai_transport.chat_request('Сейчас включено?',[],history=[{'role':'user','content':'Ты работаешь?'},{'role':'assistant','content':'Да.'}]);self.assertEqual(out,'Да, Ноу!')
   p=json.loads(call.call_args.args[0].data);self.assertNotIn('response_format',p);self.assertEqual([m['role'] for m in p['messages']][-3:],['user','assistant','user']);self.assertIn('am/gpt-oss-20b',p['messages'][0]['content']);self.assertNotIn('fake-chat-key',json.dumps(p))
 def test_real_curl_plain_text_local_only(self):
  seen={}
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    seen.update(json.loads(self.rfile.read(int(self.headers['Content-Length']))));text='Ноу — модель отвечает.'
    body=('data: '+json.dumps({'choices':[{'delta':{'content':text}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  stub=ThreadingHTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=stub.serve_forever,daemon=True);t.start();real_run=subprocess.run
  def routed(args,**kwargs):
   kwargs['input']=kwargs['input'].replace(b'https://anymodel.org/v1/chat/completions',f'http://127.0.0.1:{stub.server_port}/v1/chat/completions'.encode());return real_run(args,**kwargs)
  try:
   with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-local-key','JANA_ANYMODEL_TRANSPORT':'curl'}),patch('ai_transport.subprocess.run',side_effect=routed):
    self.assertEqual(ai_transport.chat_request('Скажи Ноу',[]),'Ноу — модель отвечает.');self.assertTrue(seen['stream']);self.assertEqual(seen['messages'][-1]['content'],'Скажи Ноу')
  finally:stub.shutdown();stub.server_close();t.join()
del PlatformTests
