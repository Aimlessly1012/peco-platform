## ADDED Requirements

### Requirement: 字段说明的展示范围由策展清单界定

`/front` 各 tab 展示的字段 MUST 全部来自人写的策展清单，清单未点名的字段 MUST NOT 出现在页面上。
清单的取值边界是「该 tab 的 demo 里实际出现过的字段」——页面演示了什么，就解释什么。

此约束存在的原因：heitu 的 canvas 模块有 274 个成员行，其中大半是 `calcWholeRingD()`、`path2D`
一类内部实现细节。全量提取会把它们倒进橱窗页面。

每个字段 MUST 展示三列：字段名、类型、说明。不设「默认值」列——heitu 的 TSDoc 未使用
`@default` 标签，默认值写在描述文本内，单独开列会有过半为空。

#### Scenario: 清单未点名的成员不出现

- **WHEN** `.d.ts` 中存在 `Circle.path2D`，而策展清单未点名该字段
- **THEN** 生成物不含该字段，页面不展示它

#### Scenario: 展示为三列

- **WHEN** 页面渲染任一 tab 的字段说明
- **THEN** 每行呈现字段名、类型、说明三列，且不存在「默认值」列

### Requirement: 人写的内容优先于机器提取的内容

字段的说明与签名 MUST 按此优先级取值：人写的覆盖层优先；覆盖层未提供时取源 `.d.ts` 的 TSDoc
（说明）或脚本提取的声明文本（签名）；两处皆无说明时生成流程 MUST 失败退出。
页面上 MUST NOT 出现空白说明。

覆盖层的存在本身即代表人已做出判断，故优先。不写覆盖层时自动取源文本，人工负担仍为零——
FormRender 的 TSDoc 覆盖率 97%，那一节几乎无需任何人工条目。

机器提取保证的是「不遗漏、不腐烂」，而非「最适合展示」：`useHtAxios` 的完整提取签名 814 字符、
手写版 78 字符，在三列表格中前者要占七八行。省略何种噪音、返回值缩写到什么程度，属于人的判断。

#### Scenario: 覆盖层与源同时存在

- **WHEN** `useDevicePixelRatio` 在 `.d.ts` 中有 TSDoc，而覆盖层也为其写了说明
- **THEN** 生成物采用覆盖层文本，并输出一条中性提示告知两者并存

#### Scenario: 仅源里有

- **WHEN** `IItem.watchClean` 带有 TSDoc，而覆盖层未点名它
- **THEN** 生成物采用该 TSDoc 文本

#### Scenario: 仅覆盖层有

- **WHEN** `ICircle.border` 在 `.d.ts` 中无 TSDoc，而覆盖层为其提供了中文说明
- **THEN** 生成物采用覆盖层文本

#### Scenario: 两处皆无说明

- **WHEN** 策展清单点名的字段在 `.d.ts` 与覆盖层中均无说明文本
- **THEN** 生成脚本以非零码退出，并指明该字段的接口名与字段名

#### Scenario: 签名的覆盖与兜底

- **WHEN** functions 形态的清单点名 `useHtAxios`，且签名覆盖层为其提供了精简签名
- **THEN** 生成物采用该精简签名；未提供签名覆盖的函数则采用脚本提取的完整签名

### Requirement: 生成脚本在内容漂移时失败

heitu 升级导致清单与实际 `.d.ts` 不一致时，生成脚本 MUST 失败退出而非静默跳过。
这是本方案区别于既有 `hooks-reference.ts` 的关键——后者的「与当前安装版本一致」是一句无人守护的断言。

#### Scenario: 点名的接口已不存在

- **WHEN** 策展清单点名 `ICircle`，而升级后的 `.d.ts` 中已无此接口
- **THEN** 脚本以非零码退出，报告接口名与查找路径

#### Scenario: 点名的字段已改名或删除

- **WHEN** 策展清单点名 `ICircle.radius`，而升级后该字段已改名为 `r`
- **THEN** 脚本以非零码退出，报告 `ICircle.radius` 不存在

#### Scenario: 新增字段被强制发现

- **WHEN** 升级后 `ICircle` 新增 `opacity` 字段且无 TSDoc，而清单已将其纳入展示范围
- **THEN** 脚本以「缺说明」失败，迫使维护者为其补写覆盖或将其移出清单

### Requirement: 覆盖层与源并存时输出中性提示

