"""从维护中的模型输出学习表 SQL 草案，不连接或修改任何数据库。

python deploy/xiaoman/study_schema.py > data/study-schema.sql
由 A 审阅，再决定是否应用。独立于底座 RLS 迁移。
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def render():
    import app.study.common.models as models
    import app.study.v2.models as v2_models
    from app.db import Base
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    tables = sorted({value.__table__ for module in (models, v2_models) for value in vars(module).values()
                     if isinstance(value, type) and issubclass(value, Base) and hasattr(value, "__table__")}, key=lambda t:t.name)
    dialect = postgresql.dialect()
    lines = ["-- Generated from app/study/common/models.py and app/study/v2/models.py; review before execution.",
             "-- Requires base RLS roles provisioned separately; runtime roles must not own tables.", "BEGIN;", "SET LOCAL search_path TO public;"]
    for table in tables:
        name = '"public"."' + table.name + '"'
        lines.append(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)) + ";")
        for index in sorted(table.indexes, key=lambda i:i.name):
            lines.append(str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)) + ";")
        lines.extend([
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY;",
            f"REVOKE ALL ON TABLE {name} FROM PUBLIC, anon, authenticated;",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {name} TO personal_agent_app;",
            f"DROP POLICY IF EXISTS xiaoman_owner ON {name};",
            f"CREATE POLICY xiaoman_owner ON {name} TO personal_agent_app USING (user_id = NULLIF(current_setting('app.user_id', true), '')) WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), ''));",
        ])
    lines.append("COMMIT;")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
