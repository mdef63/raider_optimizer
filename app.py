"""
Raider.IO Optimizer - Веб-приложение для оптимизации улучшений предметов WoW
"""

import logging
import os
from datetime import datetime
from functools import wraps
from typing import Dict, List, Optional, Tuple

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import urllib.parse

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация Flask приложения
app = Flask(__name__)
CORS(app)

# Конфигурация
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-secret-key-for-raider-optimizer'
app.config['JSON_SORT_KEYS'] = False

# ====================================================================================
# КОНСТАНТЫ
# ====================================================================================

# Информация о слотах экипировки с иконками (только нужные слоты)
SLOT_INFO = {
    'head': {'name': 'Голова (шлем)', 'icon': '🛡️'},
    'neck': {'name': 'Шея (амулет)', 'icon': '📿'},
    'shoulder': {'name': 'Плечи', 'icon': '👕'},
    'back': {'name': 'Спина (плащ)', 'icon': '游戏当中'},
    'chest': {'name': 'Грудь', 'icon': '🦺'},
    'wrist': {'name': 'Запястья (браслеты)', 'icon': '🔗'},
    'hands': {'name': 'Кисти рук (перчатки)', 'icon': '🧤'},
    'waist': {'name': 'Пояс', 'icon': '🥋'},
    'legs': {'name': 'Ноги (поножи)', 'icon': '🦵'},
    'feet': {'name': 'Ступни (обувь)', 'icon': '👟'},
    'finger1': {'name': 'Палец 1 (кольцо)', 'icon': '💍'},
    'finger2': {'name': 'Палец 2 (кольцо)', 'icon': '💍'},
    'trinket1': {'name': 'Аксессуар 1', 'icon': '💎'},
    'trinket2': {'name': 'Аксессуар 2', 'icon': '💎'},
    'mainhand': {'name': 'Основная рука (оружие)', 'icon': '⚔️'},
    'offhand': {'name': 'Вторая рука (щит/оружие)', 'icon': '🛡️'}
}

# Слоты, которые НЕЛЬЗЯ изготавливать (аксессуары)
NON_CRAFTABLE_SLOTS = ['trinket1', 'trinket2']

# Порядок слотов для сортировки
SLOT_ORDER = [
    'head', 'neck', 'shoulder', 'back', 'chest', 'wrist', 'hands',
    'waist', 'legs', 'feet', 'finger1', 'finger2', 'trinket1', 'trinket2',
    'mainhand', 'offhand'
]

# Уровни улучшений предметов
UPGRADE_LEVELS = [681, 684, 688, 691, 694, 697, 701, 704, 707, 710, 713, 717, 720, 723, 727, 730]

# Максимальные уровни для разных сложностей
MAX_LEVEL_BY_DIFFICULTY = {
    "Normal": 704,
    "Heroic": 717,
    "Mythic": 730
}

# Стоимость улучшений (ресурсы)
def get_upgrade_cost(current_level: int, target_level: int) -> Tuple[int, int, int]:
    """
    Рассчитывает стоимость улучшения предмета.
    Возвращает кортеж: (ресурс1, ресурс2, ресурс3)
    """
    resource1 = 0  # до 691 ilvl
    resource2 = 0  # до 704 ilvl
    resource3 = 0  # свыше 704 ilvl

    # Находим индексы уровней
    current_index = 0
    target_index = len(UPGRADE_LEVELS) - 1

    for i, level in enumerate(UPGRADE_LEVELS):
        if current_level >= level:
            current_index = i
        if target_level <= level:
            target_index = i
            break

    # Рассчитываем стоимость по шагам
    for i in range(current_index, target_index):
        level = UPGRADE_LEVELS[i]
        cost = 15  # Стоимость одного шага

        if level < 691:
            resource1 += cost
        elif level < 704:
            resource2 += cost
        else:
            resource3 += cost

    return (resource1, resource2, resource3)

# Стоимость изготовления предмета 727 ilvl
CRAFT_COST_727 = (0, 0, 90)  # Только ресурс №3

# Стоимость улучшения специальных предметов до 727
SPECIAL_UPGRADE_COST_727 = (0, 0, 30)  # Только ресурс №3

# Список специальных предметов, которые можно улучшить до 727 за 30 ресурсов
SPECIAL_ITEMS = [
    "Improvised Seaforium Pacemaker",
    "Ring of the Panoply",
    "Rune-Branded Waistband",
    "Everforged Warglaive"
]

# Максимальное количество изготавливаемых предметов
MAX_CRAFTED_ITEMS = 9

