# job-bot — личный бот поиска работы

Дважды в день собирает вакансии из ~10 источников, оценивает их через ИИ (по умолчанию бесплатный Gemini) под твой профиль и присылает лучшие в Telegram.
Кнопка **📄 CV + письмо** собирает PDF-резюме и сопроводительное письмо под конкретную вакансию.
Пункты опыта в CV берутся **дословно** из `profile/facts.yaml`. Модель только выбирает, какие показать, поэтому придумать тебе опыт она не может.

```
GitHub Actions (cron 2×/день)            Telegram
  bot/collect.py ──► Claude (оценка) ──► карточки вакансий [📄 CV + письмо] [🔗]
                                                     │
                     Vercel webhook/api/telegram.js ◄┘
                                │ repository_dispatch
  bot/make_cv.py ◄──────────────┘
  Claude выбирает факты + пишет письмо → проверка на выдумки → PDF → Telegram
```

## Источники
Arbeitsagentur (официальный API) · Arbeitnow · Berlin Startup Jobs · Remotive · Jobicy · Himalayas · RemoteOK · We Work Remotely · Djinni ·
**email-алерты** (LinkedIn, Xing, StepStone, Indeed — бот читает их из ярлыка Gmail).
Если источник сломался, бот пишет об этом в Telegram, а остальные продолжают работать.

---

## Запуск и тест — 3 этапа

### Этап 1. Telegram-бот (5 минут)
1. В Telegram открой **@BotFather** → `/newbot` → получи **токен**.
2. Напиши своему боту любое сообщение.
3. Открой в браузере `https://api.telegram.org/bot<ТОКЕН>/getUpdates` и найди `"chat":{"id": ...}`. Это твой **chat_id**.

### Этап 2. Поиск и оценка в GitHub (10 минут) — здесь уже придут вакансии
1. Создай **приватный** репозиторий и залей туда этот код.
2. Получи **бесплатный** ключ Gemini: aistudio.google.com → Get API key → Create API key. Карта не нужна.
3. Repo → Settings → Secrets and variables → Actions → **New repository secret**:
   | Secret | Значение |
   |---|---|
   | `GEMINI_API_KEY` | ключ Gemini из AI Studio |
   | `TELEGRAM_BOT_TOKEN` | токен от BotFather |
   | `TELEGRAM_CHAT_ID` | твой chat_id |
4. Actions → **Collect jobs** → **Run workflow**.
   Через 1–2 минуты в Telegram придёт подборка. ✅
5. Проверка CV без кнопки: возьми `id` любой вакансии из `data/jobs.json` → Actions → **Make CV** → Run workflow → вставь id. Через 1–2 минуты придут два PDF. ✅

### Этап 3. Кнопка в Telegram (10 минут)
1. vercel.com → Add New Project → этот репозиторий → **Root Directory: `webhook`** → Deploy.
2. Vercel → Settings → Environment Variables:
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
   `TELEGRAM_WEBHOOK_SECRET` (любая длинная случайная строка),
   `GITHUB_REPO` (например `eremich/job-bot`),
   `GITHUB_TOKEN` — github.com → Settings → Developer settings → Fine-grained tokens → только этот репозиторий, права **Contents: Read and write** и **Actions: Read and write**.
   После этого нажми Redeploy.
3. Подключи webhook, открыв в браузере:
   `https://api.telegram.org/bot<ТОКЕН>/setWebhook?url=https://<твой-проект>.vercel.app/api/telegram&secret_token=<TELEGRAM_WEBHOOK_SECRET>`
4. Нажми **📄 CV + письмо** под любой вакансией ✅. Команда `/run` запускает поиск вне расписания.

### Этап 4 (по желанию). Email-алерты LinkedIn / Xing / StepStone
1. Настрой на площадках алерты «Product Designer · Berlin».
2. В Gmail создай фильтр: от `jobalerts-noreply@linkedin.com`, `xing.com`, `stepstone.de`… → ярлык **Jobs**.
3. Google Account → Security → 2-Step Verification → **App passwords** → создай пароль.
4. Добавь секреты `EMAIL_USER` (твой Gmail) и `EMAIL_APP_PASSWORD`.

---

## Настройка
- `profile/facts.yaml` — **заполни все TODO** (email, LinkedIn, даты, должности, факты про A-Development). Это главное.
- `config.yaml` — ключевые слова, исключения, порог оценки (`min_score`), сколько вакансий слать, языки CV и письма.
- `templates/` — HTML/CSS резюме и письма. Меняй дизайн как хочешь.

## Локальный тест без ключей
```bash
pip install -r requirements.txt
python -m bot.collect --fixture tests/fixture_jobs.json --no-llm --dry-run
python -m bot.make_cv a1b2c3d4e5f6 --plan tests/sample_plan.json --dry-run   # PDF появятся в out/
python tests/test_email.py
```
Повторно прогнать фикстуру: удали `data/jobs.json` (бот помнит, что уже видел).

## Стоимость: €0
- GitHub Actions (приватный репозиторий, ~2 000 бесплатных минут в месяц, бот тратит ~100) и Vercel Hobby — бесплатно.
- Gemini free tier — бесплатно, без карты. Лимиты небольшие, но на 2 прогона в день и несколько CV хватает. При ошибке 429 бот ждёт и повторяет запрос.
- Если бесплатный лимит кончился или Google сменил названия моделей, бот **не падает**. Оценка переключается на формулу по ключевым словам, а письмо собирается из шаблона, о чём бот предупреждает в Telegram.
- Можно вообще без ИИ: `llm.provider: none` в `config.yaml`.
- Когда появятся деньги, можно поставить `provider: anthropic` и добавить `ANTHROPIC_API_KEY`.

⚠️ На бесплатном тарифе Google может использовать запросы для обучения моделей. Туда уходят тексты вакансий и твой банк фактов: опыт и достижения. Паспорт, адрес и телефон в банк фактов не клади.

Названия моделей (`gemini-3.5-flash-lite`, `gemini-3.8-flash`) актуальны на ноябрь 2026. Если бот пишет «model not found», посмотри текущие бесплатные модели в AI Studio и поменяй их в `config.yaml`.

## Честно об ограничениях
- У Arbeitsagentur в выдаче нет полного текста вакансии, поэтому там оценка идёт по заголовку и компании.
- Форматы сторонних площадок иногда меняются. Сломанный источник будет виден в Telegram.
- Финальное CV всё равно просматривай перед отправкой: проверка ловит выдумки в письме, но не заменяет твой взгляд.

## Надёжный ежечасный запуск (cron-job.org)
Встроенное расписание GitHub часто пропускает запуски, поэтому бота раз в час будит внешний бесплатный будильник.
1. github.com/settings/personal-access-tokens/new → Repository access: **Only select repositories → Job-bot** → Permissions → **Actions: Read and write** → Generate token.
2. cron-job.org → Create cronjob:
   - URL: `https://api.github.com/repos/eremich/Job-bot/actions/workflows/collect.yml/dispatches`
   - Schedule: каждый час, часы 7–22, Timezone Europe/Berlin
   - Advanced → Request method **POST**
   - Headers: `Authorization: Bearer <токен>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
   - Request body: `{"ref":"main","inputs":{"quiet":"true"}}`
   - Ответ `204` значит, что всё в порядке.
