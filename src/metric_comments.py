"""
metric_comments.py — DAO для комментариев к метрикам.

Комментарий привязывается к (атлет, ключ метрики, дата) — то есть к точке
на графике метрики. Функции работают через существующую сессию models.
"""
import datetime

from models import get_session, MetricComment


def upsert_comment(db_path, athlete_id, metric_key, comment_date, comment):
    """Создаёт или обновляет комментарий для (атлет, метрика, дата).

    Если комментарий для пары уже есть — обновляет текст. Иначе создаёт новый.
    Пустой comment удаляет запись (удобно для очистки).
    """
    comment = (comment or "").strip()
    session = get_session(db_path)
    try:
        row = (session.query(MetricComment)
               .filter_by(athlete_id=athlete_id, metric_key=metric_key,
                          comment_date=comment_date)
               .first())
        if not comment:
            if row is not None:
                session.delete(row)
                session.commit()
            return False
        if row is None:
            row = MetricComment(athlete_id=athlete_id, metric_key=metric_key,
                                comment_date=comment_date, comment=comment)
            session.add(row)
        else:
            row.comment = comment
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_comment(db_path, athlete_id, metric_key, comment_date):
    """Возвращает текст комментария для (атлет, метрика, дата) или None."""
    session = get_session(db_path)
    try:
        row = (session.query(MetricComment)
               .filter_by(athlete_id=athlete_id, metric_key=metric_key,
                          comment_date=comment_date)
               .first())
        return row.comment if row else None
    finally:
        session.close()


def get_comments_for_date(db_path, athlete_id, comment_date):
    """Возвращает {metric_key: comment} для всех метрик за дату."""
    session = get_session(db_path)
    try:
        rows = (session.query(MetricComment)
                .filter_by(athlete_id=athlete_id, comment_date=comment_date)
                .all())
        return {r.metric_key: r.comment for r in rows}
    finally:
        session.close()


def get_comment_map(db_path, athlete_id, metric_key):
    """Возвращает {comment_date: comment} для атлета и конкретной метрики."""
    session = get_session(db_path)
    try:
        rows = (session.query(MetricComment)
                .filter_by(athlete_id=athlete_id, metric_key=metric_key)
                .all())
        return {r.comment_date: r.comment for r in rows}
    finally:
        session.close()


def list_comments(db_path, athlete_id, metric_key=None):
    """Возвращает список комментариев атлета (опционально по метрике).

    Элементы: dict {metric_key, comment_date, comment}.
    """
    session = get_session(db_path)
    try:
        q = session.query(MetricComment).filter(MetricComment.athlete_id == athlete_id)
        if metric_key:
            q = q.filter(MetricComment.metric_key == metric_key)
        rows = q.order_by(MetricComment.comment_date).all()
        return [{"metric_key": r.metric_key,
                 "comment_date": r.comment_date,
                 "comment": r.comment} for r in rows]
    finally:
        session.close()


def delete_comment(db_path, athlete_id, metric_key, comment_date):
    """Удаляет комментарий для (атлет, метрика, дата). Возвращает True/False."""
    session = get_session(db_path)
    try:
        row = (session.query(MetricComment)
               .filter_by(athlete_id=athlete_id, metric_key=metric_key,
                          comment_date=comment_date)
               .first())
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()