# Список серверов EU
EU_REALMS = [
    'Aerie Peak', 'Agamaggan', 'Aggramar', 'Ahn\'Qiraj', 'Alonsus', 'Anachronos', 'Arathor',
    'Arena Tournament', 'Argent Dawn', 'Aszune', 'Auchindoun', 'Azjol-Nerub', 'Azuregos',
    'Azuremyst', 'Baelgun', 'Balnazzar', 'Blackhand', 'Blackmoore', 'Blackrock', 'Blackscar',
    'Blade\'s Edge', 'Bladefist', 'Bloodfeather', 'Bloodhoof', 'Bloodscalp', 'Blutkessel',
    'Booty Bay', 'Borean Tundra', 'Boulderfist', 'Bronze Dragonflight', 'Bronzebeard',
    'C\'Thun', 'Chamber of Aspects', 'Chants éternels', 'Cho\'gall', 'Chromaggus', 'Colinas Pardas',
    'Confrérie du Thorium', 'Conseil des Ombres', 'Crushridge', 'Culte de la Rive noire',
    'Daggerspine', 'Dalaran', 'Dalvengyr', 'Darkmoon Faire', 'Darksorrow', 'Darkspear',
    'Das Konsortium', 'Das Syndikat', 'Deathguard', 'Deathweaver', 'Deathwing', 'Deepholm',
    'Defias Brotherhood', 'Dentarg', 'Der abyssische Rat', 'Der Mithrilorden', 'Destromath',
    'Dethecus', 'Die Aldor', 'Die Arguswacht', 'Die ewige Wacht', 'Die Silberne Hand',
    'Doomhammer', 'Draenor', 'Dragonblight', 'Dragonmaw', 'Drak\'thul', 'Drek\'Thar', 'Dun Modr',
    'Dun Morogh', 'Dunemaul', 'Durotan', 'Earthen Ring', 'Echsenkessel', 'Eitrigg', 'Eldre\'Thalas',
    'Elune', 'Emerald Dream', 'Emeriss', 'Eonar', 'Eredar', 'Eversong', 'Executus', 'Exodar',
    'Festung der Stürme', 'Fordragon', 'Forscherliga', 'Frostmane', 'Frostmourne', 'Frostwhisper',
    'Galakrond', 'Garona', 'Garrosh', 'Genjuros', 'Ghostlands', 'Gilneas', 'Goldrinn', 'Gordunni',
    'Gorgonnash', 'Greymane', 'Grim Batol', 'Grom', 'Gul\'dan', 'Hakkar', 'Haomarush', 'Hellfire',
    'Hellscream', 'Howling Fjord', 'Hydraxis', 'Hyjal', 'Illidan', 'Jaedenar', 'Kael\'thas',
    'Karazhan', 'Kargath', 'Kazzak', 'Kel\'Thuzad', 'Khadgar', 'Khaz Modan', 'Khaz\'goroth',
    'Kil\'jaeden', 'Kilrogg', 'Kirin Tor', 'Korgath', 'Kor\'gall', 'Krag\'jin', 'Krasus', 'Kul Tiras',
    'Kult der Verdammten', 'La Croisade écarlate', 'Laughing Skull', 'Les Clairvoyants',
    'Les Sentinelles', 'Lich King', 'Lightbringer', 'Lightning\'s Blade', 'Lordaeron', 'Los Errantes',
    'Lothar', 'Madmortem', 'Magtheridon', 'Mal\'Ganis', 'Malfurion', 'Malorne', 'Malygos', 'Mannoroth',
    'Marécage de Zangar', 'Mazrigos', 'Medivh', 'Minahonda', 'Moonglade', 'Mug\'thol', 'Nagrand',
    'Nathrezim', 'Naxxramas', 'Nazjatar', 'Nemesis', 'Neptulon', 'Nera\'thor', 'Nethersturm',
    'Nordrassil', 'Norgannon', 'Nozdormu', 'Onyxia', 'Outland', 'Perenolde', 'Pozzo dell\'Eternità',
    'Proudmoore', 'Quel\'Thalas', 'Rajaxx', 'Ravencrest', 'Ravenholdt', 'Rexxar', 'Runetotem',
    'Sanguino', 'Sargeras', 'Saurfang', 'Scarshield Legion', 'Sen\'jin', 'Shadowsong', 'Shattered Halls',
    'Shattered Hand', 'Shattrath', 'Shen\'dralar', 'Silvermoon', 'Sinstralis', 'Skullcrusher',
    'Soulflayer', 'Spinebreaker', 'Sporeggar', 'Steamwheedle Cartel', 'Stormrage', 'Stormreaver',
    'Stormscale', 'Sunstrider', 'Sylvanas', 'Taerar', 'Talnivarr', 'Tarren Mill', 'Teldrassil',
    'Temple noir', 'Terenas', 'Terokkar', 'Theradras', 'Thermaplugg', 'Thrall', 'Throk\'Feroth',
    'Thunderhorn', 'Tichondrius', 'Tirion', 'Todeswache', 'Trollbane', 'Turalyon', 'Twisting Nether',
    'Tyrande', 'Uldaman', 'Ulduar', 'Uldum', 'Varimathras', 'Vashj', 'Vek\'lor', 'Vek\'nilash',
    'Vol\'jin', 'Wildhammer', 'Wrathbringer', 'Xavius', 'Ysera', 'Ysondre', 'Zenedar', 'Zirkel des Cenarius',
    'Zul\'jin', 'Zuluhed'
]

