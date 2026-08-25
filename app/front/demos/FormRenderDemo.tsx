"use client";

import { useMemo, useState } from "react";
import { Button, Form, Space } from "antd";
import { FormRender } from "heitu";
import type { IConfigItem } from "heitu";

/**
 * FormRender demo：配置即表单。
 *
 * 三节内容由 /front 侧栏切换（基础用法 / 联动演示 / 校验与提交），
 * 每节都把驱动它的 config 原样打出来——这个组件的卖点就是「配置长什么样，表单就长什么样」。
 */

type Section = "basic" | "linkage" | "validate";

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

const BASIC: (IConfigItem | IConfigItem[])[] = [
  // titlePlacement 自 1.1.1 起按 antd 大版本自动适配（v5 转 orientation），可以放心用
  { divider: true, label: "基本信息", titlePlacement: "left" },
  [
    {
      type: "Input",
      name: "name",
      label: "项目名称",
      nodeProps: { placeholder: "例如 rag-coder" },
      span: 12,
    },
    {
      type: "Select",
      name: "kind",
      label: "类型",
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
  { divider: true, label: "一行三项" },
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

const LINKAGE: (IConfigItem | IConfigItem[])[] = [
  { divider: true, label: "省份 → 城市" },
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
      // watch 到省份变化就重新拉城市，watchClean 顺手清掉旧选择
      type: "Select",
      name: "city",
      label: "城市",
      watch: ["province"],
      watchClean: true,
      nodeProps: { placeholder: "选完省份自动加载", service: fetchCities },
      span: 12,
    },
  ],
];

const VALIDATE: (IConfigItem | IConfigItem[])[] = [
  { divider: true, label: "带校验的字段" },
  [
    {
      type: "Input",
      name: "repo",
      label: "仓库名",
      rules: [
        { required: true, message: "仓库名必填" },
        { pattern: /^[a-z0-9-]+$/, message: "只能用小写字母、数字与连字符" },
      ],
      nodeProps: { placeholder: "peco-platform" },
      span: 12,
    },
    {
      type: "InputNumber",
      name: "port",
      label: "端口",
      rules: [
        { required: true, message: "端口必填" },
        { type: "number", min: 1024, max: 65535, message: "取值 1024–65535" },
      ],
      nodeProps: { style: { width: "100%" }, placeholder: "3000" },
      span: 12,
    },
  ],
  {
    type: "Select",
    name: "env",
    label: "部署环境",
    rules: [{ required: true, message: "必选" }],
    nodeProps: {
      placeholder: "请选择",
      options: [
        { label: "开发", value: "dev" },
        { label: "生产", value: "prod" },
      ],
    },
  },
];

const CONFIGS: Record<Section, (IConfigItem | IConfigItem[])[]> = {
  basic: BASIC,
  linkage: LINKAGE,
  validate: VALIDATE,
};

const NOTES: Record<Section, string> = {
  basic:
    "config 是一维数组时每行一项，写成二维数组就是一行多项（span 控制栅格）；divider 用来分组。",
  linkage:
    "watch 声明依赖字段，值一变就重新执行 nodeProps.service 拉选项；watchClean 顺带清掉过期的旧值。",
  validate:
    "rules 直接透传给 antd Form.Item，提交时用 form.validateFields() 取值，校验不过会抛异常。",
};

/** config 里有函数（service / 动态 rules），JSON 序列化时标注出来而不是丢掉。 */
function stringifyConfig(config: unknown): string {
  return JSON.stringify(
    config,
    (_k, v) => {
      if (typeof v === "function") return `ƒ ${v.name || "anonymous"}()`;
      if (v instanceof RegExp) return v.toString();
      return v;
    },
    2
  );
}

export default function FormRenderDemo({ section }: { section: string }) {
  const key = (["basic", "linkage", "validate"].includes(section) ? section : "basic") as Section;
  const [form] = Form.useForm();
  const [submitted, setSubmitted] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const config = CONFIGS[key];
  const json = useMemo(() => stringifyConfig(config), [config]);

  const submit = async () => {
    try {
      setError("");
      setSubmitted(await form.validateFields());
    } catch {
      setSubmitted(null);
      setError("校验没通过，看看标红的字段");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[11px] leading-relaxed text-muted">{NOTES[key]}</p>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,380px)]">
        {/* 表单本体：换 section 时用 key 重建，避免上一节的值残留 */}
        <div className="flex flex-col gap-4 border border-line bg-shade/40 p-4">
          <FormRender
            key={key}
            form={form}
            config={config}
            layout="vertical"
            gutter={[16, 0]}
            initialValues={key === "basic" ? { opensource: true } : undefined}
          />
          <Space>
            <Button type="primary" onClick={submit}>
              {key === "validate" ? "校验并提交" : "取值"}
            </Button>
            <Button
              onClick={() => {
                form.resetFields();
                setSubmitted(null);
                setError("");
              }}
            >
              重置
            </Button>
          </Space>

          {error && (
            <div className="border-l-2 border-danger bg-danger/[.06] px-3 py-2 text-[11px] text-danger">
              {error}
            </div>
          )}
          {submitted && (
            <pre className="overflow-x-auto border border-line bg-panel p-3 text-[11px] leading-relaxed text-ink2">
              {JSON.stringify(submitted, null, 2)}
            </pre>
          )}
        </div>

        {/* 驱动上面这张表单的配置 */}
        <div className="flex min-w-0 flex-col border border-line">
          <div className="flex items-center gap-2 border-b border-line bg-shade px-3 py-2">
            <span className="text-[10px] tracking-label text-dim">CONFIG</span>
            <span className="ml-auto text-[10px] text-faint">驱动左侧表单</span>
          </div>
          <pre className="max-h-[520px] overflow-auto bg-panel p-3 text-[10.5px] leading-relaxed text-ink2">
            {json}
          </pre>
        </div>
      </div>
    </div>
  );
}
