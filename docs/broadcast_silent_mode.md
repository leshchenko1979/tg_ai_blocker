# Admin broadcast draft — silent auto-delete mode

**Run after** channel post is published on @ai_antispam. Replace `CHANNEL_POST_URL` with the real permalink.

**Format:** HTML (`--parse-mode HTML`)  
**Audience:** active admins (~268), via `scripts/run_broadcast_on_vds.sh`

---

## Message (RU)

```html
<b>Новый режим: тихое автоудаление спама</b>

Команда <code>/mode</code> теперь переключает <b>три</b> режима:
1. Только уведомления
2. Автоудаление (с DM после каждого удаления)
3. <b>Тихое автоудаление</b> — удаляет спам без личного сообщения на каждое срабатывание

<b>Ваш текущий режим не меняется</b>, пока вы сами не нажмёте <code>/mode</code>.

<b>Как включить тихий режим:</b> откройте бота в личке → <code>/mode</code> → нажимайте, пока не увидите подтверждение тихого автоудаления.

<b>Если удалили не спам:</b> перешлите сообщение боту в личку — в тихом режиме кнопки «Не спам» после автоудаления нет.

Подробнее в канале: <a href="CHANNEL_POST_URL">@ai_antispam</a>
```

---

## Ops checklist

1. Publish [`docs/channel_post_silent_mode.md`](channel_post_silent_mode.md) to @ai_antispam
2. Paste permalink into `CHANNEL_POST_URL` above
3. Copy HTML body → `scripts/broadcast_message.txt` (gitignored)
4. Export admin IDs → `scripts/admin_ids.txt`
5. Dry-run: `scripts/run_broadcast_on_vds.sh`
6. Live with `--parse-mode HTML`, resume `scripts/broadcast_sent.ids`, `--min-sent 1`
7. Log recipient count + channel URL in `memory-bank/progress.md`
