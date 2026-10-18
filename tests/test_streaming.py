"""Streaming contract tests: no live API calls, no real keys."""
import io,json,os,unittest
from unittest.mock import patch
import assistant_service as ai
class StreamingTests(unittest.TestCase):
 def stream(self,parts,end=True):
  lines=[]
  for part in parts:lines.append('data: '+json.dumps({'choices':[{'index':0,'delta':{'content':part}}]},ensure_ascii=False)+'\n\n')
  if end:lines.append('data: [DONE]\n\n')
  return io.BytesIO(''.join(lines).encode())
 def test_unicode_stream_contract(self):
  docs=[{'id':1,'body':'Заявка создаётся в разделе Мои заявки.'}];obj={'insufficient':False,'claims':[{'text':'Откройте Мои заявки.','source_id':1,'quote':docs[0]['body']}]};text=json.dumps(obj,ensure_ascii=False)
  with patch.dict(os.environ,{'JANA_ANYMODEL_TRANSPORT':'urllib','JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-test-key'}),patch('urllib.request.urlopen',return_value=self.stream([text[:35],text[35:]])) as call:
   result=ai.cloud_request('Где создать заявку?',docs,'ru');self.assertTrue(ai.validate_claims(result,docs));payload=json.loads(call.call_args.args[0].data);self.assertIs(payload['stream'],True);self.assertNotIn('response_format',payload)
 def test_plain_json_also_supported(self):
  r=io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"insufficient":true,"claims":[]}'}}]}).encode());self.assertTrue(ai._claims_json(ai._provider_message(r))['insufficient'])
 def test_truncated_stream_rejected(self):
  with self.assertRaises(ValueError):ai._provider_message(self.stream(['{"claims":[] }'],end=False))
 def test_stream_error_rejected(self):
  with self.assertRaises(ValueError):ai._provider_message(io.BytesIO(b'data: {"error":{"message":"private upstream detail"}}\n\n'))
 def test_oversized_response_rejected(self):
  with self.assertRaises(ValueError):ai._provider_message(io.BytesIO(b'x'*262145))
 def test_reasoning_is_not_answer(self):
  r=io.BytesIO(b'data: {"choices":[{"delta":{"reasoning_content":"not user output"}}]}\n\ndata: [DONE]\n\n')
  with self.assertRaises(ValueError):ai._provider_message(r)
