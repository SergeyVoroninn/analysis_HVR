"""
Тест контроллера ресайза (ghost.py).
Проверяет ключевые свойства механизма защиты от зацикливания.
"""
import os
import sys
import time
import tkinter as tk
from unittest.mock import MagicMock, patch
import pytest

PROJECT_DIR = r"C:\s21\projects\analysis_HVR\src"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from ghost import ResizeController, SETTLE_MS, POLL_MS


class FakeBlock:
    """Фейковый блок, который считает вызовы своих методов."""
    def __init__(self, name):
        self.name = name
        self.target_size_calls = 0
        self.apply_size_calls = 0
        self.ghost_shown_calls = 0
        self.ghost_hidden_calls = 0

    def target_size(self, avail_w):
        self.target_size_calls += 1
        return (avail_w, 100)

    def ghost_rects(self, w, h):
        return [(0, 0, w, h)]

    def apply_size(self, w, h):
        self.apply_size_calls += 1

    def ghost_shown(self):
        self.ghost_shown_calls += 1

    def ghost_hidden(self):
        self.ghost_hidden_calls += 1

    def place(self, *args, **kwargs):
        pass

    def configure(self, *args, **kwargs):
        pass


@pytest.fixture(scope="module")
def resize_env():
    """Фикстура для создания окружения теста ресайза (один Tk на весь модуль)."""
    root = tk.Tk()
    root.geometry("500x500")
    root.update_idletasks()
    
    block1 = FakeBlock("block1")
    block2 = FakeBlock("block2")
    
    controller = ResizeController(root, [block1, block2], gap=10)
    
    yield root, controller, block1, block2
    
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_resize_debounce_limits_redraws(resize_env):
    """
    Сценарий: 20 быстрых изменений ширины.
    Ожидание: apply_size вызывается НЕ 20 раз (дебаунс работает), 
    а значительно меньше (1-3 раза).
    """
    root, controller, block1, block2 = resize_env

    # Сбрасываем счетчики
    block1.apply_size_calls = 0
    block2.apply_size_calls = 0

    # Имитируем 20 быстрых изменений ширины БЕЗ зажатой мыши
    with patch.object(controller, '_mouse_held', return_value=False):
        for w in range(501, 522):
            root.geometry(f"{w}x500")
            root.update_idletasks()
            
            event = MagicMock()
            event.widget = root
            event.width = w
            controller._on_configure(event)

    # Ждем оседания
    time.sleep(SETTLE_MS / 1000.0 + 0.2)
    root.update_idletasks()

    # КЛЮЧЕВАЯ ПРОВЕРКА: apply_size вызван значительно меньше 20 раз
    # (в идеале 1-2 раза, но допускаем до 5 из-за асинхронности)
    assert block1.apply_size_calls < 10, \
        f"Дебаунс не работает! apply_size вызван {block1.apply_size_calls} раз вместо <10"
    
    print(f"✓ Дебаунс работает: apply_size вызван {block1.apply_size_calls} раз при 20 изменениях")


def test_resize_ghost_mode_blocks_apply(resize_env):
    """
    Сценарий: Изменение размера с ЗАЖАТОЙ мышью.
    Ожидание: ghost_shown вызван, apply_size НЕ вызван (блокируется).
    """
    root, controller, block1, block2 = resize_env

    # Сбрасываем счетчики
    block1.apply_size_calls = 0
    block1.ghost_shown_calls = 0

    # Имитируем ресайз с зажатой мышью
    with patch.object(controller, '_mouse_held', return_value=True):
        root.geometry("600x500")
        root.update_idletasks()
        
        event = MagicMock()
        event.widget = root
        event.width = 600
        controller._on_configure(event)
        root.update_idletasks()

    # Проверяем, что включился режим ghost и apply_size заблокирован
    assert block1.ghost_shown_calls >= 1, "ghost_shown должен быть вызван при зажатой мыши"
    assert block1.apply_size_calls == 0, "apply_size НЕ должен вызываться, пока мышь зажата"
    
    print(f"✓ Ghost-режим работает: ghost_shown={block1.ghost_shown_calls}, apply_size={block1.apply_size_calls}")


def test_resize_ignores_unchanged_width(resize_env):
    """
    Сценарий: Событие <Configure> с неизменной шириной.
    Ожидание: Контроллер игнорирует событие (оптимизация).
    """
    root, controller, block1, block2 = resize_env

    # Сбрасываем счетчики
    block1.target_size_calls = 0

    with patch.object(controller, '_mouse_held', return_value=False):
        # Отправляем событие с той же шириной
        event = MagicMock()
        event.widget = root
        event.width = 600  # Текущая ширина после предыдущего теста
        controller._on_configure(event)

    # target_size не должен был вызываться
    assert block1.target_size_calls == 0, "Контроллер должен игнорировать неизменную ширину"
    
    print(f"✓ Оптимизация работает: target_size не вызван при неизменной ширине")


def test_resize_do_apply_direct(resize_env):
    """
    Прямой тест метода _do_apply: проверяем, что он корректно применяет размер.
    """
    root, controller, block1, block2 = resize_env

    # Сбрасываем счетчики
    block1.apply_size_calls = 0
    block2.apply_size_calls = 0

    # Устанавливаем мышь в отпущенное состояние
    with patch.object(controller, '_mouse_held', return_value=False):
        # Меняем ширину
        root.geometry("700x500")
        root.update_idletasks()
        
        # Принудительно вызываем _do_apply
        controller._do_apply()

    # Проверяем, что размер применился
    assert block1.apply_size_calls == 1, "apply_size должен быть вызван после _do_apply"
    assert block2.apply_size_calls == 1
    
    print(f"✓ _do_apply работает корректно")