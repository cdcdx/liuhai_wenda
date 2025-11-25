import os
import json
import base58
import shutil
import random
from datetime import datetime as dt
from pathlib import Path
from typing import Dict
from pydantic import BaseModel, validator
from fastapi import APIRouter, Depends, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse

# 尝试导入PDF相关库
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib import colors
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("PDF导出功能不可用: 未安装reportlab库")

from utils.db import get_db
from utils.log import log as logger
from utils.local import is_base58_encoded, is_base58_encoded_regex, validate_sfzid, validate_email, generate_register_code
from utils.security import get_current_userid, get_interface_userid
from config import *


router = APIRouter()


## server

# ------------------------------------------- name -------------------------------------------

# names
@router.get("/names") # ?page=1&limit=10
async def get_names(page: int | None = 1, limit: int | None = 10, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """获取姓名列表"""
    logger.info(f"/api/names")

    try:
        # 查询姓名总数
        select_query = "SELECT count(id) as len FROM wenda_names WHERE status = 1"
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query)
        all_info = await cursor.fetchone()
        # 如果是元组，转换为字典
        if isinstance(all_info, tuple):
            all_info = dict(zip([desc[0] for desc in cursor.description], all_info))
        logger.debug(f"all_info: {all_info}")
        if all_info is None:
            people_count = 0
        else:
            people_count = all_info['len']

        if people_count == 0:
            return {
                "code": 200,
                "success": True,
                "msg": "Success",
                "data": [],
                "total": 0,
            }

        if page == 0: page = 1
        # 查询分页姓名
        check_query = "SELECT id,name,sfzid,email,phone,address,status FROM wenda_names WHERE status=1 ORDER BY id ASC LIMIT %s, %s"
        values = (limit * (page - 1), limit,)
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s','?')
        logger.debug(f"check_query: {check_query} values: {values}")
        await cursor.execute(check_query, values)
        people_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(people_list, (list, tuple)) and len(people_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            people_list = [dict(zip(column_names, row)) for row in people_list]
        logger.debug(f"people_list: {people_list}")
        
        return {
            "code": 200,
            "success": True,
            "msg": "Success",
            "data": people_list if people_list else [],
            "total": people_count if people_list else 0,
        }
    except Exception as e:
        logger.error(f"/api/names - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# import name
@router.post("/name/import/csv")
async def import_csv_name(file: UploadFile = File(...), userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """导入csv姓名库 <name,sfzid,email,phone,address,status>"""
    logger.info(f"/api/name/import/csv")
    
    # 检查文件扩展名是否为CSV
    if not file.filename.endswith('.csv'):
        logger.error(f"Invalid filetype: {file.filename}")
        return {"code": 400, "success": False, "msg": "只允许上传CSV格式文件"}
    
    try:
        contents = await file.read()
        try: # 适配多种编码: utf-8 / gb2312 / gbk
            content_str = contents.decode('utf-8')
        except UnicodeDecodeError:
            try:
                content_str = contents.decode('gb2312')
            except UnicodeDecodeError:
                content_str = contents.decode('gbk')
        lines = content_str.splitlines()
        len_lines = len(lines)
        logger.debug(f"lines: {lines} len_lines: {len_lines}")

        # 重复查询语句
        check_duplicate_query = "SELECT COUNT(*) FROM wenda_names WHERE sfzid=%s"
        if DB_ENGINE == "sqlite": check_duplicate_query = check_duplicate_query.replace('%s', '?')
        # 插入语句
        insert_query = "INSERT INTO wenda_names (name,sfzid,email,phone,address,status) VALUES (%s,%s,%s,%s,%s,%s)"
        if DB_ENGINE == "sqlite": insert_query = insert_query.replace('%s','?')
        # 更新语句
        update_query = "UPDATE wenda_names set name=%s,email=%s,phone=%s,address=%s,status=%s where sfzid=%s"
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s','?')

        inserted_count = 0
        updateed_count = 0
        for line in lines:
            parts = line.split(',')
            logger.debug(f"parts: {parts}")
            if len(parts) < 6:
                logger.warning(f"Skipping invalid line: {line}")
                continue
            if parts[len(parts)-1].strip() == 'status': # 跳过标题
                logger.warning(f"Skipping invalid line: {line}")
                len_lines-=1
                continue
            name = parts[0]
            sfzid = parts[1]
            email = parts[2]
            phone = parts[3]
            address = parts[4]
            # status = int(parts[5])
            try:
                status = int(parts[5])
            except ValueError:
                logger.error(f"Invalid status: {parts[5]} line: {line}")
                return {"code": 400, "success": False, "msg": f"Invalid status: {parts[5]} line: {line}"}

            # 检查是否已存在相同sfzid的记录
            check_values = (sfzid,)
            logger.debug(f"check_duplicate_query: {check_duplicate_query}, values: {check_values}")
            await cursor.execute(check_duplicate_query, check_values)
            result = await cursor.fetchone()
            logger.debug(f"result: {result}")
            # 如果已存在相同问题，跳过插入
            if result[0] > 0:
                # 插入新记录
                values = (name,email,phone,address,status,sfzid)
                logger.debug(f"update_query: {update_query}, values: {values}")
                await cursor.execute(update_query, values)
                updateed_count += 1
                
                logger.warning(f"Skipping duplicate in {sfzid}: {name}")
                continue
            
            # 插入新记录
            values = (name,sfzid,email,phone,address,status)
            logger.debug(f"insert_query: {insert_query}, values: {values}")
            await cursor.execute(insert_query, values)
            inserted_count += 1
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()

        logger.success(f"Name import successful!  insert: {inserted_count}/{len_lines} update: {updateed_count}/{len_lines}")
        return {
            "code": 200,
            "success": True,
            "msg": f"Name import successful!  insert: {inserted_count}/{len_lines} update: {updateed_count}/{len_lines}"
        }
    except Exception as e:
        logger.error(f"/api/name/import/csv - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# add name
class NameRequest(BaseModel):
    name: str
    sfzid: str
    email: str
    phone: str
    address: str
    status: int
    
    # @validator('sfzid')
    # def validate_sfzid_format(cls, v):
    #     if not validate_sfzid(v):
    #         raise ValueError('身份证号格式不正确')
    #     return v
    
    @validator('email')
    def validate_email_format(cls, v):
        if not validate_email(v):
            raise ValueError('邮箱格式不正确')
        return v
@router.post("/name/add")
async def add_name(post_request: NameRequest, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """增加姓名"""
    logger.info(f"/api/name/add")
    
    try:
        # 获取请求参数
        name = post_request.name
        sfzid = post_request.sfzid
        email = post_request.email
        phone = post_request.phone
        address = post_request.address
        status = post_request.status
        
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_names WHERE sfzid=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (sfzid,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        logger.debug(f"result: {result}")
        if result[0] != 0:
            logger.error(f"add_name - ERROR: Name found - sfzid: {sfzid}, name: {name}")
            return {"code": 400, "success": False, "msg": "Name found"}
        
        # 插入记录
        insert_query = "INSERT INTO wenda_names (name,sfzid,email,phone,address,status) VALUES (%s,%s,%s,%s,%s,%s)"
        values = (name,sfzid,email,phone,address,status)
        if DB_ENGINE == "sqlite": insert_query = insert_query.replace('%s', '?')
        logger.debug(f"insert_query: {insert_query}, values: {values}")
        await cursor.execute(insert_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Name add successfully! sfzid: {sfzid}, name: {name}")
        return {
            "code": 200,
            "success": True,
            "msg": "Name add successful!"
        }
    except Exception as e:
        logger.error(f"/api/name/add - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# modify name
@router.post("/name/modify/{id}")
async def modify_name(post_request: NameRequest, id: int|None=0, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """修改姓名库"""
    logger.info(f"/api/name/modify/{id}")
    
    try:
        # 获取请求参数
        name = post_request.name
        sfzid = post_request.sfzid
        email = post_request.email
        phone = post_request.phone
        address = post_request.address
        status = post_request.status
        
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_names WHERE id=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (id,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] == 0:
            logger.error(f"modify_name - ERROR: Name not found - sfzid: {sfzid}, name: {name}")
            return {"code": 400, "success": False, "msg": "Name not found"}
        
        # 更新记录
        update_query = "UPDATE wenda_names SET name=%s,sfzid=%s,email=%s,phone=%s,address=%s,status=%s WHERE id=%s"
        values = (name, sfzid, email, phone, address, status, id)
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s', '?')
        logger.debug(f"update_query: {update_query}, values: {values}")
        await cursor.execute(update_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Name modified successfully! Name ID: {id}")
        return {
            "code": 200,
            "success": True,
            "msg": "Name modify successful!"
        }
    except Exception as e:
        logger.error(f"/api/name/modify/{id} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# delete name
@router.get("/name/delete/{id}")
async def delete_name(id: int|None=0, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """删除姓名"""
    logger.info(f"/api/name/delete/{id}")
    
    try:
        # 是否存在记录
        check_query = "SELECT COUNT(*) FROM wenda_survey_records WHERE nameid=%s and status=1"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (id,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] != 0:
            logger.error(f"delete_topic - ERROR: Records not deleted - nameid: {id}")
            return {"code": 400, "success": False, "msg": "Records not deleted"}
        
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_names WHERE id=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (id,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] == 0:
            logger.error(f"delete_name - ERROR: Name not found - nameid: {id}")
            return {"code": 400, "success": False, "msg": "Name not found"}
        
        # 更新记录
        status=-1
        update_query = "UPDATE wenda_names SET status=%s WHERE id=%s"
        values = (status, id)
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s', '?')
        logger.debug(f"update_query: {update_query}, values: {values}")
        await cursor.execute(update_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Name delete successfully! nameid: {id}")
        return {
            "code": 200,
            "success": True,
            "msg": "Name delete successful!"
        }
    except Exception as e:
        logger.error(f"/api/name/delete/{id} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}

# ------------------------------------------- topic -------------------------------------------

# topics
@router.get("/topics")
async def get_topics(userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """获取主题列表"""
    logger.info(f"/api/topics")

    try:
        # 查询所有主题
        select_query = "SELECT DISTINCT topicid,topic FROM wenda_questions WHERE status = 1 GROUP BY topic"
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query)
        topic_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(topic_list, (list, tuple)) and len(topic_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            topic_list = [dict(zip(column_names, row)) for row in topic_list]
        logger.debug(f"topic_list: {topic_list}")
        return {
            "code": 200,
            "success": True,
            "msg": "Success",
            "data": topic_list
        }
    except Exception as e:
        logger.error(f"/api/topics - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# questions
@router.get("/topic/{topicid}")
async def get_topic_questions(topicid: int|None =1, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """获取指定主题题库"""
    logger.info(f"/api/topic/{topicid}")
    try: 
        # 查询主题题库
        select_query = "SELECT questionid as id,questiontype as type,question,options,rates FROM wenda_questions WHERE topicid=%s AND status=1 ORDER BY id ASC"
        values=(topicid,)
        if DB_ENGINE == "sqlite": select_query = select_query.replace('%s','?')
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query, values)
        question_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(question_list, (list, tuple)) and len(question_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            question_list = [dict(zip(column_names, row)) for row in question_list]
        logger.debug(f"question_list: {question_list}")
        
        for question in question_list:
            question['options'] = json.loads(question['options'])
            # del question['rates']
        
        return {
            "code": 200,
            "success": True,
            "msg": "Success",
            "data": question_list
        }
    except Exception as e:
        logger.error(f"/api/topic/{topicid} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# import topic
@router.post("/topic/import/csv")
async def import_csv_topic(file: UploadFile = File(...), userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """导入csv题库 <topicid,topic,questionid,questiontype,question,options,rates,status>"""
    logger.info(f"/api/topic/import/csv")
    
    # 检查文件扩展名是否为CSV
    if not file.filename.endswith('.csv'):
        logger.error(f"Invalid filetype: {file.filename}")
        return {"code": 400, "success": False, "msg": "只允许上传CSV格式文件"}
    
    try:
        contents = await file.read()
        try: # 适配多种编码: utf-8 / gb2312 / gbk
            content_str = contents.decode('utf-8')
        except UnicodeDecodeError:
            try:
                content_str = contents.decode('gb2312')
            except UnicodeDecodeError:
                content_str = contents.decode('gbk')
        lines = content_str.splitlines()
        len_lines = len(lines)
        logger.debug(f"lines: {lines} len_lines: {len_lines}")

        # 重复查询语句
        check_duplicate_query = "SELECT COUNT(*) FROM wenda_questions WHERE topicid=%s AND question=%s AND status=1"
        if DB_ENGINE == "sqlite": check_duplicate_query = check_duplicate_query.replace('%s', '?')
        # 插入语句
        insert_query = "INSERT INTO wenda_questions (topicid,topic,questionid,questiontype,question,options,rates,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        if DB_ENGINE == "sqlite": insert_query = insert_query.replace('%s','?')

        inserted_count = 0
        for line in lines:
            parts = line.split(',')
            if len(parts) < 7:
                logger.warning(f"Skipping invalid line: {line}")
                continue
            if parts[len(parts)-1].strip() == 'status': # 跳过标题
                logger.warning(f"Skipping invalid line: {line}")
                len_lines-=1
                continue
            topicid = int(parts[0])
            topic = parts[1]
            questionid = int(parts[2])
            questiontype = int(parts[3])
            question = parts[4]
            options = json.dumps(parts[5].split('|'))
            rates = json.dumps([float(r) for r in parts[6].split('|')])
            # status = int(parts[7])
            try:
                status = int(parts[7])
            except ValueError:
                logger.error(f"Invalid status: {parts[7]} line: {line}")
                return {"code": 400, "success": False, "msg": f"Invalid status: {parts[7]} line: {line}"}

            if len(parts[5].split('|')) != len(parts[6].split('|')):
                logger.error(f"add_question - ERROR: Options length mismatch - options: {options}, rates: {rates}")
                return {"code": 400, "success": False, "msg": "Options length mismatch"}
            
            # 检查是否已存在相同topicid和question的记录
            check_values = (topicid, question)
            logger.debug(f"check_duplicate_query: {check_duplicate_query}, values: {check_values}")
            await cursor.execute(check_duplicate_query, check_values)
            result = await cursor.fetchone()
            
            # 如果已存在相同问题，跳过插入
            if result[0] > 0:
                logger.warning(f"Skipping duplicate question in topic {topicid}: {question}")
                continue
            
            # 插入新记录
            values = (topicid, topic, questionid, questiontype, question, options, rates, status)
            logger.debug(f"insert_query: {insert_query}, values: {values}")
            await cursor.execute(insert_query, values)
            inserted_count += 1
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()

        logger.success(f"Topic import successful!  insert: {inserted_count}/{len_lines}")
        return {
            "code": 200,
            "success": True,
            "msg": f"Topic import successful!  insert: {inserted_count}/{len_lines}"
        }
    except Exception as e:
        logger.error(f"/api/topic/import/csv - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# add topic
class QuestionRequest(BaseModel):
    questiontype: int|None = 1
    question: str
    options: str
    rates: str
    status: int|None = 1
@router.post("/topic/add/{topicid}")
async def add_topic(post_request: QuestionRequest, userid: Dict = Depends(get_interface_userid), topicid: int|None=1, cursor=Depends(get_db)):
    """增加题库 <questiontype: 0-填空 1-单选 2-多选>"""
    logger.info(f"/api/topic/add/{topicid}")
    
    try:
        # 获取请求参数
        questiontype = post_request.questiontype
        question = post_request.question
        options = json.dumps(post_request.options.split('|'))
        rates = json.dumps([float(r) for r in post_request.rates.split('|')])
        status = post_request.status

        if len(post_request.options.split('|')) != len(post_request.rates.split('|')):
            logger.error(f"add_question - ERROR: Options length mismatch - options: {options}, rates: {rates}")
            return {"code": 400, "success": False, "msg": "Options length mismatch"}
        
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_questions WHERE topicid=%s and question=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (topicid, question,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        logger.debug(f"result: {result}")
        if result[0] != 0:
            logger.error(f"add_question - ERROR: Question found - topicid: {topicid}, question: {question}")
            return {"code": 400, "success": False, "msg": "Question found"}
        
        # 查询语句
        check_query = "SELECT topic, count(id) as questionid FROM wenda_questions WHERE topicid=%s"
        check_values = (topicid,)
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        topic_one = await cursor.fetchone()
        # 如果是元组，转换为字典
        if isinstance(topic_one, tuple):
            topic_one = dict(zip([desc[0] for desc in cursor.description], topic_one))
        logger.debug(f"topic_one: {topic_one}")
        if topic_one is None:
            logger.error(f"add_topic - ERROR: Topic not found - topicid: {topicid}")
            return {"code": 400, "success": False, "msg": "Topic not found"}
        # 获取请求参数
        topic = topic_one['topic']
        questionid = int(topic_one['questionid']) + 1
        
        # 插入记录
        insert_query = "INSERT INTO wenda_questions (topicid,topic,questionid,questiontype,question,options,rates,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        values = (topicid, topic, questionid, questiontype, question, options, rates, status)
        if DB_ENGINE == "sqlite": insert_query = insert_query.replace('%s', '?')
        logger.debug(f"insert_query: {insert_query}, values: {values}")
        await cursor.execute(insert_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Question add successfully! topic: {topicid}, question: {questionid}")
        return {
            "code": 200,
            "success": True,
            "msg": "Question add successful!"
        }
    except Exception as e:
        logger.error(f"/api/topic/add/{topicid} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# modify topic
@router.post("/topic/modify/{topicid}/{id}")
async def modify_topic(post_request: QuestionRequest, topicid: int|None=1, id: int|None=0, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """修改题库 <questiontype: 0-填空 1-单选 2-多选>"""
    logger.info(f"/api/topic/modify/{topicid}/{id}")
    
    try:
        # 获取请求参数
        questiontype = post_request.questiontype
        question = post_request.question
        options = json.dumps(post_request.options.split('|'))
        rates = json.dumps([float(r) for r in post_request.rates.split('|')])
        status = post_request.status
        
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_questions WHERE topicid=%s and questionid=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (topicid, id,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] == 0:
            logger.error(f"modify_question - ERROR: Question not found - topicid: {topicid}, question: {question}")
            return {"code": 400, "success": False, "msg": "Question not found"}
        
        # 更新记录
        update_query = "UPDATE wenda_questions SET questiontype=%s,question=%s,options=%s,rates=%s,status=%s WHERE topicid=%s and questionid=%s"
        values = (questiontype, question, options, rates, status, topicid, id)
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s', '?')
        logger.debug(f"update_query: {update_query}, values: {values}")
        await cursor.execute(update_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Question modified successfully! topic: {topicid}, question: {id}")
        return {
            "code": 200,
            "success": True,
            "msg": "Question modify successful!"
        }
    except Exception as e:
        logger.error(f"/api/topic/modify/{topicid}/{id} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# delete topic
@router.get("/topic/delete/{topicid}/{id}")
async def delete_topic(topicid: int|None=1, id: int|None=0, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """删除题库"""
    logger.info(f"/api/topic/delete/{topicid}/{id}")
    
    try:
        # 是否存在记录
        check_query = "SELECT COUNT(*) FROM wenda_survey_records WHERE topicid=%s and status=1"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (topicid,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] != 0:
            logger.error(f"delete_topic - ERROR: Records not deleted - topicid: {topicid}")
            return {"code": 400, "success": False, "msg": "Records not deleted"}
        
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_questions WHERE topicid=%s and questionid=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (topicid, id,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] == 0:
            logger.error(f"delete_topic - ERROR: Question not found - topicid: {topicid}, questionid: {id}")
            return {"code": 400, "success": False, "msg": "Question not found"}
        
        # 更新记录
        status=-1
        update_query = "UPDATE wenda_questions SET status=%s WHERE topicid=%s and questionid=%s"
        values = (status, topicid, id)
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s', '?')
        logger.debug(f"update_query: {update_query}, values: {values}")
        await cursor.execute(update_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Question delete successfully! topic: {topicid}, questionid: {id}")
        return {
            "code": 200,
            "success": True,
            "msg": "Question delete successful!"
        }
    except Exception as e:
        logger.error(f"/api/topic/delete/{topicid}/{id} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# clear topic
@router.get("/topic/clear/{topicid}") # ?pwd=xxx
async def clear_topic(topicid: int|None=1, pwd: str|None='', userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """清空指定主题题库"""
    logger.info(f"/api/topic/clear/{topicid}")

    try:
        logger.debug(f"pwd: {pwd} ({type(pwd).__name__})")
        
        if pwd != APP_ACTION_PASSWD and is_base58_encoded(pwd):
            # base58 解密 pwd
            # pwd_bytes = base58.b58decode(pwd)
            try:
                pwd_bytes = base58.b58decode(pwd)
            except Exception as e:
                logger.error(f"Failed to decode base58: {e}")
                return {"code": 400, "success": False, "msg": "Invalid base58 encoding"}
            logger.debug(f"pwd_bytes: {pwd_bytes}")
            
            # bytes 转 string
            # actionpwd = bytes.decode(pwd_bytes)
            try:
                actionpwd = pwd_bytes.decode('utf-8')
            except UnicodeDecodeError as e:
                logger.error(f"Failed to decode bytes as UTF-8: {e}")
                return {"code": 400, "success": False, "msg": "Invalid password encoding"}
            logger.debug(f"actionpwd: {actionpwd} ({type(actionpwd).__name__})")
        else:
            actionpwd = pwd

        # 验证密码是否正确
        if actionpwd != APP_ACTION_PASSWD:
            logger.error(f"clear_db - ERROR: Password verification failed")
            return {"code": 400, "success": False, "msg": "Password verification failed"}

        # 是否存在记录
        check_query = "SELECT COUNT(*) FROM wenda_survey_records WHERE topicid=%s and status=1"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (topicid,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] != 0:
            logger.error(f"clear_topic - ERROR: Records not deleted - topicid: {topicid}")
            return {"code": 400, "success": False, "msg": "Records not deleted"}
        
        # 删除指定topicid的题库
        delete_query = "DELETE FROM wenda_questions WHERE topicid=%s"
        values = (topicid,)
        if DB_ENGINE == "sqlite": delete_query = delete_query.replace('%s', '?')
        logger.debug(f"delete_query: {delete_query} values: {values}")
        await cursor.execute(delete_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        # 删除指定topicid的题库对应记录
        delete_query = "DELETE FROM wenda_survey_records WHERE topicid=%s"
        values = (topicid,)
        if DB_ENGINE == "sqlite": delete_query = delete_query.replace('%s', '?')
        logger.debug(f"delete_query: {delete_query} values: {values}")
        await cursor.execute(delete_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Database topic {topicid} successful!")
        return {
            "code": 200,
            "success": True,
            "msg": "Success",
            "data": f"Database topic {topicid} successful!"
        }
    except Exception as e:
        logger.error(f"/api/topic/clear/{topicid} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}

# ------------------------------------------- record -------------------------------------------

# surveys
@router.get("/surveys")
async def get_surveys(cursor=Depends(get_db)):
    """获取调查批次"""
    logger.info(f"/api/surveys")

    try:
        # 查询所有主题
        select_query = "SELECT DISTINCT topicid,topic,survey,count(id) as len FROM wenda_survey_records WHERE status = 1 GROUP BY survey ORDER BY id DESC"
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query)
        survey_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(survey_list, (list, tuple)) and len(survey_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            survey_list = [dict(zip(column_names, row)) for row in survey_list]
        logger.debug(f"survey_list: {survey_list}")
        
        return {
            "code": 200,
            "success": True,
            "msg": "Success",
            "data": survey_list
        }
    except Exception as e:
        logger.error(f"/api/surveys - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# records
@router.get("/records/{survey}") # ?page=1&limit=10
async def get_records_survey(survey: str|None='', page: int | None = 1, limit: int | None = 10, cursor=Depends(get_db)):
    """获取指定批次的调查记录"""
    logger.info(f"/api/records/{survey}")
    try: 
        # 查询调查记录总数
        select_query = "SELECT count(id) as len FROM wenda_survey_records WHERE survey = %s AND status = 1"
        values = (survey,)
        logger.debug(f"select_query: {select_query} values: {values}")
        if DB_ENGINE == "sqlite": select_query = select_query.replace('%s','?')
        await cursor.execute(select_query, values)
        all_info = await cursor.fetchone()
        # 如果是元组，转换为字典
        if isinstance(all_info, tuple):
            all_info = dict(zip([desc[0] for desc in cursor.description], all_info))
        logger.debug(f"all_info: {all_info}")
        if all_info is None:
            record_count = 0
        else:
            record_count = all_info['len']

        if record_count == 0:
            return {
                "code": 200,
                "success": True,
                "msg": "Success",
                "data": [],
                "total": 0,
            }

        if page == 0: page = 1
        # 查询调查记录
        select_query = "SELECT id,topicid,topic,nameid,name,0 as survey_id,survey_data,survey_ip,created_time FROM wenda_survey_records WHERE survey=%s AND status=1 ORDER BY created_time ASC LIMIT %s, %s"
        values=(survey, limit * (page - 1), limit,)
        if DB_ENGINE == "sqlite": select_query = select_query.replace('%s','?')
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query, values)
        record_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(record_list, (list, tuple)) and len(record_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            record_list = [dict(zip(column_names, row)) for row in record_list]
        logger.debug(f"record_list: {record_list}")
        
        topicid = record_list[0]['topicid'] if len(record_list) > 0 else 0
        if topicid == 0:
            logger.error(f"get_records_survey - ERROR: topicid is 0")
            return {
                "code": 200,
                "success": True,
                "msg": "Success",
                "data": [],
                "total": 0,
            }
        
        # 查询主题题库
        select_query = "SELECT questionid as id,questiontype as type,question,options,rates FROM wenda_questions WHERE topicid=%s AND status=1 ORDER BY id ASC"
        values=(topicid,)
        if DB_ENGINE == "sqlite": select_query = select_query.replace('%s','?')
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query, values)
        question_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(question_list, (list, tuple)) and len(question_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            question_list = [dict(zip(column_names, row)) for row in question_list]
        for question in question_list:
            question['options'] = json.loads(question['options'])
            question['rates'] = json.loads(question['rates'])
        len_questions = len(question_list)
        logger.debug(f"question_list: {question_list} len_questions: {len_questions}")
        
        start = limit * (page - 1)
        count = 0
        for record in record_list:
            count += 1
            record['survey_id'] = start+count
            record['survey_data'] = json.loads(record['survey_data'])
            del record['nameid']
        
        return {
            "code": 200,
            "success": True,
            "msg": "Success",
            "data": record_list if record_list else [],
            "total": record_count if record_list else 0,
        }
    except Exception as e:
        logger.error(f"/api/records/{survey} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# delete records survey
@router.get("/records/delete/{survey}")
async def delete_records_survey(survey: str|None='', userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """删除问卷批次"""
    logger.info(f"/api/record/delete/{survey}")
    
    try:
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_survey_records WHERE survey=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (survey,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] == 0:
            logger.error(f"delete_record - ERROR: Records not found - survey: {survey}")
            return {"code": 400, "success": False, "msg": "Records not found"}
        
        # 更新记录
        status=-1
        update_query = "UPDATE wenda_survey_records SET status=%s WHERE survey=%s"
        values = (status, survey)
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s', '?')
        logger.debug(f"update_query: {update_query}, values: {values}")
        await cursor.execute(update_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Records delete successfully! survey: {survey}")
        return {
            "code": 200,
            "success": True,
            "msg": "Records delete successful!"
        }
    except Exception as e:
        logger.error(f"/api/record/delete/{id} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# generate records survey
@router.get("/record/generate") # ?topicid=x&number=x&start=x&end=x
async def generate_records_survey(topicid: int | None = 1, number: int | None = 10, start: int | None = 0, end: int | None = 0, cursor=Depends(get_db)):
    """生成调查记录"""
    logger.info(f"/api/record/generate")
    
    try:
        # 查询主题
        select_query = "SELECT topicid,topic FROM wenda_questions WHERE topicid=%s AND status=1 ORDER BY id ASC"
        values=(topicid,)
        if DB_ENGINE == "sqlite": select_query = select_query.replace('%s','?')
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query, values)
        topic_one = await cursor.fetchone()
        # 如果是元组，转换为字典
        if isinstance(topic_one, tuple):
            topic_one = dict(zip([desc[0] for desc in cursor.description], topic_one))
        logger.debug(f"topic_one: {topic_one}")
        if topic_one is None:
            logger.error(f"generate survey - ERROR: Topic not found - topicid: {topicid}")
            return {"code": 400, "success": False, "msg": "Topic not found"}
        topic = topic_one['topic']
        
        # 查询主题题库
        select_query = "SELECT questionid as id,questiontype as type,question,options,rates FROM wenda_questions WHERE topicid=%s AND status=1 ORDER BY id ASC"
        values=(topicid,)
        if DB_ENGINE == "sqlite": select_query = select_query.replace('%s','?')
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query, values)
        question_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(question_list, (list, tuple)) and len(question_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            question_list = [dict(zip(column_names, row)) for row in question_list]
        for question in question_list:
            question['options'] = json.loads(question['options'])
            question['rates'] = json.loads(question['rates'])
        len_questions = len(question_list)
        logger.debug(f"question_list: {question_list} len_questions: {len_questions}")
        
        
        # 查询姓名总数
        select_query = "SELECT count(id) as len FROM wenda_names WHERE status = 1"
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query)
        all_info = await cursor.fetchone()
        # 如果是元组，转换为字典
        if isinstance(all_info, tuple):
            all_info = dict(zip([desc[0] for desc in cursor.description], all_info))
        logger.debug(f"all_info: {all_info}")
        if all_info is None:
            people_count = 0
        else:
            people_count = all_info['len']
        if people_count == 0:
            logger.error(f"generate survey - ERROR: No people")
            return {"code": 400, "success": False, "msg": "No people"}
        if number > people_count:
            logger.error(f"generate survey - ERROR: The name list is insufficient, containing only {people_count} people.")
            return {"code": 400, "success": False, "msg": f"The name list is insufficient, containing only {people_count} people."}

        # 查询所有姓名
        check_query = "SELECT id,name,sfzid,email,phone,address FROM wenda_names WHERE status = 1 ORDER BY id ASC"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s','?')
        logger.debug(f"check_query: {check_query}")
        await cursor.execute(check_query)
        people_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(people_list, (list, tuple)) and len(people_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            people_list = [dict(zip(column_names, row)) for row in people_list]
        logger.debug(f"people_list: {people_list}")
        # people_list随机乱序
        people_list_pairs = list(enumerate(people_list, start=1))
        random.shuffle(people_list_pairs)
        
        ## survey 批次生成逻辑
        survey = generate_register_code(topicid, 7)
        ## 开始时间结束时间
        if start<1700000000:
            start = int(dt.now().timestamp()) - 86400
        if end<1700000000:
            end = int(dt.now().timestamp())
        
        # 插入语句
        insert_query = "INSERT INTO wenda_survey_records (nameid,name,topicid,topic,survey,survey_data,survey_ip,status,created_time) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        if DB_ENGINE == "sqlite": insert_query = insert_query.replace('%s','?')

        count=0
        for data_id, data in people_list_pairs: # people_list随机乱序
            count+=1
            if count > number:
                break
            
            nameid = data['id']
            name = data['name']
            logger.debug(f"id: {count} nameid: {nameid} | name: {name}")
            
            for question in question_list:
                questionid = question['id']
                questiontype = question['type']
                options = question['options']
                rates = question['rates']
                # 根据rates生成随机答案
                if questiontype == 2:
                    # 多选题：随机确定选择几个选项，然后随机选择这些选项
                    # 使用权重来决定选择多少个选项
                    num_options = len(options)
                    # 创建选项数量的概率分布（可以根据需要调整）
                    # 这里假设至少选1个，最多全选
                    num_choices_weights = rates[:num_options] if len(rates) >= num_options else rates + [1] * (num_options - len(rates))
                    
                    # 确保至少选择1个，不超过所有选项数
                    min_choices = 1
                    max_choices = min(num_options, len(num_choices_weights))
                    
                    # 如果有权重数据且长度足够，使用权重决定选择几个选项
                    if len(num_choices_weights) >= num_options:
                        # 只取前num_options个权重用于决定选择几个选项
                        choice_count_weights = num_choices_weights[:num_options]
                        # 至少要选1个
                        num_selected = max(min_choices, 
                                         min(max_choices, 
                                             random.choices(range(1, max_choices + 1), 
                                                          weights=choice_count_weights[:max_choices], 
                                                          k=1)[0]))
                    else:
                        # 默认随机选择1到所有选项中的若干个
                        num_selected = random.randint(min_choices, max_choices)
                    
                    # 从选项中随机选择指定数量的选项
                    answer = random.sample(options, min(num_selected, len(options)))
                    
                    logger.debug(f"answer: {answer}")
                else:
                    # 单选题：只能选择一个选项
                    answer = random.choices(options, weights=rates, k=1)[0]
                logger.debug(f"questionid: {questionid} questiontype: {questiontype} | options: {options} | rates: {rates} => answer: {answer}")
                
                # 构建调查数据
                if 'survey_json' not in locals():
                    survey_json = {}
                survey_json[str(questionid)] = answer
            survey_array = [v for k, v in survey_json.items()]
            len_survey_array = len(survey_array)
            logger.debug(f"survey_array: {survey_array} len_survey_array: {len(survey_array)}")
            survey_data = json.dumps(survey_array)
            logger.debug(f"survey_data: {survey_data}")
            
            if len_questions != len_survey_array:
                logger.error(f"generate survey - ERROR: Survey data length mismatch - nameid: {nameid} | name: {name} | len_questions: {len_questions} | len_survey_array: {len_survey_array}")
                continue
            
            ## 随机IP生成逻辑
            survey_ip = ".".join(map(str, (random.randint(1, 255) for _ in range(4))))  # 随机IP
            logger.debug(f"survey_ip: {survey_ip}")
            
            ## 随机时间生成逻辑
            created_steam = random.randint(start, end)
            created_date = dt.fromtimestamp(created_steam)
            # 确保是工作日(0=Monday, 6=Sunday)
            while created_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
                created_steam = random.randint(start, end)
                created_date = dt.fromtimestamp(created_steam)
            # 设置工作时间为8点到19点之间
            work_hour = random.randint(8, 18)
            work_minute = random.randint(0, 59)
            work_second = random.randint(0, 59)
            # 更新日期的时间部分为工作时间
            created_date = created_date.replace(hour=work_hour, minute=work_minute, second=work_second, microsecond=0)
            created_time = created_date.strftime('%Y-%m-%d %H:%M:%S')
            logger.debug(f"created_steam: {created_steam} => {created_time}")
            
            # 插入新记录
            values = (nameid, name, topicid, topic, survey, survey_data, survey_ip, 1, created_time)
            logger.debug(f"insert_query: {insert_query}, values: {values}")
            await cursor.execute(insert_query, values)
        
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Record generate successful!  topicid: {topicid} | number: {number} | start: {start} | end: {end} => survey: {survey}")
        return {
            "code": 200,
            "success": True,
            "msg": f"Record generate successful!",
            "data": survey,
        }
    except Exception as e:
        logger.error(f"/api/record/generate - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# modify record
class SurveyRequest(BaseModel):
    survey_data: list
@router.post("/record/modify/{id}")
async def modify_record_id(post_request: SurveyRequest, id: int|None=0, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """修改问卷ID"""
    logger.info(f"/api/record/modify/{id}")
    
    try:
        # 获取请求参数
        survey_data = json.dumps(post_request.survey_data)
        
        # 更新记录
        update_query = "UPDATE wenda_survey_records SET survey_data=%s WHERE id=%s"
        values = (survey_data, id)
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s', '?')
        logger.debug(f"update_query: {update_query}, values: {values}")
        await cursor.execute(update_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Record modified successfully! id: {id}")
        return {
            "code": 200,
            "success": True,
            "msg": "Record modify successful!"
        }
    except Exception as e:
        logger.error(f"/api/record/modify/{id} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}


# delete record id
@router.get("/record/delete/{id}")
async def delete_record_id(id: int|None=0, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """删除问卷ID"""
    logger.info(f"/api/record/delete/{id}")
    
    try:
        # 重复查询语句
        check_query = "SELECT COUNT(*) FROM wenda_survey_records WHERE id=%s"
        if DB_ENGINE == "sqlite": check_query = check_query.replace('%s', '?')
        check_values = (id,)
        logger.debug(f"check_query: {check_query}, values: {check_values}")
        await cursor.execute(check_query, check_values)
        result = await cursor.fetchone()
        if result[0] == 0:
            logger.error(f"delete_record_id - ERROR: Record not found - nameid: {id}")
            return {"code": 400, "success": False, "msg": "Record not found"}
        
        # 更新记录
        status=-1
        update_query = "UPDATE wenda_survey_records SET status=%s WHERE id=%s"
        values = (status, id)
        if DB_ENGINE == "sqlite": update_query = update_query.replace('%s', '?')
        logger.debug(f"update_query: {update_query}, values: {values}")
        await cursor.execute(update_query, values)
        if DB_ENGINE == "sqlite": cursor.connection.commit()
        else: await cursor.connection.commit()
        
        logger.success(f"Record delete successfully! recordid: {id}")
        return {
            "code": 200,
            "success": True,
            "msg": "Record delete successful!"
        }
    except Exception as e:
        logger.error(f"/api/record/delete/{id} - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}

# ------------------------------------------- export -------------------------------------------

@router.get("/export/{survey}/pdf")
async def export_survey_to_pdf(survey: str, cursor=Depends(get_db)):
    """将指定批次的调查记录导出为PDF文件"""
    logger.info(f"/api/export/survey/{survey}/pdf")
    
    if not PDF_AVAILABLE:
        return {"code": 500, "success": False, "msg": "PDF导出功能不可用，请安装reportlab库"}
    
    try:
        # 查询调查记录
        select_query = "SELECT topicid,topic,name,survey_data,created_time FROM wenda_survey_records WHERE survey=%s AND status=1 ORDER BY created_time ASC"
        values = (survey,)
        if DB_ENGINE == "sqlite": 
            select_query = select_query.replace('%s','?')
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query, values)
        record_list = await cursor.fetchall()
        if not record_list:
            return {"code": 404, "success": False, "msg": "未找到指定的调查记录"}
        # 如果是列表或元组，转换为字典列表
        if isinstance(record_list, (list, tuple)) and len(record_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            record_list = [dict(zip(column_names, row)) for row in record_list]
        # for record in record_list:
        for index, record in enumerate(record_list, 1):
            record['survey_id'] = index
            record['survey_data'] = json.loads(record['survey_data'])
        logger.debug(f"record_list: {record_list}")
        
        # 查询主题题库以获取问题列表
        topicid = record_list[0]['topicid']
        topic = record_list[0]['topic']
        select_query = "SELECT questionid as id,questiontype as type,question,options FROM wenda_questions WHERE topicid=%s AND status=1 ORDER BY id ASC"
        values = (topicid,)
        if DB_ENGINE == "sqlite": 
            select_query = select_query.replace('%s','?')
        logger.debug(f"select_query: {select_query}")
        await cursor.execute(select_query, values)
        question_list = await cursor.fetchall()
        # 如果是列表或元组，转换为字典列表
        if isinstance(question_list, (list, tuple)) and len(question_list) > 0:
            column_names = [desc[0] for desc in cursor.description]
            question_list = [dict(zip(column_names, row)) for row in question_list]
        for question in question_list:
            question['options'] = json.loads(question['options'])
        logger.debug(f"question_list: {question_list}")
        
        # 为每个记录生成单独的PDF页面
        pdf_filename = f"{topic}_survey_{survey}_{int(dt.now().timestamp())}.pdf"
        pdf_path = os.path.join(BASE_DIR, "temp", pdf_filename)
        
        # 确保临时目录存在
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        # 创建字体目录（如果不存在）
        font_dir = os.path.join(BASE_DIR, "assets", "fonts")
        os.makedirs(font_dir, exist_ok=True)
        
        # 尝试使用系统已有的中文字体
        system_chinese_fonts = [
            (f"{font_dir}/msyh.ttc", "MicrosoftYaHei"),
            (f"{font_dir}/wqy-zenhei.ttc", "WenQuanYiZenHei"),
            # ("C:/Windows/Fonts/msyh.ttf", "MicrosoftYaHei"),
            # ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
        ]
        # 注册中文字体
        chinese_font_registered = False
        chinese_font_name = "Helvetica"  # 默认英文字体
        for font_path, font_short_name in system_chinese_fonts:
            try:
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont(font_short_name, font_path))
                    chinese_font_name = font_short_name
                    chinese_font_registered = True
                    logger.info(f"成功注册中文字体: {font_path} as {font_short_name}")
                    break
            except Exception as e:
                logger.warning(f"注册中文字体失败 {font_path}: {str(e)}")
                continue
        
        # 如果系统字体都不可用，则使用备用方案
        if not chinese_font_registered:
            # 检查是否存在预定义的中文字体文件
            potential_font_files = [
                (os.path.join(font_dir, "MicrosoftYaHei.ttf"), "MicrosoftYaHei"),
                (os.path.join(font_dir, "msyh.ttf"), "MicrosoftYaHei"),
                (os.path.join(font_dir, "微软雅黑.ttf"), "MicrosoftYaHei"),
                (os.path.join(font_dir, "SimSun.ttf"), "SimSun"),
                (os.path.join(font_dir, "simsun.ttc"), "SimSun"),
            ]
            
            for font_file, font_short_name in potential_font_files:
                if os.path.exists(font_file):
                    try:
                        pdfmetrics.registerFont(TTFont(font_short_name, font_file))
                        chinese_font_name = font_short_name
                        chinese_font_registered = True
                        logger.info(f"成功注册自定义中文字体: {font_file} as {font_short_name}")
                        break
                    except Exception as e:
                        logger.warning(f"注册自定义中文字体失败 {font_file}: {str(e)}")
                        continue
        
        # 设置基础字体样式，使用支持Unicode的字体族
        font_name = chinese_font_name if chinese_font_registered else 'Helvetica'
        
        # 创建PDF文档
        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        elements = []
        
        # 确保所有样式都使用相同的字体
        styles = getSampleStyleSheet()
        styles['Normal'].fontName = font_name
        styles['Heading1'].fontName = font_name
        styles['Heading2'].fontName = font_name
        styles['Heading3'].fontName = font_name
        styles['Bullet'].fontName = font_name
        styles['Definition'].fontName = font_name
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            alignment=TA_CENTER,
            fontSize=18,
            spaceAfter=20,
        )
        title_style.fontName = font_name
        
        normal_style = styles['Normal']
        normal_style.fontSize = 12
        normal_style.leading = 14
        normal_style.fontName = font_name
        
        name_style = ParagraphStyle(
            'Name',
            parent=normal_style,
            alignment=TA_CENTER,
            fontSize=14,
            spaceAfter=16,
        )
        question_style = ParagraphStyle(
            'Question',
            parent=normal_style,
            spaceAfter=8,
        )
        
        # 为每个调查记录生成一页
        for record in record_list:
            # 添加标题
            title = Paragraph(f"《{topic}》问卷调查表", title_style)
            elements.append(title)
            
            # 添加姓名
            name_text = f"调查人: {record['name']}"
            name_para = Paragraph(name_text, name_style)
            elements.append(name_para)
            
            # 添加问题和答案
            for i, (question, answer) in enumerate(zip(question_list, record['survey_data']), 1):
                # 格式化选项
                options_text = ""
                if 'options' in question and question['options']:
                    option_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
                    options = question['options']
                    for j, option in enumerate(options):
                        if j < len(option_letters):
                            if option == answer:
                                options_text += f"<font color='#4682B4'>{option_letters[j]}、{option}</font>&nbsp;&nbsp;"
                            else:
                                options_text += f"{option_letters[j]}、{option}&nbsp;&nbsp;"
                
                # 构造文本
                question_text = f"<b>{i}. {question['question']}</b><br/>{options_text}<br/>"
                question_para = Paragraph(question_text, question_style)
                elements.append(question_para)
                elements.append(Spacer(1, 12))
            
            # 添加分页符（除了最后一页）
            if record != record_list[-1]:
                elements.append(PageBreak())
        
        # 构建PDF
        doc.build(elements)
        
        # 返回PDF文件
        return FileResponse(
            path=pdf_path,
            media_type='application/pdf',
            filename=pdf_filename
        )
    except Exception as e:
        logger.error(f"/api/export/survey/{survey}/pdf - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": f"导出PDF失败: {str(e)}"}

# ------------------------------------------- clear -------------------------------------------

# clear database
@router.get("/cleardb") # ?pwd=xxx
async def clear_db(pwd: str, userid: Dict = Depends(get_interface_userid), cursor=Depends(get_db)):
    """清空数据库"""
    logger.info(f"/api/cleardb")

    try:
        logger.debug(f"pwd: {pwd} ({type(pwd).__name__})") # logger.debug(f"is_base58: {is_base58_encoded(pwd)}")
        
        if pwd != APP_ACTION_PASSWD and is_base58_encoded(pwd):
            # base58 解密 pwd
            # pwd_bytes = base58.b58decode(pwd)
            try:
                pwd_bytes = base58.b58decode(pwd)
            except Exception as e:
                logger.error(f"Failed to decode base58: {e}")
                return {"code": 400, "success": False, "msg": "Invalid base58 encoding"}
            logger.debug(f"pwd_bytes: {pwd_bytes}")
            
            # bytes 转 string
            # actionpwd = bytes.decode(pwd_bytes)
            try:
                actionpwd = pwd_bytes.decode('utf-8')
            except UnicodeDecodeError as e:
                logger.error(f"Failed to decode bytes as UTF-8: {e}")
                return {"code": 400, "success": False, "msg": "Invalid password encoding"}
            logger.debug(f"actionpwd: {actionpwd} ({type(actionpwd).__name__})")
        else:
            actionpwd = pwd

        # 验证密码是否正确
        if actionpwd != APP_ACTION_PASSWD:
            logger.error(f"clear_db - ERROR: Password verification failed")
            return {"code": 400, "success": False, "msg": "Password verification failed"}

        # 清空数据表
        if DB_ENGINE == "sqlite": # sqlite
            # 清空表,重置自增主键计数器
            # sqlite wenda_questions
            delete_query = "DELETE FROM wenda_questions"
            logger.debug(f"delete_query: {delete_query}")
            await cursor.execute(delete_query)
            update_query = "UPDATE sqlite_sequence SET seq=0 WHERE name='wenda_questions'"
            logger.debug(f"update_query: {update_query}")
            await cursor.execute(update_query)
            
            # sqlite wenda_names
            delete_query = "DELETE FROM wenda_names"
            logger.debug(f"delete_query: {delete_query}")
            await cursor.execute(delete_query)
            update_query = "UPDATE sqlite_sequence SET seq=0 WHERE name='wenda_names'"
            logger.debug(f"update_query: {update_query}")
            await cursor.execute(update_query)
            
            # sqlite wenda_survey_records
            delete_query = "DELETE FROM wenda_survey_records"
            logger.debug(f"delete_query: {delete_query}")
            await cursor.execute(delete_query)
            update_query = "UPDATE sqlite_sequence SET seq=0 WHERE name='wenda_survey_records'"
            logger.debug(f"update_query: {update_query}")
            await cursor.execute(update_query)
            
            cursor.connection.commit()
        else: # mysql
            # mysql wenda_questions
            delete_query = "truncate table wenda_questions"
            logger.debug(f"delete_query: {delete_query}")
            await cursor.execute(delete_query)
            
            # mysql wenda_names
            delete_query = "truncate table wenda_names"
            logger.debug(f"delete_query: {delete_query}")
            await cursor.execute(delete_query)
            
            # mysql wenda_survey_records
            delete_query = "truncate table wenda_survey_records"
            logger.debug(f"delete_query: {delete_query}")
            await cursor.execute(delete_query)
            
            await cursor.connection.commit()

        logger.success(f"Database cleanup successful!")
        return {
            "code": 200,
            "success": True,
            "msg": "Success",
            "data": "Database cleanup successful!"
        }
    except Exception as e:
        logger.error(f"/api/cleardb - except ERROR: {str(e)}")
        return {"code": 500, "success": False, "msg": "Server error"}

# ---------------------------------------------------------------------------------------------
