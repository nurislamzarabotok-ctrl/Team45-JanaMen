import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import ai_config as config
class ConfigurationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.env=patch.dict(os.environ,{k:v for k,v in os.environ.items() if not k.startswith('JANA_')},clear=True);self.env.start();self.addCleanup(self.env.stop)
  self.path=patch.object(config,'ROOT',self.root);self.path.start();self.addCleanup(self.path.stop)
 def test_no_key_is_local(self):self.assertEqual(config.settings()['provider'],'extractive')
 def test_one_key_is_enough(self):
  (self.root/'AI_KEY.txt').write_text('fake-owner-key\n');s=config.settings();self.assertEqual(s['provider'],'anymodel');self.assertEqual(s['transport'],'curl')
 def test_placeholder_is_not_key(self):
  (self.root/'AI_KEY.txt').write_text('PASTE_YOUR_ANYMODEL_API_KEY_HERE');self.assertFalse(config.settings()['configured'])
 def test_bom_key(self):
  (self.root/'AI_KEY.txt').write_text('fake-owner-key',encoding='utf-8-sig');self.assertTrue(config.settings()['configured'])
 def test_hot_reload(self):
  p=self.root/'AI_KEY.txt';p.write_text('first-fake-key');self.assertEqual(config.settings()['key'],'first-fake-key');p.write_text('second-fake-key');self.assertEqual(config.settings()['key'],'second-fake-key')
 def test_keyfile_overrides_old_env_file_key(self):
  (self.root/'.env').write_text('JANA_AI_PROVIDER=extractive\nJANA_ANYMODEL_API_KEY=old-fake-key');(self.root/'AI_KEY.txt').write_text('new-fake-key');s=config.settings();self.assertEqual(s['provider'],'anymodel');self.assertEqual(s['key'],'new-fake-key')
 def test_environment_explicit_offline(self):
  (self.root/'AI_KEY.txt').write_text('fake-owner-key')
  with patch.dict(os.environ,{'JANA_AI_PROVIDER':'extractive'}):self.assertEqual(config.settings()['provider'],'extractive')
 def test_public_status_never_contains_key(self):
  (self.root/'AI_KEY.txt').write_text('secret-that-must-not-leak');s=config.public_settings();self.assertNotIn('key',s);self.assertNotIn('secret-that-must-not-leak',str(s))
 def test_header_injection_not_accepted(self):self.assertFalse(config.valid_key('bad\r\nInjected: yes'))
 def test_bad_number_does_not_crash(self):
  (self.root/'.env').write_text('JANA_AI_TIMEOUT=bad');self.assertEqual(config.settings()['config_error'],'config_number')
 def test_oversized_key_file_rejected(self):
  (self.root/'AI_KEY.txt').write_text('x'*5000);self.assertFalse(config.settings()['configured']);self.assertEqual(config.settings()['config_error'],'key_file')
 def test_missing_curl_reported(self):
  (self.root/'AI_KEY.txt').write_text('fake-owner-key')
  with patch('ai_config.shutil.which',return_value=None):self.assertEqual(config.settings()['config_error'],'curl_missing')
