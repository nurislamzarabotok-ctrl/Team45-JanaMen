"""Team 45: regression tests for ACLs, account lifecycle and collaboration."""
import base64,datetime as dt,json,unittest,urllib.request,urllib.error
import test_app as base
from test_app import Client
class WorkspaceTests(unittest.TestCase):
    setUpClass=classmethod(base.PlatformTests.setUpClass.__func__)
    tearDownClass=classmethod(base.PlatformTests.tearDownClass.__func__)
    # Independent suite; inherited old tests also run on a fresh database.
    def test_30_accounts(self):
        hr=self.clients['hr'];e=self.clients['employee']
        self.assertEqual(e.call('admin/users')[0],403)
        payload={'name':'Новый сотрудник','email':'new@work.local','role':'employee','manager_id':2,'department':'Логистика'}
        code,a=hr.call('admin/user',payload);self.assertEqual(code,200,a);uid=a['id'];pw=a['temporary_password']
        c=Client(self.base);c.login(payload['email'],pw)
        self.assertEqual(c.call('space',{'title':'Нельзя пока','members':[]})[0],403)
        self.assertEqual(c.call('password/change',{'current':pw,'password':'LongNewPass123'})[0],200)
        self.assertEqual(c.call('space',{'title':'Моё','members':[]})[0],200)
        self.assertEqual(hr.call('admin/user',{'id':uid,'op':'reset'})[0],200)
        self.assertEqual(c.call('me')[0],401)
        self.assertEqual(hr.call('admin/user',{'id':uid,'op':'active','active':False})[0],200)
        self.assertEqual(hr.call('admin/user',payload)[0],409)
    def test_31_workspace_acl_and_versions(self):
        e,m,o=self.clients['employee'],self.clients['manager'],self.clients['other']
        code,s=e.call('space',{'title':'Команда теста','members':[2]});self.assertEqual(code,200,s);sid=s['id']
        code,t=e.call('task',{'title':'Проверить накладную','space_id':sid,'assignee_id':2});self.assertEqual(code,200,t)
        tid=t['id'];snap=m.call('snapshot')[1]['extra'];task=next(t for t in snap['tasks'] if t['id']==tid)
        self.assertNotIn(tid,[t['id'] for t in o.call('snapshot')[1]['extra']['tasks']])
        self.assertEqual(o.call('task/comment',{'id':tid,'body':'IDOR'})[0],404)
        update={**task,'status':'doing'};self.assertEqual(m.call('task',update)[0],200)
        self.assertEqual(e.call('task',update)[0],409)
        self.assertEqual(m.call('task/comment',{'id':tid,'body':'Готовлю'})[0],200)
        self.assertEqual(e.call('space',{'id':sid,'title':'Приватно','members':[]})[0],200)
        self.assertNotIn(tid,[t['id'] for t in m.call('snapshot')[1]['extra']['tasks']])
    def test_32_files_search_acl_download(self):
        e,m,o=self.clients['employee'],self.clients['manager'],self.clients['other']
        code,f=e.call('file/upload',{'name':'brief.txt','data':base64.b64encode('Уникальная накладная Алматы'.encode()).decode(),'shares':[2]});self.assertEqual(code,200,f);fid=f['id']
        self.assertEqual(m.call('files/search',{'query':'Алматы'})[1]['files'][0]['id'],fid)
        self.assertEqual(o.call('files/search',{'query':'Алматы'})[1]['files'],[])
        with m.opener.open(self.base+'/api/file/download?id='+str(fid)) as r:self.assertIn('Алматы',r.read().decode());self.assertIn('attachment',r.headers['Content-Disposition'])
        try:o.opener.open(self.base+'/api/file/download?id='+str(fid));self.fail('ACL')
        except urllib.error.HTTPError as err:self.assertEqual(err.code,404)
        self.assertEqual(m.call('file/delete',{'id':fid})[0],404)
        self.assertEqual(e.call('file/delete',{'id':fid})[0],200)
    def test_33_services(self):
        e,hr,o=self.clients['employee'],self.clients['hr'],self.clients['other']
        code,r=e.call('ticket',{'category':'it','title':'Доступ к почте','body':'Нужно создать почтовый ящик'});self.assertEqual(code,200,r);tid=r['id']
        t=next(t for t in hr.call('snapshot')[1]['extra']['tickets'] if t['id']==tid)
        self.assertEqual(o.call('ticket/comment',{'id':tid,'body':'IDOR'})[0],404)
        self.assertEqual(hr.call('ticket',{**t,'status':'progress'})[0],200)
        self.assertEqual(hr.call('ticket',{**t,'status':'resolved'})[0],409)
        self.assertEqual(e.call('ticket/comment',{'id':tid,'body':'Спасибо'})[0],200)
    def test_34_onboarding_and_profile(self):
        e,hr=self.clients['employee'],self.clients['hr']
        self.assertEqual(e.call('onboarding/assign',{'user_id':1})[0],403)
        self.assertEqual(hr.call('onboarding/assign',{'user_id':1})[0],200)
        self.assertEqual(hr.call('onboarding/assign',{'user_id':1})[0],409)
        steps=e.call('snapshot')[1]['extra']['onboarding'];step=next(x for x in steps if not x['course_id'])
        self.assertEqual(e.call('onboarding/check',{'id':step['id'],'done':True})[0],200)
        self.assertEqual(e.call('profile/change',{'body':'Уточните должность'})[0],200)
        p=hr.call('snapshot')[1]['extra']['profile_changes'][0]
        self.assertEqual(e.call('profile/resolve',{'id':p['id']})[0],403)
        self.assertEqual(hr.call('profile/resolve',{'id':p['id']})[0],200)
    def test_35_knowledge_and_chat(self):
        hr,e,o=self.clients['hr'],self.clients['employee'],self.clients['other']
        self.assertEqual(e.call('knowledge/save',{'title':'x','body':'x'})[0],403)
        code,k=hr.call('knowledge/save',{'title':'Алматы доступ','body':'Доступ в офис выдаёт администратор.','keywords':'алматы','audience':'hr'});self.assertEqual(code,200,k)
        self.assertNotIn(k['id'],[d['id'] for d in e.call('knowledge')[1]['documents']])
        code,a=e.call('assistant',{'question':'Как оформить отпуск?'});self.assertEqual(code,200,a);tid=a['thread_id']
        self.assertEqual(len(e.call('chat/messages',{'id':tid})[1]['messages']),2)
        self.assertEqual(o.call('chat/messages',{'id':tid})[0],404)
        self.assertEqual(o.call('chat/delete',{'id':tid})[0],404)
        self.assertEqual(e.call('chat/delete',{'id':tid})[0],200)
    def test_36_leave_edit_withdraw(self):
        e=self.clients['employee'];start=dt.date.today()+dt.timedelta(days=310);end=start+dt.timedelta(days=2)
        code,r=e.call('request',{'start':str(start),'end':str(end)});self.assertEqual(code,200,r);rid=r['request']['id']
        self.assertEqual(e.call('request/manage',{'id':rid,'op':'edit','start':str(start+dt.timedelta(days=4)),'end':str(end+dt.timedelta(days=4)),'expected_start':str(start),'expected_end':str(end)})[0],200)
        self.assertEqual(e.call('request/manage',{'id':rid,'op':'withdraw'})[0],200)
        self.assertEqual(e.call('request/action',{'id':rid,'action':'approved'})[0],403)
        self.assertEqual(self.clients['manager'].call('request/action',{'id':rid,'action':'approved'})[0],409)
        doc=e.call('request/document',{'id':rid});self.assertEqual(doc[0],200);self.assertIn('ЭЦП',doc[1]['text'])
    def test_37_analytics_and_course_author(self):
        e,hr=self.clients['employee'],self.clients['hr']
        self.assertEqual(e.call('analytics')[0],403)
        self.assertEqual(hr.call('analytics')[0],200)
        self.assertEqual(hr.call('course/admin',{'title':'Новый курс','content':[{'title':'Материал','text':'Прочитайте материал'}],'questions':[{'text':'Вопрос','options':['Да','Нет'],'correct':0}]*3})[0],200)
        snap=e.call('snapshot')[1];self.assertIn('extra',snap);self.assertNotIn('password',json.dumps(snap,ensure_ascii=False))
    def test_38_reminder_dedup(self):
        e=self.clients['employee'];today=str(dt.date.today())
        self.assertEqual(e.call('task',{'title':'Сегодня проверить','due_date':today})[0],200)
        a=e.call('snapshot')[1];n=sum(x['title']=='Напоминание о сроке' for x in a['notifications'])
        b=e.call('snapshot')[1];self.assertEqual(n,sum(x['title']=='Напоминание о сроке' for x in b['notifications']));self.assertGreater(n,0)
    def test_39_notes_and_attempts(self):
        e,o=self.clients['employee'],self.clients['other'];code,n=e.call('note',{'title':'Личное','body':'Секретная идея'});self.assertEqual(code,200)
        self.assertEqual(o.call('note',{'id':n['id'],'version':1,'title':'IDOR','body':'x'})[0],404)
        self.assertEqual(e.call('note',{'id':n['id'],'version':1,'title':'Правка','body':'x'})[0],200)
        self.assertEqual(e.call('note',{'id':n['id'],'version':1,'title':'Старая правка','body':'x'})[0],409)
        e.call('course/progress',{'id':1});self.assertEqual(e.call('course/submit',{'id':1,'answers':[0,1,2,0,0,1]})[0],200)
        self.assertGreater(len(e.call('snapshot')[1]['extra']['quiz_attempts']),0)
    def test_40_delegation(self):
        hr=self.clients['hr'];code,u=hr.call('admin/user',{'name':'Замещающий','email':'delegate@work.local','role':'manager'});self.assertEqual(code,200,u)
        d=Client(self.base);d.login('delegate@work.local',u['temporary_password']);d.call('password/change',{'current':u['temporary_password'],'password':'DelegatePass123'})
        self.assertNotIn(1,[r['id'] for r in d.call('requests')[1]['requests']])
        manager=next(x for x in hr.call('admin/users')[1]['users'] if x['id']==2);manager['delegate_id']=u['id']
        self.assertEqual(hr.call('admin/user',manager)[0],200)
        self.assertIn(1,[r['id'] for r in d.call('requests')[1]['requests']])
        manager['delegate_id']=None;self.assertEqual(hr.call('admin/user',manager)[0],200)
        self.assertNotIn(1,[r['id'] for r in d.call('requests')[1]['requests']])
if __name__=='__main__':unittest.main()
