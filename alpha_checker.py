# alpha_checker.py
import requests
import yaml
import time
import csv
import os
import json
from auth import create_auth_session, refresh_session
from logger import logger

# 读取配置文件
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

auth_config = config["auth"]
BASE_URL = auth_config['sim_url'].replace('/simulations', '')

def get_alpha_details(sess, alpha_id):
    """获取Alpha的详细信息"""
    url = f"{BASE_URL}/alphas/{alpha_id}"
    
    try:
        logger.info(f"获取Alpha详情: {url}")
        sess = refresh_session(sess)
        response = sess.get(url)
        
        # 处理429限流
        if response.status_code == 429:
            logger.warning(f"获取Alpha详情触发限流，等待后重试")
            time.sleep(15)
            return get_alpha_details(sess, alpha_id)  # 递归重试
            
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"获取Alpha {alpha_id} 详情失败: {str(e)}")
        return None

def get_alpha_check(sess, alpha_id, retry_count=0, max_retries=20):
    """获取Alpha的检查结果 - 使用GET请求并处理空响应"""
    url = f"{BASE_URL}/alphas/{alpha_id}/check"
    
    try:
        logger.info(f"获取Alpha检查结果 (尝试 {retry_count+1}/{max_retries}): {url}")
        sess = refresh_session(sess)
        response = sess.get(url)
        
        # 处理429限流
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 5))
            logger.warning(f"获取检查结果触发限流，等待{retry_after}秒后重试")
            time.sleep(retry_after)
            return get_alpha_check(sess, alpha_id, retry_count, max_retries)
        
        # 处理404 - 检查可能不存在或未开始
        if response.status_code == 404:
            logger.info(f"Alpha {alpha_id} 检查未找到，可能未开始，等待5秒后重试")
            time.sleep(5)
            if retry_count < max_retries - 1:
                return get_alpha_check(sess, alpha_id, retry_count + 1, max_retries)
            return None
            
        response.raise_for_status()
        
        data = response.json()
        
        # 检查返回的数据是否为空
        if not data or data == {}:
            logger.info(f"Alpha {alpha_id} 检查结果为空，等待3秒后重试")
            time.sleep(3)
            if retry_count < max_retries - 1:
                return get_alpha_check(sess, alpha_id, retry_count + 1, max_retries)
            return None
        
        return data
        
    except Exception as e:
        logger.error(f"获取Alpha {alpha_id} 检查结果异常: {str(e)}")
        if retry_count < max_retries - 1:
            time.sleep(3)
            return get_alpha_check(sess, alpha_id, retry_count + 1, max_retries)
        return None

def set_alpha_color(sess, alpha_id, color):
    """设置Alpha的颜色"""
    url = f"{BASE_URL}/alphas/{alpha_id}"
    
    try:
        logger.info(f"设置Alpha颜色: {url} -> {color}")
        
        sess = refresh_session(sess)
        payload = {"color": color}
        response = sess.patch(url, json=payload)
        
        # 处理429限流
        if response.status_code == 429:
            logger.warning(f"设置Alpha颜色触发限流，等待后重试")
            time.sleep(5)
            return set_alpha_color(sess, alpha_id, color)  # 递归重试
            
        response.raise_for_status()
        logger.info(f"Alpha {alpha_id} 颜色已设置为 {color}")
        return True
    except Exception as e:
        logger.error(f"设置Alpha {alpha_id} 颜色失败: {str(e)}")
        return False

def evaluate_check_result(check_result):
    """评估检查结果，确定是否通过"""
    if not check_result:
        return False, "无检查结果"
    
    # 从您提供的示例来看，检查结果包含在 'is.checks' 路径下
    checks = check_result.get('is', {}).get('checks', [])
    if not checks:
        logger.warning(f"检查结果中没有找到checks字段")
        return True, "无检查项，默认通过"  # 如果没有检查项，认为通过
    
    # 先检查除了SELF_CORRELATION之外的所有检查项
    non_self_checks = [check for check in checks if check.get('name') != 'SELF_CORRELATION']
    self_correlation_check = [check for check in checks if check.get('name') == 'SELF_CORRELATION']
    
    # 检查非自相关检查项
    failed_non_self_checks = []
    pending_non_self_checks = []
    
    for check in non_self_checks:
        name = check.get('name', '未知')
        result = check.get('result', '未知')
        
        if result.upper() == 'FAIL':
            failed_non_self_checks.append(name)
            logger.warning(f"非自相关检查失败: {name}")
        elif result.upper() == 'PENDING':
            pending_non_self_checks.append(name)
            logger.info(f"非自相关检查未完成: {name} 状态为PENDING")
        elif result.upper() == 'PASS':
            logger.info(f"非自相关检查通过: {name}")
    
    # 如果有任何非自相关检查失败，立即返回失败
    if failed_non_self_checks:
        return False, f"非自相关检查失败: {', '.join(failed_non_self_checks)}"
    
    # 如果有非自相关检查项还在PENDING状态，需要等待
    if pending_non_self_checks:
        return None, f"等待非自相关检查完成: {', '.join(pending_non_self_checks)}"
    
    # 所有非自相关检查都通过，现在检查自相关
    if self_correlation_check:
        self_check = self_correlation_check[0]
        self_result = self_check.get('result', '未知')
        
        if self_result.upper() == 'FAIL':
            return False, f"自相关检查失败: {self_check.get('name')}"
        elif self_result.upper() == 'PENDING':
            return None, f"等待自相关检查完成: {self_check.get('name')}"
        elif self_result.upper() == 'PASS':
            logger.info(f"自相关检查通过: {self_check.get('name')}")
    
    # 所有检查都通过
    return True, "所有检查通过"

