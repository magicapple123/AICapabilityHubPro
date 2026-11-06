# -*- coding: utf-8 -*-
"""opsdemo 演示数据 · 对话会话内容（第 1~22 个会话，capability_id=1）。

每个会话是一个 dict：
    key       : 稳定标识，仅用于脚本内部校验
    topic     : 主题分类（用于统计，不入库）
    rounds    : [(user 消息, assistant 回复), ...]
    degraded  : 需要标记为降级的轮次（1 基），该轮 assistant 内容由脚本替换为兜底文案

约定：rounds 的条数就是该会话的调用次数（每次 user 消息对应一条 chat-completions 账单）。
"""

SESSIONS_A = [
    {
        "key": "S01",
        "topic": "平台计费与对账",
        "rounds": [
            (
                "对账时发现同一分钟里有两条 chat-completions 的扣分，金额都是 5，这算重复扣费吗？",
                "先比 request_id：两笔的 request_id 不同，就说明是两次独立请求，不是重复扣费。常见来源三类，一是前端失败重试，用户连点了两次发送；二是网关超时重试，上游其实已经执行成功了；三是多轮会话里连续追问，本来就各算一次。核对办法是把这两条记录的 request_id 拿去 t_points_log 对上，一条账单对应一条流水，金额和时间完全一致就不会多扣。如果确认是网关重试造成的，建议在网关侧把幂等键打开，用同一个 requestId 往下游透传，重复请求直接返回上一次结果，不再产生新账单。",
            ),
            (
                "要，顺手按 request_id 排序，先看 10 月 25 号之后的。",
                "给你一条能直接跑的，按 3 秒内同用户同能力成对出现来捞：\n\n```sql\nSELECT a.request_id AS req_a, b.request_id AS req_b,\n       a.capability_id, a.cost,\n       TIMESTAMPDIFF(SECOND, a.create_time, b.create_time) AS gap_sec\nFROM billing_db.t_call_record a\nJOIN billing_db.t_call_record b\n  ON a.user_id = b.user_id AND a.capability_id = b.capability_id\n AND b.create_time > a.create_time\n AND b.create_time <= a.create_time + INTERVAL 3 SECOND\nWHERE a.user_id = 8 AND a.is_deleted = 0 AND b.is_deleted = 0\nORDER BY a.request_id;\n```\n\n结果为空就说明没有成对的重试记录，可以放心结账。如果有成对的行，再拿 req_b 去 t_points_log 看它到底扣没扣分：扣了就是真重复，没扣就只是账单落库两条、积分只动了一次。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S02",
        "topic": "OpenAI 兼容接入",
        "rounds": [
            (
                "openai 的 SDK 指到我们网关，base_url 写到 /v1 还是完整路径？",
                "只写到 /v1。SDK 内部会自己拼 /chat/completions，你把完整路径塞进 base_url 就会变成 /v1/chat/completions/chat/completions，直接 404。\n\n```python\nimport os\nfrom openai import OpenAI\n\nclient = OpenAI(\n    base_url=\"http://127.0.0.1/api/v1\",\n    api_key=os.environ[\"AIHUB_SECRET_KEY\"],\n)\nresp = client.chat.completions.create(\n    model=\"ds-vision\",\n    messages=[{\"role\": \"user\", \"content\": \"介绍一下这个能力\"}],\n)\nprint(resp.choices[0].message.content)\n```\n\nmodel 这一栏填的是能力上的 openai_alias，不是上游真实模型名。网关拿到 alias 之后去目录表反查能力、算出 capability_id，再决定走哪个 provider_alias。所以 alias 是外部契约，provider_alias 是内部实现，两者故意分开，换供应商的时候不用通知客户改代码。",
            ),
            (
                "那把 alias 从 ds-vision 改成别的，是不是要重启网关？",
                "不用重启。alias 是运行时查目录表拿的，网关侧有 30 秒的本地缓存，改完最多等半分钟生效。要立刻验证可以连续发两次请求，第二次就能看到新路由。真正需要重启的情况只有一种：改了网关自己的路由前缀，比如 /v1 换成 /openai，那属于配置项，得走配置中心的发布流程。另外提醒一句，alias 全局唯一，你已经有一个叫 ds-vision 的在用，改之前先查一下有没有重复，重复会让反查结果不确定。",
            ),
            (
                "明白了，那 401 和 403 分别是什么原因？",
                "401 是身份问题：key 不存在、key 被禁用、key 过期，或者 secret 算出来的哈希对不上。403 是权限问题：身份没问题，但这个能力当前不给你用，通常是能力 status 不是 online，或者 exposed_to_market 关着。所以排查顺序是先看 401 还是 403，401 就去 t_api_key 查 access_key 和 status、expire_time；403 就去 t_capability 查 status 和 exposed_to_market。还有一种容易误判的：401 里带 invalid_api_key 的是 key 本身不对，带 missing_authorization 的是请求头没带，这两种要分开回答客户。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S03",
        "topic": "错误码排查",
        "rounds": [
            (
                "调用记录里 401 和 403 混着出现，怎么快速区分是 key 的问题还是能力没上架？",
                "看错误体里的 error.code，我们的兼容口是按 OpenAI 的格式回的错误，所以能直接判：\n\n```json\n{\n  \"error\": {\n    \"message\": \"capability is not available for this key\",\n    \"type\": \"permission_error\",\n    \"code\": \"capability_not_exposed\",\n    \"request_id\": \"6f1c2a3e-9b7d-4c1a-8f22-5d0e7b3a9c41\"\n  }\n}\n```\n\ncode 是 capability_not_exposed 或 capability_offline 就归 403，直接去目录页看那个能力的上架状态；code 是 invalid_api_key、api_key_expired、api_key_disabled 就归 401，去 API Key 页面看状态和过期时间。把 request_id 一起带上，客服拿这个就能复现。我今天已经把这两种情况的回复话术也统一了，401 让客户自助检查，403 走我们这边开权限。",
            ),
            (
                "那 failed 的调用要不要算进日用量？",
                "不看 failed，我们的口径分三层：failed 是请求没进到上游就失败了，不计费也不计调用次数；degraded 是上游不可用、我们返回了兜底内容，计一次调用但不计费用；success 是正常计一次调用也计费用。落到 t_usage_daily 上就是 call_count 里包含 degraded 但不包含 failed，total_cost 只累加实际扣费。这样客户看到的「今日调用次数」和账单条数会对不上一点点，差的就是失败那部分，报表页脚有一行小字解释这个口径，避免商务被追问。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S04",
        "topic": "限流与熔断",
        "rounds": [
            (
                "网关限流调到 20 QPS 之后，突发流量还是能打穿到上游，是限流没生效吗？",
                "限流大概率生效了，问题在粒度和形状。第一，如果网关是多副本，本地令牌桶是每副本 20 QPS，三个副本实际就是 60，得上移到 Redis 做全局限流。第二，令牌桶允许 burst，桶容量设成 20 的话，瞬时 40 个请求也能过，要把 burst 压到 5 以内，或者直接换成滑动窗口计数。第三，上游的真实瓶颈往往不是 QPS 而是并发数，模型推理占着连接不放，20 QPS 打过去可能变成 60 个并发，这时候要在网关加信号量，把同时在飞的请求数卡在 8 到 10 之间。先加并发控制，再谈 QPS 数值。",
            ),
            (
                "那熔断阈值按什么定？错误率还是响应时间？",
                "以错误率为主，响应时间做辅助。错误率用滑动窗口统计，窗口 30 秒、最小请求数 20，错误率超过 50% 打开熔断；只用一个比例会误伤低流量时段，所以必须带最小请求数门槛。响应时间用 p99 做辅助阈值，比如 p99 超过 8 秒持续 30 秒也打开，因为模型侧卡住的时候往往先表现为慢，然后再变成超时错误。半开状态给 10 秒，放 3 到 5 个探测请求，全部成功才闭合，部分成功继续半开，全失败重新计时。阈值别拍脑袋，等积累一周真实数据再调。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S05",
        "topic": "提示词与文生图",
        "rounds": [
            (
                "文生图的提示词老是画歪，加 negative prompt 有用吗？",
                "有用，但顺序比 negative 更关键。正向提示词按「主体 → 环境 → 光照 → 构图 → 画风」排，主体放最前面，权重最高，写得越具体越好，比如「三位穿深色西装的人围坐在长桌旁」比「一群人开会」稳定得多。negative 只写真正要排除的，比如「文字、水印、多余的手指」，别堆一大串，堆多了模型会分不清主次。还有两个实操点：一是尺寸跟构图要对上，竖构图别用横图比例；二是同一句提示词多跑几次挑结果，采样本来就有随机性，不是提示词写错了。",
            ),
            (
                "把刚才那个酒店大堂的例子改成竖版 3:4，方便放手机海报？",
                "",
            ),
        ],
        "degraded": [2],
    },
    {
        "key": "S06",
        "topic": "周报与汇报文案",
        "rounds": [
            (
                "本周迭代记录：完成调用记录分页修复、补齐降级状态展示，帮我写成周报。",
                "本周迭代周报\n\n一、已完成\n1. 调用记录分页修复：定位到深分页 offset 过大导致的慢查询，改为基于 create_time 的游标翻页，翻到底页的响应时间从 2.1 秒降到 180 毫秒。\n2. 降级状态展示：账单列表和详情页都加了 degraded 标识，并补了一句说明文案，客服不用再靠人工解释。\n\n二、进行中\n能力目录的 alias 重复校验，已完成后端接口，前端提示待联调。\n\n三、风险与依赖\n降级判定的口径还需要和财务确认一次，目前是计次不计费，如果财务要求计费需要改结算逻辑。\n\n四、下周计划\n文生图能力上架、调用记录导出、目录 alias 校验前端收尾。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S07",
        "topic": "竞品调研",
        "rounds": [
            (
                "竞品调研的对比表要抓哪几个维度？我要拿去跟商务对口径。",
                "建议固定这八个维度，多一个都别加，加了商务也不会看：\n\n| 维度 | 说明 | 为什么重要 |\n| --- | --- | --- |\n| 计费单位 | 按次 / 按千 token / 按秒 | 决定客户怎么估预算 |\n| 最小计费粒度 | 一次起算还是按量累计 | 小额调用的成本差异全在这 |\n| 赠送额度 | 注册赠送、试用期 | 直接影响拉新话术 |\n| 超限策略 | 拒绝、降级、自动充值 | 客户最怕半夜被掐断 |\n| 结算周期 | 预充值 / 后付费 | 决定要不要签框架合同 |\n| 并发上限 | 是否按套餐分层 | 大客户必问 |\n| 退款规则 | 是否可退、退多少 | 采购流程会卡这里 |\n| 发票与合规 | 专票、等保 | 决定能不能进国企 |\n\n我们自己的位置很清楚：按次计费、注册送 100、超限拒绝不自动扣，比按 token 的平台更容易被非技术客户理解，但单价看起来偏高。跟商务对齐时重点讲总拥有成本，别陷入单价比较。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S08",
        "topic": "SQL 与数据分析",
        "rounds": [
            (
                "帮我写个 SQL，按天和 capability_id 统计调用次数和费用，只要 opsdemo 这个账号。",
                "```sql\nSELECT DATE(create_time) AS stat_date,\n       capability_id,\n       COUNT(*) AS call_count,\n       SUM(cost) AS total_cost\nFROM billing_db.t_call_record\nWHERE user_id = 8 AND is_deleted = 0\nGROUP BY DATE(create_time), capability_id\nORDER BY stat_date, capability_id;\n```\n\n用 DATE(create_time) 分组就行，不用去 join 日用量表，账单是事实表，日用量是它的物化结果，核对的时候两边应该完全一致。加 is_deleted = 0 是必须的，否则软删的记录会被算进去。",
            ),
            (
                "再加一列，每天的平均单次费用，保留两位小数。",
                "在 SELECT 里加一列就行，分子分母都用聚合值，别再套一层子查询：\n\n```sql\nSELECT DATE(create_time) AS stat_date,\n       capability_id,\n       COUNT(*) AS call_count,\n       SUM(cost) AS total_cost,\n       ROUND(SUM(cost) / COUNT(*), 2) AS avg_cost\nFROM billing_db.t_call_record\nWHERE user_id = 8 AND is_deleted = 0\nGROUP BY DATE(create_time), capability_id\nORDER BY stat_date, capability_id;\n```\n\n注意 COUNT(*) 里包含降级记录，它的 cost 是 0，所以降级多的日子平均单价会被拉低，这是真实的算术结果，不是算错。如果想让平均单价只反映成功调用，把分母换成 SUM(cost > 0) 即可。",
            ),
            (
                "把结果按费用从高到低排，取前 8 天。",
                "那就不能按天分组了，得先按天汇总再排序：\n\n```sql\nSELECT DATE(create_time) AS stat_date,\n       COUNT(*) AS call_count,\n       SUM(cost) AS total_cost\nFROM billing_db.t_call_record\nWHERE user_id = 8 AND is_deleted = 0\nGROUP BY DATE(create_time)\nORDER BY total_cost DESC\nLIMIT 8;\n```\n\nLIMIT 要放在排序之后，MySQL 的执行顺序是 GROUP BY 完了才 ORDER BY，所以这里 LIMIT 8 取的是费用最高的 8 天。想同时保留能力维度的话，把 ordering 改成窗口函数 ROW_NUMBER() OVER (ORDER BY SUM(cost) DESC) 再过滤 <= 8 也行，但这里没必要。",
            ),
            (
                "降级的那些记录会被算进去吗？",
                "会算进 call_count，不会算进 total_cost。降级的成本字段写的就是 0，SUM 自然不受影响，但 COUNT(*) 会把它数进去。如果你要的是纯成功调用，两种写法：COUNT(CASE WHEN call_status = 'success' THEN 1 END)，或者 COUNT(IF(cost > 0, 1, NULL))。前一种语义更清楚，建议统一用 CASE 写法，别用 IF 混着来。我这边报表页的「调用次数」用的是含降级的口径，跟 t_usage_daily 保持一致，避免两个页面数字对不上。",
            ),
            (
                "那我想看每个能力占总费用的比例，用窗口函数怎么写？",
                "用 SUM() OVER () 拿总计，再相除：\n\n```sql\nSELECT capability_id,\n       SUM(cost) AS total_cost,\n       ROUND(100 * SUM(cost) / SUM(SUM(cost)) OVER (), 2) AS pct\nFROM billing_db.t_call_record\nWHERE user_id = 8 AND is_deleted = 0\nGROUP BY capability_id\nORDER BY total_cost DESC;\n```\n\n关键点是 SUM(SUM(cost)) OVER ()：里层 SUM 是分组聚合，外层 SUM 是把它当窗口再求和，MySQL 8 支持这种写法。如果觉得绕，写两个子查询也一样，只是多扫一次表。注意这里 GROUP BY 之后窗口函数没有 PARTITION BY，算的是全局总计，正好是你要的分母。",
            ),
            (
                "结果能直接给 BI 同学吗？列名要改成中文别名。",
                "可以，列名用 AS 起中文别名，注意中文别名不要加引号也能跑，但为了避免不同客户端解析差异，建议用反引号包起来：\n\n```sql\nSELECT capability_id AS `能力ID`,\n       COUNT(*) AS `调用次数`,\n       SUM(cost) AS `费用合计`,\n       ROUND(100 * SUM(cost) / SUM(SUM(cost)) OVER (), 2) AS `费用占比`\nFROM billing_db.t_call_record\nWHERE user_id = 8 AND is_deleted = 0\nGROUP BY capability_id\nORDER BY SUM(cost) DESC;\n```\n\n给 BI 的话再补一句：我们的 cost 单位是积分，不是元，1 积分不等于 1 分钱，汇率在结算模块里，别让他们直接乘。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S09",
        "topic": "能力上架字段检查",
        "rounds": [
            (
                "能力上架前要检查哪些字段？我想整理成一张 checklist。",
                "按这个顺序过一遍，全绿再点上线：\n\n| 字段 | 检查点 | 常见坑 |\n| --- | --- | --- |\n| code | 全局唯一、小写中划线 | 和已有能力撞了会路由错 |\n| category_id | 分类存在且启用 | 分类被停用后能力挂不上去 |\n| price_per_call | 与目录评审结论一致 | 少写一个 0 或者单位搞错 |\n| billing_mode | 现在是 per_call | 混用会让账单出现空单价 |\n| executor | 和执行链里的名字对齐 | 拼错就是 500 |\n| provider_alias | 至少在供应商表里 enabled | 填了 draft 供应商会全量失败 |\n| openai_alias | 唯一、不含斜杠 | 重复会导致反查不确定 |\n| max_output_tokens | 不超过上游上限 | 超了上游截断，用户以为是 bug |\n| exposed_to_market | 关闭时市场接口不返回 | 试运行阶段要关掉 |\n| status | draft → online | 直接写 online 会跳过校验 |\n\n最后一条最容易被忽略：一定要按 draft → online 的顺序走，直接从库里把 status 改成 online，前端能看到但没有跑过校验，出问题很难回溯。",
            ),
            (
                "exposed_to_market 和 status 两个字段的区别是什么？",
                "status 是能力自己的生命周期，draft 是还没配好、online 是对外可调用、offline 是主动下线；exposed_to_market 是市场可见性，只影响「能力市场」页面和 openai 兼容口的 alias 反查，不影响直接按 capability_id 调用。举个实际场景：文生图还在内部试运行，status 设成 online 让内部能调，exposed_to_market 设成 0 让市场页看不到，等商务定完价再打开。反过来只开 exposed 不开 online 是不允许的，市场页会显示一个点了就报错的能力，这种配置我们上线前会拦掉。",
            ),
            (
                "刚才那张表能不能按「必填/选填」再分一列？",
                "可以，重新给你一版，加一列必填属性：\n\n| 字段 | 必填 | 检查点 |\n| --- | --- | --- |\n| code | 是 | 全局唯一、小写中划线 |\n| name | 是 | 不超过 64 字，客户可见 |\n| category_id | 是 | 分类存在且启用 |\n| price_per_call | 是 | 与目录评审结论一致 |\n| billing_mode | 是 | 暂只支持 per_call |\n| executor | 是 | 与执行链名字对齐 |\n| provider_alias | 是 | 供应商必须 enabled |\n| openai_alias | 否 | 唯一、不含斜杠 |\n| max_output_tokens | 否 | 默认 1024，不超过上游上限 |\n| exposed_to_market | 否 | 默认关闭，试运行必须关 |\n| description | 否 | 512 字以内，写清输入输出 |\n\n必填的意思是没有它能力根本跑不起来，选填是缺了也能跑但体验差。description 我归到选填，但实际审核时没写清楚会被打回，所以别真当可选项。",
            ),
            (
                "openai_alias 如果填了重复的会怎么样？",
                "不会报错，这才是麻烦的地方。目录表对 openai_alias 没有唯一约束，因为它是可空的，加了唯一约束多个 NULL 又会冲突。所以重复时反查走的是「查到的第一行」，取决于执行计划，今天可能命中这个词明天命中那个，表现就是同一个 model 名字偶尔路由到不同能力，账单上的 capability_id 跟着乱跳。规避办法是上线前跑一条自检 SQL：按 openai_alias 分组，count 大于 1 且 alias 非空的直接列出来。要不要我把这条加进发布检查清单，以后每次发版自动跑？",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S10",
        "topic": "Docker 与部署",
        "rounds": [
            (
                "docker compose 起网关，改了 .env 之后容器里还是旧的 JWT_SECRET，为什么？",
                "因为环境变量是在容器创建时注入的，改 .env 只影响下一次「创建」，restart 只是重启进程，环境还是老的。两种办法：一是 docker compose up -d 让 compose 检测到配置变化重建容器；二是 docker compose up -d --force-recreate 网关这一个服务强制重建。注意千万别只 down 掉整个栈再 up，会把 MySQL 数据卷之外的东西全重启，联调中的其他同学会被打断。另外确认一下 .env 放在 compose 文件同级目录，compose 只自动读它自己目录下的 .env。",
            ),
            (
                "那要 down 再 up 吗，还是 restart 就够？",
                "都不是最优。restart 不刷新环境变量，down 再 up 会把整个栈停掉太粗暴。正确做法是 docker compose up -d <服务名>，compose 会比对镜像和环境变量，有变化就重建这一个容器，其他容器不动。如果你改了 Dockerfile 或者挂载卷，得先 docker compose build <服务名> 再 up -d。验证是否真的重建了，看 docker ps 的 CREATED 时间，是几十秒前就对了；如果还是几小时前，说明 compose 认为没变化，检查一下变量名有没有拼错。",
            ),
            (
                "已经有别的容器占了 3307，我改宿主端口会不会影响容器内互连？",
                "不影响。宿主端口映射只决定「从宿主机怎么访问」，容器之间走的是 docker 网络的容器端口 3306，跟 3307 没关系。所以把 compose 里的 ports 从 3307:3306 改成 3308:3306 之后，容器内其他服务连 mysql:3306 依然通，只有你在宿主机用客户端连的时候要改成 3308。容易踩的坑是有人顺手把容器端口也改了，那就真连不上了。改完记得把 .env 和本地客户端连接串一起同步，别留一处旧的。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S11",
        "topic": "Git 与协作",
        "rounds": [
            (
                "同事把一个功能分支 rebase 到 main 之后，我本地的同名分支推不上去，怎么处理？",
                "因为 rebase 重写了提交哈希，你本地还是旧的历史，远端已经换了一套，所以 push 被拒。先确认一件事：这个分支上有没有只有你本地才有的提交。有的话先 git branch backup-xxx 存一份，再 git fetch origin 然后 git reset --hard origin/分支名，最后把你备份分支里的提交 cherry-pick 回来。没有本地独有提交就直接 reset --hard 跟上远端。整个过程不要用 git push -f 往别人也在用的分支上覆盖，那会直接把同事的提交冲掉。",
            ),
            (
                "那 force-with-lease 和 force 的区别？",
                "force 是无条件覆盖远端，你在执行的那一瞬间，如果远端刚被别人推了新提交，那些提交会直接丢掉，而且找不回来。force-with-lease 会先比对远端的当前值和你的本地记录，不一致就拒绝推送，等于帮你挡掉了「别人抢先推了」这种情况。所以只要必须强推，一律用 --force-with-lease，它是安全的那个。养成习惯：命令历史里出现 --force 单独用的时候，先停下来问一句这是不是自己的分支。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S12",
        "topic": "接口契约",
        "rounds": [
            (
                "chat/completions 的请求体我们自己加了 session_id，会不会破坏 openai 兼容性？",
                "不会，OpenAI 兼容的核心是「标准字段必须按标准解析」，多出来的字段客户端不传、服务端不认就忽略，属于向前兼容的常规做法。前提是标准字段一个都不能少，model、messages 必须有，stream 按需。反过来要小心的是响应体，响应里如果多塞了非标准字段，严格的 SDK 一般会忽略，但个别版本会做严格校验，所以扩展字段统一放在顶层一个 x_ext 对象里，别散落在 choices 或 usage 里面，最安全。",
            ),
            (
                "那我在文档里怎么标这些扩展字段？",
                "用 OpenAPI 的 x- 前缀，这是规范里留给厂商的自定义位置：\n\n```json\n{\n  \"x-aihub\": {\n    \"session_id\": {\n      \"type\": \"integer\",\n      \"required\": false,\n      \"description\": \"多轮会话 ID，不传则每次请求视为独立会话\"\n    },\n    \"capability_hint\": {\n      \"type\": \"string\",\n      \"required\": false,\n      \"description\": \"按能力 code 直接路由，优先级高于 model\"\n    }\n  }\n}\n```\n\n这样生成出来的文档会把扩展字段单独归到一节，不会和标准字段混在一起让客户误以为是官方参数。另外在文档顶部加一句说明：本平台在 OpenAI 标准之上增加了少量可选扩展，不传时行为与官方完全一致。",
            ),
            (
                "如果客户端传了不认识的字段，网关是忽略还是报错？",
                "忽略。这是兼容性的底线，报错会让所有带自定义参数的客户端直接不可用，比如有些 SDK 会自动带上 extra_body。但忽略不等于不管，我们会在网关打一条 warn 日志，把不认识的字段名记下来，一周看一次频次，出现次数多的说明客户有真实需求，可以考虑正式支持。要拦住非法请求靠的是必填字段校验和类型校验，不是靠「不许多传」。",
            ),
            (
                "建议忽略但记日志，这个日志放在哪一层比较合适？",
                "放网关的请求解析之后、路由之前。原因有三：一是在这一层拿得到完整原始请求体和解析后的对象，能精确算出哪些字段被丢了；二是这一层已经有 request_id，日志能串起来；三是不用改下游服务，chat 服务完全无感。实现上给一个白名单，白名单之外且不在 x-aihub 里的键都记一条 warn，日志内容只记键名不记值，避免把客户业务数据落进日志。",
            ),
            (
                "上面那个响应结构里 usage 的字段名要不要跟官方完全一致？",
                "必须完全一致，prompt_tokens、completion_tokens、total_tokens 这三个名字不能改，改了所有按 token 做统计的客户端都会算错。我们的扩展需求放在同级的一个对象里，比如带上 token_source 说明这次统计是上游给的还是本地估的。另外注意一个细节：如果某次调用降级了，usage 里要么给全 0，要么整个 usage 不返回，别返回 null 字段，很多客户端会对 null 做算术然后崩掉。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S13",
        "topic": "活动与公告文案",
        "rounds": [
            (
                "双十一给新用户送 100 积分的公告，写 80 字以内，别太硬。",
                "新用户注册即赠 100 积分，可用于多轮对话、长文本摘要、视觉理解等全部已上架能力，按次结算，用多少扣多少，积分不设有效期。\n\n正文 62 字，把赠送额度和计费方式一次说清，重点是别让用户以为积分按时间消耗。如果还想强调活动属性，末尾再加一句「活动期间注册额外加赠」也可以，加完仍在 80 字以内。",
            ),
            (
                "语气再收一点，去掉感叹号，面向企业客户。",
                "新用户注册后可获赠 100 积分，用于试用平台已上架的能力。计费按次结算，每次调用前可在控制台查看单价，不存在超额扣费。试用期间可凭积分完成接入联调与效果验证，无需先行采购。如需正式接入，可联系商务获取专属报价与技术支持。\n\n这版 111 字，去掉了感叹号和促销语气，更适合作为发给企业客户的技术邮件正文。要不要再出一版更短的，只留赠送额度和结算方式两句？",
            ),
            (
                "加一句活动时间和库存有限的说明，但不要制造焦虑。",
                "本次赠送活动自 11 月 1 日起，至 11 月 11 日 24 时结束。积分池按日投放，当日额度用尽后次日恢复，建议注册后尽快完成首次调用验证。活动结束后注册的新用户仍保留基础赠送额度，具体以控制台展示为准。已获赠的积分不受活动结束影响，可继续使用至消耗完毕。\n\n关键是把「额度用尽」写成「次日恢复」，用户不会觉得被拒之门外，同时也有了尽快行动的理由，不需要用「仅剩」这类词。",
            ),
            (
                "再给一版放在短信里的，40 字以内，不要链接。",
                "【能力中枢】注册得100积分，可试用对话与文生图，11月11日截止，回TD退订。\n\n整条 40 字（含签名），正好卡在上限内，落在 70 字的单条计费档里不会拆条。链接故意去掉了，引导用户自己进控制台，这样能省掉一条跳转链接的合规报备，也降低被判成营销短信的概率。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S14",
        "topic": "事故复盘",
        "rounds": [
            (
                "昨晚 21:40 到 21:55 有一批调用报 502，帮我按复盘模板理一下责任边界。",
                "按复盘模板的四段来写，责任边界只写系统行为，不写人名：\n\n一、现象\n21:40:12 起网关开始返回 502，持续到 21:54:38，累计影响 47 次调用，失败集中在 chat-completions 能力。\n\n二、直接原因\n上游供应商在 21:39 触发限流，返回 429，网关的重试策略是固定间隔重试 3 次，重试放大了请求量，把上游的限流窗口彻底打满，最终表现为网关侧连接被占满、后续请求拿不到连接返回 502。\n\n三、处置\n21:47 关闭网关重试开关，21:49 上游限流解除，21:54 连接数恢复。\n\n四、责任边界\n网关侧的问题是重试策略缺退避和熔断，属于设计缺陷；上游的问题是限流阈值调整没有提前通知。两侧都需要改进，主责在网关。",
            ),
            (
                "时间线里网关和上游的重试次数怎么算？",
                "按实际发出的下游请求数算，不要按用户请求数算。用户侧是 47 次请求，网关重试 3 次意味着最坏情况放大到 4 倍，实际下游收到 168 次左右，这个数字要从上游的访问日志里取，别用估算。时间线里写清楚三列：时刻、动作、下游累计请求数。复盘里最容易含糊的就是这一段，写「大量重试」等于没写，写「21:41 至 21:47 期间下游累计收到 168 次请求，其中 121 次被上游以 429 拒绝」，别人才看得懂问题有多大。",
            ),
            (
                "补一条改进项：网关侧重试要不要加最大次数和退避？",
                "",
            ),
        ],
        "degraded": [3],
    },
    {
        "key": "S15",
        "topic": "测试用例",
        "rounds": [
            (
                "给积分扣减写一批测试用例，覆盖并发和余额不足。",
                "按这几个场景铺开，用例名直接写清前置条件：\n\n| 用例 | 前置 | 期望 |\n| --- | --- | --- |\n| 正常扣减 | 余额 100，单价 5 | 扣 5，余额 95，流水 1 条 |\n| 余额刚好等于单价 | 余额 5，单价 5 | 扣 5，余额 0，成功 |\n| 余额不足 | 余额 4，单价 5 | 拒绝，余额不变，无流水 |\n| 并发扣减 | 余额 100，10 并发各扣 5 | 余额 50，10 条流水余额链连续 |\n| 并发打穿 | 余额 15，10 并发各扣 5 | 只有 3 次成功，余额 0 |\n| 重复请求 | 同一 request_id 提交两次 | 第二条幂等返回，不重复扣 |\n\n最关键是并发打穿那条，一定要用真实并发压，串行跑永远暴露不了问题。实现上靠的是扣减语句带 balance >= amount 条件，看影响行数。",
            ),
            (
                "余额刚好等于单价的边界，算成功还是失败？",
                "算成功，余额正好扣到 0。判断条件是 balance >= amount，等号成立时允许扣。这条要在代码评审时特别强调，因为很容易被写成 balance > amount。风险在于余额 0 之后用户的后续调用全部失败，所以产品上要有一层提醒：余额低于 10 的时候在控制台挂个提示条，低于 5 的时候给用户发一条站内提醒。技术上还有一点，余额 0 的账户要不要自动冻结，目前是不冻结，靠调用时校验拦，因为冻结会让充值后的解冻流程变复杂。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S16",
        "topic": "用户访谈整理",
        "rounds": [
            (
                "整理了三条用户访谈原话，帮我提炼成需求点：一图要能直接贴到工单里；二希望知道每次调用花了多少；三不想每次都新建会话。",
                "提炼成三条可落地的需求，按优先级排：\n\n1. 调用结果可导出为可粘贴的图片。这条实际诉求不是「生成图片」，而是「能贴进外部系统」，所以要做的是结果卡片的一键复制和保存为 PNG，而不是加导出报表。优先级高，实现成本低。\n2. 单次调用费用可见。现在费用只在账单列表里，用户要跳两次页面。改成在对话页每条回复下面挂一行小字「本次消耗 5 积分」，成本几乎为零，用户感知很强。优先级最高。\n3. 会话持久化。用户说「不想每次新建」，本质是希望刷新页面后能接着聊，而不是真的要多开。先确认现在是不是刷新就丢上下文，如果丢，那是 bug 不是需求。",
            ),
            (
                "第二条能不能拆成两个需求？",
                "能拆，而且应该拆：\n\n需求 2a：单次调用的费用实时展示。在对话页回复下方展示本次消耗积分，数据来源是本次响应的账单，实时性要求秒级。\n需求 2b：费用的日/周汇总视图。在控制台首页给一个近七天的消耗趋势和分能力占比，数据来源是日用量表，天级更新即可。\n\n拆的理由是数据源和更新频率完全不同，2a 走实时链路、2b 走离线聚合，放一个需求里会被迫让其中一头妥协。落地顺序建议先做 2a，用户访谈里这条被提到的次数最多，而且不依赖任何新表。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S17",
        "topic": "积分与账务核对",
        "rounds": [
            (
                "账户余额和流水最后一条 balance_after 对不上，差 16 分，可能是什么原因？",
                "按概率从高到低排，先查这三种：一是流水里有记录被软删了，is_deleted 改成 1 之后余额没回滚，导致链断了；二是账户表在写入流水之后又被别的线程更新过，两个写操作不是同一事务，中间崩了；三是有历史数据迁移时把 balance 直接改过，没有配套流水。核对方法是从第一条流水开始，按 create_time 升序把 balance_after 逐条递推一遍，看第几条开始对不上，断点前的最后一条就是问题发生的位置。16 分这个数字很典型，5 加 3 加 8，正好是一次多轮对话加一次长文本摘要加一次视觉理解的合计，很可能是三次扣减被合并在一次写入里了。",
            ),
            (
                "如果是有条流水被软删了，版本号会对不上吧？",
                "对，version 通常等于流水条数，用来做乐观锁校验。软删一条之后流水少了 1，如果 version 没跟着减，之后每次扣减的 where version = ? 都会失败，表现就是用户无法调用、报乐观锁冲突。所以正确做法是软删流水的同一事务里把 version 也减 1、余额加回去。如果已经出问题了，别手工改 version，先把断点找出来，按金额和条数反算出正确的 version，写一条修数脚本，跑之前先备份这张表。这类修数一定要留审计记录，不然下次对账还是查不出来。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S18",
        "topic": "脚本自动化",
        "rounds": [
            (
                "写个 PowerShell，把 artifacts 下所有 sql 按修改时间倒序打印前 10 个。",
                "```powershell\n$root = 'D:\\AICapabilityHubPro\\artifacts'\nGet-ChildItem -Path $root -Recurse -Filter *.sql -File |\n    Sort-Object LastWriteTime -Descending |\n    Select-Object -First 10 @{ n = '时间'; e = { $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } },\n                            @{ n = '大小KB'; e = { [math]::Round($_.Length / 1KB, 1) } },\n                            FullName |\n    Format-Table -AutoSize\n```\n\n要点是用 -File 过滤掉目录，Select-Object 里用计算属性把时间格式化，默认的 DateTime 显示会有毫秒很难看。Format-Table 只适合看，如果要接着处理就别加它。",
            ),
            (
                "再加个 -Fresh 参数，只保留最近 3 个，其余删掉。",
                "```powershell\nparam(\n    [string]$Root = 'D:\\AICapabilityHubPro\\artifacts',\n    [switch]$Fresh\n)\n\n$files = Get-ChildItem -Path $Root -Recurse -Filter *.sql -File |\n    Sort-Object LastWriteTime -Descending\n\nif (-not $Fresh) {\n    $files | Select-Object -First 10 FullName, LastWriteTime | Format-Table -AutoSize\n    return\n}\n\n$files | Select-Object -Skip 3 | ForEach-Object {\n    Write-Host ('删除 ' + $_.FullName)\n    Remove-Item -LiteralPath $_.FullName -Force -Confirm:$false\n}\n```\n\n一定要用 -LiteralPath，路径里有方括号时 -Path 会当通配符解析。先不带 -Fresh 跑一遍看清单，确认了再加参数，别一上来就删。",
            ),
            (
                "Windows 上路径带空格会炸，怎么处理？",
                "三个地方要处理。一是调用原生命令时用调用运算符加引号，& \"C:\\Program Files\\App\\app.exe\" 参数；二是自己的函数参数一律用 [string] 类型并加引号传，PowerShell 在参数绑定阶段就会把空格保护住；三是 Get-ChildItem 这类 cmdlet 用 -LiteralPath，避免方括号和星号被当通配符。还有一个隐蔽的坑：用 Start-Process 时 -ArgumentList 是一个字符串数组，每个元素单独加引号，别拼成一个长字符串，拼了之后空格就变成参数分隔符了。",
            ),
            (
                "能不能顺便把行数也算出来？",
                "```powershell\n$files | Select-Object -First 10 | ForEach-Object {\n    $lines = (Get-Content -LiteralPath $_.FullName -ErrorAction SilentlyContinue | Measure-Object -Line).Lines\n    [pscustomobject]@{\n        时间   = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')\n        行数   = $lines\n        大小KB = [math]::Round($_.Length / 1KB, 1)\n        文件   = $_.Name\n    }\n} | Format-Table -AutoSize\n```\n\nGet-Content 会把整个文件读进内存，几十兆的 SQL 会慢，那种情况改用 [System.IO.File]::ReadLines() 逐行数，几乎不占内存。另外 Measure-Object -Line 数的是非空行，空行不算，如果你要物理行数得用 -Line 之外的办法，先确认一下口径再交给同事。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S19",
        "topic": "网关与反向代理",
        "rounds": [
            (
                "nginx 把 /api 转发到 gateway，SSE 流式返回被缓冲了，怎么改配置？",
                "在 location 块里加三行就够了：\n\n```nginx\nlocation /api/ {\n    proxy_pass http://gateway:8080/;\n    proxy_buffering off;\n    proxy_cache off;\n    proxy_http_version 1.1;\n    proxy_set_header Connection '';\n    chunked_transfer_encoding on;\n}\n```\n\n关键是 proxy_buffering off，另外必须把 Connection 头清空并显式用 HTTP 1.1，否则 nginx 默认 1.0 加 keepalive 会让上游一直等着凑包，表现就是前端一个字一个字地卡。还有一点容易漏：gzip 不能对 text/event-stream 生效，gzip_types 里别包含它。",
            ),
            (
                "proxy_buffering off 之后，日志里 upstream 响应时间变长了，正常吗？",
                "正常，但要看长多少。开缓冲时 nginx 拿到完整响应才记 upstream_time，关掉之后记的是首字节到末字节的真实时长，流式场景本来就长，所以数值变大是统计口径变了，不是变慢。判断是否真变慢要看首字节时间，也就是 upstream_header_time，这个指标不受缓冲开关影响，横向比较才有意义。如果 header_time 也涨了，那是上游本身慢了，跟 nginx 配置无关。",
            ),
            (
                "那 gzip 和 SSE 能一起开吗？",
                "技术上能开但不能这么用。gzip 是流式压缩，压缩器需要攒够一个压缩块才输出，event-stream 的每个事件都很小，攒的过程在客户端看来就是「卡住然后一次吐一大段」，把流式体验毁掉了。正确做法是 gzip 全局开、但把 text/event-stream 从 gzip_types 里排除，同时确认上游没有自己对响应体做压缩，两层压缩会直接乱码。如果你的场景确实要省带宽，考虑在应用层做逐事件压缩，别指望 http 层。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S20",
        "topic": "日志与链路追踪",
        "rounds": [
            (
                "同一个 requestId 在网关日志有，到了 chat 服务就丢了，怎么串起来？",
                "两种可能：要么网关没往下游传，要么 chat 服务的日志配置里没打这个字段。先看网关的代理配置有没有把 requestId 塞进请求头，一般用 X-Request-Id；再看 chat 服务的日志模板里有没有把这个头读出来放进 MDC。两处都补上之后，日志里搜一次就能串起来。另外建议网关在入口处就生成 requestId，如果客户端已经带了就沿用，这样客户端和我们看到的是同一个值，客服沟通成本最低。",
            ),
            (
                "trace_id 和 request_id 该怎么分工？",
                "request_id 是「一次业务请求」的标识，从网关入口生成，全链路透传，写进账单和审计，是给人查问题用的。trace_id 是「一次调用链」的标识，遵循 W3C 标准，可能一次业务请求里包含多个 span，是给 APM 做拓扑用的。两者不要合并：账单表里存 request_id 就够，别存 trace_id，因为账单是业务事实，不该依赖追踪系统；反过来 APM 里两者都记，方便从慢调用反查到具体是哪条账单。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S21",
        "topic": "需求评审",
        "rounds": [
            (
                "明天评审文生图这个需求，我该准备哪几个尖锐问题？",
                "五个问题，一个比一个难回答：\n\n1. 单次 20 积分的定价依据是什么？上游按张计费的实际成本是多少，毛利率能不能覆盖失败重试的成本？\n2. 出图失败怎么算钱？上游返回了 5xx 但已经计费的情况，我们是不扣还是有条件扣？需要明确到状态机层面。\n3. 生成的内容版权归属和审核责任怎么定？用户拿去做商用出了纠纷，责任在平台还是用户？\n4. 单张图的生成时长 9 到 28 秒，前端体验怎么做？是同步等还是先返回任务 ID 轮询？\n5. 有什么能力是「上了就下不来」的？比如一旦对客户承诺了 20 分一次，后面要调价会怎样？\n\n第 2 和第 5 个问题最容易在会上被含糊带过，但其实是最容易埋雷的，一定要在会上拿到明确结论。",
            ),
            (
                "第三条成本那块，把 20 分一次的成本模型说清楚点。",
                "按三块拆：一是上游直采成本，通义万相按张计费，一张大约几分钱，具体单价以采购合同为准；二是失败成本，上游超时或返回空图的比例按 5% 估，这部分我们也付了钱但用户拿不到图，如果不扣分就变成纯亏损；三是平台成本，存储图像和带宽，一张 1024 的图约 1 到 2 MB，存 30 天。三项加起来再乘一个目标毛利率，才是 20 分这个数字的来处。评审时建议把这三点直接写进需求文档的定价依据一节，避免以后有人问「为什么是 20 不是 15」时只有一个答案叫「拍脑袋定的」。",
            ),
        ],
        "degraded": [],
    },
    {
        "key": "S22",
        "topic": "监控指标口径",
        "rounds": [
            (
                "看板上的成功率是 99.2%，但调用记录里失败的只有 3 条，口径差在哪？",
                "分母不一样。看板的成功率是用「网关收到的请求数」做分母，包含了参数校验失败、鉴权失败这些根本没进账单的请求；调用记录只统计已经落到账单表的请求。所以两边差的就是「没进账单的那批」。先把看板的分母改成账单条数，两个数字立刻能对上。如果不想改，就在看板旁边标注一句「含未入账请求」，别让人拿两个口径的数字做除法。这种口径差在跨部门汇报时最容易被质疑，提前统一掉省事。",
            ),
            (
                "那降级的算成功还是失败？",
                "都不算，单独一类。监控上建议做成三色：success 绿、degraded 黄、failed 红。成功率的分母用全部请求，分子只算 success，这样降级会拉低成功率，符合它「用户没拿到真实结果」的本质。但现在看板把降级算进成功了，因为实现里判断的是「有没有抛异常」，降级没抛异常所以算成功，这是实现和口径没对齐。建议改成按 call_status 字段判断，别看异常。改完之后历史数据会跳一下，要在变化点做标记。",
            ),
        ],
        "degraded": [],
    },
]
