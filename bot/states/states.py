"""FSM States"""

from aiogram.fsm.state import State, StatesGroup


class AgentSetup(StatesGroup):
    waiting_name = State()
    waiting_instructions = State()
    confirm = State()


class ChannelLink(StatesGroup):
    waiting_forward = State()


class ContentGeneration(StatesGroup):
    waiting_prompt = State()         # Ожидание запроса на генерацию
    waiting_edit = State()           # Ожидание инструкции по редактированию


class RewritePost(StatesGroup):
    waiting_post = State()           # Ожидание пересланного поста для рерайта
    waiting_edit = State()           # Редактирование рерайта


class MediaManagement(StatesGroup):
    """Управление медиа поста"""
    menu = State()                    # В меню медиа (ожидание действия)
    waiting_ai_image_prompt = State() # Ожидание промта для AI-картинки
    waiting_ai_video_prompt = State() # Ожидание промта для AI-видео
    waiting_upload = State()          # Ожидание загрузки медиа от пользователя
    waiting_delete_index = State()    # Ожидание номера для удаления
