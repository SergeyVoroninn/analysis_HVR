"""
Генератор профилей спортсменов с физиологическими параметрами.
"""

import datetime
import random
import uuid

CURRENT_YEAR = datetime.date.today().year

BASE_NAMES = [
    "Иван", "Пётр", "Дамир", "Ильдар", "Максим",
    "Артём", "Андрей", "Сергей", "Дмитрий", "Алексей",
    "Игорь", "Виталий", "Роман", "Тимур", "Марат",
    "Руслан", "Кирилл", "Егор", "Артур", "Богдан",
]

FEMALE_FIRST_NAMES = [
    "Анна", "Мария", "Дарья", "Анастасия", "Виктория",
    "Полина", "Екатерина", "Ксения", "Алина", "София",
    "Ева", "Вероника", "Арина", "Алиса", "Варвара",
    "Милана", "Диана", "Кира", "Юлия", "Олеся",
]


def _to_base(name):
    """Нормализуем основу: заменяем ё на е."""
    return name.replace('ё', 'е')


def _make_last_name(base, gender):
    """Фамилия из основы имени."""
    base = _to_base(base)
    if base.endswith(('й', 'ь')):
        return base[:-1] + ('ева' if gender == 'F' else 'ев')
    return base + ('ова' if gender == 'F' else 'ов')


def _make_middle_name(base, gender):
    """Отчество из основы имени."""
    base = _to_base(base)
    if base.endswith(('й', 'ь')):
        return base[:-1] + ('евна' if gender == 'F' else 'евич')
    return base + ('овна' if gender == 'F' else 'ович')


def _generate_polar_id():
    """Генерирует ID датчика Polar в формате C8208E2E."""
    return ''.join(random.choices('0123456789ABCDEF', k=8))


def _estimate_height_cm(age, gender):
    """Приблизительный рост с учётом возраста и пола."""
    adult = 178 if gender == 'M' else 166
    if age >= 18:
        return adult + random.randint(-8, 8)
    ratio = 0.70 + 0.30 * (max(age - 6, 0) / 12)
    return int(adult * ratio) + random.randint(-4, 4)


def _estimate_weight_kg(height_cm, age, gender):
    """Приблизительный вес через ИМТ."""
    if age < 12:
        bmi = random.uniform(15, 18)
    elif age < 18:
        bmi = random.uniform(17, 21)
    else:
        bmi = random.uniform(19, 24) if gender == 'M' else random.uniform(18, 23)
    return round(bmi * (height_cm / 100) ** 2, 1)


def _estimate_resting_hr(age, gender):
    """Пульс покоя: выше у детей и женщин."""
    if age < 8:
        hr = random.randint(85, 105)
    elif age < 12:
        hr = random.randint(75, 95)
    elif age < 15:
        hr = random.randint(65, 85)
    elif age < 18:
        hr = random.randint(58, 78)
    else:
        hr = random.randint(48, 68)
    if gender == 'F':
        hr += random.randint(3, 7)
    return hr


def _estimate_max_hr(age):
    """Максимальный пульс по формуле Tanaka: 208 - 0.7*age."""
    return int(208 - 0.7 * age)


def _estimate_hrv_rmssd(age):
    """Базовая вариабельность (RMSSD): выше у молодых."""
    if age < 13:
        return random.randint(55, 90)
    elif age < 20:
        return random.randint(45, 80)
    elif age < 30:
        return random.randint(35, 70)
    else:
        return random.randint(25, 55)


def create_athlete(birth_year, gender):
    """
    Генерирует профиль спортсмена с ФИО и физиологией.

    :param birth_year: год рождения (например, 2010)
    :param gender: 'M' или 'F'
    :return: словарь с профилем спортсмена
    """
    gender = gender.upper()
    if gender not in ('M', 'F'):
        raise ValueError("gender must be 'M' or 'F'")

    age = CURRENT_YEAR - birth_year
    if age < 0:
        raise ValueError("birth_year is in the future")

    last_name = _make_last_name(random.choice(BASE_NAMES), gender)
    middle_name = _make_middle_name(random.choice(BASE_NAMES), gender)
    first_name = (random.choice(BASE_NAMES) if gender == 'M'
                  else random.choice(FEMALE_FIRST_NAMES))

    height_cm = _estimate_height_cm(age, gender)
    weight_kg = _estimate_weight_kg(height_cm, age, gender)
    resting_hr = _estimate_resting_hr(age, gender)
    max_hr = _estimate_max_hr(age)
    hrv_rmssd = _estimate_hrv_rmssd(age)
    avg_rr_ms = int(60000 / resting_hr)

    return {
        "id": str(uuid.uuid4()),
        "last_name": last_name,
        "first_name": first_name,
        "middle_name": middle_name,
        "gender": gender,
        "birth_year": birth_year,
        "age": age,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "resting_hr": resting_hr,
        "max_hr": max_hr,
        "hrv_rmssd_baseline": hrv_rmssd,
        "avg_rr_ms": avg_rr_ms,
        "polar_id": _generate_polar_id(),
    }


if __name__ == '__main__':
    # Тест: генерируем 5 спортсменов
    for _ in range(5):
        athlete = create_athlete(random.randint(2000, 2012), random.choice(['M', 'F']))
        print(f"{athlete['last_name']} {athlete['first_name']} | "
              f"{athlete['gender']}, {athlete['age']} лет | "
              f"рост {athlete['height_cm']}, вес {athlete['weight_kg']} | "
              f"пульс покоя {athlete['resting_hr']}")