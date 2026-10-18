"""Mocked curl contracts. No real API requests or credentials."""
import json,os,subprocess,unittest,urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import assistant_service as ai
class CurlTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_TRANSPORT':'curl','JANA_ANYMODEL_API_KEY':'fake-curl-test-key'});self.env.start();self.addCleanup(self.env.stop)
  self.which=patch('assistant_service.shutil.which',return_value='curl.exe');self.which.start();self.addCleanup(self.which.stop)
 def response(self,args,**kwargs):
  content=json.dumps({'insufficient':False,'claims':[{'text':'Откройте Мои заявки.','source_id':1,'quote':'Заявка создаётся в разделе Мои заявки.'}]},ensure_ascii=False)
  raw='data: '+json.dumps({'choices':[{'delta':{'content':content}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n'
  Path(args[args.index('--output')+1]).write_bytes(raw.encode());return SimpleNamespace(stdout=b'200',stderr=b'',returncode=0)
 def test_curl_answer_and_no_key_in_args(self):
  with patch('assistant_service.subprocess.run',side_effect=self.response) as call:
   result=ai.cloud_request('Где создать заявку?',[{'id':1,'body':'Заявка создаётся в разделе Мои заявки.'}],'ru');self.assertTrue(result['claims']);args=call.call_args.args[0];self.assertNotIn('fake-curl-test-key',' '.join(args));self.assertIn('--config',args);self.assertNotIn('--insecure',args);self.assertNotIn('--retry',args);self.assertNotIn('--location',args)
   cfg=call.call_args.kwargs['input'].decode();data=next(l for l in cfg.splitlines() if l.startswith('data = '));payload=json.loads(json.loads(data.split(' = ',1)[1]));self.assertEqual(set(payload),{'model','messages','stream'});self.assertEqual(payload['messages'][0]['role'],'system')
 def test_http403_is_diagnostic(self):
  with patch('assistant_service.subprocess.run',return_value=SimpleNamespace(stdout=b'403',stderr=b'private detail',returncode=0)):
   with self.assertRaises(urllib.error.HTTPError) as e:ai._anymodel_curl({})
   self.assertEqual(e.exception.code,403);self.assertNotIn('private detail',str(e.exception))
 def test_curl_timeout(self):
  with patch('assistant_service.subprocess.run',return_value=SimpleNamespace(stdout=b'000',stderr=b'',returncode=28)):
   with self.assertRaises(TimeoutError):ai._anymodel_curl({})
 def test_process_timeout(self):
  with patch('assistant_service.subprocess.run',side_effect=subprocess.TimeoutExpired(['curl'],20)):
   with self.assertRaises(TimeoutError):ai._anymodel_curl({})
 def test_no_curl(self):
  with patch('assistant_service.shutil.which',return_value=None):
   with self.assertRaises(RuntimeError):ai._anymodel_curl({})
 def test_header_injection_rejected(self):
  with patch.dict(os.environ,{'JANA_ANYMODEL_API_KEY':'bad\r\nheader'}),patch('assistant_service.subprocess.run') as run:
   with self.assertRaises(ValueError):ai._anymodel_curl({})
   run.assert_not_called()
