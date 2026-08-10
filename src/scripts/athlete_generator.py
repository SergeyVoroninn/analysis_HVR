"""
Генератор профилей спортсменов с физиологическими параметрами.
"""

import datetime
import random
import uuid

TODAY = datetime.date.today()
CURRENT_YEAR = TODAY.year

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
    return name.replace('ё', 'е')


def _make_last_name(base, gender):
    base = _to_base(base)
    if base.endswith(('й', 'ь')):
        return base[:-1] + ('ева' if gender == 'F' else 'ев')
    return base + ('ова' if gender == 'F' else 'ов')


def _make_middle_name(base, gender):
    base = _to_base(base)
    if base.endswith(('й', 'ь')):
        return base[:-1] + ('евна' if gender == 'F' else 'евич')
    return base + ('овна' if gender == 'F' else 'ович')


def _generate_polar_id():
    return ''.join(random.choices('0123456789ABCDEF', k=8))


def _random_date_in_year(year):
    """Генерирует случайную дату в заданном году (учитывает длину месяца)."""
    month = random.randint(1, 12)
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
    else:
        next_month = datetime.date(year, month + 1, 1)
    first_of_month = datetime.date(year, month, 1)
    days_in_month = (next_month - first_of_month).days
    day = random.randint(1, days_in_month)
    return datetime.date(year, month, day)


def _calc_age(birth_date):
    """
    Полный возраст в годах на сегодня.
    Принимает datetime.date ИЛИ строку ISO "YYYY-MM-DD" (как приходит из SQLite).
    """
    if not birth_date:
        return 0
    if isinstance(birth_date, str):
        try:
            birth_date = datetime.date.fromisoformat(birth_date)
        except ValueError:
            return 0
    age = TODAY.year - birth_date.year
    if (TODAY.month, TODAY.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def _estimate_height_cm(age, gender):
    adult = 178 if gender == 'M' else 166
    if age >= 18:
        return adult + random.randint(-8, 8)
    ratio = 0.70 + 0.30 * (max(age - 6, 0) / 12)
    return int(adult * ratio) + random.randint(-4, 4)


def _estimate_weight_kg(height_cm, age, gender):
    if age < 12:
        bmi = random.uniform(15, 18)
    elif age < 18:
        bmi = random.uniform(17, 21)
    else:
        bmi = random.uniform(19, 24) if gender == 'M' else random.uniform(18, 23)
    return round(bmi * (height_cm / 100) ** 2, 1)


def _estimate_resting_hr(age, gender):
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
    return int(208 - 0.7 * age)


def _estimate_hrv_rmssd(age):
    if age < 13:
        return random.randint(55, 90)
    elif age < 20:
        return random.randint(45, 80)
    elif age < 30:
        return random.randint(35, 70)
    else:
        return random.randint(25, 55)


def create_athlete(birth_year, gender='M'):
    """
    Генерирует профиль спортсмена с ФИО и физиологией.

    :param birth_year: год рождения (например, 2010)
    :param gender: 'M' или 'F'
    :return: dict с профилем (birth_date = случайный день в году)
    """
    gender = gender.upper()
    if gender not in ('M', 'F'):
        raise ValueError("gender must be 'M' or 'F'")

    birth_year = int(birth_year)
    if birth_year > CURRENT_YEAR:
        raise ValueError("birth_year is in the future")

    # Случайная дата в заданном году — генерируется один раз
    bd = _random_date_in_year(birth_year)
    age = _calc_age(bd)

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
        "birth_date": bd.isoformat(),          # DATE в ISO-формате
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "resting_hr": resting_hr,
        "max_hr": max_hr,
        "hrv_rmssd_baseline": hrv_rmssd,
        "avg_rr_ms": avg_rr_ms,
        "polar_id": _generate_polar_id(),
    }


if __name__ == '__main__':
    for _ in range(5):
        year = random.randint(2000, 2012)
        athlete = create_athlete(birth_year=year, gender=random.choice(['M', 'F']))
        bd = datetime.date.fromisoformat(athlete['birth_date'])
        age = _calc_age(bd)
        print(f"{athlete['last_name']} {athlete['first_name']} | "
              f"{athlete['gender']}, {bd.isoformat()} ({age} лет) | "
              f"рост {athlete['height_cm']}, вес {athlete['weight_kg']} | "
              f"пульс покоя {athlete['resting_hr']}")