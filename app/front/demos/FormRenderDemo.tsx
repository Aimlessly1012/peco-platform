"use client";

import { useState } from "react";
import { Button, Form, Space } from "antd";
import { FormRender } from "heitu";
import type { IConfigItem } from "heitu";

/**
 * FormRender demo：配置即表单。
 * 演示三件事——二维数组一行多项、watch 字段联动、service 异步选项。
 */

/** 异步选项：真实项目里这里是接口，demo 里造个延迟。 */
const fetchCities = async (form?: unknown, watched?: unknown[]) => {
  const province = (watched?.[0] as string) || "";
  await new Promise((r) => setTimeout(r, 400));
  const MAP: Record<string, string[]> = {
    zhejiang: ["杭州", "宁波", "温州"],
    jiangsu: ["南京", "苏州", "无锡"],
    guangdong: ["广州", "深圳", "珠海"],
  };
  return (MAP[province] ?? []).map((c) => ({ label: c, value: c }));
};

export default function FormRenderDemo() {
  const [form] = Form.useForm();
  const [submitted, setSubmitted] = useState<Record<string, unknown> | null>(null);

  const config: (IConfigItem | IConfigItem[])[] = [
    { divider: true, label: "基本信息" },
    [
      {
        type: "Input",
        name: "name",
        label: "项目名称",
        rules: [{ required: true, message: "必填" }],
        nodeProps: { placeholder: "例如 rag-coder" },
        span: 12,
      },
      {
        type: "Select",
        name: "kind",
        label: "类型",
        rules: [{ required: true, message: "必选" }],
        nodeProps: {
          placeholder: "请选择",
          options: [
            { label: "Web 应用", value: "web" },
            { label: "组件库", value: "lib" },
            { label: "CLI 工具", value: "cli" },
          ],
        },
        span: 12,
      },
    ],
    { divider: true, label: "联动演示" },
    [
      {
        type: "Select",
        name: "province",
        label: "省份",
        nodeProps: {
          placeholder: "先选省份",
          options: [
            { label: "浙江", value: "zhejiang" },
            { label: "江苏", value: "jiangsu" },
            { label: "广东", value: "guangdong" },
          ],
        },
        span: 12,
      },
      {
        // watch 到省份变化就重新拉城市，并清掉旧选择
        type: "Select",
        name: "city",
        label: "城市",
        watch: ["province"],
        watchClean: true,
        nodeProps: { placeholder: "选完省份自动加载", service: fetchCities },
        span: 12,
      },
    ],
    { divider: true, label: "其他" },
    [
      { type: "InputNumber", name: "stars", label: "Star 数", nodeProps: { min: 0 }, span: 8 },
      { type: "Switch", name: "opensource", label: "开源", span: 8 },
      { type: "DatePicker", name: "released", label: "发布日期", span: 8 },
    ],
    {
      type: "TextArea",
      name: "desc",
      label: "一句话描述",
      nodeProps: { rows: 2, placeholder: "这个项目解决什么问题" },
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <FormRender
        form={form}
        config={config}
        layout="vertical"
        gutter={[16, 0]}
        initialValues={{ opensource: true }}
      />
      <Space>
        <Button
          type="primary"
          onClick={async () => {
            const values = await form.validateFields();
            setSubmitted(values);
          }}
        >
          提交
        </Button>
        <Button
          onClick={() => {
            form.resetFields();
            setSubmitted(null);
          }}
        >
          重置
        </Button>
      </Space>

      {submitted && (
        <pre className="overflow-x-auto border border-line bg-shade p-3 text-[11px] leading-relaxed text-ink2">
          {JSON.stringify(submitted, null, 2)}
        </pre>
      )}
    </div>
  );
}
