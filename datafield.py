import pandas as pd
from logger import logger
import yaml
from auth import refresh_session
import time  # 新增导入time模块

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
datafield_config = config["datafield"]  # 多组数据字段配置
auth_config = config["auth"]

def clean_string(s):
    if not isinstance(s, str):
        return s
    return s.strip().replace("\n", "").replace("\t", "").replace("\r", "").replace("\\", "\\\\").replace('"', '\\"')

def get_datafield_group(sess, group_name):
    """获取单组数据字段（如datafield1/datafield2/datafield3）"""
    group_config = datafield_config.get(group_name)
    if not group_config:
        logger.error(f"数据字段组 {group_name} 配置不存在")
        return pd.DataFrame()

    search_scope = group_config["search_scope"]
    dataset_id = clean_string(group_config["dataset_id"].strip())
    search = clean_string(group_config["search"].strip())
    limit = group_config["limit"]
    
    # 新增：检查search是否为空，如果为空则跳过该组
    if not search:
        logger.info(f"组 {group_name} 的search字段为空，跳过该组数据字段获取")
        return pd.DataFrame()
    
    url = auth_config["datafield_url"]
    
    base_params = {
        "dataset.id": dataset_id,
        "delay": str(search_scope["delay"]),
        "instrumentType": clean_string(search_scope["instrumentType"]),
        "limit": limit,
        "region": clean_string(search_scope["region"]),
        "universe": clean_string(search_scope["universe"]),
        "search": search,  # 新增搜索关键词
        "offset": 50
    }
    
    all_fields = []
    offset = 0
    logger.info(f"开始获取数据集'{dataset_id}'（组：{group_name}）的字段，搜索关键词：{search}，每页{limit}条...")
    
    while True:
        try:
            sess = refresh_session(sess)
            current_params = base_params.copy()
            current_params["offset"] = offset
            logger.debug(f"数据字段请求参数: {current_params}")
            
            # 新增：API调用前添加1秒延迟
            time.sleep(1)
            
            resp = sess.get(url, params=current_params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            current_fields = data.get("results", [])
            if not current_fields:
                logger.info(f"组 {group_name} 已获取全部数据（当前页无内容）")
                break
            
            cleaned_fields = []
            for field in current_fields:
                cleaned_field = {}
                for k, v in field.items():
                    cleaned_field[k] = clean_string(v) if isinstance(v, str) else v
                cleaned_fields.append(cleaned_field)
            
            all_fields.extend(cleaned_fields)
            logger.info(f"组 {group_name} 已获取偏移量{offset}的数据，累计{len(all_fields)}条")
            
            total_count = data.get("count", 0)
            if total_count > 0 and len(all_fields) >= total_count:
                logger.info(f"组 {group_name} 已获取全部数据（总条数{total_count}）")
                break
            if len(current_fields) < limit:
                logger.info(f"组 {group_name} 已到达最后一页（当前页数据不足一页）")
                break
            
            offset += limit
        
        except Exception as e:
            logger.error(f"组 {group_name} 获取偏移量{offset}的数据失败: {str(e)}")
            if offset == 0:
                raise  # 首页失败则终止
            continue
    
    if not all_fields:
        logger.warning(f"组 {group_name} 未获取到任何数据字段")
        return pd.DataFrame()
    
    df = pd.DataFrame(all_fields).drop_duplicates(subset=["id"])
    df = df[df["type"] == "MATRIX"]
    logger.info(f"组 {group_name} 最终有效数据字段数: {len(df)}（已过滤非MATRIX类型）")
    return df

def get_datafields(sess):
    """获取所有组数据字段，返回字典 {group_name: [ids...]}"""
    datafield_groups = {}
    # 遍历配置中的所有datafield组（如datafield1/datafield2/datafield3）
    for group_name in datafield_config:
        # 新增：在调用前检查search是否为空
        group_config = datafield_config.get(group_name)
        if group_config:
            search = clean_string(group_config.get("search", "").strip())
            if not search:
                logger.info(f"组 {group_name} 的search字段为空，跳过该组")
                continue
                
        df = get_datafield_group(sess, group_name)
        if not df.empty:
            datafield_groups[group_name] = df["id"].tolist()
        else:
            logger.warning(f"组 {group_name} 无有效数据字段，将跳过该组")
    return datafield_groups

if __name__ == "__main__":
    from auth import create_auth_session
    sess = create_auth_session()
    groups = get_datafields(sess)
    print(f"所有组数据字段ID: {groups}")