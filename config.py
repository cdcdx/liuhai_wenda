import os
import sys
from cryptography.fernet import Fernet
from fastapi.templating import Jinja2Templates
from dotenv import find_dotenv, load_dotenv, get_key, set_key

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_envsion(key, format=True):
    if format:
        value = []
        value_str = get_key(find_dotenv('.env'), key_to_get=key)
        if value_str:
            value = value_str.split(',')
    else:
        value = get_key(find_dotenv('.env'), key_to_get=key)
    return value


def set_envsion(key, value, format=True):
    if format:
        value_str = ','.join(value)
    else:
        value_str = value
    return set_key(find_dotenv('.env'), key_to_set=key, value_to_set=value_str)


# .env
if not os.path.exists('.env'):
    print("ERROR: '.env' file does not exist")
    sys.exit()
else:
    load_dotenv(find_dotenv('.env'))


## CRYPTO-KEY
KEY = os.getenv("KEY")
KEY = KEY if KEY.endswith("=") else KEY + "="
FNet = Fernet(KEY)


# APP
APP_TITLE = os.getenv('APP_TITLE', default='iTube')
APP_PAGE_LIMIT = int(os.getenv('APP_PAGE_LIMIT', default=12))
APP_ACTION_PASSWD = os.getenv('APP_ACTION_PASSWD', default='123456')
API_BASE_URL = os.getenv("API_BASE_URL", default="https://api.xxx.com/")
API_BASE_URL = (API_BASE_URL[:-1] if API_BASE_URL.endswith("/") else API_BASE_URL)
APP_BASE_URL = os.getenv("APP_BASE_URL", default="https://app.xxx.com/")
APP_BASE_URL = (APP_BASE_URL[:-1] if APP_BASE_URL.endswith("/") else APP_BASE_URL)
APP_LEVEL = os.getenv("APP_LEVEL", default="debug")  # debug模式: 测试数据
APP_STARTUP_MODE = os.getenv("APP_STARTUP_MODE", default="background")  # 启动模式
APP_EMAIL_MODE = os.getenv("APP_EMAIL_MODE", default="email")  # 邮件模式
APP_ADMIN_LIST = get_envsion("APP_ADMIN_LIST")  # 管理员权限
APP_CONFIG = {
    "apibase": API_BASE_URL,
    "appbase": APP_BASE_URL,
    "level": APP_LEVEL,
    "startup": APP_STARTUP_MODE.lower(),
    "admin": APP_ADMIN_LIST,
}


# FastAPI
FASTAPI_API_PATH: str = '/api'
FASTAPI_TITLE: str = APP_TITLE
FASTAPI_VERSION: str = '0.0.1'
FASTAPI_DESCRIPTION: str = f'{APP_TITLE} API Interface'
FASTAPI_DOCS_URL: str | None = f'{FASTAPI_API_PATH}/docs'
FASTAPI_REDOC_URL: str | None = None
FASTAPI_OPENAPI_URL: str | None = f'{FASTAPI_API_PATH}/openapi'
FASTAPI_STATIC_FILES: bool = False


# UVICORN
UVICORN_HOST = os.getenv('UVICORN_HOST', default='127.0.0.1')
UVICORN_PORT = int(os.getenv('UVICORN_PORT', default=8000))
SSL_KEYFILE = os.getenv('SSL_KEYFILE', default='')
SSL_CERTFILE = os.getenv('SSL_CERTFILE', default='')


# BASIC AUTH
BASIC_USERNAME = os.getenv('BASIC_USERNAME', default='admin')
BASIC_PASSWORD = os.getenv('BASIC_PASSWORD', default='admin')

## JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", default="4836c0bf4d6d6ce80922e6c17327bfa5e78d29118f9a350d228fb79cc802ac6c")  # `openssl rand -hex 32`
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", default="HS256")  # 算法
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", default=30))  # 令牌有效期 30天
JWT_CONFIG = {
    "secretkey": JWT_SECRET_KEY,
    "algorithm": JWT_ALGORITHM,
    "expire": JWT_EXPIRE_DAYS * 3600 * 24,
}


