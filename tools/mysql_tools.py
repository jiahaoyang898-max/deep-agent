
# 1. list_sql_tables: 列出数据库中所有可用的表，这是了解数据库结构的第一步。
# 2. get_table_data: 读取指定表的前100行数据，用于快速预览数据内容。
# 3. execute_sql_query: 执行自定义SQL查询。当需要复杂的筛选、联接或聚合时使用此工具。

import os
import re
from dotenv import load_dotenv
from api.monitor import monitor
from mysql.connector import connect, Error
from typing import Annotated, List
from langchain_core.tools import tool
from utils.logger_utils import logger

load_dotenv()

# 加载配置文件方便后续使用
def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
        "collation": os.getenv("MYSQL_COLLATION", "utf8mb4_unicode_ci"),
        # 三个工具都只做查询，autocommit 必须关闭，配合只读事务兜底
        "autocommit": False,
        "sql_mode": os.getenv("MYSQL_SQL_MODE", "TRADITIONAL")
    }
    # 移除 None 值（核心必要操作）
    config = {k: v for k, v in config.items() if v is not None}

    # 补充：校验核心配置是否存在（可选但推荐）
    required_keys = ["user", "password", "database"]
    missing_keys = [k for k in required_keys if k not in config]
    if missing_keys:
        raise ValueError(f"缺失数据库核心配置：{', '.join(missing_keys)}")
    return config


# ====================== 只读守卫 ======================
# 智能体只要查询能力；放开写语句等于把删库权限交给一句 prompt 注入。
_WRITE_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "replace", "rename", "set", "call", "execute",
    "load", "handler", "lock", "unlock", "flush", "kill", "shutdown",
    "commit", "rollback", "savepoint", "prepare", "deallocate",
}
_READ_KEYWORDS = {"select", "with", "show", "describe", "desc", "explain"}
_COMMENT_PATTERNS = (
    re.compile(r"/\*.*?\*/", re.S),
    re.compile(r"--[^\n]*"),
    re.compile(r"#[^\n]*"),
)


class SqlPolicyError(ValueError):
    """语句未通过只读守卫。"""


def _strip_comments(sql: str) -> str:
    for pattern in _COMMENT_PATTERNS:
        sql = pattern.sub(" ", sql)
    return sql


def ensure_read_only_sql(sql: str) -> str:
    """前置校验：单条语句 + 只读动词 + 不含任何写动词，挡住注释/多语句/大小写绕过。"""
    cleaned = _strip_comments(str(sql or "")).strip().rstrip(";").strip()
    if not cleaned:
        raise SqlPolicyError("空语句")
    if ";" in cleaned:
        raise SqlPolicyError("只允许执行一条查询语句")

    statement = cleaned
    tokens = [t for t in re.split(r"[^a-zA-Z_]+", statement.lower()) if t]
    if not tokens:
        raise SqlPolicyError("语句无法识别")
    if tokens[0] not in _READ_KEYWORDS:
        raise SqlPolicyError(f"只允许查询语句（{sorted(_READ_KEYWORDS)}），当前以 {tokens[0]} 开头")

    forbidden = sorted(_WRITE_KEYWORDS & set(tokens))
    if forbidden:
        raise SqlPolicyError(f"检测到写操作关键字：{', '.join(forbidden)}")

    if re.search(r"\binto\s+(outfile|dumpfile)\b", statement, re.I) or re.search(r"\bload_file\s*\(", statement, re.I):
        raise SqlPolicyError("禁止读写服务器文件")

    return statement


def _open_read_only_connection():
    """建连并强制会话只读：即使前置校验被绕过，MySQL 也会拒绝写操作。"""
    conn = connect(**get_db_config())
    with conn.cursor() as cursor:
        cursor.execute("set session transaction read only")
        cursor.execute("start transaction read only")
    return conn


def _fetch_table_names() -> List[str]:
    conn = _open_read_only_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("show tables")
            return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

