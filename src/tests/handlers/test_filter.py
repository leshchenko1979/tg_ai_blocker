import pytest
from aiogram import Dispatcher
from aiogram.types import Message

from app.handlers.updates_filter import filter_handle_message

dp = Dispatcher()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update, should_process",
    [
        (
            {
                "message": {
                    "chat": {
                        "id": -1001503592176,
                        "title": "Инвестиции в недвижимость — чат",
                        "type": "supergroup",
                        "username": "redevest_chat",
                    },
                    "date": 1730712821,
                    "from": {
                        "first_name": "Denis",
                        "id": 205980892,
                        "is_bot": False,
                        "username": "buloshnikov",
                    },
                    "message_id": 10242,
                    "message_thread_id": 10229,
                    "reply_to_message": {
                        "caption": "🏗 Апдейт по складам во Фрязино: дело к финишу!\n\nДрузья, спешу поделиться позитивными новостями с нашей стройплощадки!\n\n▫️ На этой неделе добьём полноценный фильм о проекте (трейлер вверху) — монтаж уже на финишной прямой. Готовьте попкорн! 🎬\n\n▫️ Первый склад уже готов — осталось дождаться, пока высохнет свежезалитый пол, и можно выходить на комиссию по вводу в эксплуатацию. Это как ждать, пока остынет свежеиспеченный пирог — знаешь, что вот-вот, но нужно набраться терпения 😅\n\n▫️ Второй и третий корпуса следуют за первопроходцем с небольшим отставанием — как младшие братья, которые спешат за старшим.\n\n\nИ тут самое интересное: на третьем складе осталось всего 2 места для инвесторов (11 млн). \n\nЗнаете, что самое забавное? Эти счастливчики зайдут в проект практически без рисков по срокам строительства — склад уже почти готов. Как говорится, все сливки достанутся тем, кто пришёл к десерту 😉\n\nЧестно признаюсь: будь у меня сейчас свободные средства, сам бы закрыл эти 11 млн не раздумывая. Но, как говорится, чужое счастье ждёт своего героя!\n\n📌 [Почитать о проекте]\n📌 [Посмотреть ход строительства]\n📌 [Посмотреть презентацию и финмодель]\n\nА вы когда-нибудь заходили в инвестпроект на финальной стадии?",
                        "caption_entities": [
                            {"length": 44, "offset": 3, "type": "bold"},
                            {
                                "length": 6,
                                "offset": 248,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest/67",
                            },
                            {
                                "length": 6,
                                "offset": 487,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest/63",
                            },
                            {
                                "length": 6,
                                "offset": 496,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest/64",
                            },
                            {"length": 64, "offset": 636, "type": "bold"},
                            {
                                "length": 18,
                                "offset": 1058,
                                "type": "text_link",
                                "url": "https://t.me/flipping_invest/807",
                            },
                            {
                                "length": 28,
                                "offset": 1082,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest",
                            },
                            {
                                "length": 34,
                                "offset": 1116,
                                "type": "text_link",
                                "url": "tg://resolve?domain=FlippingInvestBot&start=c1707842038691-ds",
                            },
                            {"length": 62, "offset": 1153, "type": "bold"},
                        ],
                        "chat": {
                            "id": -1001503592176,
                            "title": "Инвестиции в недвижимость — чат",
                            "type": "supergroup",
                            "username": "redevest_chat",
                        },
                        "date": 1730178121,
                        "edit_date": 1730181661,
                        "forward_date": 1730178118,
                        "forward_from_chat": {
                            "id": -1001664173586,
                            "title": "Инвестиции в редевелопмент | Лещенко",
                            "type": "channel",
                            "username": "flipping_invest",
                        },
                        "forward_from_message_id": 844,
                        "forward_origin": {
                            "chat": {
                                "id": -1001664173586,
                                "title": "Инвестиции в редевелопмент | Лещенко",
                                "type": "channel",
                                "username": "flipping_invest",
                            },
                            "date": 1730178118,
                            "message_id": 844,
                            "type": "channel",
                        },
                        "from": {
                            "first_name": "Telegram",
                            "id": 777000,
                            "is_bot": False,
                        },
                        "is_automatic_forward": True,
                        "message_id": 10229,
                        "sender_chat": {
                            "id": -1001664173586,
                            "title": "Инвестиции в редевелопмент | Лещенко",
                            "type": "channel",
                            "username": "flipping_invest",
                        },
                        "video": {
                            "duration": 95,
                            "file_id": "BAACAgIAAx0CWZ7-8AACJ_VnKASp23wG65v0zmT-JT2y3R9M1gACOFoAAl4LAUk6dPoMmYqiizYE",
                            "file_name": "Видео WhatsApp 2024-10-26 в 16.16.36_2bb4d36a.mp4",
                            "file_size": 11073514,
                            "file_unique_id": "AgADOFoAAl4LAUk",
                            "height": 480,
                            "mime_type": "video/mp4",
                            "thumb": {
                                "file_id": "AAMCAgADHQJZnv7wAAIn9WcoBKnbfAbrm_TOZP4lPbLdH0zWAAI4WgACXgsBSTp0-gyZiqKLAQAHbQADNgQ",
                                "file_size": 12103,
                                "file_unique_id": "AQADOFoAAl4LAUly",
                                "height": 180,
                                "width": 320,
                            },
                            "thumbnail": {
                                "file_id": "AAMCAgADHQJZnv7wAAIn9WcoBKnbfAbrm_TOZP4lPbLdH0zWAAI4WgACXgsBSTp0-gyZiqKLAQAHbQADNgQ",
                                "file_size": 12103,
                                "file_unique_id": "AQADOFoAAl4LAUly",
                                "height": 180,
                                "width": 320,
                            },
                            "width": 854,
                        },
                    },
                    "text": "Алексей, добрый день!\nПланирую строить своё производство в МО. Но нет в этом опыта. Формат складов которые вы строите, как раз, то, что мне нужно. Не могли бы Вы меня сконтактировать с Павлом Кунцевым, если я правильно понял он погружен в эту тему и сможет помочь и советом и делом.",
                },
                "update_id": 726062782,
            },
            True,
        ),
        (
            {
                "message": {
                    "chat": {
                        "id": -1001503592176,
                        "title": "Инвестиции в недвижимость — чат",
                        "type": "supergroup",
                        "username": "redevest_chat",
                    },
                    "date": 1730714961,
                    "from": {
                        "first_name": "Master",
                        "id": 2058183096,
                        "is_bot": False,
                        "last_name": "Guru",
                        "username": "masterguru509",
                    },
                    "message_id": 10244,
                    "message_thread_id": 10229,
                    "reply_to_message": {
                        "caption": "🏗 Апдейт по складам во Фрязино: дело к финишу!\n\nДрузья, спешу поделиться позитивными новостями с нашей стройплощадки!\n\n▫️ На этой неделе добьём полноценный фильм о проекте (трейлер вверху) — монтаж уже на финишной прямой. Готовьте попкорн! 🎬\n\n▫️ Первый склад уже готов — осталось дождаться, пока высохнет свежезалитый пол, и можно выходить на комиссию по вводу в эксплуатацию. Это как ждать, пока остынет свежеиспеченный пирог — знаешь, что вот-вот, но нужно набраться терпения 😅\n\n▫️ Второй и третий корпуса следуют за первопроходцем с небольшим отставанием — как младшие братья, которые спешат за старшим.\n\n\nИ тут самое интересное: на третьем складе осталось всего 2 места для инвесторов (11 млн). \n\nЗнаете, что самое забавное? Эти счастливчики зайдут в проект практически без рисков по срокам строительства — склад уже почти готов. Как говорится, все сливки достанутся тем, кто пришёл к десерту 😉\n\nЧестно признаюсь: будь у меня сейчас свободные средства, сам бы закрыл эти 11 млн не раздумывая. Но, как говорится, чужое счастье ждёт своего героя!\n\n📌 [Почитать о проекте]\n📌 [Посмотреть ход строительства]\n📌 [Посмотреть презентацию и финмодель]\n\nА вы когда-нибудь заходили в инвестпроект на финальной стадии?",
                        "caption_entities": [
                            {"length": 44, "offset": 3, "type": "bold"},
                            {
                                "length": 6,
                                "offset": 248,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest/67",
                            },
                            {
                                "length": 6,
                                "offset": 487,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest/63",
                            },
                            {
                                "length": 6,
                                "offset": 496,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest/64",
                            },
                            {"length": 64, "offset": 636, "type": "bold"},
                            {
                                "length": 18,
                                "offset": 1058,
                                "type": "text_link",
                                "url": "https://t.me/flipping_invest/807",
                            },
                            {
                                "length": 28,
                                "offset": 1082,
                                "type": "text_link",
                                "url": "https://t.me/fryazino_redevest",
                            },
                            {
                                "length": 34,
                                "offset": 1116,
                                "type": "text_link",
                                "url": "tg://resolve?domain=FlippingInvestBot&start=c1707842038691-ds",
                            },
                            {"length": 62, "offset": 1153, "type": "bold"},
                        ],
                        "chat": {
                            "id": -1001503592176,
                            "title": "Инвестиции в недвижимость — чат",
                            "type": "supergroup",
                            "username": "redevest_chat",
                        },
                        "date": 1730178121,
                        "edit_date": 1730181661,
                        "forward_date": 1730178118,
                        "forward_from_chat": {
                            "id": -1001664173586,
                            "title": "Инвестиции в редевелопмент | Лещенко",
                            "type": "channel",
                            "username": "flipping_invest",
                        },
                        "forward_from_message_id": 844,
                        "forward_origin": {
                            "chat": {
                                "id": -1001664173586,
                                "title": "Инвестиции в редевелопмент | Лещенко",
                                "type": "channel",
                                "username": "flipping_invest",
                            },
                            "date": 1730178118,
                            "message_id": 844,
                            "type": "channel",
                        },
                        "from": {
                            "first_name": "Telegram",
                            "id": 777000,
                            "is_bot": False,
                        },
                        "is_automatic_forward": True,
                        "message_id": 10229,
                        "sender_chat": {
                            "id": -1001664173586,
                            "title": "Инвестиции в редевелопмент | Лещенко",
                            "type": "channel",
                            "username": "flipping_invest",
                        },
                        "video": {
                            "duration": 95,
                            "file_id": "BAACAgIAAx0CWZ7-8AACJ_VnKASp23wG65v0zmT-JT2y3R9M1gACOFoAAl4LAUk6dPoMmYqiizYE",
                            "file_name": "Видео WhatsApp 2024-10-26 в 16.16.36_2bb4d36a.mp4",
                            "file_size": 11073514,
                            "file_unique_id": "AgADOFoAAl4LAUk",
                            "height": 480,
                            "mime_type": "video/mp4",
                            "thumb": {
                                "file_id": "AAMCAgADHQJZnv7wAAIn9WcoBKnbfAbrm_TOZP4lPbLdH0zWAAI4WgACXgsBSTp0-gyZiqKLAQAHbQADNgQ",
                                "file_size": 12103,
                                "file_unique_id": "AQADOFoAAl4LAUly",
                                "height": 180,
                                "width": 320,
                            },
                            "thumbnail": {
                                "file_id": "AAMCAgADHQJZnv7wAAIn9WcoBKnbfAbrm_TOZP4lPbLdH0zWAAI4WgACXgsBSTp0-gyZiqKLAQAHbQADNgQ",
                                "file_size": 12103,
                                "file_unique_id": "AQADOFoAAl4LAUly",
                                "height": 180,
                                "width": 320,
                            },
                            "width": 854,
                        },
                    },
                    "text": "сколько заработают инвесторы годовых?",
                },
                "update_id": 726062786,
            },
            True,
        ),
        (
            {
                "message": {
                    "chat": {
                        "id": -1001503592176,
                        "title": "Инвестиции в недвижимость — чат",
                        "type": "supergroup",
                        "username": "redevest_chat",
                    },
                    "date": 1730714058,
                    "from": {
                        "first_name": "Channel",
                        "id": 136817688,
                        "is_bot": True,
                        "username": "Channel_Bot",
                    },
                    "message_id": 10243,
                    "message_thread_id": 10229,
                    "quote": {
                        "is_manual": True,
                        "position": 22,
                        "text": "Планирую строить своё производство в МО",
                    },
                    "reply_to_message": {
                        "chat": {
                            "id": -1001503592176,
                            "title": "Инвестиции в недвижимость — чат",
                            "type": "supergroup",
                            "username": "redevest_chat",
                        },
                        "date": 1730712821,
                        "from": {
                            "first_name": "Denis",
                            "id": 205980892,
                            "is_bot": False,
                            "username": "buloshnikov",
                        },
                        "message_id": 10242,
                        "message_thread_id": 10229,
                        "text": "Алексей, добрый день!\nПланирую строить своё производство в МО. Но нет в этом опыта. Формат складов которые вы строите, как раз, то, что мне нужно. Не могли бы Вы меня сконтактировать с Павлом Кунцевым, если я правильно понял он погружен в эту тему и сможет помочь и советом и делом.",
                    },
                    "sender_chat": {
                        "id": -1001664173586,
                        "title": "Инвестиции в редевелопмент | Лещенко",
                        "type": "channel",
                        "username": "flipping_invest",
                    },
                    "text": "А почему строить, а не купить готовое?",
                },
                "update_id": 726062784,
            },
            False,
        ),
        (
            {
                "message": {
                    "chat": {
                        "id": -1001503592176,
                        "title": "Инвестиции в недвижимость — чат",
                        "type": "supergroup",
                        "username": "redevest_chat",
                    },
                    "date": 1730715059,
                    "entities": [{"length": 61, "offset": 48, "type": "url"}],
                    "from": {
                        "first_name": "Channel",
                        "id": 136817688,
                        "is_bot": True,
                        "username": "Channel_Bot",
                    },
                    "message_id": 10246,
                    "message_thread_id": 10229,
                    "reply_to_message": {
                        "chat": {
                            "id": -1001503592176,
                            "title": "Инвестиции в недвижимость — чат",
                            "type": "supergroup",
                            "username": "redevest_chat",
                        },
                        "date": 1730714961,
                        "from": {
                            "first_name": "Master",
                            "id": 2058183096,
                            "is_bot": False,
                            "last_name": "Guru",
                            "username": "masterguru509",
                        },
                        "message_id": 10244,
                        "message_thread_id": 10229,
                        "text": "сколько заработают инвесторы годовых?",
                    },
                    "sender_chat": {
                        "id": -1001664173586,
                        "title": "Инвестиции в редевелопмент | Лещенко",
                        "type": "channel",
                        "username": "flipping_invest",
                    },
                    "text": "До 70% годовых.\n\nБолее подробная финмодель тут: tg://resolve?domain=FlippingInvestBot&start=c1707842038691-ds",
                },
                "update_id": 726062788,
            },
            False,
        ),
        (
            {
                "message": {
                    "chat": {
                        "id": -1001503592176,
                        "title": "Инвестиции в недвижимость — чат",
                        "type": "supergroup",
                        "username": "redevest_chat",
                    },
                    "date": 1730721610,
                    "from": {
                        "first_name": "Сергей",
                        "id": 589118505,
                        "is_bot": False,
                        "is_premium": True,
                        "language_code": "ru",
                        "last_name": "Наседкин",
                        "username": "Serg1VN",
                    },
                    "message_id": 10254,
                    "message_thread_id": 10229,
                    "reply_to_message": {
                        "chat": {
                            "id": -1001503592176,
                            "title": "Инвестиции в недвижимость — чат",
                            "type": "supergroup",
                            "username": "redevest_chat",
                        },
                        "date": 1730721393,
                        "from": {
                            "first_name": "Denis",
                            "id": 205980892,
                            "is_bot": False,
                            "username": "buloshnikov",
                        },
                        "message_id": 10252,
                        "message_thread_id": 10229,
                        "text": "Планирую строиться в городском округе Подольск или Домодедово до ЦКАД. Площадь 1500-2000м.  По моему пониманию строиться будет существенно выгоднее чем покупать готовое, особенно если идти через аренду ЗУ, строительство и выкуп.",
                    },
                    "text": "Если до этого не строились то самостоятельно может выйти дорого и долго.\nМожет лучше привлечь партнёра  кто уже имеет опыт реализации схожих проектов.",
                },
                "update_id": 726062795,
            },
            False,
        ),
    ],
)
async def test_single_update(update, should_process):
    # extract Message
    msg = Message.model_validate(update["message"])
    print(msg)
    assert await filter_handle_message(msg) == should_process
