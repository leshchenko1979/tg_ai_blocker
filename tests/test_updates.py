import pytest

update = {
  "message": {
    "chat": {
      "all_members_are_administrators": True,
      "id": -4513474783,
      "title": "spam test",
      "type": "group"
    },
    "date": 1730566790,
    "from": {
      "first_name": "Алексей",
      "id": 133526395,
      "is_bot": False,
      "is_premium": True,
      "language_code": "ru",
      "last_name": "Лещенко | Недвижимость 40-90% в год",
      "username": "leshchenko1979"
    },
    "message_id": 50,
    "text": "Ребята,всем тут привет! Я новичок"
  },
  "update_id": 726062680
}

@pytest.mark.asyncio
async def test_updates():
    import main
    from common.dp import dp

    await dp.feed_raw_update(main.bot, update)
    assert False
