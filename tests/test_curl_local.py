"""Real curl process against LOCAL stub only, never against the provider."""
import json,os,shutil,subprocess,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
import ai_transport
class LocalCurlTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.curl=shutil.which('curl.exe') or shutil.which('curl')
  if not cls.curl:raise unittest.SkipTest('curl is unavailable')
  cls.mode='sse';cls.seen={}
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    cls.seen=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
    if cls.mode=='403':self.send_response(403);self.end_headers();return
    obj={'insufficient':False,'claims':[{'text':'Откройте Workspace.','source_id':7,'quote':'Общая задача доступна участникам пространства.'}]};content=json.dumps(obj,ensure_ascii=False)
    if cls.mode=='sse':body=('data: '+json.dumps({'choices':[{'delta':{'content':content}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode()
    else:body=json.dumps({'choices':[{'message':{'content':content}}]},ensure_ascii=False).encode()
    self.send_response(200);self.send_header('Content-Type','text/event-stream' if cls.mode=='sse' else 'application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  cls.stub=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.worker=threading.Thread(target=cls.stub.serve_forever,daemon=True);cls.worker.start()
 @classmethod
 def tearDownClass(cls):cls.stub.shutdown();cls.stub.server_close();cls.worker.join()
 def call(self,mode):
  type(self).mode=mode;real_run=subprocess.run
  def routed(args,**kwargs):
   kwargs['input']=kwargs['input'].replace(b'https://anymodel.org/v1/chat/completions',('http://127.0.0.1:'+str(self.stub.server_port)+'/v1/chat/completions').encode());return real_run(args,**kwargs)
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-local-key','JANA_ANYMODEL_TRANSPORT':'curl'}),patch('ai_transport.subprocess.run',side_effect=routed):return ai_transport.cloud_request('Как создать задачу?', [{'id':7,'body':'Общая задача доступна участникам пространства.'}],'ru')
 def test_real_curl_sse_unicode(self):
  out=self.call('sse');self.assertEqual(out['claims'][0]['text'],'Откройте Workspace.');self.assertEqual(self.seen['messages'][0]['role'],'system');self.assertTrue(self.seen['stream'])
 def test_real_curl_json(self):self.assertFalse(self.call('json')['insufficient'])
 def test_real_curl_http403_classified(self):
  with self.assertRaises(ai_transport.AIError) as e:self.call('403')
  self.assertEqual(e.exception.code,'http_403')
