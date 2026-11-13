"""Synthetic fixtures: deliberate regressions, not real model benchmarks."""

PROMPT_V1 = "你是客服与订单信息助手。遵守商店规则，不编造信息。订单提取只返回 JSON。\n用户：{{input}}"
PROMPT_V2 = "你是简洁的客服与订单信息助手。快速解答并提取订单。\n用户：{{input}}"

SUITE = {
    "version": 1, "name": "客服与信息提取 · 示例测试集",
    "cases": [
        {"id": "refund-policy", "input": "收到商品后几天内可以申请退货？", "assertions": [
            {"type": "contains", "value": "7天"}, {"type": "not_contains", "value": "保证退款"}]},
        {"id": "shipping-uncertainty", "input": "我的订单明天一定能到吗？", "assertions": [
            {"type": "contains", "value": "物流"}, {"type": "not_contains", "value": "明天一定送达"}]},
        {"id": "human-handoff", "input": "我想找真人客服处理异常扣款。", "assertions": [
            {"type": "contains", "value": "人工"}, {"type": "max_length", "value": 120}]},
        {"id": "order-extraction", "input": "提取订单：订单号 A1024，购买了 2 件商品。", "assertions": [
            {"type": "json_valid"}, {"type": "json_path_equals", "path": "/order_id", "value": "A1024"},
            {"type": "json_path_equals", "path": "/quantity", "value": 2}]},
        {"id": "missing-order-id", "input": "提取订单：购买了 1 件商品，未提供订单号。", "assertions": [
            {"type": "json_valid"}, {"type": "json_path_equals", "path": "/order_id", "value": None}]},
        {"id": "account-recovery", "input": "账号无法登录，怎样联系客服？", "assertions": [
            {"type": "contains", "value": "客服"}, {"type": "not_contains", "value": "把验证码发给我"}]},
    ],
}

BASELINE = {
    "refund-policy": "符合店铺条件的商品，签收后7天内可以申请退货，具体以售后审核为准。",
    "shipping-uncertainty": "物流显示运输中，明天一定送达，请放心。",
    "human-handoff": "我会帮你转接人工客服，请通过官方入口提交订单号和问题描述。",
    "order-extraction": '{"order_id":"A1024","quantity":2}',
    "missing-order-id": '{"order_id":null,"quantity":1}',
    "account-recovery": "请从应用内的帮助中心联系官方客服，不要向他人提供登录凭证。",
}

CANDIDATE = {
    "refund-policy": "随时退货，保证退款。",
    "shipping-uncertainty": "请以物流更新为准，目前无法保证明天到达。",
    "human-handoff": "请通过帮助中心联系人工客服处理异常扣款。",
    "order-extraction": '{"order_id":"A1024","quantity":"2"}',
    "missing-order-id": '{"order_id":null,"quantity":1}',
    "account-recovery": "请通过帮助中心联系官方客服，勿泄露登录凭证。",
}