当覆盖层某条目对应的字段在源 `.d.ts` 中同样带有 TSDoc，脚本 MUST 输出提示，告知两者并存、
当前采用的是人写版本。该提示 MUST NOT 使脚本失败，且 MUST NOT 表述为「可删除」——
是否改用上游文本需逐条判断，脚本无从代劳。

早期设计将此提示定为「该覆盖已冗余可删」，其前提是上游 TSDoc 总是更优。实测证伪：19 个 hook
中 6 个两者兼有，其中 4 条人写版更适合橱窗（面向使用者），2 条上游版更完整准确。
故提示由待办降级为告知。

#### Scenario: 上游也有 TSDoc

- **WHEN** heitu 为 `ICircle.border` 补写了 TSDoc，而覆盖层仍保留人工说明
- **THEN** 脚本正常生成并采用人工说明，同时提示两者并存供人复核

### Requirement: 生成物与手写物分离

策展清单与覆盖层 MUST 位于独立于生成物的文件。生成脚本 MUST NOT 写入手写文件。
生成物 MUST 标注为脚本产物、不得手改，沿用 `app/fonts.css` 的既有约定。

合并两者会导致人工补写的说明在下次执行脚本时被覆盖丢失。

#### Scenario: 重复执行不损坏手写内容

- **WHEN** 维护者在手写文件补充若干覆盖条目后再次执行生成脚本
- **THEN** 手写文件逐字节不变，仅生成物被覆写

### Requirement: 数据源限定为已安装的 npm 包

生成脚本 MUST 从 `node_modules/heitu/dist/**/*.d.ts` 读取类型信息，MUST NOT 引用同级仓库
`../heitu-platform` 的源码。

peco-platform 在容器内构建（`Dockerfile` 仅 `COPY . .`），隔壁仓库在该环境中不存在；
且 npm 包版本与 `package.json` 锁定一致，天然对齐所展示的版本。

#### Scenario: 隔壁仓库不可达的环境

- **WHEN** 在不存在 `../heitu-platform` 的环境（如容器构建）中执行生成脚本
- **THEN** 脚本正常完成，不产生任何路径错误

### Requirement: hooks 以函数签名呈现而非字段表

hooks 这一 tab 的表 MUST 每行呈现一个 hook 的「函数名 / 签名 / 说明」，MUST NOT 展开各 hook 入参
选项接口的字段。19 个 hook 是各自独立的 `declare function`，散在 `hooks/useXxx/index.d.ts` 中，
不存在共同的宿主接口，因此策展清单对该 tab MUST 使用函数形态而非接口成员形态。

展开入参接口会使该 tab 体量失控（19 个 hook 各自的 options），且偏离橱窗对该节的承诺——
读者要知道的是「有哪些 hook、怎么调用」，而非每个可选参数的详解。

#### Scenario: 渲染 hooks 表

- **WHEN** 渲染 hooks tab
- **THEN** 每行是一个 hook 的名称、完整调用签名与中文说明，页面上不出现 `Options` 一类入参接口的字段展开

#### Scenario: 清单使用了错误的形态

- **WHEN** 策展清单为 hooks tab 使用接口成员形态，或为普通接口使用函数形态
- **THEN** 生成脚本以非零码退出，指明该 group 的标题与形态不匹配的原因

### Requirement: 外部类型的继承不予展开

子类型的字段表 MUST 只列自有字段，其继承字段 MUST NOT 逐条展开——无论继承自 heitu 之外的
类型（如 antd 的 `FormProps`），还是 heitu 内部的基础配置类型，一律以一行文字标明继承来源。

`IFormRenderProps extends FormProps` 展开会带入 antd 的数十个字段；四种图表均
`extends IChartConfig`，展开会使同十余行内容重复四遍。

#### Scenario: 继承自外部库

- **WHEN** 渲染 `IFormRenderProps` 的字段表
- **THEN** 只列出 demo 演示过的自有字段（如 `config`、`form`、`gutter`），并标明其余继承自 antd `FormProps`；
  未被演示的自有字段（`isSub`、`extra`）依前一条 Requirement 的策展边界不列入，可在表脚注明其存在

#### Scenario: 继承自内部基类

- **WHEN** 渲染四种图表的字段表
- **THEN** 各表仅列自有字段（如折线图的 `xField`、`yField`、`smooth`、`point`），
  `IChartConfig` 的公共字段另置一张「图表通用配置」表，全站只出现一次
