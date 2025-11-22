"""
Raider.IO Optimizer - Веб-приложение для оптимизации улучшений предметов WoW
Улучшенная версия с профилями, стратегиями и расширенной функциональностью
"""

import logging
import os
import json
import hashlib
from datetime import datetime
from functools import wraps
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import sqlite3
from contextlib import contextmanager

from flask import Flask, render_template, request, jsonify, Response
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
app.config['DATABASE'] = 'raider_optimizer.db'

# ====================================================================================
# КОНСТАНТЫ И СТРАТЕГИИ
# ====================================================================================

# Информация о слотах экипировки с иконками (только нужные слоты)
SLOT_INFO = {
    'head': {'name': 'Голова (шлем)', 'icon': '[H]'},
    'neck': {'name': 'Шея (амулет)', 'icon': '[N]'},
    'shoulder': {'name': 'Плечи', 'icon': '[S]'},
    'back': {'name': 'Спина (плащ)', 'icon': '[B]'},
    'chest': {'name': 'Грудь', 'icon': '[C]'},
    'wrist': {'name': 'Запястья (браслеты)', 'icon': '[W]'},
    'hands': {'name': 'Кисти рук (перчатки)', 'icon': '[G]'},
    'waist': {'name': 'Пояс', 'icon': '[P]'},
    'legs': {'name': 'Ноги (поножи)', 'icon': '[L]'},
    'feet': {'name': 'Ступни (обувь)', 'icon': '[F]'},
    'finger1': {'name': 'Палец 1 (кольцо)', 'icon': '[R1]'},
    'finger2': {'name': 'Палец 2 (кольцо)', 'icon': '[R2]'},
    'trinket1': {'name': 'Аксессуар 1', 'icon': '[T1]'},
    'trinket2': {'name': 'Аксессуар 2', 'icon': '[T2]'},
    'mainhand': {'name': 'Основная рука (оружие)', 'icon': '[MH]'},
    'offhand': {'name': 'Вторая рука (щит/оружие)', 'icon': '[OH]'}
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

# Стратегии оптимизации
OPTIMIZATION_STRATEGIES = {
    "cost_efficient": {
        "name": "Экономичная",
        "description": "Минимум ресурсов за максимальный прирост",
        "priority": "efficiency"
    },
    "fastest": {
        "name": "Быстрая",
        "description": "Быстрое достижение цели (даже за больше ресурсов)",
        "priority": "speed"
    },
    "balanced": {
        "name": "Сбалансированная",
        "description": "Оптимальный баланс скорости и стоимости",
        "priority": "balanced"
    },
    "level_priority": {
        "name": "Приоритет уровней",
        "description": "Сначала улучшаем самые низкоуровневые предметы",
        "priority": "level"
    }
}

# Альтернативные источники предметов
ALTERNATIVE_SOURCES = {
    "mythic_plus": "Mythic+",
    "raid_drops": "Рейдовые луты",
    "world_quests": "Задания мира",
    "vendor": "Продавцы"
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

# Предметы, доступные через Mythic+
MYTHIC_PLUS_ITEMS = {
    "Charhound's Vicious Hornguards",
    "Mawsworn Soulkeeper",
    "Reinforced Soulsteel Sabatons"
}

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

# Классы персонажей и их специализации
CHARACTER_CLASSES = {
    "Death Knight": ["Blood", "Frost", "Unholy"],
    "Demon Hunter": ["Havoc", "Vengeance"],
    "Druid": ["Balance", "Feral", "Guardian", "Restoration"],
    "Evoker": ["Devastation", "Preservation"],
    "Hunter": ["Beast Mastery", "Marksmanship", "Survival"],
    "Mage": ["Arcane", "Fire", "Frost"],
    "Monk": ["Brewmaster", "Mistweaver", "Windwalker"],
    "Paladin": ["Holy", "Protection", "Retribution"],
    "Priest": ["Discipline", "Holy", "Shadow"],
    "Rogue": ["Assassination", "Outlaw", "Subtlety"],
    "Shaman": ["Elemental", "Enhancement", "Restoration"],
    "Warlock": ["Affliction", "Demonology", "Destruction"],
    "Warrior": ["Arms", "Fury", "Protection"]
}

# Рекомендации по специализациям
SPECIALIZATION_RECOMMENDATIONS = {
    "Death Knight": {
        "Blood": "Фокус на выживание и танкование",
        "Frost": "Баланс между уроном и контролем",
        "Unholy": "Максимальный урон с призывом существ"
    },
    "Demon Hunter": {
        "Havoc": "Высокий урон в PvP и PvE",
        "Vengeance": "Танкование с высокой мобильностью"
    },
    "Druid": {
        "Balance": "Рейндж урон с AoE возможностями",
        "Feral": "Мили урон с высокой мобильностью",
        "Guardian": "Танкование с природными способностями",
        "Restoration": "Исцеление с природной магией"
    }
}

# ====================================================================================
# БАЗА ДАННЫХ
# ====================================================================================

def init_db():
    """Инициализация базы данных"""
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                character_name TEXT,
                realm TEXT,
                region TEXT,
                target_average REAL,
                strategy TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data TEXT
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS optimization_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_name TEXT,
                realm TEXT,
                region TEXT,
                target_average REAL,
                strategy TEXT,
                final_average REAL,
                total_resources INTEGER,
                processing_time REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id TEXT PRIMARY KEY,
                default_strategy TEXT,
                max_crafted_items INTEGER,
                exclude_trinkets BOOLEAN,
                show_alternatives BOOLEAN
            )
        ''')

        conn.commit()

@contextmanager
def get_db_connection():
    """Контекстный менеджер для работы с базой данных"""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

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
        parts.append(f"Ресурс 1: {r1}")
    if r2 > 0:
        parts.append(f"Ресурс 2: {r2}")
    if r3 > 0:
        parts.append(f"Ресурс 3: {r3}")
    return ", ".join(parts) if parts else "Бесплатно"

def get_cache_key(region, realm, name, target_average, strategy="balanced"):
    """Генерирует ключ кэша"""
    key_string = f"{region}_{realm}_{name}_{target_average}_{strategy}"
    return hashlib.md5(key_string.encode()).hexdigest()

def get_item_color(item_level: int) -> str:
    """Возвращает цвет для визуализации уровня предмета"""
    if item_level >= 727:
        return "#FF8C00"  # Оранжевый
    elif item_level >= 717:
        return "#0070DD"  # Синий
    elif item_level >= 704:
        return "#1EFF00"  # Зеленый
    elif item_level >= 680:
        return "#FFFFFF"  # Белый
    else:
        return "#9D9D9D"  # Серый

def evaluate_alternative_methods(item_name: str, current_level: int) -> List[Dict]:
    """Оценивает альтернативные способы получения предметов"""
    alternatives = []

    # Проверяем, можно ли получить предмет через другие источники
    if item_name in MYTHIC_PLUS_ITEMS:
        alternatives.append({
            "method": "Mythic+",
            "estimated_level": 720,
            "cost": "Еженедельный ключ",
            "time_required": "2-4 часа"
        })

    # Добавляем общие альтернативы
    alternatives.append({
        "method": "Рейдовые луты",
        "estimated_level": current_level + 10,
        "cost": "Время/золото",
        "time_required": "Случайно"
    })

    return alternatives

def get_priority_items_for_upgrade(items: List[Dict], target_average: float, current_average: float, strategy: str = "balanced") -> List[Tuple]:
    """Определяет приоритетные предметы для улучшения"""
    item_priorities = []

    for i, item in enumerate(items):
        # Приоритет основан на стратегии
        if strategy == "level_priority":
            # Сначала самые низкоуровневые предметы
            priority = -item['item_level']
        else:
            # Стандартный алгоритм
            gap_from_avg = current_average - item['item_level']
            potential_gain = min(727, get_max_level_for_difficulty(item['difficulty'])) - item['item_level']

            # Предметы, которые сильно отстают, получают высокий приоритет
            priority = gap_from_avg * 2 + potential_gain

            # Специальные предметы получают бонусный приоритет
            if item['is_special']:
                priority += 50

        item_priorities.append((i, priority, item))

    # Сортируем по убыванию приоритета
    item_priorities.sort(key=lambda x: x[1], reverse=True)
    return item_priorities

def generate_recommendations(items: List[Dict], target_average: float, crafted_slots: set, crafted_items_count: int) -> List[Dict]:
    """Генерирует рекомендации по оптимизации"""
    recommendations = []

    # Рекомендации по предметам
    low_items = [item for item in items if item['item_level'] < (target_average - 20)]
    if low_items:
        recommendations.append({
            "type": "priority_upgrade",
            "message": f"Сначала улучшите {len(low_items)} предметов с низким уровнем",
            "items": [item['name'] for item in low_items[:3]]  # Показываем первые 3
        })

    # Рекомендации по слотам
    craftable_slots = [item for item in items
                      if item['slot'] not in NON_CRAFTABLE_SLOTS
                      and item['slot'] not in crafted_slots]

    if len(craftable_slots) > 0 and crafted_items_count < MAX_CRAFTED_ITEMS:
        recommendations.append({
            "type": "crafting_opportunity",
            "message": f"Рассмотрите изготовление предметов в {min(len(craftable_slots), MAX_CRAFTED_ITEMS - crafted_items_count)} слотах",
            "slots": [item['slot'] for item in craftable_slots[:3]]
        })

    # Рекомендации по балансу
    current_avg = sum(item['item_level'] for item in items) / len(items) if items else 0
    if abs(current_avg - target_average) < 5:
        recommendations.append({
            "type": "near_target",
            "message": "Вы близки к целевому значению. Рассмотрите точечные улучшения",
            "items": []
        })

    return recommendations

def compare_strategies(items: List[Dict], target_average: float, max_crafted_items: int = 9, budget_limit: Optional[int] = None) -> Dict:
    """Сравнивает разные стратегии оптимизации"""
    strategies = ["cost_efficient", "fastest", "balanced", "level_priority"]
    comparison = {}

    for strategy in strategies:
        optimizer = UpgradeOptimizer(items.copy(), target_average, strategy, max_crafted_items, budget_limit)
        result = optimizer.find_optimal_path()

        comparison[strategy] = {
            "total_cost": result["total_resources_cost"],
            "steps": len(result["upgrades"]) + len(result["crafted_items_log"]),
            "final_average": result["final_average"],
            "crafted_items": result["crafted_items"],
            "strategy_name": OPTIMIZATION_STRATEGIES[strategy]["name"]
        }

    return comparison

def calculate_item_efficiency(current_level: int, target_level: int, cost: Tuple[int, int, int]) -> float:
    """Рассчитывает эффективность улучшения предмета"""
    level_gain = target_level - current_level
    total_cost = sum(cost)
    return level_gain / total_cost if total_cost > 0 else 0

def get_class_recommendations(character_class: str, specialization: str) -> str:
    """Возвращает рекомендации по классу и специализации"""
    if character_class in SPECIALIZATION_RECOMMENDATIONS:
        if specialization in SPECIALIZATION_RECOMMENDATIONS[character_class]:
            return SPECIALIZATION_RECOMMENDATIONS[character_class][specialization]
    return "Рекомендации для этой специализации недоступны"

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
                  f"&fields=gear,raid_progression,mythic_plus_scores,mythic_plus_recent_runs")

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
                        'is_special': any(special_item in item_data.get('name', '') for special_item in SPECIAL_ITEMS),
                        'alternatives': evaluate_alternative_methods(item_data.get('name', ''), item_data['item_level'])
                    })

        # Сортируем по заданному порядку слотов
        items.sort(key=lambda item: get_slot_priority(item['slot']))

        logger.info(f"Извлечено {len(items)} предметов для {self.name} (из {len(SLOT_ORDER)} возможных)")
        return items

    def get_character_info(self) -> Dict:
        """Получает общую информацию о персонаже"""
        if not self.data:
            return {}

        return {
            'name': self.data.get('name', ''),
            'realm': self.data.get('realm', ''),
            'region': self.data.get('region', ''),
            'class': self.data.get('class', ''),
            'active_spec_name': self.data.get('active_spec_name', ''),
            'active_spec_role': self.data.get('active_spec_role', ''),
            'faction': self.data.get('faction', ''),
            'race': self.data.get('race', ''),
            'gender': self.data.get('gender', ''),
            'achievement_points': self.data.get('achievement_points', 0),
            'honorable_kills': self.data.get('honorable_kills', 0),
            'mythic_plus_scores': self.data.get('mythic_plus_scores', {}),
            'raid_progression': self.data.get('raid_progression', {})
        }

class UpgradeOptimizer:
    """Класс для оптимизации улучшений предметов"""

    def __init__(self, items: List[Dict], target_average: float, strategy: str = "balanced",
                 max_crafted_items: int = 9, budget_limit: Optional[int] = None,
                 exclude_trinkets: bool = False):
        self.items = items
        self.target_average = target_average
        self.strategy = strategy
        self.max_crafted_items = max_crafted_items
        self.budget_limit = budget_limit
        self.exclude_trinkets = exclude_trinkets
        self.current_average = sum(item['item_level'] for item in items) / len(items) if items else 0
        self.crafted_items_count = 0  # Счетчик изготавливаемых предметов
        self.crafted_items_log = []    # Лог изготовленных предметов
        self.crafted_slots = set()     # Отслеживаем уже использованные слоты для изготовления
        self.step_history = []         # История шагов для предотвращения зацикливания
        self.total_spent_resources = 0  # Общие потраченные ресурсы

    def can_craft_item(self, slot: str) -> bool:
        """Проверяет, можно ли изготовить предмет в данном слоте."""
        # Проверяем ограничения на количество, слот и дубликаты
        non_craftable_slots = NON_CRAFTABLE_SLOTS if self.exclude_trinkets else []

        return (self.crafted_items_count < self.max_crafted_items and
                slot not in non_craftable_slots and
                slot not in self.crafted_slots)

    def get_next_upgrade_level(self, current_level: int, difficulty: str) -> Optional[int]:
        """Возвращает следующий возможный уровень улучшения с учетом ограничений сложности."""
        max_level = get_max_level_for_difficulty(difficulty)

        for level in UPGRADE_LEVELS:
            if level > current_level and level <= max_level:
                return level
        return None

    def calculate_strategy_priority(self, current_level: int, max_level_for_difficulty: int,
                                  upgrade_cost: Tuple[int, int, int], craft_cost: Tuple[int, int, int]) -> str:
        """Рассчитывает приоритет на основе выбранной стратегии"""
        upgrade_total = sum(upgrade_cost)
        craft_total = sum(craft_cost)

        # Проверяем лимит бюджета
        if self.budget_limit is not None:
            if self.total_spent_resources + craft_total > self.budget_limit:
                return "upgrade"  # Не можем позволить себе изготовление
            if self.total_spent_resources + upgrade_total > self.budget_limit:
                return "skip"  # Не можем позволить себе улучшение

        if self.strategy == "cost_efficient":
            # Минимизация затрат
            return "craft" if craft_total < upgrade_total else "upgrade"
        elif self.strategy == "fastest":
            # Максимизация скорости (изготовление быстрее)
            return "craft"
        elif self.strategy == "level_priority":
            # Приоритет уровней - предпочитаем улучшение
            return "upgrade"
        else:  # balanced
            # Баланс между стоимостью и эффективностью
            gap_to_target = self.target_average - self.current_average
            if gap_to_target > 10:  # Большая разница - предпочитаем изготовление
                return "craft" if craft_total <= upgrade_total * 1.5 else "upgrade"
            else:  # Маленькая разница - предпочитаем улучшение
                return "upgrade" if upgrade_total <= craft_total * 1.2 else "craft"

    def is_cycling_detected(self, item_slot: str, item_level: int) -> bool:
        """Проверяет, не происходит ли зацикливание на предмете"""
        # Проверяем последние 5 шагов
        recent_steps = self.step_history[-5:] if len(self.step_history) >= 5 else self.step_history

        # Считаем, сколько раз этот предмет обрабатывался в последних шагах
        same_item_count = sum(1 for step in recent_steps
                             if step['slot'] == item_slot and step['level'] == item_level)

        # Если предмет обрабатывался 3 и более раз в последних 5 шагах - зацикливание
        return same_item_count >= 3

    def find_optimal_path(self) -> Dict:
        """Находит оптимальный путь улучшений."""
        logger.info(f"Начинаем оптимизацию. Текущее среднее: {self.current_average:.2f}, Цель: {self.target_average}, Стратегия: {self.strategy}")

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
                "final_items": final_items,
                "strategy": self.strategy,
                "strategy_name": OPTIMIZATION_STRATEGIES[self.strategy]["name"]
            }

        # Создаем копию предметов для симуляции улучшений
        upgraded_items = [item.copy() for item in self.items]
        total_resources = [0, 0, 0]  # [ресурс1, ресурс2, ресурс3]
        upgrades_made = []
        current_avg = self.current_average
        step = 1
        max_steps = 100

        while current_avg < self.target_average and step <= max_steps:
            # Проверяем лимит бюджета
            if self.budget_limit is not None and sum(total_resources) >= self.budget_limit:
                break

            # Используем улучшенный алгоритм выбора предметов
            priority_items = get_priority_items_for_upgrade(upgraded_items, self.target_average, current_avg, self.strategy)

            if not priority_items:
                break

            min_item_idx = priority_items[0][0]  # Берем индекс первого по приоритету предмета

            current_level = upgraded_items[min_item_idx]['item_level']
            item_slot = upgraded_items[min_item_idx]['slot']
            item_name = upgraded_items[min_item_idx]['name']
            item_difficulty = upgraded_items[min_item_idx]['difficulty']
            is_special = upgraded_items[min_item_idx]['is_special']

            # СТРОГАЯ проверка: если предмет уже максимального уровня, пропускаем его сразу
            if current_level >= 727:
                logger.info(f"Предмет {item_name} уже имеет максимальный уровень {current_level}")
                # Ищем следующий предмет, который можно улучшить
                available_items = [
                    (idx, priority, item) for idx, priority, item in priority_items[1:]
                    if item['item_level'] < 727
                    and item['slot'] not in self.crafted_slots
                ]
                if available_items:
                    min_item_idx = available_items[0][0]
                    current_level = upgraded_items[min_item_idx]['item_level']
                    item_slot = upgraded_items[min_item_idx]['slot']
                    item_name = upgraded_items[min_item_idx]['name']
                    item_difficulty = upgraded_items[min_item_idx]['difficulty']
                    is_special = upgraded_items[min_item_idx]['is_special']
                else:
                    # Если нет доступных предметов для улучшения, проверяем возможность изготовления
                    logger.info("Все предметы имеют максимальный уровень")
                    if self.crafted_items_count < self.max_crafted_items:
                        # Ищем предметы, которые можно изготовить (уже изготовленные пропускаем)
                        non_craftable_slots = NON_CRAFTABLE_SLOTS if self.exclude_trinkets else []
                        craftable_items = [
                            (i, item) for i, item in enumerate(upgraded_items)
                            if item['slot'] not in non_craftable_slots
                            and item['slot'] not in self.crafted_slots
                            and item['item_level'] < 727
                        ]
                        if craftable_items:
                            # Сортируем по уровню (самые низкие первыми)
                            craftable_items.sort(key=lambda x: x[1]['item_level'])
                            min_item_idx = craftable_items[0][0]
                            current_level = upgraded_items[min_item_idx]['item_level']
                            item_slot = upgraded_items[min_item_idx]['slot']
                            item_name = upgraded_items[min_item_idx]['name']
                            is_special = upgraded_items[min_item_idx]['is_special']
                        else:
                            break
                    else:
                        break

            # Проверка на зацикливание (только если предмет не максимального уровня)
            if current_level < 727 and self.is_cycling_detected(item_slot, current_level):
                logger.info(f"Обнаружено зацикливание на предмете {item_name} {current_level}")
                # Принудительно переходим к следующему предмету в списке приоритетов
                next_items = [
                    item for item in priority_items[1:]
                    if not self.is_cycling_detected(item[2]['slot'], item[2]['item_level'])
                    and item[2]['item_level'] < 727
                ]
                if next_items:
                    min_item_idx = next_items[0][0]
                    current_level = upgraded_items[min_item_idx]['item_level']
                    item_slot = upgraded_items[min_item_idx]['slot']
                    item_name = upgraded_items[min_item_idx]['name']
                    item_difficulty = upgraded_items[min_item_idx]['difficulty']
                    is_special = upgraded_items[min_item_idx]['is_special']
                else:
                    # Если все предметы в цикле, проверяем возможность изготовления
                    if self.can_craft_item(item_slot) and current_level < 727:
                        pass  # Продолжаем с изготовлением
                    else:
                        logger.info("Все предметы в цикле или максимального уровня, прекращаем обработку")
                        break

            # Добавляем шаг в историю (только если предмет не максимального уровня)
            if current_level < 727:
                self.step_history.append({
                    'slot': item_slot,
                    'level': current_level,
                    'name': item_name,
                    'step': step
                })

            # Получаем максимальный уровень для этой сложности (для улучшения)
            max_level_for_difficulty = get_max_level_for_difficulty(item_difficulty)

            # Проверяем, достиг ли предмет максимального уровня для своей сложности
            if current_level >= max_level_for_difficulty and current_level < 727:
                logger.info(f"Предмет {item_name} достиг максимального уровня {max_level_for_difficulty} для сложности {item_difficulty}")
                # Ищем другой предмет для улучшения из приоритетного списка
                non_craftable_slots = NON_CRAFTABLE_SLOTS if self.exclude_trinkets else []
                available_items = [
                    (idx, priority, item) for idx, priority, item in priority_items
                    if (item['item_level'] < get_max_level_for_difficulty(item['difficulty']) or item['item_level'] < 727)
                    and item['slot'] not in self.crafted_slots  # Исключаем уже использованные слоты
                    and item['item_level'] < 727  # Исключаем уже максимальные
                    and item['slot'] not in non_craftable_slots  # Исключаем неизготавливаемые слоты
                ]
                if available_items:
                    # Проверяем на зацикливание
                    valid_items = [
                        item for item in available_items
                        if not self.is_cycling_detected(item[2]['slot'], item[2]['item_level'])
                    ]
                    if valid_items:
                        min_item_idx = valid_items[0][0]  # Берем самый приоритетный незацикленный
                    else:
                        min_item_idx = available_items[0][0]  # Берем первый доступный
                    current_level = upgraded_items[min_item_idx]['item_level']
                    item_slot = upgraded_items[min_item_idx]['slot']
                    item_name = upgraded_items[min_item_idx]['name']
                    item_difficulty = upgraded_items[min_item_idx]['difficulty']
                    is_special = upgraded_items[min_item_idx]['is_special']
                    max_level_for_difficulty = get_max_level_for_difficulty(item_difficulty)
                else:
                    logger.info("Все предметы достигли максимального уровня для своей сложности")
                    # Проверяем возможность изготовления предметов до 727
                    if self.crafted_items_count < self.max_crafted_items:
                        # Ищем предметы, которые можно изготовить до 727
                        non_craftable_slots = NON_CRAFTABLE_SLOTS if self.exclude_trinkets else []
                        craftable_items = [
                            (i, item) for i, item in enumerate(upgraded_items)
                            if item['slot'] not in non_craftable_slots
                            and item['slot'] not in self.crafted_slots
                            and item['item_level'] < 727  # Можно улучшить до 727
                        ]
                        if craftable_items:
                            # Сортируем по уровню (самые низкие первыми)
                            craftable_items.sort(key=lambda x: x[1]['item_level'])
                            min_item_idx = craftable_items[0][0]
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

                # Проверяем лимит бюджета
                if self.budget_limit is not None and sum(total_resources) + sum(craft_cost) > self.budget_limit:
                    # Не можем позволить себе изготовление, пробуем улучшить
                    pass
                else:
                    # Рассчитываем потенциальное улучшение до максимального уровня сложности
                    max_upgrade_level = min(max_level_for_difficulty, 727)
                    can_upgrade_to_max = current_level < max_upgrade_level

                    # Рассчитываем стоимость улучшения до максимального уровня
                    if can_upgrade_to_max:
                        upgrade_cost_to_max = get_upgrade_cost(current_level, max_upgrade_level)
                    else:
                        upgrade_cost_to_max = (0, 0, 0)

                    # Принимаем решение на основе стратегии
                    decision = self.calculate_strategy_priority(
                        current_level, max_level_for_difficulty,
                        upgrade_cost_to_max, craft_cost
                    )

                    if decision == "skip":
                        # Пропускаем этот шаг из-за лимита бюджета
                        logger.info(f"Пропускаем {item_name} из-за лимита бюджета")
                        # Ищем другой предмет
                        available_items = [
                            (idx, priority, item) for idx, priority, item in priority_items[1:]
                            if item['item_level'] < 727
                            and item['slot'] not in self.crafted_slots
                        ]
                        if available_items:
                            min_item_idx = available_items[0][0]
                            current_level = upgraded_items[min_item_idx]['item_level']
                            item_slot = upgraded_items[min_item_idx]['slot']
                            item_name = upgraded_items[min_item_idx]['name']
                            item_difficulty = upgraded_items[min_item_idx]['difficulty']
                            is_special = upgraded_items[min_item_idx]['is_special']
                        else:
                            break
                    elif decision == "craft" or not can_upgrade_to_max or current_level >= max_level_for_difficulty:
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
                        self.total_spent_resources += sum(craft_cost)

                        logger.info(f"Шаг {step}: Изготовление предмета {upgraded_items[min_item_idx]['name']} {old_level}→{target_level}")
                        step += 1
                        current_avg = new_avg
                        continue

            # Обычное улучшение (если цель еще не достигнута)
            if current_avg < self.target_average and current_level < 727:
                next_level = self.get_next_upgrade_level(current_level, item_difficulty)

                # Для специальных предметов ограничиваем уровень 727
                if is_special and next_level and next_level > 727:
                    next_level = 727 if current_level < 727 else None

                # Ограничиваем уровнем сложности, но разрешаем до 727
                if next_level and next_level > max_level_for_difficulty:
                    next_level = min(next_level, 727)

                if next_level is None or next_level <= current_level:
                    logger.info(f"Предмет {item_name} не может быть улучшен дальше")
                    # Ищем другой предмет для улучшения
                    non_craftable_slots = NON_CRAFTABLE_SLOTS if self.exclude_trinkets else []
                    available_items = [
                        (idx, priority, item) for idx, priority, item in priority_items[1:]
                        if item['item_level'] < min(get_max_level_for_difficulty(item['difficulty']), 727)
                        and item['slot'] not in self.crafted_slots  # Исключаем уже использованные слоты
                        and item['item_level'] < 727
                        and not self.is_cycling_detected(item['slot'], item['item_level'])  # Исключаем зацикленные
                        and item['slot'] not in non_craftable_slots  # Исключаем неизготавливаемые слоты
                    ]
                    if available_items:
                        min_item_idx = available_items[0][0]  # Берем самый приоритетный
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
                            next_level = min(next_level, 727)
                    else:
                        logger.info("Все предметы достигли максимального уровня или в цикле")
                        # Проверяем возможность изготовления
                        if self.crafted_items_count < self.max_crafted_items:
                            non_craftable_slots = NON_CRAFTABLE_SLOTS if self.exclude_trinkets else []
                            craftable_items = [
                                (i, item) for i, item in enumerate(upgraded_items)
                                if item['slot'] not in non_craftable_slots
                                and item['slot'] not in self.crafted_slots
                                and item['item_level'] < 727
                            ]
                            if craftable_items:
                                # Сортируем по уровню
                                craftable_items.sort(key=lambda x: x[1]['item_level'])
                                min_item_idx = craftable_items[0][0]
                                current_level = upgraded_items[min_item_idx]['item_level']
                                item_slot = upgraded_items[min_item_idx]['slot']
                                item_name = upgraded_items[min_item_idx]['name']
                                is_special = upgraded_items[min_item_idx]['is_special']
                                # Продолжаем с изготовлением
                                continue
                        break

                if next_level is not None and next_level > current_level:
                    # Рассчитываем стоимость улучшения
                    cost = get_upgrade_cost(current_level, next_level)

                    # Проверяем лимит бюджета
                    if self.budget_limit is not None and sum(total_resources) + sum(cost) > self.budget_limit:
                        # Не можем позволить себе улучшение, ищем другой предмет
                        logger.info(f"Пропускаем улучшение {item_name} из-за лимита бюджета")
                        available_items = [
                            (idx, priority, item) for idx, priority, item in priority_items[1:]
                            if item['item_level'] < 727
                            and item['slot'] not in self.crafted_slots
                        ]
                        if available_items:
                            min_item_idx = available_items[0][0]
                            current_level = upgraded_items[min_item_idx]['item_level']
                            item_slot = upgraded_items[min_item_idx]['slot']
                            item_name = upgraded_items[min_item_idx]['name']
                            item_difficulty = upgraded_items[min_item_idx]['difficulty']
                            is_special = upgraded_items[min_item_idx]['is_special']
                            next_level = self.get_next_upgrade_level(current_level, item_difficulty)
                        else:
                            break
                        continue

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
                    self.total_spent_resources += sum(cost)

                    logger.debug(f"Шаг {step}: {upgraded_items[min_item_idx]['name']} {current_level}→{next_level} ({format_resources(cost)})")

                    step += 1
                    current_avg = new_avg
                else:
                    # Если не можем улучить, проверяем возможность изготовления
                    if self.can_craft_item(item_slot) and current_level < 727:
                        # Продолжаем с изготовлением
                        continue
                    else:
                        break

            # Проверяем достижение цели
            if current_avg >= self.target_average:
                break

        # Рассчитываем эффективность
        total_resource_cost = sum(total_resources)
        efficiency = ((current_avg - self.current_average) / total_resource_cost * 1000) if total_resource_cost > 0 else 0

        # Создаем копию финальных предметов для вывода
        final_items = [item.copy() for item in upgraded_items]

        # Генерируем рекомендации
        recommendations = generate_recommendations(self.items, self.target_average, self.crafted_slots, self.crafted_items_count)

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
            "final_items": final_items,
            "strategy": self.strategy,
            "strategy_name": OPTIMIZATION_STRATEGIES[self.strategy]["name"],
            "recommendations": recommendations,
            "max_crafted_items": self.max_crafted_items,
            "budget_limit": self.budget_limit,
            "exclude_trinkets": self.exclude_trinkets
        }

        logger.info(f"Оптимизация завершена. Ресурсы: {total_resource_cost}, Среднее: {current_avg:.2f}")
        return result

# ====================================================================================
# ДЕКОРАТОРЫ
# ====================================================================================

def handle_api_errors(f):
    """Декоратор для централизованной обработки ошибок API."""

    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.error(f"Ошибка валидации данных: {e}")
            return jsonify({"error": "Некорректные данные"}), 400
        except Exception as e:
            logger.error(f"Внутренняя ошибка сервера: {e}")
            return jsonify({"error": "Внутренняя ошибка сервера"}), 500

    wrapper.__name__ = f.__name__
    return wrapper

# ====================================================================================
# МАРШРУТЫ
# ====================================================================================

@app.route('/')
def index():
    """Главная страница приложения."""
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    """Манифест для PWA"""
    return jsonify({
        "name": "Raider.IO Optimizer",
        "short_name": "RaiderOptimizer",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1e3c72",
        "description": "Оптимизация улучшений предметов World of Warcraft"
    })

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
        "max_levels": MAX_LEVEL_BY_DIFFICULTY,
        "strategies": OPTIMIZATION_STRATEGIES,
        "character_classes": CHARACTER_CLASSES
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
    strategy = data.get('strategy', 'balanced')
    max_crafted_items = data.get('max_crafted_items', 9)
    budget_limit = data.get('budget_limit')
    exclude_trinkets = data.get('exclude_trinkets', False)
    show_alternatives = data.get('show_alternatives', False)

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

    if strategy not in OPTIMIZATION_STRATEGIES:
        strategy = 'balanced'  # По умолчанию

    # Валидация дополнительных параметров
    if max_crafted_items is not None:
        try:
            max_crafted_items = int(max_crafted_items)
            if max_crafted_items < 0 or max_crafted_items > 9:
                max_crafted_items = 9
        except (ValueError, TypeError):
            max_crafted_items = 9
    else:
        max_crafted_items = 9

    if budget_limit is not None:
        try:
            budget_limit = int(budget_limit)
            if budget_limit < 0:
                budget_limit = None
        except (ValueError, TypeError):
            budget_limit = None

    character = CharacterData(region, realm, character_name)
    if not character.fetch_data():
        return jsonify({"error": "Персонаж не найден. Проверьте правильность введенных данных."}), 404

    items = character.get_equipment_items()
    if not items:
        return jsonify({"error": "Не удалось получить данные о предметах персонажа"}), 400

    # Получаем дополнительную информацию о персонаже
    character_info = character.get_character_info()

    optimizer = UpgradeOptimizer(
        items,
        target_average,
        strategy,
        max_crafted_items=max_crafted_items,
        budget_limit=budget_limit,
        exclude_trinkets=exclude_trinkets
    )
    optimization_result = optimizer.find_optimal_path()

    end_time = datetime.now()
    processing_time = (end_time - start_time).total_seconds()

    result = {
        "status": "success",
        "character": character_info,
        "target_average": target_average,
        "processing_time": round(processing_time, 2),
        **optimization_result
    }

    if not result.get("message") and not result["goal_reached"]:
        result["message"] = f"Цель не достигнута. Максимальное достижимое среднее: {result['final_average']}"

    # Сохраняем в историю оптимизаций
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO optimization_history 
                (character_name, realm, region, target_average, strategy, final_average, total_resources, processing_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                character_name, realm, region, target_average, strategy,
                result['final_average'], result['total_resources_cost'], processing_time
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения истории оптимизации: {e}")

    logger.info(f"Анализ завершен за {processing_time:.2f} секунд")
    return jsonify(result)

@app.route('/api/strategies/compare', methods=['POST'])
@handle_api_errors
def compare_strategies_api():
    """Сравнивает разные стратегии оптимизации."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Неверный формат данных"}), 400

    region = data.get('region', 'eu').lower()
    realm = data.get('realm', '').strip()
    character_name = data.get('character_name', '').strip()
    target_average = data.get('target_average')
    max_crafted_items = data.get('max_crafted_items', 9)
    budget_limit = data.get('budget_limit')

    if not realm or not character_name or target_average is None:
        return jsonify({"error": "Необходимо указать все параметры"}), 400

    try:
        target_average = float(target_average)
    except (ValueError, TypeError):
        return jsonify({"error": "Целевое значение должно быть числом"}), 400

    # Валидация дополнительных параметров
    if max_crafted_items is not None:
        try:
            max_crafted_items = int(max_crafted_items)
            if max_crafted_items < 0 or max_crafted_items > 9:
                max_crafted_items = 9
        except (ValueError, TypeError):
            max_crafted_items = 9
    else:
        max_crafted_items = 9

    if budget_limit is not None:
        try:
            budget_limit = int(budget_limit)
            if budget_limit < 0:
                budget_limit = None
        except (ValueError, TypeError):
            budget_limit = None

    character = CharacterData(region, realm, character_name)
    if not character.fetch_data():
        return jsonify({"error": "Персонаж не найден"}), 404

    items = character.get_equipment_items()
    if not items:
        return jsonify({"error": "Не удалось получить данные о предметах"}), 400

    comparison = compare_strategies(items, target_average, max_crafted_items, budget_limit)

    return jsonify({
        "status": "success",
        "comparison": comparison,
        "character": {
            "name": character_name,
            "realm": realm,
            "region": REGIONS_LOCALIZED.get(region, region.upper())
        }
    })

@app.route('/api/profiles', methods=['GET', 'POST'])
def manage_profiles():
    """Управление профилями оптимизации"""
    if request.method == 'POST':
        profile_data = request.get_json()
        profile_id = hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]
        name = profile_data.get('name', f'Профиль {datetime.now().strftime("%Y-%m-%d %H:%M")}')
        description = profile_data.get('description', '')
        character_info = profile_data.get('character', {})

        try:
            with get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO profiles 
                    (id, name, description, character_name, realm, region, target_average, strategy, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    profile_id, name, description,
                    character_info.get('name', ''),
                    character_info.get('realm', ''),
                    character_info.get('region', ''),
                    profile_data.get('target_average', 0),
                    profile_data.get('strategy', 'balanced'),
                    json.dumps(profile_data)
                ))
                conn.commit()
            return jsonify({"status": "saved", "profile_id": profile_id})
        except Exception as e:
            logger.error(f"Ошибка сохранения профиля: {e}")
            return jsonify({"error": "Ошибка сохранения профиля"}), 500
    else:
        # Вернуть список профилей
        try:
            with get_db_connection() as conn:
                cursor = conn.execute('''
                    SELECT id, name, description, character_name, realm, region, target_average, strategy, created_at
                    FROM profiles
                    ORDER BY created_at DESC
                ''')
                profiles = cursor.fetchall()

                profiles_list = []
                for profile in profiles:
                    profiles_list.append({
                        "id": profile['id'],
                        "name": profile['name'],
                        "description": profile['description'],
                        "character": {
                            "name": profile['character_name'],
                            "realm": profile['realm'],
                            "region": profile['region']
                        },
                        "target_average": profile['target_average'],
                        "strategy": profile['strategy'],
                        "created_at": profile['created_at']
                    })
                return jsonify({"profiles": profiles_list})
        except Exception as e:
            logger.error(f"Ошибка получения профилей: {e}")
            return jsonify({"error": "Ошибка получения профилей"}), 500

@app.route('/api/profiles/<profile_id>', methods=['GET', 'DELETE'])
def profile_detail(profile_id):
    """Детали профиля"""
    if request.method == 'GET':
        try:
            with get_db_connection() as conn:
                cursor = conn.execute('SELECT * FROM profiles WHERE id = ?', (profile_id,))
                profile = cursor.fetchone()
                if profile:
                    return jsonify({
                        "id": profile['id'],
                        "name": profile['name'],
                        "description": profile['description'],
                        "data": json.loads(profile['data']) if profile['data'] else {},
                        "created_at": profile['created_at']
                    })
                else:
                    return jsonify({"error": "Профиль не найден"}), 404
        except Exception as e:
            logger.error(f"Ошибка получения профиля: {e}")
            return jsonify({"error": "Ошибка получения профиля"}), 500
    else:
        try:
            with get_db_connection() as conn:
                conn.execute('DELETE FROM profiles WHERE id = ?', (profile_id,))
                conn.commit()
                return jsonify({"status": "deleted"})
        except Exception as e:
            logger.error(f"Ошибка удаления профиля: {e}")
            return jsonify({"error": "Ошибка удаления профиля"}), 500

@app.route('/api/export/<format_type>', methods=['POST'])
def export_results(format_type):
    """Экспорт результатов в разных форматах"""
    data = request.get_json()

    if format_type == "json":
        return jsonify(data)
    elif format_type == "csv":
        # Простая реализация CSV экспорта
        csv_content = "Slot,Current Level,Final Level,Action,Cost\n"
        for item in data.get("final_items", []):
            csv_content += f"{item.get('readable_slot', '')},{item.get('item_level', '')},,,\n"
        return Response(csv_content, mimetype='text/csv', headers={
            'Content-Disposition': 'attachment; filename=raider_optimizer_export.csv'
        })
    else:
        return jsonify({"error": "Неподдерживаемый формат"}), 400

@app.route('/api/stats')
def get_stats():
    """Возвращает статистику API."""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute('SELECT COUNT(*) as profile_count FROM profiles')
            profile_count = cursor.fetchone()['profile_count']

            cursor = conn.execute('SELECT COUNT(*) as optimization_count FROM optimization_history')
            optimization_count = cursor.fetchone()['optimization_count']
    except:
        profile_count = 0
        optimization_count = 0

    return jsonify({
        "status": "online",
        "version": "4.0.0",
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
        "strategies": OPTIMIZATION_STRATEGIES,
        "character_classes": CHARACTER_CLASSES,
        "stats": {
            "profiles_created": profile_count,
            "optimizations_performed": optimization_count
        },
        "last_updated": datetime.now().isoformat()
    })

@app.route('/api/recommendations/class/<character_class>/<specialization>')
def get_class_recommendations_api(character_class, specialization):
    """Возвращает рекомендации по классу и специализации"""
    recommendation = get_class_recommendations(character_class, specialization)
    return jsonify({
        "class": character_class,
        "specialization": specialization,
        "recommendation": recommendation
    })

@app.route('/api/history')
def get_optimization_history():
    """Возвращает историю оптимизаций"""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM optimization_history
                ORDER BY created_at DESC
                LIMIT 50
            ''')
            history = cursor.fetchall()

            history_list = []
            for record in history:
                history_list.append({
                    "id": record['id'],
                    "character_name": record['character_name'],
                    "realm": record['realm'],
                    "region": record['region'],
                    "target_average": record['target_average'],
                    "strategy": record['strategy'],
                    "final_average": record['final_average'],
                    "total_resources": record['total_resources'],
                    "processing_time": record['processing_time'],
                    "created_at": record['created_at']
                })
            return jsonify({"history": history_list})
    except Exception as e:
        logger.error(f"Ошибка получения истории: {e}")
        return jsonify({"error": "Ошибка получения истории"}), 500

# Обработка ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Страница не найдена"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Внутренняя ошибка сервера: {error}")
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500

# Инициализация базы данных при запуске
with app.app_context():
    init_db()

if __name__ == '__main__':
    # Получаем параметры из переменных окружения
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'

    logger.info(f"Запуск Raider.IO Optimizer на {host}:{port}")
    app.run(host=host, port=port, debug=debug)