def determine_color_from_grade(grade):
    """根据等级确定颜色"""
    if not grade:
        return "PURPLE"
        
    grade = grade.upper()
    if grade == "EXCELLENT":
        return "GREEN"
    elif grade == "GOOD":
        return "BLUE"
    elif grade == "AVERAGE":
        return "YELLOW"
    elif grade == "POOR":
        return "RED"
    else:
        return "PURPLE"

def process_single_alpha(sess, alpha_id, index, total):
    """处理单个Alpha"""
    logger.info(f"处理Alpha {index}/{total}: {alpha_id}")
    
    # 步骤1: 先获取当前Alpha的详情，查看是否已经有等级
    logger.info(f"步骤1: 获取Alpha {alpha_id} 当前详情...")
    alpha_details = get_alpha_details(sess, alpha_id)
    
    if not alpha_details:
        logger.error(f"无法获取Alpha {alpha_id} 的详情")
        return False, "获取详情失败"
    
    # 检查是否已经有等级
    current_grade = alpha_details.get('grade')
    if current_grade:
        logger.info(f"Alpha {alpha_id} 已有等级: {current_grade}")
    
    # 步骤2: 获取检查结果并进行评估
    max_check_attempts = 30  # 最大检查尝试次数
    attempt = 0
    
    while attempt < max_check_attempts:
        logger.info(f"步骤2: 获取Alpha {alpha_id} 的检查结果 (尝试 {attempt+1}/{max_check_attempts})...")
        check_result = get_alpha_check(sess, alpha_id, max_retries=3)
        
        if not check_result:
            logger.error(f"无法获取Alpha {alpha_id} 的检查结果")
            return False, "获取检查结果失败"
        
        # 步骤3: 评估检查结果
        logger.info(f"步骤3: 评估Alpha {alpha_id} 的检查结果...")
        passed, message = evaluate_check_result(check_result)
        
        # 如果评估结果为None，表示需要等待检查完成
        if passed is None:
            logger.info(f"Alpha {alpha_id} 检查未完成: {message}，等待10秒后重试...")
            time.sleep(10)
            attempt += 1
            continue
        
        # 如果检查失败
        if not passed:
            logger.warning(f"Alpha {alpha_id} 检查未通过: {message}")
            return False, message
        
        # 检查通过
        logger.info(f"Alpha {alpha_id} 检查通过: {message}")
        break
    
    # 如果超过最大尝试次数仍未完成检查
    if attempt >= max_check_attempts:
        logger.error(f"Alpha {alpha_id} 检查超时")
        return False, "检查超时"
    
    # 步骤4: 检查通过后，重新获取Alpha详情以获取最新的等级
    logger.info(f"步骤4: 重新获取Alpha {alpha_id} 详情以获取最新等级...")
    time.sleep(5)  # 等待检查结果更新
    alpha_details = get_alpha_details(sess, alpha_id)
    
    if not alpha_details:
        logger.error(f"无法重新获取Alpha {alpha_id} 的详情")
        return False, "重新获取详情失败"
    
    grade = alpha_details.get('grade')
    if not grade:
        logger.warning(f"Alpha {alpha_id} 没有等级信息")
        grade = "UNKNOWN"
    
    # 步骤5: 根据等级设置颜色
    color = determine_color_from_grade(grade)
    logger.info(f"步骤5: 设置Alpha {alpha_id} 颜色为 {color} (等级: {grade})...")
    
    if set_alpha_color(sess, alpha_id, color):
        return True, f"成功设置颜色为 {color} (等级: {grade})"
    else:
        return False, "颜色设置失败"