# 定义查看数据库表的工具
"""
【mysql.connector 核心 API 说明（针对 connect/cursor）】
1. connect 函数：
   - 作用：建立与 MySQL 数据库的连接，返回一个 Connection 对象；
   - 使用方式：connect(**config)，config 为包含 host/user/password 等的字典；
   - 上下文管理器：注意 `with connect(...) as conn` 只做 commit/rollback，**不会关闭连接**，
     所以三个工具函数都在 finally 里显式 conn.close()，否则每次调用泄漏一个连接；
   - 核心属性/方法：
     - conn.cursor(): 创建游标对象（执行 SQL 的核心）；
     - conn.commit(): 提交事务（本模块只读，不需要）；
     - conn.close(): 关闭连接（必须显式调用）。
2. cursor 游标对象：
   - 作用：执行 SQL 语句、获取查询结果的核心对象；
   - 创建方式：conn.cursor()；
   - 上下文管理器：with conn.cursor() as cursor，自动关闭游标；
   - 核心方法：
     - cursor.execute(sql): 执行单条 SQL 语句（如 SHOW TABLES/SELECT/INSERT）；
     - cursor.executemany(sql, params): 批量执行 SQL 语句（如批量插入）；
     - cursor.close(): 关闭游标（with 语句自动执行）。
3. 【重点】cursor 执行 DQL/DML 后的结果解析：
   ▶ DQL（数据查询语言，如 SELECT/SHOW）：查询类操作，返回「数据结果集」
     - 核心方法：
       1. cursor.fetchall(): 获取所有结果（返回列表，每个元素是元组，如 [(1, '张三'), (2, '李四')]）；
       2. cursor.fetchone(): 获取一条结果（返回元组，如 (1, '张三')，多次调用可遍历所有结果）；
       3. cursor.fetchmany(n): 获取前 n 条结果（返回列表）；
       4. cursor.column_names: 获取查询结果的列名（列表，如 ['id', 'name']）；
     - 解析技巧：将「列名 + 元组结果」转为字典（更易读），如 {'id': 1, 'name': '张三'}。
   ▶ DML（数据操作语言，如 INSERT/UPDATE/DELETE）：修改类操作，无「数据结果集」
     - 核心属性：
       1. cursor.rowcount: 返回受影响的行数（整数，如 INSERT 1 条返回 1，UPDATE 3 条返回 3）；
       2. cursor.lastrowid: INSERT 操作后，返回新增记录的自增 ID（仅对有自增主键的表有效）；
     - 解析技巧：通过 rowcount 判断操作是否生效，lastrowid 获取新增数据的主键。
4. 异常处理：
   - Error: mysql.connector 专属异常类，捕获所有数据库操作异常（如连接失败、SQL 语法错误）；
   - 推荐方式：try-except Error as e 捕获异常，返回友好提示。
"""

# 1. list_sql_tables: 列出数据库中所有可用的表，这是了解数据库结构的第一步。

@tool
def list_sql_tables() -> str:
    """
    查询当前库中有哪些可用表!
        对应的sql: show tables;
    :return: 可用表:1,2,3   /  没有可用
    """
    monitor.report_tool(tool_name="搜索表名工具")
    conn = None
    try:
        # 创建只读连接（with connect(...) 不会关连接，见文件头 API 说明）
        conn = _open_read_only_connection()
        with conn.cursor() as cursor:
            # [(1,),(2,),(3,)]
            cursor.execute("show tables;")
            select_result = cursor.fetchall()
            if not select_result or len(select_result) == 0:
                return "没有可用表"
            table_name_list = [item[0] for item in select_result]
            return f"可用表:{",".join(table_name_list)}"
    except Error as e:
        return "数据库连接失败: " + str(e)
    finally:
        if conn is not None:
            conn.close()


