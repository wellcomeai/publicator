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


class Onboarding(StatesGroup):
    choosing_preset = State()       # Выбор пресета агента
    custom_prompt = State()         # Ввод кастомного промта
    naming_agent = State()          # Ввод имени агента
    waiting_channel = State()       # Привязка канала
    first_post_prompt = State()     # Создание первого поста


class SchedulePost(StatesGroup):
    waiting_datetime = State()      # Ожидание даты и времени


class MediaManagement(StatesGroup):
    """Управление медиа поста"""
    menu = State()                    # В меню медиа (ожидание действия)
    waiting_ai_image_prompt = State() # Ожидание промта для AI-картинки
    waiting_ai_video_prompt = State() # Ожидание промта для AI-видео
    waiting_upload = State()          # Ожидание загрузки медиа от пользователя
    waiting_delete_index = State()    # Ожидание номера для удаления
