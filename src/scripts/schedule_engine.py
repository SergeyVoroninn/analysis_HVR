"""
Движок генерации расписаний ЭКГ на основе конфигурации.
Импортирует генератор спортсменов из athlete_generator.
"""

import datetime
import random
import yaml

from athlete_generator import create_athlete

WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3,
               "fri": 4, "sat": 5, "sun": 6}


# ============================================================
# ГЕНЕРАТОРЫ ВРЕМЕНИ СУТОК
# ============================================================
def _minutes_to_hm(total):
    return total // 60, total % 60


def _morning():        # 07:00–09:30
    return _minutes_to_hm(random.randint(7 * 60, 9 * 60 + 30))


def _lunch():          # 12:00–14:00
    return _minutes_to_hm(random.randint(12 * 60, 14 * 60))


def _evening():        # 18:00–21:00
    return _minutes_to_hm(random.randint(18 * 60, 21 * 60))


def _random_daytime(): # 07:00–22:00
    return _minutes_to_hm(random.randint(7 * 60, 22 * 60))


SLOT_GENERATORS = {"morning": _morning, "lunch": _lunch, "evening": _evening}


def _dt(date, hm):
    h, m = hm
    return datetime.datetime(date.year, date.month, date.day, h, m)


def _times_for_day(slots, times_per_day):
    if slots == "random":
        return sorted([_random_daytime() for _ in range(times_per_day)])
    return sorted([SLOT_GENERATORS[s]() for s in slots])


def _add_day(out, date, slots, times_per_day):
    for hm in _times_for_day(slots, times_per_day):
        out.append(_dt(date, hm))


def _weekday_nums(names):
    return {WEEKDAY_MAP[n] for n in names}


# ============================================================
# ДИАПАЗОН СЕЗОНА
# ============================================================
def _season_range(season, ref):
    year = ref.year
    seasons = {
        "summer": (datetime.date(year, 6, 1),  datetime.date(year, 8, 31)),
        "autumn": (datetime.date(year, 9, 1),  datetime.date(year, 11, 30)),
        "winter": (datetime.date(year, 1, 1),  datetime.date(year, 2, 28)),
        "spring": (datetime.date(year, 3, 1),  datetime.date(year, 5, 31)),
    }
    start, end = seasons[season]
    return start, min(end, ref)


# ============================================================
# ГЕНЕРАЦИЯ ПО ДИАПАЗОНУ ДАТ
# ============================================================
def _gen_by_range(start, end, days_cfg, slots, times_per_day):
    dtype = days_cfg["type"]
    out = []

    if dtype == "random_gap":
        d = end
        while d >= start:
            _add_day(out, d, slots, times_per_day)
            d -= datetime.timedelta(days=random.randint(
                days_cfg["min_days"], days_cfg["max_days"]))
        return sorted(out)

    if dtype == "random_days_per_week":
        count = days_cfg["count"]
        week = start - datetime.timedelta(days=start.weekday())
        while week <= end:
            for dd in random.sample(range(7), count):
                day = week + datetime.timedelta(days=dd)
                if start <= day <= end:
                    _add_day(out, day, slots, times_per_day)
            week += datetime.timedelta(weeks=1)
        return sorted(out)

    wanted = None if dtype == "every_day" else _weekday_nums(days_cfg["weekdays"])
    d = start
    while d <= end:
        if wanted is None or d.weekday() in wanted:
            _add_day(out, d, slots, times_per_day)
        d += datetime.timedelta(days=1)
    return sorted(out)


# ============================================================
# ГЕНЕРАЦИЯ ПО ОБЩЕМУ КОЛИЧЕСТВУ
# ============================================================
def _gen_by_count(total, days_cfg, slots, times_per_day, ref):
    dtype = days_cfg["type"]
    out = []

    if dtype == "weekdays":
        wanted = _weekday_nums(days_cfg["weekdays"])
        d = ref
        while len(out) < total:
            if d.weekday() in wanted:
                _add_day(out, d, slots, times_per_day)
            d -= datetime.timedelta(days=1)

    elif dtype == "every_day":
        d = ref
        while len(out) < total:
            _add_day(out, d, slots, times_per_day)
            d -= datetime.timedelta(days=1)

    elif dtype == "random_days_per_week":
        count = days_cfg["count"]
        week = ref - datetime.timedelta(days=ref.weekday())
        while len(out) < total:
            for dd in random.sample(range(7), count):
                day = week + datetime.timedelta(days=dd)
                if day <= ref:
                    _add_day(out, day, slots, times_per_day)
            week -= datetime.timedelta(weeks=1)

    return sorted(out[:total])


# ============================================================
# ГЛАВНЫЙ ДИСПЕТЧЕР
# ============================================================
def generate_schedule(profile_cfg, ref):
    extent = profile_cfg["extent"]
    days_cfg = profile_cfg["days"]
    slots = profile_cfg.get("slots", "random")
    times_per_day = profile_cfg.get("times_per_day", 1)

    if "total_records" in extent:
        return _gen_by_count(extent["total_records"], days_cfg,
                             slots, times_per_day, ref)
    if "period_days" in extent:
        start = ref - datetime.timedelta(days=extent["period_days"])
        return _gen_by_range(start, ref, days_cfg, slots, times_per_day)
    if "season" in extent:
        start, end = _season_range(extent["season"], ref)
        return _gen_by_range(start, end, days_cfg, slots, times_per_day)
    raise ValueError(f"Неизвестный extent: {extent}")


# ============================================================
# ЗАГРУЗКА КОНФИГА И СБОРКА РАСПИСАНИЙ
# ============================================================
def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_schedules(config_path="config.yaml"):
    """Собирает команду из конфига и строит расписание для каждого."""
    cfg = load_config(config_path)
    ref = datetime.date.fromisoformat(cfg["reference_date"])
    profiles_lib = cfg["profiles"]

    result = []
    for member in cfg["team"]:
        profile_name = member["profile"]
        if profile_name not in profiles_lib:
            raise KeyError(
                f"Профиль '{profile_name}' не найден в секции profiles")

        athlete = create_athlete(member["birth_year"], member["gender"])

        for key in ("first_name", "last_name", "middle_name", "polar_id"):
            if key in member:
                athlete[key] = member[key]

        times = generate_schedule(profiles_lib[profile_name], ref)
        result.append((athlete, profile_name, times))
    return result


def summarize(config_path="config.yaml"):
    for athlete, pname, times in build_schedules(config_path):
        fio = f"{athlete['last_name']} {athlete['first_name']}"
        print(f"{fio:22} | {athlete['gender']},{athlete['birth_year']} | "
              f"{pname:22} | записей: {len(times):5} | "
              f"{times[0].date()} ... {times[-1].date()}")


if __name__ == '__main__':
    summarize()