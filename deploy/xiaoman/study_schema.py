"""从维护中的模型输出学习表（及身份索引表）的建表 SQL，不连接或修改任何数据库。

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
    # 身份索引（防泄露检查用：只存 HMAC 后的哈希，可由用户档案重建）。它要和 user_profiles 在同一个库里做联表，
    # 所以放在业务库；不按用户隔离（检查时要能比对到别人的标识），只授权给应用 / 系统两个角色。
    from app.agent.harness.identity import IdentityIndex, IdentityIndexed
    for table in (IdentityIndex.__table__, IdentityIndexed.__table__):
        name = '"public"."' + table.name + '"'
        lines.append(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)) + ";")
        for index in sorted(table.indexes, key=lambda i: i.name):
            lines.append(str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)) + ";")
        lines.extend([
            # 和其它表一样开启并强制 RLS（守住“每张表都有 RLS”的底线），用显式策略只放行两个运行时角色。
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY;",
            f"REVOKE ALL ON TABLE {name} FROM PUBLIC, anon, authenticated;",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {name} TO personal_agent_app, personal_agent_system;",
            f"DROP POLICY IF EXISTS xiaoman_identity_index ON {name};",
            f"CREATE POLICY xiaoman_identity_index ON {name} TO personal_agent_app, personal_agent_system USING (true) WITH CHECK (true);",
        ])
    lines.append('GRANT USAGE, SELECT ON SEQUENCE "public"."identity_index_id_seq" TO personal_agent_app, personal_agent_system;')
    lines.append("COMMIT;")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
