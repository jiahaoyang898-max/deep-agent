"""第 7/8/12 条：MySQL 工具只读守卫、表名白名单、连接不泄漏（真实库验证）。

注意：写/删类语句一律只针对本用例自建的 scratch 表，绝不拿 drugs/inventory 当靶子——
守卫缺失时测试必须"失败"而不是真把业务数据删掉。
"""
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import mysql.connector

from tools.mysql_tools import execute_sql_query, get_table_data, list_sql_tables

SCRATCH = "utest_guard_scratch"


def _apply_test_db_target():
    """dotenv 会被别的模块 import 时覆盖回 .env 值，所以每个用例前重新指定目标库。"""
    host, port = os.getenv("DAS_TEST_MYSQL_HOST"), os.getenv("DAS_TEST_MYSQL_PORT")
    if host:
        os.environ["MYSQL_HOST"] = host
        os.environ["MYSQL_PORT"] = port or "3306"


def _admin_conn():
    from tools.mysql_tools import get_db_config

    cfg = dict(get_db_config())
    cfg["autocommit"] = True
    return mysql.connector.connect(**cfg)


def _scalar(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()[0]


def _tables(conn):
    with conn.cursor() as cur:
        cur.execute("show tables")
        return {r[0] for r in cur.fetchall()}


class SqlReadOnlyGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _apply_test_db_target()
        cls.conn = _admin_conn()
        with cls.conn.cursor() as cur:
            cur.execute(f"drop table if exists {SCRATCH}")
            cur.execute(f"create table {SCRATCH} (id int primary key, note varchar(50))")
            cur.execute(f"insert into {SCRATCH} (id, note) values (1,'keep'),(2,'keep')")

    @classmethod
    def tearDownClass(cls):
        with cls.conn.cursor() as cur:
            cur.execute(f"drop table if exists {SCRATCH}")
        cls.conn.close()

    def setUp(self):
        _apply_test_db_target()

    # ---------- 正常查询必须仍然可用 ----------
    def test_normal_select_still_works(self):
        result = execute_sql_query.invoke(
            {"sql": "select d.generic_name, sum(i.quantity_on_hand) as total "
                    "from drugs d join inventory i on i.drug_id = d.drug_id "
                    "group by d.drug_id order by total limit 10"}
        )
        self.assertIn("generic_name", result)
        self.assertGreaterEqual(len(result.splitlines()), 2, f"应返回表格数据，实得：{result[:200]}")

    def test_show_and_list_tables_allowed(self):
        self.assertIn("可用表", list_sql_tables.invoke({}))
        self.assertIn("drugs", execute_sql_query.invoke({"sql": "show tables"}))
        self.assertIn("generic_name", get_table_data.invoke({"table_name": "drugs"}))

    # ---------- 写语句一律拒绝，且数据分毫不动 ----------
    def test_write_statements_rejected(self):
        dangerous = [
            f"delete from {SCRATCH}",
            f"update {SCRATCH} set note = '被篡改'",
            f"insert into {SCRATCH} (id, note) values (99,'攻击')",
            f"drop table {SCRATCH}",
            f"truncate table {SCRATCH}",
            f"alter table {SCRATCH} add column hack int",
            f"rename table {SCRATCH} to hacked",
            "create table utest_hacked (id int)",
            "grant all on pharma_db.* to 'x'@'%'",
            f"DELETE   FROM {SCRATCH}",
            f"  delete   from {SCRATCH}",
        ]
        for sql in dangerous:
            result = str(execute_sql_query.invoke({"sql": sql}))
            self.assertRegex(result, r"(只读|拒绝|禁止|不允许)", f"未拦截写语句：{sql} -> {result[:120]}")
        self.assertIn(SCRATCH, _tables(self.conn), "drop/truncate 竟然生效了")
        self.assertEqual(2, _scalar(self.conn, f"select count(*) from {SCRATCH}"), "scratch 表行数被改动")
        self.assertNotIn("utest_hacked", _tables(self.conn))

    def test_comment_and_multistatement_bypass_blocked(self):
        for sql in [
            f"/*x*/ delete from {SCRATCH}",
            f"# c\n delete from {SCRATCH}",
            f"-- c\ndelete from {SCRATCH}",
            f"select id from {SCRATCH}; drop table {SCRATCH}",
            f"select 1;delete from {SCRATCH};",
            f"select 1 /* */ ; update {SCRATCH} set note='x'",
        ]:
            result = str(execute_sql_query.invoke({"sql": sql}))
            self.assertRegex(result, r"(只读|拒绝|禁止|不允许)", f"绕过手法未被拦截：{sql!r} -> {result[:120]}")
        self.assertEqual(2, _scalar(self.conn, f"select count(*) from {SCRATCH}"))

    def test_table_name_injection_blocked(self):
        for name in [f"{SCRATCH}; drop table {SCRATCH}", "nonexistent_table", "mysql.user", "../etc/passwd",
                     "information_schema.tables"]:
            result = str(get_table_data.invoke({"table_name": name}))
            self.assertRegex(result, r"(白名单|不存在|非法|拒绝|禁止)", f"表名未校验：{name!r} -> {result[:120]}")
        self.assertEqual(2, _scalar(self.conn, f"select count(*) from {SCRATCH}"), "表名注入改动到了数据")

    def test_read_only_transaction_blocks_writes_even_if_guard_bypassed(self):
        # 兜底层：跳过语句校验，直接在只读连接上写，MySQL 必须自己拒绝
        from tools.mysql_tools import _open_read_only_connection

        conn = _open_read_only_connection()
        try:
            with conn.cursor() as cursor:
                with self.assertRaises(mysql.connector.Error):
                    cursor.execute(f"delete from {SCRATCH}")
        finally:
            conn.close()
        self.assertEqual(2, _scalar(self.conn, f"select count(*) from {SCRATCH}"))

    def test_tool_path_disables_autocommit(self):
        from tools.mysql_tools import get_db_config

        self.assertFalse(get_db_config().get("autocommit", False), "工具路径必须关闭 autocommit")

    def test_connections_not_leaked(self):
        baseline = _live_db_conns(self.conn)
        for _ in range(12):
            list_sql_tables.invoke({})
            get_table_data.invoke({"table_name": "drugs"})
            execute_sql_query.invoke({"sql": "select 1"})
        current = _live_db_conns(self.conn)
        self.assertLessEqual(current, baseline + 1, f"12 轮调用后连接数从 {baseline} 涨到 {current}，存在泄漏")


def _live_db_conns(conn):
    return _scalar(conn, "select count(*) from information_schema.processlist where db = %s",
                   (os.getenv("MYSQL_DATABASE"),))


if __name__ == "__main__":
    unittest.main()
