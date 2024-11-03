import os

from common.yandex_logging import get_yandex_logger
from common.llms import get_openrouter_response
from utils import config

logger = get_yandex_logger(__name__)

prompt = """
Ты - классификатор спама. Пользователь подает тебе сообщения, а ты должен определить, спам это или нет, и дать оценку своей уверенности в процентах.

ФОРМАТ:
<начало ответа>
да ХХХ%
<конец ответа>

ИЛИ

<начало ответа>
нет ХХХ%
<конец ответа>

где ХХХ% - уровень твоей уверенности от 0 до 100.

Больше ничего к ответу не добавляй.

ПРИМЕРЫ:

"""

# add spam examples to the prompt from config
for example in config["spam_examples"]:
    prompt += f"""
<начало запроса>
{example["text"]}
<конец запроса>
<начало ответа>
{"да" if example["score"] > 0 else "нет"} {example["score"] if example["score"] > 0 else -example["score"]}%
<конец ответа>
"""

class ExtractionFailedError(Exception):
    pass

async def is_spam(comment: str):
    """
    Возвращает -100, если не спам, и 100, если спам
    """
    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES):
        try:
            messages = [{"role": "system", "text": prompt}, {"role": "user", "text": comment}]
            response = await get_openrouter_response(messages)
            logger.info(f"Spam classifier response: {response}")
            return extract_spam_score(response.lower())
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                raise ExtractionFailedError("Failed to extract spam score after 3 attempts") from e

def extract_spam_score(response: str):
    try:
        if "да" in response:
            multiplier = 1
        elif "нет" in response:
            multiplier = -1
        else:
            raise ValueError("Response doesn't contain 'да' or 'нет'")

        conf_score = int(response.split(" ")[1].replace("%", ""))
        return multiplier * conf_score
    except (IndexError, ValueError) as e:
        raise ValueError(f"Failed to parse response: {response}") from e