# 2. get_table_data: 读取指定表的前100行数据，用于快速预览数据内容。
# 参数 table_name:表名
# 返回
"""
   表格形式
   id   name    age 
    1  二狗子    18
    2  驴蛋蛋    19
"""
@tool
def get_table_data(table_name: str) -> str:
    """
    查询指定表名的数据,参数就是表名! 为了让助手理解表的结构!
    我们返回的格式参照表格格式 如下:
            id   name    age
            1  二狗子    18
            2  驴蛋蛋    19
    """
    monitor.report_tool(tool_name="搜索指定表名的数据工具", args={"table_name": table_name})

    # 表名不能进 SQL 字符串，先拿 show tables 的结果做白名单
    try:
        allowed_tables = _fetch_table_names()
    except Error as e:
        return "数据库连接失败: " + str(e)
    if table_name not in allowed_tables:
        return f"表 {table_name} 不在本库白名单中，可用表：{',' .join(allowed_tables)}"

    conn = None
    try:
        conn = _open_read_only_connection()
        with conn.cursor() as cursor:
            # 表名已校验且无反引号冲突字符，标识符只能参数化到白名单层面，故用反引号包裹
            cursor.execute(f"select * from `{table_name}` limit 100;")
            # 获取结果 [1.判断有没有数据 2. 获取表头  3. 获取表数据]
            # description获取表的元数据 (表头)  1. 判断是不是有效表或者有数据  2. 获取表头信息
            # [
            #   (id , 第一列的描述 , ....) ,
            #   (name , 第一列的描述 , ....)
            # ]
            description = cursor.description
            if  not description:
                return f"当前表{table_name}没有数据"
            table_header = [column_tuple[0] for column_tuple in description]
            # [(1,name,18),(),()]
            result = cursor.fetchall()
            # (1,name,18) -> "1,name,18"
            # [(1,name,18),(),()] -> ["1,name,18","2,hehe,20"]
            data_list = [ ",".join(map(str ,row_tuple)) for row_tuple in result]
            # id,name,age
            table_header_str = ",".join(table_header)
            # "1,name,18"\n"2,hehe,20\n
            data_list_str = "\n".join(data_list)
            return table_header_str + "\n" + data_list_str
    except Error as e:
        return "数据库查询失败: " + str(e)
    finally:
        if conn is not None:
            conn.close()


# 3. execute_sql_query: 执行自定义SQL查询。当需要复杂的筛选、联接或聚合时使用此工具。
# 参数: sql
# 响应: 查询数据 表格形式
@tool
def execute_sql_query(sql: str) -> str:

    """
    执行自定义SQL查询
    :param sql: 自定义SQL查询语句
    :return: 查询数据 表格形式
    """
    monitor.report_tool(tool_name="执行自定义SQL查询工具", args={"sql": sql})

    # 前置只读校验：智能体只需要查询，写语句/多语句/注释绕过一律拒绝
    try:
        statement = ensure_read_only_sql(sql)
    except SqlPolicyError as e:
        logger.warning(f"[MySQL] 拒绝非只读语句: {e} | 原文: {str(sql)[:200]}")
        return f"该语句被只读守卫拒绝：{e}。本工具仅支持 select/show/describe/explain 查询。"

    conn = None
    try:
        conn = _open_read_only_connection()
        with conn.cursor() as cursor:
            cursor.execute(statement)
            # 获取结果 [1.判断有没有数据 2. 获取表头  3. 获取表数据]
            # description获取表的元数据 (表头)  1. 判断是不是有效表或者有数据  2. 获取表头信息
            # [
            #   (id , 第一列的描述 , ....) ,
            #   (name , 第一列的描述 , ....)
            # ]
            description = cursor.description
            if  not description:
                return f"当前语句{sql}没有数据"
            table_header = [column_tuple[0] for column_tuple in description]
            # [(1,name,18),(),()]
            result = cursor.fetchall()
            # (1,name,18) -> "1,name,18"
            # [(1,name,18),(),()] -> ["1,name,18","2,hehe,20"]
            data_list = [ ",".join(map(str ,row_tuple)) for row_tuple in result]
            # id,name,age
            table_header_str = ",".join(table_header)
            # "1,name,18"\n"2,hehe,20\n
            data_list_str = "\n".join(data_list)
            return table_header_str + "\n" + data_list_str
    except Error as e:
        # 只读事务兜底：绕过前置校验的写语句会在这里被 MySQL 拒绝
        return "数据库查询失败: " + str(e)
    finally:
        if conn is not None:
            conn.close()

if __name__ == '__main__':
    # print(list_sql_tables.invoke({}))
    # print(get_table_data.invoke({"table_name": "drugs"}))
    print(execute_sql_query.invoke({"sql": "select * from drugs limit 100"}))