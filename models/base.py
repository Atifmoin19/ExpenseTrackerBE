"""Re-exports the shared declarative Base so `models/*.py` don't need to
import from `core.database` directly (keeps model modules import-light for
Alembic's `env.py`, which only needs `models.base.Base.metadata`)."""
from core.database import Base

__all__ = ["Base"]
