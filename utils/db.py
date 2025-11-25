import os
import urllib
import aiosqlite
import aiomysql
from contextlib import asynccontextmanager
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from fastapi import HTTPException

from utils.log import log as logger
from config import DB_ENGINE, SQLITE_URL, MYSQL_URL, MYSQL_MAXCONNECT, BASE_DIR

class Database(ABC):
    def __init__(self, url: str):
        self.url = url
        self.pool = None

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator:
        pass

class SQLiteDatabase(Database):
    def __init__(self, url: str):
        super().__init__(url)
        db_path = url.split("://")[1]
        if db_path.startswith('./'):
            self.url = os.path.join(BASE_DIR, db_path.replace('./', ''))
        else:
            self.url = db_path
        logger.info(f"SQLite URL: {self.url}")

    async def connect(self) -> None:
        # logger.info(f"Connecting to SQLite database: {self.url}")
        
        if not os.path.exists(self.url):
            conn = await aiosqlite.connect(self.url, uri=True)
            # 检查表是否存在 sqlite wenda_users
            # await conn.execute("""DROP TABLE IF EXISTS wenda_users""")
            await conn.execute("""
                    CREATE TABLE IF NOT EXISTS wenda_users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        register_code  TEXT DEFAULT '',
                        email          TEXT DEFAULT '',
                        userid         TEXT DEFAULT '',
                        username       TEXT DEFAULT '',
                        password       TEXT DEFAULT '',
                        state          TEXT DEFAULT '',
                        created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_time DATETIME DEFAULT NULL
                    )
                """)
            await conn.execute("""
                    INSERT INTO wenda_users (`id`, `register_code`, `email`, `userid`, `username`, `password`, `state`, `created_time`) VALUES 
                    (1, 'KOMAC', 'admin@liuhai.com', '1033809395880', 'admin',   '$2b$12$YoWDyiLyzZr/GU9nCT3rQeN7x7e5V7WtSRHkc0KP3.pwGWjxShDyO', 'VERIFIED', '2025-07-11 07:28:39'),
                    (2, 'PMOCR', '370887876@qq.com', '1033963391743', 'pangtou', '$2b$12$sq3jCm0Z6B9W.H5MsLXh7.O.zlMDmLgwUrQM2V3XX144AL0GKqpFS', 'VERIFIED', '2025-07-11 07:28:39'),
                    (3, 'ZD3JU', 'psh001@qq.com', '1040492267738', 'psh001', '$2b$12$hnJh2jqkn2etSAjhq19saORj0z5NiwE4znZTp6c5y/H4cOB1B5Yku', 'VERIFIED', '2025-07-11 07:28:39');
                """)
            # 检查表是否存在 sqlite wenda_names
            # await conn.execute("""DROP TABLE IF EXISTS wenda_names""")
            await conn.execute("""
                    CREATE TABLE IF NOT EXISTS wenda_names (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name           TEXT DEFAULT '',
                        sfzid          TEXT DEFAULT '',
                        email          TEXT DEFAULT '',
                        phone          TEXT DEFAULT '',
                        address        TEXT DEFAULT '',
                        status         INTEGER DEFAULT 0,
                        created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_time DATETIME DEFAULT NULL
                    )
                """)
            # 检查表是否存在 sqlite wenda_questions
            # await conn.execute("""DROP TABLE IF EXISTS wenda_questions""")
            await conn.execute("""
                    CREATE TABLE IF NOT EXISTS wenda_questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        topicid        INTEGER DEFAULT 0,
                        topic          TEXT DEFAULT '',
                        questionid     INTEGER DEFAULT 0,
                        questiontype   INTEGER DEFAULT 1,
                        question       TEXT DEFAULT '',
                        options        TEXT DEFAULT '',
                        rates          TEXT DEFAULT '',
                        status         INTEGER DEFAULT 0,
                        note           TEXT DEFAULT '',
                        created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_time DATETIME DEFAULT NULL
                    )
                """)
            # 检查表是否存在 sqlite wenda_survey_records
            # await conn.execute("""DROP TABLE IF EXISTS wenda_survey_records""")
            await conn.execute("""
                    CREATE TABLE IF NOT EXISTS wenda_survey_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nameid         INTEGER DEFAULT 0,
                        name           TEXT DEFAULT '',
                        topicid        INTEGER DEFAULT 0,
                        topic          TEXT DEFAULT '',
                        survey         TEXT DEFAULT '',
                        survey_data    TEXT DEFAULT '',
                        survey_ip      TEXT DEFAULT '',
                        status         INTEGER DEFAULT 0,
                        note           TEXT DEFAULT '',
                        created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_time DATETIME DEFAULT NULL
                    )
                """)
            await conn.commit()
            await conn.close()
        # 创建连接池
        self.pool = await aiosqlite.connect(self.url, uri=True, check_same_thread=False)

    async def disconnect(self) -> None:
        if self.pool:
            await self.pool.close()

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        if self.pool is None:
            await self.connect()
        if self.pool is None:  # 再次检查连接是否成功建立
            raise RuntimeError("Failed to establish database connection")
        try:
            yield self.pool
        finally:
            pass  # SQLite 不需要显式关闭连接池中的连接

