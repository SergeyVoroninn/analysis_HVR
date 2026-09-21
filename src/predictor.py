"""predictor.py"""
from dataclasses import dataclass
from typing import List, Tuple, Optional

@dataclass
class ForecastPoint:
    x: float
    y: float
    confidence: float

class PIDPredictor:
    def __init__(
        self, 
        history_days: float = 7.0, 
        forecast_days: int = 1, 
        min_points: int = 3,
        value_floor: Optional[float] = None,    # Минимально возможное значение (например, 0)
        value_ceiling: Optional[float] = None   # Максимально возможное значение
    ):
        self.history_days = history_days
        self.forecast_days = forecast_days
        self.min_points = min_points
        self.value_floor = value_floor
        self.value_ceiling = value_ceiling

        # Коэффициенты можно вынести в app_constants, если нужно, 
        # но пока оставим здесь для простоты
        self.kp, self.ki, self.kd = 0.5, 0.3, 0.2

    def predict(self, points: List[Tuple[float, float]]) -> List[ForecastPoint]:
        if len(points) < self.min_points:
            return []

        points = sorted(points, key=lambda p: p[0])
        last_x = points[-1][0]
        recent = [(x, y) for x, y in points if (last_x - x) <= self.history_days]
        
        if len(recent) < self.min_points:
            return []

        # Вычисляем суточные изменения
        dy = []
        for i in range(1, len(recent)):
            dx = recent[i][0] - recent[i - 1][0]
            if dx > 0:
                dy.append((recent[i][1] - recent[i - 1][1]) / dx)

        if len(dy) < 2:
            return []

        P = dy[-1]
        I = sum(dy) / len(dy)
        D = dy[-1] - dy[-2]

        delta_y = (self.kp * P) + (self.ki * I) + (self.kd * D)

        forecast = []
        current_y = recent[-1][1]
        current_x = recent[-1][0]

        for day_offset in range(1, self.forecast_days + 1):
            next_x = current_x + day_offset
            next_y = current_y + delta_y * day_offset

            # Применяем физические ограничения, если они заданы
            if self.value_floor is not None:
                next_y = max(self.value_floor, next_y)
            if self.value_ceiling is not None:
                next_y = min(self.value_ceiling, next_y)

            confidence = max(0.0, 1.0 - (day_offset - 1) * 0.25)
            forecast.append(ForecastPoint(x=next_x, y=next_y, confidence=confidence))

        return forecast