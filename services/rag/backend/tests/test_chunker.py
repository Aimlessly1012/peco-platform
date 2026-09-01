"""AST 分块器单测：四语言 fixture，断言切块边界与元数据（spec: AST 分块）。"""
from pathlib import Path

import pytest

from app.services.ingest.chunker import chunk_file

PY_SAMPLE = '''import os
from pathlib import Path

CONSTANT = 42


def top_level_fn(a, b):
    """docstring"""
    return a + b


class OrderService:
    def create(self, data):
        return data

    def delete(self, oid):
        return oid


@property
def decorated_fn():
    return 1
'''

TS_SAMPLE = '''import { useState } from "react";

export const API_BASE = "/api";

export function fetchOrders(): Promise<Order[]> {
  return fetch(`${API_BASE}/orders`).then(r => r.json());
}

export const OrderList = () => {
  const [orders, setOrders] = useState<Order[]>([]);
  return null;
};

interface Order {
  id: string;
}

class OrderStore {
  orders: Order[] = [];
}
'''

JS_SAMPLE = '''const axios = require("axios");

function getUser(id) {
  return axios.get(`/users/${id}`);
}

class UserCache {
  constructor() { this.map = new Map(); }
}
'''

TSX_SAMPLE = '''import React from "react";

export default function HomePage() {
  return <div>home</div>;
}

export const Card = ({ title }: { title: string }) => <div>{title}</div>;
'''


def _write_and_chunk(tmp_path: Path, name: str, content: str):
    (tmp_path / name).write_text(content, encoding="utf-8")
    return chunk_file(tmp_path, Path(name))


def test_python_chunks(tmp_path):
    chunks = _write_and_chunk(tmp_path, "sample.py", PY_SAMPLE)
    symbols = {c.symbol: c for c in chunks}

    assert "top_level_fn" in symbols
    assert symbols["top_level_fn"].symbol_type == "function"
    assert symbols["top_level_fn"].start_line == 7

    assert "OrderService" in symbols
    assert symbols["OrderService"].symbol_type == "class"

    assert "decorated_fn" in symbols  # decorated_definition 提取内部名

    module = symbols.get("(module)")
    assert module is not None
    assert "import os" in module.code
    assert "CONSTANT = 42" in module.code


def test_typescript_chunks(tmp_path):
    chunks = _write_and_chunk(tmp_path, "orders.ts", TS_SAMPLE)
    symbols = {c.symbol for c in chunks}
    assert {"fetchOrders", "OrderList", "Order", "OrderStore", "API_BASE"} <= symbols


def test_javascript_chunks(tmp_path):
    chunks = _write_and_chunk(tmp_path, "user.js", JS_SAMPLE)
    symbols = {c.symbol for c in chunks}
    assert {"getUser", "UserCache"} <= symbols


def test_tsx_chunks(tmp_path):
    chunks = _write_and_chunk(tmp_path, "page.tsx", TSX_SAMPLE)
    symbols = {c.symbol for c in chunks}
    assert {"HomePage", "Card"} <= symbols


def test_all_chunks_have_metadata(tmp_path):
    chunks = _write_and_chunk(tmp_path, "sample.py", PY_SAMPLE)
    for c in chunks:
        assert c.content_hash and len(c.content_hash) == 16
        assert 1 <= c.start_line <= c.end_line
        assert c.code.strip()
        assert c.language == "python"


def test_syntax_error_file_skipped(tmp_path):
    # tree-sitter 容错解析：完全无法产出 AST 的文件抛 ChunkError；
    # 局部语法错误仍能提取有效定义，两种情况都不应崩溃
    (tmp_path / "broken.py").write_text("def broken(:\n    pass\n\ndef ok():\n    return 1\n")
    chunks = chunk_file(tmp_path, Path("broken.py"))
    assert any(c.symbol == "ok" for c in chunks)