class MySQLDatabase(Database):
    def __init__(self, url: str):
        super().__init__(url)
        parsed_url = urllib.parse.urlparse(url)
        self.host = parsed_url.hostname
        self.port = parsed_url.port or 3306
        self.username = urllib.parse.unquote(parsed_url.username)
        self.password = urllib.parse.unquote(parsed_url.password)
        self.db = parsed_url.path.lstrip('/')
        logger.info(f"MySQL URL: host={self.host}, port={self.port}, user={self.username}, db={self.db}")

    async def connect(self) -> None:
        try:
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.username,
                password=self.password,
                db=self.db,
                maxsize=MYSQL_MAXCONNECT
            )
            # 连接成功后检查并创建表
            await self.create_tables()
        except aiomysql.Error as e:
            logger.error(f"Failed to connect to MySQL database: {e}")
            # 尝试创建数据库
            await self.create_database()
            # 重新尝试创建连接池
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.username,
                password=self.password,
                db=self.db,
                maxsize=MYSQL_MAXCONNECT
            )
            # 连接成功后检查并创建表
            await self.create_tables()

    async def create_database(self) -> None:
        try:
            async with aiomysql.connect(
                host=self.host,
                port=self.port,
                user=self.username,
                password=self.password
            ) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db}")
                    await conn.commit()
        except aiomysql.Error as e:
            logger.error(f"Failed to create MySQL database: {e}")
            raise HTTPException(status_code=500, detail="Failed to create database")

    async def create_tables(self) -> None:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 检查表是否存在 mysql wenda_users
                    await cursor.execute("SHOW TABLES LIKE 'wenda_users'")
                    table_exists = await cursor.fetchone()
                    if not table_exists:
                        # 表不存在，创建表
                        await cursor.execute("""
                            CREATE TABLE `wenda_users`
                            (
                                `id`                   int           NOT NULL AUTO_INCREMENT COMMENT 'id',
                                `register_code`        varchar(16)   NOT NULL    COMMENT '注册码',      -- 一人一码

                                `email`                varchar(128)  DEFAULT ''  COMMENT '邮箱',
                                `userid`               varchar(32)   DEFAULT ''  COMMENT '用户ID',
                                `username`             varchar(64)   DEFAULT ''  COMMENT '用户名',
                                `password`             varchar(255)  DEFAULT ''  COMMENT '密码哈希',
                                `state`                varchar(32)   DEFAULT 'UNVERIFIED' COMMENT '用户状态',    -- UNVERIFIED/VERIFIED/ACTIVE

                                `created_time`         datetime      DEFAULT CURRENT_TIMESTAMP,
                                `updated_time`         datetime      DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
                                PRIMARY KEY (`id`)  USING BTREE,
                                INDEX idx_email (email),
                                INDEX idx_userid (userid),
                                INDEX idx_username (username)
                            ) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Dynamic;
                        """)
                        await cursor.execute("""
                            INSERT INTO wenda_users (`id`, `register_code`, `email`, `userid`, `username`, `password`, `state`, `created_time`) VALUES 
                            (1, 'KOMAC', 'admin@liuhai.com', '1033809395880', 'admin',   '$2b$12$YoWDyiLyzZr/GU9nCT3rQeN7x7e5V7WtSRHkc0KP3.pwGWjxShDyO', 'VERIFIED', '2025-07-11 07:28:39'),
                            (2, 'PMOCR', '370887876@qq.com', '1033963391743', 'pangtou', '$2b$12$sq3jCm0Z6B9W.H5MsLXh7.O.zlMDmLgwUrQM2V3XX144AL0GKqpFS', 'VERIFIED', '2025-07-11 07:28:39'),
                            (3, 'ZD3JU', 'psh001@qq.com', '1040492267738', 'psh001', '$2b$12$hnJh2jqkn2etSAjhq19saORj0z5NiwE4znZTp6c5y/H4cOB1B5Yku', 'VERIFIED', '2025-07-11 07:28:39');
                        """)
                        await conn.commit()
                    # 检查表是否存在 mysql wenda_names 
                    await cursor.execute("SHOW TABLES LIKE 'wenda_names'")
                    table_exists = await cursor.fetchone()
                    if not table_exists:
                        # 表不存在，创建表
                        await cursor.execute("""
                            CREATE TABLE `wenda_names`
                            (
                                `id`                    int           NOT NULL AUTO_INCREMENT COMMENT 'id',

                                `name`                  varchar(64)   DEFAULT ''  COMMENT '姓名',
                                `sfzid`                 varchar(32)   DEFAULT ''  COMMENT '身份证ID',
                                `email`                 varchar(128)  DEFAULT ''  COMMENT '邮箱',
                                `phone`                 varchar(32)   DEFAULT ''  COMMENT '手机',
                                `address`               varchar(512)  DEFAULT ''  COMMENT '家庭地址',
                                `status`                TINYINT       DEFAULT 0   COMMENT '用户状态', -- -1 delete, 0 pending, 1 active

                                `created_time`          datetime      DEFAULT NOW() COMMENT '创建时间',
                                `updated_time`          datetime      DEFAULT NULL  COMMENT '更新时间',
                                PRIMARY KEY (`id`)  USING BTREE
                            ) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Dynamic;
                        """)
                        await conn.commit()
                    # 检查表是否存在 mysql wenda_questions 
                    await cursor.execute("SHOW TABLES LIKE 'wenda_questions'")
                    table_exists = await cursor.fetchone()
                    if not table_exists:
                        # 表不存在，创建表
                        await cursor.execute("""
                            CREATE TABLE `wenda_questions`
                            (
                                `id`                    int           NOT NULL AUTO_INCREMENT COMMENT 'id',

                                `topicid`               int           DEFAULT 0   COMMENT '类型', -- 1-关爱心脏健康 2-关爱呼吸健康
                                `topic`                 varchar(64)   DEFAULT ''  COMMENT '主题', -- 1-关爱心脏健康 2-关爱呼吸健康
                                `questionid`            int           DEFAULT 0   COMMENT '题库ID',
                                `questiontype`          int           DEFAULT 1   COMMENT '选择类型', -- 0-填空 1-单选 2-多选
                                `question`              text          NOT NULL    COMMENT '选择题',

                                `options`               json          NOT NULL    COMMENT '可选项',
                                `rates`                 json          NOT NULL    COMMENT '可选项随机概率',
                                `status`                TINYINT       DEFAULT 0   COMMENT '问题状态', -- -1 delete, 0 pending, 1 active
                                `note`                  varchar(512)  DEFAULT ''  COMMENT '备注',

                                `created_time`          datetime      DEFAULT NOW() COMMENT '创建时间',
                                `updated_time`          datetime      DEFAULT NULL  COMMENT '更新时间',
                                PRIMARY KEY (`id`)  USING BTREE
                            ) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Dynamic;
                        """)
                        await conn.commit()
                    # 检查表是否存在 mysql wenda_survey_records 
                    await cursor.execute("SHOW TABLES LIKE 'wenda_survey_records'")
                    table_exists = await cursor.fetchone()
                    if not table_exists:
                        # 表不存在，创建表
                        await cursor.execute("""
                            CREATE TABLE `wenda_survey_records`
                            (
                                `id`                    int           NOT NULL AUTO_INCREMENT COMMENT 'id',

                                `nameid`               int           DEFAULT 0   COMMENT '姓名ID',
                                `name`                 varchar(64)   DEFAULT ''  COMMENT '姓名',
                                `topicid`              int           DEFAULT 0   COMMENT '类型', -- 1-关爱心脏健康 2-关爱呼吸健康
                                `topic`                varchar(64)   DEFAULT ''  COMMENT '主题', -- 1-关爱心脏健康 2-关爱呼吸健康

                                `survey`               varchar(32)   DEFAULT ''  COMMENT '问卷代码',
                                `survey_data`          json          NOT NULL    COMMENT '问卷数据',
                                `survey_ip`            varchar(64)   DEFAULT ''  COMMENT '问卷提交IP',
                                `status`               TINYINT       DEFAULT 1   COMMENT '记录状态', -- 0 invalid, 1 valid
                                `note`                 varchar(512)  DEFAULT ''  COMMENT '备注',

                                `created_time`          datetime      DEFAULT NOW() COMMENT '创建时间',
                                `updated_time`          datetime      DEFAULT NULL  COMMENT '更新时间',
                                PRIMARY KEY (`id`)  USING BTREE
                            ) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_general_ci ROW_FORMAT = Dynamic;
                        """)
                        await conn.commit()
        except aiomysql.Error as e:
            logger.error(f"Failed to create or check table: {e}")
            raise HTTPException(status_code=500, detail="Failed to create or check table")

    async def disconnect(self) -> None:
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiomysql.Connection, None]:
        if self.pool is None:
            await self.connect()
        if self.pool is None:  # 再次检查连接是否成功建立
            raise RuntimeError("Failed to establish database connection")
        conn = await self.pool.acquire()
        try:
            yield conn
        finally:
            if self.pool:
                self.pool.release(conn)

# print(f"DB_ENGINE: {DB_ENGINE}")
if DB_ENGINE == "mysql":
    database = MySQLDatabase(url=MYSQL_URL)
else:
    database = SQLiteDatabase(url=SQLITE_URL)


async def get_db() -> AsyncGenerator:
    try:
        async with database.get_connection() as conn:
            cursor = await conn.cursor()
            yield cursor
    except Exception as e:
        logger.error(f"Database connection error: {str(e)} | Engine: {DB_ENGINE} | URL: {database.url}")
        raise HTTPException(status_code=500, detail="Database connection error")

@asynccontextmanager
async def get_db_app():
    async with database.get_connection() as conn:
        async with conn.cursor() as cursor:
            yield cursor
