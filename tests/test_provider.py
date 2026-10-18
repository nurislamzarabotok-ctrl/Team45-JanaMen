"""Provider adapter contract tests: mocked HTTPS, never consumes owner tokens."""
import json,os,unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import assistant_service as ai
class Response:
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,n):return json.dumps({'choices':[{'message':{'content':json.dumps({'insufficient':False,'claims':[{'text':'Create a request.','source_id':1,'quote':'Заявка создаётся в разделе Мои заявки.'}]})}}]}).encode()
class ProviderTests(unittest.TestCase):
    def test_anymodel_contract(self):
        docs=[{'id':1,'body':'Заявка создаётся в разделе Мои заявки.'}]
        with patch.dict(os.environ,{'JANA_ANYMODEL_TRANSPORT':'urllib','JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'not-a-real-key','JANA_ANYMODEL_MODEL':'am/gpt-oss-20b'}),patch('urllib.request.urlopen',return_value=Response()) as call:
            self.assertEqual(ai.provider_mode(),'anymodel');r=ai.cloud_request('Где создать заявку?',docs,'en');self.assertTrue(ai.validate_claims(r,docs));req=call.call_args.args[0];payload=json.loads(req.data)
            self.assertEqual(req.full_url,'https://anymodel.org/v1/chat/completions');self.assertEqual(payload['model'],'am/gpt-oss-20b');self.assertNotIn('max_tokens',payload);self.assertNotIn('max_completion_tokens',payload);self.assertEqual(call.call_args.kwargs['timeout'],45)
    def test_invalid_or_unauthorised_quotes(self):
        docs=[{'id':1,'body':'Заявка создаётся в разделе Мои заявки.'}]
        self.assertIsNone(ai.validate_claims({'insufficient':False,'claims':[{'text':'Wrong','source_id':2,'quote':docs[0]['body']}]},docs))
        self.assertIsNone(ai.validate_claims({'insufficient':False,'claims':[{'text':'Wrong','source_id':1,'quote':'Это несуществующая цитата из другого документа'}]},docs))
    def test_seven_languages_prompt_contract(self):
        with patch.dict(os.environ,{'JANA_ANYMODEL_TRANSPORT':'urllib','JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'not-a-real-key'}),patch('urllib.request.urlopen',return_value=Response()) as call:
            for lang in ('ru','kk','uz','tg','mn','ky','en'):
                ai.cloud_request('Где создать заявку?',[{'id':1,'body':'Заявка создаётся в разделе Мои заявки.'}],lang)
                self.assertIn({'ru':'русский','kk':'казахский','uz':'узбекский','tg':'таджикский','mn':'монгольский','ky':'кыргызский','en':'английский'}[lang],json.loads(call.call_args.args[0].data)['messages'][0]['content'])
