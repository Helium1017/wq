import requests
import json
from requests.auth import HTTPBasicAuth
from logger import logger
import yaml

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
auth_config = config["auth"]
system_config = config["system"]

def clean_string(s):
    if not isinstance(s, str):
        return s
    return s.strip().replace("\n", "").replace("\t", "").replace("\r", "").replace("\\", "\\\\").replace('"', '\\"')

def get_credentials():
    try:
        with open(auth_config["creds_file"], "r", encoding="utf-8") as f:
            credentials = json.load(f)
            username = clean_string(credentials[0])
            password = clean_string(credentials[1])
            return username, password
    except Exception as e:
        logger.error(f"读取凭证失败: {str(e)}")
        raise

def create_auth_session(retry_times=None):
    retry_times = retry_times or system_config["retry_times"]
    username, password = get_credentials()
    
    for i in range(retry_times):
        try:
            sess = requests.Session()
            sess.auth = HTTPBasicAuth(username, password)
            resp = sess.post(auth_config["auth_url"])
            resp.raise_for_status()
            logger.info(f"认证成功，状态码: {resp.status_code}")
            return sess
        except Exception as e:
            logger.warning(f"认证失败（第{i+1}/{retry_times}次）: {str(e)}")
            if i == retry_times - 1:
                logger.error("认证重试次数耗尽，退出程序")
                raise
            continue

def refresh_session(sess):
    try:
        resp = sess.get(auth_config["datafield_url"], params={"limit": 1}, timeout=10)
        if resp.status_code == 401:
            logger.warning("Session失效，重新认证")
            return create_auth_session()
        return sess
    except Exception as e:
        logger.warning(f"Session检查失败，重新认证: {str(e)}")
        return create_auth_session()

if __name__ == "__main__":
    sess = create_auth_session()
    logger.info("Session创建完成，认证状态正常")