# Отображение регионов
REGIONS_LOCALIZED = {
    'eu': 'Европа',
    'us': 'США',
    'kr': 'Корея',
    'tw': 'Тайвань'
}

# Базовый URL для иконок Raider.IO
RAIDER_IO_ICON_BASE = "https://render.worldofwarcraft.com/eu/icons/56"

# ====================================================================================
# УТИЛИТЫ
# ====================================================================================

def determine_item_difficulty(item, item_level):
    """Определение сложности предмета по бонусам и уровню"""
    bonuses = item.get('bonuses', [])
    if not isinstance(bonuses, list):
        bonuses = []

    item_name = item.get('name', '')

    # Проверяем специальные предметы
    if any(special_item in item_name for special_item in SPECIAL_ITEMS):
        # Эти предметы могут быть Mythic по умолчанию
        if "Improvised Seaforium Pacemaker" in item_name:
            return "Mythic"
        elif "Ring of the Panoply" in item_name:
            return "Heroic"
        elif "Rune-Branded Waistband" in item_name or "Everforged Warglaive" in item_name:
            return "Mythic"  # Предполагаем, что они Mythic

    # Словарь с бонусами для разных режимов сложности
    difficulty_map = {
        "Mythic": [
            1540,    # Mythic raid
            1579,    # Mythic raid
            1530,    # Mythic raid
            1546,    # Mythic+
            1563,    # Mythic+
            6704     # Дополнительный бонус для Mythic
        ],
        "Heroic": [
            1527,    # Heroic raid
            1514,    # Heroic raid
            1520,    # Heroic raid
            1489,    # Heroic dungeon
            1565,    # Heroic (другой тип)
            1523,    # Heroic (еще один тип)
            12353,   # Heroic (из ваших данных - кольца)
            12675,   # Heroic (из ваших данных - комплект)
            12676,   # Heroic (из ваших данных - комплект)
            13446    # Heroic (из ваших данных)
        ],
        "Normal": [
            1518,    # Normal raid
            1507,    # Normal raid
            12229,   # Normal (из ваших данных)
            12230,   # Normal (из ваших данных)
            12231,   # Normal (из ваших данных)
            12232,   # Normal (из ваших данных)
            12233    # Normal (из ваших данных)
        ]
    }

    # Проверяем бонусы в порядке приоритета
    for difficulty, bonus_list in difficulty_map.items():
        if any(bonus in bonus_list for bonus in bonuses):
            return difficulty

    # Если бонусов нет, определяем по уровню (приблизительно)
    if item_level >= 720:
        return "Mythic"
    elif item_level >= 707:
        return "Heroic"
    elif item_level >= 680:
        return "Normal"

    return ""

def get_max_level_for_difficulty(difficulty: str) -> int:
    """Возвращает максимальный уровень для заданной сложности"""
    return MAX_LEVEL_BY_DIFFICULTY.get(difficulty, 730)

def get_max_craftable_level_for_item(item: Dict) -> int:
    """Возвращает максимальный уровень, до которого можно изготовить предмет"""
    item_name = item.get('name', '')

    # Для специальных предметов максимальный уровень - 727
    if any(special_item in item_name for special_item in SPECIAL_ITEMS):
        return 727

    # Для обычных предметов максимальный уровень - всегда 727 (при изготовлении)
    return 727

def transform_realm_name(realm_name: str) -> str:
    """Преобразует название сервера для использования в URL."""
    if not realm_name:
        return ""

    transformed = realm_name.lower().replace('\'', '').replace(' ', '-')

    replacements = {
        'é': 'e', 'è': 'e', 'à': 'a', 'ç': 'c',
        'ñ': 'n', 'ö': 'o', 'ü': 'u', 'ä': 'a',
        'ß': 'ss', 'ú': 'u', 'í': 'i', 'ó': 'o'
    }

    for char, replacement in replacements.items():
        transformed = transformed.replace(char, replacement)

    return transformed

def get_item_icon_url(icon_name: str) -> str:
    """Возвращает полный URL иконки предмета с Raider.IO."""
    if not icon_name:
        return f"{RAIDER_IO_ICON_BASE}/inv_misc_questionmark.jpg"
    return f"{RAIDER_IO_ICON_BASE}/{icon_name}.jpg"

