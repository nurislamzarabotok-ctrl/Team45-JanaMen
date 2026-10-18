"""Private local terminal entry; never send the key through chat."""
import getpass,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import ai_config
print('Настройка Google Gemini для JanaМен. Ключ не отображается при вводе.')
try:key=getpass.getpass('Вставьте API-ключ и нажмите Enter: ').strip()
except (EOFError,KeyboardInterrupt):print('\nНастройка отменена.');sys.exit(1)
if not ai_config.valid_key(key):print('Ключ пустой, содержит пробелы/переносы или является заглушкой. Файл не изменён.');sys.exit(1)
p=ROOT/'GEMINI_KEY.txt';p.write_text(key+'\n',encoding='utf-8')
try:os.chmod(p,0o600)
except OSError:pass
print('Сохранено в GEMINI_KEY.txt. Не публикуйте этот файл. Другие файлы/данные не изменены.')
print('Для проверки API: py -3 scripts/check_ai.py. Для запуска: START_IPHONE_SERVER.bat.')
