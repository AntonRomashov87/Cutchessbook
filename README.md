# Chess Book Bot

Бот для Telegram, який:

- Завантажує PDF та DJVU книги.
- Конвертує сторінки у PNG.
- Публікує сторінки у Telegram-канал (ВТ, ЧТ, СБ о 10:00).
- Відправляє шахові задачі з JSON.
- Можливість ручного тригеру через `/trigger-puzzle/<secret>`.

## Запуск

1. Створи віртуальне середовище:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