def get_slot_priority(slot: str) -> int:
    """Возвращает приоритет слота для сортировки."""
    try:
        return SLOT_ORDER.index(slot)
    except ValueError:
        return len(SLOT_ORDER)

def format_resources(resources: Tuple[int, int, int]) -> str:
    """Форматирует ресурсы для отображения."""
    r1, r2, r3 = resources
    parts = []
    if r1 > 0:
        parts.append(f"Ресурс №1: {r1}")
    if r2 > 0:
        parts.append(f"Ресурс №2: {r2}")
    if r3 > 0:
        parts.append(f"Ресурс №3: {r3}")
    return ", ".join(parts) if parts else "Бесплатно"

# ====================================================================================
# МОДЕЛИ
# ====================================================================================

class CharacterData:
    """Класс для работы с данными персонажа World of Warcraft"""

    def __init__(self, region: str, realm: str, name: str):
        self.region = region.lower()
        self.realm = realm
        self.name = name
        self.data = None

    def fetch_data(self) -> Optional[Dict]:
        """Получает данные персонажа с Raider.IO API."""
        try:
            transformed_realm = transform_realm_name(self.realm)
            encoded_name = urllib.parse.quote(self.name)

            url = (f"https://raider.io/api/v1/characters/profile"
                  f"?region={self.region}"
                  f"&realm={urllib.parse.quote(transformed_realm)}"
                  f"&name={encoded_name}"
                  f"&fields=gear")

            logger.info(f"Запрос к API Raider.IO: {url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
            }

            response = requests.get(url, headers=headers, timeout=20)

            if response.status_code == 200:
                self.data = response.json()
                logger.info(f"Получены данные для персонажа {self.name}")
                return self.data
            elif response.status_code == 404:
                logger.warning(f"Персонаж {self.name} не найден на {self.realm}")
                return None
            else:
                logger.error(f"Ошибка API Raider.IO: {response.status_code}")
                return None

        except requests.exceptions.Timeout:
            logger.error(f"Таймаут при запросе данных для {self.name}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети при запросе данных: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении данных: {e}")
            return None

    def get_equipment_items(self) -> List[Dict]:
        """Извлекает информацию о предметах экипировки (только нужные слоты)."""
        if not self.data or 'gear' not in self.data:
            return []

        gear_data = self.data['gear']
        items = []

        if 'items' in gear_data and isinstance(gear_data['items'], dict):
            for slot_key, item_data in gear_data['items'].items():
                # Проверяем, что слот находится в списке нужных слотов
                if slot_key in SLOT_INFO and isinstance(item_data, dict) and 'item_level' in item_data:
                    slot_info = SLOT_INFO[slot_key]

                    # Получаем URL иконки с Raider.IO
                    icon_url = get_item_icon_url(item_data.get('icon'))

                    # Определяем сложность предмета
                    difficulty = determine_item_difficulty(item_data, item_data['item_level'])
                    difficulty_display = f" [{difficulty}]" if difficulty else ""

                    items.append({
                        'item_level': item_data['item_level'],
                        'slot': slot_key,
                        'readable_slot': slot_info['name'],
                        'slot_icon': slot_info['icon'],
                        'id': item_data.get('item_id', 'N/A'),
                        'name': item_data.get('name', 'Без названия') + difficulty_display,
                        'quality': item_data.get('item_quality', 0),
                        'icon': item_data.get('icon', 'inv_misc_questionmark'),
                        'icon_url': icon_url,
                        'crafted': False,  # По умолчанию предмет не изготовлен
                        'difficulty': difficulty,  # Добавляем информацию о сложности
                        'is_special': any(special_item in item_data.get('name', '') for special_item in SPECIAL_ITEMS)
                    })

        # Сортируем по заданному порядку слотов
        items.sort(key=lambda item: get_slot_priority(item['slot']))

        logger.info(f"Извлечено {len(items)} предметов для {self.name} (из {len(SLOT_ORDER)} возможных)")
        return items

