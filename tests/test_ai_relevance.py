"""Regression for the owner's reported background/profile mismatch."""
import os,sqlite3,unittest
from unittest.mock import patch
import assistant_service as ai
from test_app import PlatformTests
class RelevanceTests(unittest.TestCase):
 setUpClass=classmethod(PlatformTests.setUpClass.__func__)
 tearDownClass=classmethod(PlatformTests.tearDownClass.__func__)
 def inputs(self,db):
  docs=[dict(r) for r in db.execute("SELECT * FROM knowledge WHERE audience='all'")];u=dict(db.execute('SELECT * FROM users WHERE id=1').fetchone());return docs,u
 def test_background_selects_theme_not_profile(self):
  with self.app.connect() as db:docs,u=self.inputs(db)
  for q in ['Как изменить Цвет Фона?','Как включить тёмную тему?','How to change background?']:
   found=ai.ranked_docs(q,docs);self.assertTrue(found);self.assertTrue(found[0]['title'].startswith('Оформление:'));self.assertFalse(any(d['id']==3 for d in found))
 def test_model_insufficient_does_not_dump_unrelated_text(self):
  with self.app.connect() as db:
   docs,u=self.inputs(db)
   with patch.dict(os.environ,{'JANA_AI_PROVIDER':'anymodel','JANA_ANYMODEL_API_KEY':'fake-test-key'}),patch.object(ai,'cloud_request',return_value={'insufficient':True,'claims':[]}):out=ai.grounded_answer(db,'Как изменить Цвет Фона?',docs,[],u)
  self.assertEqual(out['mode'],'no_answer');self.assertEqual(out['sources'],[]);self.assertNotIn('1С',out['answer']);self.assertEqual(out['error_code'],'insufficient')
 def test_ui_knowledge_migrates_existing_db_once(self):
  import ai_knowledge
  with self.app.connect() as db:
   db.execute("DELETE FROM knowledge WHERE title LIKE 'Оформление:%'");db.execute("DELETE FROM schema_changes WHERE name='ai-ui-knowledge-v1'");db.commit();ai_knowledge.initialize(db);ai_knowledge.initialize(db)
   self.assertEqual(db.execute("SELECT count(*) FROM knowledge WHERE title LIKE 'Оформление:%'").fetchone()[0],1)
del PlatformTests
