import yaml
import json
import re
import csv
from logger import logger

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
alpha_config = config["alpha"]
storage_config = config["storage"]

def clean_string(s):
    if not isinstance(s, str):
        return str(s) if s is not None else ""
    return s.strip().replace('，', ',').replace('\\', '')

def generate_alpha_list(datafield_groups):
    """
    生成Alpha列表，支持多组占位符（{datafieldX}/{operatorX}/{lookbackX}）
    参数：datafield_groups - 字典 {group_name: [ids...]} 如 {"datafield1": [...], ...}
    """
    alpha_list = []
    expr_template = alpha_config.get("template")
    if not expr_template:
        logger.warning("模板为空，无法生成Alpha")
        return alpha_list

    # 提取配置中的算子和回溯期（多组）
    operators = alpha_config.get("operators", {})  # {"operator1": [...], ...}
    lookbacks = alpha_config.get("lookbacks", {})  # {"lookback1": [...], ...}

    # 解析模板中的所有占位符（如{datafield1}, {lookback2}）
    placeholder_pattern = re.compile(r"\{(\w+)\}")
    placeholders = placeholder_pattern.findall(expr_template)
    if not placeholders:
        logger.warning("模板中未包含任何占位符，无法生成Alpha")
        return alpha_list
    logger.info(f"模板中识别的占位符：{placeholders}")

    # 分类占位符类型
    datafield_placeholders = [p for p in placeholders if p.startswith("datafield")]
    operator_placeholders = [p for p in placeholders if p.startswith("operator")]
    lookback_placeholders = [p for p in placeholders if p.startswith("lookback")]

    # 验证占位符对应的配置是否存在
    valid = True
    for p in datafield_placeholders:
        if p not in datafield_groups:
            logger.error(f"占位符 {p} 无对应数据字段组")
            valid = False
    for p in operator_placeholders:
        if p not in operators:
            logger.error(f"占位符 {p} 无对应算子组")
            valid = False
    for p in lookback_placeholders:
        if p not in lookbacks:
            logger.error(f"占位符 {p} 无对应回溯期组")
            valid = False
    if not valid:
        return alpha_list

    # 准备各组数据（清洗后）
    datafield_values = {p: [clean_string(df) for df in datafield_groups[p] if clean_string(df)] for p in datafield_placeholders}
    operator_values = {p: [clean_string(op) for op in operators[p] if clean_string(op)] for p in operator_placeholders}
    lookback_values = {p: [clean_string(str(lb)) for lb in lookbacks[p]] for p in lookback_placeholders}

    # 构建所有占位符的组合参数
    all_placeholder_values = []
    for p in placeholders:
        if p in datafield_values:
            all_placeholder_values.append((p, datafield_values[p]))
        elif p in operator_values:
            all_placeholder_values.append((p, operator_values[p]))
        elif p in lookback_values:
            all_placeholder_values.append((p, lookback_values[p]))

    # 递归生成所有组合并替换模板
    base_idx = 0
    def generate_combinations(params, current={}, index=0):
        nonlocal base_idx
        if index == len(params):
            try:
                # 替换模板中的占位符
                alpha_expr = expr_template
                for p, val in current.items():
                    alpha_expr = alpha_expr.replace(f"{{{p}}}", val)
                alpha_expr = clean_string(alpha_expr)

                # 生成唯一alpha_id
                id_parts = [f"{p}_{current[p]}" for p in placeholders]
                alpha_id = f"alpha_{base_idx}_{'_'.join(id_parts)}"

                # 构建Alpha项
                alpha_item = {
                    "type": alpha_config.get("type", "REGULAR"),
                    "settings": alpha_config.get("settings", {}),
                    "regular": alpha_expr,
                    "alpha_id": alpha_id,
                    "status": "pending",
                    "error_msg": "",
                    "operator": ", ".join([current[p] for p in operator_placeholders]) if operator_placeholders else "",
                    "config": {
                        "type": alpha_config.get("type"),
                        "settings": alpha_config.get("settings"),
                        "expression": alpha_expr
                    },
                    "idx": base_idx,
                    "expr": alpha_expr
                }

                # 补全存储字段
                for field in storage_config["fieldnames"]:
                    if field not in alpha_item:
                        alpha_item[field] = ""

                alpha_list.append(alpha_item)
                logger.info(f"生成Alpha | ID: {alpha_id} | 表达式: {alpha_expr}")
                base_idx += 1
            except Exception as e:
                logger.error(f"生成失败 | 组合: {current} | 错误: {str(e)}")
            return

        # 递归处理下一个占位符
        p, values = params[index]
        for val in values:
            current[p] = val
            generate_combinations(params, current, index + 1)
        current.pop(p, None)

    # 启动组合生成
    generate_combinations(all_placeholder_values)

    logger.info(f"Alpha生成完成 | 总数量: {len(alpha_list)}")
    return alpha_list

def write_pending_alphas(alpha_list):
    if not alpha_list:
        logger.warning("无Alpha可写入pending表")
        return
    
    pending_file = storage_config["pending_file"]
    fieldnames = storage_config["fieldnames"]
    
    try:
        with open(pending_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for alpha in alpha_list:
                row = {}
                for field in fieldnames:
                    value = alpha.get(field, "")
                    if field == "settings" and isinstance(value, dict):
                        row[field] = json.dumps(value, ensure_ascii=False)
                    else:
                        row[field] = clean_string(str(value))
                writer.writerow(row)
        logger.info(f"成功写入{len(alpha_list)}个Alpha到pending表: {pending_file}")
    except Exception as e:
        logger.error(f"写入pending表失败: {str(e)}", exc_info=True)

if __name__ == "__main__":
    # 模拟多组数据字段
    test_datafield_groups = {
        "datafield1": ["close", "open", "high"],
        "datafield2": ["volume", "amount"],
        "datafield3": ["sentiment_score"]
    }
    alpha_list = generate_alpha_list(test_datafield_groups)
    write_pending_alphas(alpha_list)