## CAPTCHA配置
TURNSTILE_URL=os.getenv("TURNSTILE_URL")
TURNSTILE_SECRET=os.getenv("TURNSTILE_SECRET")
RECAPTCHA_URL=os.getenv("RECAPTCHA_URL")
RECAPTCHA_SECRET=os.getenv("RECAPTCHA_SECRET")
HCAPTCHA_URL=os.getenv("HCAPTCHA_URL")
HCAPTCHA_SECRET=os.getenv("HCAPTCHA_SECRET")
CAPTCHA_CONFIG={
    'turnstile_url':    TURNSTILE_URL,
    'turnstile_secret': TURNSTILE_SECRET,
    'recaptcha_url':    RECAPTCHA_URL,
    'recaptcha_secret': RECAPTCHA_SECRET,
    'hcaptcha_url':     HCAPTCHA_URL,
    'hcaptcha_secret':  HCAPTCHA_SECRET,
}


## EMAIL配置
EMAIL_BLACKLIST = {}
EMAIL_HOST = os.getenv("EMAIL_HOST", default="smtp.qq.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", default=587))
EMAIL_USERNAME = get_envsion("EMAIL_USERNAME")  # 发件人
# EMAIL_USERNAME=os.getenv("EMAIL_USERNAME", default='')
# EMAIL_PASSWORD=os.getenv("EMAIL_PASSWORD", default='')
EMAIL_ENCRYPT = os.getenv("EMAIL_PASSWORD")
EMAIL_PASSWORD = FNet.decrypt(EMAIL_ENCRYPT.encode()).decode()
# print("EMAIL_ENCRYPT:",EMAIL_ENCRYPT,"EMAIL_PASSWORD:",EMAIL_PASSWORD)
SES_SENDER = os.getenv("SES_SENDER", default="service@xxx.com")
SES_REGION = os.getenv("SES_REGION", default="ap-southeast-2")
SES_ACCESS_KEY = os.getenv("SES_ACCESS_KEY", default="")
SES_SECRET_ACCESS_KEY = os.getenv("SES_SECRET_ACCESS_KEY", default="")
MAIL_CONFIG = {
    "mode": APP_EMAIL_MODE,
    "host": EMAIL_HOST,  # email
    "port": EMAIL_PORT,  # email
    "userlist": EMAIL_USERNAME,  # email
    "password": EMAIL_PASSWORD,  # email
    "sender": SES_SENDER,  # ses
    "region": SES_REGION,  # ses
    "accesskey": SES_ACCESS_KEY,  # ses
    "secretkey": SES_SECRET_ACCESS_KEY,  # ses
}

# SQL配置
DB_ENGINE = os.getenv('DB_ENGINE', default='sqlite')
SQLITE_URL = os.getenv('SQLITE_URL', default='wenda_db.sqlite')
MYSQL_URL = os.getenv('MYSQL_URL', default='')
MYSQL_MAXCONNECT = int(os.getenv('MYSQL_MAXCONNECT', default=100))


# REDIS配置
REDIS_MODE = os.getenv('REDIS_MODE', default='standalone')
REDIS_ADDRESS = os.getenv('REDIS_ADDRESS', default='127.0.0.1:6379')
REDIS_USERNAME = os.getenv('REDIS_USERNAME', default=None)
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', default=None)
REDIS_DB = int(os.getenv('REDIS_DB', default=0))
REDIS_TIMEOUT = int(os.getenv('REDIS_TIMEOUT', default=5))
REDIS_CONFIG = {
    'mode': REDIS_MODE,
    'host': REDIS_ADDRESS,
    'username': REDIS_USERNAME,
    'password': REDIS_PASSWORD,
    'db': REDIS_DB,
    'timeout': REDIS_TIMEOUT,
}
