"""PWA/public-host regression; local requests only, no secrets or public publication."""
import json,os,importlib.util,tempfile,unittest,urllib.request
from pathlib import Path
from unittest.mock import patch
import test_app
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mobile_setup',ROOT/'scripts/setup_public_url.py');setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
class MobileSetupTests(unittest.TestCase):
 def test_origin_normalized(self):self.assertEqual(setup.normalize_url('https://HR.example.com:443/'),'https://hr.example.com')
 def test_bad_url_rejected(self):
  for u in ['http://hr.example.com','https://user:pass@example.com','https://example.com/path','https://example.com?key=x','https://example.com#hash','https://localhost','https://127.0.0.1','javascript:alert(1)']:
   with self.assertRaises(ValueError,msg=u):setup.normalize_url(u)
 def test_preserves_existing_env_and_no_duplicate(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'.env';p.write_text('# existing settings\nJANA_GEMINI_MODEL=auto\nJANA_PUBLIC_URL=https://old.example.com\nJANA_ANYMODEL_API_KEY=fake-local-key\n');setup.save_url(d,'https://new.example.com');s=p.read_text();self.assertIn('JANA_ANYMODEL_API_KEY=fake-local-key',s);self.assertIn('JANA_GEMINI_MODEL=auto',s);self.assertEqual(s.count('JANA_PUBLIC_URL='),1);self.assertIn('https://new.example.com',s)
 def test_invalid_origin_does_not_write(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):setup.save_url(d,'http://invalid.example.com')
   self.assertFalse((Path(d)/'.env').exists())
class MobileHttpTests(unittest.TestCase):
 setUpClass=classmethod(test_app.PlatformTests.setUpClass.__func__)
 tearDownClass=classmethod(test_app.PlatformTests.tearDownClass.__func__)
 def test_mobile_files_served(self):
  for name in ['mobile.js','mobile.css','assets/apple-touch-icon.png','manifest.webmanifest','sw.js','offline.html']:
   with urllib.request.urlopen(self.base+'/'+name) as res:self.assertEqual(res.status,200)
 def test_viewport_and_apple_metadata(self):
  with urllib.request.urlopen(self.base) as res:s=res.read().decode()
  self.assertIn('viewport-fit=cover',s);self.assertIn('apple-mobile-web-app-capable',s);self.assertIn('/mobile.js',s);self.assertIn('/mobile.css',s)
 def test_manifest_installable(self):
  with urllib.request.urlopen(self.base+'/manifest.webmanifest') as res:m=json.load(res)
  self.assertEqual(m['display'],'standalone');self.assertEqual(m['start_url'],'/');self.assertTrue(any(i['sizes']=='180x180' for i in m['icons']))
 def test_public_https_cookie_and_csrf(self):
  with patch.dict(os.environ,{'JANA_PUBLIC_URL':'https://phone.example.test'}):
   req=urllib.request.Request(self.base+'/api/login',data=json.dumps({'email':'employee@demo.local','password':self.pw}).encode(),headers={'Content-Type':'application/json','Host':'phone.example.test','Origin':'https://phone.example.test'})
   with urllib.request.urlopen(req) as res:
    cookie=res.headers['Set-Cookie'];self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
 def test_unknown_host_denied(self):
  from urllib.error import HTTPError
  req=urllib.request.Request(self.base,headers={'Host':'unknown.example.test'})
  with self.assertRaises(HTTPError) as e:urllib.request.urlopen(req)
  self.assertEqual(e.exception.code,403)
 def test_secret_key_not_served(self):
  from urllib.error import HTTPError
  for name in ['GEMINI_KEY.txt','.env','data/DEMO-ACCOUNTS.txt']:
   with self.assertRaises(HTTPError) as e:urllib.request.urlopen(self.base+'/'+name)
   self.assertEqual(e.exception.code,404)