class UpgradeOptimizer:
    """Класс для оптимизации улучшений предметов"""

    def __init__(self, items: List[Dict], target_average: float):
        self.items = items
        self.target_average = target_average
        self.current_average = sum(item['item_level'] for item in items) / len(items) if items else 0
        self.crafted_items_count = 0  # Счетчик изготавливаемых предметов
        self.crafted_items_log = []    # Лог изготовленных предметов
        self.crafted_slots = set()     # Отслеживаем уже использованные слоты для изготовления

    def can_craft_item(self, slot: str) -> bool:
        """Проверяет, можно ли изготовить предмет в данном слоте."""
        # Проверяем ограничения на количество, слот и дубликаты
        return (self.crafted_items_count < MAX_CRAFTED_ITEMS and
                slot not in NON_CRAFTABLE_SLOTS and
                slot not in self.crafted_slots)

    def get_next_upgrade_level(self, current_level: int, difficulty: str) -> Optional[int]:
        """Возвращает следующий возможный уровень улучшения с учетом ограничений сложности."""
        max_level = get_max_level_for_difficulty(difficulty)

        for level in UPGRADE_LEVELS:
            if level > current_level and level <= max_level:
                return level
        return None

    def find_optimal_path(self) -> Dict:
        """Находит оптимальный путь улучшений."""
        logger.info(f"Начинаем оптимизацию. Текущее среднее: {self.current_average:.2f}, Цель: {self.target_average}")

        if self.current_average >= self.target_average:
            # Создаем копию предметов для финальной экипировки
            final_items = [item.copy() for item in self.items]
            return {
                "message": "Целевое значение уже достигнуто!",
                "resources_needed": {"resource1": 0, "resource2": 0, "resource3": 0},
                "total_resources_cost": 0,
                "upgrades": [],
                "crafted_items": 0,
                "crafted_items_log": [],
                "final_average": self.current_average,
                "final_items": final_items
            }

        # Создаем копию предметов для симуляции улучшений
        upgraded_items = [item.copy() for item in self.items]
        total_resources = [0, 0, 0]  # [ресурс1, ресурс2, ресурс3]
        upgrades_made = []
        current_avg = self.current_average
        step = 1
        max_steps = 100

        while current_avg < self.target_average and step <= max_steps:
            # Находим предмет с минимальным уровнем
            min_item_idx = min(range(len(upgraded_items)),
                             key=lambda i: upgraded_items[i]['item_level'])

            current_level = upgraded_items[min_item_idx]['item_level']
            item_slot = upgraded_items[min_item_idx]['slot']
            item_name = upgraded_items[min_item_idx]['name']
            item_difficulty = upgraded_items[min_item_idx]['difficulty']
            is_special = upgraded_items[min_item_idx]['is_special']

            # Получаем максимальный уровень для этой сложности (для улучшения)
            max_level_for_difficulty = get_max_level_for_difficulty(item_difficulty)

            # Проверяем, достиг ли предмет максимального уровня для своей сложности
            if current_level >= max_level_for_difficulty:
                logger.info(f"Предмет {item_name} достиг максимального уровня {max_level_for_difficulty} для сложности {item_difficulty}")
                # Ищем другой предмет для улучшения
                available_items = [
                    (i, item) for i, item in enumerate(upgraded_items)
                    if item['item_level'] < get_max_level_for_difficulty(item['difficulty'])
                    and item['slot'] not in self.crafted_slots  # Исключаем уже использованные слоты
                ]
                if available_items:
                    min_item_idx = min(available_items, key=lambda x: x[1]['item_level'])[0]
                    current_level = upgraded_items[min_item_idx]['item_level']
                    item_slot = upgraded_items[min_item_idx]['slot']
                    item_name = upgraded_items[min_item_idx]['name']
                    item_difficulty = upgraded_items[min_item_idx]['difficulty']
                    is_special = upgraded_items[min_item_idx]['is_special']
                    max_level_for_difficulty = get_max_level_for_difficulty(item_difficulty)
                else:
                    logger.info("Все предметы достигли максимального уровня для своей сложности")
                    # Проверяем возможность изготовления предметов до 727
                    if self.crafted_items_count < MAX_CRAFTED_ITEMS:
                        # Ищем предметы, которые можно изготовить до 727
                        craftable_items = [
                            (i, item) for i, item in enumerate(upgraded_items)
                            if item['slot'] not in NON_CRAFTABLE_SLOTS
                            and item['slot'] not in self.crafted_slots
                            and item['item_level'] < 727  # Можно улучшить до 727
                        ]
                        if craftable_items:
                            min_item_idx = min(craftable_items, key=lambda x: x[1]['item_level'])[0]
                            current_level = upgraded_items[min_item_idx]['item_level']
                            item_slot = upgraded_items[min_item_idx]['slot']
                            item_name = upgraded_items[min_item_idx]['name']
                            is_special = upgraded_items[min_item_idx]['is_special']
                        else:
                            break

            # Проверяем возможность изготовления предмета до 727 (если цель еще не достигнута)
            if self.can_craft_item(item_slot) and current_avg < self.target_average and current_level < 727:
                # Определяем стоимость изготовления до 727
                if is_special:
                    target_level = 727
                    craft_cost = SPECIAL_UPGRADE_COST_727
                else:
                    target_level = 727  # Всегда 727 при изготовлении
                    craft_cost = CRAFT_COST_727

                # Рассчитываем потенциальное улучшение до максимального уровня сложности
                max_upgrade_level = min(max_level_for_difficulty, 727)
                can_upgrade_to_max = current_level < max_upgrade_level

                # Рассчитываем стоимость улучшения до максимального уровня
                if can_upgrade_to_max:
                    upgrade_cost_to_max = get_upgrade_cost(current_level, max_upgrade_level)
                    upgrade_total_cost = sum(upgrade_cost_to_max)
                else:
                    upgrade_total_cost = float('inf')  # Невозможно улучшить

                craft_total_cost = sum(craft_cost)

                # Принимаем решение: улучшать или изготавливать
                # Изготавливаем до 727, если:
                # 1. Стоимость изготовления выгоднее улучшения до максимума
                # 2. Или предмет уже максимально улучшен для своей сложности
                # 3. Или цель еще не достигнута
                if not can_upgrade_to_max or craft_total_cost <= upgrade_total_cost or current_avg < self.target_average:
                    # Изготовление предмета до 727
                    self.crafted_items_count += 1
                    self.crafted_slots.add(item_slot)  # Отмечаем слот как использованный
                    old_level = upgraded_items[min_item_idx]['item_level']
                    upgraded_items[min_item_idx]['item_level'] = target_level
                    upgraded_items[min_item_idx]['crafted'] = True  # Помечаем как изготовленный

                    new_levels = [item['item_level'] for item in upgraded_items]
                    new_avg = sum(new_levels) / len(new_levels)

                    # Добавляем информацию об изготовлении
                    crafted_info = {
                        'step': step,
                        'item_slot': upgraded_items[min_item_idx]['readable_slot'],
                        'item_slot_icon': upgraded_items[min_item_idx]['slot_icon'],
                        'item_name': upgraded_items[min_item_idx]['name'],
                        'item_icon_url': upgraded_items[min_item_idx]['icon_url'],
                        'from': old_level,
                        'to': target_level,
                        'cost': craft_cost,
                        'cost_formatted': format_resources(craft_cost),
                        'type': 'crafted'
                    }

                    self.crafted_items_log.append(crafted_info)
                    upgrades_made.append(crafted_info)

                    # Обновляем общие ресурсы
                    for i in range(3):
                        total_resources[i] += craft_cost[i]

                    logger.info(f"Шаг {step}: Изготовление предмета {upgraded_items[min_item_idx]['name']} {old_level}→{target_level}")
                    step += 1
                    current_avg = new_avg
                    continue

            # Обычное улучшение (если цель еще не достигнута)
            if current_avg < self.target_average:
                next_level = self.get_next_upgrade_level(current_level, item_difficulty)

                # Для специальных предметов ограничиваем уровень 727
                if is_special and next_level and next_level > 727:
                    next_level = 727 if current_level < 727 else None

                # Ограничиваем уровнем сложности
                if next_level and next_level > max_level_for_difficulty:
                    next_level = None

                if next_level is None:
                    logger.info(f"Предмет {item_name} не может быть улучшен дальше")
                    # Ищем другой предмет для улучшения
                    available_items = [
                        (i, item) for i, item in enumerate(upgraded_items)
                        if item['item_level'] < get_max_level_for_difficulty(item['difficulty'])
                        and item['slot'] not in self.crafted_slots  # Исключаем уже использованные слоты
                    ]
                    if available_items:
                        min_item_idx = min(available_items, key=lambda x: x[1]['item_level'])[0]
                        current_level = upgraded_items[min_item_idx]['item_level']
                        item_slot = upgraded_items[min_item_idx]['slot']
                        item_name = upgraded_items[min_item_idx]['name']
                        item_difficulty = upgraded_items[min_item_idx]['difficulty']
                        is_special = upgraded_items[min_item_idx]['is_special']
                        next_level = self.get_next_upgrade_level(current_level, item_difficulty)
                        # Для специальных предметов ограничиваем уровень 727
                        if is_special and next_level and next_level > 727:
                            next_level = 727 if current_level < 727 else None
                        # Ограничиваем уровнем сложности
                        if next_level and next_level > get_max_level_for_difficulty(item_difficulty):
                            next_level = None
                        if next_level is None:
                            logger.info("Все предметы достигли максимального уровня")
                            # Проверяем возможность изготовления
                            if self.crafted_items_count < MAX_CRAFTED_ITEMS:
                                craftable_items = [
                                    (i, item) for i, item in enumerate(upgraded_items)
                                    if item['slot'] not in NON_CRAFTABLE_SLOTS
                                    and item['slot'] not in self.crafted_slots
                                    and item['item_level'] < 727
                                ]
                                if craftable_items:
                                    min_item_idx = min(craftable_items, key=lambda x: x[1]['item_level'])[0]
                                    current_level = upgraded_items[min_item_idx]['item_level']
                                    item_slot = upgraded_items[min_item_idx]['slot']
                                    item_name = upgraded_items[min_item_idx]['name']
                                    is_special = upgraded_items[min_item_idx]['is_special']
                                    # Продолжаем с изготовлением
                                    continue
                            break
                    else:
                        logger.info("Все предметы достигли максимального уровня")
                        # Проверяем возможность изготовления
                        if self.crafted_items_count < MAX_CRAFTED_ITEMS:
                            craftable_items = [
                                (i, item) for i, item in enumerate(upgraded_items)
                                if item['slot'] not in NON_CRAFTABLE_SLOTS
                                and item['slot'] not in self.crafted_slots
                                and item['item_level'] < 727
                            ]
                            if craftable_items:
                                min_item_idx = min(craftable_items, key=lambda x: x[1]['item_level'])[0]
                                current_level = upgraded_items[min_item_idx]['item_level']
                                item_slot = upgraded_items[min_item_idx]['slot']
                                item_name = upgraded_items[min_item_idx]['name']
                                is_special = upgraded_items[min_item_idx]['is_special']
                                # Продолжаем с изготовлением
                                continue
                        break

                if next_level is not None:
                    # Рассчитываем стоимость улучшения
                    cost = get_upgrade_cost(current_level, next_level)

                    # Выполняем улучшение
                    upgraded_items[min_item_idx]['item_level'] = next_level
                    new_levels = [item['item_level'] for item in upgraded_items]
                    new_avg = sum(new_levels) / len(new_levels)

                    # Добавляем информацию об улучшении
                    upgrade_info = {
                        'step': step,
                        'item_slot': upgraded_items[min_item_idx]['readable_slot'],
                        'item_slot_icon': upgraded_items[min_item_idx]['slot_icon'],
                        'item_name': upgraded_items[min_item_idx]['name'],
                        'item_icon_url': upgraded_items[min_item_idx]['icon_url'],
                        'from': current_level,
                        'to': next_level,
                        'cost': cost,
                        'cost_formatted': format_resources(cost),
                        'type': 'upgrade'
                    }

                    upgrades_made.append(upgrade_info)

                    # Обновляем общие ресурсы
                    for i in range(3):
                        total_resources[i] += cost[i]

                    logger.debug(f"Шаг {step}: {upgraded_items[min_item_idx]['name']} {current_level}→{next_level} ({format_resources(cost)})")

                    step += 1
                    current_avg = new_avg

            # Проверяем достижение цели
            if current_avg >= self.target_average:
                break

        # Рассчитываем эффективность
        total_resource_cost = sum(total_resources)
        efficiency = ((current_avg - self.current_average) / total_resource_cost * 1000) if total_resource_cost > 0 else 0

        # Создаем копию финальных предметов для вывода
        final_items = [item.copy() for item in upgraded_items]
        result = {
            "current_average": round(self.current_average, 2),
            "final_average": round(current_avg, 2),
            "resources_needed": {
                "resource1": total_resources[0],
                "resource2": total_resources[1],
                "resource3": total_resources[2]
            },
            "total_resources_cost": total_resource_cost,
            "upgrades_count": len([u for u in upgrades_made if u['type'] == 'upgrade']),
            "crafted_items": len(self.crafted_items_log),
            "crafted_items_log": self.crafted_items_log,
            "upgrades": upgrades_made,
            "goal_reached": current_avg >= self.target_average,
            "efficiency": round(efficiency, 2),
            "current_items": self.items,
            "final_items": final_items
        }

        logger.info(f"Оптимизация завершена. Ресурсы: {total_resource_cost}, Среднее: {current_avg:.2f}")
        return result


