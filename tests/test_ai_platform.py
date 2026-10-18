"""Full authenticated assistant API, mocked provider only."""
import json,os,time,threading,unittest
from unittest.mock import patch
from test_app import PlatformTests,Client
import assistant_service as ai
class AssistantPlatformTests(unittest.TestCase):
 setUpClass=classmethod(PlatformTests.setUpClass.__func__)
 tearDownClass=classmethod(PlatformTests.tearDownClass.__func__)
 def reset_rate(self):self.server.ai_attempts={}
 def fake(self,q,docs,lang):
  d=docs[0];return {'insufficient':False,'claims':[{'text':'Проверенный ответ по '+d['title']+'.','source_id':d['id'],'quote':d['body'][:120]}]}
 def ask(self,q,**kw):return self.clients['employee'].call('assistant',dict(question=q,**kw))
 def test_01_status_is_private_and_safe(self):
  self.assertEqual(Client(self.base).call('ai/status')[0],401)
  status=self.clients['employee'].call('ai/status')[1];self.assertNotIn('key',status);self.assertNotIn('API_KEY',json.dumps(status))
 def test_02_every_main_section_retrieved(self):
  with self.app.connect() as db:
   docs=[dict(r) for r in db.execute("SELECT * FROM knowledge WHERE audience='all'")]
  for q,title in [('Как создать задачу?','Workspace:'),('Как передать файл коллеге?','Документы:'),('Как создать обращение в IT?','Сервисы:'),('Где маршрут адаптации?','Адаптация:'),('Как восстановить пароль?','Вход,'),('Как открыть календарь?','Календарь'),('Как установить на телефон?','Мобильный'),('Что умеет платформа?','Возможности')]:
   self.assertTrue(ai.ranked_docs(q,docs)[0]['title'].startswith(title),(q,ai.ranked_docs(q,docs)))
 def test_03_greeting_and_offtopic(self):
  self.reset_rate()
  with patch.object(ai,'cloud_request') as cloud:
   self.assertEqual(self.ask('Привет!')[1]['mode'],'help');self.assertEqual(self.ask('Напиши рецепт пиццы')[1]['mode'],'no_answer');cloud.assert_not_called()
 def test_04_private_tools_never_go_to_model(self):
  self.reset_rate()
  with patch.object(ai,'cloud_request') as cloud:
   for q in ['Мои задачи','Мои курсы','Мой профиль','Мои обращения','Мой остаток отпуска','Мои заявки']:
    code,out=self.ask(q);self.assertEqual(code,200);self.assertEqual(out['mode'],'account',out)
   cloud.assert_not_called()
 def test_05_model_flows_through_actual_endpoint(self):
  self.reset_rate()
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-key','JANA_AI_DAILY_LIMIT':'100'}),patch.object(ai,'cloud_request',side_effect=self.fake):
   code,out=self.ask('Как создать задачу?');self.assertEqual(code,200);self.assertEqual(out['mode'],'anymodel');self.assertTrue(out['source_versions']);tid=out['thread_id']
   messages=self.clients['employee'].call('chat/messages',{'id':tid})[1]['messages'];self.assertEqual(messages[-1]['body'],out['answer'])
   last=self.clients['employee'].call('ai/status')[1]['last_result'];self.assertEqual(last['mode'],'anymodel')
 def test_06_idempotency_prevents_second_paid_call(self):
  self.reset_rate();request={'question':'Как оформить отпуск?','client_id':'same-request-1234'}
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-key'}),patch.object(ai,'cloud_request',side_effect=self.fake) as cloud:
   first=self.clients['employee'].call('assistant',request);again=self.clients['employee'].call('assistant',request);self.assertEqual(first,again);self.assertEqual(cloud.call_count,1)
   self.assertEqual(self.clients['employee'].call('assistant',dict(request,question='Как пройти курс?'))[0],409)
 def test_07_provider_error_is_explained_without_secrets(self):
  self.reset_rate()
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-key'}),patch.object(ai,'cloud_request',side_effect=ai.AIError('http_403')):
   out=self.ask('Как оформить отпуск?')[1];self.assertEqual(out['mode'],'extractive_fallback');self.assertEqual(out['error_code'],'http_403');self.assertIn('403',out['notice']);self.assertNotIn('fake-key',json.dumps(out))
 def test_08_source_edit_invalidates_old_history_and_cached_response(self):
  self.reset_rate();req={'question':'Как создать задачу?','client_id':'source-change-1234'}
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-key'}),patch.object(ai,'cloud_request',side_effect=self.fake):out=self.clients['employee'].call('assistant',req)[1]
  source=out['sources'][0]['id']
  with self.app.connect() as db:db.execute('UPDATE knowledge SET version=version+1 WHERE id=?',(source,))
  hist=self.clients['employee'].call('chat/messages',{'id':out['thread_id']})[1]['messages'];self.assertEqual(hist[-1]['payload']['mode'],'no_answer');self.assertEqual(self.clients['employee'].call('assistant',req)[1]['error_code'],'source_changed')
 def test_09_slow_provider_does_not_lock_workspace(self):
  self.reset_rate();entered=threading.Event();release=threading.Event();answers=[]
  def slow(q,d,l):entered.set();release.wait(5);return self.fake(q,d,l)
  e=Client(self.base);e.login('employee@demo.local',self.pw)
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-key'}),patch.object(ai,'cloud_request',side_effect=slow):
   thread=threading.Thread(target=lambda:answers.append(e.call('assistant',{'question':'Как оформить отпуск?'})));thread.start();self.assertTrue(entered.wait(3));start=time.monotonic()
   try:
    code,_=self.clients['hr'].call('note',{'title':'Параллельно с AI','body':'Сервер не заблокирован.'});self.assertEqual(code,200);self.assertLess(time.monotonic()-start,1.5)
   finally:release.set();thread.join(6)
  self.assertEqual(answers[0][0],200)
 def test_10_cross_user_thread_is_forbidden(self):
  self.reset_rate();tid=self.ask('Привет!')[1]['thread_id'];self.assertEqual(self.clients['hr'].call('chat/messages',{'id':tid})[0],404)
 def test_11_seven_languages_scope_answers(self):
  self.reset_rate()
  for lang in ('ru','kk','uz','tg','mn','ky','en'):
   out=self.ask('Напиши рецепт пиццы',lang=lang)[1];self.assertEqual(out['mode'],'no_answer');self.assertEqual(out['answer'],ai.REFUSALS[lang])
 def test_12_bad_inputs_rejected(self):
  self.reset_rate();self.assertEqual(self.ask({'not':'text'})[0],400);self.assertEqual(self.ask('Как оформить отпуск?',client_id='bad!')[0],400)
 def test_13_secret_files_cannot_be_downloaded(self):
  import urllib.request,urllib.error
  for path in ['/AI_KEY.txt','/.env','/ai_config.py']:
   with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(self.base+path)
   self.assertEqual(e.exception.code,404)
 def test_14_followup_uses_previous_question(self):
  self.reset_rate()
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-key'}),patch.object(ai,'cloud_request',side_effect=self.fake) as cloud:
   out=self.ask('Как создать задачу?')[1];self.ask('А где это?',thread_id=out['thread_id']);self.assertIn('Как создать задачу?',cloud.call_args.args[0])
 def test_15_pending_request_is_not_sent_twice(self):
  self.reset_rate();client=self.clients['employee'];req={'question':'Как оформить отпуск?','client_id':'pending-request-123'}
  import hashlib
  fingerprint=hashlib.sha256(json.dumps([req['question'],None,'ru'],ensure_ascii=False).encode()).hexdigest()
  with self.app.connect() as db:db.execute('INSERT INTO ai_turns(user_id,request_key,question_hash,status,created_at) VALUES(?,?,?,?,?)',(1,req['client_id'],fingerprint,'pending',time.time()))
  with patch.object(ai,'cloud_request') as cloud:self.assertEqual(client.call('assistant',req)[0],409);cloud.assert_not_called()
del PlatformTests
