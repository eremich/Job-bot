// Vercel serverless function — Telegram webhook.
// Button "📄 CV + письмо"  -> starts the "Make CV" GitHub Action
// /run                     -> starts a job search right now
// /start or /id            -> replies with your chat id (needed once for setup)
//
// Env vars (Vercel → Project → Settings → Environment Variables):
//   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET,
//   GITHUB_TOKEN (fine-grained, this repo only, "Contents: read & write" + "Actions: read & write"),
//   GITHUB_REPO  (e.g. "Dishain/job-bot")

const TG = (method, body) =>
  fetch(`https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

const GH = (path, body) =>
  fetch(`https://api.github.com/repos/${process.env.GITHUB_REPO}${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "job-bot-webhook",
    },
    body: JSON.stringify(body),
  });

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(200).send("job-bot webhook is alive");
  if (req.headers["x-telegram-bot-api-secret-token"] !== process.env.TELEGRAM_WEBHOOK_SECRET) {
    return res.status(401).send("nope");
  }
  const update = req.body || {};
  const owner = String(process.env.TELEGRAM_CHAT_ID || "");

  try {
    // ── Button press ──
    const cb = update.callback_query;
    if (cb) {
      const chat = String(cb.message?.chat?.id ?? "");
      const [action, jobId] = String(cb.data || "").split(":");
      if (chat !== owner) {
        await TG("answerCallbackQuery", { callback_query_id: cb.id, text: "Это личный бот 🙂" });
      } else if (action === "cv" && /^[0-9a-f]{12}$/.test(jobId)) {
        const r = await GH("/dispatches", { event_type: "make_cv", client_payload: { job_id: jobId } });
        await TG("answerCallbackQuery", {
          callback_query_id: cb.id,
          text: r.ok ? "Готовлю CV и письмо — ~1–2 минуты ⏳" : `GitHub ответил ${r.status} — проверь GITHUB_TOKEN`,
          show_alert: !r.ok,
        });
      }
      return res.status(200).json({ ok: true });
    }

    // ── Text commands ──
    const msg = update.message;
    if (msg?.text) {
      const chat = String(msg.chat.id);
      const cmd = msg.text.trim().split(/\s+/)[0].toLowerCase();
      if (cmd === "/start" || cmd === "/id") {
        await TG("sendMessage", { chat_id: chat, text: `Твой chat_id: ${chat}` });
      } else if (cmd === "/run" && chat === owner) {
        const r = await GH("/actions/workflows/collect.yml/dispatches", { ref: "main" });
        await TG("sendMessage", {
          chat_id: chat,
          text: r.ok ? "Запустил поиск, подборка придёт через пару минут 🔎" : `GitHub ответил ${r.status}`,
        });
      }
    }
  } catch (e) {
    console.error(e);
  }
  return res.status(200).json({ ok: true });
}