def process_completed_alphas(sess, process_all=False):
    """处理已完成的Alpha列表"""
    completed_file = config["storage"]["completed_file"]
    
    if not os.path.exists(completed_file):
        logger.error(f"完成文件 {completed_file} 不存在")
        return 0, 0
    
    # 记录已处理的Alpha ID，避免重复处理
    processed_file = "processed_alpha_checks.txt"
    processed_alphas = set()
    
    if os.path.exists(processed_file) and not process_all:
        with open(processed_file, 'r', encoding='utf-8') as f:
            processed_alphas = set(line.strip() for line in f if line.strip())
        logger.info(f"已加载 {len(processed_alphas)} 个已处理的Alpha")
    
    # 读取已完成Alpha列表
    with open(completed_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        alphas = list(reader)
    
    logger.info(f"从 {completed_file} 读取到 {len(alphas)} 个Alpha记录")
    
    # 统计有效Alpha ID数量
    valid_alphas = [alpha for alpha in alphas if alpha.get('alpha', '').strip()]
    logger.info(f"其中 {len(valid_alphas)} 个有有效的alpha ID")
    
    # 过滤掉已处理的Alpha
    if not process_all:
        new_alphas = [alpha for alpha in valid_alphas if alpha.get('alpha', '').strip() not in processed_alphas]
        logger.info(f"有 {len(new_alphas)} 个新的Alpha需要处理")
    else:
        new_alphas = valid_alphas
        logger.info(f"处理所有 {len(new_alphas)} 个Alpha")
    
    if not new_alphas:
        logger.info("没有新的Alpha需要处理")
        return 0, 0
    
    processed_count = 0
    failed_count = 0
    
    for i, alpha in enumerate(new_alphas):
        alpha_id = alpha.get('alpha', '').strip()
        if not alpha_id:
            logger.warning(f"跳过第{i+1}个记录，无有效alpha ID")
            continue
        
        success, message = process_single_alpha(sess, alpha_id, i+1, len(new_alphas))
        
        if success:
            # 记录已处理的Alpha
            with open(processed_file, 'a', encoding='utf-8') as f:
                f.write(f"{alpha_id}\n")
            processed_count += 1
            logger.info(f"Alpha {alpha_id} 处理完成: {message}")
        else:
            failed_count += 1
            logger.error(f"Alpha {alpha_id} 处理失败: {message}")
        
        # 添加延迟避免限流
        if i < len(new_alphas) - 1:  # 如果不是最后一个
            logger.info("等待10秒后处理下一个Alpha...")
            time.sleep(10)
    
    logger.info(f"处理完成: 成功 {processed_count} 个, 失败 {failed_count} 个")
    return processed_count, failed_count

def main(process_all=False):
    """主函数"""
    logger.info("=== Alpha检查与颜色标记工具启动 ===")
    logger.info(f"模式: {'处理所有Alpha' if process_all else '仅处理新Alpha'}")
    
    # 创建认证会话
    sess = create_auth_session()
    
    # 测试认证是否有效
    test_alpha = "A16rg6bd"  # 使用您提供的测试Alpha ID
    logger.info(f"测试认证有效性，获取Alpha {test_alpha} 详情...")
    details = get_alpha_details(sess, test_alpha)
    
    if details:
        logger.info(f"认证成功！获取到Alpha详情: {details.get('id')}")
        logger.info(f"当前等级: {details.get('grade')}")
        logger.info(f"当前颜色: {details.get('color')}")
        
        # 测试检查API
        logger.info(f"测试检查API...")
        check_result = get_alpha_check(sess, test_alpha, max_retries=3)
        if check_result:
            logger.info(f"检查API测试成功")
            checks = check_result.get('is', {}).get('checks', [])
            logger.info(f"检查项数量: {len(checks)}")
            for check in checks:
                logger.info(f"  - {check.get('name')}: {check.get('result')}")
        else:
            logger.warning("检查API返回空结果，可能需要多次尝试")
        
        try:
            processed, failed = process_completed_alphas(sess, process_all)
            logger.info(f"=== Alpha处理完成: 成功 {processed} 个, 失败 {failed} 个 ===")
        except Exception as e:
            logger.error(f"处理过程中发生错误: {str(e)}")
    else:
        logger.error("认证测试失败，请检查认证配置")
    
    logger.info("=== 工具运行结束 ===")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Alpha检查与颜色标记工具")
    parser.add_argument("--all", action="store_true", help="处理所有Alpha，包括已处理过的")
    parser.add_argument("--test", type=str, help="测试单个Alpha ID")
    args = parser.parse_args()
    
    if args.test:
        # 测试单个Alpha
        logger.info(f"=== 测试单个Alpha: {args.test} ===")
        sess = create_auth_session()
        details = get_alpha_details(sess, args.test)
        if details:
            logger.info(f"Alpha详情: {json.dumps(details, indent=2, ensure_ascii=False)}")
            
            check_result = get_alpha_check(sess, args.test, max_retries=5)
            if check_result:
                logger.info(f"检查结果: {json.dumps(check_result, indent=2, ensure_ascii=False)}")
                
                # 评估检查结果
                passed, message = evaluate_check_result(check_result)
                logger.info(f"评估结果: 通过={passed}, 消息={message}")
            else:
                logger.error("无法获取检查结果")
    else:
        main(process_all=args.all)