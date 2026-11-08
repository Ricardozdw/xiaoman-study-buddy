"""一次性准备小满的 PostgreSQL（本地或 Supabase）：底座 RLS 迁移 + 学习表 + 身份索引表 + 两个运行时登录角色。

用法（只用管理员连接执行；运行时绝不能用这个连接）：
    OWNER_DATABASE_URL=postgresql://postgres:...@host:5432/postgres \\
    XM_APP_PASSWORD=... XM_SYSTEM_PASSWORD=... \\
    python deploy/xiaoman/provision_pg.py

- 可以重复执行：表 / 策略 / 授权都是“没有才建”，角色已存在时只重设密码。
- 密码只从环境变量读，不打印、不写文件。
- Supabase 自带 anon / authenticated 角色；本地 PostgreSQL 没有时会先建成 NOLOGIN 占位，方便同一份 SQL 两边都能跑。
- 运行时：DATABASE_URL 用 xm_app，SYSTEM_DATABASE_URL 用 xm_system（见 docs/postgres-rls.md）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

APP_LOGIN, SYSTEM_LOGIN = "xm_app", "xm_system"


def main() -> int:
    owner = os.environ.get("OWNER_DATABASE_URL", "")
    app_pw, sys_pw = os.environ.get("XM_APP_PASSWORD", ""), os.environ.get("XM_SYSTEM_PASSWORD", "")
    if not owner or len(app_pw) < 16 or len(sys_pw) < 16:
        print("需要 OWNER_DATABASE_URL，以及至少 16 位的 XM_APP_PASSWORD / XM_SYSTEM_PASSWORD", file=sys.stderr)
        return 2

    from sqlalchemy import text
    from app.data_access.postgres import database_engine

    engine = database_engine(owner)
    with engine.begin() as conn:
        for role in ("anon", "authenticated"):
            conn.execute(text(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                              f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$;"))

    # 1) 底座：私有表 + RLS + personal_agent_app / personal_agent_system 两个组角色
    env = {**os.environ, "DATABASE_URL": owner}
    subprocess.run([sys.executable, "-m", "app.data_access.rls_migration", "up"], cwd=ROOT, env=env, check=True)

    # 2) 学习表（按用户隔离）+ 身份索引表
    from deploy.xiaoman.study_schema import render
    sql = render()
    with engine.begin() as conn:
        conn.exec_driver_sql(sql.replace("BEGIN;", "").replace("COMMIT;", ""))

    # 3) 运行时登录角色：只继承各自的组角色，不拥有表、不能绕过 RLS
    with engine.begin() as conn:
        for login, group, password in ((APP_LOGIN, "personal_agent_app", app_pw), (SYSTEM_LOGIN, "personal_agent_system", sys_pw)):
            exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": login}).scalar()
            quoted = conn.execute(text("SELECT quote_literal(:p)"), {"p": password}).scalar()
            if exists:
                conn.exec_driver_sql(f"ALTER ROLE {login} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {quoted}")
            else:
                conn.exec_driver_sql(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {quoted}")
            conn.exec_driver_sql(f"GRANT {group} TO {login}")
        tables = conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")).scalar()
    print(f"完成：public 下 {tables} 张表；运行时角色 {APP_LOGIN} / {SYSTEM_LOGIN} 已就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