# ====================================================================================
# ДЕКОРАТОРЫ
# ====================================================================================

def handle_api_errors(f):
    """Декоратор для централизованной обработки ошибок API."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.error(f"Ошибка валидации данных: {e}")
            return jsonify({"error": "Некорректные данные"}), 400
        except Exception as e:
            logger.error(f"Внутренняя ошибка сервера: {e}")
            return jsonify({"error": "Внутренняя ошибка сервера"}), 500

    return wrapper


# ====================================================================================
# МАРШРУТЫ
# ====================================================================================

@app.route('/')
def index():
    """Главная страница приложения."""
    return render_template('index.html')


@app.route('/api/realms')
def get_realms():
    """Возвращает список доступных серверов."""
    popular_realms = [
        'Howling Fjord', 'Grom', 'Fordragon', 'Soulflayer', 'Blackscar', 'Azuregos',
        'Deathwing', 'Blackrock', 'Bloodhoof', 'Dalaran', 'Frostmourne', 'Goldrinn',
        'Greymane', 'Proudmoore', 'Dragonblight', 'Dragonmaw', 'Blackhand', 'Karazhan',
        'Ravencrest', 'Sargeras', 'Stormrage', 'Area 52'
    ]

    other_realms = sorted([realm for realm in EU_REALMS if realm not in popular_realms])
    all_realms = popular_realms + other_realms

    return jsonify({
        "realms": all_realms,
        "regions": REGIONS_LOCALIZED,
        "total_realms": len(all_realms),
        "upgrade_levels": UPGRADE_LEVELS,
        "max_crafted_items": MAX_CRAFTED_ITEMS,
        "non_craftable_slots": NON_CRAFTABLE_SLOTS,
        "craft_cost_727": {
            "resource1": CRAFT_COST_727[0],
            "resource2": CRAFT_COST_727[1],
            "resource3": CRAFT_COST_727[2]
        },
        "special_upgrade_cost_727": {
            "resource1": SPECIAL_UPGRADE_COST_727[0],
            "resource2": SPECIAL_UPGRADE_COST_727[1],
            "resource3": SPECIAL_UPGRADE_COST_727[2]
        },
        "special_items": SPECIAL_ITEMS,
        "max_levels": MAX_LEVEL_BY_DIFFICULTY
    })


@app.route('/api/character', methods=['POST'])
@handle_api_errors
def analyze_character():
    """Анализирует персонажа и находит оптимальный путь улучшений."""
    start_time = datetime.now()
    logger.info("Начало анализа персонажа")

    data = request.get_json()
    if not data:
        return jsonify({"error": "Неверный формат данных"}), 400

    region = data.get('region', 'eu').lower()
    realm = data.get('realm', '').strip()
    character_name = data.get('character_name', '').strip()
    target_average = data.get('target_average')

    if not realm:
        return jsonify({"error": "Необходимо указать сервер"}), 400

    if not character_name:
        return jsonify({"error": "Необходимо указать имя персонажа"}), 400

    if target_average is None:
        return jsonify({"error": "Необходимо указать целевое среднее значение"}), 400

    try:
        target_average = float(target_average)
    except (ValueError, TypeError):
        return jsonify({"error": "Целевое значение должно быть числом"}), 400

    if target_average <= 0:
        return jsonify({"error": "Целевое значение должно быть положительным"}), 400

    character = CharacterData(region, realm, character_name)
    if not character.fetch_data():
        return jsonify({"error": "Персонаж не найден. Проверьте правильность введенных данных."}), 404

    items = character.get_equipment_items()
    if not items:
        return jsonify({"error": "Не удалось получить данные о предметах персонажа"}), 400

    optimizer = UpgradeOptimizer(items, target_average)
    optimization_result = optimizer.find_optimal_path()

    end_time = datetime.now()
    processing_time = (end_time - start_time).total_seconds()

    result = {
        "status": "success",
        "character": {
            "name": character_name,
            "realm": realm,
            "region": REGIONS_LOCALIZED.get(region, region.upper())
        },
        "target_average": target_average,
        "processing_time": round(processing_time, 2),
        **optimization_result
    }

    if not result.get("message") and not result["goal_reached"]:
        result["message"] = f"Цель не достигнута. Максимальное достижимое среднее: {result['final_average']}"

    logger.info(f"Анализ завершен за {processing_time:.2f} секунд")
    return jsonify(result)


@app.route('/api/stats')
def get_stats():
    """Возвращает статистику API."""
    return jsonify({
        "status": "online",
        "version": "2.2.0",
        "supported_regions": list(REGIONS_LOCALIZED.keys()),
        "supported_realms_eu": len(EU_REALMS),
        "upgrade_levels": UPGRADE_LEVELS,
        "max_crafted_items": MAX_CRAFTED_ITEMS,
        "non_craftable_slots": NON_CRAFTABLE_SLOTS,
        "craft_cost_727": {
            "resource1": CRAFT_COST_727[0],
            "resource2": CRAFT_COST_727[1],
            "resource3": CRAFT_COST_727[2]
        },
        "special_upgrade_cost_727": {
            "resource1": SPECIAL_UPGRADE_COST_727[0],
            "resource2": SPECIAL_UPGRADE_COST_727[1],
            "resource3": SPECIAL_UPGRADE_COST_727[2]
        },
        "special_items": SPECIAL_ITEMS,
        "max_levels": MAX_LEVEL_BY_DIFFICULTY,
        "last_updated": datetime.now().isoformat()
    })


# Обработка ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Страница не найдена"}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Внутренняя ошибка сервера: {error}")
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500


if __name__ == '__main__':
    # Получаем параметры из переменных окружения
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'

    logger.info(f"Запуск Raider.IO Optimizer на {host}:{port}")
    app.run(host=host, port=port, debug=debug)
