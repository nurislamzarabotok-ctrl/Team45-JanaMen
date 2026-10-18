"""Owner-run check; one live request unless --local. Never prints credentials."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ai_config,assistant_service
config=ai_config.settings()
print('Сборка: 1.4-iPhone + Gemini')
print('Папка проекта:',ai_config.ROOT)
print('Ключ настроен:', 'да' if config['configured'] else 'нет')
print('Режим:',config['provider'],'/','curl' if config['transport']=='curl' else 'urllib')
if config['config_error']:
 print('Ошибка настройки:',config['config_error']);sys.exit(1)
if not config['configured']:
 print('Откройте GEMINI_KEY.txt рядом с server.py, вставьте ключ Google AI Studio и сохраните.');sys.exit(1)
if '--local' in sys.argv:
 print('Локальная настройка готова. API не вызывался; доступность модели ещё не проверена.');sys.exit(0)
print('При model=auto сначала запрашивается список доступных моделей Google; затем один запрос генерации.')
print('Проверка одного ответа API (может расходовать токены), ожидание до',config['timeout'],'секунд...')
docs=[{'id':1,'body':'Заявка на отпуск создаётся в разделе «Мои заявки». Рассмотрение выполняет руководитель.'}]
try:
 result=assistant_service.chat_request('Где создать заявку на отпуск?',[dict(d,title='Отпуск') for d in docs],'ru')
 if not result.strip():raise assistant_service.AIError('invalid_response')
 print('OK: получен текстовый ответ API, без шаблонной подстановки.')
 print('Провайдер:',config['provider'],'Модель:',ai_config.public_settings().get('resolved_model') or config['model'])
 print('Теперь запустите сервер и проверьте новый диалог в платформе. Это отдельная проверка.')
except assistant_service.AIError as e:
 print('Ошибка:',e.code+'.',assistant_service.ERRORS.get(e.code,'Проверьте доступность модели и настройки.'));sys.exit(3)
except Exception:
 print('Проверка не завершена. Код: check_failed. Ключ и ответ API не выводятся.');sys.exit(4)
