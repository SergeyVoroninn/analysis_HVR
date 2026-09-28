# -*- coding: utf-8 -*-
"""
build_bio_ecg_reference.py — формирует эталонный набор данных для
регрессионного теста модуля определения атлета по ЭКГ (ecg_biometrics).

Что делает:
  1. Берёт исходные записи 4 атлетов (andrey, filipp, konstantin, trofim)
     из raw_data/sambo.
  2. Дедуплицирует записи по содержимому (md5): часть файлов продублирована
     и/или переименована — «бардак».
  3. Выбирает атлета-эталона с наибольшим набором уникальных записей.
  4. Копирует его записи в <tests>/bio_ecg_reference/template/ — из них тест
     строит биометрический шаблон.
  5. Копирует по ОДНОЙ записи каждого атлета в <tests>/bio_ecg_reference/probes/
     (пробой эталона выводится из шаблона — hold-out).
  6. Пишет manifest.json: эталон, список атлетов, соответствие probe->атлет,
     список файлов шаблона.

Скрипт идемпотентен: можно перегенерировать набор заново.
"""
import os
import sys
import json
import shutil
import hashlib
from pathlib import Path

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT = os.path.dirname(SRC)
TESTS_DIR = os.path.join(SRC, "tests")
OUT_DIR = os.path.join(TESTS_DIR, "bio_ecg_reference")

SAMBO = os.path.join(PROJECT, "raw_data", "sambo")
ATHLETE_FOLDERS = {
    "andrey": "andrey",
    "filipp": "filipp",
    "konstantin": "konstantin",
    "trofim": "trofim",
}

# Рекомендуемые пробы. Выбираем содержательные именованные записи;
# автоматика ниже всё равно отбросит файл, если его содержимое входит в шаблон эталона.
PREFERRED_PROBES = {
    "andrey": "84E5FD2B_2026_08_17_09_00_09_teamloggerh10.teamloggerh10",
    "filipp": "C8219D21_2026_08_15_09_07_07_teamloggerh10.teamloggerh10",
    "konstantin": "C821E528_2026_08_11_08_48_07_teamloggerh10.teamloggerh10",
    "trofim": "C821EB2E_2026_08_24_09_08_21_teamloggerh10.teamloggerh10",
}


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(folder):
    return [f for f in sorted(os.listdir(folder))
            if os.path.isfile(os.path.join(folder, f))]


def main():
    # 1. Собираем содержимое по атлетам (хэш -> список (атлет, файл)).
    content = {}          # h -> [(athlete, filename)]
    for athlete, folder in ATHLETE_FOLDERS.items():
        adir = os.path.join(SAMBO, folder)
        for fname in list_files(adir):
            h = md5(os.path.join(adir, fname))
            if fname.startswith("~"):
                continue
            content.setdefault(h, []).append((athlete, fname))

    # 2. Уникальные записи по каждому атлету (по хэшу).
    unique = {a: {} for a in ATHLETE_FOLDERS}   # athlete -> {h: filename}
    for h, items in content.items():
        for athlete, fname in items:
            # держим первое (сортировка уже по имени) — представителя хэша
            unique[athlete].setdefault(h, fname)

    counts = {a: len(m) for a, m in unique.items()}
    print("Уникальных файлов по атлетам:", counts)

    # 3. Эталон = атлет с наибольшим набором уникальных записей.
    etalon = max(counts, key=counts.get)
    print("Атлет-эталон:", etalon, "записей:", counts[etalon])

    # 4. Чистим выходную папку.
    for sub in ("template", "probes", "manifest.json", "results_golden.json"):
        p = os.path.join(OUT_DIR, sub)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    os.makedirs(os.path.join(OUT_DIR, "template"), exist_ok=True)
    os.makedirs(os.path.join(OUT_DIR, "probes"), exist_ok=True)

    # 5. Шаблон = уникальные записи эталона (кроме той, что уйдёт в пробы).
    probe_etalon = PREFERRED_PROBES[etalon]
    etalon_src_dir = os.path.join(SAMBO, ATHLETE_FOLDERS[etalon])
    etalon_probe_hash = md5(os.path.join(etalon_src_dir, probe_etalon))

    template_hashes = sorted(h for h in unique[etalon] if h != etalon_probe_hash)
    template_records = []
    for i, h in enumerate(template_hashes, 1):
        src_name = unique[etalon][h]
        src_path = os.path.join(etalon_src_dir, src_name)
        dst_name = f"{etalon}_{i:02d}.teamloggerh10"
        dst_path = os.path.join(OUT_DIR, "template", dst_name)
        shutil.copy2(src_path, dst_path)
        template_records.append({
            "file": f"template/{dst_name}",
            "content_hash": h,
            "source": src_name,
        })

    # 6. Пробы: по одной записи каждого атлета.
    probes = {}
    for athlete in ATHLETE_FOLDERS:
        adir = os.path.join(SAMBO, ATHLETE_FOLDERS[athlete])
        chosen = None
        chosen_hash = None
        # Отдаём приоритет рекомендованной пробе, если она есть у атлета и
        # (для эталона) не входит в шаблон.
        pref = PREFERRED_PROBES.get(athlete)
        if pref and os.path.exists(os.path.join(adir, pref)):
            ph = md5(os.path.join(adir, pref))
            if ph != etalon_probe_hash or athlete == etalon:
                chosen, chosen_hash = pref, ph
        # Запасной вариант: первый файл, чей хэш не входит в шаблон эталона.
        if chosen is None:
            for fname in list_files(adir):
                h = md5(os.path.join(adir, fname))
                if h not in set(template_hashes + [etalon_probe_hash]):
                    chosen, chosen_hash = fname, h
                    break
        if chosen is None:
            # последняя надежда: пробуем любой файл кроме пробы эталона
            for fname in list_files(adir):
                if fname != pref:
                    chosen, chosen_hash = fname, md5(os.path.join(adir, fname))
                    break
        if chosen is None:
            sys.exit(f"Нет файла для пробы атлета {athlete}")

        dst = f"{athlete}_probe.teamloggerh10"
        shutil.copy2(os.path.join(adir, chosen), os.path.join(OUT_DIR, "probes", dst))
        probes[athlete] = {
            "file": f"probes/{dst}",
            "content_hash": chosen_hash,
            "source": chosen,
        }

    # 7. Manifest.
    manifest = {
        "description": (
            "Эталонный набор для регрессионного теста определения атлета по ЭКГ. "
            "template/ — записи атлета-эталона, из которых тест строит биометрический "
            "шаблон; probes/ — по одной записи каждого атлета для сравнения с шаблоном. "
            "Запись, принадлежащая эталонному атлету, должна дать наибольшее совпадение."
        ),
        "etalon_athlete": etalon,
        "unique_records_count": counts,
        "template": {
            "count": len(template_records),
            "records": template_records,
        },
        "probes": probes,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Готово. Папка: {OUT_DIR}")
    print("Записей в шаблоне (эталон, hold-out проба исключена):", len(template_records))
    for athlete, info in probes.items():
        print(f"Проба {athlete}: {info['file']} (источник: {info['source']})")


if __name__ == "__main__":
    main()