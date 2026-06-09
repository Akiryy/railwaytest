# Railway PTB Test Bot

Тестовый Telegram-бот на `python-telegram-bot[job-queue]`.

## Что умеет

- читает настройки и тестовые заказы из `config.json`;
- хранит настройки и просмотренные заказы в SQLite;
- запускает периодическую проверку через JobQueue;
- позволяет менять настройки через Telegram.

## Команды

- `/start` — запуск и создание настроек
- `/status` — показать настройки
- `/check` — проверить тестовые заказы сейчас
- `/interval 180` — изменить интервал проверки в минутах
- `/threshold 10` — изменить минимальный балл
- `/on` — включить проверки
- `/off` — выключить проверки
- `/reset_seen` — очистить просмотренные тестовые заказы

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="токен_бота"
export DB_PATH="./data/bot.sqlite"
python bot.py
```

Для Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:BOT_TOKEN="токен_бота"
$env:DB_PATH="./data/bot.sqlite"
python bot.py
```

## Railway

1. Залей проект в GitHub.
2. В Railway создай новый проект из GitHub repo.
3. Добавь переменную:

```env
BOT_TOKEN=токен_бота
```

4. Добавь Volume и смонтируй его в `/data`.
5. Добавь переменную:

```env
DB_PATH=/data/bot.sqlite
```

6. Start command:

```bash
python bot.py
```

Если Railway использует Procfile, там уже есть:

```Procfile
worker: python bot.py
```
