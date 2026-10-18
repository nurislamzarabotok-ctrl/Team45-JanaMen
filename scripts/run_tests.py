"""Run the entire suite while forbidding real provider requests."""
import os,sys,unittest,urllib.parse,urllib.request,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
real_urlopen=urllib.request.urlopen;real_run=subprocess.run

def local_urlopen(req,*a,**kw):
 url=req.full_url if hasattr(req,'full_url') else str(req)
 if urllib.parse.urlsplit(url).hostname not in ('127.0.0.1','localhost','::1'):raise AssertionError('Tests cannot call external HTTP endpoints')
 return real_urlopen(req,*a,**kw)
def local_subprocess(args,*a,**kw):
 # Mocked provider tests intercept this function; real curl is allowed only for local stubs.
 if isinstance(args,(list,tuple)) and args and 'curl' in str(args[0]).lower():
  data=kw.get('input',b'');data=data.decode('utf-8',errors='replace') if isinstance(data,bytes) else str(data)
  if '--config' not in args or not any('url = "http://'+host in data for host in ('127.0.0.1:','localhost:','[::1]:')):raise AssertionError('Tests cannot call real curl provider endpoints')
 return real_run(args,*a,**kw)
urllib.request.urlopen=local_urlopen;subprocess.run=local_subprocess
import gemini_transport
real_gemini_open=gemini_transport._open
def local_gemini_open(req,timeout):
 if urllib.parse.urlsplit(req.full_url).hostname not in ('127.0.0.1','localhost','::1'):raise AssertionError('Tests cannot call real Google endpoints')
 return real_gemini_open(req,timeout)
gemini_transport._open=local_gemini_open
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(verbosity=2).run(suite)
print('External provider requests were forbidden during this test run.')
sys.exit(0 if result.wasSuccessful() else 1)
